package repository

// S4c-2b-1 acceptance (protected): a committed parse attempt only records its source
// revision; it is pinned while a published release cites it and released afterwards.
// Sealed (G3) rows stay pinned. Spec: docs/design/slices/S4c-2b-1-发布固定来源.md §3.1, §3.4.

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

func committedPDF(t *testing.T, db *gorm.DB, repo *knowledgeRepository) string {
	t.Helper()
	id := seedRevisionKnowledge(t, db, types.ParseStatusProcessing, 1, 0)
	seedRevisionChunk(t, db, id, 1, 0, "first")
	_, err := repo.CommitDirectRevision(context.Background(), id, testRevisionBinding(1))
	require.NoError(t, err)
	return id
}

func sourceRow(t *testing.T, db *gorm.DB, id string, attempt int64) types.KnowledgeRevisionSource {
	t.Helper()
	var row types.KnowledgeRevisionSource
	require.NoError(t, db.Where("knowledge_id = ? AND parse_attempt = ?", id, attempt).First(&row).Error)
	return row
}

func pinSources(db *gorm.DB, tenantID uint64, refs ...RevisionRef) error {
	return db.Transaction(func(tx *gorm.DB) error { return PinRevisionSources(tx, tenantID, refs) })
}

func releaseSources(db *gorm.DB, tenantID uint64, refs ...RevisionRef) error {
	return db.Transaction(func(tx *gorm.DB) error { return ReleaseRevisionSources(tx, tenantID, refs) })
}

func TestCommitRecordsTheSourceRevisionWithoutPinningIt(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := committedPDF(t, db, repo)

	row := sourceRow(t, db, id, 1)
	require.Equal(t, types.KnowledgeRevisionSourceReleased, row.RetentionState)
	require.NotNil(t, row.ReleasedAt)
	require.Empty(t, row.BindingDigest)

	pinned, err := repo.HasPinnedRevisionSource(context.Background(), 1, id)
	require.NoError(t, err)
	require.False(t, pinned)
}

func TestAnUncitedCommittedPDFCanBeReparsedAndDeleted(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := committedPDF(t, db, repo)

	attempt, err := repo.AllocateParseAttempt(context.Background(), id, "embed-1", "")
	require.NoError(t, err)
	require.Equal(t, int64(2), attempt)
	require.Equal(t, types.KnowledgeRevisionSourceReleased, sourceRow(t, db, id, 1).RetentionState)

	require.NoError(t, repo.DeleteKnowledge(context.Background(), 1, id))
	var after types.Knowledge
	require.NoError(t, db.Unscoped().Where("id = ?", id).First(&after).Error)
	require.True(t, after.DeletedAt.Valid)
}

func TestCommitsWithoutARegisteredPDFResourceSucceedWithoutASourceRow(t *testing.T) {
	for name, mutate := range map[string]func(*testing.T, *gorm.DB, string){
		"markdown resource": func(t *testing.T, db *gorm.DB, id string) {
			require.NoError(t, db.Model(&types.StoredResource{}).
				Where("id IN (SELECT resource_id FROM resource_bindings WHERE owner_id = ?)", id).
				Update("mime_type", "text/markdown").Error)
		},
		"not a registered resource": func(t *testing.T, db *gorm.DB, id string) {
			require.NoError(t, db.Exec(`UPDATE knowledges SET file_path = 'legacy/input.pdf' WHERE id = ?`, id).Error)
		},
	} {
		t.Run(name, func(t *testing.T) {
			db := setupRevisionTestDB(t)
			repo := NewKnowledgeRepository(db).(*knowledgeRepository)
			id := seedRevisionKnowledge(t, db, types.ParseStatusProcessing, 1, 0)
			seedRevisionChunk(t, db, id, 1, 0, "first")
			mutate(t, db, id)

			revision, err := repo.CommitDirectRevision(context.Background(), id, testRevisionBinding(1))
			require.NoError(t, err)
			require.Equal(t, 1, revision.ChunkCount)
			var status string
			require.NoError(t, db.Raw(`SELECT parse_status FROM knowledges WHERE id = ?`, id).Row().Scan(&status))
			require.Equal(t, types.ParseStatusCompleted, status)
			var sources int64
			require.NoError(t, db.Table("knowledge_revision_sources").Count(&sources).Error)
			require.Zero(t, sources)
		})
	}
}

func TestPinnedSourcesBlockDeleteAndReparseUntilReleased(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := committedPDF(t, db, repo)
	ref := RevisionRef{KnowledgeID: id, ParseAttempt: 1}

	require.NoError(t, pinSources(db, 1, ref))
	row := sourceRow(t, db, id, 1)
	require.Equal(t, types.KnowledgeRevisionSourcePinned, row.RetentionState)
	require.Nil(t, row.ReleasedAt)
	require.NoError(t, pinSources(db, 1, ref), "pinning an already pinned source is a no-op")

	require.ErrorIs(t, repo.DeleteKnowledge(context.Background(), 1, id), ErrResourcePinned)
	require.ErrorIs(t, repo.DeleteKnowledgeList(context.Background(), 1, []string{id}), ErrResourcePinned)
	_, err := repo.AllocateParseAttempt(context.Background(), id, "embed-1", "")
	require.ErrorIs(t, err, ErrResourcePinned)

	require.NoError(t, releaseSources(db, 1, ref))
	row = sourceRow(t, db, id, 1)
	require.Equal(t, types.KnowledgeRevisionSourceReleased, row.RetentionState)
	require.NotNil(t, row.ReleasedAt)
	require.NoError(t, repo.DeleteKnowledge(context.Background(), 1, id))
}

func TestPinningIsAllOrNothingAndRefusesUnavailableSources(t *testing.T) {
	cases := map[string]func(*testing.T, *gorm.DB, string) (uint64, RevisionRef){
		"knowledge deleting": func(t *testing.T, db *gorm.DB, id string) (uint64, RevisionRef) {
			require.NoError(t, db.Exec(`UPDATE knowledges SET parse_status = ? WHERE id = ?`,
				types.ParseStatusDeleting, id).Error)
			return 1, RevisionRef{KnowledgeID: id, ParseAttempt: 1}
		},
		"knowledge soft-deleted": func(t *testing.T, db *gorm.DB, id string) (uint64, RevisionRef) {
			require.NoError(t, db.Exec(`UPDATE knowledges SET deleted_at = ? WHERE id = ?`, time.Now().UTC(), id).Error)
			return 1, RevisionRef{KnowledgeID: id, ParseAttempt: 1}
		},
		"other tenant": func(_ *testing.T, _ *gorm.DB, id string) (uint64, RevisionRef) {
			return 2, RevisionRef{KnowledgeID: id, ParseAttempt: 1}
		},
		"attempt without a source row": func(_ *testing.T, _ *gorm.DB, id string) (uint64, RevisionRef) {
			return 1, RevisionRef{KnowledgeID: id, ParseAttempt: 2}
		},
		"unknown knowledge": func(_ *testing.T, _ *gorm.DB, _ string) (uint64, RevisionRef) {
			return 1, RevisionRef{KnowledgeID: strings.Repeat("0", 36), ParseAttempt: 1}
		},
	}
	for name, broken := range cases {
		t.Run(name, func(t *testing.T) {
			db := setupRevisionTestDB(t)
			repo := NewKnowledgeRepository(db).(*knowledgeRepository)
			good := committedPDF(t, db, repo)
			other := committedPDF(t, db, repo)
			tenantID, ref := broken(t, db, other)

			refs := []RevisionRef{{KnowledgeID: good, ParseAttempt: 1}, ref}
			err := db.Transaction(func(tx *gorm.DB) error { return PinRevisionSources(tx, tenantID, refs) })
			require.ErrorIs(t, err, ErrRevisionSourceUnavailable)
			require.Equal(t, types.KnowledgeRevisionSourceReleased, sourceRow(t, db, good, 1).RetentionState)
			require.Equal(t, types.KnowledgeRevisionSourceReleased, sourceRow(t, db, other, 1).RetentionState)
		})
	}
}

func TestReleasingLeavesSealedAndForeignRowsPinned(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	sealed := committedPDF(t, db, repo)
	plain := committedPDF(t, db, repo)

	source := sourceRow(t, db, sealed, 1)
	_, err := repo.SealRevisionSourcePageCount(context.Background(), 1, sealed, 1, source.RevisionSourceID, 2)
	require.NoError(t, err)
	require.Equal(t, types.KnowledgeRevisionSourcePinned, sourceRow(t, db, sealed, 1).RetentionState,
		"sealing pins the row")
	require.NoError(t, pinSources(db, 1, RevisionRef{KnowledgeID: plain, ParseAttempt: 1}))

	refs := []RevisionRef{{KnowledgeID: sealed, ParseAttempt: 1}, {KnowledgeID: plain, ParseAttempt: 1}}
	require.NoError(t, releaseSources(db, 2, refs...), "another tenant releases nothing")
	require.Equal(t, types.KnowledgeRevisionSourcePinned, sourceRow(t, db, plain, 1).RetentionState)

	require.NoError(t, releaseSources(db, 1, refs...))
	require.Equal(t, types.KnowledgeRevisionSourcePinned, sourceRow(t, db, sealed, 1).RetentionState)
	require.Equal(t, types.KnowledgeRevisionSourceReleased, sourceRow(t, db, plain, 1).RetentionState)
	missing := RevisionRef{KnowledgeID: plain, ParseAttempt: 9}
	require.NoError(t, releaseSources(db, 1, missing), "missing rows are ignored")
}

func TestKnowledgeBaseReportsWhetherAnyOfItsSourcesIsPinned(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := committedPDF(t, db, repo)
	ctx := context.Background()

	pinned, err := repo.HasPinnedRevisionSourceInKnowledgeBase(ctx, 1, "kb-1")
	require.NoError(t, err)
	require.False(t, pinned)

	require.NoError(t, pinSources(db, 1, RevisionRef{KnowledgeID: id, ParseAttempt: 1}))
	for _, scope := range []struct {
		tenantID uint64
		kbID     string
		want     bool
	}{{1, "kb-1", true}, {1, "kb-2", false}, {2, "kb-1", false}} {
		pinned, err = repo.HasPinnedRevisionSourceInKnowledgeBase(ctx, scope.tenantID, scope.kbID)
		require.NoError(t, err)
		require.Equal(t, scope.want, pinned, "tenant %d kb %s", scope.tenantID, scope.kbID)
	}
}
