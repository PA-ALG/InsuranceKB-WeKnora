package mcpserver

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/mcptools"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type noSpaces struct{}

func (noSpaces) SpaceIDs(uint64) []string { return nil }
func (noSpaces) KnowledgeBases(uint64, string) (string, string, bool) {
	return "", "", false
}

func TestExtraKnowledgeToolsUseCatalogFilterGuardAndRateLimit(t *testing.T) {
	calls := 0
	tools := mcptools.Tools(mcptools.Deps{
		Spaces: noSpaces{},
		Caller: func(context.Context) (mcptools.Caller, bool) {
			calls++
			return mcptools.Caller{TenantID: 7, Readable: func(string) bool { return true }}, true
		},
	})
	srv := NewServer(nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil).
		WithExtraTools(tools)
	ep := &types.MCPEndpoint{
		ID: "extra", TenantID: 7, Enabled: true, RateLimitPerMinute: 1,
		Tools: types.StringArray{"knowledge_list_spaces"},
	}
	r := gin.New()
	r.POST("/mcp/:endpoint_id", func(c *gin.Context) {
		ctx := context.WithValue(c.Request.Context(), types.MCPEndpointContextKey, ep)
		c.Request = c.Request.WithContext(ctx)
		c.Next()
	}, gin.WrapH(srv.Handler()))
	require.Equal(t, []string{"knowledge_list_spaces"}, toolNames(t, rpc(t, r, "tools/list", map[string]any{})))
	hidden := rpc(t, r, "tools/call", map[string]any{"name": "knowledge_get_fields", "arguments": map[string]any{}})
	// mcp-go v1 applies the endpoint tool filter to tools/call as well: a hidden
	// tool is "not found" (a JSON-RPC error) before guardTool runs.
	require.Nil(t, hidden["result"])
	require.NotNil(t, hidden["error"])
	require.Zero(t, calls)
	first := rpc(t, r, "tools/call", map[string]any{"name": "knowledge_list_spaces", "arguments": map[string]any{}})
	require.NotContains(t, first["result"], "isError")
	require.Equal(t, 1, calls)
	second := rpc(t, r, "tools/call", map[string]any{"name": "knowledge_list_spaces", "arguments": map[string]any{}})
	require.Contains(t, second["result"], "isError")
	require.Equal(t, 1, calls)
}

func TestKnowledgeCatalogAppendsToUnchangedOriginalTools(t *testing.T) {
	catalog := types.MCPEndpointToolCatalog()
	var names []string
	for _, def := range catalog {
		names = append(names, def.Name)
	}
	require.Equal(t, []string{
		"list_knowledge_bases", "search_knowledge", "grep_chunks", "list_documents", "read_document",
		"ask", "wiki_search", "wiki_read_page", "wiki_index", "add_document", "update_document", "delete_document",
		"knowledge_list_spaces", "knowledge_find_entity", "knowledge_get_fields", "knowledge_search_fields",
		"knowledge_get_concept", "knowledge_search_pages", "knowledge_read_citation",
	}, names)
	for _, def := range catalog[12:] {
		require.Equal(t, types.MCPEndpointToolGroup("knowledge"), def.Group)
		require.False(t, def.Destructive)
		require.Equal(t, []string{"retrieve"}, types.MCPEndpointCapabilitiesForTools([]string{def.Name}))
	}
}
