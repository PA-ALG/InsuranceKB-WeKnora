package router

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
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
	headErr          error
	calls            int
	tenantIDs        []uint64
	wikiKBIDs        []string
	events           *[]string
	preparationScope *types.WikiReleaseScope
	preparationCalls int
}

type schemaWikiRouteCitationAuthorityResolver struct {
	authority *service.SchemaWikiCitationContentRouteAuthorityV1
	err       error
	calls     int
	events    *[]string
}

func (s *schemaWikiRouteCitationAuthorityResolver) ResolveSchemaCitationContentRouteAuthority(
	_ context.Context,
	_ string,
) (*service.SchemaWikiCitationContentRouteAuthorityV1, error) {
	s.calls++
	if s.events != nil {
		*s.events = append(*s.events, "token")
	}
	return s.authority, s.err
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
	return s.head, s.headErr
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
	citationResolvers ...handler.SchemaWikiCitationContentRouteAuthorityResolver,
) *gin.Engine {
	return newSchemaWikiScopeRouteEngineWithRole(
		t, resolver, apiKeyScope, kbs, events, accessMiddleware, types.TenantRoleViewer,
		citationResolvers...,
	)
}

func newSchemaWikiScopeRouteEngineWithRole(
	t *testing.T,
	resolver *schemaWikiRouteScopeResolver,
	apiKeyScope *types.TenantAPIKeyScope,
	kbs map[string]*types.KnowledgeBase,
	events *[]string,
	accessMiddleware schemaWikiReleaseAccessMiddleware,
	role types.TenantRole,
	citationResolvers ...handler.SchemaWikiCitationContentRouteAuthorityResolver,
) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	enabled := true
	guards := &rbacGuards{
		cfg:       &config.Config{Tenant: &config.TenantConfig{EnableRBAC: &enabled}},
		kbService: &orderedSchemaWikiKBLookup{kbs: kbs, events: events},
	}
	schemaHandler := handler.NewSchemaWikiHandler(resolver, nil, citationResolvers...)
	if accessMiddleware == nil {
		accessMiddleware = handler.NewWikiReleaseHandler(nil)
	}

	engine := gin.New()
	engine.Use(middleware.ErrorHandler())
	engine.Use(func(c *gin.Context) {
		principal := types.Principal{Type: types.PrincipalWebUser, ID: "viewer"}
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(10003))
		ctx = context.WithValue(ctx, types.TenantRoleContextKey, role)
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

func TestSchemaWikiGoldenSuccessorStatusUsesExactHumanDualACLSealOrder(t *testing.T) {
	t.Parallel()
	events := []string{}
	access := &schemaWikiRouteAccessMiddlewareSpy{events: &events}
	engine := newSchemaWikiScopeRouteEngineWithRole(
		t,
		&schemaWikiRouteScopeResolver{},
		nil,
		map[string]*types.KnowledgeBase{
			"wiki-596-1": {ID: "wiki-596-1", TenantID: 10003, Type: types.KnowledgeBaseTypeWiki},
			"raw-596-1":  {ID: "raw-596-1", TenantID: 10003},
		},
		&events,
		access,
		types.TenantRoleAdmin,
	)
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(
		http.MethodGet,
		"/api/v1/knowledgebase/wiki-596-1/wiki/release-scopes/space-596-1/raw/raw-596-1/schema/golden-quality/successor-status",
		nil,
	)
	engine.ServeHTTP(recorder, request)

	require.Equal(t, http.StatusServiceUnavailable, recorder.Code)
	require.Contains(t, recorder.Body.String(), "NO_GOLDEN_SUCCESSOR_STATUS")
	require.Equal(t, []string{
		"acl:wiki-596-1", "evidence:wiki", "acl:raw-596-1", "evidence:raw", "seal",
	}, events)
	require.Equal(t, 1, access.sealCalls)
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
			for _, request := range []*http.Request{
				httptest.NewRequest(
					http.MethodPost,
					"/api/v1/knowledgebase/wiki-596-1/wiki/release-scopes/space-596-1/raw/raw-596-1/schema/preparations/preparation-596-1/review",
					nil,
				),
				httptest.NewRequest(
					http.MethodGet,
					"/api/v1/knowledgebase/wiki-596-1/wiki/release-scopes/space-596-1/raw/raw-kb-596-1/schema/golden-quality/successor-status",
					nil,
				),
			} {
				recorder = httptest.NewRecorder()
				engine.ServeHTTP(recorder, request)
				require.Equal(t, http.StatusForbidden, recorder.Code)
				require.Zero(t, resolver.preparationCalls)
				require.Zero(t, access.sealCalls)
				require.Empty(t, events)
			}
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

func TestSchemaWikiCitationContentNoHeadStillReachesSealedDualACLHandler(t *testing.T) {
	t.Parallel()
	events := []string{}
	access := &schemaWikiRouteAccessMiddlewareSpy{events: &events}
	resolver := &schemaWikiRouteScopeResolver{
		events: &events, headErr: apprepo.ErrWikiReleaseNotFound,
		preparationScope: &types.WikiReleaseScope{
			TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-596-1",
		},
	}
	citationResolver := &schemaWikiRouteCitationAuthorityResolver{
		events: &events,
		authority: &service.SchemaWikiCitationContentRouteAuthorityV1{
			Kind: "preparation",
			Scope: types.WikiReleaseScope{
				TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-596-1",
			},
			PreparationID: "preparation-596-1",
		},
	}
	engine := newSchemaWikiScopeRouteEngineWithRole(
		t,
		resolver,
		nil,
		map[string]*types.KnowledgeBase{
			"wiki-596-1": {ID: "wiki-596-1", TenantID: 10003, Type: types.KnowledgeBaseTypeWiki},
			"raw-596-1":  {ID: "raw-596-1", TenantID: 10003},
		},
		&events,
		access,
		types.TenantRoleAdmin,
		citationResolver,
	)
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(
		http.MethodGet,
		"/api/v1/knowledgebase/wiki-596-1/wiki/release-scopes/space-596-1/raw/raw-596-1/schema/citation-content/preparation-token",
		nil,
	)
	engine.ServeHTTP(recorder, request)

	require.Equal(t, http.StatusServiceUnavailable, recorder.Code, "body=%s", recorder.Body.String())
	require.Contains(t, recorder.Body.String(), "schema wiki citation unavailable")
	require.Equal(t, []string{
		"acl:wiki-596-1",
		"evidence:wiki",
		"token",
		"acl:raw-596-1",
		"evidence:raw",
		"seal",
	}, events)
	require.Zero(t, resolver.calls, "opaque content route must not require an Active Head")
	require.Equal(t, 1, resolver.preparationCalls)
	require.Equal(t, 1, citationResolver.calls)
	require.Equal(t, 1, access.sealCalls)
}

func TestSchemaWikiCitationContentTokenAuthorityFailsBeforeRawACLAndSeal(t *testing.T) {
	t.Parallel()
	exact := types.WikiReleaseScope{
		TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-596-1",
	}
	for name, setup := range map[string]func(
		*schemaWikiRouteScopeResolver,
		*schemaWikiRouteCitationAuthorityResolver,
		*types.TenantAPIKeyScope,
	){
		"invalid token": func(_ *schemaWikiRouteScopeResolver, token *schemaWikiRouteCitationAuthorityResolver, _ *types.TenantAPIKeyScope) {
			token.authority = nil
			token.err = service.ErrSchemaWikiCitationUnavailable
		},
		"preparation scope drift": func(resolver *schemaWikiRouteScopeResolver, _ *schemaWikiRouteCitationAuthorityResolver, _ *types.TenantAPIKeyScope) {
			foreign := exact
			foreign.RawKBID = "raw-foreign"
			resolver.preparationScope = &foreign
		},
		"preparation id absent": func(_ *schemaWikiRouteScopeResolver, token *schemaWikiRouteCitationAuthorityResolver, _ *types.TenantAPIKeyScope) {
			token.authority.PreparationID = ""
		},
		"api key preparation": func(_ *schemaWikiRouteScopeResolver, _ *schemaWikiRouteCitationAuthorityResolver, apiKey *types.TenantAPIKeyScope) {
			*apiKey = types.TenantAPIKeyScope{
				KeyID: 120, KnowledgeBaseIDs: types.StringArray{exact.WikiKBID, exact.RawKBID},
				Capabilities: types.StringArray{string(types.APIKeyCapabilityRetrieve)},
			}
		},
	} {
		t.Run(name, func(t *testing.T) {
			events := []string{}
			access := &schemaWikiRouteAccessMiddlewareSpy{events: &events}
			resolver := &schemaWikiRouteScopeResolver{events: &events, preparationScope: &exact}
			token := &schemaWikiRouteCitationAuthorityResolver{events: &events, authority: &service.SchemaWikiCitationContentRouteAuthorityV1{
				Kind: "preparation", Scope: exact, PreparationID: "preparation-596-1",
			}}
			var apiKey types.TenantAPIKeyScope
			setup(resolver, token, &apiKey)
			var scope *types.TenantAPIKeyScope
			if apiKey.KeyID != 0 {
				scope = &apiKey
			}
			engine := newSchemaWikiScopeRouteEngineWithRole(
				t, resolver, scope,
				map[string]*types.KnowledgeBase{
					exact.WikiKBID: {ID: exact.WikiKBID, TenantID: exact.TenantID, Type: types.KnowledgeBaseTypeWiki},
					exact.RawKBID:  {ID: exact.RawKBID, TenantID: exact.TenantID},
				},
				&events, access, types.TenantRoleAdmin, token,
			)
			recorder := httptest.NewRecorder()
			request := httptest.NewRequest(
				http.MethodGet,
				"/api/v1/knowledgebase/wiki-596-1/wiki/release-scopes/space-596-1/raw/raw-596-1/schema/citation-content/token",
				nil,
			)
			engine.ServeHTTP(recorder, request)

			require.Equal(t, http.StatusForbidden, recorder.Code, "body=%s", recorder.Body.String())
			require.Zero(t, access.sealCalls)
			require.NotContains(t, events, "acl:raw-596-1")
			require.NotContains(t, events, "handler")
		})
	}
}

type schemaWikiC5RouteReaderStub struct {
	record  apprepo.SchemaWikiFormalCandidatePreviewRecord
	content apprepo.SchemaWikiFormalCandidatePreviewContent
}

func (s *schemaWikiC5RouteReaderStub) ReadExact(
	_ uint64,
	_ apprepo.SchemaWikiFormalCandidatePreviewKey,
) (apprepo.SchemaWikiFormalCandidatePreviewRecord, error) {
	return s.record, nil
}

func (s *schemaWikiC5RouteReaderStub) ReadContentExact(
	_ uint64,
	_ apprepo.SchemaWikiFormalCandidatePreviewKey,
	_ apprepo.SchemaWikiFormalCandidatePreviewContentRequest,
) (apprepo.SchemaWikiFormalCandidatePreviewContent, error) {
	return s.content, nil
}

func TestSchemaWikiFormalCandidatePreviewRoutesUseOnlyMaterialKBReadACL(t *testing.T) {
	t.Parallel()
	events := []string{}
	enabled := true
	guards := &rbacGuards{
		cfg: &config.Config{Tenant: &config.TenantConfig{EnableRBAC: &enabled}},
		kbService: &orderedSchemaWikiKBLookup{kbs: map[string]*types.KnowledgeBase{
			"wiki-596-1": {ID: "wiki-596-1", TenantID: 10003},
		}, events: &events},
	}
	contentBytes := []byte("%PDF exact")
	contentSum := sha256.Sum256(contentBytes)
	reader := &schemaWikiC5RouteReaderStub{
		record: apprepo.SchemaWikiFormalCandidatePreviewRecord{
			TenantID: 10003, KBID: "wiki-596-1",
			ExperimentID:   "2a92f197-4b33-41de-a6af-c60252d6347d",
			ManifestSHA256: strings.Repeat("a", 64), CandidateSHA256: strings.Repeat("b", 64),
			CompanionSHA256: strings.Repeat("c", 64), TerminalSHA256: strings.Repeat("d", 64),
			RevisionSetSHA256: strings.Repeat("e", 64), PreviewSHA256: strings.Repeat("f", 64),
			Preview: json.RawMessage(`{"contract":"schema-wiki-formal-candidate-preview.815.v1","preview_sha256":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"}`),
		},
		content: apprepo.SchemaWikiFormalCandidatePreviewContent{
			Bytes: contentBytes, OriginalFileSHA256: hex.EncodeToString(contentSum[:]),
		},
	}
	schemaService := service.NewSchemaWikiServiceWithFormalCandidatePreview(reader)
	schemaHandler := handler.NewSchemaWikiHandler(nil, schemaService)
	access := &schemaWikiRouteAccessMiddlewareSpy{events: &events}
	engine := gin.New()
	engine.Use(middleware.ErrorHandler())
	engine.Use(func(c *gin.Context) {
		principal := types.Principal{Type: types.PrincipalWebUser, ID: "viewer"}
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(10003))
		ctx = context.WithValue(ctx, types.TenantRoleContextKey, types.TenantRoleViewer)
		ctx = types.WithPrincipal(ctx, principal)
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), uint64(10003))
		c.Set(types.PrincipalContextKey.String(), principal)
		c.Next()
	})
	RegisterSchemaWikiRoutes(engine.Group("/api/v1"), schemaHandler, access, guards)
	base := "/api/v1/knowledgebase/wiki-596-1/wiki/schema-experiments/2a92f197-4b33-41de-a6af-c60252d6347d/versions/" + strings.Repeat("a", 64)
	for _, path := range []string{base, base + "/fields/field-01/selections/selection-01/content"} {
		events = nil
		recorder := httptest.NewRecorder()
		engine.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, path, nil))
		require.Equal(t, http.StatusOK, recorder.Code, "body=%s", recorder.Body.String())
		require.Equal(t, []string{"acl:wiki-596-1"}, events)
		require.Zero(t, access.sealCalls, "C5 must not require release scope or Active seal")
	}
}

func TestSchemaWikiFormalCandidatePreviewRoutesRejectCurrentLatestAndWrongKB(t *testing.T) {
	t.Parallel()
	// Route existence and query rejection are exercised through the real handler;
	// a foreign material KB must stop at the existing KB ACL before the service.
	events := []string{}
	enabled := true
	guards := &rbacGuards{
		cfg:       &config.Config{Tenant: &config.TenantConfig{EnableRBAC: &enabled}},
		kbService: &orderedSchemaWikiKBLookup{kbs: map[string]*types.KnowledgeBase{}, events: &events},
	}
	reader := &schemaWikiC5RouteReaderStub{}
	schemaHandler := handler.NewSchemaWikiHandler(nil, service.NewSchemaWikiServiceWithFormalCandidatePreview(reader))
	engine := gin.New()
	engine.Use(func(c *gin.Context) {
		principal := types.Principal{Type: types.PrincipalWebUser, ID: "viewer"}
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(10003))
		ctx = context.WithValue(ctx, types.TenantRoleContextKey, types.TenantRoleViewer)
		ctx = types.WithPrincipal(ctx, principal)
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), uint64(10003))
		c.Next()
	})
	RegisterSchemaWikiRoutes(engine.Group("/api/v1"), schemaHandler, &schemaWikiRouteAccessMiddlewareSpy{events: &events}, guards)
	path := "/api/v1/knowledgebase/foreign/wiki/schema-experiments/2a92f197-4b33-41de-a6af-c60252d6347d/versions/" + strings.Repeat("a", 64) + "?latest=1"
	recorder := httptest.NewRecorder()
	engine.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, path, nil))
	require.Equal(t, http.StatusForbidden, recorder.Code)
	require.Equal(t, []string{"acl:foreign"}, events)
}

func TestSchemaWikiCitationContentActiveTokenStillRequiresExactHeadBeforeRawACL(t *testing.T) {
	t.Parallel()
	exact := types.WikiReleaseScope{
		TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-596-1",
	}
	for name, head := range map[string]*types.WikiReleaseHead{
		"exact active": {
			WikiReleaseScope: exact, ActiveReleaseID: "release-596-1", ActivationEpoch: 7,
		},
		"head drift": {
			WikiReleaseScope: types.WikiReleaseScope{
				TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-foreign", WikiKBID: "wiki-596-1",
			},
			ActiveReleaseID: "release-596-1", ActivationEpoch: 7,
		},
	} {
		t.Run(name, func(t *testing.T) {
			events := []string{}
			access := &schemaWikiRouteAccessMiddlewareSpy{events: &events}
			resolver := &schemaWikiRouteScopeResolver{events: &events, head: head}
			token := &schemaWikiRouteCitationAuthorityResolver{events: &events, authority: &service.SchemaWikiCitationContentRouteAuthorityV1{
				Kind: "active", Scope: exact,
			}}
			engine := newSchemaWikiScopeRouteEngine(
				t, resolver, nil,
				map[string]*types.KnowledgeBase{
					exact.WikiKBID: {ID: exact.WikiKBID, TenantID: exact.TenantID, Type: types.KnowledgeBaseTypeWiki},
					exact.RawKBID:  {ID: exact.RawKBID, TenantID: exact.TenantID},
				},
				&events, access, token,
			)
			recorder := httptest.NewRecorder()
			request := httptest.NewRequest(
				http.MethodGet,
				"/api/v1/knowledgebase/wiki-596-1/wiki/release-scopes/space-596-1/raw/raw-596-1/schema/citation-content/token",
				nil,
			)
			engine.ServeHTTP(recorder, request)

			if name == "exact active" {
				require.Equal(t, http.StatusServiceUnavailable, recorder.Code)
				require.Equal(t, 1, access.sealCalls)
				require.Contains(t, events, "acl:raw-596-1")
			} else {
				require.Equal(t, http.StatusForbidden, recorder.Code)
				require.Zero(t, access.sealCalls)
				require.NotContains(t, events, "acl:raw-596-1")
			}
		})
	}
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
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/golden-quality/successor-status"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/taxonomy/current"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/entities/:entity_id/versions/:version_id/current"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/releases/:release_id/root"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/releases/:release_id/sections/:section_id"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/releases/:release_id/fields/:field_id"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/preparations/:preparation_id/root"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/preparations/:preparation_id/sections/:section_id"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/preparations/:preparation_id/fields/:field_id"])
	require.True(t, paths[http.MethodGet+" /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/releases/:release_id/fields/:field_id/citations/:citation_id/preview"])
	contentPath := http.MethodGet + " /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/citation-content/:token"
	require.True(t, paths[contentPath])
	for path := range paths {
		if strings.Contains(path, "/schema/citation-content/") {
			require.NotContains(t, path, ":page")
			require.NotContains(t, path, ":revision")
			require.NotContains(t, path, ":attempt")
		}
	}
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

const (
	schemaWikiC6RouteSpaceID      = "a8751a40-83ce-55c8-a160-079b283483ca"
	schemaWikiC6RouteRawKBID      = "b1f1764c-443d-46b8-98e3-d5aa5e55eb42"
	schemaWikiC6RouteWikiKBID     = "8d5695de-f255-42d5-9a41-042ba86e97b9"
	schemaWikiC6RouteExperimentID = "5655e43c-1adb-4282-95f7-305e58441512"
)

func schemaWikiC6DecisionRoutePath() string {
	return "/api/v1/knowledgebase/" + schemaWikiC6RouteWikiKBID +
		"/wiki/release-scopes/" + schemaWikiC6RouteSpaceID +
		"/raw/" + schemaWikiC6RouteRawKBID +
		"/schema-experiments/" + schemaWikiC6RouteExperimentID +
		"/versions/" + strings.Repeat("a", 64) + "/decision"
}

func newSchemaWikiC6DecisionRouteEngine(
	t *testing.T,
	role types.TenantRole,
	apiKeyScope *types.TenantAPIKeyScope,
	events *[]string,
) (*gin.Engine, *schemaWikiRouteScopeResolver, *schemaWikiRouteAccessMiddlewareSpy) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	enabled := true
	resolver := &schemaWikiRouteScopeResolver{
		headErr: apprepo.ErrWikiReleaseNotFound,
		events:  events,
	}
	access := &schemaWikiRouteAccessMiddlewareSpy{events: events}
	guards := &rbacGuards{
		cfg: &config.Config{Tenant: &config.TenantConfig{EnableRBAC: &enabled}},
		kbService: &orderedSchemaWikiKBLookup{
			events: events,
			kbs: map[string]*types.KnowledgeBase{
				schemaWikiC6RouteWikiKBID: {
					ID: schemaWikiC6RouteWikiKBID, TenantID: 10003, Type: types.KnowledgeBaseTypeWiki,
				},
				schemaWikiC6RouteRawKBID: {ID: schemaWikiC6RouteRawKBID, TenantID: 10003},
			},
		},
	}
	reader := &schemaWikiC5RouteReaderStub{}
	schemaService := service.NewSchemaWikiServiceWithFormalCandidatePreview(reader)
	schemaHandler := handler.NewSchemaWikiHandler(resolver, schemaService)
	engine := gin.New()
	engine.Use(middleware.ErrorHandler())
	engine.Use(func(c *gin.Context) {
		principal := types.Principal{Type: types.PrincipalWebUser, ID: "reviewer-815"}
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(10003))
		ctx = context.WithValue(ctx, types.UserIDContextKey, principal.ID)
		ctx = context.WithValue(ctx, types.TenantRoleContextKey, role)
		ctx = types.WithPrincipal(ctx, principal)
		if apiKeyScope != nil {
			ctx = types.WithTenantAPIKeyScope(ctx, *apiKeyScope)
		}
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), uint64(10003))
		c.Set(types.PrincipalContextKey.String(), principal)
		c.Next()
	})
	RegisterSchemaWikiRoutes(engine.Group("/api/v1"), schemaHandler, access, guards)
	return engine, resolver, access
}

func TestSchemaWikiC6DecisionRouteUsesExactHumanAdminDualACLSealOrder(t *testing.T) {
	events := []string{}
	engine, resolver, access := newSchemaWikiC6DecisionRouteEngine(
		t, types.TenantRoleAdmin, nil, &events,
	)
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(
		http.MethodPost,
		schemaWikiC6DecisionRoutePath(),
		strings.NewReader(`{"human_decision":{"nonce":"route-815"},"publish_authorization":null}`),
	)
	engine.ServeHTTP(recorder, request)
	require.Equal(t, http.StatusBadRequest, recorder.Code, "body=%s", recorder.Body.String())
	require.Equal(t, []string{
		"acl:" + schemaWikiC6RouteWikiKBID,
		"evidence:wiki",
		"resolve",
		"acl:" + schemaWikiC6RouteRawKBID,
		"evidence:raw",
		"seal",
	}, events)
	require.Equal(t, 1, resolver.calls)
	require.Equal(t, 1, access.sealCalls)

	for _, test := range []struct {
		name        string
		role        types.TenantRole
		apiKeyScope *types.TenantAPIKeyScope
	}{
		{name: "viewer", role: types.TenantRoleViewer},
		{name: "api key", role: types.TenantRoleAdmin, apiKeyScope: &types.TenantAPIKeyScope{
			KnowledgeBaseIDs: types.StringArray{schemaWikiC6RouteWikiKBID, schemaWikiC6RouteRawKBID},
		}},
	} {
		t.Run(test.name, func(t *testing.T) {
			blockedEvents := []string{}
			blocked, _, blockedAccess := newSchemaWikiC6DecisionRouteEngine(
				t, test.role, test.apiKeyScope, &blockedEvents,
			)
			blockedRecorder := httptest.NewRecorder()
			blockedRequest := httptest.NewRequest(
				http.MethodPost,
				schemaWikiC6DecisionRoutePath(),
				strings.NewReader(`{"human_decision":{},"publish_authorization":null}`),
			)
			blocked.ServeHTTP(blockedRecorder, blockedRequest)
			require.Equal(t, http.StatusForbidden, blockedRecorder.Code)
			require.Empty(t, blockedEvents)
			require.Zero(t, blockedAccess.sealCalls)
		})
	}
}

func TestSchemaWikiC6DecisionRouteRegistersOnlyBoundedPOSTPath(t *testing.T) {
	guards := &rbacGuards{}
	engine := gin.New()
	RegisterSchemaWikiRoutes(
		engine.Group("/api/v1"),
		&handler.SchemaWikiHandler{},
		&handler.WikiReleaseHandler{},
		guards,
	)
	want := "/api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/" +
		"schema-experiments/:experiment_id/versions/:version_identity/decision"
	decisionRoutes := []gin.RouteInfo{}
	for _, route := range engine.Routes() {
		if strings.HasSuffix(route.Path, "/decision") {
			decisionRoutes = append(decisionRoutes, route)
		}
	}
	require.Len(t, decisionRoutes, 1)
	require.Equal(t, http.MethodPost, decisionRoutes[0].Method)
	require.Equal(t, want, decisionRoutes[0].Path)

	readEngine, _, _ := newSchemaWikiC6DecisionRouteEngine(
		t, types.TenantRoleAdmin, nil, &[]string{},
	)
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, schemaWikiC6DecisionRoutePath(), nil)
	readEngine.ServeHTTP(recorder, request)
	require.Equal(t, http.StatusNotFound, recorder.Code)
}
