package router

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

type enterpriseSourceRepo struct {
	interfaces.KnowledgeRepository
	calls  int
	tenant uint64
}

func (r *enterpriseSourceRepo) GetKnowledgeByID(_ context.Context, tenant uint64, _ string) (*types.Knowledge, error) {
	r.calls++
	r.tenant = tenant
	return nil, repository.ErrKnowledgeNotFound
}

func (r *enterpriseSourceRepo) GetRevision(context.Context, string, int64) (*types.KnowledgeRevision, error) {
	panic("missing knowledge must stop before revision lookup")
}

func enterpriseRouter(t *testing.T, cfg *config.Config, repo *enterpriseSourceRepo) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		principal := types.Principal{Type: types.PrincipalAPITenant, ID: "7"}
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(7))
		ctx = types.WithPrincipal(ctx, principal)
		ctx = types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{KeyID: 1, FullAccess: true})
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), uint64(7))
		c.Set(types.PrincipalContextKey.String(), principal)
	})
	g := &rbacGuards{}
	v1 := r.Group("/api/v1", g.ensureAPIKeyAuthorizer().Middleware())
	registerEnterpriseRoutes(v1, RouterParams{
		Config: cfg, KnowledgeRepository: repo, FirstParseStore: service.NewG3FirstParseStore(nil),
	}, g)
	g.assertAPIKeyPoliciesMatchRoutes(r)
	for _, path := range []string{
		"/api/v1/enterprise/spaces/:space_id/sources/:knowledge_id/attempts/:attempt/pages",
		"/api/v1/enterprise/spaces/:space_id/candidates/:candidate_id/preview",
	} {
		policy := mustLookupAPIKeyPolicy(t, g, http.MethodGet, path)
		require.True(t, policy.RequireFullAccess)
	}
	return r
}

func enterpriseSourceConfig() *config.Config {
	return &config.Config{G3PlatformProcessing: &config.G3PlatformProcessingConfig{
		Enabled: true, TenantID: 7, SpaceID: "space", RawKBID: "raw", WikiKBID: "wiki",
		Mode: "ISOLATED_NOT_FOR_PRODUCTION",
	}}
}

func TestEnterpriseProductionMountScopesSourcesAndLeavesCandidatesUnavailable(t *testing.T) {
	repo := &enterpriseSourceRepo{}
	r := enterpriseRouter(t, enterpriseSourceConfig(), repo)
	for _, space := range []string{"other", "space"} {
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest(http.MethodGet,
			"/api/v1/enterprise/spaces/"+space+"/sources/source/attempts/2/pages", nil))
		require.Equal(t, http.StatusNotFound, w.Code, w.Body.String())
		require.Contains(t, w.Body.String(), "SOURCE_NOT_FOUND")
		if space == "other" {
			require.Zero(t, repo.calls)
		}
	}
	require.Equal(t, 1, repo.calls)
	require.Equal(t, uint64(7), repo.tenant)
	for _, tc := range []struct{ method, path string }{
		{http.MethodPost, "/api/v1/enterprise/spaces/space/candidates"},
		{http.MethodGet, "/api/v1/enterprise/spaces/space/candidates/missing/preview"},
	} {
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest(tc.method, tc.path, nil))
		require.Equal(t, http.StatusServiceUnavailable, w.Code)
		require.Contains(t, w.Body.String(), "SERVICE_UNAVAILABLE")
	}
}

func TestEnterpriseProductionSourcesRejectOtherTenantAndDisabledCaptureScope(t *testing.T) {
	for _, mutate := range []func(*config.Config){
		func(c *config.Config) { c.G3PlatformProcessing.TenantID++ },
		func(c *config.Config) { c.G3PlatformProcessing.Enabled = false },
		func(c *config.Config) { c.G3PlatformProcessing.Mode = "" },
		func(c *config.Config) { c.G3PlatformProcessing.RawKBID = "" },
		func(c *config.Config) { c.G3PlatformProcessing = nil },
	} {
		cfg := enterpriseSourceConfig()
		mutate(cfg)
		repo := &enterpriseSourceRepo{}
		r := enterpriseRouter(t, cfg, repo)
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest(http.MethodGet,
			"/api/v1/enterprise/spaces/space/sources/source/attempts/2/pages", nil))
		require.Equal(t, http.StatusNotFound, w.Code, w.Body.String())
		require.Zero(t, repo.calls)
	}
}
