package router

import (
	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/gin-gonic/gin"
)

// RegisterKnowledgeRevisionSourceRoutes mounts the operational source mutations
// (sealed backfill, exact3 backfill, and S11g's record of a missing commit-time row). It is declared to the global API-key gate only so the explicit
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
	knowledge.POST(
		"/:id/revisions/:attempt/source/record",
		middleware.DenyAPIKeyPrincipal(),
		g.Admin(),
		g.KBAccessWriteFromKnowledgeIDParam("id"),
		h.Record,
	)
	knowledgeBases := g.apiKeyGroup(
		r.Group("/knowledge-bases"), apiKeyIngest(apiKeyFullAccess()),
	)
	knowledgeBases.POST(
		"/:id/revision-sources/exact3/backfill",
		middleware.DenyAPIKeyPrincipal(),
		g.Admin(),
		g.KBAccessWrite("id"),
		func(c *gin.Context) {
			c.Params = append(c.Params, gin.Param{Key: "kb_id", Value: c.Param("id")})
			h.BackfillExact3(c)
		},
	)
}
