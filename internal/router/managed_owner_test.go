package router

import (
	"context"
	"net/http"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/managed"
	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type ownerAwareRouteClassifier struct {
	role    managed.Role
	tenants []uint64
}

func (c *ownerAwareRouteClassifier) Classify(_ context.Context, tenant uint64, _ string) (managed.Role, error) {
	c.tenants = append(c.tenants, tenant)
	if tenant == 42 {
		return c.role, nil
	}
	return managed.Role{Kind: managed.KindNone, State: managed.StateUnmanaged}, nil
}

func TestNativeWikiWritesClassifySharedKnowledgeBaseOwner(t *testing.T) {
	for _, kind := range []managed.Kind{managed.KindWiki, managed.KindRaw} {
		for _, state := range []managed.State{managed.StatePending, managed.StateActive} {
			t.Run(string(kind)+"/"+string(state), func(t *testing.T) {
				classifier := &ownerAwareRouteClassifier{role: managed.Role{Kind: kind, State: state}}
				lookup := &stubWikiKBLookup{kbs: map[string]*types.KnowledgeBase{
					"shared": {ID: "shared", TenantID: 42, Type: types.KnowledgeBaseTypeWiki},
				}}
				engine := newKBRouteTestEngine(t, 7, lookup, nil, func(r *gin.RouterGroup, g *rbacGuards) {
					RegisterWikiPageRoutesWithRelease(r, &handler.WikiPageHandler{}, nil, g, classifier)
				})
				routes := nativeWikiWriteRoutes(engine)
				require.Len(t, routes, 11)
				for _, route := range routes {
					rec := serve(engine, route.Method, concretePath(route.Path, "shared"))
					require.Equal(t, http.StatusConflict, rec.Code, route.Path+" "+rec.Body.String())
					require.Equal(t, managed.ErrorCodeReleaseManaged, errorCode(t, rec))
				}
				require.Len(t, classifier.tenants, len(routes))
				for _, tenant := range classifier.tenants {
					require.Equal(t, uint64(42), tenant)
				}
			})
		}
	}
}
