package router

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	apprepo "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type schemaWikiRouteScopeResolver struct {
	head             *types.WikiReleaseHead
	calls            int
	tenantIDs        []uint64
	wikiKBIDs        []string
	events           *[]string
	preparationScope *types.WikiReleaseScope
	preparationCalls int
}

func (s *schemaWikiRouteScopeResolver) GetPreparationScopeForWikiKB(
	_ context.Context,
	_ uint64,
	_ string,
	_ string,
) (*types.WikiReleaseScope, error) {
	s.preparationCalls++
	return s.preparationScope, nil
}

func (s *schemaWikiRouteScopeResolver) GetHeadForWikiKB(
	_ context.Context,
	tenantID uint64,
	wikiKBID string,
) (*types.WikiReleaseHead, error) {
	s.calls++
	s.tenantIDs = append(s.tenantIDs, tenantID)
	s.wikiKBIDs = append(s.wikiKBIDs, wikiKBID)
	if s.events != nil {
		*s.events = append(*s.events, "resolve")
	}
	return s.head, nil
}

type schemaWikiRouteAccessMiddlewareSpy struct {
	events    *[]string
	sealCalls int
}

func (s *schemaWikiRouteAccessMiddlewareSpy) RecordWikiAccessEvidence() gin.HandlerFunc {
	return func(c *gin.Context) {
		*s.events = append(*s.events, "evidence:wiki")
		c.Next()
	}
}

func (s *schemaWikiRouteAccessMiddlewareSpy) RecordRawAccessEvidence() gin.HandlerFunc {
	return func(c *gin.Context) {
		*s.events = append(*s.events, "evidence:raw")
		c.Next()
	}
}

func (s *schemaWikiRouteAccessMiddlewareSpy) SealAccess() gin.HandlerFunc {
	return func(c *gin.Context) {
		s.sealCalls++
		*s.events = append(*s.events, "seal")
		principal, ok := types.PrincipalFromContext(c.Request.Context())
		if !ok {
			c.AbortWithStatus(http.StatusForbidden)
			return
		}
		scope := types.WikiReleaseScope{
			TenantID: 10003,
			SpaceID:  c.Param("space_id"),
			RawKBID:  c.Param("raw_kb_id"),
			WikiKBID: c.Param("kb_id"),
		}
		sealedPrincipal := types.WikiReleasePrincipal{
			ID:       principal.StorageID(),
			TenantID: scope.TenantID,
			SpaceID:  scope.SpaceID,
		}
		if apiKeyScope, exists := types.TenantAPIKeyScopeFromContext(c.Request.Context()); exists {
			sealedPrincipal.APIKeyKnowledgeBaseIDs = append(
				[]string(nil), apiKeyScope.KnowledgeBaseIDs...,
			)
		}
		c.Request = c.Request.WithContext(
			service.SealWikiReleaseAccess(c.Request.Context(), sealedPrincipal, scope),
		)
		c.Next()
	}
}

type orderedSchemaWikiKBLookup struct {
	kbs    map[string]*types.KnowledgeBase
	events *[]string
}

func (s *orderedSchemaWikiKBLookup) GetKnowledgeBaseByID(
	_ context.Context,
	id string,
) (*types.KnowledgeBase, error) {
	if s.events != nil {
		*s.events = append(*s.events, "acl:"+id)
	}
	if kb, ok := s.kbs[id]; ok {
		return kb, nil
	}
	return nil, apprepo.ErrKnowledgeBaseNotFound
}

func newSchemaWikiScopeRouteEngine(
	t *testing.T,
	resolver *schemaWikiRouteScopeResolver,
	apiKeyScope *types.TenantAPIKeyScope,
	kbs map[string]*types.KnowledgeBase,
	events *[]string,
	accessMiddleware schemaWikiReleaseAccessMiddleware,
) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	enabled := true
	guards := &rbacGuards{
		cfg:       &config.Config{Tenant: &config.TenantConfig{EnableRBAC: &enabled}},
		kbService: &orderedSchemaWikiKBLookup{kbs: kbs, events: events},
	}
	schemaHandler := handler.NewSchemaWikiHandler(resolver, nil)
	if accessMiddleware == nil {
		accessMiddleware = handler.NewWikiReleaseHandler(nil)
	}

	engine := gin.New()
	engine.Use(middleware.ErrorHandler())
	engine.Use(func(c *gin.Context) {
		principal := types.Principal{Type: types.PrincipalWebUser, ID: "viewer"}
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(10003))
		ctx = context.WithValue(ctx, types.TenantRoleContextKey, types.TenantRoleViewer)
		ctx = types.WithPrincipal(ctx, principal)
		if apiKeyScope != nil {
			ctx = types.WithTenantAPIKeyScope(ctx, *apiKeyScope)
		}
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), uint64(10003))
		c.Set(types.PrincipalContextKey.String(), principal)
		c.Next()
	})
	if events != nil {
		engine.Use(func(c *gin.Context) {
			c.Next()
			if c.Writer.Status() == http.StatusOK {
				*events = append(*events, "handler")
			}
		})
	}
	RegisterSchemaWikiRoutes(engine.Group("/api/v1"), schemaHandler, accessMiddleware, guards)
	return engine
}

func TestSchemaWikiScopeBootstrapRequiresWikiThenDerivedRawACL(t *testing.T) {
	t.Parallel()
	resolver := &schemaWikiRouteScopeResolver{head: &types.WikiReleaseHead{
		WikiReleaseScope: types.WikiReleaseScope{
			TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-596-1",
		},
		ActiveReleaseID: "release-596-1",
		ActivationEpoch: 1,
	}}

	t.Run("wiki authorized but raw rejected", func(t *testing.T) {
		engine := newSchemaWikiScopeRouteEngine(t, resolver, nil, map[string]*types.KnowledgeBase{
			"wiki-596-1": {ID: "wiki-596-1", TenantID: 10003, Type: types.KnowledgeBaseTypeWiki},
		}, nil, nil)
		recorder := httptest.NewRecorder()
		request := httptest.NewRequest(http.MethodGet, "/api/v1/knowledgebase/wiki-596-1/wiki/schema-scope", nil)
		engine.ServeHTTP(recorder, request)
		require.Equal(t, http.StatusForbidden, recorder.Code, "body=%s", recorder.Body.String())
		require.Equal(t, 1, resolver.calls, "scope resolution occurs only after Wiki ACL")
		require.Equal(t, []uint64{10003}, resolver.tenantIDs)
		require.Equal(t, []string{"wiki-596-1"}, resolver.wikiKBIDs)
	})

	t.Run("api key allowlisting only wiki is rejected by raw ACL", func(t *testing.T) {
		resolver.calls = 0
		scope := &types.TenantAPIKeyScope{
			KnowledgeBaseIDs: types.StringArray{"wiki-596-1"},
			Capabilities:     types.StringArray{string(types.APIKeyCapabilityRetrieve)},
		}
		engine := newSchemaWikiScopeRouteEngine(t, resolver, scope, map[string]*types.KnowledgeBase{
			"wiki-596-1": {ID: "wiki-596-1", TenantID: 10003, Type: types.KnowledgeBaseTypeWiki},
			"raw-596-1":  {ID: "raw-596-1", TenantID: 10003},
		}, nil, nil)
		recorder := httptest.NewRecorder()
		request := httptest.NewRequest(http.MethodGet, "/api/v1/knowledgebase/wiki-596-1/wiki/schema-scope", nil)
		engine.ServeHTTP(recorder, request)
		require.Equal(t, http.StatusForbidden, recorder.Code, "body=%s", recorder.Body.String())
		require.Equal(t, 1, resolver.calls)
	})
}

func TestSchemaWikiScopeBootstrapSealsExactDualACLInOrder(t *testing.T) {
	t.Parallel()
	for name, apiKeyScope := range map[string]*types.TenantAPIKeyScope{
		"human viewer": nil,
		"api key allowlists both KBs": {
			KeyID:            120,
			KnowledgeBaseIDs: types.StringArray{"wiki-596-1", "raw-596-1"},
			Capabilities:     types.StringArray{string(types.APIKeyCapabilityRetrieve)},
		},
	} {
		t.Run(name, func(t *testing.T) {
			events := []string{}
			accessMiddleware := &schemaWikiRouteAccessMiddlewareSpy{events: &events}
			resolver := &schemaWikiRouteScopeResolver{
				events: &events,
				head: &types.WikiReleaseHead{WikiReleaseScope: types.WikiReleaseScope{
					TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-596-1",
				}, ActiveReleaseID: "release-596-1", ActivationEpoch: 7},
			}
			engine := newSchemaWikiScopeRouteEngine(
				t, resolver, apiKeyScope,
				map[string]*types.KnowledgeBase{
					"wiki-596-1": {ID: "wiki-596-1", TenantID: 10003, Type: types.KnowledgeBaseTypeWiki},
					"raw-596-1":  {ID: "raw-596-1", TenantID: 10003},
				},
				&events,
				accessMiddleware,
			)
			recorder := httptest.NewRecorder()
			request := httptest.NewRequest(
				http.MethodGet, "/api/v1/knowledgebase/wiki-596-1/wiki/schema-scope", nil,
			)
			engine.ServeHTTP(recorder, request)

			require.Equal(t, http.StatusOK, recorder.Code, "body=%s", recorder.Body.String())
			require.Equal(t, []string{
				"acl:wiki-596-1",
				"evidence:wiki",
				"resolve",
				"acl:raw-596-1",
				"evidence:raw",
				"seal",
				"handler",
			}, events)
			require.Equal(t, 1, accessMiddleware.sealCalls)
			require.Equal(t, []uint64{10003}, resolver.tenantIDs)
			require.Equal(t, []string{"wiki-596-1"}, resolver.wikiKBIDs)
			var response struct {
				Success bool                   `json:"success"`
				Data    map[string]interface{} `json:"data"`
			}
			require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &response))
			require.True(t, response.Success)
			require.Len(t, response.Data, 5)
			for _, key := range []string{
				"version", "space_id", "raw_kb_id", "wiki_kb_id", "scope_sha256",
			} {
				require.Contains(t, response.Data, key)
			}
			require.Equal(t, "schema-wiki-scope.v1", response.Data["version"])
			require.Regexp(t, `^[0-9a-f]{64}$`, response.Data["scope_sha256"])
		})
	}
}

func TestSchemaWikiHumanRoutesDenyMachineAndViewerBeforeScopeOrSeal(t *testing.T) {
	t.Parallel()
	for name, apiKeyScope := range map[string]*types.TenantAPIKeyScope{
		"viewer":  nil,
		"api key": {KeyID: 120, FullAccess: true},
	} {
		t.Run(name, func(t *testing.T) {
			events := []string{}
			access := &schemaWikiRouteAccessMiddlewareSpy{events: &events}
			resolver := &schemaWikiRouteScopeResolver{preparationScope: &types.WikiReleaseScope{
				TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-596-1",
			}}
			engine := newSchemaWikiScopeRouteEngine(t, resolver, apiKeyScope, map[string]*types.KnowledgeBase{
				"wiki-596-1": {ID: "wiki-596-1", TenantID: 10003, Type: types.KnowledgeBaseTypeWiki},
				"raw-596-1":  {ID: "raw-596-1", TenantID: 10003},
			}, &events, access)
			recorder := httptest.NewRecorder()
			request := httptest.NewRequest(
				http.MethodPost,
				"/api/v1/knowledgebase/wiki-596-1/wiki/release-scopes/space-596-1/raw/raw-596-1/schema/preparations/preparation-596-1/review",
				nil,
			)
			engine.ServeHTTP(recorder, request)
			require.Equal(t, http.StatusForbidden, recorder.Code)
			require.Zero(t, resolver.preparationCalls)
			require.Zero(t, access.sealCalls)
			require.Empty(t, events)
		})
	}
}

func TestSchemaWikiActiveScopedPathDriftStopsBeforeRawACLAndSeal(t *testing.T) {
	t.Parallel()
	events := []string{}
	access := &schemaWikiRouteAccessMiddlewareSpy{events: &events}
	resolver := &schemaWikiRouteScopeResolver{events: &events, head: &types.WikiReleaseHead{
		WikiReleaseScope: types.WikiReleaseScope{
			TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-596-1",
		}, ActiveReleaseID: "release-596-1", ActivationEpoch: 1,
	}}
	engine := newSchemaWikiScopeRouteEngine(t, resolver, nil, map[string]*types.KnowledgeBase{
		"wiki-596-1":  {ID: "wiki-596-1", TenantID: 10003, Type: types.KnowledgeBaseTypeWiki},
		"raw-foreign": {ID: "raw-foreign", TenantID: 10003},
	}, &events, access)
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(
		http.MethodGet,
		"/api/v1/knowledgebase/wiki-596-1/wiki/release-scopes/space-596-1/raw/raw-foreign/schema/domains",
		nil,
	)
	engine.ServeHTTP(recorder, request)
	require.Equal(t, http.StatusForbidden, recorder.Code)
	require.Equal(t, []string{"acl:wiki-596-1", "evidence:wiki", "resolve"}, events)
	require.Zero(t, access.sealCalls)
	require.NotContains(t, recorder.Body.String(), "raw-foreign")
}

func TestSchemaWikiRoutesDeclareExactScopedPrefixAndRetrievePolicy(t *testing.T) {
	t.Parallel()
	guards := &rbacGuards{}
	engine := gin.New()
	RegisterSchemaWikiRoutes(
		engine.Group("/api/v1"),
		&handler.SchemaWikiHandler{},
		&handler.WikiReleaseHandler{},
		guards,
	)

	paths := map[string]bool{}
	for _, route := range engine.Routes() {
		paths[route.Method+" "+route.Path] = true
	}
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/schema-scope"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/domains"])
	require.True(t, paths[http.MethodPost+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/preparations"])
	require.True(t, paths[http.MethodPost+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/preparations/:preparation_id/review"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/taxonomy/current"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/entities/:entity_id/versions/:version_id/current"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/releases/:release_id/root"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/releases/:release_id/sections/:section_id"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/releases/:release_id/fields/:field_id"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/preparations/:preparation_id/root"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/preparations/:preparation_id/sections/:section_id"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/preparations/:preparation_id/fields/:field_id"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/releases/:release_id/fields/:field_id/citations/:citation_id/preview"])
	require.False(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/preparations/:preparation_id/fields/:field_id/citations/:citation_id/preview"])
	require.False(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/drafts/:preparation_id/fields/:field_id"])

	policy := mustLookupAPIKeyPolicy(
		t,
		guards,
		http.MethodGet,
		"/api/v1/knowledgebase/:kb_id/wiki/schema-scope",
	)
	require.True(t, policyHasCapability(policy, types.APIKeyCapabilityRetrieve))
}
