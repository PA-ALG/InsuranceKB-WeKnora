package handler

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type g3PlatformUploadLookupStub struct {
	record *service.G3PlatformUploadSnapshotV1
	err    error
}

type g3BoundReparserStub struct {
	request service.G3BoundReparseRequest
	calls int
}
func (s *g3BoundReparserStub) BoundReparseKnowledge(_ context.Context, knowledgeID string, request service.G3BoundReparseRequest) (types.G3BoundReparseReceipt, error) {
	s.calls++
	s.request = request
	return types.G3BoundReparseReceipt{Contract: types.G3BoundReparseContractV1, RunID: request.RunID, Ordinal: request.Ordinal, KnowledgeID: knowledgeID, ExpectedParseAttempt: request.ExpectedParseAttempt, ParseAttempt: request.ExpectedParseAttempt+1, RecoveryKey: request.RecoveryKey, DeadlineAt: request.DeadlineAt, DispatchState: "enqueued"}, nil
}
func (s *g3BoundReparserStub) ReadBoundReparseKnowledge(_ context.Context, knowledgeID, key string) (types.G3BoundReparseReceipt, error) {
	return types.G3BoundReparseReceipt{Contract: types.G3BoundReparseContractV1, RunID: "run-1", Ordinal: 0, KnowledgeID: knowledgeID, ExpectedParseAttempt: 3, ParseAttempt: 4, RecoveryKey: key, DispatchState: "enqueued"}, nil
}

func (s *g3PlatformUploadLookupStub) LookupUpload(
	_ context.Context, _ types.WikiReleaseScope, _ string, _ int,
) (*service.G3PlatformUploadSnapshotV1, error) {
	return s.record, s.err
}

type g3PlatformSourceCapturerStub struct {
	record *service.G3PlatformSignedSourceSnapshotV1
	err    error
}

func (s *g3PlatformSourceCapturerStub) Capture(
	_ context.Context, _ types.WikiReleaseScope, _ string, _ int64,
) (*service.G3PlatformSignedSourceSnapshotV1, error) {
	return s.record, s.err
}

type g3PlatformBaseReaderStub struct {
	record *service.G3PlatformSignedBaseSnapshotV1
	err    error
}

func (s *g3PlatformBaseReaderStub) Read(
	_ context.Context, _ types.WikiReleaseScope, _ string, _ uint64,
) (*service.G3PlatformSignedBaseSnapshotV1, error) {
	return s.record, s.err
}

func newG3PlatformHandlerEngine(
	h *G3PlatformSnapshotsHandler,
) *gin.Engine {
	gin.SetMode(gin.TestMode)
	engine := gin.New()
	engine.Use(func(c *gin.Context) {
		principal := types.Principal{Type: types.PrincipalAPITenant, ID: "42"}
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(42))
		ctx = types.WithPrincipal(ctx, principal)
		ctx = types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{
			KeyID: 91, KnowledgeBaseIDs: types.StringArray{"raw-1", "wiki-1"},
		})
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), uint64(42))
		c.Set(types.PrincipalContextKey.String(), principal)
		c.Next()
	})
	base := "/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/platform"
	engine.GET(base+"/uploads/:run_id/:ordinal", h.Upload)
	engine.GET(base+"/uploads/:run_id/:ordinal/reparse", h.ReparseUpload)
	engine.POST(base+"/uploads/:run_id/:ordinal/reparse", h.ReparseUpload)
	engine.POST(base+"/sources/:knowledge_id/attempts/:attempt/snapshot", h.Source)
	engine.GET(base+"/bases/:release_id/epochs/:epoch", h.Base)
	return engine
}

func TestG3PlatformReparseBindsUploadAndExpectedGeneration(t *testing.T) {
	upload := &g3PlatformUploadLookupStub{record: &service.G3PlatformUploadSnapshotV1{RunID: "run-1", Ordinal: 0, KnowledgeID: "source", ParseAttempt: 3}}
	reparser := &g3BoundReparserStub{}
	h := NewG3PlatformSnapshotsHandler(NewWikiReleaseHandler(nil), upload, nil, nil, reparser)
	engine := newG3PlatformHandlerEngine(h)
	deadline := time.Now().Add(time.Hour).UTC().Format(time.RFC3339Nano)
	body := `{"expected_parse_attempt":3,"recovery_key":"`+strings.Repeat("a",64)+`","deadline_at":"`+deadline+`"}`
	path := "/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/platform/uploads/run-1/0/reparse"
	response := httptest.NewRecorder()
	engine.ServeHTTP(response, httptest.NewRequest(http.MethodPost, path, strings.NewReader(body)))
	require.Equal(t, http.StatusOK, response.Code, response.Body.String())
	require.Equal(t, 1, reparser.calls)
	require.Equal(t, "raw-1", reparser.request.RawKBID)
	require.Equal(t, int64(3), reparser.request.ExpectedParseAttempt)
	require.Contains(t, response.Body.String(), `"dispatch_state":"enqueued"`)
}

func TestG3PlatformSnapshotsHandlerReturnsOnlyVersionedMachineData(t *testing.T) {
	now := time.Date(2026, 9, 13, 12, 0, 0, 0, time.UTC)
	upload := &g3PlatformUploadLookupStub{record: &service.G3PlatformUploadSnapshotV1{
		Contract: service.G3PlatformUploadSnapshotContractV1,
		RunID:    "run-1", Ordinal: 0, KnowledgeID: "knowledge-1", FileName: "terms.pdf",
		ParseStatus: types.ParseStatusCompleted, ParseAttempt: 3,
		CreatedAt: now, UpdatedAt: now, ProcessedAt: &now,
	}}
	source := &g3PlatformSourceCapturerStub{record: &service.G3PlatformSignedSourceSnapshotV1{
		Contract: service.G3PlatformSignedSourceSnapshotContractV1,
		Authority: service.G3PlatformSnapshotAuthorityV1{
			Contract: service.G3PlatformSnapshotAuthorityContractV1,
			Domain:   service.G3PlatformSourceSnapshotSigningDomainV1,
			KeyID:    "source-key-1", PayloadSHA256: strings.Repeat("a", 64),
			Signature: []byte("source-signature"),
		},
	}}
	base := &g3PlatformBaseReaderStub{record: &service.G3PlatformSignedBaseSnapshotV1{
		Contract: service.G3PlatformSignedBaseSnapshotContractV1,
	}}
	h := NewG3PlatformSnapshotsHandler(NewWikiReleaseHandler(nil), upload, source, base)
	engine := newG3PlatformHandlerEngine(h)

	for _, request := range []struct {
		method string
		path   string
		want   string
	}{
		{http.MethodGet, "/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/platform/uploads/run-1/0", service.G3PlatformUploadSnapshotContractV1},
		{http.MethodPost, "/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/platform/sources/knowledge-1/attempts/3/snapshot", service.G3PlatformSignedSourceSnapshotContractV1},
		{http.MethodGet, "/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/platform/bases/release-1/epochs/9", service.G3PlatformSignedBaseSnapshotContractV1},
	} {
		recorder := httptest.NewRecorder()
		engine.ServeHTTP(recorder, httptest.NewRequest(request.method, request.path, nil))
		require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())
		var body struct {
			Success bool            `json:"success"`
			Data    json.RawMessage `json:"data"`
		}
		require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &body))
		require.True(t, body.Success)
		require.Contains(t, string(body.Data), `"contract":"`+request.want+`"`)
		require.NotContains(t, recorder.Body.String(), "file_path")
		if request.method == http.MethodPost {
			require.Contains(t, recorder.Body.String(), `"signature":"c291cmNlLXNpZ25hdHVyZQ=="`)
		}
	}
}

func TestG3PlatformSnapshotsHandlerMapsNotFoundReadinessAndInvalidPath(t *testing.T) {
	upload := &g3PlatformUploadLookupStub{err: service.ErrG3PlatformUploadNotFound}
	source := &g3PlatformSourceCapturerStub{err: service.ErrG3PlatformSnapshotUnavailable}
	h := NewG3PlatformSnapshotsHandler(
		NewWikiReleaseHandler(nil), upload, source, &g3PlatformBaseReaderStub{},
	)
	engine := newG3PlatformHandlerEngine(h)

	tests := []struct {
		method string
		path   string
		status int
		code   string
	}{
		{http.MethodGet, "/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/platform/uploads/run-1/0", http.StatusNotFound, "G3_PLATFORM_UPLOAD_NOT_FOUND"},
		{http.MethodPost, "/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/platform/sources/knowledge-1/attempts/3/snapshot", http.StatusConflict, "G3_PLATFORM_SNAPSHOT_UNAVAILABLE"},
		{http.MethodGet, "/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/platform/uploads/run-1/not-an-ordinal", http.StatusBadRequest, "G3_PLATFORM_REQUEST_INVALID"},
	}
	for _, test := range tests {
		recorder := httptest.NewRecorder()
		engine.ServeHTTP(recorder, httptest.NewRequest(test.method, test.path, nil))
		require.Equal(t, test.status, recorder.Code, recorder.Body.String())
		require.Contains(t, recorder.Body.String(), test.code)
	}
}

func TestG3PlatformSnapshotsHandlerRejectsNonMachinePrincipal(t *testing.T) {
	h := NewG3PlatformSnapshotsHandler(
		NewWikiReleaseHandler(nil), &g3PlatformUploadLookupStub{},
		&g3PlatformSourceCapturerStub{}, &g3PlatformBaseReaderStub{},
	)
	gin.SetMode(gin.TestMode)
	engine := gin.New()
	engine.GET("/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/platform/uploads/:run_id/:ordinal", h.Upload)
	recorder := httptest.NewRecorder()
	engine.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet,
		"/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/platform/uploads/run-1/0", nil))
	require.Equal(t, http.StatusForbidden, recorder.Code)
}
