package enterprise_test

import (
	"fmt"
	"net/http"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestMountedFixedReleaseReadsRejectInvalidRequestsAndRestrictedKeys(t *testing.T) {
	service := publishService(t, newPublishStore())
	prefix := spacePath + "/releases/"
	full := mountRouter(service, machineKey())
	tenant := uint64(7)
	restricted := mountRouter(service, &types.TenantAPIKey{ID: 1, TenantID: &tenant})
	for _, route := range []struct{ method, path, body string }{
		{http.MethodGet, "active/summary", ""},
		{http.MethodGet, "fixed/member-index", ""},
		{http.MethodPost, "fixed/member-lookup", `{"slugs":["examples/a"]}`},
	} {
		t.Run(route.path, func(t *testing.T) {
			response := request(restricted, route.method, prefix+route.path, "test-key", []byte(route.body))
			require.Equal(t, http.StatusForbidden, response.Code)
		})
	}
	for _, tc := range []struct{ method, path, body string }{
		{http.MethodGet, "active/member-index", ""},
		{http.MethodPost, "active/member-lookup", `{"slugs":["a"]}`},
		{http.MethodPost, "fixed/member-lookup", `{"slugs":["a","a"]}`},
		{http.MethodPost, "fixed/member-lookup", `{"slugs":["a"],"slugs":["b"]}`},
		{http.MethodPost, "fixed/member-lookup", `{"slugs":["a"],"space_id":"elsewhere"}`},
		{http.MethodPost, "fixed/member-lookup", `{"slugs":[]}`},
		{http.MethodPost, "fixed/member-lookup", `{"slugs":["a"," "]}`},
		{http.MethodPost, "fixed/member-lookup", lookupBody(257)},
	} {
		response := request(full, tc.method, prefix+tc.path, "test-key", []byte(tc.body))
		require.Equal(t, http.StatusBadRequest, response.Code, tc.path)
		require.Equal(t, release.ErrorInvalidRequest, code(t, response.Body.Bytes()))
	}
}

func lookupBody(n int) string {
	values := make([]string, n)
	for i := range values {
		values[i] = fmt.Sprintf("%q", fmt.Sprintf("slug/%d", i))
	}
	return `{"slugs":[` + strings.Join(values, ",") + `]}`
}
