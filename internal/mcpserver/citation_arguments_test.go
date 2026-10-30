package mcpserver

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/mcptools"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type citationSpaces struct{}

func (citationSpaces) SpaceIDs(uint64) []string { return []string{"s1"} }
func (citationSpaces) KnowledgeBases(uint64, string) (string, string, bool) {
	return "raw", "wiki", true
}

type recordingCitations struct{ indexes []int }

func (c *recordingCitations) Citation(
	_ context.Context, _ uint64, _, _, _ string, index int,
) (mcptools.Citation, error) {
	c.indexes = append(c.indexes, index)
	return mcptools.Citation{Document: "source.pdf", Page: 3, Quote: "verified"}, nil
}

func citationTransport(ep *types.MCPEndpoint, citations *recordingCitations) http.Handler {
	srv := NewServer(nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil)
	srv.WithExtraTools(mcptools.Tools(mcptools.Deps{
		Spaces: citationSpaces{}, Citations: citations,
		Caller: func(context.Context) (mcptools.Caller, bool) {
			return mcptools.Caller{TenantID: 7, Readable: func(string) bool { return true }}, true
		},
	}))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx := context.WithValue(r.Context(), types.MCPEndpointContextKey, ep)
		srv.Handler().ServeHTTP(w, r.WithContext(ctx))
	})
}

func rawToolCall(t *testing.T, handler http.Handler, name, arguments string) map[string]any {
	t.Helper()
	body := fmt.Sprintf(`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":%q,"arguments":%s}}`,
		name, arguments)
	request := httptest.NewRequest(http.MethodPost, "/mcp/ep", bytes.NewBufferString(body))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Accept", "application/json, text/event-stream")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	require.Equal(t, http.StatusOK, response.Code, response.Body.String())
	raw := response.Body.String()
	for _, line := range strings.Split(raw, "\n") {
		if strings.HasPrefix(line, "data:") {
			raw = strings.TrimSpace(strings.TrimPrefix(line, "data:"))
			break
		}
	}
	var envelope struct {
		Result map[string]any `json:"result"`
		Error  map[string]any `json:"error"`
	}
	require.NoError(t, json.Unmarshal([]byte(raw), &envelope))
	if envelope.Error != nil {
		// mcp-go v1 rejects hidden tools before the handler: keep the message.
		return map[string]any{"isError": true, "content": envelope.Error["message"]}
	}
	require.NotNil(t, envelope.Result, raw)
	return envelope.Result
}

func citationArguments(index string) string {
	return `{"space_id":"s1","release_id":"history","member":"member","evidence":` + index + `}`
}

func TestCitationHTTPValidatesSDKDecodedEvidenceIndex(t *testing.T) {
	ep := &types.MCPEndpoint{
		ID: "precise", TenantID: 7, Enabled: true, RateLimitPerMinute: 100,
		Tools: types.StringArray{types.MCPEndpointToolKnowledgeReadCitation},
	}
	citations := &recordingCitations{}
	handler := citationTransport(ep, citations)
	// mcp-go v1 hands the tool the literal JSON number, so only plain integer
	// spellings pass (v0.52 decoded 1.0 / 1e2 to float64 and they passed).
	for _, value := range []string{
		"1.5", "-1", "-0.0", `"1"`, "true", "null", "1000000", "1e6", "9223372036854775808",
		"1.0", "1e2", "1.00000000000000000000000001", "1e-1000000000",
	} {
		result := rawToolCall(t, handler, ep.Tools[0], citationArguments(value))
		require.Equal(t, true, result["isError"], value)
		require.Contains(t, fmt.Sprint(result["content"]), "INVALID_REQUEST", value)
	}
	require.Empty(t, citations.indexes, "invalid decoded values must never reach citation storage")
	for _, tc := range []struct {
		value string
		index int
	}{
		{"0", 0},
		{"1", 1},
		{"100", 100},
		{"999999", 999999},
	} {
		result := rawToolCall(t, handler, ep.Tools[0], citationArguments(tc.value))
		require.NotContains(t, result, "isError", tc.value)
		require.Equal(t, tc.index, citations.indexes[len(citations.indexes)-1])
	}
}

func TestCitationArgumentsStillPassEndpointGuardAndRateLimit(t *testing.T) {
	citations := &recordingCitations{}
	ep := &types.MCPEndpoint{ID: "guarded", TenantID: 7, Enabled: true, RateLimitPerMinute: 1}
	handler := citationTransport(ep, citations)
	hidden := rawToolCall(t, handler, types.MCPEndpointToolKnowledgeReadCitation, citationArguments("0"))
	require.Equal(t, true, hidden["isError"])
	require.Contains(t, fmt.Sprint(hidden["content"]), "not found")
	require.Empty(t, citations.indexes)
	ep.Tools = types.StringArray{types.MCPEndpointToolKnowledgeReadCitation}
	allowed := rawToolCall(t, handler, ep.Tools[0], citationArguments("1"))
	require.NotContains(t, allowed, "isError")
	limited := rawToolCall(t, handler, ep.Tools[0], citationArguments("1.0"))
	require.Contains(t, fmt.Sprint(limited["content"]), "rate limit")
	require.Equal(t, []int{1}, citations.indexes)
}
