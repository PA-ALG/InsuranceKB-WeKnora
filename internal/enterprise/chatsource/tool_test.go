package chatsource_test

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type nativeTool struct{ result *types.ToolResult }

func (nativeTool) Name() string                { return "search_knowledge" }
func (nativeTool) Description() string         { return "native description" }
func (nativeTool) Parameters() json.RawMessage { return json.RawMessage(`{"type":"object"}`) }
func (n nativeTool) Execute(context.Context, json.RawMessage) (*types.ToolResult, error) {
	return n.result, nil
}

func TestWrapToolFiltersEveryExecutionAndRebuildsOutput(t *testing.T) {
	s, h, p, a := fixture()
	r := resolver(s, h, p, a)
	turn, err := r.Resolve(context.Background(), tenant, types.SearchTargets{kb("raw-1"), kb("plain")})
	require.NoError(t, err)
	meta := map[string]interface{}{"keep": "yes"}
	good := map[string]interface{}{
		"chunk_id": "good", "knowledge_id": "k1", "knowledge_base_id": "raw-1",
		"content": "accepted", "metadata": meta, "score": 0.8,
	}
	bad := map[string]interface{}{
		"chunk_id": "bad", "knowledge_id": "k2", "knowledge_base_id": "raw-1", "content": "REMOVED_SECRET",
	}
	plain := map[string]interface{}{
		"faq_id": "plain", "knowledge_id": "p", "knowledge_base_id": "plain",
		"content": "ordinary", "metadata": map[string]interface{}{"plain": true},
	}
	inner := nativeTool{&types.ToolResult{
		Success: true, Output: "accepted REMOVED_SECRET ordinary", Data: map[string]interface{}{
			"results": []map[string]interface{}{good, bad, plain}, "count": 3,
			"kb_counts": map[string]int{"raw-1": 2, "plain": 1}, "mode": "keyword",
		},
	}}
	chunks := chunkRows{rows: []*types.Chunk{
		{ID: "good", TenantID: tenant, KnowledgeID: "k1", KnowledgeBaseID: "raw-1", ParseAttempt: 2},
		{ID: "bad", TenantID: tenant, KnowledgeID: "k2", KnowledgeBaseID: "raw-1", ParseAttempt: 9},
	}}
	tool := chatsource.WrapTool(inner, r, turn, tenant, chunks)
	require.Equal(t, inner.Description(), tool.Description())
	got, err := tool.Execute(context.Background(), json.RawMessage(`{"mode":"keyword"}`))
	require.NoError(t, err)
	require.Equal(t, 2, got.Data["count"])
	require.Equal(t, map[string]int{"raw-1": 1, "plain": 1}, got.Data["kb_counts"])
	rows := got.Data["results"].([]map[string]interface{})
	require.Equal(t, 0.8, rows[0]["score"])
	require.Equal(t,
		map[string]interface{}{"keep": "yes", "source_tier": "raw_text", "release_id": "rel-1"},
		rows[0]["metadata"])
	require.Equal(t, plain, rows[1])
	require.Equal(t, map[string]interface{}{"keep": "yes"}, meta)
	require.Equal(t, 3, inner.result.Data["count"])
	require.NotContains(t, got.Output, "REMOVED_SECRET")
	require.Contains(t, got.Output, "accepted")
	a.current["k1"] = 3
	got, err = tool.Execute(context.Background(), nil)
	require.NoError(t, err)
	require.Equal(t, 1, got.Data["count"])
	require.NotContains(t, got.Output, "accepted")
	require.Equal(t, 1, h.reads["s1"])
	boom := errors.New("unavailable")
	tool = chatsource.WrapTool(inner, r, turn, tenant, chunkRows{err: boom})
	got, err = tool.Execute(context.Background(), nil)
	require.ErrorIs(t, err, boom)
	require.Nil(t, got)
}

func TestWrapToolLeavesOrdinaryTurnUnchanged(t *testing.T) {
	inner := nativeTool{&types.ToolResult{
		Success: true, Output: "native", Data: map[string]interface{}{"results": []interface{}{}},
	}}
	tool := chatsource.WrapTool(inner, nil, chatsource.Turn{}, tenant, nil)
	got, err := tool.Execute(context.Background(), nil)
	require.NoError(t, err)
	require.Same(t, inner.result, got)
}
