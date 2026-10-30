package service

import (
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/require"

	chatpipeline "github.com/Tencent/WeKnora/internal/application/service/chat_pipeline"
	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
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

func resultIDs(results []*types.SearchResult) []string {
	out := []string{}
	for _, result := range results {
		out = append(out, result.ID)
	}
	return out
}

func TestQ1b2WikiOnlyQuickAnswerUsesPublishedFieldsWithoutRawSearch(t *testing.T) {
	run := runQ1b2(t, []string{"q-wiki"}, "Product field", nil)
	require.Zero(t, run.searched, "a Wiki-only answer runs no raw retrieval")
	require.Equal(t, []string{"release:q-release:E/field"}, resultIDs(run.prompted))
	require.Equal(t, "release", run.prompted[0].Metadata["source_tier"])
	require.Equal(t, []string{"release:q-release:E/field"}, resultIDs(run.refs))
	require.False(t, run.fallback)
	require.Equal(t, 1, run.reads, "published fields are read once for prompt and references")
}

func TestQ1b2EmptyRawSearchDefersToPublishedFields(t *testing.T) {
	run := runQ1b2(t, []string{"q-raw", "q-wiki"}, "Product field", nil)
	require.Equal(t, []string{"release:q-release:E/field"}, resultIDs(run.prompted))
	require.False(t, run.fallback)
}

func TestQ1b2PublishedFieldsComeBeforeRawResults(t *testing.T) {
	raw := []*types.SearchResult{
		{ID: "q-current", KnowledgeID: "q-doc", KnowledgeBaseID: "q-raw", Content: "fixed material", ImageInfo: "[]"},
	}
	run := runQ1b2(t, []string{"q-raw", "q-wiki"}, "Product field", raw)
	require.Equal(t, []string{"release:q-release:E/field", "q-current"}, resultIDs(run.prompted))
	require.Equal(t, "raw_text", run.prompted[1].Metadata["source_tier"])
	require.Equal(t, []string{"release:q-release:E/field", "q-current"}, resultIDs(run.refs))
}

func TestQ1b2NoPublishedMatchFallsBack(t *testing.T) {
	run := runQ1b2(t, []string{"q-wiki"}, "unrelated question", nil)
	require.Nil(t, run.prompted, "nothing to answer from: the prompt stage does not run")
	require.True(t, run.fallback)
}

// The three regressions below come from Codex's review of #263.

type q1b2ModelKBs struct{ *q1aKBs }

func (s q1b2ModelKBs) GetKnowledgeBaseByID(ctx context.Context, id string) (*types.KnowledgeBase, error) {
	kb, err := s.q1aKBs.GetKnowledgeBaseByID(ctx, id)
	if kb != nil {
		kb.SummaryModelID = "q-chat"
	}
	return kb, err
}

func TestQ1b2WikiOnlyKeepsTheSelectedKnowledgeBaseModel(t *testing.T) {
	ctx, svc, _, kbs := q1aFixture()
	svc.knowledgeBaseService = q1b2ModelKBs{kbs}
	svc.chatSources = svc.chatSources.WithPublished(knowledge.NewService(&publishedReader{}))
	svc.modelService = &stubModelService{
		modelsByID: map[string]*types.Model{
			"q-chat": {ID: "q-chat", Type: types.ModelTypeKnowledgeQA, Source: types.ModelSourceRemote},
		},
		availableModels: []*types.Model{{ID: "other-chat", Type: types.ModelTypeKnowledgeQA}},
	}
	req := &types.QARequest{
		Session: &types.Session{ID: "q-session", TenantID: 7}, TurnLeaseHeld: true,
		KnowledgeBaseIDs: []string{"q-wiki"}, Query: "Product field",
	}
	expected, _, err := svc.resolveChatModelID(ctx, req, []string{"q-wiki"}, nil)
	require.NoError(t, err)
	require.Equal(t, "q-chat", expected)
	actual := ""
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.INTO_CHAT_MESSAGE},
		on:     func(_ types.EventType, cm *types.ChatManage) { actual = cm.ChatModelID },
	})
	require.NoError(t, svc.KnowledgeQA(ctx, req, event.NewEventBus()))
	require.Equal(t, expected, actual, "a Wiki-only answer keeps the selected knowledge base's model")
}

func TestQ1b2RenderedPublishedPromptSurvivesTheSecondFilter(t *testing.T) {
	ctx, svc, _, _ := q1aFixture()
	reader := &publishedReader{}
	svc.chatSources = svc.chatSources.WithPublished(knowledge.NewService(reader))
	svc.cfg.Conversation.Summary.ContextTemplate = "context={{contexts}} query={{query}}"
	chatpipeline.NewPluginIntoChatMessage(svc.eventManager, nil, nil)
	rendered := ""
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.INTO_CHAT_MESSAGE},
		on: func(_ types.EventType, cm *types.ChatManage) {
			rendered = cm.UserContent
			require.NotEmpty(t, cm.RenderedContexts)
		},
	})
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.CHAT_COMPLETION_STREAM},
		on: func(_ types.EventType, cm *types.ChatManage) {
			require.Equal(t, rendered, cm.UserContent)
			require.NotEmpty(t, cm.RenderedContexts)
			require.Equal(t, 1, reader.reads)
		},
	})
	require.NoError(t, svc.KnowledgeQA(ctx, &types.QARequest{
		Session: &types.Session{ID: "q-session", TenantID: 7}, SummaryModelID: "q-chat", TurnLeaseHeld: true,
		KnowledgeBaseIDs: []string{"q-wiki"}, Query: "Product field",
	}, event.NewEventBus()))
}

type q1b2FailedReader struct{}

func (q1b2FailedReader) ReleaseByID(context.Context, uint64, string, string) (release.Release, error) {
	return release.Release{}, errors.New("published read failed")
}

func TestQ1b2PublishedReadFailureStopsBeforePrompt(t *testing.T) {
	ctx, svc, _, _ := q1aFixture()
	svc.chatSources = svc.chatSources.WithPublished(knowledge.NewService(q1b2FailedReader{}))
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.INTO_CHAT_MESSAGE, types.CHAT_COMPLETION_STREAM},
		on:     func(_ types.EventType, _ *types.ChatManage) { t.Fatal("must stop before prompt or stream") },
	})
	err := svc.KnowledgeQA(ctx, &types.QARequest{
		Session: &types.Session{ID: "q-session", TenantID: 7}, SummaryModelID: "q-chat", TurnLeaseHeld: true,
		KnowledgeBaseIDs: []string{"q-wiki"}, Query: "Product field",
	}, event.NewEventBus())
	require.EqualError(t, err, "published read failed")
}

// R2 (#263): the model fallback uses only knowledge bases that passed the ACL checks.
type q1b2ScopeKBs struct{ *q1aKBs }

func (s q1b2ScopeKBs) GetKnowledgeBaseByIDOnly(ctx context.Context, id string) (*types.KnowledgeBase, error) {
	kb, err := s.q1aKBs.GetKnowledgeBaseByIDOnly(ctx, id)
	if err != nil {
		return nil, err
	}
	switch id {
	case "q-wiki":
		kb.SummaryModelID = "wiki-chat"
	case "q-raw":
		kb.SummaryModelID = "raw-chat"
	case "plain":
		kb.SummaryModelID = "plain-chat"
	case "foreign":
		kb.TenantID, kb.SummaryModelID = 8, "foreign-chat"
	}
	return kb, nil
}

func (s q1b2ScopeKBs) GetKnowledgeBaseByID(ctx context.Context, id string) (*types.KnowledgeBase, error) {
	return s.GetKnowledgeBaseByIDOnly(ctx, id)
}

func (s q1b2ScopeKBs) GetKnowledgeBasesByIDsOnly(ctx context.Context, ids []string) ([]*types.KnowledgeBase, error) {
	var out []*types.KnowledgeBase
	for _, id := range ids {
		kb, err := s.GetKnowledgeBaseByIDOnly(ctx, id)
		if err != nil {
			return nil, err
		}
		out = append(out, kb)
	}
	return out, nil
}

func TestQ1b2ModelFollowsTheAuthorizedScope(t *testing.T) {
	for _, tc := range []struct {
		name      string
		ids       []string
		want      string
		targetIDs []string
	}{
		{"wiki-only", []string{"q-wiki"}, "wiki-chat", nil},
		{"raw-only", []string{"q-raw"}, "raw-chat", []string{"q-raw"}},
		{"mixed-wiki-first", []string{"q-wiki", "q-raw"}, "raw-chat", []string{"q-raw"}},
		{"ordinary", []string{"plain"}, "plain-chat", []string{"plain"}},
		{"wiki-and-ordinary", []string{"q-wiki", "plain"}, "plain-chat", []string{"plain"}},
		{"wiki-and-denied-ordinary", []string{"foreign", "q-wiki"}, "wiki-chat", nil},
	} {
		t.Run(tc.name, func(t *testing.T) {
			ctx, svc, _, kbs := q1aFixture()
			svc.knowledgeBaseService = q1b2ScopeKBs{kbs}
			svc.chatSources = svc.chatSources.WithPublished(knowledge.NewService(&publishedReader{}))
			local := func(id string) *types.Model {
				return &types.Model{ID: id, Type: types.ModelTypeKnowledgeQA, Source: types.ModelSourceLocal}
			}
			svc.modelService = &stubModelService{
				modelsByID: map[string]*types.Model{
					"wiki-chat": local("wiki-chat"), "raw-chat": local("raw-chat"), "plain-chat": local("plain-chat"),
				},
				availableModels: []*types.Model{{ID: "wiki-chat", Type: types.ModelTypeKnowledgeQA}},
			}
			actual := ""
			svc.eventManager.Register(q1aPipeline{
				events: []types.EventType{types.QUERY_UNDERSTAND},
				on: func(_ types.EventType, cm *types.ChatManage) {
					actual = cm.ChatModelID
					require.Equal(t, tc.targetIDs, cm.SearchTargets.GetAllKnowledgeBaseIDs())
				},
			})
			err := svc.KnowledgeQA(ctx, &types.QARequest{
				Session: &types.Session{ID: "q-session", TenantID: 7}, TurnLeaseHeld: true,
				KnowledgeBaseIDs: tc.ids, Query: "Product field",
			}, event.NewEventBus())
			require.NoError(t, err)
			require.Equal(t, tc.want, actual)
		})
	}
}
