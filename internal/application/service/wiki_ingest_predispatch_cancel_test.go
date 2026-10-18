package service

import (
	"context"
	"errors"
	"sync/atomic"
	"testing"

	"github.com/Tencent/WeKnora/internal/agent"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
)

// Cancelling while computing the request identity occurs after the worker's
// admission check but before the request has joined tenant-scoped coalescing.
type cancelDuringWikiRequestIdentity struct {
	windowChat
	cancel context.CancelFunc
}

func (m *cancelDuringWikiRequestIdentity) GetModelID() string {
	m.cancel()
	return "cancel-during-request-identity"
}

func TestWikiCancellationDuringRequestPreparationIsNotRun(t *testing.T) {
	for _, prompt := range []string{agent.WikiCandidateSlugPrompt, agent.WikiChunkCitationPrompt} {
		t.Run(wikiPromptPurpose(prompt), func(t *testing.T) {
			tenantCtx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(7))
			ctx, cancel := context.WithCancel(tenantCtx)
			defer cancel()
			var calls atomic.Int32
			model := &cancelDuringWikiRequestIdentity{cancel: cancel, windowChat: windowChat{answer: func(context.Context, []chat.Message) (*types.ChatResponse, error) {
				calls.Add(1)
				return &types.ChatResponse{Content: "{}"}, nil
			}}}
			_, err := (&wikiIngestService{}).generateWithTemplateResult(ctx, model, prompt, nil)
			var failure *wikiStageFailure
			if calls.Load() != 0 || !errors.As(err, &failure) || failure.Stage != wikiPromptPurpose(prompt) || failure.Outcome != wikiOutcomeNotRun || !errors.Is(err, context.Canceled) {
				t.Fatalf("pre-dispatch cancellation: calls=%d failure=%+v err=%v", calls.Load(), failure, err)
			}
		})
	}
}
