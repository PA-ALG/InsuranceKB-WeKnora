package service

// S6a-5 acceptance: candidate and citation calls get a 65,536-token completion budget when the
// model is known to emit that much, splitting goes one level deeper, and a transport failure names
// its class without echoing any error body (Spec docs/design/slices/S6a-5-思考调用输出预算.md §4).
// Protected file: written by Claude. RED until S6a-5.

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"strings"
	"sync"
	"syscall"
	"testing"

	"github.com/Tencent/WeKnora/internal/agent"
	"github.com/Tencent/WeKnora/internal/models/api"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
)

// budgetModel answers every Wiki call successfully and records the completion budget per purpose.
type budgetModel struct {
	templateCaptureChatModel
	mu      sync.Mutex
	budgets map[string][]int
}

func (m *budgetModel) Chat(
	ctx context.Context, _ []chat.Message, opts *chat.ChatOptions,
) (*types.ChatResponse, error) {
	purpose, _ := types.LLMCallMetadataFromContext(ctx)
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.budgets == nil {
		m.budgets = map[string][]int{}
	}
	budget := 0
	if opts != nil {
		budget = opts.MaxTokens
	}
	m.budgets[purpose] = append(m.budgets[purpose], budget)
	switch purpose {
	case wikiPromptPurpose(agent.WikiCandidateSlugPrompt):
		answer := `{"entities":[],"concepts":[{"name":"W","slug":"concept/w-000","description":"d","details":"d"}]}`
		return &types.ChatResponse{Content: answer, FinishReason: "stop"}, nil
	case wikiPromptPurpose(agent.WikiChunkCitationPrompt):
		return &types.ChatResponse{Content: `{"citations":{},"new_slugs":[]}`, FinishReason: "stop"}, nil
	default:
		return &types.ChatResponse{Content: "SUMMARY: Policy\nPolicy summary.", FinishReason: "stop"}, nil
	}
}

// limitedBudgetModel reports a known output limit the way NewChat's chats do.
type limitedBudgetModel struct {
	*budgetModel
	maxOutput int
}

func (m limitedBudgetModel) MaxOutputTokens() int { return m.maxOutput }

var _ chat.OutputLimited = limitedBudgetModel{}

func mapForBudgets(t *testing.T, model chat.Chat) {
	t.Helper()
	svc := &wikiIngestService{
		knowledgeSvc: wikiOutcomeKnowledge{}, chunkRepo: wikiOutcomeChunks{}, wikiService: &wikiOutcomePages{},
	}
	if _, _, err := svc.mapOneDocument(
		context.Background(), model,
		WikiIngestPayload{TenantID: 1, KnowledgeBaseID: "kb"},
		WikiPendingOp{Op: WikiOpIngest, KnowledgeID: "source"},
		wikiOutcomeBatchContext(),
	); err != nil {
		t.Fatalf("mapping must succeed: %v", err)
	}
}

func checkBudgets(t *testing.T, budgets map[string][]int, structured int) {
	t.Helper()
	candidate := wikiPromptPurpose(agent.WikiCandidateSlugPrompt)
	citation := wikiPromptPurpose(agent.WikiChunkCitationPrompt)
	if len(budgets[candidate]) == 0 || len(budgets[citation]) == 0 || len(budgets) < 3 {
		t.Fatalf("the document must reach candidate, citation and at least one other call: %v", budgets)
	}
	for purpose, seen := range budgets {
		want := 32768
		if purpose == candidate || purpose == citation {
			want = structured
		}
		for _, got := range seen {
			if got != want {
				t.Fatalf("%s call sent max_tokens=%d, want %d (all budgets: %v)", purpose, got, want, budgets)
			}
		}
	}
}

func TestCandidateAndCitationCallsUseTheLargerBudgetWhenTheModelEmitsThatMuch(t *testing.T) {
	model := limitedBudgetModel{budgetModel: &budgetModel{}, maxOutput: 384000}
	mapForBudgets(t, model)
	checkBudgets(t, model.budgets, 65536)
}

func TestEveryWikiCallKeepsTheDefaultBudgetWithoutAKnownLargeLimit(t *testing.T) {
	for _, tc := range []struct {
		name  string
		model func() (chat.Chat, *budgetModel)
	}{
		{"no limit reported", func() (chat.Chat, *budgetModel) { m := &budgetModel{}; return m, m }},
		{"unknown limit", func() (chat.Chat, *budgetModel) {
			m := &budgetModel{}
			return limitedBudgetModel{budgetModel: m}, m
		}},
		{"limit below 65,536", func() (chat.Chat, *budgetModel) {
			m := &budgetModel{}
			return limitedBudgetModel{budgetModel: m, maxOutput: 40000}, m
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			model, recorder := tc.model()
			mapForBudgets(t, model)
			checkBudgets(t, recorder.budgets, 32768)
		})
	}
}

// The two windows (about 54 and 36 chunks) only fit at 8 chunks per answer: their quarters (13-14
// and 9 chunks) still overflow, so every chunk is read only after a third split.
func TestACandidateWindowThatFitsOnlyAtTheThirdSplitIsReadInFull(t *testing.T) {
	model := &splitModel{limit: 8}
	if failure := candidateStageFailure(mapSplitDocument(t, longDocChunks{}, model)); failure != nil {
		t.Fatalf("a window that fits at the third split must not fail the document: %v", failure)
	}
	seen := map[int]int{}
	for i, chunks := range model.answered {
		if len(chunks) > 8 {
			t.Fatalf("answered window %d still holds %d chunks", i, len(chunks))
		}
		for _, n := range chunks {
			seen[n]++
		}
	}
	for n := 0; n < longDocChunkCount; n++ {
		if seen[n] != 1 {
			t.Fatalf("chunk %d was read by %d answered windows, want exactly 1", n, seen[n])
		}
	}
}

// The five citation batches (14-20 chunks) only fit at 4 chunks per answer: a 20-chunk batch's
// quarters hold 5 chunks and overflow, so it needs a third split.
func TestACitationBatchThatFitsOnlyAtTheThirdSplitIsCitedInFull(t *testing.T) {
	model := &citationSplitModel{limit: 4}
	if failure := citationStageFailure(mapCitationSplit(t, longDocChunks{}, model)); failure != nil {
		t.Fatalf("a batch that fits at the third split must not fail the document: %v", failure)
	}
	seen := map[int]int{}
	for i, chunks := range model.answered {
		if len(chunks) > 4 {
			t.Fatalf("answered batch %d still holds %d chunks", i, len(chunks))
		}
		for _, n := range chunks {
			seen[n]++
		}
	}
	for n := 0; n < longDocChunkCount; n++ {
		if seen[n] != 1 {
			t.Fatalf("chunk %d reached %d answered citation batches, want exactly 1", n, seen[n])
		}
	}
}

type timeoutError struct{}

func (timeoutError) Error() string   { return "i/o timeout" }
func (timeoutError) Timeout() bool   { return true }
func (timeoutError) Temporary() bool { return true }

var _ net.Error = timeoutError{}

func TestATransportFailureNamesItsClassWithoutTheErrorBody(t *testing.T) {
	const marker = "ECHOED-PROMPT-TEXT"
	reset := &net.OpError{Op: "read", Net: "tcp", Err: os.NewSyscallError("read", syscall.ECONNRESET)}
	for _, tc := range []struct {
		err  error
		want string
	}{
		{&api.HTTPError{StatusCode: 503, Body: marker}, "http 503"},
		{timeoutError{}, "timeout"},
		{io.ErrUnexpectedEOF, "connection closed"},
		{reset, "connection closed"},
		{errors.New(marker), "other"},
	} {
		for _, err := range []error{tc.err, fmt.Errorf("chat: %w", tc.err)} {
			got := wikiTransportDetail(err)
			if got != tc.want {
				t.Fatalf("wikiTransportDetail(%T) = %q, want %q", err, got, tc.want)
			}
			if strings.Contains(got, marker) {
				t.Fatalf("the transport detail must never carry the error body: %q", got)
			}
		}
	}
}
