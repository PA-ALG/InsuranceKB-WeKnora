package service

// S6a-4 acceptance: a citation batch whose answer overflows the completion budget is split and
// classified again, like an overflowing candidate window (Spec
// docs/design/slices/S6a-4-引用批次溢出拆分.md §4). Protected file: written by Claude.
// RED until S6a-4: today a truncated citation answer fails the whole document.

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"testing"

	"github.com/Tencent/WeKnora/internal/agent"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

// citationSplitModel answers candidates normally and a citation call only when its batch holds at
// most limit chunks; a larger batch overflows (finish_reason=length), or with lost set its result is
// unknown.
type citationSplitModel struct {
	templateCaptureChatModel
	mu        sync.Mutex
	limit     int
	lost      bool
	sent      int     // citation calls
	answered  [][]int // chunk numbers of each answered citation call
	overflown int
}

func (m *citationSplitModel) Chat(
	ctx context.Context, messages []chat.Message, _ *chat.ChatOptions,
) (*types.ChatResponse, error) {
	purpose, _ := types.LLMCallMetadataFromContext(ctx)
	text := promptText(messages)
	m.mu.Lock()
	defer m.mu.Unlock()
	switch purpose {
	case wikiPromptPurpose(agent.WikiCandidateSlugPrompt):
		first := 0
		if chunks := chunkNumbers(text); len(chunks) > 0 {
			first = chunks[0]
		}
		return &types.ChatResponse{Content: fmt.Sprintf(
			`{"entities":[],"concepts":[{"name":"窗口W%03d","slug":"concept/w-%03d","description":"d","details":"d"}]}`,
			first, first,
		), FinishReason: "stop"}, nil
	case wikiPromptPurpose(agent.WikiChunkCitationPrompt):
		m.sent++
		chunks := chunkNumbers(text)
		if m.limit == 0 || len(chunks) > m.limit {
			if m.lost {
				return nil, errors.New("connection reset after send")
			}
			m.overflown++
			return &types.ChatResponse{Content: `{"citations":{"concept/w-000":["c1"`, FinishReason: "length"}, nil
		}
		m.answered = append(m.answered, chunks)
		return &types.ChatResponse{Content: `{"citations":{},"new_slugs":[]}`, FinishReason: "stop"}, nil
	default:
		return &types.ChatResponse{Content: "SUMMARY: Policy\nPolicy summary.", FinishReason: "stop"}, nil
	}
}

func mapCitationSplit(t *testing.T, repo interfaces.ChunkRepository, model *citationSplitModel) error {
	t.Helper()
	svc := &wikiIngestService{knowledgeSvc: wikiOutcomeKnowledge{}, chunkRepo: repo, wikiService: &wikiOutcomePages{}}
	_, _, err := svc.mapOneDocument(
		context.Background(), model,
		WikiIngestPayload{TenantID: 1, KnowledgeBaseID: "kb"},
		WikiPendingOp{Op: WikiOpIngest, KnowledgeID: "source"},
		wikiOutcomeBatchContext(),
	)
	return err
}

func citationStageFailure(err error) *wikiStageFailure {
	var failure *wikiStageFailure
	if errors.As(err, &failure) && failure.Stage == "wiki_chunk_citation" {
		return failure
	}
	return nil
}

// The 90-chunk document forms five citation batches of 14-20 chunks; with room for 12 chunks per
// answer each overflows once and its two halves fit.
func TestAnOverflowingCitationBatchIsSplitAndEveryChunkIsCitedOnce(t *testing.T) {
	model := &citationSplitModel{limit: 12}
	if failure := citationStageFailure(mapCitationSplit(t, longDocChunks{}, model)); failure != nil {
		t.Fatalf("an overflowing citation batch must be split, not fail the document: %v", failure)
	}
	if model.overflown != 5 || len(model.answered) != 10 {
		t.Fatalf("each of the five batches must overflow once and be classified as two halves: "+
			"overflown=%d answered=%d", model.overflown, len(model.answered))
	}
	seen := map[int]int{}
	for i, chunks := range model.answered {
		if len(chunks) > 12 {
			t.Fatalf("answered batch %d still holds %d chunks", i, len(chunks))
		}
		for j, n := range chunks {
			seen[n]++
			if j > 0 && n != chunks[j-1]+1 {
				t.Fatalf("answered batch %d is not a contiguous run of the document: %v", i, chunks)
			}
		}
	}
	for n := 0; n < longDocChunkCount; n++ {
		if seen[n] != 1 {
			t.Fatalf("chunk %d reached %d answered citation batches, want exactly 1", n, seen[n])
		}
	}
}

func TestACitationSplitStopsAtItsDepthAndFailsAsTruncation(t *testing.T) {
	model := &citationSplitModel{limit: 0} // every citation answer overflows
	err := mapCitationSplit(t, longDocChunks{}, model)
	failure := citationStageFailure(err)
	if failure == nil || failure.Outcome != wikiOutcomeFailed || !errors.Is(err, errWikiOutputTruncated) {
		t.Fatalf("a batch still overflowing at the depth bound must fail as truncation, got %v", err)
	}
	// Five batches, each at most 1 + 2 + 4 calls under a split depth of 2.
	if model.sent < 5 || model.sent > 35 {
		t.Fatalf("citation calls must stay within the split depth: got %d, want 5..35", model.sent)
	}
}

func TestASingleChunkCitationBatchIsNotSplit(t *testing.T) {
	model := &citationSplitModel{limit: 0}
	err := mapCitationSplit(t, wikiOutcomeChunks{}, model)
	if citationStageFailure(err) == nil || !errors.Is(err, errWikiOutputTruncated) {
		t.Fatalf("a one-chunk citation batch that overflows must fail as truncation, got %v", err)
	}
	if model.sent != 1 {
		t.Fatalf("a one-chunk batch cannot be split and must not be sent again: %d calls", model.sent)
	}
}

func TestAnUnknownCitationSendIsNeitherSplitNorResent(t *testing.T) {
	model := &citationSplitModel{limit: 12, lost: true}
	failure := citationStageFailure(mapCitationSplit(t, longDocChunks{}, model))
	if failure == nil || failure.Outcome != wikiOutcomeUnknown {
		t.Fatalf("a citation send with an unknown result must fail the stage as UNKNOWN, got %v", failure)
	}
	if model.sent != 5 {
		t.Fatalf("each batch is sent once; an unknown send must not be split or resent: %d calls", model.sent)
	}
}
