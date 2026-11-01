package handler

// S11g acceptance: POST .../revisions/:attempt/source/record defaults to a dry run, writes only with
// dry_run=false, and returns a closed receipt without storage identifiers.
// Spec: docs/design/slices/S11g-Office来源修订记录.md §2.2.

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/revisionsource"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type knowledgeRevisionSourceRecordStub struct {
	knowledgeRevisionSourceHTTPStub
	recordCalls int
	gotDryRun   bool
	outcome     types.RevisionSourceRecordOutcome
	recordErr   error
}

func (s *knowledgeRevisionSourceRecordStub) RecordMissingSource(
	_ context.Context, knowledgeID string, attempt int64, dryRun bool,
) (*types.KnowledgeRevisionSource, types.RevisionSourceRecordOutcome, error) {
	s.recordCalls++
	s.gotID, s.attempt, s.gotDryRun = knowledgeID, attempt, dryRun
	if s.recordErr != nil {
		return nil, "", s.recordErr
	}
	return &types.KnowledgeRevisionSource{
		KnowledgeID: knowledgeID, ParseAttempt: attempt,
		RevisionSourceID: strings.Repeat("a", 64), ResourceID: "resource-private",
		ResourceHandle: strings.Repeat("h", 22), FileSHA256: strings.Repeat("b", 64),
		ObjectSHA256: strings.Repeat("b", 64), Size: 4096,
		MimeType:          "application/vnd.openxmlformats-officedocument.presentationml.presentation",
		ManifestAlgorithm: types.RevisionManifestAlgorithm, ManifestDigest: strings.Repeat("c", 64),
		ChunkCount: 12, ImmutableLocator: "resource://" + strings.Repeat("h", 22),
		RetentionState: types.KnowledgeRevisionSourceReleased,
	}, s.outcome, nil
}

func recordRequest(t *testing.T, stub *knowledgeRevisionSourceRecordStub, query string) *httptest.ResponseRecorder {
	t.Helper()
	gin.SetMode(gin.TestMode)
	h := NewKnowledgeRevisionSourceHandler(stub)
	engine := gin.New()
	engine.POST("/knowledge/:id/revisions/:attempt/source/record", h.Record)
	recorder := httptest.NewRecorder()
	engine.ServeHTTP(recorder, httptest.NewRequest(
		http.MethodPost, "/knowledge/knowledge-1/revisions/2/source/record"+query, nil,
	))
	return recorder
}

func TestKnowledgeRevisionSourceRecordDefaultsToADryRun(t *testing.T) {
	for query, wantDryRun := range map[string]bool{"": true, "?dry_run=true": true, "?dry_run=false": false} {
		stub := &knowledgeRevisionSourceRecordStub{outcome: types.RevisionSourceRecordWouldRecord}
		recorder := recordRequest(t, stub, query)
		require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())
		require.Equal(t, 1, stub.recordCalls)
		require.Equal(t, wantDryRun, stub.gotDryRun, query)
		require.Equal(t, "knowledge-1", stub.gotID)
		require.Equal(t, int64(2), stub.attempt)
		encoded := recorder.Body.String()
		require.Contains(t, encoded, "knowledge-revision-source-record.v1")
		require.Contains(t, encoded, string(types.RevisionSourceRecordWouldRecord))
		require.NotContains(t, encoded, "resource-private")
		require.NotContains(t, encoded, "resource_handle")
		require.NotContains(t, encoded, "immutable_locator")
	}
}

func TestKnowledgeRevisionSourceRecordRejectsAmbiguousDryRunAndMapsErrors(t *testing.T) {
	stub := &knowledgeRevisionSourceRecordStub{}
	recorder := recordRequest(t, stub, "?dry_run=maybe")
	require.Equal(t, http.StatusConflict, recorder.Code)
	require.Zero(t, stub.recordCalls)

	stub = &knowledgeRevisionSourceRecordStub{recordErr: revisionsource.ErrRevisionSourceBackfillDisabled}
	recorder = recordRequest(t, stub, "?dry_run=false")
	require.Equal(t, http.StatusServiceUnavailable, recorder.Code)
	require.Contains(t, recorder.Body.String(), "REVISION_SOURCE_BACKFILL_DISABLED")
}
