package service

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/agent/tools"
	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestQ1aAgentRawOnlyOffersSearchAndReusesTurnForEveryCall(t *testing.T) {
	ctx, quick, source, kbs := q1aFixture()
	kbs.rawWiki = true
	quick.cfg.Conversation.KeywordThreshold = 0.15
	svc := &agentService{
		cfg: quick.cfg, knowledgeBaseService: quick.knowledgeBaseService,
		knowledgeService: quick.knowledgeService, chunkService: quick.chunkService, chatSources: quick.chatSources,
	}
	config := &types.AgentConfig{SearchTargets: types.SearchTargets{
		{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "q-wiki", TenantID: 7},
		{
			Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "q-raw", TenantID: 7,
			TagIDs: []string{"physical-tag"}, ScopeTagIDs: []string{"logical-tag"},
		},
	}, AllowedTools: []string{
		tools.ToolSearchKnowledge, tools.ToolReadDocument, tools.ToolListDocuments,
		tools.ToolDatabaseQuery, tools.ToolDataAnalysis, tools.ToolDataSchema,
		tools.ToolWikiReadPage, tools.ToolWikiSearch,
	}}
	registry := tools.NewToolRegistry()
	require.NoError(t, svc.registerTools(ctx, registry, config, nil, nil, "session"))
	require.ElementsMatch(t, []string{
		tools.ToolSearchKnowledge, "knowledge_find_entity", "knowledge_get_fields",
		"knowledge_search_fields", "knowledge_get_concept", "knowledge_search_pages",
	}, registry.ListTools())
	search, err := registry.GetTool(tools.ToolSearchKnowledge)
	require.NoError(t, err)
	for range 2 {
		result, err := search.Execute(ctx, json.RawMessage(`{"query":"question","mode":"keyword"}`))
		require.NoError(t, err)
		require.True(t, result.Success)
		rows := result.Data["results"].([]map[string]interface{})
		require.Len(t, rows, 1)
		require.Equal(t, "q-current", rows[0]["chunk_id"])
		metadata := rows[0]["metadata"].(map[string]interface{})
		require.Equal(t, "raw_text", metadata["source_tier"])
		require.Equal(t, "q-release", metadata["release_id"])
		require.NotContains(t, result.Output, "different parse")
	}
	require.Equal(t, 1, source.reads)
	require.Len(t, kbs.seen, 2)
	for _, params := range kbs.seen {
		require.Equal(t, []string{"q-doc"}, params.KnowledgeIDs)
		require.Equal(t, []string{"physical-tag"}, params.TagIDs)
		require.Equal(t, []string{"logical-tag"}, params.ScopeTagIDs)
		require.Equal(t, 0.15, params.KeywordThreshold)
	}
	require.Len(t, config.SearchTargets, 2, "stored configuration was not rewritten")
}

func TestQ1aAgentMixedScopeDoesNotExposeEnterpriseToDocumentTools(t *testing.T) {
	ctx, quick, _, _ := q1aFixture()
	svc := &agentService{
		cfg: quick.cfg, knowledgeBaseService: quick.knowledgeBaseService,
		knowledgeService: quick.knowledgeService, chunkService: quick.chunkService,
		chatSources: quick.chatSources, managedKBs: unmanagedKBs{},
	}
	registry := tools.NewToolRegistry()
	require.NoError(t, svc.registerTools(ctx, registry, &types.AgentConfig{SearchTargets: types.SearchTargets{
		{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "q-raw", TenantID: 7},
		{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "plain", TenantID: 7},
	}, AllowedTools: []string{tools.ToolSearchKnowledge, tools.ToolReadDocument}}, nil, nil, "session"))
	reader, err := registry.GetTool(tools.ToolReadDocument)
	require.NoError(t, err, "ordinary targets keep their document tool")
	_, err = reader.Execute(ctx, json.RawMessage(`{"id":"q-doc"}`))
	require.Error(t, err, "the document tool must not reach the enterprise target")
}

func TestQ1bAgentWikiOnlyRegistersPublishedKnowledgeTools(t *testing.T) {
	ctx, quick, source, _ := q1aFixture()
	svc := &agentService{
		publishedKnowledge: knowledge.NewService(nil),
		cfg:                quick.cfg, knowledgeBaseService: quick.knowledgeBaseService, chatSources: quick.chatSources,
	}
	registry := tools.NewToolRegistry()
	require.NoError(t, svc.registerTools(ctx, registry, &types.AgentConfig{
		KnowledgeBases: []string{"q-wiki"},
		SearchTargets: types.SearchTargets{
			{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "q-wiki", TenantID: 7},
		},
		AllowedTools: []string{
			tools.ToolSearchKnowledge, tools.ToolReadDocument, tools.ToolWikiReadPage, tools.ToolWikiSearch,
		},
	}, nil, nil, "session"))
	require.ElementsMatch(t, []string{
		"knowledge_find_entity", "knowledge_get_fields", "knowledge_search_fields", "knowledge_get_concept",
		"knowledge_search_pages",
	}, registry.ListTools())
	require.Equal(t, 1, source.reads)
}

func TestQ1aAgentEnterpriseMetadataFailureStopsTurn(t *testing.T) {
	ctx, quick, _, kbs := q1aFixture()
	kbs.singleErr = errors.New("metadata unavailable")
	svc := &agentService{cfg: quick.cfg, knowledgeBaseService: kbs, chatSources: quick.chatSources}
	err := svc.registerTools(ctx, tools.NewToolRegistry(), &types.AgentConfig{SearchTargets: types.SearchTargets{
		{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "q-raw", TenantID: 7},
	}, AllowedTools: []string{tools.ToolSearchKnowledge}}, nil, nil, "session")
	require.ErrorIs(t, err, kbs.singleErr)
}

func TestQ1aAgentReusesResolvedKBMetadataForCapabilities(t *testing.T) {
	ctx, quick, _, kbs := q1aFixture()
	kbs.singleErr, kbs.failAfter = errors.New("later metadata unavailable"), 2
	svc := &agentService{
		cfg: quick.cfg, knowledgeBaseService: kbs, knowledgeService: quick.knowledgeService,
		chunkService: quick.chunkService, chatSources: quick.chatSources,
	}
	registry := tools.NewToolRegistry()
	err := svc.registerTools(ctx, registry, &types.AgentConfig{SearchTargets: types.SearchTargets{
		{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "q-raw", TenantID: 7},
	}, AllowedTools: []string{tools.ToolSearchKnowledge}}, nil, nil, "session")
	require.NoError(t, err)
	require.Equal(t, []string{tools.ToolSearchKnowledge}, registry.ListTools())
	require.Equal(t, 1, kbs.singleCalls)
}

func TestQ1aAgentPromptDoesNotReadUnfixedMetadata(t *testing.T) {
	ctx, quick, source, kbs := q1aFixture()
	kbs.profile = &types.KnowledgeBaseProfile{Gist: "unreleased secret profile"}
	svc := &agentService{
		cfg: quick.cfg, knowledgeBaseService: kbs, knowledgeService: &q1aDocs{},
		chunkService: quick.chunkService, chatSources: quick.chatSources,
	}
	model := &q1aCaptureChat{}
	engine, err := svc.CreateAgentEngine(ctx, &types.AgentConfig{
		KnowledgeBases: []string{"q-raw", "q-wiki"},
		SearchTargets: types.SearchTargets{
			{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "q-raw", TenantID: 7},
			{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "q-wiki", TenantID: 7},
		}, QuestionOrigin: &types.QuestionOrigin{KnowledgeBaseID: "q-raw", KnowledgeID: "unreleased-doc"},
		AllowedTools: []string{tools.ToolSearchKnowledge},
	}, model, nil, nil, "session", "message")
	require.NoError(t, err)
	_, err = engine.Execute(ctx, "session", "message", "question", nil)
	require.NoError(t, err)
	require.NotContains(t, model.lastSystemPrompt, "unreleased secret")
	for _, message := range model.messages {
		require.NotContains(t, message.Content, "unreleased secret")
	}
	require.Contains(t, model.lastSystemPrompt, "已发布知识优先") // Q1b replaced the Q1a "not yet available" notice
	require.Equal(t, 1, source.reads)
}

type q1aCaptureChat struct {
	fakeAgentChatModel
	messages []chat.Message
}

func (m *q1aCaptureChat) ChatStream(
	ctx context.Context, messages []chat.Message, opts *chat.ChatOptions,
) (<-chan types.StreamResponse, error) {
	m.messages = messages
	return m.fakeAgentChatModel.ChatStream(ctx, messages, opts)
}

func (*q1aDocs) ListPagedKnowledgeByKnowledgeBaseID(
	_ context.Context, _ string, p *types.Pagination, _ types.KnowledgeListFilter,
) (*types.PageResult, error) {
	return types.NewPageResult(1, p, []*types.Knowledge{{ID: "unreleased-doc", Title: "unreleased secret title"}}), nil
}

func (s *q1aDocs) GetKnowledgeByID(_ context.Context, id string) (*types.Knowledge, error) {
	return &types.Knowledge{ID: id, TenantID: 7, KnowledgeBaseID: "q-raw"}, nil
}

func (s *q1aDocs) GetKnowledgeByIDOnly(ctx context.Context, id string) (*types.Knowledge, error) {
	return s.GetKnowledgeByID(ctx, id)
}
