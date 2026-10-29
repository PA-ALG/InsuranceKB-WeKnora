package service

import (
	"context"
	"errors"
	"sync"
	"testing"

	chatpipeline "github.com/Tencent/WeKnora/internal/application/service/chat_pipeline"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/managed"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/event"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
)

type q1aSources struct {
	reads   int
	err     error
	current int64
}

func (*q1aSources) SpaceOf(tenant uint64, kb string) (string, chatsource.Role, bool) {
	if tenant == 7 && (kb == "q-raw" || kb == "q-wiki") {
		if kb == "q-wiki" {
			return "q-space", chatsource.RoleWiki, true
		}
		return "q-space", chatsource.RoleRaw, true
	}
	return "", "", false
}

func (s *q1aSources) ActiveRelease(context.Context, uint64, string) (string, error) {
	s.reads++
	return "q-release", s.err
}

func (s *q1aSources) ReleaseSources(context.Context, uint64, string, string) ([]chatsource.Pin, error) {
	return []chatsource.Pin{{KnowledgeID: "q-doc", ParseAttempt: 2}}, s.err
}

func (s *q1aSources) CurrentAttempts(context.Context, uint64, []string) (map[string]int64, error) {
	if s.current != 0 {
		return map[string]int64{"q-doc": s.current}, nil
	}
	return map[string]int64{"q-doc": 2}, nil
}

type q1aKBs struct {
	interfaces.KnowledgeBaseService
	mu          sync.Mutex
	seen        []types.SearchParams
	rows        []*types.SearchResult
	missing     bool
	singleErr   error
	singleCalls int
	failAfter   int
	rawWiki     bool
	profile     *types.KnowledgeBaseProfile
}

func (s *q1aKBs) GetKnowledgeBaseByIDOnly(_ context.Context, id string) (*types.KnowledgeBase, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.singleCalls++
	if s.singleErr != nil && id == "q-raw" && (s.failAfter == 0 || s.singleCalls >= s.failAfter) {
		return nil, s.singleErr
	}
	return &types.KnowledgeBase{
		ID: id, TenantID: 7, Type: types.KnowledgeBaseTypeDocument,
		GeneratedProfile: s.profile,
		IndexingStrategy: types.IndexingStrategy{KeywordEnabled: true, WikiEnabled: id == "q-wiki" || s.rawWiki},
	}, nil
}

func (s *q1aKBs) GetKnowledgeBaseByID(ctx context.Context, id string) (*types.KnowledgeBase, error) {
	return s.GetKnowledgeBaseByIDOnly(ctx, id)
}

func (s *q1aKBs) GetKnowledgeBasesByIDsOnly(ctx context.Context, ids []string) ([]*types.KnowledgeBase, error) {
	if s.missing {
		return nil, nil
	}
	var rows []*types.KnowledgeBase
	for _, id := range ids {
		row, _ := s.GetKnowledgeBaseByIDOnly(ctx, id)
		rows = append(rows, row)
	}
	return rows, nil
}

func (*q1aKBs) ResolveEmbeddingModelKeys(context.Context, []*types.KnowledgeBase) map[string]string {
	return nil
}

func (s *q1aKBs) HybridSearch(_ context.Context, _ string, p types.SearchParams) ([]*types.SearchResult, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.seen = append(s.seen, p)
	return s.rows, nil
}

func (*q1aKBs) CheckNativeRead(_ context.Context, id string) error {
	if id == "q-raw" || id == "q-wiki" {
		return &managed.ReadError{Code: managed.ErrorCodeReleaseManaged}
	}
	return nil
}

type q1aDocs struct{ interfaces.KnowledgeService }

func (*q1aDocs) GetKnowledgeBatchWithSharedAccess(context.Context, uint64, []string) ([]*types.Knowledge, error) {
	return []*types.Knowledge{{ID: "q-doc", TenantID: 7, KnowledgeBaseID: "q-raw"}}, nil
}

type q1aTenants struct{ interfaces.TenantService }

func (*q1aTenants) GetTenantByID(context.Context, uint64) (*types.Tenant, error) {
	return &types.Tenant{}, nil
}

type q1aChunkRepo struct {
	interfaces.ChunkRepository
	rows []*types.Chunk
}

func (r *q1aChunkRepo) ListChunksByID(_ context.Context, tenant uint64, ids []string) ([]*types.Chunk, error) {
	var rows []*types.Chunk
	for _, id := range ids {
		for _, row := range r.rows {
			if row.ID == id && row.TenantID == tenant {
				rows = append(rows, row)
			}
		}
	}
	return rows, nil
}

type q1aChunks struct {
	interfaces.ChunkService
	repo *q1aChunkRepo
}

func (s *q1aChunks) GetRepository() interfaces.ChunkRepository { return s.repo }

type q1aPipeline struct {
	events []types.EventType
	on     func(types.EventType, *types.ChatManage)
}

func (p q1aPipeline) ActivationEvents() []types.EventType { return p.events }
func (p q1aPipeline) OnEvent(
	_ context.Context, kind types.EventType, cm *types.ChatManage, next func() *chatpipeline.PluginError,
) *chatpipeline.PluginError {
	p.on(kind, cm)
	return next()
}

func q1aFixture() (context.Context, *sessionService, *q1aSources, *q1aKBs) {
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(7))
	ctx = types.WithCaller(ctx, types.Caller{TenantID: 7, UserID: "viewer", Role: types.TenantRoleViewer})
	source := &q1aSources{}
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
		"q-chat": {ID: "q-chat", Type: types.ModelTypeKnowledgeQA},
	}}
	svc := NewSessionService(cfg, nil, nil, kbs, &q1aDocs{}, chunks, models, &q1aTenants{}, events,
		nil, nil, nil, nil, nil, nil, nil, nil, nil, HostSandboxManager{}, nil, nil, nil, nil, nil,
		chatsource.NewResolver(source, source, source, source)).(*sessionService)
	chatpipeline.NewPluginSearch(events, kbs, svc.knowledgeService, chunks, cfg, nil, svc.tenantService, nil, nil, nil)
	events.Register(q1aPipeline{
		events: []types.EventType{types.CHUNK_MERGE},
		on:     func(_ types.EventType, cm *types.ChatManage) { cm.MergeResult = cm.SearchResult },
	})
	return ctx, svc, source, kbs
}

func TestQ1aSearchKnowledgeUsesFixedTargetsAndDeliversOnlyMatchingChunks(t *testing.T) {
	ctx, svc, source, kbs := q1aFixture()
	rows, err := searchKnowledgeRows(svc, ctx, []string{"q-raw", "q-wiki"}, nil, nil, "question")
	require.NoError(t, err)
	require.Equal(t, 1, source.reads)
	require.Len(t, kbs.seen, 1)
	require.Equal(t, []string{"q-doc"}, kbs.seen[0].KnowledgeIDs)
	require.Len(t, rows, 1)
	require.Equal(t, "q-current", rows[0].ID)
	require.Equal(t, "raw_text", rows[0].Metadata["source_tier"])
	require.Equal(t, "q-release", rows[0].Metadata["release_id"])
	require.Nil(t, kbs.rows[0].Metadata, "retrieval caches are not labelled in place")
}

func TestQ1aQuickWikiOnlyAndDependencyFailuresDoNotRecall(t *testing.T) {
	ctx, svc, source, kbs := q1aFixture()
	_, err := searchKnowledgeRows(svc, ctx, []string{"q-wiki"}, nil, nil, "question")
	var failure *release.Error
	require.ErrorAs(t, err, &failure)
	require.Equal(t, "RELEASE_MANAGED_KB", failure.Code)
	require.Contains(t, err.Error(), "请先选择原始材料库")
	source.err = errors.New("read unavailable")
	_, err = searchKnowledgeRows(svc, ctx, []string{"q-raw"}, nil, nil, "question")
	require.ErrorIs(t, err, source.err)
	require.Empty(t, kbs.seen)
}

func TestQ1aExplicitEnterpriseMissingFromNativeBatchFailsClosed(t *testing.T) {
	ctx, svc, _, kbs := q1aFixture()
	kbs.missing = true
	_, err := searchKnowledgeRows(svc, ctx, []string{"q-raw"}, nil, nil, "question")
	require.Error(t, err)
	require.Empty(t, kbs.seen)
}

func TestQ1aUnmanagedSearchKeepsNativeResultUnlabelled(t *testing.T) {
	ctx, svc, source, kbs := q1aFixture()
	kbs.rows = []*types.SearchResult{{ID: "plain-chunk", KnowledgeID: "plain-doc", Content: "ordinary"}}
	rows, err := searchKnowledgeRows(svc, ctx, []string{"plain"}, nil, nil, "question")
	require.NoError(t, err)
	require.Zero(t, source.reads)
	require.Len(t, rows, 1)
	require.Nil(t, rows[0].Metadata)
}

func TestQ1aKnowledgeQAReferencesAreFilteredBeforePromptAndStream(t *testing.T) {
	ctx, svc, source, kbs := q1aFixture()
	bus := event.NewEventBus()
	var refs []*types.SearchResult
	bus.On(event.EventAgentReferences, func(_ context.Context, evt event.Event) error {
		refs = evt.Data.(event.AgentReferencesData).References.([]*types.SearchResult)
		return nil
	})
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.CHUNK_SEARCH_PARALLEL},
		on:     func(_ types.EventType, cm *types.ChatManage) { cm.SearchResult = kbs.rows },
	})
	var prompted []*types.SearchResult
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.INTO_CHAT_MESSAGE},
		on:     func(_ types.EventType, cm *types.ChatManage) { prompted = cm.MergeResult },
	})
	err := svc.KnowledgeQA(ctx, &types.QARequest{
		Session: &types.Session{ID: "q-session", TenantID: 7}, SummaryModelID: "q-chat", TurnLeaseHeld: true,
		KnowledgeBaseIDs: []string{"q-raw", "q-wiki"}, Query: "question",
	}, bus)
	require.NoError(t, err)
	require.Equal(t, 1, source.reads)
	require.Len(t, prompted, 1)
	require.Len(t, refs, 1)
	require.Equal(t, "q-current", refs[0].ID)
	require.Equal(t, "raw_text", refs[0].Metadata["source_tier"])
}

func TestQ1aFallbackDoesNotListEnterpriseWholeLibrary(t *testing.T) {
	ctx, svc, _, _ := q1aFixture()
	cm := &types.ChatManage{}
	cm.Query = "question"
	cm.FallbackPrompt = "question: {{query}}; documents: {{kb_documents}}"
	cm.SearchTargets = types.SearchTargets{
		{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "q-raw", TenantID: 7},
	}
	cm.KnowledgeBaseIDs = []string{"q-raw"}
	prompt, err := svc.renderFallbackPrompt(ctx, cm)
	require.NoError(t, err)
	require.NotContains(t, prompt, "unreleased secret")
	cm.SearchTargets = types.SearchTargets{
		{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "plain", TenantID: 7},
	}
	cm.KnowledgeBaseIDs = []string{"plain"}
	prompt, err = svc.renderFallbackPrompt(ctx, cm)
	require.NoError(t, err)
	require.Contains(t, prompt, "unreleased secret", "ordinary fallback keeps its document list")
}

func (*q1aDocs) ListKnowledgeByKnowledgeBaseID(context.Context, string) ([]*types.Knowledge, error) {
	return []*types.Knowledge{{
		ID: "unreleased-doc", Title: "unreleased secret title",
		Description: "unreleased secret description", EnableStatus: "enabled",
	}}, nil
}

func TestQ1aQuickReparseAfterPromptAssemblyRemovesOldText(t *testing.T) {
	ctx, svc, source, kbs := q1aFixture()
	turn, err := svc.chatSources.Resolve(ctx, 7, types.SearchTargets{
		{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "q-raw", TenantID: 7},
	})
	require.NoError(t, err)
	ctx = chatsource.WithTurn(ctx, turn, 7)
	cm := &types.ChatManage{}
	cm.Query = "question"
	cm.MergeResult = kbs.rows[:1]
	cm.SummaryConfig.ContextTemplate = "context={{contexts}}; query={{query}}"
	cm.ImageDescription = "image detail"
	cm.QuotedContext = "quoted text"
	cm.EventBus = event.NewEventBus().AsEventBusInterface()
	model := &q1aCaptureChat{}
	svc.modelService = &stubModelService{chatModel: model}
	chatpipeline.NewPluginIntoChatMessage(svc.eventManager, nil, nil)
	chatpipeline.NewPluginChatCompletionStream(svc.eventManager, svc.modelService)
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.INTO_CHAT_MESSAGE},
		on: func(_ types.EventType, cm *types.ChatManage) {
			require.Contains(t, cm.UserContent, "fixed material")
			source.current = 3
		},
	})
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.CHAT_COMPLETION_STREAM},
		on: func(_ types.EventType, cm *types.ChatManage) {
			require.Empty(t, cm.MergeResult)
			require.NotContains(t, cm.UserContent, "fixed material")
			require.Empty(t, cm.RenderedContexts)
			require.Contains(t, cm.UserContent, "question")
			require.Contains(t, cm.UserContent, "image detail")
			require.Contains(t, cm.UserContent, "quoted text")
		},
	})
	require.NoError(t, svc.KnowledgeQAByEvent(ctx, cm, []types.EventType{
		types.INTO_CHAT_MESSAGE, types.CHAT_COMPLETION_STREAM,
	}))
	require.NotEmpty(t, model.messages)
	for _, message := range model.messages {
		require.NotContains(t, message.Content, "fixed material")
	}
}

type q1aAnalysisDocs struct {
	q1aDocs
	reads []string
}

func (d *q1aAnalysisDocs) GetKnowledgeByID(_ context.Context, id string) (*types.Knowledge, error) {
	d.reads = append(d.reads, id)
	return nil, errors.New("offline fixture stops before file access")
}

func TestQ1aQuickAnalysisExcludesEnterpriseAndPreservesRawContext(t *testing.T) {
	for _, file := range []string{"material.csv", "material.xlsx"} {
		t.Run(file, func(t *testing.T) {
			ctx, svc, _, kbs := q1aFixture()
			docs := &q1aAnalysisDocs{}
			svc.knowledgeService = docs
			kbs.rows = kbs.rows[:1]
			kbs.rows[0].KnowledgeFilename, kbs.rows[0].ChunkType = file, string(types.ChunkTypeTableSummary)
			if file == "material.xlsx" {
				kbs.rows = append(kbs.rows, &types.SearchResult{
					ID: "plain-chunk", KnowledgeID: "plain-doc", KnowledgeBaseID: "plain",
					KnowledgeFilename: "ordinary.csv", Content: "ordinary context",
				})
			}
			svc.eventManager.Register(q1aPipeline{
				events: []types.EventType{types.CHUNK_SEARCH_PARALLEL},
				on:     func(_ types.EventType, cm *types.ChatManage) { cm.SearchResult = kbs.rows },
			})
			chatpipeline.NewPluginDataAnalysis(svc.eventManager, nil, nil, docs, nil, nil, nil, nil, nil)
			var delivered []*types.SearchResult
			svc.eventManager.Register(q1aPipeline{
				events: []types.EventType{types.INTO_CHAT_MESSAGE},
				on:     func(_ types.EventType, cm *types.ChatManage) { delivered = cm.MergeResult },
			})
			err := svc.KnowledgeQA(ctx, &types.QARequest{
				Session: &types.Session{ID: "q-session", TenantID: 7}, SummaryModelID: "q-chat", TurnLeaseHeld: true,
				KnowledgeBaseIDs: []string{"q-raw", "plain"}, Query: "question",
				CustomAgent: &types.CustomAgent{
					TenantID: 7, Config: types.CustomAgentConfig{ModelID: "q-chat", DataAnalysisEnabled: true},
				},
			}, event.NewEventBus())
			require.NoError(t, err)
			require.NotContains(t, docs.reads, "q-doc", "native data analysis must not open enterprise files")
			require.NotEmpty(t, delivered)
			require.Equal(t, "fixed material", delivered[0].Content)
			require.Equal(t, "raw_text", delivered[0].Metadata["source_tier"])
			if file == "material.xlsx" {
				require.Equal(t, []string{"plain-doc"}, docs.reads)
				require.Len(t, delivered, 2)
			} else {
				require.Empty(t, docs.reads)
			}
		})
	}
}

// searchKnowledgeRows adapts upstream v0.9.0's SearchKnowledge (options + result
// envelope) to the row assertions these Q1a cases make.
func searchKnowledgeRows(
	svc *sessionService, ctx context.Context, kbIDs, docIDs []string, tags []types.TagScope, query string,
) ([]*types.SearchResult, error) {
	result, err := svc.SearchKnowledge(ctx, kbIDs, docIDs, tags, query, nil)
	if err != nil || result == nil {
		return nil, err
	}
	return result.Results, nil
}
