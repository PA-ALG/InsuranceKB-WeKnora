package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// The upstream replace fixture (knowledge_replace_test.go) stays byte-identical to
// v0.9.0. Reparse in this fork opens a parse revision through AllocateParseAttempt
// (and type-asserts the revision commit methods), and binds the source SHA-256, reading
// the file back when the row has none. The upstream fixture's apply does not know the
// file_sha256 column, so the shared fixture needs these methods; they keep only the
// state the upstream fixture already has. Tests that assert the revision binding use
// revisionReplaceHarness below.

func (r *replaceFileRepo) AllocateParseAttempt(
	_ context.Context, knowledgeID, modelID, fileSHA256 string,
) (int64, error) {
	if knowledgeID != r.row.ID {
		return 0, errors.New("unexpected knowledge allocation")
	}
	r.row.CurrentParseAttempt++
	r.row.EmbeddingModelID = modelID
	r.row.FileSHA256 = fileSHA256
	r.row.ErrorMessage = ""
	return r.row.CurrentParseAttempt, nil
}

func (*replaceFileRepo) CommitDirectRevision(
	context.Context, string, types.RevisionCommitBinding,
) (*types.KnowledgeRevision, error) {
	return nil, errors.New("unexpected direct revision commit during enqueue")
}

func (*replaceFileRepo) FinalizeSubtaskRevision(
	context.Context, string, types.RevisionCommitBinding,
) (int, bool, error) {
	return 0, false, errors.New("unexpected revision finalization during enqueue")
}

// GetFile serves the fixture's two paths: the original source and the replacement it
// saved. The upstream store keeps no bytes for the replacement, so that reads back empty;
// upstream replace tests never assert the SHA-256 reparse derives from it.
func (f *replaceFileStore) GetFile(_ context.Context, filePath string) (io.ReadCloser, error) {
	for _, deleted := range f.deleted {
		if deleted == filePath {
			return nil, fmt.Errorf("file deleted: %s", filePath)
		}
	}
	switch {
	case filePath == "old/file.md":
		return io.NopCloser(strings.NewReader(replaceFileOldContent)), nil
	case filePath == "new/file.md" && f.saved > 0:
		return io.NopCloser(strings.NewReader("")), nil
	}
	return nil, fmt.Errorf("file not found: %s", filePath)
}

// revisionReplaceRepo records the revision a replace allocates and every committed
// source update. No method of the embedded fixture calls AllocateParseAttempt or
// UpdateKnowledgeColumns, so both overrides see every call.
type revisionReplaceRepo struct {
	*replaceFileRepo
	allocatedKnowledgeID string
	allocatedModelID     string
	allocatedFileSHA256  string
	sourceSnapshots      []types.Knowledge
}

func (r *revisionReplaceRepo) AllocateParseAttempt(
	ctx context.Context, knowledgeID, modelID, fileSHA256 string,
) (int64, error) {
	r.allocatedKnowledgeID, r.allocatedModelID, r.allocatedFileSHA256 = knowledgeID, modelID, fileSHA256
	return r.replaceFileRepo.AllocateParseAttempt(ctx, knowledgeID, modelID, fileSHA256)
}

// UpdateKnowledgeColumns keeps the fixture's chosen-call failure; a write that applied
// (succeeded, or committed then reported an error) also sets file_sha256 and is recorded.
func (r *revisionReplaceRepo) UpdateKnowledgeColumns(
	ctx context.Context, id string, values map[string]interface{},
) error {
	err := r.replaceFileRepo.UpdateKnowledgeColumns(ctx, id, values)
	if err != nil && !r.commitThenFail {
		return err
	}
	if sha, ok := values["file_sha256"]; ok {
		r.row.FileSHA256 = sha.(string)
	}
	r.sourceSnapshots = append(r.sourceSnapshots, r.row)
	return err
}

// byteKeepingReplaceStore keeps the bytes of every stored file, so a test can check what
// the replacement saved and what a compensation deleted. No method of the embedded
// fixture calls SaveFile, GetFile or DeleteFile.
type byteKeepingReplaceStore struct {
	*replaceFileStore
	files map[string][]byte
}

func (f *byteKeepingReplaceStore) SaveFile(
	ctx context.Context, file *multipart.FileHeader, tenantID uint64, knowledgeID string,
) (string, error) {
	if f.saveErr != nil {
		return f.replaceFileStore.SaveFile(ctx, file, tenantID, knowledgeID)
	}
	reader, err := file.Open()
	if err != nil {
		return "", err
	}
	content, readErr := io.ReadAll(reader)
	closeErr := reader.Close()
	if err := errors.Join(readErr, closeErr); err != nil {
		return "", err
	}
	path, err := f.replaceFileStore.SaveFile(ctx, file, tenantID, knowledgeID)
	if err != nil {
		return "", err
	}
	f.files[path] = content
	return path, nil
}

func (f *byteKeepingReplaceStore) GetFile(_ context.Context, filePath string) (io.ReadCloser, error) {
	content, ok := f.files[filePath]
	if !ok {
		return nil, fmt.Errorf("file not found: %s", filePath)
	}
	return io.NopCloser(bytes.NewReader(content)), nil
}

func (f *byteKeepingReplaceStore) DeleteFile(ctx context.Context, filePath string) error {
	delete(f.files, filePath)
	return f.replaceFileStore.DeleteFile(ctx, filePath)
}

// revisionReplaceHarness is the upstream replace harness with the recording repository
// and the byte-keeping store wired into the service.
type revisionReplaceHarness struct {
	*replaceFileHarness
	repo  *revisionReplaceRepo
	store *byteKeepingReplaceStore
}

func newRevisionReplaceHarness(t *testing.T) *revisionReplaceHarness {
	t.Helper()
	h := newReplaceFileHarness(t)
	rh := &revisionReplaceHarness{
		replaceFileHarness: h,
		repo:               &revisionReplaceRepo{replaceFileRepo: h.repo},
		store: &byteKeepingReplaceStore{
			replaceFileStore: h.store,
			files:            map[string][]byte{h.original.FilePath: []byte(replaceFileOldContent)},
		},
	}
	h.svc.repo = rh.repo
	h.svc.fileSvc = rh.store
	return rh
}

func TestReplaceKnowledgeFileBindsNewBytesWhenPreviousSHAIsNonempty(t *testing.T) {
	h := newRevisionReplaceHarness(t)
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
			h := newRevisionReplaceHarness(t)
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
