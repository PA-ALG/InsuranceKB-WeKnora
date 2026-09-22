package router

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type automaticReleaseRouteStub struct{ calls int }

func (s *automaticReleaseRouteStub) CreateBatchConceptDraftAutomated830G3(_ context.Context, _ types.WikiReleasePrincipal, scope types.WikiReleaseScope, id string, _ json.RawMessage) (*types.WikiReleasePreparation, error) {
	s.calls++
	return &types.WikiReleasePreparation{ID: id, WikiReleaseScope: scope}, nil
}
func (s *automaticReleaseRouteStub) ReviewDraftAutomated(context.Context, types.WikiReleasePrincipal, types.WikiReleaseScope, string, []byte) (*types.WikiReleasePreparation, error) {
	s.calls++
	return &types.WikiReleasePreparation{}, nil
}
func (s *automaticReleaseRouteStub) ActivateAutomated(context.Context, types.WikiReleasePrincipal, []byte, []byte) (*types.WikiReleaseReceipt, error) {
	s.calls++
	return &types.WikiReleaseReceipt{}, nil
}

func TestG3PlatformReleaseRoutesRegisterOnlyThreeScopedIngestPosts(t *testing.T) {
	gin.SetMode(gin.TestMode)
	e := gin.New()
	g := &rbacGuards{apiKeyAuthorizer: middleware.NewAPIKeyRouteAuthorizer()}
	access := handler.NewWikiReleaseHandler(nil)
	h := handler.NewG3PlatformReleaseHandler(access, &automaticReleaseRouteStub{}, &automaticReleaseRouteStub{})
	RegisterG3PlatformReleaseRoutes(e.Group("/api/v1"), h, g3PlatformScopeMiddlewareStub{}, access, g)
	prefix := "/api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/platform"
	require.Len(t, e.Routes(), 3)
	for _, suffix := range []string{"/preparations", "/preparations/:preparation_id/review", "/activate"} {
		found := false
		for _, r := range e.Routes() {
			if r.Path == prefix+suffix && r.Method == http.MethodPost {
				found = true
			}
		}
		require.True(t, found, suffix)
		policy, ok := g.apiKeyAuthorizer.Lookup(http.MethodPost, prefix+suffix)
		require.True(t, ok)
		require.Contains(t, policy.Capabilities, types.APIKeyCapabilityIngest)
	}
}

func TestG3PlatformReleaseRoutesRequireRealDualKBEvidenceBeforeService(t *testing.T) {
	for _, denyRaw := range []bool{false, true} {
		t.Run(map[bool]string{false: "authorized", true: "raw unavailable"}[denyRaw], func(t *testing.T) {
			gin.SetMode(gin.TestMode)
			e := gin.New()
			enabled := true
			events := []string{}
			kbs := map[string]*types.KnowledgeBase{"wiki-1": {ID: "wiki-1", TenantID: 42}, "raw-1": {ID: "raw-1", TenantID: 42}}
			if denyRaw {
				delete(kbs, "raw-1")
			}
			g := &rbacGuards{cfg: &config.Config{Tenant: &config.TenantConfig{EnableRBAC: &enabled}}, kbService: &orderedSchemaWikiKBLookup{kbs: kbs, events: &events}, apiKeyAuthorizer: middleware.NewAPIKeyRouteAuthorizer()}
			e.Use(middleware.ErrorHandler())
			e.Use(func(c *gin.Context) {
				terminal := types.Principal{Type: types.PrincipalAPITenant, ID: "42"}
				ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(42))
				ctx = types.WithPrincipal(ctx, terminal)
				ctx = types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{KeyID: 9, KnowledgeBaseIDs: types.StringArray{"raw-1", "wiki-1"}, Capabilities: types.StringArray{"ingest"}})
				c.Request = c.Request.WithContext(ctx)
				c.Set(types.TenantIDContextKey.String(), uint64(42))
				c.Set(types.PrincipalContextKey.String(), terminal)
				c.Next()
			})
			resolver := &schemaWikiRouteScopeResolver{head: &types.WikiReleaseHead{WikiReleaseScope: types.WikiReleaseScope{TenantID: 42, SpaceID: "space-1", RawKBID: "raw-1", WikiKBID: "wiki-1"}, ActiveReleaseID: "parent", ActivationEpoch: 9}, events: &events}
			access := handler.NewWikiReleaseHandler(nil)
			port := &automaticReleaseRouteStub{}
			h := handler.NewG3PlatformReleaseHandler(access, port, port)
			RegisterG3PlatformReleaseRoutes(e.Group("/api/v1"), h, handler.NewSchemaWikiHandler(resolver, nil), access, g)
			r := httptest.NewRecorder()
			q := httptest.NewRequest(http.MethodPost, "/api/v1/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/platform/preparations", strings.NewReader(`{"preparation_id":"draft-1","bundle":{}}`))
			q.Header.Set("Content-Type", "application/json")
			e.ServeHTTP(r, q)
			if denyRaw {
				require.NotEqual(t, http.StatusCreated, r.Code, r.Body.String())
				require.Zero(t, port.calls)
			} else {
				require.Equal(t, http.StatusCreated, r.Code, r.Body.String())
				require.Equal(t, 1, port.calls)
				require.Equal(t, []string{"acl:wiki-1", "resolve", "acl:raw-1"}, events)
			}
		})
	}
}

func TestG3PlatformCompositionRegistersBothGroupsOnlyWhenConfigured(t *testing.T) {
	gin.SetMode(gin.TestMode)
	for _, enabled := range []bool{false, true} {
		e := gin.New()
		g := &rbacGuards{apiKeyAuthorizer: middleware.NewAPIKeyRouteAuthorizer()}
		params := RouterParams{WikiReleaseHandler: handler.NewWikiReleaseHandler(nil), SchemaWikiHandler: &handler.SchemaWikiHandler{}}
		if enabled {
			params.G3PlatformSnapshotsHandler = handler.NewG3PlatformSnapshotsHandler(params.WikiReleaseHandler, nil, nil, nil)
			params.G3PlatformReleaseHandler = handler.NewG3PlatformReleaseHandler(params.WikiReleaseHandler, nil, nil)
		}
		registerConfiguredG3PlatformRoutes(e.Group("/api/v1"), params, g)
		if !enabled {
			require.Empty(t, e.Routes())
			continue
		}
		require.Len(t, e.Routes(), 6)
		prefix := "/api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/platform"
		for _, route := range []struct{ method, path string }{{"GET", "/uploads/:run_id/:ordinal"}, {"POST", "/sources/:knowledge_id/attempts/:attempt/snapshot"}, {"GET", "/bases/:release_id/epochs/:epoch"}, {"POST", "/preparations"}, {"POST", "/preparations/:preparation_id/review"}, {"POST", "/activate"}} {
			_, ok := g.apiKeyAuthorizer.Lookup(route.method, prefix+route.path)
			require.True(t, ok, route.path)
		}
	}
}

func TestG3PlatformCompositionMainRouterRegistersMachineRoutes(t *testing.T) {
	gin.SetMode(gin.TestMode)
	access := handler.NewWikiReleaseHandler(nil)
	engine := NewRouter(RouterParams{Config: &config.Config{}, WikiReleaseHandler: access, SchemaWikiHandler: &handler.SchemaWikiHandler{}, G3PlatformSnapshotsHandler: handler.NewG3PlatformSnapshotsHandler(access, nil, nil, nil), G3PlatformReleaseHandler: handler.NewG3PlatformReleaseHandler(access, nil, nil)})
	found := map[string]bool{}
	for _, route := range engine.Routes() {
		if strings.Contains(route.Path, "/platform/") {
			found[route.Method+" "+route.Path] = true
		}
	}
	require.Len(t, found, 6)
}
