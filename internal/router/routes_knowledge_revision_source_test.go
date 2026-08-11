package router

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type revisionSourceRouteBackfiller struct {
	calls int
}

func (s *revisionSourceRouteBackfiller) BackfillCurrentCompleted(
	context.Context, string, int64,
) (*types.KnowledgeRevisionSource, error) {
	s.calls++
	pages := 2
	return &types.KnowledgeRevisionSource{PageCount: &pages}, nil
}

type revisionSourceRouteKnowledgeLookup struct{}

func (revisionSourceRouteKnowledgeLookup) GetKnowledgeByIDOnly(
	context.Context, string,
) (*types.Knowledge, error) {
	return &types.Knowledge{ID: "knowledge-1", KnowledgeBaseID: "raw-kb-1", TenantID: 10003}, nil
}

type revisionSourceRouteKBLookup struct{}

func (revisionSourceRouteKBLookup) GetKnowledgeBaseByID(
	context.Context, string,
) (*types.KnowledgeBase, error) {
	return &types.KnowledgeBase{ID: "raw-kb-1", TenantID: 10003}, nil
}

func TestKnowledgeRevisionSourceRoutesExposeOnlyAdminBackfill(t *testing.T) {
	gin.SetMode(gin.TestMode)
	engine := gin.New()
	RegisterKnowledgeRevisionSourceRoutes(
		engine.Group("/api/v1"),
		handler.NewKnowledgeRevisionSourceHandler(nil),
		&rbacGuards{},
	)
	routes := map[string]string{}
	for _, route := range engine.Routes() {
		routes[route.Method+" "+route.Path] = route.Handler
	}
	require.Contains(t, routes,
		http.MethodPost+" /api/v1/knowledge/:id/revisions/:attempt/source/backfill")
	require.NotContains(t, routes,
		http.MethodGet+" /api/v1/knowledge/:id/revisions/:attempt/source/preview")
}

func TestMainRouterMountsKnowledgeRevisionSourceRoutes(t *testing.T) {
	raw, err := os.ReadFile("router.go")
	require.NoError(t, err)
	source := string(raw)
	require.Contains(t, source, "KnowledgeRevisionSourceHandler *handler.KnowledgeRevisionSourceHandler")
	require.Contains(t, source, "RegisterKnowledgeRevisionSourceRoutes(")
}

func TestKnowledgeRevisionSourceRouteDeniesAPIKeyAndViewerBeforeService(t *testing.T) {
	for name, requestContext := range map[string]func(context.Context) context.Context{
		"api key": func(ctx context.Context) context.Context {
			ctx = context.WithValue(ctx, types.TenantRoleContextKey, types.TenantRoleAdmin)
			return types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{KeyID: 1, FullAccess: true})
		},
		"viewer": func(ctx context.Context) context.Context {
			return context.WithValue(ctx, types.TenantRoleContextKey, types.TenantRoleViewer)
		},
	} {
		t.Run(name, func(t *testing.T) {
			gin.SetMode(gin.TestMode)
			enabled := true
			service := &revisionSourceRouteBackfiller{}
			engine := gin.New()
			engine.Use(func(c *gin.Context) {
				ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(10003))
				c.Request = c.Request.WithContext(requestContext(ctx))
				c.Next()
			})
			RegisterKnowledgeRevisionSourceRoutes(
				engine.Group("/api/v1"),
				handler.NewKnowledgeRevisionSourceHandler(service),
				&rbacGuards{cfg: &config.Config{Tenant: &config.TenantConfig{EnableRBAC: &enabled}}},
			)
			recorder := httptest.NewRecorder()
			request := httptest.NewRequest(
				http.MethodPost,
				"/api/v1/knowledge/knowledge-1/revisions/2/source/backfill",
				nil,
			)
			engine.ServeHTTP(recorder, request)
			require.Equal(t, http.StatusForbidden, recorder.Code, recorder.Body.String())
			require.Zero(t, service.calls)
		})
	}
}

func TestKnowledgeRevisionSourceRouteAllowsAdminAfterExactKBAuthority(t *testing.T) {
	gin.SetMode(gin.TestMode)
	enabled := true
	service := &revisionSourceRouteBackfiller{}
	engine := gin.New()
	engine.Use(func(c *gin.Context) {
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(10003))
		ctx = context.WithValue(ctx, types.TenantRoleContextKey, types.TenantRoleAdmin)
		c.Request = c.Request.WithContext(ctx)
		c.Next()
	})
	RegisterKnowledgeRevisionSourceRoutes(
		engine.Group("/api/v1"),
		handler.NewKnowledgeRevisionSourceHandler(service),
		&rbacGuards{
			cfg:              &config.Config{Tenant: &config.TenantConfig{EnableRBAC: &enabled}},
			knowledgeService: revisionSourceRouteKnowledgeLookup{},
			kbService:        revisionSourceRouteKBLookup{},
		},
	)
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(
		http.MethodPost,
		"/api/v1/knowledge/knowledge-1/revisions/2/source/backfill",
		nil,
	)
	engine.ServeHTTP(recorder, request)
	require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())
	require.Equal(t, 1, service.calls)
}
