package service

// S6a-3 acceptance: a wiki model call that never left the process is NOT_RUN, whatever its purpose;
// only a call that was actually sent may end OUTCOME_UNKNOWN (Spec
// docs/design/slices/S6a-3-原生Wiki取消后的失败归类.md §2.1). Protected file: written by Claude.
// RED until S6a-3: today a cancelled page rewrite or taxonomy plan reports OUTCOME_UNKNOWN without a send.

import (
	"context"
	"sync/atomic"
	"testing"

	"github.com/Tencent/WeKnora/internal/agent"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
)

// blockingWikiModel signals that a call was sent, blocks until its context ends, then reports that error.
type blockingWikiModel struct {
	templateCaptureChatModel
	calls   atomic.Int32
	started chan struct{}
}

func (m *blockingWikiModel) Chat(
	ctx context.Context, _ []chat.Message, _ *chat.ChatOptions,
) (*types.ChatResponse, error) {
	if m.calls.Add(1) == 1 {
		close(m.started)
	}
	<-ctx.Done()
	return nil, ctx.Err()
}

var everyWikiPurpose = []string{
	agent.WikiPageModifyUserPrompt, agent.WikiTaxonomyPlanPrompt, agent.WikiSummaryPrompt,
	agent.WikiIndexIntroPrompt, agent.WikiDeduplicationPrompt, agent.WikiCandidateSlugPrompt,
	agent.WikiChunkCitationPrompt,
}

func pageModifyData() map[string]string {
	return map[string]string{
		"HasAdditions": "true", "SharedSourceContexts": "<chunk>x</chunk>", "PageSlug": "concept/x",
	}
}

func TestEveryWikiCallCancelledBeforeSendingIsNotRun(t *testing.T) {
	for _, prompt := range everyWikiPurpose {
		t.Run(wikiPromptPurpose(prompt), func(t *testing.T) {
			tenant := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(7))
			ctx, cancel := context.WithCancel(tenant)
			cancel()
			model := &failingWikiModel{}
			_, err := (&wikiIngestService{}).generateWithTemplate(ctx, model, prompt, pageModifyData())
			if model.calls != 0 || wikiFailureOutcome(err) != wikiOutcomeNotRun {
				t.Fatalf("a call cancelled before sending must be NOT_RUN without a send: calls=%d outcome=%s err=%v",
					model.calls, wikiFailureOutcome(err), err)
			}
		})
	}
}

func TestACallCancelledAfterSendingStaysUnknown(t *testing.T) {
	for _, prompt := range []string{agent.WikiPageModifyUserPrompt, agent.WikiTaxonomyPlanPrompt} {
		t.Run(wikiPromptPurpose(prompt), func(t *testing.T) {
			tenant := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(7))
			ctx, cancel := context.WithCancel(tenant)
			model := &blockingWikiModel{started: make(chan struct{})}
			done := make(chan error, 1)
			go func() {
				_, err := (&wikiIngestService{}).generateWithTemplate(ctx, model, prompt, pageModifyData())
				done <- err
			}()
			select {
			case <-model.started:
			case err := <-done:
				t.Fatalf("returned before sending: %v", err)
			}
			cancel()
			err := <-done
			if model.calls.Load() != 1 || wikiFailureOutcome(err) != wikiOutcomeUnknown {
				t.Fatalf("a sent call cut off by cancellation is OUTCOME_UNKNOWN: calls=%d outcome=%s err=%v",
					model.calls.Load(), wikiFailureOutcome(err), err)
			}
		})
	}
}
