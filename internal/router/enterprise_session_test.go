package router

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/releasestore"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

const sessionRoute = "/api/v1/enterprise/spaces/space-a/view/releases/active"

type sessionRouteKBLookup struct {
	kbs     map[string]*types.KnowledgeBase
	ids     []string
	tenants []uint64
}

func (s *sessionRouteKBLookup) GetKnowledgeBaseByID(ctx context.Context, id string) (*types.KnowledgeBase, error) {
	s.ids = append(s.ids, id)
	tenant, _ := types.TenantIDFromContext(ctx)
	s.tenants = append(s.tenants, tenant)
	if kb := s.kbs[id]; kb != nil {
		return kb, nil
	}
	return nil, repository.ErrKnowledgeBaseNotFound
}

type sessionRouteShares struct {
	interfaces.KBShareService
	allowed map[string]bool
	callers []uint64
}

func (s *sessionRouteShares) CheckTenantKBPermission(
	_ context.Context, id string, tenant uint64, _ types.TenantRole,
) (types.OrgMemberRole, bool, error) {
	s.callers = append(s.callers, tenant)
	return types.OrgRoleViewer, s.allowed[id], nil
}

type sessionRouteStore struct {
	release.Store
	release.Publisher
	tenant, execution uint64
	calls             int
}

func (s *sessionRouteStore) ReleaseByID(
	ctx context.Context, tenant uint64, _, _ string,
) (release.Release, error) {
	s.calls++
	s.tenant = tenant
	s.execution, _ = types.TenantIDFromContext(ctx)
	return release.Release{ID: "release-1", Members: []release.Member{
		{LogicalSlug: "visible", AccessScope: "space"},
		{LogicalSlug: "hidden", AccessScope: "board"},
	}}, nil
}

func newEnterpriseSessionRouter(
	t *testing.T, enabled, apiKey bool, lookup *sessionRouteKBLookup, shares *sessionRouteShares,
) (*gin.Engine, *sessionRouteStore, *middleware.APIKeyRouteAuthorizer) {
	t.Helper()
	cfg := &config.Config{Tenant: &config.TenantConfig{EnableRBAC: &enabled}}
	spaces, err := releasestore.ParseSpaces(spaceSourceSpaces)
	require.NoError(t, err)
	store := &sessionRouteStore{}
	svc := release.NewService(store, nil, map[string][]byte{"candidate_bundle": []byte(`{"type":"object"}`)},
		release.WithPublisher(store))
	g := &rbacGuards{cfg: cfg, kbService: lookup, kbShareService: shares}
	r := gin.New()
	r.Use(middleware.ErrorHandler(), func(c *gin.Context) {
		principal := types.Principal{Type: types.PrincipalWebUser, ID: "user-1"}
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(7))
		ctx = context.WithValue(ctx, types.UserIDContextKey, "user-1")
		ctx = context.WithValue(ctx, types.TenantRoleContextKey, types.TenantRoleViewer)
		ctx = types.WithCaller(ctx, types.Caller{TenantID: 7, UserID: "user-1", Role: types.TenantRoleViewer})
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
	gate := g.ensureAPIKeyAuthorizer()
	registerEnterpriseRoutes(r.Group("/api/v1", gate.Middleware()), RouterParams{
		Config: cfg, EnterpriseSpaces: spaces, EnterpriseCandidates: svc,
	}, g)
	g.assertAPIKeyPoliciesMatchRoutes(r)
	return r, store, gate
}

func TestEnterpriseSessionRoutesRequireBothKBReadGrants(t *testing.T) {
	for _, tc := range []struct {
		name                  string
		rawTenant, wikiTenant uint64
		rbac, shareRaw        bool
		status                int
		lookups               []string
	}{
		{"raw denied", 8, 7, true, false, 403, []string{"raw-a"}},
		{"wiki denied", 7, 8, true, false, 403, []string{"raw-a", "wiki-a"}},
		{"both allowed", 7, 7, true, false, 200, []string{"raw-a", "wiki-a"}},
		{"RBAC disabled still checks RAW", 8, 7, false, false, 403, []string{"raw-a"}},
		{"shared RAW preserves caller", 8, 7, true, true, 200, []string{"raw-a", "wiki-a"}},
		{"shared RAW does not grant wiki", 8, 9, true, true, 403, []string{"raw-a", "wiki-a"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			lookup := &sessionRouteKBLookup{kbs: map[string]*types.KnowledgeBase{
				"raw-a": {ID: "raw-a", TenantID: tc.rawTenant}, "wiki-a": {ID: "wiki-a", TenantID: tc.wikiTenant},
			}}
			shares := &sessionRouteShares{allowed: map[string]bool{"raw-a": tc.shareRaw}}
			r, store, _ := newEnterpriseSessionRouter(t, tc.rbac, false, lookup, shares)
			w := httptest.NewRecorder()
			r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, sessionRoute, nil))
			require.Equal(t, tc.status, w.Code, w.Body.String())
			require.Equal(t, tc.lookups, lookup.ids)
			for _, tenant := range shares.callers {
				require.Equal(t, uint64(7), tenant, "shares use the caller, never a preceding KB's tenant")
			}
			if tc.status != http.StatusOK {
				require.Zero(t, store.calls)
				return
			}
			require.Equal(t, 1, store.calls)
			require.Equal(t, uint64(7), store.tenant)
			require.Equal(t, uint64(7), store.execution)
			require.NotContains(t, w.Body.String(), "hidden")
			if tc.shareRaw {
				require.Equal(t, []uint64{7, 8}, lookup.tenants, "the first guard actually rewrote execution scope")
			}
		})
	}
}

func TestEnterpriseSessionRoutesRemainUndeclaredToAPIKeys(t *testing.T) {
	lookup := &sessionRouteKBLookup{}
	r, store, gate := newEnterpriseSessionRouter(t, true, true, lookup, &sessionRouteShares{})
	for _, path := range []string{"/api/v1/enterprise/spaces", sessionRoute} {
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, path, nil))
		require.Equal(t, http.StatusForbidden, w.Code, w.Body.String())
	}
	_, declared := gate.Lookup(http.MethodGet, "/api/v1/enterprise/spaces/:space_id/view/releases/active")
	require.False(t, declared)
	require.Empty(t, lookup.ids)
	require.Zero(t, store.calls)
}

func TestEnterpriseSessionRejectsUnknownSpacesBeforeKBLookup(t *testing.T) {
	lookup := &sessionRouteKBLookup{}
	r, store, _ := newEnterpriseSessionRouter(t, true, false, lookup, &sessionRouteShares{})
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodGet,
		"/api/v1/enterprise/spaces/foreign/view/releases/active", nil))
	require.Equal(t, http.StatusNotFound, w.Code, w.Body.String())
	require.Empty(t, lookup.ids)
	require.Zero(t, store.calls)
}
