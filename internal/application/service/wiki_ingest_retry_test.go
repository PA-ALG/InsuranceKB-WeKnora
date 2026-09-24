package service

import (
	"context"
	"errors"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
	"testing"
)

type failingWikiModel struct {
	templateCaptureChatModel
	failure error
	calls   int
}

func (m *failingWikiModel) Chat(context.Context, []chat.Message, *chat.ChatOptions) (*types.ChatResponse, error) {
	m.calls++
	return nil, m.failure
}

// Provider text cannot establish whether a request was sent or processed.
// None of these errors may trigger wrapper/SDK replay.
func TestWikiModelErrorsDoNotAuthorizeAutomaticReplay(t *testing.T) {
	for _, msg := range []string{"status 504", "status 429", "status 401", "connection reset", "unexpected EOF", "context deadline exceeded"} {
		t.Run(msg, func(t *testing.T) {
			model := &failingWikiModel{failure: errors.New(msg)}
			_, err := (&wikiIngestService{}).generateWithTemplate(context.Background(), model, "input", nil)
			if model.calls != 1 || wikiFailureOutcome(err) != wikiOutcomeUnknown {
				t.Fatalf("calls=%d err=%v", model.calls, err)
			}
		})
	}
}

func TestWikiCancelledBeforeDispatchIsNotRun(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	model := &failingWikiModel{}
	_, err := (&wikiIngestService{}).generateWithTemplate(ctx, model, "input", nil)
	if model.calls != 0 || wikiFailureOutcome(err) != wikiOutcomeNotRun {
		t.Fatalf("calls=%d err=%v", model.calls, err)
	}
}
