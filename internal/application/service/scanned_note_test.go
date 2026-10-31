// S11f acceptance (protected, written by Claude): an uncaptured enterprise upload records why.
// Spec docs/design/slices/S11f-未采集材料带类型原因.md §3.2. RED until S11f: no note is written, so
// the page API cannot name the reason.
package service

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/capture"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
)

func notCapturedReason(t *testing.T, err error) (string, int) {
	t.Helper()
	var failure *source.Error
	require.True(t, errors.As(err, &failure), "%v", err)
	require.Equal(t, source.ErrorNotCaptured, failure.Code)
	return failure.Reason, failure.Page
}

func TestAScannedEnterprisePDFNamesItsFirstScannedPage(t *testing.T) {
	u := uploadToEnterpriseRawKB(t, &types.ReadResult{Error: "page 5 is scanned"})
	spans := &captureSpans{}
	u.service.spanTracker = NewSpanTracker(spans, nil)
	require.NoError(t, u.service.ProcessDocument(context.Background(), u.task))
	require.NotEqual(t, types.ParseStatusFailed, u.knowledge.ParseStatus)
	require.Empty(t, u.chunks.written)

	_, err := u.pages(3)
	reason, page := notCapturedReason(t, err)
	require.Equal(t, source.NotCapturedScannedPage, reason)
	require.Equal(t, 5, page)

	entries, err := os.ReadDir(u.store.root)
	if err == nil {
		require.Empty(t, entries, "the capture directory still holds no first-parse record")
	} else {
		require.ErrorIs(t, err, os.ErrNotExist)
	}
	var stage *types.KnowledgeProcessingSpan
	for i := range spans.rows {
		if spans.rows[i].Name == types.StageDocReader {
			stage = &spans.rows[i]
		}
	}
	require.NotNil(t, stage)
	require.Equal(t, types.SpanStatusDone, stage.Status)
	require.Equal(t, types.JSONMap{"first_parse_saved": false, "not_captured_reason": "scanned_page"}, stage.Output,
		"the stage output is unchanged")
}

func TestAScannedPDFWithoutATrustedRevisionWritesNoNote(t *testing.T) {
	u := uploadToEnterpriseRawKB(t, &types.ReadResult{Error: "page 5 is scanned"})
	var payload types.DocumentProcessPayload
	require.NoError(t, json.Unmarshal(u.task.Payload(), &payload))
	payload.Revision.ParseAttempt = 2 // not the knowledge's current attempt 3
	kb := u.service.kbService.(*createKnowledgeFileKBServiceStub).kb
	_, err := u.service.convert(context.Background(), payload, kb, u.knowledge, ResolveProcessConfig(kb, nil), true)
	require.NoError(t, err)
	_, err = u.pages(3)
	reason, page := notCapturedReason(t, err)
	require.Equal(t, source.NotCapturedNotRecorded, reason, "no trusted identity, no note")
	require.Zero(t, page)
}

func TestAnUnreadableOfficeUploadNotesWhy(t *testing.T) {
	data := []byte("not a zip package")
	c := newOfficeCaptureCase(t, data)
	c.svc.captureOffice(context.Background(), c.knowledge, c.payload, "pptx", data)
	_, err := c.read(t)
	require.True(t, errors.Is(err, os.ErrNotExist), "still no capture")

	k := *c.knowledge
	k.FileType = "pptx"
	repo := &sourcePagesRepository{knowledge: &k, revision: &types.KnowledgeRevision{
		KnowledgeID: k.ID, ParseAttempt: 3, FileSHA256: c.id.SourceSHA256,
	}}
	scope := types.WikiReleaseScope{TenantID: 7, SpaceID: "space", RawKBID: "raw-1", WikiKBID: "wiki"}
	_, err = capture.ReadSourceArtifact(context.Background(), capture.NewStore(c.root, captureTestKeys(t)),
		repo, scope, k.ID, 3)
	var reason *source.NotCaptured
	require.True(t, errors.As(err, &reason), "%v", err)
	require.Equal(t, source.NotCapturedOfficeUnreadable, reason.Reason)
	require.Zero(t, reason.Page)

	unbound := newOfficeCaptureCase(t, data)
	unbound.payload.Revision.FileSHA256 = captureTestSHA256("other bytes")
	unbound.svc.captureOffice(context.Background(), unbound.knowledge, unbound.payload, "pptx", data)
	_, err = os.ReadDir(unbound.root + "-notes")
	require.True(t, errors.Is(err, os.ErrNotExist), "a revision that does not bind to the bytes gets no note")
}
