package router

import (
	"context"

	"github.com/gin-gonic/gin"

	"github.com/Tencent/WeKnora/internal/enterprise/managed"
	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/Tencent/WeKnora/internal/types"
)

// probeOwnerKBs resolves every probed kb_id to a tenant-owned knowledge base,
// so release custody can classify it.
type probeOwnerKBs struct{}

func (probeOwnerKBs) GetKnowledgeBaseByID(_ context.Context, id string) (*types.KnowledgeBase, error) {
	return &types.KnowledgeBase{ID: id, TenantID: 1}, nil
}

func (k probeOwnerKBs) GetKnowledgeBaseByIDOnly(ctx context.Context, id string) (*types.KnowledgeBase, error) {
	return k.GetKnowledgeBaseByID(ctx, id)
}

// registerCustodyWikiRoutes registers the native Wiki table with release
// custody wired the way production wires it, for unmanaged knowledge bases.
// Upstream's operation-catalog probe then sees its role guards decide, as on
// a deployment where every probed library is outside the release chain.
func registerCustodyWikiRoutes(v1 *gin.RouterGroup, g *rbacGuards) {
	guards := *g
	if guards.kbService == nil {
		guards.kbService = probeOwnerKBs{}
	}
	RegisterWikiPageRoutes(v1, &handler.WikiPageHandler{}, &guards, &stubClassifier{roles: map[string]managed.Role{}})
}
