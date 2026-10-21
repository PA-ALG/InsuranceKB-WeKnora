package service

// S6a-2 acceptance: a candidate window whose answer overflows the completion budget is split and
// read again (Spec docs/design/slices/S6a-2-候选窗口溢出拆分.md §4). Protected file: written by
// Claude. RED until S6a-2: today a truncated candidate answer fails the whole document.

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"sync"
	"testing"

	"github.com/Tencent/WeKnora/internal/agent"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

var (
	splitChunkMark = regexp.MustCompile(longDocChunkMark + `(\d{3})`)
	splitSlugMark  = regexp.MustCompile(`concept/w-(\d{3})`)
)

// splitModel answers a candidate call only when its window holds at most limit chunks; a larger
// window overflows like a dense document (finish_reason=length), or, with lost set, the send's
// result is unknown. Each answered window yields one concept named after its first chunk.
type splitModel struct {
	templateCaptureChatModel
	mu        sync.Mutex
	limit     int
	lost      bool
	sent      int     // candidate calls
	answered  [][]int // chunk numbers of each answered candidate call
	overflown int
	citations []string
}

func chunkNumbers(text string) []int {
	var out []int
	for _, match := range splitChunkMark.FindAllStringSubmatch(text, -1) {
		n, _ := strconv.Atoi(match[1])
		out = append(out, n)
	}
	return out
}

func (m *splitModel) Chat(
	ctx context.Context, messages []chat.Message, _ *chat.ChatOptions,
) (*types.ChatResponse, error) {
	purpose, _ := types.LLMCallMetadataFromContext(ctx)
	text := promptText(messages)
	m.mu.Lock()
	defer m.mu.Unlock()
	switch purpose {
	case wikiPromptPurpose(agent.WikiCandidateSlugPrompt):
		m.sent++
		chunks := chunkNumbers(text)
		if len(chunks) > m.limit || m.limit == 0 {
			if m.lost {
				return nil, errors.New("connection reset after send")
			}
			m.overflown++
			return &types.ChatResponse{Content: `{"entities":[],"concepts":[{"name":"W`, FinishReason: "length"}, nil
		}
		m.answered = append(m.answered, chunks)
		first := 0
		if len(chunks) > 0 {
			first = chunks[0]
		}
		return &types.ChatResponse{Content: fmt.Sprintf(
			`{"entities":[],"concepts":[{"name":"窗口W%03d","slug":"concept/w-%03d","description":"d","details":"d"}]}`,
			first, first,
		), FinishReason: "stop"}, nil
	case wikiPromptPurpose(agent.WikiChunkCitationPrompt):
		m.citations = append(m.citations, text)
		return &types.ChatResponse{Content: `{"citations":{},"new_slugs":[]}`, FinishReason: "stop"}, nil
	default:
		return &types.ChatResponse{Content: "SUMMARY: Policy\nPolicy summary.", FinishReason: "stop"}, nil
	}
}

func mapSplitDocument(t *testing.T, repo interfaces.ChunkRepository, model *splitModel) error {
	t.Helper()
	svc := &wikiIngestService{knowledgeSvc: wikiOutcomeKnowledge{}, chunkRepo: repo, wikiService: &wikiOutcomePages{}}
	_, _, err := svc.mapOneDocument(
		context.Background(),
		model,
		WikiIngestPayload{TenantID: 1, KnowledgeBaseID: "kb"},
		WikiPendingOp{Op: WikiOpIngest, KnowledgeID: "source"},
		wikiOutcomeBatchContext(),
	)
	return err
}

func candidateStageFailure(err error) *wikiStageFailure {
	var failure *wikiStageFailure
	if errors.As(err, &failure) && failure.Stage == "wiki_candidate_slug" {
		return failure
	}
	return nil
}

// The 90-chunk document opens as two windows (about 54 and 36 chunks); with room for 30 chunks per
// answer each overflows once and its two halves fit.
func TestAnOverflowingCandidateWindowIsSplitAndEveryChunkIsReadOnce(t *testing.T) {
	model := &splitModel{limit: 30}
	if failure := candidateStageFailure(mapSplitDocument(t, longDocChunks{}, model)); failure != nil {
		t.Fatalf("an overflowing window must be split, not fail the document: %v", failure)
	}
	if model.overflown != 2 || len(model.answered) != 4 {
		t.Fatalf("each of the two windows must overflow once and be read as two halves: overflown=%d answered=%d",
			model.overflown, len(model.answered))
	}
	seen := map[int]int{}
	for i, chunks := range model.answered {
		for j, n := range chunks {
			seen[n]++
			if j > 0 && n != chunks[j-1]+1 {
				t.Fatalf("answered window %d is not a contiguous run of the document: %v", i, chunks)
			}
		}
	}
	for n := 0; n < longDocChunkCount; n++ {
		if seen[n] != 1 {
			t.Fatalf("chunk %d was read by %d answered windows, want exactly 1", n, seen[n])
		}
	}
}

func TestCitationBatchesListTheCandidatesOfTheirSplitWindow(t *testing.T) {
	model := &splitModel{limit: 30}
	_ = mapSplitDocument(t, longDocChunks{}, model) // the empty citations may end the document; the calls matter

	owner := map[int]string{} // chunk number -> slug found by the half that read it
	for _, chunks := range model.answered {
		for _, n := range chunks {
			owner[n] = fmt.Sprintf("concept/w-%03d", chunks[0])
		}
	}
	if len(model.citations) == 0 {
		t.Fatal("citation batches must still be classified")
	}
	cited := map[int]bool{}
	for i, prompt := range model.citations {
		listed := map[string]bool{}
		for _, match := range splitSlugMark.FindAllString(prompt, -1) {
			listed[match] = true
		}
		for _, n := range chunkNumbers(prompt) {
			cited[n] = true
			if !listed[owner[n]] {
				t.Fatalf("citation batch %d holds chunk %d but does not list %q from the half that read it; lists %v",
					i, n, owner[n], keys(listed))
			}
		}
		if len(listed) != 1 {
			t.Fatalf("citation batch %d must list only its own half's candidate, lists %v", i, keys(listed))
		}
	}
	if len(cited) != longDocChunkCount {
		t.Fatalf("every chunk must reach a citation batch, %d of %d did", len(cited), longDocChunkCount)
	}
}

func TestASplitStopsAtItsDepthAndFailsAsTruncation(t *testing.T) {
	model := &splitModel{limit: 0} // every candidate answer overflows
	err := mapSplitDocument(t, longDocChunks{}, model)

	failure := candidateStageFailure(err)
	if failure == nil || failure.Outcome != wikiOutcomeFailed || !errors.Is(err, errWikiOutputTruncated) {
		t.Fatalf("a window still overflowing at the depth bound must fail as truncation, got %v", err)
	}
	// Two windows, each at most 1 + 2 + 4 + 8 calls under a split depth of 3 (S6a-5).
	if model.sent < 2 || model.sent > 30 {
		t.Fatalf("candidate calls must stay within the split depth: got %d, want 2..30", model.sent)
	}
	if len(model.citations) != 0 {
		t.Fatalf("no citation call may follow a failed candidate stage, got %d", len(model.citations))
	}
}

func TestASingleChunkWindowIsNotSplit(t *testing.T) {
	model := &splitModel{limit: 0}
	err := mapSplitDocument(t, wikiOutcomeChunks{}, model)

	if candidateStageFailure(err) == nil || !errors.Is(err, errWikiOutputTruncated) {
		t.Fatalf("a one-chunk window that overflows must fail as truncation, got %v", err)
	}
	if model.sent != 1 {
		t.Fatalf("a one-chunk window cannot be split and must not be sent again: %d calls", model.sent)
	}
}

func TestAnUnknownCandidateSendIsNeitherSplitNorResent(t *testing.T) {
	model := &splitModel{limit: 30, lost: true}
	err := mapSplitDocument(t, longDocChunks{}, model)

	failure := candidateStageFailure(err)
	if failure == nil || failure.Outcome != wikiOutcomeUnknown {
		t.Fatalf("a send with an unknown result must fail the candidate stage as UNKNOWN, got %v", err)
	}
	if model.sent != 2 {
		t.Fatalf("each window is sent once; an unknown send must not be split or resent: %d calls", model.sent)
	}
}

func keys(set map[string]bool) []string {
	out := make([]string, 0, len(set))
	for key := range set {
		out = append(out, key)
	}
	sort.Strings(out)
	return out
}
