package mcptools_test

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/mcptools"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/stretchr/testify/require"
)

func TestInvalidArgumentsNeverReadHeadOrRelease(t *testing.T) {
	for _, args := range []any{
		nil,
		[]any{},
		json.RawMessage(`null`), json.RawMessage(`{} {}`),
		map[string]any{"space_id": "s1", "entity_id": "E", "query": "extra"},
		map[string]any{"space_id": "s1", "entity_id": "E", "fields": nil},
		map[string]any{"space_id": "s1", "entity_id": "E", "fields": []any{1}},
		map[string]any{"space_id": "s1", "entity_id": nil},
		map[string]any{"space_id": "s1", "entity_id": "E", "release_id": nil},
		map[string]any{"space_id": "s1", "entity_id": "E", "release_id": " ACTIVE "},
		map[string]any{"entity_id": "E"},
	} {
		f := setup()
		req := mcp.CallToolRequest{}
		req.Params.Name, req.Params.Arguments = "knowledge_get_fields", args
		result, err := f.tools[req.Params.Name].Handler(endpoint(), req)
		require.NoError(t, err)
		refused(t, result, "INVALID_REQUEST")
		require.Empty(t, f.heads.reads)
		require.Empty(t, f.releases.reads)
	}
}

func TestCitationIndexRejectsInvalidValuesBeforeReadingDependencies(t *testing.T) {
	for _, index := range []any{
		nil, -1, 1.5, "1", true, 1000000, 1e30, json.Number(`1e2`), json.RawMessage(`1e1000000000`),
		json.RawMessage(`1e-1000000000`), json.RawMessage(`1.000000000000000000000000000001`),
	} {
		f := setup()
		refused(t, f.call(endpoint(), t, "knowledge_read_citation", map[string]any{
			"space_id": "s1", "release_id": "rel-1", "member": "E/field", "evidence": index,
		}), "INVALID_REQUEST")
		require.Zero(t, f.citations.calls)
		require.Empty(t, f.heads.reads)
	}
}

func TestCitationAcceptsSDKDecodedZeroForms(t *testing.T) {
	for _, raw := range []json.RawMessage{
		json.RawMessage(`0`), json.RawMessage(`0.0`),
		json.RawMessage(`0e1000000000`), json.RawMessage(`0e-1000000000`),
	} {
		var index any
		require.NoError(t, json.Unmarshal(raw, &index))
		f := setup()
		got := f.call(endpoint(), t, "knowledge_read_citation", map[string]any{
			"space_id": "s1", "release_id": "rel-1", "member": "E/field", "evidence": index,
		})
		require.False(t, got.IsError, text(got))
		require.Equal(t, 1, f.citations.calls)
	}
}

func TestCancelledCallsDoNotReadDependencies(t *testing.T) {
	f := setup()
	ctx, cancel := context.WithCancel(endpoint())
	cancel()
	require.True(t, f.call(ctx, t, "knowledge_list_spaces", map[string]any{}).IsError)
	require.True(t, f.call(ctx, t, "knowledge_get_fields", map[string]any{
		"space_id": "s1", "entity_id": "E",
	}).IsError)
	require.Empty(t, f.heads.reads)
	require.Empty(t, f.releases.reads)
}

type failingHeads struct{ err error }

func (h failingHeads) ActiveRelease(context.Context, uint64, string) (string, error) {
	return "", h.err
}

func TestErrorsNeverExposeDependencyDetails(t *testing.T) {
	for _, err := range []error{
		errors.New("private backend secret"),
		&release.Error{Code: release.ErrorReleaseNotFound, Detail: "private backend secret"},
		&release.Error{Code: "private backend secret", Detail: "private backend secret"},
	} {
		tools := mcptools.Tools(mcptools.Deps{
			Spaces: spaces{"s1": {"raw", "wiki"}}, Heads: failingHeads{err},
			Caller: func(context.Context) (mcptools.Caller, bool) {
				return mcptools.Caller{TenantID: tenant, Readable: func(string) bool { return true }}, true
			},
		})
		req := mcp.CallToolRequest{}
		req.Params.Arguments = map[string]any{}
		result, callErr := tools[0].Handler(endpoint(), req)
		require.NoError(t, callErr)
		require.True(t, result.IsError)
		require.NotContains(t, text(result), "private")
		require.Nil(t, result.StructuredContent)
	}
}

func TestMissingDependenciesFailClosed(t *testing.T) {
	for _, tool := range mcptools.Tools(mcptools.Deps{}) {
		req := mcp.CallToolRequest{}
		req.Params.Arguments = map[string]any{"space_id": "s1"}
		result, err := tool.Handler(endpoint(), req)
		require.NoError(t, err)
		require.True(t, result.IsError)
	}
}
