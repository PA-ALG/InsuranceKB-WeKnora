package service

// QA5 acceptance: through the real KnowledgeQA pipeline and parallel search plugin, a quick answer
// whose question understanding chose web_search with web search off still reads the Space's
// published fields and pinned materials; chitchat and ordinary KB turns keep the native "no
// retrieval" path (Spec docs/design/slices/QA5-web_search意图回落.md §4.2). Protected file: written by
// Claude. RED until QA5: nothing calls chatsource.AnswerIntent after question understanding.

import (
	"context"
	"sync"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/event"
	"github.com/Tencent/WeKnora/internal/types"
)

const nativeIntentPrompt = "intent prompt"

type intentRun struct {
	prompted []*types.SearchResult
	intent   types.QueryIntent
	override string
}

// askWithIntent stands in for the native question-understanding plugin: it sets the model's
// intent and, like applyIntentPromptOverride, the intent prompt when that intent retrieves nothing.
func askWithIntent(
	ctx context.Context, t *testing.T, svc *sessionService, kbIDs []string, intent types.QueryIntent,
) intentRun {
	t.Helper()
	var run intentRun
	var mu sync.Mutex
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.QUERY_UNDERSTAND},
		on: func(_ types.EventType, cm *types.ChatManage) {
			cm.Intent = intent
			if !cm.NeedsRetrieval() {
				cm.SystemPromptOverride = nativeIntentPrompt
			}
		},
	})
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.INTO_CHAT_MESSAGE},
		on: func(_ types.EventType, cm *types.ChatManage) {
			mu.Lock()
			defer mu.Unlock()
			run.prompted, run.intent, run.override = cm.MergeResult, cm.Intent, cm.SystemPromptOverride
		},
	})
	require.NoError(t, svc.KnowledgeQA(ctx, &types.QARequest{
		Session: &types.Session{ID: "q-session", TenantID: 7}, SummaryModelID: "q-chat", TurnLeaseHeld: true,
		KnowledgeBaseIDs: kbIDs, Query: "Product field",
	}, event.NewEventBus()))
	mu.Lock()
	defer mu.Unlock()
	return run
}

func TestQA5WebSearchIntentWithoutWebReadsPublishedFieldsAndPinnedMaterials(t *testing.T) {
	ctx, svc, kbs := q2aFixture()
	run := askWithIntent(ctx, t, svc, []string{"q-wiki"}, types.IntentWebSearch)
	require.Len(t, kbs.seen, 1, "the Space's raw KB is searched once")
	require.Equal(t, []string{"q-doc"}, kbs.seen[0].KnowledgeIDs, "only the release-pinned material is searched")
	require.Equal(t, []string{"release:q-release:E/field", "q-current"}, resultIDs(run.prompted))
	require.Equal(t, types.IntentKBSearch, run.intent)
	require.Empty(t, run.override, "the answer is not told that web search is unavailable")
}

func TestQA5ChitchatOnAQuickAnswerStillRetrievesNothing(t *testing.T) {
	ctx, svc, kbs := q2aFixture()
	run := askWithIntent(ctx, t, svc, []string{"q-wiki"}, types.IntentChitchat)
	require.Empty(t, kbs.seen)
	require.Empty(t, run.prompted)
	require.Equal(t, types.IntentChitchat, run.intent)
	require.Equal(t, nativeIntentPrompt, run.override)
}

func TestQA5OrdinaryKBKeepsTheNativeWebSearchIntent(t *testing.T) {
	ctx, svc, kbs := q2aFixture()
	run := askWithIntent(ctx, t, svc, []string{"plain"}, types.IntentWebSearch)
	require.Empty(t, kbs.seen, "native: web_search without web search retrieves nothing")
	require.Empty(t, run.prompted)
	require.Equal(t, types.IntentWebSearch, run.intent)
	require.Equal(t, nativeIntentPrompt, run.override)
}
