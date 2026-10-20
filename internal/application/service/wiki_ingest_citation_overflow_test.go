package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"regexp"
	"strconv"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

var citationPromptChunks = regexp.MustCompile(`<c id="(c[0-9]+)" index="([0-9]+)">`)

func citationCallMembers(messages []chat.Message) ([]string, []int) {
	var handles []string
	var indexes []int
	for _, match := range citationPromptChunks.FindAllStringSubmatch(promptText(messages), -1) {
		index, _ := strconv.Atoi(match[2])
		handles = append(handles, match[1])
		indexes = append(indexes, index)
	}
	return handles, indexes
}

func citationOverflowChunks(n int) []*types.Chunk {
	var chunks []*types.Chunk
	for i := 0; i < n; i++ {
		chunks = append(chunks, windowChunk(fmt.Sprintf("source-chunk-%d", i), i, strings.Repeat("x", 500)))
	}
	return chunks
}

func citationOverflowAnswer() *types.ChatResponse {
	return &types.ChatResponse{Content: "{", FinishReason: "length"}
}

func TestCitationOverflowPreservesCandidatesRebuildsHandlesAndMerges(t *testing.T) {
	chunks := citationOverflowChunks(8)
	// Rune-balanced splitting must choose 1+7, not the count midpoint 4+4.
	chunks[0].Content = strings.Repeat("字", 5000)
	candidates := "- slug: entity/known, name: \"Known\"\n- slug: concept/other, name: \"Other\"\n"
	var prompts []string
	var members [][]int
	var allHandles [][]string
	model := &windowChat{answer: func(_ context.Context, messages []chat.Message) (*types.ChatResponse, error) {
		handles, indexes := citationCallMembers(messages)
		prompts = append(prompts, promptText(messages))
		members = append(members, indexes)
		allHandles = append(allHandles, handles)
		if len(indexes) == 8 {
			return citationOverflowAnswer(), nil
		}
		ids := append(append([]string{}, handles...), handles[0])
		raw, err := json.Marshal(citationBatchResult{
			Citations: map[string][]string{"entity/known": ids},
			NewSlugs: []newSlugFromCitation{
				{Type: "concept", Slug: "concept/new", Name: fmt.Sprintf("first-%d", indexes[0]), SourceChunks: ids},
				{Type: "concept", Slug: "concept/new", Name: "duplicate", SourceChunks: ids},
			},
		})
		return &types.ChatResponse{Content: string(raw), FinishReason: "stop"}, err
	}}
	out := (&wikiIngestService{}).classifyChunkCitations(
		context.Background(), model, candidates, chunks, "en", wikiOutcomeBatchContext(), nil,
	)
	require.NoError(t, out.Err())
	require.Equal(t, [][]int{{0, 1, 2, 3, 4, 5, 6, 7}, {0}, {1, 2, 3, 4, 5, 6, 7}}, members)
	for i, prompt := range prompts {
		require.Contains(t, prompt, "<candidate_slugs>\n"+candidates+"\n</candidate_slugs>")
		for j, handle := range allHandles[i] {
			require.Equal(t, fmt.Sprintf("c%03d", j), handle, "each invocation needs its own handles")
		}
	}
	var ids []string
	for _, c := range chunks {
		ids = append(ids, c.ID)
	}
	require.Equal(t, ids, out.Citations["entity/known"])
	require.Equal(t, ids, out.Citations["concept/new"])
	require.Len(t, out.NewSlugs, 1)
	require.Equal(t, "first-0", out.NewSlugs[0].Name)
	require.Equal(t, ids, out.NewSlugs[0].SourceChunks)
	entities, concepts, uncited := mergeCitationsIntoItems(
		[]extractedItem{{Slug: "entity/known", Name: "Known"}}, nil, out.Citations, out.NewSlugs,
	)
	require.Zero(t, uncited)
	require.Equal(t, ids, entities[0].SourceChunks)
	require.Len(t, concepts, 1)
	require.Equal(t, ids, concepts[0].SourceChunks)
}

func TestCitationOverflowBoundsAndNonRetryableResults(t *testing.T) {
	for _, tc := range []struct {
		name      string
		chunks    int
		response  *types.ChatResponse
		err       error
		calls     int
		outcome   string
		truncated bool
	}{
		{"depth limit", 8, citationOverflowAnswer(), nil, 7, wikiOutcomeFailed, true},
		{"single chunk", 1, citationOverflowAnswer(), nil, 1, wikiOutcomeFailed, true},
		{"invalid json", 8, &types.ChatResponse{Content: "{"}, nil, 1, wikiOutcomeFailed, false},
		{
			"invalid handle", 8, &types.ChatResponse{Content: `{"citations":{"entity/known":["c999"]}}`},
			nil, 1, wikiOutcomeFailed, false,
		},
		{"unknown send", 8, nil, io.EOF, 1, wikiOutcomeUnknown, false},
		{"unknown with truncation cause", 8, nil, errWikiOutputTruncated, 1, wikiOutcomeUnknown, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			calls := 0
			model := &windowChat{answer: func(context.Context, []chat.Message) (*types.ChatResponse, error) {
				calls++
				return tc.response, tc.err
			}}
			out := (&wikiIngestService{}).classifyChunkCitations(
				context.Background(), model, "entity/known", citationOverflowChunks(tc.chunks),
				"en", wikiOutcomeBatchContext(), nil,
			)
			require.Error(t, out.Err())
			require.Equal(t, tc.calls, calls)
			require.Equal(t, tc.outcome, wikiFailureOutcome(out.Err()))
			require.Equal(t, tc.truncated, errors.Is(out.Err(), errWikiOutputTruncated))
		})
	}
}

func TestCitationOverflowTwoLevelsHaveFourOrderedLeaves(t *testing.T) {
	var members [][]int
	model := &windowChat{answer: func(_ context.Context, messages []chat.Message) (*types.ChatResponse, error) {
		handles, indexes := citationCallMembers(messages)
		members = append(members, indexes)
		if len(indexes) > 2 {
			return citationOverflowAnswer(), nil
		}
		raw, err := json.Marshal(citationBatchResult{Citations: map[string][]string{"entity/known": handles}})
		return &types.ChatResponse{Content: string(raw)}, err
	}}
	chunks := citationOverflowChunks(8)
	out := (&wikiIngestService{}).classifyChunkCitations(
		context.Background(), model, "entity/known", chunks, "en", wikiOutcomeBatchContext(), nil,
	)
	require.NoError(t, out.Err())
	require.Equal(t, [][]int{
		{0, 1, 2, 3, 4, 5, 6, 7}, {0, 1, 2, 3}, {0, 1}, {2, 3}, {4, 5, 6, 7}, {4, 5}, {6, 7},
	}, members)
	require.Len(t, out.Citations["entity/known"], 8)
}

func TestCitationOverflowFailedChildDoesNotRetryOrSuppressSibling(t *testing.T) {
	for _, unknown := range []bool{false, true} {
		t.Run(fmt.Sprintf("unknown=%v", unknown), func(t *testing.T) {
			calls := 0
			model := &windowChat{answer: func(_ context.Context, messages []chat.Message) (*types.ChatResponse, error) {
				calls++
				_, indexes := citationCallMembers(messages)
				if len(indexes) == 8 {
					return citationOverflowAnswer(), nil
				}
				if indexes[0] == 0 {
					if unknown {
						return nil, io.EOF
					}
					// Valid in the parent, outside this child's handle space.
					return &types.ChatResponse{Content: `{"citations":{"entity/known":["c007"]}}`}, nil
				}
				return &types.ChatResponse{Content: `{"citations":{"entity/known":["c000"]}}`}, nil
			}}
			out := (&wikiIngestService{}).classifyChunkCitations(
				context.Background(), model, "entity/known", citationOverflowChunks(8),
				"en", wikiOutcomeBatchContext(), nil,
			)
			wantOutcome := wikiOutcomeFailed
			if unknown {
				wantOutcome = wikiOutcomeUnknown
			}
			require.Equal(t, wantOutcome, wikiFailureOutcome(out.Err()))
			require.Equal(t, 3, calls)
			require.Equal(t, []string{"source-chunk-4"}, out.Citations["entity/known"])
		})
	}
}
