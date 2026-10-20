// Q1c acceptance: MCP tools read published knowledge pinned to one release per call (Spec
// docs/design/slices/Q1c-MCP读取已发布知识.md §2, §3). Protected file: written by Claude.
//
// A call reads a Space only when both of its knowledge bases are readable by the endpoint caller;
// without release_id it reads Active once and says which release it used; with release_id it
// reads exactly that release (never "active"); citations need an explicit release. RED until Q1c.
package mcptools_test

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/mcptools"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

const tenant = uint64(7)

type spaces map[string][2]string // space -> raw, wiki

func (s spaces) SpaceIDs(tenantID uint64) []string {
	if tenantID != tenant {
		return nil
	}
	return []string{"s1", "s2", "s3"}
}

func (s spaces) KnowledgeBases(tenantID uint64, spaceID string) (string, string, bool) {
	kbs, ok := s[spaceID]
	return kbs[0], kbs[1], ok && tenantID == tenant
}

type heads struct{ reads map[string]int }

func (h *heads) ActiveRelease(_ context.Context, tenantID uint64, spaceID string) (string, error) {
	h.reads[spaceID]++
	if tenantID != tenant {
		return "", nil
	}
	return map[string]string{"s1": "rel-2", "s2": "rel-9"}[spaceID], nil // s3 has no Active
}

type releases struct{ reads []string }

func (r *releases) ReleaseByID(_ context.Context, tenantID uint64, spaceID, releaseID string) (release.Release, error) {
	r.reads = append(r.reads, spaceID+"/"+releaseID)
	if tenantID != tenant || spaceID != "s1" || (releaseID != "rel-1" && releaseID != "rel-2") {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	return release.Release{ID: releaseID, Members: []release.Member{
		{Kind: "entity", LogicalSlug: "entity/E", AccessScope: "space",
			Payload: json.RawMessage(`{"entity_id":"E","names":["Product"]}`)},
		{Kind: "claim", LogicalSlug: "E/field", AccessScope: "space", Payload: json.RawMessage(
			`{"subject_ref":"E","predicate":"field","state":"present","value":"20 days",` +
				`"origin":"SOURCE_SUPPORTED","evidence":[{"quote":"20 days","locator":{"page":3}}]}`)},
	}}, nil
}

type citations struct{ calls int }

func (c *citations) Citation(
	_ context.Context, tenantID uint64, spaceID, releaseID, member string, evidence int,
) (mcptools.Citation, error) {
	c.calls++
	if tenantID != tenant || spaceID != "s1" || releaseID != "rel-1" || member != "E/field" || evidence != 0 {
		return mcptools.Citation{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	return mcptools.Citation{Document: "条款.pdf", Page: 3, Quote: "20 days"}, nil
}

type fixture struct {
	tools     map[string]server.ServerTool
	names     []string
	heads     *heads
	releases  *releases
	citations *citations
}

type callerKey struct{}

func setup() fixture {
	f := fixture{heads: &heads{reads: map[string]int{}}, releases: &releases{}, citations: &citations{}}
	all := mcptools.Tools(mcptools.Deps{
		Spaces:    spaces{"s1": {"raw-1", "wiki-1"}, "s2": {"raw-2", "wiki-2"}, "s3": {"raw-3", "wiki-3"}},
		Heads:     f.heads,
		Knowledge: knowledge.NewService(f.releases),
		Citations: f.citations,
		Caller: func(ctx context.Context) (mcptools.Caller, bool) {
			caller, ok := ctx.Value(callerKey{}).(mcptools.Caller)
			return caller, ok
		},
	})
	f.tools = map[string]server.ServerTool{}
	for _, tool := range all {
		f.tools[tool.Tool.Name] = tool
		f.names = append(f.names, tool.Tool.Name)
	}
	return f
}

// The caller may read every knowledge base except s2's Wiki base.
func endpoint() context.Context {
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, tenant)
	return context.WithValue(ctx, callerKey{}, mcptools.Caller{
		TenantID: tenant, Readable: func(kb string) bool { return kb != "wiki-2" },
	})
}

func (f fixture) call(t *testing.T, ctx context.Context, name string, args map[string]any) *mcp.CallToolResult {
	t.Helper()
	tool, ok := f.tools[name]
	require.True(t, ok, "missing tool %s", name)
	result, err := tool.Handler(ctx, mcp.CallToolRequest{Params: mcp.CallToolParams{Name: name, Arguments: args}})
	require.NoError(t, err, "tool failures are tool results, not protocol errors")
	require.NotNil(t, result)
	return result
}

func text(result *mcp.CallToolResult) string {
	var parts []string
	for _, content := range result.Content {
		if item, ok := content.(mcp.TextContent); ok {
			parts = append(parts, item.Text)
		}
	}
	return strings.Join(parts, "\n")
}

// structured reads the result as an MCP client does: JSON on the wire, decoded into an object.
func structured(t *testing.T, result *mcp.CallToolResult) map[string]any {
	t.Helper()
	require.False(t, result.IsError, text(result))
	raw, err := json.Marshal(result.StructuredContent)
	require.NoError(t, err)
	var data map[string]any
	require.NoError(t, json.Unmarshal(raw, &data), "structured content must be an object: %s", raw)
	return data
}

func firstRow(t *testing.T, data map[string]any) map[string]any {
	t.Helper()
	rows, ok := data["results"].([]any)
	require.True(t, ok && len(rows) > 0, "results: %v", data["results"])
	return rows[0].(map[string]any)
}

func refused(t *testing.T, result *mcp.CallToolResult, code string) {
	t.Helper()
	require.True(t, result.IsError)
	require.True(t, strings.HasPrefix(text(result), code), "want %s, got %q", code, text(result))
}

func TestToolsAreThePublishedKnowledgeSet(t *testing.T) {
	require.Equal(t, []string{
		"knowledge_list_spaces", "knowledge_find_entity", "knowledge_get_fields", "knowledge_search_fields",
		"knowledge_get_concept", "knowledge_search_pages", "knowledge_read_citation",
	}, setup().names)
}

func TestListSpacesShowsReadableSpacesWithTheirActiveRelease(t *testing.T) {
	f := setup()
	data := structured(t, f.call(t, endpoint(), "knowledge_list_spaces", map[string]any{}))
	require.Equal(t, []any{map[string]any{"space_id": "s1", "release_id": "rel-2"}}, data["spaces"])
}

func TestACallWithoutReleaseReadsActiveOnceAndSaysWhichRelease(t *testing.T) {
	f := setup()
	data := structured(t, f.call(t, endpoint(), "knowledge_get_fields", map[string]any{
		"space_id": "s1", "entity_id": "E",
	}))
	require.Equal(t, 1, f.heads.reads["s1"])
	require.Equal(t, "rel-2", data["release_id"])
	require.Equal(t, "s1", data["space_id"])
	require.Equal(t, "release:rel-2:E/field", firstRow(t, data)["chunk_id"])
	require.Equal(t, []string{"s1/rel-2"}, f.releases.reads)
}

func TestACallWithAReleaseReadsExactlyThatRelease(t *testing.T) {
	f := setup()
	data := structured(t, f.call(t, endpoint(), "knowledge_get_fields", map[string]any{
		"space_id": "s1", "entity_id": "E", "release_id": "rel-1",
	}))
	require.Equal(t, "rel-1", data["release_id"])
	require.Equal(t, "release:rel-1:E/field", firstRow(t, data)["chunk_id"])
	require.Zero(t, f.heads.reads["s1"], "a named release does not read Active")

	for _, alias := range []string{"active", "Active", ""} {
		refused(t, f.call(t, endpoint(), "knowledge_get_fields", map[string]any{
			"space_id": "s1", "entity_id": "E", "release_id": alias,
		}), "INVALID_REQUEST")
	}
	require.Equal(t, []string{"s1/rel-1"}, f.releases.reads, "a refused release is never read")

	result := f.call(t, endpoint(), "knowledge_get_fields", map[string]any{
		"space_id": "s1", "entity_id": "E", "release_id": "rel-other",
	})
	require.True(t, result.IsError, "a release outside the Space is not readable")
}

func TestUnreadableSpacesAndAnonymousCallsAreRefusedBeforeAnyRead(t *testing.T) {
	f := setup()
	for _, space := range []string{"s2", "s9"} {
		refused(t, f.call(t, endpoint(), "knowledge_search_fields", map[string]any{
			"space_id": space, "query": "20",
		}), "RELEASE_ACCESS_DENIED")
	}
	anonymous := context.WithValue(context.Background(), types.TenantIDContextKey, tenant)
	require.True(t, f.call(t, anonymous, "knowledge_list_spaces", map[string]any{}).IsError)
	require.True(t, f.call(t, anonymous, "knowledge_get_fields", map[string]any{
		"space_id": "s1", "entity_id": "E",
	}).IsError)
	require.Empty(t, f.heads.reads)
	require.Empty(t, f.releases.reads)
}

func TestCitationsNeedAnExplicitReleaseAndAReadableSpace(t *testing.T) {
	f := setup()
	refused(t, f.call(t, endpoint(), "knowledge_read_citation", map[string]any{
		"space_id": "s1", "member": "E/field", "evidence": 0,
	}), "INVALID_REQUEST")
	data := structured(t, f.call(t, endpoint(), "knowledge_read_citation", map[string]any{
		"space_id": "s1", "release_id": "rel-1", "member": "E/field", "evidence": 0,
	}))
	require.Equal(t, map[string]any{"document": "条款.pdf", "page": float64(3), "quote": "20 days"}, data)
	refused(t, f.call(t, endpoint(), "knowledge_read_citation", map[string]any{
		"space_id": "s2", "release_id": "rel-9", "member": "E/field", "evidence": 0,
	}), "RELEASE_ACCESS_DENIED")
	require.Equal(t, 1, f.citations.calls)
}
