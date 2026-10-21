package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/sirupsen/logrus"
)

func overflowChunks(bodies ...string) []*types.Chunk {
	chunks := make([]*types.Chunk, len(bodies))
	for i, body := range bodies {
		chunks[i] = windowChunk(
			fmt.Sprintf("overflow-%d", i), i, fmt.Sprintf("%s%03d %s", longDocChunkMark, i, body),
		)
	}
	return chunks
}

func overflowResponse() *types.ChatResponse {
	return &types.ChatResponse{Content: `{"entities":[`, FinishReason: "length"}
}

func TestCandidateOverflowBalancesRebuiltRunes(t *testing.T) {
	for _, tc := range []struct {
		name   string
		bodies []string
		want   [][]int
	}{
		{
			"uneven chunks",
			[]string{
				strings.Repeat("a", 1500), strings.Repeat("b", 100),
				strings.Repeat("c", 100), strings.Repeat("d", 100),
			},
			[][]int{{0}, {1, 2, 3}},
		},
		{
			"runes rather than bytes",
			[]string{
				strings.Repeat("文", 700), strings.Repeat("a", 600),
				strings.Repeat("b", 600), strings.Repeat("c", 600),
			},
			[][]int{{0, 1}, {2, 3}},
		},
		{
			"earlier boundary wins ties",
			[]string{strings.Repeat("a", 100), strings.Repeat("b", 100), strings.Repeat("c", 100)},
			[][]int{{0}, {1, 2}},
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			windows, _ := prepareWikiDocumentWindows(context.Background(), nil, 1, overflowChunks(tc.bodies...))
			original := windows[0].content
			var sent [][]int
			model := &windowChat{answer: func(_ context.Context, messages []chat.Message) (*types.ChatResponse, error) {
				sent = append(sent, chunkNumbers(promptText(messages)))
				if len(sent) == 1 {
					return overflowResponse(), nil
				}
				return candidateAnswer(), nil
			}}
			_, _, _, err := (&wikiIngestService{}).extractCandidateSlugs(
				context.Background(), model, "kb", windows, "en", nil, wikiOutcomeBatchContext(),
			)
			if err != nil || len(sent) != 3 || !reflect.DeepEqual(sent[1:], tc.want) {
				t.Fatalf("split=%v want=%v err=%v", sent, tc.want, err)
			}
			if windows[0].content != original || len(windows[0].chunks) != len(tc.bodies) {
				t.Fatal("splitting changed the original window needed by summary/retraction")
			}
		})
	}
}

func TestCandidateOverflowReusesOnlyMemberImageMetadata(t *testing.T) {
	for _, sharedURL := range []bool{false, true} {
		t.Run(fmt.Sprintf("shared_url=%v", sharedURL), func(t *testing.T) {
			chunks := overflowChunks("first", "second", "third", "fourth")
			repo := &windowChunks{citedChunkRepo: citedChunkRepo{byParent: map[string][]*types.Chunk{}}}
			for i, chunk := range chunks {
				url := fmt.Sprintf("resource://picture-%d", i)
				if sharedURL {
					url = "resource://shared-picture"
				}
				chunk.Content += " ![scan](" + url + ")"
				caption := fmt.Sprintf("CAPTION_%d ", i) + strings.Repeat("图", 50)
				if !sharedURL && i == 0 {
					caption += strings.Repeat("长", 2000)
				}
				info, _ := json.Marshal([]types.ImageInfo{{URL: url, Caption: caption}})
				repo.byParent[chunk.ID] = []*types.Chunk{
					imageChildChunk("image-"+chunk.ID, chunk.ID, types.ChunkTypeImageCaption, string(info), true),
				}
			}
			windows, _ := prepareWikiDocumentWindows(context.Background(), repo, 1, chunks)
			var prompts []string
			model := &windowChat{answer: func(_ context.Context, messages []chat.Message) (*types.ChatResponse, error) {
				prompt := promptText(messages)
				prompts = append(prompts, prompt)
				// Single-chunk leaves make same-URL ownership unambiguous.
				if len(chunkNumbers(prompt)) > 1 && sharedURL || len(prompts) == 1 {
					return overflowResponse(), nil
				}
				return candidateAnswer(), nil
			}}
			_, _, _, err := (&wikiIngestService{}).extractCandidateSlugs(
				context.Background(), model, "kb", windows, "en", nil, wikiOutcomeBatchContext(),
			)
			if err != nil || repo.reads != 1 {
				t.Fatalf("metadata reads=%d err=%v", repo.reads, err)
			}
			if !sharedURL {
				if len(prompts) != 3 || !reflect.DeepEqual(chunkNumbers(prompts[1]), []int{0}) {
					t.Fatalf("enriched rune lengths must put the large caption alone: calls=%d", len(prompts))
				}
				if !strings.Contains(prompts[1], "CAPTION_0") || strings.Contains(prompts[2], "CAPTION_0") {
					t.Fatal("child content lost or leaked image enrichment")
				}
			} else {
				var leaves int
				for _, prompt := range prompts {
					ids := chunkNumbers(prompt)
					if len(ids) != 1 {
						continue
					}
					leaves++
					for i := range chunks {
						if strings.Contains(prompt, fmt.Sprintf("CAPTION_%d", i)) != (i == ids[0]) {
							t.Fatalf("caption ownership leaked into chunk %d from %d", ids[0], i)
						}
					}
				}
				if leaves != 4 {
					t.Fatalf("expected four enriched leaves, got %d", leaves)
				}
			}
		})
	}
}

func TestCandidateOverflowDepthBudgetAndSafeLogs(t *testing.T) {
	var output bytes.Buffer
	privateLogger := logrus.New()
	privateLogger.SetOutput(&output)
	ctx := context.WithValue(context.Background(), types.LoggerContextKey, logrus.NewEntry(privateLogger))
	windows, _ := prepareWikiDocumentWindows(ctx, nil, 1, overflowChunks(
		"secret-a", "secret-b", "secret-c", "secret-d", "secret-e", "secret-f", "secret-g", "secret-h",
	))
	var sent [][]int
	model := &windowChat{answer: func(_ context.Context, messages []chat.Message) (*types.ChatResponse, error) {
		sent = append(sent, chunkNumbers(promptText(messages)))
		return overflowResponse(), nil
	}}
	e, c, items, err := (&wikiIngestService{}).extractCandidateSlugs(
		ctx, model, "kb", windows, "en", nil, wikiOutcomeBatchContext(),
	)
	// S6a-5: a split depth of 3 reaches single chunks.
	want := [][]int{
		{0, 1, 2, 3, 4, 5, 6, 7},
		{0, 1, 2, 3},
		{0, 1},
		{0},
		{1},
		{2, 3},
		{2},
		{3},
		{4, 5, 6, 7},
		{4, 5},
		{4},
		{5},
		{6, 7},
		{6},
		{7},
	}
	if !reflect.DeepEqual(sent, want) || wikiFailureOutcome(err) != wikiOutcomeFailed ||
		!errors.Is(err, errWikiOutputTruncated) || len(e)+len(c)+len(items) != 0 {
		t.Fatalf("bounded sequential tree: sent=%v err=%v partial=%d", sent, err, len(e)+len(c)+len(items))
	}
	logs := output.String()
	for _, fields := range []string{
		"window=0 split_depth=1 left_chunks=4 right_chunks=4",
		"window=0 split_depth=2 left_chunks=2 right_chunks=2",
		"window=0 split_depth=3 left_chunks=1 right_chunks=1",
	} {
		if !strings.Contains(logs, fields) {
			t.Fatalf("missing diagnostic %q in %s", fields, logs)
		}
	}
	if strings.Contains(logs, "secret-") || strings.Contains(logs, `{"entities"`) {
		t.Fatal("split diagnostics exposed source or model content")
	}
}

func TestCandidateOverflowDoesNotReplayOtherFailures(t *testing.T) {
	for _, tc := range []struct {
		name     string
		response *types.ChatResponse
		cause    error
		outcome  string
	}{
		{"unknown wraps truncation", nil, fmt.Errorf("lost: %w", errWikiOutputTruncated), wikiOutcomeUnknown},
		{"unknown with truncated response", overflowResponse(), errors.New("lost response"), wikiOutcomeUnknown},
		{"empty", &types.ChatResponse{Content: " ", FinishReason: "stop"}, nil, wikiOutcomeFailed},
		{"malformed", &types.ChatResponse{Content: "{", FinishReason: "stop"}, nil, wikiOutcomeFailed},
	} {
		t.Run(tc.name, func(t *testing.T) {
			windows, _ := prepareWikiDocumentWindows(context.Background(), nil, 1, overflowChunks("left", "right"))
			calls := 0
			model := &windowChat{answer: func(context.Context, []chat.Message) (*types.ChatResponse, error) {
				calls++
				return tc.response, tc.cause
			}}
			e, c, items, err := (&wikiIngestService{}).extractCandidateSlugs(
				context.Background(), model, "kb", windows, "en", nil, wikiOutcomeBatchContext(),
			)
			if calls != 1 || wikiFailureOutcome(err) != tc.outcome || len(e)+len(c)+len(items) != 0 {
				t.Fatalf("calls=%d outcome=%s err=%v", calls, wikiFailureOutcome(err), err)
			}
		})
	}
}

func TestCandidateOverflowCancellationLeavesChildrenUnsent(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	windows, _ := prepareWikiDocumentWindows(ctx, nil, 1, overflowChunks("left", "right"))
	calls := 0
	model := &windowChat{answer: func(context.Context, []chat.Message) (*types.ChatResponse, error) {
		calls++
		cancel()
		return overflowResponse(), nil
	}}
	e, c, items, err := (&wikiIngestService{}).extractCandidateSlugs(
		ctx, model, "kb", windows, "en", nil, wikiOutcomeBatchContext(),
	)
	if calls != 1 || wikiFailureOutcome(err) != wikiOutcomeNotRun ||
		!errors.Is(err, context.Canceled) || len(e)+len(c)+len(items) != 0 {
		t.Fatalf("unsent children must be NOT_RUN: calls=%d err=%v", calls, err)
	}
}
