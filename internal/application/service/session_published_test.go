package service

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/event"
	"github.com/Tencent/WeKnora/internal/types"
)

type q1b2Run struct {
	prompted []*types.SearchResult
	refs     []*types.SearchResult
	fallback bool
	searched int
	reads    int
}

// runQ1b2 asks one quick question with published knowledge configured (Q1b-2).
func runQ1b2(t *testing.T, kbIDs []string, query string, raw []*types.SearchResult) q1b2Run {
	t.Helper()
	ctx, svc, _, kbs := q1aFixture()
	reader := &publishedReader{}
	svc.chatSources = svc.chatSources.WithPublished(knowledge.NewService(reader))
	kbs.rows = nil // raw results, if any, come from the search stage below
	var run q1b2Run
	bus := event.NewEventBus()
	bus.On(event.EventAgentReferences, func(_ context.Context, evt event.Event) error {
		run.refs = evt.Data.(event.AgentReferencesData).References.([]*types.SearchResult)
		return nil
	})
	bus.On(event.EventAgentFinalAnswer, func(context.Context, event.Event) error {
		run.fallback = true
		return nil
	})
	if raw != nil {
		svc.eventManager.Register(q1aPipeline{
			events: []types.EventType{types.CHUNK_SEARCH_PARALLEL},
			on:     func(_ types.EventType, cm *types.ChatManage) { cm.SearchResult = raw },
		})
	}
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.INTO_CHAT_MESSAGE},
		on:     func(_ types.EventType, cm *types.ChatManage) { run.prompted = cm.MergeResult },
	})
	err := svc.KnowledgeQA(ctx, &types.QARequest{
		Session: &types.Session{ID: "q-session", TenantID: 7}, SummaryModelID: "q-chat", TurnLeaseHeld: true,
		KnowledgeBaseIDs: kbIDs, Query: query,
	}, bus)
	require.NoError(t, err)
	run.searched, run.reads = len(kbs.seen), reader.reads
	return run
}

func ids(results []*types.SearchResult) []string {
	out := []string{}
	for _, result := range results {
		out = append(out, result.ID)
	}
	return out
}

func TestQ1b2WikiOnlyQuickAnswerUsesPublishedFieldsWithoutRawSearch(t *testing.T) {
	run := runQ1b2(t, []string{"q-wiki"}, "Product field", nil)
	require.Zero(t, run.searched, "a Wiki-only answer runs no raw retrieval")
	require.Equal(t, []string{"release:q-release:E/field"}, ids(run.prompted))
	require.Equal(t, "release", run.prompted[0].Metadata["source_tier"])
	require.Equal(t, []string{"release:q-release:E/field"}, ids(run.refs))
	require.False(t, run.fallback)
	require.Equal(t, 1, run.reads, "published fields are read once for prompt and references")
}

func TestQ1b2EmptyRawSearchDefersToPublishedFields(t *testing.T) {
	run := runQ1b2(t, []string{"q-raw", "q-wiki"}, "Product field", nil)
	require.Equal(t, []string{"release:q-release:E/field"}, ids(run.prompted))
	require.False(t, run.fallback)
}

func TestQ1b2PublishedFieldsComeBeforeRawResults(t *testing.T) {
	raw := []*types.SearchResult{
		{ID: "q-current", KnowledgeID: "q-doc", KnowledgeBaseID: "q-raw", Content: "fixed material", ImageInfo: "[]"},
	}
	run := runQ1b2(t, []string{"q-raw", "q-wiki"}, "Product field", raw)
	require.Equal(t, []string{"release:q-release:E/field", "q-current"}, ids(run.prompted))
	require.Equal(t, "raw_text", run.prompted[1].Metadata["source_tier"])
	require.Equal(t, []string{"release:q-release:E/field", "q-current"}, ids(run.refs))
}

func TestQ1b2NoPublishedMatchFallsBack(t *testing.T) {
	run := runQ1b2(t, []string{"q-wiki"}, "unrelated question", nil)
	require.Nil(t, run.prompted, "nothing to answer from: the prompt stage does not run")
	require.True(t, run.fallback)
}
