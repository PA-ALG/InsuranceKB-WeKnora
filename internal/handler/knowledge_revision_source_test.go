package handler

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type knowledgeRevisionSourceHTTPStub struct {
	calls   int
	source  *types.KnowledgeRevisionSource
	err     error
	gotID   string
	attempt int64
}

func (s *knowledgeRevisionSourceHTTPStub) BackfillCurrentCompleted(
	_ context.Context, knowledgeID string, attempt int64,
) (*types.KnowledgeRevisionSource, error) {
	s.calls++
	s.gotID = knowledgeID
	s.attempt = attempt
	return s.source, s.err
}

func TestKnowledgeRevisionSourceBackfillReturnsClosedSafeReceipt(t *testing.T) {
	gin.SetMode(gin.TestMode)
	pageCount := 39
	stub := &knowledgeRevisionSourceHTTPStub{source: &types.KnowledgeRevisionSource{
		KnowledgeID: "knowledge-1", ParseAttempt: 2,
		RevisionSourceID: strings.Repeat("a", 64),
		ResourceID:       "resource-private", ResourceHandle: strings.Repeat("h", 22),
		FileSHA256: strings.Repeat("b", 64), ObjectSHA256: strings.Repeat("b", 64),
		Size: 4096, MimeType: "application/pdf", PageCount: &pageCount,
		ManifestAlgorithm: types.RevisionManifestAlgorithm,
		ManifestDigest:    strings.Repeat("c", 64), ChunkCount: 162,
		ImmutableLocator: "resource://" + strings.Repeat("h", 22),
		BindingDigest:    strings.Repeat("d", 64),
		RetentionState:   types.KnowledgeRevisionSourcePinned,
	}}
	h := NewKnowledgeRevisionSourceHandler(stub)
	engine := gin.New()
	engine.POST("/knowledge/:id/revisions/:attempt/source/backfill", h.Backfill)
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(
		http.MethodPost, "/knowledge/knowledge-1/revisions/2/source/backfill", nil,
	)
	engine.ServeHTTP(recorder, request)
	require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())
	require.Equal(t, 1, stub.calls)
	require.Equal(t, "knowledge-1", stub.gotID)
	require.Equal(t, int64(2), stub.attempt)
	var wire map[string]any
	require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &wire))
	encoded := recorder.Body.String()
	require.Contains(t, encoded, "knowledge-revision-source.v1")
	require.NotContains(t, encoded, "resource-private")
	require.NotContains(t, encoded, "resource_handle")
	require.NotContains(t, encoded, "immutable_locator")
}

func TestKnowledgeRevisionSourceBackfillMapsTypedSafeErrors(t *testing.T) {
	for name, test := range map[string]struct {
		err    error
		status int
		code   string
	}{
		"disabled":         {service.ErrRevisionSourceBackfillDisabled, http.StatusServiceUnavailable, "REVISION_SOURCE_BACKFILL_DISABLED"},
		"mismatch":         {service.ErrRevisionSourceMismatch, http.StatusConflict, "REVISION_SOURCE_MISMATCH"},
		"page unavailable": {service.ErrRevisionSourcePageUnavailable, http.StatusUnprocessableEntity, "PAGE_UNAVAILABLE"},
	} {
		t.Run(name, func(t *testing.T) {
			gin.SetMode(gin.TestMode)
			stub := &knowledgeRevisionSourceHTTPStub{err: test.err}
			h := NewKnowledgeRevisionSourceHandler(stub)
			engine := gin.New()
			engine.POST("/knowledge/:id/revisions/:attempt/source/backfill", h.Backfill)
			recorder := httptest.NewRecorder()
			request := httptest.NewRequest(
				http.MethodPost, "/knowledge/private-id/revisions/2/source/backfill", nil,
			)
			engine.ServeHTTP(recorder, request)
			require.Equal(t, test.status, recorder.Code, recorder.Body.String())
			require.Contains(t, recorder.Body.String(), test.code)
			require.NotContains(t, recorder.Body.String(), "private-id")
		})
	}
}
