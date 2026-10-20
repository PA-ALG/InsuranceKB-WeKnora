package mcptools_test

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/mcptools"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/stretchr/testify/require"
)

type historicalPublisher struct {
	release.Publisher
	value release.Release
	reads []string
}

func (p *historicalPublisher) ReleaseByID(
	_ context.Context, tenantID uint64, space, id string,
) (release.Release, error) {
	p.reads = append(p.reads, space+"/"+id)
	if tenantID != tenant || space != "s1" || id != p.value.ID {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	return p.value, nil
}

type historicalStore struct{ release.Store }

func historicalKnowledge(t *testing.T) (*knowledge.Service, *historicalPublisher) {
	t.Helper()
	member := func(kind, slug, payload string) release.Member {
		return release.Member{Kind: kind, LogicalSlug: slug, AccessScope: "space", Payload: json.RawMessage(payload)}
	}
	retired := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	members := []release.Member{
		member("entity", "entity/E", `{"entity_id":"E","names":["Product"]}`),
		member("claim", "E/field", `{"subject_ref":"E","predicate":"field","state":"present","value":"20 days",
			"origin":"SOURCE_SUPPORTED","evidence":[{"quote":"20 days","locator":{"page":3}}]}`),
		member("concept", "concept/period", `{"concept_key":"period","title":"Period","origin":"MODEL_GENERATED",
			"definition":"Duration","statements":[{"text":"20 days","refs":["E/field"]}]}`),
		member("wiki_page", "wiki/E/period", `{"page_key":"period","entity_refs":["E"],"title":"Period",
			"page_type":"concept","origin":"MODEL_GENERATED","content":"20 days explanation",
			"evidence":[{"quote":"20 days","locator":{"page":3}}]}`),
	}
	publisher := &historicalPublisher{value: release.Release{ID: "history", RetiredAt: &retired, Members: members}}
	service := release.NewService(&historicalStore{}, nil, nil, release.WithPublisher(publisher))
	return knowledge.NewService(knowledge.NewReleaseReader(service)), publisher
}

func TestAllFiveToolsPreserveAgentDataAndOutputForExplicitRetiredRelease(t *testing.T) {
	service, publisher := historicalKnowledge(t)
	ctx, _ := authenticatedEndpoint()
	heads := &heads{reads: map[string]int{}}
	tools := mcptools.Tools(mcptools.Deps{
		Spaces: spaces{"s1": {"raw", "wiki"}}, Heads: heads, Knowledge: service,
		Caller: func(context.Context) (mcptools.Caller, bool) {
			return mcptools.Caller{TenantID: tenant, Readable: func(string) bool { return true }}, true
		},
	})
	cases := []struct {
		name string
		args map[string]any
	}{
		{"knowledge_find_entity", map[string]any{"query": "Product"}},
		{"knowledge_get_fields", map[string]any{"entity_id": "E", "fields": []string{"field"}}},
		{"knowledge_search_fields", map[string]any{"query": "20"}},
		{"knowledge_get_concept", map[string]any{"name": "Period"}},
		{"knowledge_search_pages", map[string]any{"query": "explanation", "entity_id": "E"}},
	}
	agentTools := knowledge.NewTools(service, tenant, map[string]string{"s1": "history"})
	for i, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			tc.args["space_id"] = "s1"
			raw, err := json.Marshal(tc.args)
			require.NoError(t, err)
			want, err := agentTools[i].Execute(ctx, raw)
			require.NoError(t, err)
			require.True(t, want.Success)
			tc.args["release_id"] = "history"
			req := mcp.CallToolRequest{}
			req.Params.Name, req.Params.Arguments = tc.name, tc.args
			got, err := tools[i+1].Handler(ctx, req)
			require.NoError(t, err)
			require.False(t, got.IsError, text(got))
			require.Equal(t, want.Output, text(got))
			want.Data["space_id"], want.Data["release_id"] = "s1", "history"
			require.Equal(t, want.Data, got.StructuredContent, "all rows, IDs, metadata and extra keys survive")
			if tc.name != "knowledge_find_entity" {
				require.NotEmpty(t, firstRow(t, structured(t, got))["metadata"])
			}
		})
	}
	require.Empty(t, heads.reads, "an explicit retired release never resolves Active")
	require.Len(t, publisher.reads, 10)
	for _, read := range publisher.reads {
		require.Equal(t, "s1/history", read)
	}
}

func TestKnowledgeNotFoundCodesRemainTyped(t *testing.T) {
	f := setup()
	for _, tc := range []struct {
		name, key, code string
	}{
		{"knowledge_get_fields", "entity_id", "ENTITY_NOT_FOUND"},
		{"knowledge_get_concept", "name", "CONCEPT_NOT_FOUND"},
	} {
		refused(t, f.call(endpoint(), t, tc.name, map[string]any{
			"space_id": "s1", "release_id": "rel-1", tc.key: "missing",
		}), tc.code)
	}
}

func TestInheritedEmptyStringArgumentsKeepAgentSemantics(t *testing.T) {
	cases := []struct {
		name, key string
	}{
		{"knowledge_find_entity", "query"},
		{"knowledge_get_fields", "entity_id"},
		{"knowledge_search_fields", "query"},
		{"knowledge_get_concept", "name"},
		{"knowledge_search_pages", "query"},
	}
	for _, value := range []string{"", "   "} {
		for i, tc := range cases {
			t.Run(tc.name+"/"+value, func(t *testing.T) {
				f := setup()
				agentTools := knowledge.NewTools(knowledge.NewService(f.releases), tenant,
					map[string]string{"s1": "rel-1"})
				args := map[string]any{"space_id": "s1", tc.key: value}
				raw, err := json.Marshal(args)
				require.NoError(t, err)
				want, wantErr := agentTools[i].Execute(endpoint(), raw)
				args["release_id"] = "rel-1"
				got := f.call(endpoint(), t, tc.name, args)
				if wantErr != nil {
					var failure *release.Error
					require.True(t, errors.As(wantErr, &failure))
					refused(t, got, failure.Code)
					return
				}
				require.False(t, got.IsError, text(got))
				require.Equal(t, want.Output, text(got))
				want.Data["space_id"], want.Data["release_id"] = "s1", "rel-1"
				require.Equal(t, want.Data, got.StructuredContent)
			})
		}
	}
}

type unorderedSpaces struct{}

func (unorderedSpaces) SpaceIDs(uint64) []string { return []string{"z", "blocked", "a", "empty"} }
func (unorderedSpaces) KnowledgeBases(_ uint64, id string) (string, string, bool) {
	return "raw-" + id, "wiki-" + id, true
}

type listedHeads struct{ reads []string }

func (h *listedHeads) ActiveRelease(_ context.Context, _ uint64, space string) (string, error) {
	h.reads = append(h.reads, space)
	if space == "empty" {
		return "", nil
	}
	return "release-" + space, nil
}

func TestListSortsReadableActiveSpacesWithoutTouchingForbiddenHead(t *testing.T) {
	h := &listedHeads{}
	tools := mcptools.Tools(mcptools.Deps{
		Spaces: unorderedSpaces{}, Heads: h,
		Caller: func(context.Context) (mcptools.Caller, bool) {
			return mcptools.Caller{
				TenantID: tenant,
				Readable: func(kb string) bool { return kb != "wiki-blocked" },
			}, true
		},
	})
	req := mcp.CallToolRequest{}
	got, err := tools[0].Handler(endpoint(), req)
	require.NoError(t, err)
	require.Equal(t, []any{
		map[string]any{"space_id": "a", "release_id": "release-a"},
		map[string]any{"space_id": "z", "release_id": "release-z"},
	}, structured(t, got)["spaces"])
	require.Equal(t, []string{"a", "empty", "z"}, h.reads)
}

func TestMissingActiveIsReleaseNotFoundWithoutReadingRelease(t *testing.T) {
	f := setup()
	refused(t, f.call(endpoint(), t, "knowledge_get_fields", map[string]any{
		"space_id": "s3", "entity_id": "E",
	}), release.ErrorReleaseNotFound)
	require.Equal(t, 1, f.heads.reads["s3"])
	require.Empty(t, f.releases.reads)
}
