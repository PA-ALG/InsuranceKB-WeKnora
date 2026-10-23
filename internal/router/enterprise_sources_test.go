package router

import (
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

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
	_, snapshot, err := ed25519.GenerateKey(nil)
	require.NoError(t, err)
	now := time.Now()
	cfg := &config.Config{
		SchemaWikiSigning: &config.SchemaWikiSigningConfig{
			PublishAuthorizationPublicKeys: []config.SchemaWikiEd25519PublicKeyConfig{publicKey("publish")},
		},
		G3PlatformProcessing: &config.G3PlatformProcessingConfig{
			Enabled: true, TenantID: 7, SpaceID: enterpriseSourceSpaceID,
			RawKBID: "10000000-0000-0000-0000-000000000002", WikiKBID: "10000000-0000-0000-0000-000000000003",
			MachinePrincipalID: "api_tenant:7", APIKeyID: 1, PolicyID: "test-policy", PolicyVersion: "1",
			Mode: "ISOLATED_NOT_FOR_PRODUCTION", NotBefore: now.Add(-time.Hour).Unix(),
			ExpiresAt: now.Add(time.Hour).Unix(), Capabilities: []string{"activate", "create-draft", "review"},
			SystemDecisionKeyID: "system", SystemDecisionPublicKeys: []config.SchemaWikiEd25519PublicKeyConfig{
				publicKey("system"),
			},
			SourceSnapshotSigningKey: config.SchemaWikiEd25519PrivateKeyConfig{
				KeyID: "snapshot", PrivateKeyBase64: base64.RawURLEncoding.EncodeToString(snapshot),
			},
		},
	}
	_, err = config.DecodeG3PlatformProcessing(cfg, now)
	require.NoError(t, err)
	return cfg
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
		if space == "other" {
			require.Zero(t, repo.calls)
		}
	}
	require.Equal(t, 1, repo.calls)
	require.Equal(t, uint64(7), repo.tenant)
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

func TestEnterpriseProductionSourcesRejectOtherTenantAndDisabledCaptureScope(t *testing.T) {
	for _, tc := range []struct {
		mutate func(*config.Config)
		status int
	}{
		{func(c *config.Config) {
			c.G3PlatformProcessing.TenantID++
			c.G3PlatformProcessing.MachinePrincipalID = "api_tenant:8"
		}, http.StatusNotFound},
		{func(c *config.Config) { c.G3PlatformProcessing.Enabled = false }, http.StatusNotFound},
		{func(c *config.Config) { c.G3PlatformProcessing.Mode = "" }, http.StatusBadRequest},
		{func(c *config.Config) { c.G3PlatformProcessing.RawKBID = "" }, http.StatusBadRequest},
		{func(c *config.Config) { c.G3PlatformProcessing = nil }, http.StatusNotFound},
	} {
		cfg := enterpriseSourceConfig(t)
		tc.mutate(cfg)
		repo := &enterpriseSourceRepo{}
		r := enterpriseRouter(t, cfg, repo)
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest(http.MethodGet,
			"/api/v1/enterprise/spaces/"+enterpriseSourceSpaceID+"/sources/source/attempts/2/pages", nil))
		require.Equal(t, tc.status, w.Code, w.Body.String())
		require.Zero(t, repo.calls)
	}
}

func TestEnterpriseProductionRejectsInvalidPolicyLifetimeAfterMount(t *testing.T) {
	for name, invalidate := range map[string]func(*config.G3PlatformProcessingConfig){
		"expired": func(c *config.G3PlatformProcessingConfig) {
			c.ExpiresAt = time.Now().Add(-time.Minute).Unix()
		},
		"not yet active": func(c *config.G3PlatformProcessingConfig) {
			c.NotBefore = time.Now().Add(time.Hour).Unix()
			c.ExpiresAt = time.Now().Add(2 * time.Hour).Unix()
		},
	} {
		t.Run(name, func(t *testing.T) {
			cfg := enterpriseSourceConfig(t)
			repo := &enterpriseSourceRepo{}
			r := enterpriseRouter(t, cfg, repo)
			path := "/api/v1/enterprise/spaces/" + enterpriseSourceSpaceID + "/sources/source/attempts/2/pages"
			valid := httptest.NewRecorder()
			r.ServeHTTP(valid, httptest.NewRequest(http.MethodGet, path, nil))
			require.Equal(t, http.StatusNotFound, valid.Code)
			require.Equal(t, 1, repo.calls)
			repo.calls = 0
			invalidate(cfg.G3PlatformProcessing)
			denied := httptest.NewRecorder()
			r.ServeHTTP(denied, httptest.NewRequest(http.MethodGet, path, nil))
			require.Equal(t, http.StatusBadRequest, denied.Code, denied.Body.String())
			require.Contains(t, denied.Body.String(), "INVALID_REQUEST")
			require.NotContains(t, denied.Body.String(), `"pages"`)
			require.Zero(t, repo.calls, "invalid policy must fail before source lookup")
		})
	}
}
