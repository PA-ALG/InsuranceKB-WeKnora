package router

import (
	"net/http"

	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/gin-gonic/gin"
)

// RegisterG3PlatformReleaseRoutes keeps system writes separate from the human
// review routes while retaining current WIKI-write and RAW-read ACL evidence.
func RegisterG3PlatformReleaseRoutes(r *gin.RouterGroup, h *handler.G3PlatformReleaseHandler, scope g3PlatformScopeMiddleware, access schemaWikiReleaseAccessMiddleware, g *rbacGuards) {
	if r == nil || h == nil || scope == nil || access == nil || g == nil {
		return
	}
	platform := r.Group("/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/platform")
	guards := []gin.HandlerFunc{
		g.Contributor(),
		schemaWikiKBAccess(g.KBAccessWrite("kb_id")),
		access.RecordWikiAccessEvidence(),
		scope.RequireScopeParams(),
		schemaWikiKBAccess(g.KBAccessRead("raw_kb_id")),
		access.RecordRawAccessEvidence(),
		access.SealAccess(),
	}
	for _, route := range []struct {
		path     string
		endpoint gin.HandlerFunc
	}{
		{"/preparations", h.CreatePreparation},
		{"/preparations/:preparation_id/review", h.ReviewPreparation},
		{"/activate", h.Activate},
	} {
		g.apiKeyRoute(platform, http.MethodPost, route.path, apiKeyIngest(apiKeyFullAccess()), append(append([]gin.HandlerFunc(nil), guards...), route.endpoint)...)
	}
}
