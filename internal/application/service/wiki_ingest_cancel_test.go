package service

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/agent"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
)

// Seeing Done proves the follower reached its wait; it never relies on a sleep
// to guess whether a concurrent invocation has joined the shared request.
type wikiWaitContext struct {
	context.Context
	waiting chan struct{}
	once    sync.Once
}

func (c *wikiWaitContext) Done() <-chan struct{} {
	c.once.Do(func() { close(c.waiting) })
	return c.Context.Done()
}

func awaitWikiSignal(t *testing.T, signal <-chan struct{}) {
	t.Helper()
	select {
	case <-signal:
	case <-time.After(5 * time.Second):
		t.Fatal("concurrent Wiki work did not reach the expected boundary")
	}
}

func TestWikiSharedRequestUnsentCancellationCannotDispatch(t *testing.T) {
	svc := &wikiIngestService{}
	started := make(chan struct{})
	warmupDone := make(chan struct{})
	svc.promptWarmups.Store("prefix", &wikiPromptWarmup{done: warmupDone})
	var sends atomic.Int32
	execute := func(ctx context.Context, request *wikiLLMRequest) (wikiTemplateResult, error) {
		waitCtx := &wikiWaitContext{Context: ctx, waiting: started}
		_, warmupErr := svc.awaitWikiPromptWarmup(waitCtx, "prefix")
		if warmupErr == nil {
			return wikiTemplateResult{}, errors.New("warmup unexpectedly completed")
		}
		if err := request.beginDispatch("wiki_page_modify"); err != nil {
			return wikiTemplateResult{}, err
		}
		sends.Add(1)
		return wikiTemplateResult{Content: "must not send"}, nil
	}
	leader := make(chan error, 1)
	go func() {
		_, err := svc.runWikiRequest(context.Background(), "same", true, "wiki_page_modify", execute)
		leader <- err
	}()
	awaitWikiSignal(t, started)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	followerCtx := &wikiWaitContext{Context: ctx, waiting: make(chan struct{})}
	follower := make(chan error, 1)
	go func() {
		_, err := svc.runWikiRequest(followerCtx, "same", true, "wiki_page_modify", execute)
		follower <- err
	}()
	awaitWikiSignal(t, followerCtx.waiting)
	cancel()
	for _, done := range []<-chan error{follower, leader} {
		select {
		case err := <-done:
			if wikiFailureOutcome(err) != wikiOutcomeNotRun {
				t.Fatalf("unsent shared request: %v", err)
			}
		case <-time.After(5 * time.Second):
			t.Fatal("shared unsent execution was not cancelled")
		}
	}
	if sends.Load() != 0 {
		t.Fatal("a request dispatched after reporting NOT_RUN")
	}
	close(warmupDone)
}

func TestWikiSharedRequestSentFollowerCancellationKeepsLeader(t *testing.T) {
	svc := &wikiIngestService{}
	started, release := make(chan struct{}), make(chan struct{})
	var sends atomic.Int32
	execute := func(ctx context.Context, request *wikiLLMRequest) (wikiTemplateResult, error) {
		if err := request.beginDispatch("wiki_summary"); err != nil {
			return wikiTemplateResult{}, err
		}
		if sends.Add(1) == 1 {
			close(started)
		}
		<-release
		if ctx.Err() != nil {
			return wikiTemplateResult{}, ctx.Err()
		}
		return wikiTemplateResult{Content: "complete"}, nil
	}
	leader := make(chan error, 1)
	go func() {
		result, err := svc.runWikiRequest(context.Background(), "same", true, "wiki_summary", execute)
		if err == nil && result.Content != "complete" {
			err = errors.New("leader lost the complete result")
		}
		leader <- err
	}()
	awaitWikiSignal(t, started)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	followerCtx := &wikiWaitContext{Context: ctx, waiting: make(chan struct{})}
	follower := make(chan error, 1)
	go func() {
		_, err := svc.runWikiRequest(followerCtx, "same", true, "wiki_summary", execute)
		follower <- err
	}()
	awaitWikiSignal(t, followerCtx.waiting)
	cancel()
	if err := <-follower; wikiFailureOutcome(err) != wikiOutcomeUnknown {
		t.Fatalf("follower must inherit shared send state: %v", err)
	}
	close(release)
	if err := <-leader; err != nil {
		t.Fatal(err)
	}
	if sends.Load() != 1 {
		t.Fatalf("coalesced request sent %d times", sends.Load())
	}
	if _, err := svc.runWikiRequest(context.Background(), "same", true, "wiki_summary", execute); err != nil {
		t.Fatal(err)
	}
	if sends.Load() != 2 {
		t.Fatal("completed request was retained as a result cache")
	}
}

func TestWikiSharedRequestCancelDispatchRace(t *testing.T) {
	for range 100 {
		ctx, cancel := context.WithCancelCause(context.Background())
		request := &wikiLLMRequest{ctx: ctx, cancel: cancel}
		start := make(chan struct{})
		dispatched, cancelled := make(chan error, 1), make(chan error, 1)
		go func() { <-start; dispatched <- request.beginDispatch("wiki_summary") }()
		go func() { <-start; cancelled <- request.cancelled("wiki_summary", context.Canceled) }()
		close(start)
		cancelErr, dispatchErr := <-cancelled, <-dispatched
		if wikiFailureOutcome(cancelErr) == wikiOutcomeNotRun && dispatchErr == nil {
			t.Fatal("NOT_RUN permitted a later dispatch")
		}
		cancel(nil)
	}
}

type wikiCancelledContinuationModel struct {
	templateCaptureChatModel
	cancel context.CancelFunc
	calls  atomic.Int32
}

func (m *wikiCancelledContinuationModel) Chat(
	context.Context, []chat.Message, *chat.ChatOptions,
) (*types.ChatResponse, error) {
	m.calls.Add(1)
	m.cancel()
	return &types.ChatResponse{Content: "partial page", FinishReason: "length"}, nil
}

func TestWikiCancelledContinuationRetainsPriorSend(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	model := &wikiCancelledContinuationModel{cancel: cancel}
	_, err := (&wikiIngestService{}).generateWithTemplate(ctx, model, agent.WikiPageModifyUserPrompt, pageModifyData())
	if model.calls.Load() != 1 || wikiFailureOutcome(err) != wikiOutcomeUnknown {
		t.Fatalf("partial prior send cannot be released for replay: calls=%d err=%v", model.calls.Load(), err)
	}
}

func TestWikiUnscopedCompletedTruncationSurvivesCancellation(t *testing.T) {
	// Independent calls keep their synchronous result ownership. A complete
	// truncated response remains known even when the model cancels its parent.
	for range 100 {
		ctx, cancel := context.WithCancel(context.Background())
		model := &wikiCancelledContinuationModel{cancel: cancel}
		_, err := (&wikiIngestService{}).generateWithTemplate(
			ctx, model, agent.WikiCandidateSlugPrompt, map[string]string{"Content": "source"},
		)
		cancel()
		if model.calls.Load() != 1 || !errors.Is(err, errWikiOutputTruncated) {
			t.Fatalf("known truncation became uncertain: calls=%d err=%v", model.calls.Load(), err)
		}
	}
}
