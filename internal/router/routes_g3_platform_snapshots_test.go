package router

import (
	"net/http"
	"testing"

	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type g3PlatformScopeMiddlewareStub struct{}

func (g3PlatformScopeMiddlewareStub) RequireScopeParams() gin.HandlerFunc {
	return func(c *gin.Context) { c.Next() }
}

func TestG3PlatformSnapshotRoutesExposeOnlyBoundedMachineReads(t *testing.T) {
	gin.SetMode(gin.TestMode)
	engine := gin.New()
	guards := &rbacGuards{apiKeyAuthorizer: middleware.NewAPIKeyRouteAuthorizer()}
	h := handler.NewG3PlatformSnapshotsHandler(handler.NewWikiReleaseHandler(nil), nil, nil, nil)
	RegisterG3PlatformSnapshotRoutes(
		engine.Group("/api/v1"), h, g3PlatformScopeMiddlewareStub{},
		handler.NewWikiReleaseHandler(nil), guards,
	)
	routes := map[string]bool{}
	for _, route := range engine.Routes() {
		routes[route.Method+" "+route.Path] = true
	}
	prefix := "/api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/platform"
	require.True(t, routes[http.MethodGet+" "+prefix+"/uploads/:run_id/:ordinal"])
	require.True(t, routes[http.MethodGet+" "+prefix+"/files/by-sha256/:sha256"])
	require.True(t, routes[http.MethodGet+" "+prefix+"/uploads/:run_id/:ordinal/reparse"])
	require.True(t, routes[http.MethodPost+" "+prefix+"/uploads/:run_id/:ordinal/reparse"])
	require.True(t, routes[http.MethodPost+" "+prefix+"/sources/:knowledge_id/attempts/:attempt/snapshot"])
	require.True(t, routes[http.MethodGet+" "+prefix+"/bases/:release_id/epochs/:epoch"])

	uploadPolicy, ok := guards.apiKeyAuthorizer.Lookup(http.MethodGet, prefix+"/uploads/:run_id/:ordinal")
	require.True(t, ok)
	require.Contains(t, uploadPolicy.Capabilities, types.APIKeyCapabilityRetrieve)
	fingerprintPolicy, ok := guards.apiKeyAuthorizer.Lookup(http.MethodGet, prefix+"/files/by-sha256/:sha256")
	require.True(t, ok)
	require.Contains(t, fingerprintPolicy.Capabilities, types.APIKeyCapabilityRetrieve)
	reparsePolicy, ok := guards.apiKeyAuthorizer.Lookup(http.MethodPost, prefix+"/uploads/:run_id/:ordinal/reparse")
	require.True(t, ok)
	require.Contains(t, reparsePolicy.Capabilities, types.APIKeyCapabilityIngest)
	sourcePolicy, ok := guards.apiKeyAuthorizer.Lookup(http.MethodPost, prefix+"/sources/:knowledge_id/attempts/:attempt/snapshot")
	require.True(t, ok)
	require.Contains(t, sourcePolicy.Capabilities, types.APIKeyCapabilityIngest)
}
