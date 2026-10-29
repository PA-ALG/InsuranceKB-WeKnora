package service

// Q2a acceptance: a quick answer on a Space's wiki KB also reads the Space's release-pinned raw
// materials, labels both source tiers for the model, and when neither has anything gives a fixed
// answer instead of the model's general knowledge (Spec docs/design/slices/Q2a-快问快答找不到时查原文.md
// §4). Protected file: written by Claude. RED until Q2a: chatsource.NotFoundAnswer is missing.

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	chatpipeline "github.com/Tencent/WeKnora/internal/application/service/chat_pipeline"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/event"
	"github.com/Tencent/WeKnora/internal/types"
)

// q2aSources is the Q1a directory plus the Space's two configured KBs, like releasestore.Spaces.
type q2aSources struct{ *q1aSources }

func (q2aSources) KnowledgeBases(tenant uint64, space string) (string, string, bool) {
	if tenant == 7 && space == "q-space" {
		return "q-raw", "q-wiki", true
	}
	return "", "", false
}

// q2aModelKBs gives the two KBs different chat models, so a model switch would be visible.
type q2aModelKBs struct{ *q1aKBs }

func (s q2aModelKBs) GetKnowledgeBaseByID(ctx context.Context, id string) (*types.KnowledgeBase, error) {
	return s.GetKnowledgeBaseByIDOnly(ctx, id)
}

func (s q2aModelKBs) GetKnowledgeBaseByIDOnly(ctx context.Context, id string) (*types.KnowledgeBase, error) {
	kb, err := s.q1aKBs.GetKnowledgeBaseByIDOnly(ctx, id)
	if kb != nil {
		kb.SummaryModelID = map[string]string{"q-wiki": "q-chat", "q-raw": "raw-chat"}[id]
	}
	return kb, err
}

func q2aFixture() (context.Context, *sessionService, *q1aKBs) {
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(7))
	ctx = types.WithCaller(ctx, types.Caller{TenantID: 7, UserID: "viewer", Role: types.TenantRoleViewer})
	source := q2aSources{&q1aSources{}}
	kbs := &q1aKBs{rows: []*types.SearchResult{
		{ID: "q-current", KnowledgeID: "q-doc", KnowledgeBaseID: "q-raw", Content: "fixed material", ImageInfo: "[]"},
		{ID: "q-new", KnowledgeID: "q-doc", KnowledgeBaseID: "q-raw", Content: "different parse", ImageInfo: "[]"},
	}}
	cfg := &config.Config{Conversation: &config.ConversationConfig{Summary: &config.SummaryConfig{}}}
	cfg.Conversation.EmbeddingTopK = 10
	cfg.Conversation.RerankTopK = 10
	events := chatpipeline.NewEventManager()
	chunks := &q1aChunks{repo: &q1aChunkRepo{rows: []*types.Chunk{
		{ID: "q-current", TenantID: 7, KnowledgeID: "q-doc", KnowledgeBaseID: "q-raw", ParseAttempt: 2},
		{ID: "q-new", TenantID: 7, KnowledgeID: "q-doc", KnowledgeBaseID: "q-raw", ParseAttempt: 3},
	}}}
	models := &stubModelService{modelsByID: map[string]*types.Model{
		"q-chat":   {ID: "q-chat", Type: types.ModelTypeKnowledgeQA},
		"raw-chat": {ID: "raw-chat", Type: types.ModelTypeKnowledgeQA},
	}}
	svc := NewSessionService(cfg, nil, nil, kbs, &q1aDocs{}, chunks, models, &q1aTenants{}, events,
		nil, nil, nil, nil, nil, nil, nil, nil, nil, HostSandboxManager{}, nil, nil, nil, nil, nil,
		chatsource.NewResolver(source, source, source, source)).(*sessionService)
	// KnowledgeQA runs CHUNK_SEARCH_PARALLEL, as the production container registers it.
	chatpipeline.NewPluginSearchParallel(events, kbs, svc.knowledgeService, chunks, cfg, nil, svc.tenantService,
		nil, nil, nil, nil, chunks.repo, nil)
	events.Register(q1aPipeline{
		events: []types.EventType{types.CHUNK_MERGE},
		on:     func(_ types.EventType, cm *types.ChatManage) { cm.MergeResult = cm.SearchResult },
	})
	svc.chatSources = svc.chatSources.WithPublished(knowledge.NewService(&publishedReader{}))
	return ctx, svc, kbs
}

type q2aRun struct {
	prompted []*types.SearchResult
	refs     []*types.SearchResult
	answer   *event.AgentFinalAnswerData
	rendered string
	model    string
}

func askQ2a(ctx context.Context, t *testing.T, svc *sessionService, query, model string) q2aRun {
	t.Helper()
	var run q2aRun
	bus := event.NewEventBus()
	bus.On(event.EventAgentReferences, func(_ context.Context, evt event.Event) error {
		run.refs = evt.Data.(event.AgentReferencesData).References.([]*types.SearchResult)
		return nil
	})
	bus.On(event.EventAgentFinalAnswer, func(_ context.Context, evt event.Event) error {
		data := evt.Data.(event.AgentFinalAnswerData)
		run.answer = &data
		return nil
	})
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.INTO_CHAT_MESSAGE},
		on: func(_ types.EventType, cm *types.ChatManage) {
			run.prompted, run.model = cm.MergeResult, cm.ChatModelID
		},
	})
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.CHAT_COMPLETION_STREAM},
		on:     func(_ types.EventType, cm *types.ChatManage) { run.rendered = cm.UserContent },
	})
	require.NoError(t, svc.KnowledgeQA(ctx, &types.QARequest{
		Session: &types.Session{ID: "q-session", TenantID: 7}, SummaryModelID: model, TurnLeaseHeld: true,
		KnowledgeBaseIDs: []string{"q-wiki"}, Query: query,
	}, bus))
	return run
}

func TestQ2aWikiOnlyQuickAnswerAlsoReadsTheSpacesPinnedMaterials(t *testing.T) {
	ctx, svc, kbs := q2aFixture()
	run := askQ2a(ctx, t, svc, "Product field", "q-chat")
	require.Len(t, kbs.seen, 1, "the Space's raw KB is searched once")
	require.Equal(t, []string{"q-doc"}, kbs.seen[0].KnowledgeIDs, "only the release-pinned material is searched")
	require.Equal(t, []string{"release:q-release:E/field", "q-current"}, resultIDs(run.prompted))
	require.Equal(t, "release", run.prompted[0].Metadata["source_tier"])
	require.Equal(t, "raw_text", run.prompted[1].Metadata["source_tier"])
	require.Equal(t, []string{"release:q-release:E/field", "q-current"}, resultIDs(run.refs))
	require.True(t, run.answer == nil || !run.answer.IsFallback, "an answer from sources is not a fallback")
}

func TestQ2aRawMaterialsAnswerWhenNoPublishedFieldMatches(t *testing.T) {
	ctx, svc, _ := q2aFixture()
	run := askQ2a(ctx, t, svc, "unrelated question", "q-chat")
	require.Equal(t, []string{"q-current"}, resultIDs(run.prompted))
	require.Equal(t, []string{"q-current"}, resultIDs(run.refs))
	require.True(t, run.answer == nil || !run.answer.IsFallback)
}

func TestQ2aNothingFoundGivesTheFixedAnswerInsteadOfGeneralKnowledge(t *testing.T) {
	ctx, svc, kbs := q2aFixture()
	kbs.rows = nil
	run := askQ2a(ctx, t, svc, "unrelated question", "q-chat")
	require.Nil(t, run.prompted, "nothing to answer from: no prompt is rendered")
	require.NotNil(t, run.answer)
	require.True(t, run.answer.IsFallback)
	require.Equal(t, chatsource.NotFoundAnswer, run.answer.Content)
}

func TestQ2aTheModelSeesBothSourceTiers(t *testing.T) {
	ctx, svc, _ := q2aFixture()
	svc.cfg.Conversation.Summary.ContextTemplate = "context={{contexts}} query={{query}}"
	chatpipeline.NewPluginIntoChatMessage(svc.eventManager, nil, nil)
	run := askQ2a(ctx, t, svc, "Product field", "q-chat")
	require.Contains(t, run.rendered, "已发布知识（审核过）", "published fields are labelled")
	require.Contains(t, run.rendered, "原文检索（未经编译审核）", "raw passages are labelled")
}

func TestQ2aTheAddedRawKBDoesNotChooseTheModel(t *testing.T) {
	ctx, svc, kbs := q2aFixture()
	svc.knowledgeBaseService = q2aModelKBs{kbs}
	run := askQ2a(ctx, t, svc, "Product field", "")
	require.Equal(t, "q-chat", run.model, "the selected wiki KB's model answers, not the added raw KB's")
}
