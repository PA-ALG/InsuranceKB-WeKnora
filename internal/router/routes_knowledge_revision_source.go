package router

import (
	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/gin-gonic/gin"
)

// RegisterKnowledgeRevisionSourceRoutes mounts the sole operational source
// mutation. It is declared to the global API-key gate only so the explicit
// DenyAPIKeyPrincipal guard remains load-bearing before the human Admin gate.
func RegisterKnowledgeRevisionSourceRoutes(
	r *gin.RouterGroup,
	h *handler.KnowledgeRevisionSourceHandler,
	g *rbacGuards,
) {
	if r == nil || h == nil || g == nil {
		return
	}
	knowledge := g.apiKeyGroup(r.Group("/knowledge"), apiKeyIngest(apiKeyFullAccess()))
	knowledge.POST(
		"/:id/revisions/:attempt/source/backfill",
		middleware.DenyAPIKeyPrincipal(),
		g.Admin(),
		g.KBAccessWriteFromKnowledgeIDParam("id"),
		h.Backfill,
	)
	knowledgeBases := g.apiKeyGroup(
		r.Group("/knowledge-bases"), apiKeyIngest(apiKeyFullAccess()),
	)
	knowledgeBases.POST(
		"/:kb_id/revision-sources/exact3/backfill",
		middleware.DenyAPIKeyPrincipal(),
		g.Admin(),
		g.KBAccessWrite("kb_id"),
		h.BackfillExact3,
	)
}
