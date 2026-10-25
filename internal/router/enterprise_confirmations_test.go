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
	"github.com/Tencent/WeKnora/internal/enterprise/confirm"
	"github.com/Tencent/WeKnora/internal/enterprise/releasestore"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
)

type routerConfirmStore struct {
	confirm.Store
	calls, answers int
	execution      uint64
	answer         confirm.Answer
}

func routerConfirmItem() confirm.Item {
	return confirm.Item{
		ID: "item-a", SpaceID: "space-a", Subject: "k-1", Revision: "1", Title: "t",
		Options: []confirm.Option{{Key: "ignore", Label: "忽略"}},
	}
}

func (s *routerConfirmStore) ListItems(
	ctx context.Context, tenant uint64, space string, _ confirm.Filter,
) ([]confirm.Item, error) {
	s.calls++
	s.execution, _ = types.TenantIDFromContext(ctx)
	if tenant != 7 || space != "space-a" {
		return nil, nil
	}
	return []confirm.Item{routerConfirmItem()}, nil
}

func (s *routerConfirmStore) ItemByID(_ context.Context, tenant uint64, space, id string) (confirm.Item, bool, error) {
	s.calls++
	return routerConfirmItem(), tenant == 7 && space == "space-a" && id == "item-a", nil
}

func (s *routerConfirmStore) AppendAnswer(ctx context.Context, _ uint64, _ string, a confirm.Answer) error {
	s.calls++
	s.answers++
	s.answer = a
	s.execution, _ = types.TenantIDFromContext(ctx)
	return nil
}

func newRouterConfirmations(
	t *testing.T, enabled bool, role types.TenantRole, apiKey bool, lookup *sessionRouteKBLookup,
	shares *routerSpotShares,
) (*gin.Engine, *routerConfirmStore) {
	t.Helper()
	cfg := &config.Config{Tenant: &config.TenantConfig{EnableRBAC: &enabled}}
	spaces, err := releasestore.ParseSpaces(spaceSourceSpaces)
	require.NoError(t, err)
	store := &routerConfirmStore{}
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
		Config: cfg, EnterpriseSpaces: spaces, EnterpriseConfirmations: confirm.NewService(store),
	}, guards)
	guards.assertAPIKeyPoliciesMatchRoutes(router)
	return router, store
}

func confirmationLookup() *sessionRouteKBLookup {
	return &sessionRouteKBLookup{kbs: map[string]*types.KnowledgeBase{
		"raw-a": {ID: "raw-a", TenantID: 8}, "wiki-a": {ID: "wiki-a", TenantID: 9},
	}}
}

func TestEnterpriseConfirmationAnswersNeedAnAdminWithWikiEditRights(t *testing.T) {
	admin, contributor := types.TenantRoleAdmin, types.TenantRoleContributor
	viewer, editor := types.OrgRoleViewer, types.OrgRoleEditor
	for _, tc := range []struct {
		name     string
		rbac     bool
		role     types.TenantRole
		apiKey   bool
		rawShare bool
		wikiRole types.OrgMemberRole
		space    string
		status   int
	}{
		{"admin with Wiki editor answers", true, admin, false, true, editor, "space-a", 201},
		{"owner with Wiki editor answers", true, types.TenantRoleOwner, false, true, editor, "space-a", 201},
		{"contributor is refused", true, contributor, false, true, editor, "space-a", 403},
		{"viewer is refused", true, types.TenantRoleViewer, false, true, editor, "space-a", 403},
		{"admin with only Wiki read is refused", true, admin, false, true, viewer, "space-a", 403},
		{"disabled RBAC still needs Wiki edit rights", false, contributor, false, true, viewer, "space-a", 403},
		{"disabled RBAC still needs an admin: contributor", false, contributor, false, true, editor, "space-a", 403},
		{
			"disabled RBAC still needs an admin: viewer", false, types.TenantRoleViewer, false, true, editor,
			"space-a", 403,
		},
		{"disabled RBAC admin with Wiki editor answers", false, admin, false, true, editor, "space-a", 201},
		{"service keys have no session route", true, types.TenantRoleOwner, true, true, editor, "space-a", 403},
		{"RAW denial stops the answer", true, admin, false, false, editor, "space-a", 403},
		{"unknown Space", true, admin, false, true, editor, "space-z", 404},
	} {
		t.Run(tc.name, func(t *testing.T) {
			shares := &routerSpotShares{roles: map[string]types.OrgMemberRole{"wiki-a": tc.wikiRole}}
			if tc.rawShare {
				shares.roles["raw-a"] = viewer
			}
			router, store := newRouterConfirmations(t, tc.rbac, tc.role, tc.apiKey, confirmationLookup(), shares)
			res := httptest.NewRecorder()
			router.ServeHTTP(res, httptest.NewRequest(http.MethodPost,
				"/api/v1/enterprise/spaces/"+tc.space+"/view/confirmations/item-a/answers",
				strings.NewReader(`{"option_key":"ignore"}`)))
			require.Equal(t, tc.status, res.Code, res.Body.String())
			for _, tenant := range shares.callers {
				require.Equal(t, uint64(7), tenant, "each guard must authorize the original caller")
			}
			if tc.status != 201 {
				require.Zero(t, store.answers)
				require.Zero(t, store.calls, "a refused answer never reaches the store")
				return
			}
			require.Equal(t, 1, store.answers)
			require.Equal(t, "web_user:user-1", store.answer.Answerer)
			require.Equal(t, uint64(7), store.execution, "the original caller's tenant is restored")
		})
	}
}

func TestEnterpriseConfirmationListRequiresBothKBReadPermissions(t *testing.T) {
	for _, denied := range []string{"", "raw-a", "wiki-a"} {
		t.Run(denied, func(t *testing.T) {
			shares := &routerSpotShares{roles: map[string]types.OrgMemberRole{
				"raw-a": types.OrgRoleViewer, "wiki-a": types.OrgRoleViewer,
			}}
			delete(shares.roles, denied)
			lookup := confirmationLookup()
			router, store := newRouterConfirmations(t, false, types.TenantRoleViewer, false, lookup, shares)
			res := httptest.NewRecorder()
			router.ServeHTTP(res, httptest.NewRequest(http.MethodGet,
				"/api/v1/enterprise/spaces/space-a/view/confirmations", nil))
			if denied != "" {
				require.Equal(t, 403, res.Code, res.Body.String())
				require.Zero(t, store.calls)
				return
			}
			require.Equal(t, 200, res.Code, res.Body.String())
			require.Contains(t, res.Body.String(), `"items":[`)
			require.Equal(t, uint64(7), store.execution)
		})
	}
}
