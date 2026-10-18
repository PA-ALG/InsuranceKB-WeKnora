package router

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/releasestore"
	"github.com/Tencent/WeKnora/internal/enterprise/spotcheck"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

const routerSpotPath = "/api/v1/enterprise/spaces/space-a/view/samples"

type routerSpotShares struct {
	interfaces.KBShareService
	roles   map[string]types.OrgMemberRole
	callers []uint64
}

func (s *routerSpotShares) CheckTenantKBPermission(
	_ context.Context, id string, tenant uint64, _ types.TenantRole,
) (types.OrgMemberRole, bool, error) {
	s.callers = append(s.callers, tenant)
	role, ok := s.roles[id]
	return role, ok, nil
}

type routerSpotStore struct {
	spotcheck.Store
	calls, appends    int
	tenant, execution uint64
	caller            types.Caller
	verdict           spotcheck.Verdict
}

func (s *routerSpotStore) observe(ctx context.Context, tenant uint64) {
	s.calls++
	s.tenant = tenant
	s.execution, _ = types.TenantIDFromContext(ctx)
	s.caller = types.CallerFromContext(ctx)
}

func routerSpotSample() spotcheck.Sample {
	return spotcheck.Sample{
		ID: "sample-a", SpaceID: "space-a", ReleaseID: "release-1", LogicalSlug: "visible", Stratum: "a",
	}
}

func (s *routerSpotStore) ListSamples(
	ctx context.Context, tenant uint64, space string, _ spotcheck.Filter,
) ([]spotcheck.Sample, error) {
	s.observe(ctx, tenant)
	if tenant != 7 || space != "space-a" {
		return nil, nil
	}
	return []spotcheck.Sample{routerSpotSample()}, nil
}

func (s *routerSpotStore) SampleByID(
	ctx context.Context, tenant uint64, space, id string,
) (spotcheck.Sample, bool, error) {
	s.observe(ctx, tenant)
	return routerSpotSample(), tenant == 7 && space == "space-a" && id == "sample-a", nil
}

func (s *routerSpotStore) AppendVerdict(ctx context.Context, tenant uint64, _ string, v spotcheck.Verdict) error {
	s.observe(ctx, tenant)
	s.appends++
	s.verdict = v
	return nil
}

func newRouterSpotChecks(
	t *testing.T, enabled, apiKey bool, lookup *sessionRouteKBLookup, shares *routerSpotShares,
) (*gin.Engine, *routerSpotStore, *middleware.APIKeyRouteAuthorizer) {
	t.Helper()
	cfg := &config.Config{Tenant: &config.TenantConfig{EnableRBAC: &enabled}}
	spaces, err := releasestore.ParseSpaces(spaceSourceSpaces)
	require.NoError(t, err)
	releases := &sessionRouteStore{}
	candidates := release.NewService(
		releases, nil, map[string][]byte{"candidate_bundle": []byte(`{"type":"object"}`)},
		release.WithPublisher(releases),
	)
	store := &routerSpotStore{}
	checks := spotcheck.NewService(store, candidates)
	guards := &rbacGuards{cfg: cfg, kbService: lookup, kbShareService: shares}
	router := gin.New()
	router.Use(middleware.ErrorHandler(), func(c *gin.Context) {
		principal := types.Principal{Type: types.PrincipalWebUser, ID: "user-1"}
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(7))
		ctx = context.WithValue(ctx, types.UserIDContextKey, "user-1")
		ctx = context.WithValue(ctx, types.TenantRoleContextKey, types.TenantRoleContributor)
		ctx = types.WithCaller(ctx, types.Caller{TenantID: 7, UserID: "user-1", Role: types.TenantRoleContributor})
		if apiKey {
			principal = types.Principal{Type: types.PrincipalAPITenant, ID: "7"}
			ctx = types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{KeyID: 1, FullAccess: true})
		}
		ctx = types.WithPrincipal(ctx, principal)
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), uint64(7))
		c.Set(types.PrincipalContextKey.String(), principal)
		c.Set(types.UserIDContextKey.String(), "user-1")
		c.Next()
	})
	gate := guards.ensureAPIKeyAuthorizer()
	registerEnterpriseRoutes(router.Group("/api/v1", gate.Middleware()), RouterParams{
		Config: cfg, EnterpriseSpaces: spaces, EnterpriseCandidates: candidates, EnterpriseSpotChecks: checks,
	}, guards)
	guards.assertAPIKeyPoliciesMatchRoutes(router)
	return router, store, gate
}

func TestEnterpriseSpotCheckWritesUseRealWikiEditorPermission(t *testing.T) {
	for _, tc := range []struct {
		name                string
		rbac                bool
		wikiRole            types.OrgMemberRole
		shareRaw, shareWiki bool
		status              int
	}{
		{"shared Viewer cannot decide", true, types.OrgRoleViewer, true, true, 403},
		{"shared Editor can decide", true, types.OrgRoleEditor, true, true, 201},
		{"disabled tenant RBAC does not permit shared Viewer", false, types.OrgRoleViewer, true, true, 403},
		{"disabled tenant RBAC still needs Wiki share", false, types.OrgRoleEditor, true, false, 403},
		{"RAW denial stops write", true, types.OrgRoleEditor, false, true, 403},
	} {
		t.Run(tc.name, func(t *testing.T) {
			lookup := &sessionRouteKBLookup{kbs: map[string]*types.KnowledgeBase{
				"raw-a": {ID: "raw-a", TenantID: 8}, "wiki-a": {ID: "wiki-a", TenantID: 9},
			}}
			shares := &routerSpotShares{roles: map[string]types.OrgMemberRole{}}
			if tc.shareRaw {
				shares.roles["raw-a"] = types.OrgRoleViewer
			}
			if tc.shareWiki {
				shares.roles["wiki-a"] = tc.wikiRole
			}
			router, store, _ := newRouterSpotChecks(t, tc.rbac, false, lookup, shares)
			res := httptest.NewRecorder()
			router.ServeHTTP(res, httptest.NewRequest(
				http.MethodPost, routerSpotPath+"/sample-a/verdicts", strings.NewReader(`{"outcome":"correct"}`),
			))
			require.Equal(t, tc.status, res.Code, res.Body.String())
			for _, tenant := range shares.callers {
				require.Equal(t, uint64(7), tenant, "each guard must authorize the original caller")
			}
			if tc.status != 201 {
				require.Zero(t, store.calls)
				require.Zero(t, store.appends)
				return
			}
			require.Equal(t, 1, store.appends)
			require.Equal(t, uint64(7), store.tenant)
			require.Equal(t, uint64(7), store.execution)
			require.Equal(t, uint64(7), store.caller.TenantID)
			require.Equal(t, "web_user:user-1", store.verdict.Reviewer)
			require.Contains(t, lookup.ids, "raw-a")
			require.Contains(t, lookup.ids, "wiki-a")
			require.Contains(t, lookup.tenants, uint64(8), "a preceding guard must actually change execution scope")
		})
	}
}

func TestEnterpriseSpotCheckSessionListRequiresBothKBReadPermissions(t *testing.T) {
	for _, denied := range []string{"", "raw-a", "wiki-a"} {
		t.Run(denied, func(t *testing.T) {
			lookup := &sessionRouteKBLookup{kbs: map[string]*types.KnowledgeBase{
				"raw-a": {ID: "raw-a", TenantID: 8}, "wiki-a": {ID: "wiki-a", TenantID: 9},
			}}
			shares := &routerSpotShares{roles: map[string]types.OrgMemberRole{
				"raw-a": types.OrgRoleViewer, "wiki-a": types.OrgRoleViewer,
			}}
			delete(shares.roles, denied)
			router, store, _ := newRouterSpotChecks(t, false, false, lookup, shares)
			res := httptest.NewRecorder()
			router.ServeHTTP(res, httptest.NewRequest(http.MethodGet, routerSpotPath, nil))
			if denied != "" {
				require.Equal(t, 403, res.Code, res.Body.String())
				require.Zero(t, store.calls)
				return
			}
			require.Equal(t, 200, res.Code, res.Body.String())
			require.Contains(t, res.Body.String(), `"samples":[`)
			require.Equal(t, uint64(7), store.execution)
		})
	}
}

func TestEnterpriseSpotCheckSessionRoutesRemainUnavailableToAPIKeys(t *testing.T) {
	lookup := &sessionRouteKBLookup{}
	router, store, gate := newRouterSpotChecks(t, true, true, lookup, &routerSpotShares{})
	for _, route := range []struct{ method, path, policy string }{
		{http.MethodGet, routerSpotPath, "/api/v1/enterprise/spaces/:space_id/view/samples"},
		{
			http.MethodPost, routerSpotPath + "/sample-a/verdicts",
			"/api/v1/enterprise/spaces/:space_id/view/samples/:sample_id/verdicts",
		},
	} {
		res := httptest.NewRecorder()
		router.ServeHTTP(res, httptest.NewRequest(route.method, route.path, strings.NewReader(`{"outcome":"correct"}`)))
		require.Equal(t, 403, res.Code, res.Body.String())
		_, declared := gate.Lookup(route.method, route.policy)
		require.False(t, declared)
	}
	res := httptest.NewRecorder()
	router.ServeHTTP(res, httptest.NewRequest(http.MethodGet, "/api/v1/enterprise/spaces/space-a/samples", nil))
	require.Equal(t, 200, res.Code, res.Body.String())
	require.Empty(t, lookup.ids)
	for _, route := range []struct{ method, path string }{
		{http.MethodGet, "/api/v1/enterprise/spaces/:space_id/samples"},
		{http.MethodPost, "/api/v1/enterprise/spaces/:space_id/releases/:release_id/samples"},
	} {
		policy, declared := gate.Lookup(route.method, route.path)
		require.True(t, declared)
		require.True(t, policy.RequireFullAccess)
	}
	require.Zero(t, store.appends)
}

func TestEnterpriseSpotCheckUnknownSpaceStopsBeforeKBAndService(t *testing.T) {
	lookup := &sessionRouteKBLookup{}
	router, store, _ := newRouterSpotChecks(t, true, false, lookup, &routerSpotShares{})
	for _, method := range []string{http.MethodGet, http.MethodPost} {
		path := strings.Replace(routerSpotPath, "space-a", "foreign", 1)
		if method == http.MethodPost {
			path += "/sample-a/verdicts"
		}
		res := httptest.NewRecorder()
		router.ServeHTTP(res, httptest.NewRequest(method, path, strings.NewReader(`{"outcome":"correct"}`)))
		require.Equal(t, 404, res.Code, res.Body.String())
	}
	require.Empty(t, lookup.ids)
	require.Zero(t, store.calls)
}
