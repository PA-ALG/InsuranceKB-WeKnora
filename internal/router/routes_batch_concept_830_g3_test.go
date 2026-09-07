package router

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

func TestBatchConceptPreparation830G3DeclaresSingleHumanReadRoute(t *testing.T) {
	gin.SetMode(gin.TestMode)
	engine := gin.New()
	RegisterSchemaWikiRoutes(
		engine.Group("/api/v1"),
		&handler.SchemaWikiHandler{},
		&handler.WikiReleaseHandler{},
		&rbacGuards{},
	)
	path := http.MethodGet + " /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/preparations/:preparation_id/batch-concept"
	count := 0
	for _, route := range engine.Routes() {
		if route.Method+" "+route.Path == path {
			count++
		}
	}
	require.Equal(t, 1, count)
}

func TestBatchConceptPreparation830G3UsesHumanAdminDualKBSeal(t *testing.T) {
	path := "/api/v1/knowledgebase/wiki-g3/wiki/release-scopes/space-g3/raw/raw-g3/schema/preparations/batch-preparation/batch-concept"
	for _, test := range []struct {
		name       string
		role       types.TenantRole
		wantStatus int
		wantSeal   int
		wantScope  int
	}{
		{name: "admin", role: types.TenantRoleAdmin, wantStatus: http.StatusBadRequest, wantSeal: 1, wantScope: 1},
		{name: "viewer", role: types.TenantRoleViewer, wantStatus: http.StatusForbidden},
	} {
		t.Run(test.name, func(t *testing.T) {
			events := []string{}
			resolver := &schemaWikiRouteScopeResolver{preparationScope: &types.WikiReleaseScope{
				TenantID: 10003, SpaceID: "space-g3", RawKBID: "raw-g3", WikiKBID: "wiki-g3",
			}}
			access := &schemaWikiRouteAccessMiddlewareSpy{events: &events}
			engine := newSchemaWikiScopeRouteEngineWithRole(
				t, resolver, nil,
				map[string]*types.KnowledgeBase{
					"wiki-g3": {ID: "wiki-g3", TenantID: 10003, Type: types.KnowledgeBaseTypeWiki},
					"raw-g3":  {ID: "raw-g3", TenantID: 10003},
				},
				&events, access, test.role,
			)
			recorder := httptest.NewRecorder()
			engine.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, path, nil))
			require.Equal(t, test.wantStatus, recorder.Code, recorder.Body.String())
			require.Equal(t, test.wantSeal, access.sealCalls)
			require.Equal(t, test.wantScope, resolver.preparationCalls)
			if test.role == types.TenantRoleAdmin {
				require.Equal(t, []string{
					"acl:wiki-g3", "evidence:wiki", "acl:raw-g3", "evidence:raw", "seal",
				}, events)
			} else {
				require.Empty(t, events)
			}
		})
	}
}
