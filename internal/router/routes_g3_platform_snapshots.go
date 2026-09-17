package router

import (
	"net/http"

	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/gin-gonic/gin"
)

type g3PlatformScopeMiddleware interface {
	RequireScopeParams() gin.HandlerFunc
}

// RegisterG3PlatformSnapshotRoutes mounts the machine source/base adapter under
// the existing active-scope route. Every endpoint repeats the production Wiki
// and RAW ACL evidence chain before the handler reaches its machine authorizer.
func RegisterG3PlatformSnapshotRoutes(
	r *gin.RouterGroup,
	h *handler.G3PlatformSnapshotsHandler,
	scope g3PlatformScopeMiddleware,
	access schemaWikiReleaseAccessMiddleware,
	g *rbacGuards,
) {
	if r == nil || h == nil || scope == nil || access == nil || g == nil {
		return
	}
	platform := r.Group(
		"/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/platform",
	)
	activeGuards := []gin.HandlerFunc{
		g.Viewer(),
		schemaWikiKBAccess(g.KBAccessRead("kb_id")),
		access.RecordWikiAccessEvidence(),
		scope.RequireScopeParams(),
		schemaWikiKBAccess(g.KBAccessRead("raw_kb_id")),
		access.RecordRawAccessEvidence(),
		access.SealAccess(),
	}
	register := func(
		method string,
		path string,
		policy middleware.APIKeyRoutePolicy,
		endpoint gin.HandlerFunc,
	) {
		g.apiKeyRoute(
			platform, method, path, policy,
			append(append([]gin.HandlerFunc(nil), activeGuards...), endpoint)...,
		)
	}
	register(
		http.MethodGet, "/uploads/:run_id/:ordinal",
		apiKeyRetrieve(apiKeyFullAccess()), h.Upload,
	)
	register(
		http.MethodGet, "/files/by-sha256/:sha256",
		apiKeyRetrieve(apiKeyFullAccess()), h.FileBySHA256,
	)
	register(
		http.MethodGet, "/uploads/:run_id/:ordinal/reparse",
		apiKeyRetrieve(apiKeyFullAccess()), h.ReparseUpload,
	)
	writeGuards := append(append([]gin.HandlerFunc(nil), activeGuards...),
		g.KBAccessWrite("raw_kb_id"), g.KBAccessWrite("kb_id"), h.ReparseUpload)
	g.apiKeyRoute(platform, http.MethodPost, "/uploads/:run_id/:ordinal/reparse",
		apiKeyIngest(apiKeyFullAccess()), writeGuards...)
	register(
		http.MethodPost, "/sources/:knowledge_id/attempts/:attempt/snapshot",
		apiKeyIngest(apiKeyFullAccess()), h.Source,
	)
	register(
		http.MethodGet, "/bases/:release_id/epochs/:epoch",
		apiKeyRetrieve(apiKeyFullAccess()), h.Base,
	)
}
