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
	"github.com/Tencent/WeKnora/internal/enterprise/releasestore"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
)

// The expert-edit route needs a tenant Admin and Wiki editor rights; with the service unset a
// request that passes every guard answers 503, so 503 marks "reached the handler".
func newRouterExpertEdits(
	t *testing.T, enabled bool, role types.TenantRole, apiKey bool, lookup *sessionRouteKBLookup,
	shares *routerSpotShares,
) *gin.Engine {
	t.Helper()
	cfg := &config.Config{Tenant: &config.TenantConfig{EnableRBAC: &enabled}}
	spaces, err := releasestore.ParseSpaces(spaceSourceSpaces)
	require.NoError(t, err)
	guards := &rbacGuards{cfg: cfg, kbService: lookup, kbShareService: shares}
	router := gin.New()
	router.Use(middleware.ErrorHandler(), func(c *gin.Context) {
		principal := types.Principal{Type: types.PrincipalWebUser, ID: "user-1"}
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(7))
		ctx = context.WithValue(ctx, types.UserIDContextKey, "user-1")
		ctx = context.WithValue(ctx, types.TenantRoleContextKey, role)
		ctx = types.WithCaller(ctx, types.Caller{TenantID: 7, UserID: "user-1", Role: role})
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
		Config: cfg, EnterpriseSpaces: spaces,
	}, guards)
	guards.assertAPIKeyPoliciesMatchRoutes(router)
	return router
}

func TestEnterpriseExpertEditsNeedATenantAdminWithWikiEditorRights(t *testing.T) {
	for _, tc := range []struct {
		name     string
		rbac     bool
		role     types.TenantRole
		apiKey   bool
		wikiRole types.OrgMemberRole
		space    string
		status   int
	}{
		{"admin with Wiki editor reaches the handler", true, types.TenantRoleAdmin, false, types.OrgRoleEditor, "space-a", 503},
		{"owner with Wiki editor reaches the handler", true, types.TenantRoleOwner, false, types.OrgRoleEditor, "space-a", 503},
		{"contributor is refused", true, types.TenantRoleContributor, false, types.OrgRoleEditor, "space-a", 403},
		{"admin with Wiki viewer is refused", true, types.TenantRoleAdmin, false, types.OrgRoleViewer, "space-a", 403},
		{"disabled RBAC still refuses a contributor", false, types.TenantRoleContributor, false, types.OrgRoleEditor, "space-a", 403},
		{"service keys have no session route", true, types.TenantRoleOwner, true, types.OrgRoleEditor, "space-a", 403},
		{"unknown Space", true, types.TenantRoleAdmin, false, types.OrgRoleEditor, "space-z", 404},
	} {
		t.Run(tc.name, func(t *testing.T) {
			lookup := &sessionRouteKBLookup{kbs: map[string]*types.KnowledgeBase{
				"raw-a": {ID: "raw-a", TenantID: 8}, "wiki-a": {ID: "wiki-a", TenantID: 9},
			}}
			shares := &routerSpotShares{roles: map[string]types.OrgMemberRole{
				"raw-a": types.OrgRoleViewer, "wiki-a": tc.wikiRole,
			}}
			router := newRouterExpertEdits(t, tc.rbac, tc.role, tc.apiKey, lookup, shares)
			res := httptest.NewRecorder()
			router.ServeHTTP(res, httptest.NewRequest(http.MethodPost,
				"/api/v1/enterprise/spaces/"+tc.space+"/view/expert-edits", strings.NewReader(`{}`)))
			require.Equal(t, tc.status, res.Code, res.Body.String())
			for _, tenant := range shares.callers {
				require.Equal(t, uint64(7), tenant, "each guard must authorize the original caller")
			}
		})
	}
}
