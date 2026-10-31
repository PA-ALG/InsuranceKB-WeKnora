// S11f acceptance (protected, written by Claude): a revision that was not captured says why.
// Spec docs/design/slices/S11f-未采集材料带类型原因.md §2.1, §3.1. RED until S11f: Store has no
// SaveNote and ReadSourceArtifact returns the bare ErrNotCaptured.
package capture_test

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise/capture"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
)

const noteSHA = "ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12"

type noteRepo struct {
	knowledge types.Knowledge
	attempts  map[int64]bool
}

func (r noteRepo) GetKnowledgeByID(_ context.Context, _ uint64, id string) (*types.Knowledge, error) {
	if r.knowledge.ID != id {
		return nil, repository.ErrKnowledgeNotFound
	}
	k := r.knowledge
	return &k, nil
}

func (r noteRepo) GetRevision(_ context.Context, id string, attempt int64) (*types.KnowledgeRevision, error) {
	if r.knowledge.ID != id || !r.attempts[attempt] {
		return nil, repository.ErrKnowledgeNotFound
	}
	return &types.KnowledgeRevision{KnowledgeID: id, ParseAttempt: attempt, FileSHA256: noteSHA}, nil
}

type noteCase struct {
	root  string
	store *capture.Store
	repo  noteRepo
	scope types.WikiReleaseScope
	id    capture.Identity
}

func newNoteCase(t *testing.T, fileType string) noteCase {
	t.Helper()
	root := filepath.Join(t.TempDir(), "captures")
	id := capture.Identity{TenantID: 7, RawKBID: "raw-1", KnowledgeID: "k-1", ParseAttempt: 3, SourceSHA256: noteSHA}
	return noteCase{
		root:  root,
		store: capture.NewStore(root, testKeys()),
		repo: noteRepo{
			knowledge: types.Knowledge{
				ID: "k-1", TenantID: 7, KnowledgeBaseID: "raw-1", FileName: "material." + fileType, FileType: fileType,
			},
			attempts: map[int64]bool{3: true, 4: true},
		},
		scope: types.WikiReleaseScope{TenantID: 7, SpaceID: "space-1", RawKBID: "raw-1", WikiKBID: "wiki-1"},
		id:    id,
	}
}

func (c noteCase) read(t *testing.T, attempt int64) error {
	t.Helper()
	artifact, err := capture.ReadSourceArtifact(context.Background(), c.store, c.repo, c.scope, "k-1", attempt)
	require.Nil(t, artifact)
	return err
}

func notCaptured(t *testing.T, err error) *source.NotCaptured {
	t.Helper()
	require.ErrorIs(t, err, source.ErrNotCaptured, "every reason is still PARSE_ARTIFACT_NOT_CAPTURED")
	var reason *source.NotCaptured
	require.True(t, errors.As(err, &reason), "%v", err)
	return reason
}

func TestAScannedNoteNamesTheFirstScannedPage(t *testing.T) {
	c := newNoteCase(t, "pdf")
	require.NoError(t, c.store.SaveNote(c.id, source.NotCapturedScannedPage, 3))
	got := notCaptured(t, c.read(t, 3))
	require.Equal(t, source.NotCapturedScannedPage, got.Reason)
	require.Equal(t, 3, got.Page)

	entries, err := os.ReadDir(c.root)
	require.True(t, err != nil && errors.Is(err, os.ErrNotExist) || len(entries) == 0,
		"the capture directory itself holds no note: no first-parse record is written for a scanned PDF")
	notes, err := os.ReadDir(c.root + "-notes")
	require.NoError(t, err)
	require.Len(t, notes, 1)
	require.True(t, strings.HasPrefix(notes[0].Name(), "note-"), notes[0].Name())
}

func TestAnOfficeNoteHasNoPage(t *testing.T) {
	c := newNoteCase(t, "pptx")
	require.NoError(t, c.store.SaveNote(c.id, source.NotCapturedOfficeUnreadable, 0))
	got := notCaptured(t, c.read(t, 3))
	require.Equal(t, source.NotCapturedOfficeUnreadable, got.Reason)
	require.Zero(t, got.Page)
}

func TestWithoutANoteTheFileTypeDecides(t *testing.T) {
	for fileType, want := range map[string]string{
		"pdf": source.NotCapturedNotRecorded, "PDF": source.NotCapturedNotRecorded,
		"docx": source.NotCapturedNotRecorded, "xlsx": source.NotCapturedNotRecorded,
		"txt": source.NotCapturedUnsupportedFormat, "png": source.NotCapturedUnsupportedFormat,
		"": source.NotCapturedUnsupportedFormat,
	} {
		t.Run(fileType, func(t *testing.T) {
			c := newNoteCase(t, fileType)
			got := notCaptured(t, c.read(t, 3))
			require.Equal(t, want, got.Reason)
			require.Zero(t, got.Page)
		})
	}
}

func TestANoteOnlyAppliesToItsOwnAttemptAndNeverHidesACapture(t *testing.T) {
	c := newNoteCase(t, "pdf")
	require.NoError(t, c.store.SaveNote(c.id, source.NotCapturedScannedPage, 2))
	require.Equal(t, source.NotCapturedNotRecorded, notCaptured(t, c.read(t, 4)).Reason)

	in, sealed := load(t)
	captured := capture.NewStore(seeded(t, in, sealed), testKeys())
	require.NoError(t, captured.SaveNote(in.Identity, source.NotCapturedScannedPage, 1))
	repo := noteRepo{
		knowledge: types.Knowledge{
			ID: in.Identity.KnowledgeID, TenantID: in.Identity.TenantID,
			KnowledgeBaseID: in.Identity.RawKBID, FileName: "条款.pdf", FileType: "pdf",
		},
		attempts: map[int64]bool{in.Identity.ParseAttempt: true},
	}
	scope := types.WikiReleaseScope{
		TenantID: in.Identity.TenantID, SpaceID: "s", RawKBID: in.Identity.RawKBID, WikiKBID: "w",
	}
	reader := revisionOf{noteRepo: repo, sha: in.Identity.SourceSHA256}
	artifact, err := capture.ReadSourceArtifact(context.Background(), captured, reader, scope,
		in.Identity.KnowledgeID, in.Identity.ParseAttempt)
	require.NoError(t, err, "an existing capture is read as before; a note never replaces it")
	require.Equal(t, in.Markdown, artifact.Markdown)
}

// revisionOf answers the revision with the given file digest.
type revisionOf struct {
	noteRepo
	sha string
}

func (r revisionOf) GetRevision(_ context.Context, id string, attempt int64) (*types.KnowledgeRevision, error) {
	if r.knowledge.ID != id || !r.attempts[attempt] {
		return nil, repository.ErrKnowledgeNotFound
	}
	return &types.KnowledgeRevision{KnowledgeID: id, ParseAttempt: attempt, FileSHA256: r.sha}, nil
}

func TestAnInvalidNoteIsRefusedWhenWrittenAndWhenRead(t *testing.T) {
	c := newNoteCase(t, "pdf")
	for _, bad := range []struct {
		reason string
		page   int
	}{
		{source.NotCapturedScannedPage, 0},
		{source.NotCapturedScannedPage, -1},
		{source.NotCapturedOfficeUnreadable, 2},
		{source.NotCapturedNotRecorded, 0},
		{source.NotCapturedUnsupportedFormat, 0},
		{"SOMETHING_ELSE", 0},
		{"", 0},
	} {
		require.ErrorIs(t, c.store.SaveNote(c.id, bad.reason, bad.page), capture.ErrUnavailable, "%+v", bad)
	}
	_, err := os.ReadDir(c.root + "-notes")
	require.True(t, errors.Is(err, os.ErrNotExist), "a refused note leaves nothing behind")

	require.NoError(t, c.store.SaveNote(c.id, source.NotCapturedScannedPage, 5))
	require.NoError(t, c.store.SaveNote(c.id, source.NotCapturedScannedPage, 5), "the same note again is accepted")
	require.ErrorIs(t, c.store.SaveNote(c.id, source.NotCapturedScannedPage, 6), capture.ErrUnavailable,
		"a note is written once")

	other := c.id
	other.ParseAttempt = 4
	require.NoError(t, c.store.SaveNote(other, source.NotCapturedOfficeUnreadable, 0))
	notes, err := os.ReadDir(c.root + "-notes")
	require.NoError(t, err)
	require.Len(t, notes, 2)
	paths := map[int64]string{}
	for _, attempt := range []int64{3, 4} {
		id := c.id
		id.ParseAttempt = attempt
		for _, entry := range notes {
			data, readErr := os.ReadFile(filepath.Join(c.root+"-notes", entry.Name()))
			require.NoError(t, readErr)
			if strings.Contains(string(data), `"parse_attempt":`+map[int64]string{3: "3", 4: "4"}[attempt]) {
				paths[attempt] = filepath.Join(c.root+"-notes", entry.Name())
			}
		}
	}
	require.Len(t, paths, 2)
	swapped, err := os.ReadFile(paths[4])
	require.NoError(t, err)
	require.NoError(t, os.WriteFile(paths[3], swapped, 0o600), "attempt 4's note under attempt 3's key")
	var failure *source.Error
	err = c.read(t, 3)
	require.True(t, errors.As(err, &failure), "%v", err)
	require.Equal(t, source.ErrorIntegrity, failure.Code, "a note under another key fails closed")

	require.NoError(t, os.WriteFile(paths[3], []byte(`{"not":"sealed"}`), 0o600))
	err = c.read(t, 3)
	require.True(t, errors.As(err, &failure), "%v", err)
	require.Equal(t, source.ErrorIntegrity, failure.Code, "an unsealed note fails closed")
}
