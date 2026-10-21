package service

import (
	"context"
	"sync"
	"testing"

	"github.com/Tencent/WeKnora/internal/event"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

// Unlike the frozen acceptance helper, these tests run the real asynchronous
// streaming plugin. Protect event collection while returning a result snapshot.
func askQ2aEdges(ctx context.Context, t *testing.T, svc *sessionService, query, model string) q2aRun {
	t.Helper()
	var run q2aRun
	var mu sync.Mutex
	bus := event.NewEventBus()
	bus.On(event.EventAgentReferences, func(_ context.Context, evt event.Event) error {
		mu.Lock()
		defer mu.Unlock()
		run.refs = evt.Data.(event.AgentReferencesData).References.([]*types.SearchResult)
		return nil
	})
	bus.On(event.EventAgentFinalAnswer, func(_ context.Context, evt event.Event) error {
		mu.Lock()
		defer mu.Unlock()
		data := evt.Data.(event.AgentFinalAnswerData)
		run.answer = &data
		return nil
	})
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.INTO_CHAT_MESSAGE},
		on: func(_ types.EventType, cm *types.ChatManage) {
			mu.Lock()
			defer mu.Unlock()
			run.prompted, run.model = cm.MergeResult, cm.ChatModelID
		},
	})
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.CHAT_COMPLETION_STREAM},
		on: func(_ types.EventType, cm *types.ChatManage) {
			mu.Lock()
			defer mu.Unlock()
			run.rendered = cm.UserContent
		},
	})
	require.NoError(t, svc.KnowledgeQA(ctx, &types.QARequest{
		Session: &types.Session{ID: "q-session", TenantID: 7}, SummaryModelID: model, TurnLeaseHeld: true,
		KnowledgeBaseIDs: []string{"q-wiki"}, Query: query,
	}, bus))
	mu.Lock()
	defer mu.Unlock()
	return run
}
