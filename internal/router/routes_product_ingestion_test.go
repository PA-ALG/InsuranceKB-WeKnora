package router

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

func TestProductIngestionRoutesKeepExistingUploadAndExposeScopedTaskEntries(t *testing.T) {
	gin.SetMode(gin.TestMode)
	engine := gin.New()
	engine.Use(middleware.ErrorHandler())
	group := engine.Group("/api/v1")
	guards := &rbacGuards{}
	RegisterKnowledgeRoutes(group, &handler.KnowledgeHandler{}, guards)
	RegisterProductIngestionRoutes(group, handler.NewProductIngestionHandler(nil, nil), guards)
	routes := map[string]bool{}
	for _, route := range engine.Routes() {
		routes[route.Method+" "+route.Path] = true
	}
	prefix := "/api/v1/knowledge-bases/:id/product-ingestions"
	for _, route := range []string{"GET " + prefix + "/capabilities", "POST " + prefix + "/uploads",
		"GET " + prefix, "GET " + prefix + "/:run_id", "POST " + prefix + "/:run_id/retry-fields", "POST " + prefix + "/:run_id/retry-processing"} {
		require.True(t, routes[route], route)
	}
	require.True(t, routes["POST /api/v1/knowledge-bases/:id/knowledge/file"])
}

func TestProductIngestionRoutesRejectAnonymousBeforeHandler(t *testing.T) {
	gin.SetMode(gin.TestMode)
	enabled := true
	guards := &rbacGuards{cfg: &config.Config{Tenant: &config.TenantConfig{EnableRBAC: &enabled}}}
	guards.kbCreator = func(*gin.Context) (string, error) { return "kb-owner", nil }
	engine := gin.New()
	engine.Use(middleware.ErrorHandler())
	RegisterProductIngestionRoutes(engine.Group("/api/v1"), handler.NewProductIngestionHandler(nil, nil), guards)
	for _, endpoint := range []struct{ method, path string }{
		{"GET", "/capabilities"}, {"GET", ""}, {"GET", "/run"},
		{"POST", "/uploads"}, {"POST", "/run/retry-fields"}, {"POST", "/run/retry-processing"},
	} {
		recorder := httptest.NewRecorder()
		engine.ServeHTTP(recorder, httptest.NewRequest(endpoint.method,
			"/api/v1/knowledge-bases/raw/product-ingestions"+endpoint.path, nil))
		require.Contains(t, []int{http.StatusUnauthorized, http.StatusForbidden}, recorder.Code,
			"%s %s: %s", endpoint.method, endpoint.path, recorder.Body.String())
	}
}
