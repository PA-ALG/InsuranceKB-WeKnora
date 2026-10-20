package mcpserver

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/mcptools"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/stretchr/testify/require"
)

func TestPublishedKnowledgeTransportPreservesVerifiedContentWithoutResourceGrants(t *testing.T) {
	f := newResourceURLFixture(t)
	f.ep.RateLimitPerMinute = 100
	srv := NewServer(f.srv.kbService, nil, nil, nil, nil, nil, nil, f.srv.kbShareService,
		f.srv.tenantService, nil, nil, nil, nil, f.srv.resourceCatalog, nil, f.srv.storageResolver)
	output := "The original source says: " + f.ref + " and " + f.path
	data := map[string]any{
		"space_id": "s1", "release_id": "history", "quote": output,
		"results": []map[string]any{{
			"chunk_id": "release:history:member",
			"metadata": map[string]string{"quoted_reference": f.ref, "quoted_path": f.path, "quote": output},
		}},
	}
	wantData, err := json.Marshal(data)
	require.NoError(t, err)
	tools := mcptools.Tools(mcptools.Deps{})
	for i := range tools {
		f.ep.Tools = append(f.ep.Tools, tools[i].Tool.Name)
		// Isolate outbound middleware while retaining actual catalog definitions,
		// endpoint guards, transport, and the real resource-grant repository.
		tools[i].Handler = func(context.Context, mcp.CallToolRequest) (*mcp.CallToolResult, error) {
			return mcp.NewToolResultStructured(data, output), nil
		}
	}
	srv.WithExtraTools(tools)
	r := gin.New()
	r.POST("/mcp/:endpoint_id", func(c *gin.Context) {
		c.Request = c.Request.WithContext(f.ctx)
		c.Next()
	}, gin.WrapH(srv.Handler()))

	for _, tool := range tools {
		t.Run(tool.Tool.Name, func(t *testing.T) {
			response := rpc(t, r, "tools/call", map[string]any{
				"name": tool.Tool.Name, "arguments": map[string]any{},
			})
			result, ok := response["result"].(map[string]any)
			require.True(t, ok)
			require.NotContains(t, result, "isError")
			content := result["content"].([]any)[0].(map[string]any)
			require.Equal(t, output, content["text"], "published Output must remain byte-for-byte unchanged")
			gotData, err := json.Marshal(result["structuredContent"])
			require.NoError(t, err)
			require.JSONEq(t, string(wantData), string(gotData), "quote, rows and metadata must stay unchanged")
		})
	}
	var grants int64
	require.NoError(t, f.db.Model(&types.ResourceAccessGrant{}).Count(&grants).Error)
	require.Zero(t, grants, "reading published content must not mint resource access grants")
	require.Zero(t, f.storage.calls)
	require.Zero(t, f.files.calls)
}
