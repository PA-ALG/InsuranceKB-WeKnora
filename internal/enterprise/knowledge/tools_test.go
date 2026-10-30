package knowledge_test

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/modelcontext"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func toolContext() context.Context {
	return context.WithValue(context.Background(), types.TenantIDContextKey, tenant)
}

func tool(t *testing.T, service *knowledge.Service, name string, scopes map[string]string) types.Tool {
	t.Helper()
	for _, candidate := range knowledge.NewTools(service, tenant, scopes) {
		if candidate.Name() == name {
			return candidate
		}
	}
	t.Fatalf("missing tool %s", name)
	return nil
}

func TestKnowledgeToolOnlyEvidenceGetsHandlesAndModelKeepsUncitedStates(t *testing.T) {
	s, r := service()
	bound := map[string]string{space: pinned}
	query := tool(t, s, "knowledge_get_fields", bound)
	bound[space] = "new-active"
	result, err := query.Execute(toolContext(), json.RawMessage(`{"entity_id":"1828"}`))
	require.NoError(t, err)
	rows := result.Data["results"].([]map[string]interface{})
	require.Len(t, rows, 1)
	require.Equal(t, "release:rel-3:1828/cooling_off_period", rows[0]["chunk_id"])
	require.Equal(t, map[string]string{
		"source_tier": "release", "space_id": space, "release_id": pinned,
		"logical_slug": "1828/cooling_off_period", "evidence_index": "0",
	}, rows[0]["metadata"])
	registry := modelcontext.NewRegistry(true)
	rendered := registry.ModelToolResultForTool(query.Name(), result)
	require.Contains(t, rendered, `id="chunk://1"`) // v0.9.0 source handle syntax (was c1)
	require.Contains(t, registry.DecodeOutputText(`<ref id="c1"/>`), `chunk_id="release:rel-3:1828/cooling_off_period"`)
	require.Contains(t, rendered, "自签收之日起20日内")
	require.Contains(t, rendered, "90日；意外无等待期")
	require.Contains(t, rendered, "材料明确没有") // QA1 §4.1: Chinese states (updated in the QA1 RED commit)
	require.NotContains(t, rendered, "source:v1:")
	require.NotContains(t, rendered, "release:rel-3:")
	_, err = query.Execute(toolContext(), json.RawMessage(`{"entity_id":"1828"}`))
	require.NoError(t, err)
	require.Equal(t, []read{{tenant, space, pinned}, {tenant, space, pinned}}, r.reads)
	persisted, err := json.Marshal(result.Data)
	require.NoError(t, err)
	require.Contains(t, string(persisted), `"logical_slug":"1828/cooling_off_period"`)
}

func TestKnowledgeToolsRejectOutOfTurnArgumentsBeforeReading(t *testing.T) {
	s, r := service()
	query := tool(t, s, "knowledge_search_fields", map[string]string{space: pinned, "second": "r2"})
	for _, args := range []string{
		`{"query":"日"}`, `{"space_id":"foreign","query":"日"}`,
		`{"space_id":"s1","tenant_id":8}`, `{"space_id":"s1","release_id":"active"}`,
	} {
		_, err := query.Execute(toolContext(), json.RawMessage(args))
		require.Error(t, err)
	}
	foreign := context.WithValue(toolContext(), types.TenantIDContextKey, uint64(8))
	_, err := query.Execute(foreign, json.RawMessage(`{"space_id":"s1","query":"日"}`))
	require.Error(t, err)
	require.Empty(t, r.reads)
}

func TestKnowledgeConceptNotesAreModelGeneratedAndNoEvidenceCannotBeCited(t *testing.T) {
	s, _ := service()
	query := tool(t, s, "knowledge_get_concept", map[string]string{space: pinned})
	result, err := query.Execute(toolContext(), json.RawMessage(`{"name":"犹豫期"}`))
	require.NoError(t, err)
	require.Empty(t, result.Data["results"])
	rendered := modelcontext.NewRegistry(true).ModelToolResultForTool(query.Name(), result)
	require.Contains(t, rendered, "模型补充（概念说明）")
	require.Contains(t, rendered, "甲医疗为15日")
	require.NotContains(t, rendered, "审核过")
	require.NotContains(t, rendered, `<chunk`)
}
