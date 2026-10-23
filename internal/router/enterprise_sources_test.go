package router

import (
	"context"
	"crypto/ed25519"
	"encoding/base64"
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

const enterpriseSourceSpaceID = "10000000-0000-0000-0000-000000000001"

func enterpriseSourceConfig(t *testing.T) *config.Config {
	t.Helper()
	// Test-only authorities are generated in memory; no deployment settings are loaded.
	publicKey := func(id string) config.SchemaWikiEd25519PublicKeyConfig {
		public, _, err := ed25519.GenerateKey(nil)
		require.NoError(t, err)
		return config.SchemaWikiEd25519PublicKeyConfig{
			KeyID: id, PublicKeyBase64: base64.RawURLEncoding.EncodeToString(public),
		}
	}
	return &config.Config{
		SchemaWikiSigning: &config.SchemaWikiSigningConfig{
			PublishAuthorizationPublicKeys: []config.SchemaWikiEd25519PublicKeyConfig{publicKey("publish")},
		},
	}
}

func TestEnterpriseProductionMountScopesSourcesAndLeavesCandidatesUnavailable(t *testing.T) {
	repo := &enterpriseSourceRepo{}
	r := enterpriseRouter(t, enterpriseSourceConfig(t), repo)
	for _, space := range []string{"other", enterpriseSourceSpaceID} {
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest(http.MethodGet,
			"/api/v1/enterprise/spaces/"+space+"/sources/source/attempts/2/pages", nil))
		require.Equal(t, http.StatusNotFound, w.Code, w.Body.String())
		require.Contains(t, w.Body.String(), "SOURCE_NOT_FOUND")
	}
	require.Zero(t, repo.calls, "a Space missing from ENTERPRISE_SPACES never reads a knowledge base")
	for _, tc := range []struct{ method, path string }{
		{http.MethodPost, "/api/v1/enterprise/spaces/" + enterpriseSourceSpaceID + "/candidates"},
		{http.MethodGet, "/api/v1/enterprise/spaces/" + enterpriseSourceSpaceID + "/candidates/missing/preview"},
	} {
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest(tc.method, tc.path, nil))
		require.Equal(t, http.StatusServiceUnavailable, w.Code)
		require.Contains(t, w.Body.String(), "SERVICE_UNAVAILABLE")
	}
}
