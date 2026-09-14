package router

import (
	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/gin-gonic/gin"
)

func RegisterProductIngestionRoutes(r *gin.RouterGroup, h *handler.ProductIngestionHandler, g *rbacGuards) {
	if h == nil {
		return
	}
	writes := g.apiKeyGroup(r.Group("/knowledge-bases/:id/product-ingestions"), apiKeyIngest(apiKeyFullAccess()))
	reads := writes.With(apiKeyRetrieve(apiKeyFullAccess()))
	reads.GET("/capabilities", g.Viewer(), g.KBAccessRead("id"), h.Capabilities)
	reads.GET("", g.Viewer(), g.KBAccessRead("id"), h.List)
	reads.GET("/:run_id", g.Viewer(), g.KBAccessRead("id"), h.Get)
	writes.POST("/uploads", g.OwnedKBOrAdmin(), g.KBAccessWrite("id"), h.Upload)
	writes.POST("/:run_id/retry-fields", g.OwnedKBOrAdmin(), g.KBAccessWrite("id"), h.RetryFields)
	writes.POST("/:run_id/retry-processing", g.OwnedKBOrAdmin(), g.KBAccessWrite("id"), h.RetryProcessing)
}
