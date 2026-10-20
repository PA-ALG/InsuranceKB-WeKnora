package service

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/Tencent/WeKnora/internal/agent/tools"
	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type publishedReader struct{ reads int }

func (r *publishedReader) ReleaseByID(_ context.Context, tenant uint64, _ string, id string) (release.Release, error) {
	r.reads++
	if tenant != 7 || id != "q-release" {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseAccessDenied}
	}
	return release.Release{ID: id, Members: []release.Member{
		{
			Kind: "entity", LogicalSlug: "entity/E", AccessScope: "space",
			Payload: json.RawMessage(`{"entity_id":"E","names":["Product"]}`),
		},
		{Kind: "claim", LogicalSlug: "E/field", AccessScope: "space", Payload: json.RawMessage(
			`{"subject_ref":"E","predicate":"field","state":"present","value":"20 days",` +
				`"origin":"SOURCE_SUPPORTED","evidence":[{"quote":"20 days","locator":{"page":3}}]}`)},
	}}, nil
}

func TestQ1bNoWikiKeepsOrdinaryWhitelistWithoutRequiringRetrievalIdentity(t *testing.T) {
	svc := &agentService{}
	registry := tools.NewToolRegistry()
	err := svc.registerTools(context.Background(), registry,
		&types.AgentConfig{AllowedTools: []string{"thinking"}}, nil, nil, "session")
	require.NoError(t, err)
	require.Equal(t, []string{"thinking"}, registry.ListTools())
}

func TestQ1bSelectedWikiDerivesKnowledgeToolsAlongsideFixedRawSearch(t *testing.T) {
	ctx, quick, source, _ := q1aFixture()
	reader := &publishedReader{}
	svc := &agentService{
		cfg: quick.cfg, chatSources: quick.chatSources, knowledgeBaseService: quick.knowledgeBaseService,
		knowledgeService: quick.knowledgeService, chunkService: quick.chunkService,
		publishedKnowledge: knowledge.NewService(reader),
	}
	registry := tools.NewToolRegistry()
	err := svc.registerTools(ctx, registry, &types.AgentConfig{
		AllowedTools: []string{tools.ToolSearchKnowledge}, SearchTargets: types.SearchTargets{
			{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "q-raw", TenantID: 7},
			{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "q-wiki", TenantID: 7},
		},
	}, nil, nil, "session")
	require.NoError(t, err)
	require.Len(t, registry.ListTools(), 6) // five published-knowledge tools (S6e adds pages) and raw search
	query, err := registry.GetTool("knowledge_get_fields")
	require.NoError(t, err)
	result, err := query.Execute(ctx, json.RawMessage(`{"entity_id":"E"}`))
	require.NoError(t, err)
	metadata := result.Data["results"].([]map[string]interface{})[0]["metadata"].(map[string]string)
	require.Equal(t, "release", metadata["source_tier"])
	require.Equal(t, 1, source.reads)
	require.Equal(t, 1, reader.reads)
}
