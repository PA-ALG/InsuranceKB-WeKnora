package handler

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type productGatewayBridgeStub struct {
	created  int
	reads    int
	retries  int
	expected int
	fail     bool
}

func (s *productGatewayBridgeStub) Scope() service.ProductIngestionScope {
	return service.ProductIngestionScope{TenantID: 1, SpaceID: "space", RawKnowledgeBaseID: "raw", WikiKnowledgeBaseID: "wiki"}
}
func (s *productGatewayBridgeStub) MaxUploadFiles() int   { return 3 }
func (s *productGatewayBridgeStub) MaxUploadBytes() int64 { return 1 << 20 }
func (s *productGatewayBridgeStub) CreateRun(_ context.Context, count int) (*service.ProductIngestionRun, error) {
	s.created++
	s.expected = count
	if s.fail {
		return nil, errors.New("SECRET_UPSTREAM")
	}
	return &service.ProductIngestionRun{RunID: "server-run", State: "accepting_uploads"}, nil
}
func (s *productGatewayBridgeStub) ListRuns(context.Context) ([]service.ProductIngestionRun, error) {
	s.reads++
	return []service.ProductIngestionRun{{RunID: "server-run", State: "running"}}, nil
}
func (s *productGatewayBridgeStub) GetRun(context.Context, string) (*service.ProductIngestionRun, error) {
	s.reads++
	return &service.ProductIngestionRun{RunID: "server-run", State: "running"}, nil
}
func (s *productGatewayBridgeStub) RetryFields(_ context.Context, _ string, keys []string) (*service.ProductIngestionRun, error) {
	s.retries++
	return &service.ProductIngestionRun{RunID: "retry-run", State: "running"}, nil
}

type productGatewayKBStub struct {
	interfaces.KnowledgeBaseService
	denyWiki bool
	seen     []string
}

func (s *productGatewayKBStub) GetKnowledgeBaseByID(_ context.Context, id string) (*types.KnowledgeBase, error) {
	s.seen = append(s.seen, id)
	tenant := uint64(1)
	if id == "wiki" && s.denyWiki {
		tenant = 2
	}
	return &types.KnowledgeBase{ID: id, TenantID: tenant, CreatorID: "creator"}, nil
}

type productGatewayUploadStub struct {
	interfaces.KnowledgeService
	bridge     *productGatewayBridgeStub
	t          *testing.T
	calls      int
	failSecond bool
	markers    []string
}

func (s *productGatewayUploadStub) CreateKnowledgeFromFile(ctx context.Context, kb string, file *multipart.FileHeader, metadata map[string]string, multi *bool, name string, tags []string, channel string, overrides *types.KnowledgeProcessOverrides) (*types.Knowledge, error) {
	require.Equal(s.t, 1, s.bridge.created, "durable run must precede saving any original")
	require.Equal(s.t, uint64(1), ctx.Value(types.TenantIDContextKey))
	require.Equal(s.t, "raw", kb)
	require.Len(s.t, metadata, 1)
	require.Nil(s.t, multi)
	require.Empty(s.t, name)
	require.Empty(s.t, tags)
	require.Nil(s.t, overrides)
	body, err := file.Open()
	require.NoError(s.t, err)
	defer body.Close()
	data, _ := io.ReadAll(body)
	require.Equal(s.t, "ORIGINAL", string(data))
	s.markers = append(s.markers, metadata["product_ingestion_upload"])
	s.calls++
	if s.failSecond && s.calls == 2 {
		return nil, errors.New("SECRET_STORAGE")
	}
	return &types.Knowledge{ID: fmt.Sprint(s.calls)}, nil
}
func productGatewayRouter(t *testing.T, bridge *productGatewayBridgeStub, kb *productGatewayKBStub, role types.TenantRole) (*gin.Engine, *productGatewayUploadStub) {
	gin.SetMode(gin.TestMode)
	kg := &productGatewayUploadStub{bridge: bridge, t: t}
	cfg := &config.Config{}
	kh := NewKnowledgeHandler(cfg, kg, kb, nil, nil, nil, nil)
	handler := NewProductIngestionHandler(kh, bridge)
	r := gin.New()
	r.Use(middleware.ErrorHandler())
	r.Use(func(c *gin.Context) {
		c.Set(types.TenantIDContextKey.String(), uint64(1))
		c.Set(types.UserIDContextKey.String(), "viewer")
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(1))
		ctx = context.WithValue(ctx, types.TenantRoleContextKey, role)
		c.Request = c.Request.WithContext(ctx)
		c.Next()
	})
	const base = "/api/v1/knowledge-bases/:id/product-ingestions"
	r.GET(base+"/capabilities", handler.Capabilities)
	r.POST(base+"/uploads", handler.Upload)
	r.GET(base, handler.List)
	r.GET(base+"/:run_id", handler.Get)
	r.POST(base+"/:run_id/retry-fields", handler.RetryFields)
	return r, kg
}
func productUploadRequest(t *testing.T, count int, extra string) *http.Request {
	var body bytes.Buffer
	w := multipart.NewWriter(&body)
	for i := 0; i < count; i++ {
		part, err := w.CreateFormFile("files", fmt.Sprintf("original-%d.pdf", i))
		require.NoError(t, err)
		_, _ = part.Write([]byte("ORIGINAL"))
	}
	if extra != "" {
		require.NoError(t, w.WriteField(extra, `{"candidate":"client"}`))
	}
	require.NoError(t, w.Close())
	r := httptest.NewRequest(http.MethodPost, "/api/v1/knowledge-bases/raw/product-ingestions/uploads", &body)
	r.Header.Set("Content-Type", w.FormDataContentType())
	return r
}
func TestProductIngestionGatewayUploadsOnlyOriginalsAfterAdmission(t *testing.T) {
	bridge := &productGatewayBridgeStub{}
	kb := &productGatewayKBStub{}
	router, kg := productGatewayRouter(t, bridge, kb, types.TenantRoleAdmin)
	kg.failSecond = true
	response := httptest.NewRecorder()
	router.ServeHTTP(response, productUploadRequest(t, 3, ""))
	require.Equal(t, 200, response.Code, response.Body.String())
	require.Equal(t, 3, bridge.expected)
	require.Equal(t, 3, kg.calls)
	require.Equal(t, []string{"server-run:0", "server-run:1", "server-run:2"}, kg.markers)
	require.JSONEq(t, `{"success":true,"data":{"run_id":"server-run","accepted_file_count":2,"rejected_file_count":1}}`, response.Body.String())
	require.Contains(t, kb.seen, "wiki")
	require.NotContains(t, response.Body.String(), "SECRET_STORAGE")
}
func TestProductIngestionGatewayRejectsClientSemanticFieldsAndCapacityBeforeAdmission(t *testing.T) {
	for _, extra := range []string{"candidate", "metadata", "process_config"} {
		t.Run(extra, func(t *testing.T) {
			bridge := &productGatewayBridgeStub{}
			router, kg := productGatewayRouter(t, bridge, &productGatewayKBStub{}, types.TenantRoleAdmin)
			response := httptest.NewRecorder()
			router.ServeHTTP(response, productUploadRequest(t, 1, extra))
			require.Equal(t, 400, response.Code, response.Body.String())
			require.Zero(t, bridge.created)
			require.Zero(t, kg.calls)
		})
	}
	bridge := &productGatewayBridgeStub{}
	router, _ := productGatewayRouter(t, bridge, &productGatewayKBStub{}, types.TenantRoleAdmin)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, productUploadRequest(t, 4, ""))
	require.Equal(t, 400, response.Code)
	require.Zero(t, bridge.created)
}
func TestProductIngestionGatewayChecksWikiReadAndWriteACL(t *testing.T) {
	for _, path := range []string{"/capabilities", "", "/server-run"} {
		bridge := &productGatewayBridgeStub{}
		router, _ := productGatewayRouter(t, bridge, &productGatewayKBStub{denyWiki: true}, types.TenantRoleAdmin)
		response := httptest.NewRecorder()
		router.ServeHTTP(response, httptest.NewRequest("GET", "/api/v1/knowledge-bases/raw/product-ingestions"+path, nil))
		require.Equal(t, 403, response.Code, response.Body.String())
		require.Zero(t, bridge.reads)
	}
	for _, test := range []struct {
		denyWiki bool
		role     types.TenantRole
	}{{true, types.TenantRoleAdmin}, {false, types.TenantRoleViewer}} {
		bridge := &productGatewayBridgeStub{}
		router, kg := productGatewayRouter(t, bridge, &productGatewayKBStub{denyWiki: test.denyWiki}, test.role)
		response := httptest.NewRecorder()
		router.ServeHTTP(response, productUploadRequest(t, 1, ""))
		require.Equal(t, 403, response.Code, response.Body.String())
		require.Zero(t, bridge.created)
		require.Zero(t, kg.calls)
	}
}
func TestProductIngestionGatewayCapabilityMatchesOnlyConfiguredRaw(t *testing.T) {
	bridge := &productGatewayBridgeStub{}
	router, _ := productGatewayRouter(t, bridge, &productGatewayKBStub{}, types.TenantRoleAdmin)
	for _, id := range []string{"raw", "other"} {
		response := httptest.NewRecorder()
		router.ServeHTTP(response, httptest.NewRequest("GET", "/api/v1/knowledge-bases/"+id+"/product-ingestions/capabilities", nil))
		require.Equal(t, 200, response.Code)
		require.JSONEq(t, fmt.Sprintf(`{"success":true,"data":{"enabled":%t}}`, id == "raw"), response.Body.String())
	}
	require.Zero(t, bridge.created)
	require.Zero(t, bridge.reads)
}
func TestProductIngestionGatewayAdmissionFailureNeverUploadsOrLeaksDetails(t *testing.T) {
	bridge := &productGatewayBridgeStub{fail: true}
	router, kg := productGatewayRouter(t, bridge, &productGatewayKBStub{}, types.TenantRoleAdmin)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, productUploadRequest(t, 1, ""))
	require.Equal(t, 503, response.Code, response.Body.String())
	require.Zero(t, kg.calls)
	require.NotContains(t, response.Body.String(), "SECRET_UPSTREAM")
}
func TestProductIngestionGatewayReadAndStrictRetryContract(t *testing.T) {
	bridge := &productGatewayBridgeStub{}
	router, _ := productGatewayRouter(t, bridge, &productGatewayKBStub{}, types.TenantRoleAdmin)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest("GET", "/api/v1/knowledge-bases/raw/product-ingestions", nil))
	require.Equal(t, 200, response.Code)
	require.Contains(t, response.Body.String(), `"runs"`)
	for _, body := range []string{`{"field_keys":["premium"],"value":"unverified"}`, `{"field_keys":["premium","premium"]}`, `{"field_keys":[]}`} {
		response = httptest.NewRecorder()
		request := httptest.NewRequest("POST", "/api/v1/knowledge-bases/raw/product-ingestions/server-run/retry-fields", strings.NewReader(body))
		request.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(response, request)
		require.Equal(t, 400, response.Code, response.Body.String())
	}
	require.Zero(t, bridge.retries)
	response = httptest.NewRecorder()
	request := httptest.NewRequest("POST", "/api/v1/knowledge-bases/raw/product-ingestions/server-run/retry-fields", strings.NewReader(`{"field_keys":["premium"]}`))
	request.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(response, request)
	require.Equal(t, 201, response.Code, response.Body.String())
	require.Equal(t, 1, bridge.retries)
}
