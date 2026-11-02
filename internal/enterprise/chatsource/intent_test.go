package chatsource_test

// QA5 acceptance: with web search off, an enterprise answer turn whose question understanding
// chose web_search reads the knowledge base like kb_search; every other turn and intent keeps the
// native behaviour (Spec docs/design/slices/QA5-web_search意图回落.md §4.1). Protected file: written
// by Claude. RED until QA5: chatsource.AnswerIntent is missing.

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/types"
)

// intentPrompt stands for the native intent prompt question understanding applies to an intent
// that retrieves nothing (web_search: "web search is unavailable").
const intentPrompt = "intent prompt"

func intentTurn(t *testing.T, kind string) context.Context {
	t.Helper()
	var (
		ctx context.Context
		err error
	)
	switch kind {
	case "answer": // quick answer pinned to the Space's active release
		ctx, _, err = chatsource.ResolveAnswer(context.Background(), resolver(fixture()), tenant,
			types.SearchTargets{kb("raw-1")})
		require.True(t, chatsource.IsEnterpriseAnswer(ctx))
	case "published": // quick answer on the wiki KB, reading published fields
		r, _ := published()
		ctx, _, err = chatsource.ResolveAnswer(context.Background(), r, tenant, types.SearchTargets{kb("wiki-1")})
		require.True(t, chatsource.HasPublished(ctx))
	case "ordinary": // quick answer on an ordinary KB
		ctx, _, err = chatsource.ResolveAnswer(context.Background(), resolver(fixture()), tenant,
			types.SearchTargets{kb("plain")})
		require.False(t, chatsource.IsEnterpriseAnswer(ctx) || chatsource.HasPublished(ctx))
	case "search": // the knowledge-search endpoint on an enterprise raw KB
		ctx, _, err = chatsource.ResolveQuick(context.Background(), resolver(fixture()), tenant,
			types.SearchTargets{kb("raw-1")})
		require.False(t, chatsource.IsEnterpriseAnswer(ctx) || chatsource.HasPublished(ctx))
	default:
		t.Fatalf("unknown turn kind %q", kind)
	}
	require.NoError(t, err)
	return ctx
}

// understood is the state question understanding leaves behind: the model's intent, and the
// intent prompt when that intent retrieves nothing.
func understood(intent types.QueryIntent, web bool) *types.ChatManage {
	cm := &types.ChatManage{}
	cm.WebSearchEnabled = web
	cm.Intent = intent
	if !cm.NeedsRetrieval() {
		cm.SystemPromptOverride = intentPrompt
	}
	return cm
}

func TestAnswerIntentReadsTheKnowledgeBaseForWebSearchWithoutWeb(t *testing.T) {
	for _, kind := range []string{"answer", "published"} {
		t.Run(kind, func(t *testing.T) {
			ctx := intentTurn(t, kind)
			cm := understood(types.IntentWebSearch, false)
			require.False(t, cm.NeedsRetrieval(), "native: web_search without web search retrieves nothing")

			chatsource.AnswerIntent(ctx, types.QUERY_UNDERSTAND, cm)

			require.Equal(t, types.IntentKBSearch, cm.Intent)
			require.Empty(t, cm.SystemPromptOverride, "the web-search-unavailable prompt is dropped")
			require.True(t, cm.NeedsRetrieval())
		})
	}
}

func TestAnswerIntentKeepsOtherTurnsIntentsAndStages(t *testing.T) {
	cases := []struct {
		name   string
		kind   string
		event  types.EventType
		intent types.QueryIntent
		web    bool
	}{
		{"web search on", "answer", types.QUERY_UNDERSTAND, types.IntentWebSearch, true},
		{"chitchat", "answer", types.QUERY_UNDERSTAND, types.IntentChitchat, false},
		{"greeting", "published", types.QUERY_UNDERSTAND, types.IntentGreeting, false},
		{"kb_search", "answer", types.QUERY_UNDERSTAND, types.IntentKBSearch, false},
		{"understanding failed", "answer", types.QUERY_UNDERSTAND, "", false},
		{"ordinary KB", "ordinary", types.QUERY_UNDERSTAND, types.IntentWebSearch, false},
		{"search endpoint", "search", types.QUERY_UNDERSTAND, types.IntentWebSearch, false},
		{"other stage", "answer", types.CHUNK_SEARCH_PARALLEL, types.IntentWebSearch, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			ctx := intentTurn(t, tc.kind)
			cm := understood(tc.intent, tc.web)
			intent, prompt, retrieves := cm.Intent, cm.SystemPromptOverride, cm.NeedsRetrieval()

			chatsource.AnswerIntent(ctx, tc.event, cm)

			require.Equal(t, intent, cm.Intent)
			require.Equal(t, prompt, cm.SystemPromptOverride)
			require.Equal(t, retrieves, cm.NeedsRetrieval())
		})
	}
	require.NotPanics(t, func() {
		chatsource.AnswerIntent(intentTurn(t, "answer"), types.QUERY_UNDERSTAND, nil)
	})
}
