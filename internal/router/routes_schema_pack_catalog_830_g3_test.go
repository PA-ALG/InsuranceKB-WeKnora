package router

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

func TestSchemaPackCatalog830G3AuthorizedRouteReturnsCatalog(t *testing.T) {
	t.Parallel()
	events := []string{}
	access := &schemaWikiRouteAccessMiddlewareSpy{events: &events}
	resolver := &schemaWikiRouteScopeResolver{events: &events, head: &types.WikiReleaseHead{
		WikiReleaseScope: types.WikiReleaseScope{
			TenantID: 10003, SpaceID: "space-g3", RawKBID: "raw-g3", WikiKBID: "wiki-g3",
		},
		ActiveReleaseID: "release-g2-published",
		ActivationEpoch: 5,
	}}
	engine := newSchemaWikiScopeRouteEngine(
		t,
		resolver,
		nil,
		map[string]*types.KnowledgeBase{
			"wiki-g3": {ID: "wiki-g3", TenantID: 10003, Type: types.KnowledgeBaseTypeWiki},
			"raw-g3":  {ID: "raw-g3", TenantID: 10003},
		},
		&events,
		access,
	)

	response := httptest.NewRecorder()
	request := httptest.NewRequest(
		http.MethodGet,
		"/api/v1/knowledgebase/wiki-g3/wiki/release-scopes/space-g3/raw/raw-g3/schema/catalogs/schema_catalog_insurance_product/versions/2026-08-12-v5",
		nil,
	)
	engine.ServeHTTP(response, request)

	require.Equal(t, http.StatusOK, response.Code, "body=%s", response.Body.String())
	require.Contains(t, response.Header().Get("Cache-Control"), "private")
	require.Contains(t, response.Header().Get("Cache-Control"), "no-store")
	require.Equal(t, 1, access.sealCalls)
	require.Equal(t, []string{
		"acl:wiki-g3", "evidence:wiki", "resolve", "acl:raw-g3", "evidence:raw", "seal", "handler",
	}, events)
}

func TestSchemaPackCatalog830G3RouteFailsClosed(t *testing.T) {
	t.Parallel()
	path := "/api/v1/knowledgebase/wiki-g3/wiki/release-scopes/space-g3/raw/raw-g3/schema/catalogs/schema_catalog_insurance_product/versions/2026-08-12-v5"
	head := &types.WikiReleaseHead{WikiReleaseScope: types.WikiReleaseScope{
		TenantID: 10003, SpaceID: "space-g3", RawKBID: "raw-g3", WikiKBID: "wiki-g3",
	}, ActiveReleaseID: "release-g2-published", ActivationEpoch: 5}
	for name, kbs := range map[string]map[string]*types.KnowledgeBase{
		"missing wiki ACL": {"raw-g3": {ID: "raw-g3", TenantID: 10003}},
		"missing raw ACL":  {"wiki-g3": {ID: "wiki-g3", TenantID: 10003, Type: types.KnowledgeBaseTypeWiki}},
	} {
		t.Run(name, func(t *testing.T) {
			events := []string{}
			access := &schemaWikiRouteAccessMiddlewareSpy{events: &events}
			engine := newSchemaWikiScopeRouteEngine(
				t, &schemaWikiRouteScopeResolver{head: head}, nil, kbs, &events, access,
			)
			response := httptest.NewRecorder()
			engine.ServeHTTP(response, httptest.NewRequest(http.MethodGet, path, nil))
			require.Equal(t, http.StatusForbidden, response.Code, "body=%s", response.Body.String())
			require.Zero(t, access.sealCalls)
		})
	}

	t.Run("active scope drift", func(t *testing.T) {
		events := []string{}
		access := &schemaWikiRouteAccessMiddlewareSpy{events: &events}
		drifted := *head
		drifted.SpaceID = "other-space"
		engine := newSchemaWikiScopeRouteEngine(t, &schemaWikiRouteScopeResolver{head: &drifted}, nil,
			map[string]*types.KnowledgeBase{
				"wiki-g3": {ID: "wiki-g3", TenantID: 10003, Type: types.KnowledgeBaseTypeWiki},
				"raw-g3":  {ID: "raw-g3", TenantID: 10003},
			}, &events, access)
		response := httptest.NewRecorder()
		engine.ServeHTTP(response, httptest.NewRequest(http.MethodGet, path, nil))
		require.Equal(t, http.StatusForbidden, response.Code, "body=%s", response.Body.String())
		require.Zero(t, access.sealCalls)
	})
}

func TestSchemaPackCatalog830G3AnonymousCallerIsRejected(t *testing.T) {
	t.Parallel()
	gin.SetMode(gin.TestMode)
	enabled := true
	guards := &rbacGuards{cfg: &config.Config{Tenant: &config.TenantConfig{EnableRBAC: &enabled}}}
	engine := gin.New()
	RegisterSchemaWikiRoutes(
		engine.Group("/api/v1"),
		handler.NewSchemaWikiHandler(nil, nil),
		handler.NewWikiReleaseHandler(nil),
		guards,
	)
	response := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet,
		"/api/v1/knowledgebase/wiki-g3/wiki/release-scopes/space-g3/raw/raw-g3/schema/catalogs/schema_catalog_insurance_product/versions/2026-08-12-v5",
		nil)
	engine.ServeHTTP(response, request)
	require.Equal(t, http.StatusForbidden, response.Code, "body=%s", response.Body.String())
}

func TestSchemaPackCatalog830G3UnknownIdentityIsNotFound(t *testing.T) {
	t.Parallel()
	events := []string{}
	access := &schemaWikiRouteAccessMiddlewareSpy{events: &events}
	resolver := &schemaWikiRouteScopeResolver{head: &types.WikiReleaseHead{
		WikiReleaseScope: types.WikiReleaseScope{
			TenantID: 10003, SpaceID: "space-g3", RawKBID: "raw-g3", WikiKBID: "wiki-g3",
		}, ActiveReleaseID: "release-g2-published", ActivationEpoch: 5,
	}}
	engine := newSchemaWikiScopeRouteEngine(t, resolver, nil, map[string]*types.KnowledgeBase{
		"wiki-g3": {ID: "wiki-g3", TenantID: 10003, Type: types.KnowledgeBaseTypeWiki},
		"raw-g3":  {ID: "raw-g3", TenantID: 10003},
	}, &events, access)
	for _, suffix := range []string{
		"catalogs/unknown/versions/2026-08-12-v5",
		"catalogs/schema_catalog_insurance_product/versions/unknown",
	} {
		response := httptest.NewRecorder()
		path := "/api/v1/knowledgebase/wiki-g3/wiki/release-scopes/space-g3/raw/raw-g3/schema/" + suffix
		engine.ServeHTTP(response, httptest.NewRequest(http.MethodGet, path, nil))
		require.Equal(t, http.StatusNotFound, response.Code, "body=%s", response.Body.String())
	}
}
