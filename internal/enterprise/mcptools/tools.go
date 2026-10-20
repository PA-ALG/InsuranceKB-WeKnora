// Package mcptools adapts the shared published-knowledge service to MCP.
package mcptools

import (
	"context"
	"encoding/json"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

// Caller is an authenticated tenant and its endpoint-scoped KB read policy.
type Caller struct {
	TenantID uint64
	Readable func(kbID string) bool
}

// Spaces resolves tenant-owned Space bindings without reading a release.
type Spaces interface {
	SpaceIDs(tenantID uint64) []string
	KnowledgeBases(tenantID uint64, spaceID string) (raw, wiki string, ok bool)
}

// Heads resolves the currently active release once per unpinned call.
type Heads interface {
	ActiveRelease(ctx context.Context, tenantID uint64, spaceID string) (string, error)
}

// Citation contains only verified source content.
type Citation struct {
	Document string
	Page     int
	Quote    string
}

// Citations verifies evidence from an explicitly selected release.
type Citations interface {
	Citation(ctx context.Context, tenantID uint64, spaceID, releaseID, member string, evidence int) (Citation, error)
}

// Deps supplies production services and request identity; absent services fail closed.
type Deps struct {
	Spaces    Spaces
	Heads     Heads
	Knowledge *knowledge.Service
	Citations Citations
	Caller    func(ctx context.Context) (Caller, bool)
}

type argumentSchema struct {
	Type                 string              `json:"type"`
	Properties           map[string]property `json:"properties"`
	Required             []string            `json:"required"`
	AdditionalProperties bool                `json:"additionalProperties"`
}

type property struct {
	Type    string    `json:"type"`
	Items   *property `json:"items,omitempty"`
	Minimum *int      `json:"minimum,omitempty"`
}

// Tools returns the frozen, read-only catalog. Knowledge schemas and execution
// come from the same Agent tools; only the explicit MCP version scope is added.
func Tools(deps Deps) []server.ServerTool {
	out := []server.ServerTool{makeTool(deps, "knowledge_list_spaces",
		"List readable Spaces with their active published release.", argumentSchema{
			Type: "object", Properties: map[string]property{}, Required: []string{},
		})}
	for _, tool := range knowledge.NewTools(deps.Knowledge, 0, nil) {
		var schema argumentSchema
		// These schemas are produced by knowledge.NewTools, not external input.
		if err := json.Unmarshal(tool.Parameters(), &schema); err != nil {
			panic("invalid published knowledge tool schema")
		}
		schema.Properties["release_id"] = property{Type: "string"}
		out = append(out, makeTool(deps, tool.Name(), tool.Description(), schema))
	}
	zero := 0
	out = append(out, makeTool(deps, "knowledge_read_citation",
		"Read verified source evidence from an explicit published release.", argumentSchema{
			Type: "object", Properties: map[string]property{
				"space_id": {Type: "string"}, "release_id": {Type: "string"},
				"member": {Type: "string"}, "evidence": {Type: "integer", Minimum: &zero},
			},
			Required: []string{"space_id", "release_id", "member", "evidence"},
		}))
	return out
}

func makeTool(deps Deps, name, description string, schema argumentSchema) server.ServerTool {
	raw, _ := json.Marshal(schema)
	return server.ServerTool{
		Tool: mcp.NewToolWithRawSchema(name, description, raw),
		Handler: func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
			result, err := execute(ctx, deps, name, schema, request.GetRawArguments())
			if err != nil {
				return errorResult(err), nil
			}
			return result, nil
		},
	}
}
