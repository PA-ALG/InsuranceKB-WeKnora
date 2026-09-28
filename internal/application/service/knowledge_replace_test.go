package service

import (
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestReplaceKnowledgeFilePreservesIDAndReparsesNewContent(t *testing.T) {
	h := newReplaceFileHarness(t)
	content := "# new body"

	got, err := h.replace(t, content, "notes/sub/b.md",
		map[string]string{"source_updated_at": "2026-09-14T00:00:00Z"})

	require.NoError(t, err)
	require.Equal(t, h.original.ID, got.ID)
	row := h.repo.row
	assert.Equal(t, "new/file.md", row.FilePath)
	assert.Equal(t, md5Hex(content), row.FileHash)
	assert.Equal(t, int64(len(content)), row.FileSize)
	assert.Equal(t, "b.md", row.FileName)
	assert.Equal(t, "b.md", row.Title, "a title that mirrored the file name follows the rename")
	assert.Equal(t, "notes/sub", row.FolderPath)
	assert.Equal(t, types.ParseStatusPending, row.ParseStatus)

	metadata, err := row.Metadata.Map()
	require.NoError(t, err)
	assert.Equal(t, "notes/a.md", metadata["external_id"])
	assert.Equal(t, "2026-09-14T00:00:00Z", metadata["source_updated_at"])
	assert.Equal(t, map[string]interface{}{"nested": true}, metadata["extra"], "unmanaged entries survive")

	require.Len(t, h.tasks.payloads, 1)
	assert.Equal(t, h.original.ID, h.tasks.payloads[0].KnowledgeID)
	assert.Equal(t, "new/file.md", h.tasks.payloads[0].FilePath)
	assert.Equal(t, []string{"save", "dequeue:knowledge-1", "enqueue", "delete:old/file.md"}, h.events,
		"queued parse tasks are dropped before reparse; the old file is deleted only after enqueue")
}

func TestReplaceKnowledgeFileUnchangedContentSkipsReparse(t *testing.T) {
	h := newReplaceFileHarness(t)

	got, err := h.replace(t, replaceFileOldContent, "notes/a.md", map[string]string{"source_updated_at": "later"})

	var dupErr *types.DuplicateKnowledgeError
	require.ErrorAs(t, err, &dupErr)
	require.Equal(t, h.original.ID, got.ID)
	assert.Equal(t, h.original.ID, dupErr.Knowledge.ID)
	assert.Zero(t, h.store.saved)
	assert.Empty(t, h.tasks.payloads)
	assert.Empty(t, h.store.deleted)
	assert.Equal(t, h.original.FilePath, h.repo.row.FilePath)
	assert.Equal(t, "later", h.repo.row.GetMetadata()["source_updated_at"], "changed metadata is still persisted")
}

func TestReplaceKnowledgeFileSaveFailureLeavesKnowledgeUntouched(t *testing.T) {
	h := newReplaceFileHarness(t)
	h.store.saveErr = errors.New("storage unavailable")

	_, err := h.replace(t, "# new body", "notes/a.md", nil)

	require.ErrorIs(t, err, h.store.saveErr)
	assert.Equal(t, h.original, h.repo.row)
	assert.Empty(t, h.store.deleted)
	assert.Empty(t, h.tasks.payloads)
}

func TestReplaceKnowledgeFileSourceUpdateFailureDiscardsNewFile(t *testing.T) {
	h := newReplaceFileHarness(t)
	h.repo.failColumnsCall = 1

	_, err := h.replace(t, "# new body", "notes/a.md", nil)

	require.Error(t, err)
	assert.Equal(t, h.original, h.repo.row)
	assert.Equal(t, []string{"new/file.md"}, h.store.deleted, "the old file must never be deleted")
	assert.Empty(t, h.tasks.payloads)
}

func TestReplaceKnowledgeFileCommittedUpdateReportedAsFailedContinuesReparse(t *testing.T) {
	h := newReplaceFileHarness(t)
	h.repo.failColumnsCall = 1
	h.repo.commitThenFail = true

	got, err := h.replace(t, "# new body", "notes/a.md", nil)

	require.NoError(t, err)
	require.Equal(t, h.original.ID, got.ID)
	assert.Equal(t, "new/file.md", h.repo.row.FilePath)
	assert.Equal(t, types.ParseStatusPending, h.repo.row.ParseStatus)
	assert.Equal(t, []string{"old/file.md"}, h.store.deleted)
	require.Len(t, h.tasks.payloads, 1)
}

func TestReplaceKnowledgeFileReparseFailureRestoresPreviousSource(t *testing.T) {
	h := newReplaceFileHarness(t)
	h.tasks.err = errors.New("queue unavailable")

	_, err := h.replace(t, "# new body", "notes/sub/b.md", map[string]string{"source_updated_at": "later"})

	require.Error(t, err)
	row := h.repo.row
	assert.Equal(t, h.original.ID, row.ID)
	assert.Equal(t, h.original.FilePath, row.FilePath)
	assert.Equal(t, h.original.FileHash, row.FileHash)
	assert.Equal(t, h.original.FileSize, row.FileSize)
	assert.Equal(t, h.original.FileName, row.FileName)
	assert.Equal(t, h.original.Title, row.Title)
	assert.Equal(t, h.original.FolderPath, row.FolderPath)
	assert.JSONEq(t, string(h.original.Metadata), string(row.Metadata))
	assert.Equal(t, types.ParseStatusFailed, row.ParseStatus, "the old index may already be cleaned up")
	assert.Equal(t, []string{"new/file.md"}, h.store.deleted)
}

func TestReplaceKnowledgeFileRestoreFailureKeepsBothFiles(t *testing.T) {
	h := newReplaceFileHarness(t)
	h.tasks.err = errors.New("queue unavailable")
	h.repo.failColumnsCall = 2 // the restore write

	_, err := h.replace(t, "# new body", "notes/a.md", nil)

	require.Error(t, err)
	assert.Equal(t, "new/file.md", h.repo.row.FilePath)
	assert.Empty(t, h.store.deleted)
}

func TestReplaceKnowledgeFileRejectsNonFileKnowledge(t *testing.T) {
	h := newReplaceFileHarness(t)
	h.repo.row.Type = types.KnowledgeTypeManual

	_, err := h.replace(t, "# new body", "notes/a.md", nil)

	require.Error(t, err)
	assert.Zero(t, h.store.saved)
}

func TestReplaceKnowledgeFileRejectsUnsupportedFileType(t *testing.T) {
	h := newReplaceFileHarness(t)

	_, err := h.replace(t, "MZ", "notes/tool.exe", nil)

	require.Error(t, err)
	assert.Zero(t, h.store.saved)
	assert.Equal(t, h.original, h.repo.row)
}

func TestReplaceKnowledgeFileEmptyCustomNameKeepsFolder(t *testing.T) {
	h := newReplaceFileHarness(t)

	_, err := h.replaceNamed(t, "# new body", "a.md", "", nil)

	require.NoError(t, err)
	assert.Equal(t, "notes", h.repo.row.FolderPath)
	assert.Equal(t, "a.md", h.repo.row.FileName)
}

func TestReplaceKnowledgeFileBareCustomNameKeepsFolder(t *testing.T) {
	h := newReplaceFileHarness(t)

	_, err := h.replace(t, "# new body", "b.md", nil)

	require.NoError(t, err)
	assert.Equal(t, "notes", h.repo.row.FolderPath, "a basename must not move the document to the KB root")
	assert.Equal(t, "b.md", h.repo.row.FileName)
}

func TestReplaceKnowledgeFileIgnoresStorageQuota(t *testing.T) {
	h := newReplaceFileHarness(t)
	h.ctx = context.WithValue(h.ctx, types.TenantInfoContextKey, &types.Tenant{
		ID: 7, StorageQuota: 1, StorageUsed: 1,
	})

	got, err := h.replace(t, "# new body", "notes/a.md", nil)

	require.NoError(t, err)
	require.Equal(t, h.original.ID, got.ID)
	assert.Equal(t, types.ParseStatusPending, h.repo.row.ParseStatus)
}

func TestReplaceKnowledgeFileDequeuesInProgressParse(t *testing.T) {
	h := newReplaceFileHarness(t)
	h.repo.row.ParseStatus = types.ParseStatusProcessing

	got, err := h.replace(t, "# new body", "notes/a.md", nil)

	require.NoError(t, err)
	require.Equal(t, h.original.ID, got.ID)
	assert.Contains(t, h.events, "dequeue:knowledge-1")
	assert.Equal(t, types.ParseStatusPending, h.repo.row.ParseStatus)
	assert.Equal(t, "disabled", h.repo.row.EnableStatus)
}

func TestReplaceKnowledgeFileRejectsFAQKnowledgeBase(t *testing.T) {
	h := newReplaceFileHarness(t)
	h.svc.kbService = &reparseFailureKBService{kb: &types.KnowledgeBase{
		ID: "kb-1", TenantID: 7, Type: types.KnowledgeBaseTypeFAQ,
	}}

	_, err := h.replace(t, "# new body", "notes/a.md", nil)

	require.Error(t, err)
	assert.Zero(t, h.store.saved)
}

func TestIsKnowledgeSourceReplaced(t *testing.T) {
	h := newReplaceFileHarness(t)
	loaded := h.original
	assert.False(t, h.svc.isKnowledgeSourceReplaced(h.ctx, &loaded))

	h.repo.row.FilePath = "new/file.md"
	assert.True(t, h.svc.isKnowledgeSourceReplaced(h.ctx, &loaded))
}

func TestUpdateKnowledgeUnlessSourceReplacedSkipsStaleSave(t *testing.T) {
	h := newReplaceFileHarness(t)
	stale := h.original
	stale.ParseStatus = types.ParseStatusFailed
	h.repo.row.FilePath = "new/file.md"

	require.NoError(t, h.svc.updateKnowledgeUnlessSourceReplaced(h.ctx, &stale))
	assert.Equal(t, "new/file.md", h.repo.row.FilePath)
	assert.NotEqual(t, types.ParseStatusFailed, h.repo.row.ParseStatus)
}

func TestReplaceKnowledgeFileBindsNewBytesWhenPreviousSHAIsNonempty(t *testing.T) {
	h := newReplaceFileHarness(t)
	h.repo.row.FileSHA256 = fmt.Sprintf("%x", sha256.Sum256([]byte(replaceFileOldContent)))
	h.repo.row.CurrentParseAttempt = 3
	content := "# replacement with different bytes"
	wantSHA := fmt.Sprintf("%x", sha256.Sum256([]byte(content)))

	got, err := h.replace(t, content, "notes/a.md", nil)

	require.NoError(t, err)
	require.Len(t, h.tasks.payloads, 1)
	require.NotNil(t, h.tasks.payloads[0].Revision)
	assert.Equal(t, []byte(content), h.store.files[got.FilePath])
	assert.Equal(t, int64(4), got.CurrentParseAttempt)
	assert.Equal(t, wantSHA, got.FileSHA256)
	assert.Equal(t, wantSHA, h.repo.allocatedFileSHA256)
	assert.Equal(t, wantSHA, h.tasks.payloads[0].Revision.FileSHA256)
}

func TestReplaceKnowledgeFileKeepsSourceSHAPairedWithPathDuringCompensation(t *testing.T) {
	for _, tc := range []struct {
		name           string
		legacyEmptySHA bool
		commitThenFail bool
		failRestore    bool
	}{
		{name: "restore previous source"},
		{name: "restore legacy source without SHA", legacyEmptySHA: true},
		{name: "source update committed but reported failure", commitThenFail: true},
		{name: "failed compensation retains replacement source", failRestore: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			h := newReplaceFileHarness(t)
			oldSHA := fmt.Sprintf("%x", sha256.Sum256([]byte(replaceFileOldContent)))
			if tc.legacyEmptySHA {
				oldSHA = ""
			}
			h.original.FileSHA256, h.repo.row.FileSHA256 = oldSHA, oldSHA
			h.tasks.err = errors.New("queue unavailable")
			if tc.commitThenFail {
				h.repo.failColumnsCall, h.repo.commitThenFail = 1, true
			}
			if tc.failRestore {
				h.repo.failColumnsCall = 2
			}
			content := "# replacement source"
			newSHA := fmt.Sprintf("%x", sha256.Sum256([]byte(content)))

			got, err := h.replace(t, content, "notes/a.md", nil)

			require.Error(t, err)
			require.Nil(t, got)
			require.NotEmpty(t, h.repo.sourceSnapshots)
			assert.Equal(t, "new/file.md", h.repo.sourceSnapshots[0].FilePath)
			assert.Equal(t, md5Hex(content), h.repo.sourceSnapshots[0].FileHash)
			assert.Equal(t, newSHA, h.repo.sourceSnapshots[0].FileSHA256)
			assert.Equal(t, newSHA, h.repo.allocatedFileSHA256)
			assert.Empty(t, h.tasks.payloads)
			assert.Equal(t, []byte(replaceFileOldContent), h.store.files["old/file.md"])
			if tc.failRestore {
				require.Len(t, h.repo.sourceSnapshots, 1)
				assert.Equal(t, "new/file.md", h.repo.row.FilePath)
				assert.Equal(t, newSHA, h.repo.row.FileSHA256)
				assert.Equal(t, []byte(content), h.store.files["new/file.md"])
				assert.Empty(t, h.store.deleted)
				return
			}
			require.Len(t, h.repo.sourceSnapshots, 2)
			assert.Equal(t, h.original.FilePath, h.repo.sourceSnapshots[1].FilePath)
			assert.Equal(t, h.original.FileHash, h.repo.sourceSnapshots[1].FileHash)
			assert.Equal(t, oldSHA, h.repo.sourceSnapshots[1].FileSHA256)
			assert.Equal(t, oldSHA, h.repo.row.FileSHA256)
			assert.Equal(t, []string{"new/file.md"}, h.store.deleted)
			assert.NotContains(t, h.store.files, "new/file.md")
		})
	}
}
