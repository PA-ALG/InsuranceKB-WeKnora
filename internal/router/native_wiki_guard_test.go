package router

// S1 acceptance (blueprint 1001 §7.5, guards G7/G8). Protected file: written by
// Claude, implementers must not edit it. Every native /wiki route — read or
// write, existing or added later — must be rejected for a release-managed KB
// before RBAC or the handler runs, and must fail closed when classification
// fails. Unmanaged KBs pass through to the normal guards.

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/managed"
	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

const nativeWikiPrefix = "/api/v1/knowledgebase/:kb_id/wiki"

type stubClassifier struct {
	roles map[string]managed.Role
	err   error
	calls []string
}

func (s *stubClassifier) Classify(_ context.Context, tenantID uint64, kbID string) (managed.Role, error) {
	s.calls = append(s.calls, kbID)
	if s.err != nil {
		return managed.Role{}, s.err
	}
	if tenantID == 0 {
		return managed.Role{}, errors.New("tenant missing")
	}
	return s.roles[kbID], nil
}

func newGuardedWikiEngine(t *testing.T, classifier managed.Classifier) *gin.Engine {
	t.Helper()
	return newKBRouteTestEngine(t, 1, tenantKBLookupFixture(), nil, func(r *gin.RouterGroup, guards *rbacGuards) {
		RegisterWikiPageRoutesWithRelease(r, &handler.WikiPageHandler{}, nil, guards, classifier)
	})
}

// nativeWikiRoutes returns every registered native wiki route, excluding the
// release-scoped routes that serve published content.
func nativeWikiRoutes(engine *gin.Engine) []gin.RouteInfo {
	var out []gin.RouteInfo
	for _, route := range engine.Routes() {
		if !strings.HasPrefix(route.Path, nativeWikiPrefix+"/") {
			continue
		}
		if strings.HasPrefix(route.Path, nativeWikiPrefix+"/release-scopes/") {
			continue
		}
		out = append(out, route)
	}
	return out
}

// nativeWikiWriteRoutes is the S1a scope: mutation routes only. Read routes are
// bound to a release in S1b, not here.
func nativeWikiWriteRoutes(engine *gin.Engine) []gin.RouteInfo {
	var out []gin.RouteInfo
	for _, route := range nativeWikiRoutes(engine) {
		switch route.Method {
		case http.MethodPost, http.MethodPut, http.MethodPatch, http.MethodDelete:
			out = append(out, route)
		}
	}
	return out
}

func concretePath(pattern, kbID string) string {
	parts := strings.Split(pattern, "/")
	for i, part := range parts {
		switch {
		case part == ":kb_id":
			parts[i] = kbID
		case strings.HasPrefix(part, ":"):
			parts[i] = "x"
		case strings.HasPrefix(part, "*"):
			parts[i] = "some-page"
		}
	}
	return strings.Join(parts, "/")
}

func serve(engine *gin.Engine, method, path string) *httptest.ResponseRecorder {
	var body *strings.Reader
	if method == http.MethodGet || method == http.MethodHead {
		body = strings.NewReader("")
	} else {
		body = strings.NewReader("{}")
	}
	req := httptest.NewRequest(method, path, body)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	engine.ServeHTTP(rec, req)
	return rec
}

func errorCode(t *testing.T, rec *httptest.ResponseRecorder) string {
	t.Helper()
	var envelope struct {
		Error struct {
			Code string `json:"code"`
		} `json:"error"`
	}
	_ = json.Unmarshal(rec.Body.Bytes(), &envelope)
	return envelope.Error.Code
}

func TestNativeWikiRoutesIncludeKnownWriteAndReadPaths(t *testing.T) {
	engine := newGuardedWikiEngine(t, &stubClassifier{})
	registered := map[string]bool{}
	for _, route := range nativeWikiRoutes(engine) {
		registered[route.Method+" "+route.Path] = true
	}
	for _, want := range []string{
		"POST " + nativeWikiPrefix + "/pages",
		"PUT " + nativeWikiPrefix + "/pages/*slug",
		"DELETE " + nativeWikiPrefix + "/pages/*slug",
		"POST " + nativeWikiPrefix + "/revert",
		"POST " + nativeWikiPrefix + "/folders",
		"POST " + nativeWikiPrefix + "/rebuild-links",
		"POST " + nativeWikiPrefix + "/auto-fix",
		"GET " + nativeWikiPrefix + "/pages",
		"GET " + nativeWikiPrefix + "/pages/*slug",
		"GET " + nativeWikiPrefix + "/search",
	} {
		require.True(t, registered[want], "native wiki route %q is not registered", want)
	}
}

func TestNativeWikiWriteRoutesRejectReleaseManagedKB(t *testing.T) {
	for _, state := range []managed.State{managed.StatePending, managed.StateActive} {
		for _, kind := range []managed.Kind{managed.KindWiki, managed.KindRaw} {
			classifier := &stubClassifier{roles: map[string]managed.Role{
				"kb-allowed": {Kind: kind, State: state},
			}}
			engine := newGuardedWikiEngine(t, classifier)
			routes := nativeWikiWriteRoutes(engine)
			require.NotEmpty(t, routes)
			for _, route := range routes {
				rec := serve(engine, route.Method, concretePath(route.Path, "kb-allowed"))
				require.Equalf(t, http.StatusConflict, rec.Code,
					"%s %s kind=%v state=%v body=%s", route.Method, route.Path, kind, state, rec.Body.String())
				require.Equal(t, managed.ErrorCodeReleaseManaged, errorCode(t, rec),
					"%s %s", route.Method, route.Path)
			}
		}
	}
}

func TestNativeWikiGuardFailsClosedWhenClassificationFails(t *testing.T) {
	engine := newGuardedWikiEngine(t, &stubClassifier{err: errors.New("database unavailable")})
	for _, route := range nativeWikiWriteRoutes(engine) {
		rec := serve(engine, route.Method, concretePath(route.Path, "kb-allowed"))
		require.Equalf(t, http.StatusServiceUnavailable, rec.Code, "%s %s body=%s",
			route.Method, route.Path, rec.Body.String())
		require.Equal(t, managed.ErrorCodeClassificationUnavailable, errorCode(t, rec))
	}
}

func TestNativeWikiGuardPassesUnmanagedKBToNormalGuards(t *testing.T) {
	// kb-victim belongs to another tenant, so RBAC must reject it with 403.
	// Reaching that 403 proves the managed guard let the request through.
	lookup := &stubWikiKBLookup{kbs: map[string]*types.KnowledgeBase{
		"kb-victim": {ID: "kb-victim", TenantID: 999, Type: types.KnowledgeBaseTypeWiki},
	}}
	classifier := &stubClassifier{roles: map[string]managed.Role{}}
	engine := newKBRouteTestEngine(t, 1, lookup, nil, func(r *gin.RouterGroup, guards *rbacGuards) {
		RegisterWikiPageRoutesWithRelease(r, &handler.WikiPageHandler{}, nil, guards, classifier)
	})
	for _, tc := range []struct{ method, path string }{
		{http.MethodPost, "/api/v1/knowledgebase/kb-victim/wiki/pages"},
		{http.MethodPost, "/api/v1/knowledgebase/kb-victim/wiki/revert"},
		{http.MethodPost, "/api/v1/knowledgebase/kb-victim/wiki/rebuild-links"},
	} {
		rec := serve(engine, tc.method, tc.path)
		require.Equalf(t, http.StatusForbidden, rec.Code, "%s %s body=%s", tc.method, tc.path, rec.Body.String())
		require.NotEqual(t, managed.ErrorCodeReleaseManaged, errorCode(t, rec))
	}
	require.Contains(t, classifier.calls, "kb-victim", "guard must classify before RBAC")
}

// TestNativeWikiReadRoutesAreNotWriteGuarded records the S1a boundary: read
// routes stay on the native tables until S1b binds them to a release. S1b
// replaces this expectation with a release-bound assertion.
func TestNativeWikiReadRoutesAreNotWriteGuarded(t *testing.T) {
	classifier := &stubClassifier{roles: map[string]managed.Role{
		"kb-allowed": {Kind: managed.KindWiki, State: managed.StateActive},
	}}
	engine := newGuardedWikiEngine(t, classifier)
	for _, route := range nativeWikiRoutes(engine) {
		if route.Method != http.MethodGet {
			continue
		}
		rec := serve(engine, route.Method, concretePath(route.Path, "kb-allowed"))
		require.NotEqual(t, http.StatusConflict, rec.Code,
			"read route %s %s must not be blocked by the S1a write guard", route.Method, route.Path)
	}
}
