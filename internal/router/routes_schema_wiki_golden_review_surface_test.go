package router

import (
	"net/http"
	"testing"

	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

func TestSchemaWikiGoldenReviewSurfaceRoutesArePreparationScoped(t *testing.T) {
	t.Parallel()
	engine := gin.New()
	RegisterSchemaWikiRoutes(
		engine.Group("/api/v1"),
		&handler.SchemaWikiHandler{},
		&handler.WikiReleaseHandler{},
		&rbacGuards{},
	)

	paths := map[string]bool{}
	for _, route := range engine.Routes() {
		paths[route.Method+" "+route.Path] = true
	}
	prefix := "/api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema"
	require.True(t, paths[http.MethodGet+" "+prefix+"/preparations/:preparation_id/golden-quality/evaluations/:evaluation_id/summary"])
	require.True(t, paths[http.MethodGet+" "+prefix+"/preparations/:preparation_id/golden-quality/evaluations/:evaluation_id/dossier"])
	require.True(t, paths[http.MethodGet+" "+prefix+"/preparations/:preparation_id/golden-quality/evaluations/:evaluation_id/fields/:field_id/evidence/:evidence_id/preview"])
	require.False(t, paths[http.MethodGet+" "+prefix+"/releases/:release_id/quality-dossier"])
	require.False(t, paths[http.MethodGet+" "+prefix+"/quality/latest"])
	require.False(t, paths[http.MethodGet+" "+prefix+"/quality/current"])
}
