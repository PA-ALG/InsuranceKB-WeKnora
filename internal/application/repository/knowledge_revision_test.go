package repository

import (
	"context"
	"errors"
	"sort"
	"strings"
	"sync"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

func TestAllocateParseAttemptCommitsPendingBeforeAnyChunkDestruction(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := seedRevisionKnowledge(t, db, types.ParseStatusCompleted, 3, 0)
	seedRevisionChunk(t, db, id, 3, 0, "old")

	attempt, err := repo.AllocateParseAttempt(context.Background(), id, "embed-2", "")
	require.NoError(t, err)
	require.Equal(t, int64(4), attempt)

	var status string
	var current int64
	var pending int
	require.NoError(t, db.Raw(`
SELECT parse_status, current_parse_attempt, pending_subtasks_count
FROM knowledges WHERE id = ?
`, id).Row().Scan(&status, &current, &pending))
	require.Equal(t, types.ParseStatusPending, status)
	require.Equal(t, int64(4), current)
	require.Zero(t, pending)

	var oldChunkCount int64
	require.NoError(t, db.Table("chunks").
		Where("knowledge_id = ? AND parse_attempt = ?", id, 3).
		Count(&oldChunkCount).Error)
	require.Equal(t, int64(1), oldChunkCount, "allocation must not destroy the prior attempt")
}

func TestAllocateParseAttemptSerializesConcurrentReparse(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := seedRevisionKnowledge(t, db, types.ParseStatusCompleted, 3, 0)

	var wg sync.WaitGroup
	attempts := make([]int64, 2)
	errs := make([]error, 2)
	for index := range attempts {
		wg.Add(1)
		go func() {
			defer wg.Done()
			attempts[index], errs[index] = repo.AllocateParseAttempt(
				context.Background(), id, "embed-1", "",
			)
		}()
	}
	wg.Wait()
	require.NoError(t, errs[0])
	require.NoError(t, errs[1])
	sort.Slice(attempts, func(i, j int) bool { return attempts[i] < attempts[j] })
	require.Equal(t, []int64{4, 5}, attempts)
}

func TestAllocateParseAttemptFailurePreservesCurrentRevisionAndChunks(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := seedRevisionKnowledge(t, db, types.ParseStatusCompleted, 3, 0)
	seedRevisionChunk(t, db, id, 3, 0, "still serviceable")
	require.NoError(t, db.Exec(`
CREATE TRIGGER reject_parse_attempt_update
BEFORE UPDATE OF current_parse_attempt ON knowledges
BEGIN SELECT RAISE(ABORT, 'allocation failed'); END;
`).Error)

	_, err := repo.AllocateParseAttempt(context.Background(), id, "embed-1", "")
	require.ErrorContains(t, err, "allocation failed")
	var status string
	var attempt int64
	require.NoError(t, db.Raw(
		"SELECT parse_status, current_parse_attempt FROM knowledges WHERE id = ?", id,
	).Row().Scan(&status, &attempt))
	require.Equal(t, types.ParseStatusCompleted, status)
	require.Equal(t, int64(3), attempt)
	var chunks int64
	require.NoError(t, db.Table("chunks").Where(
		"knowledge_id = ? AND parse_attempt = ?", id, 3,
	).Count(&chunks).Error)
	require.Equal(t, int64(1), chunks)
}

func TestCommitDirectRevisionIsAtomicAndFenced(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := seedRevisionKnowledge(t, db, types.ParseStatusProcessing, 1, 0)
	seedRevisionChunk(t, db, id, 1, 0, "first")
	seedRevisionChunk(t, db, id, 1, 2, "second")

	revision, err := repo.CommitDirectRevision(context.Background(), id, testRevisionBinding(1))
	require.NoError(t, err)
	require.Equal(t, 2, revision.ChunkCount)
	require.Len(t, revision.ManifestDigest, 64)

	var status string
	require.NoError(t, db.Raw(`SELECT parse_status FROM knowledges WHERE id = ?`, id).
		Row().Scan(&status))
	require.Equal(t, types.ParseStatusCompleted, status)

	var revisionCount int64
	require.NoError(t, db.Table("knowledge_revisions").
		Where("knowledge_id = ? AND parse_attempt = 1", id).
		Count(&revisionCount).Error)
	require.Equal(t, int64(1), revisionCount)

	var source types.KnowledgeRevisionSource
	require.NoError(t, db.Where(
		"knowledge_id = ? AND parse_attempt = ?", id, 1,
	).First(&source).Error)
	require.Equal(t, uint64(1), source.TenantID)
	require.Equal(t, revision.FileSHA256, source.FileSHA256)
	require.Equal(t, int64(1024), source.Size)
	require.Equal(t, "application/pdf", source.MimeType)
	require.Equal(t, revision.FileSHA256, source.ObjectSHA256)
	require.Equal(t, revision.ManifestDigest, source.ManifestDigest)
	require.Equal(t, revision.ChunkCount, source.ChunkCount)
	require.Empty(t, source.BindingDigest)
	// S4c-2b-1: a commit records the source revision; only published releases pin it.
	require.Equal(t, types.KnowledgeRevisionSourceReleased, source.RetentionState)
	var resource types.StoredResource
	require.NoError(t, db.Where("id = ?", source.ResourceID).First(&resource).Error)
	require.Equal(t, resource.Handle, source.ResourceHandle)
	require.Equal(t, revision.FileSHA256, resource.ContentHash)

	_, err = repo.CommitDirectRevision(context.Background(), id, testRevisionBinding(1))
	require.ErrorIs(t, err, ErrRevisionAlreadyCommitted)
}

func TestCommitDirectRevisionRejectsResourceDigestOrBindingDriftWithoutPartialWrite(t *testing.T) {
	tests := map[string]func(*testing.T, *gorm.DB, string){
		"foreign knowledge binding": func(t *testing.T, db *gorm.DB, id string) {
			require.NoError(t, db.Model(&types.ResourceBinding{}).
				Where("owner_id = ?", id).Update("owner_id", "foreign").Error)
		},
		"foreign tenant": func(t *testing.T, db *gorm.DB, id string) {
			require.NoError(t, db.Model(&types.StoredResource{}).
				Where("id IN (SELECT resource_id FROM resource_bindings WHERE owner_id = ?)", id).
				Update("tenant_id", 2).Error)
		},
		"existing content digest": func(t *testing.T, db *gorm.DB, id string) {
			require.NoError(t, db.Model(&types.StoredResource{}).
				Where("id IN (SELECT resource_id FROM resource_bindings WHERE owner_id = ?)", id).
				Update("content_hash", strings.Repeat("b", 64)).Error)
		},
		"zero size": func(t *testing.T, db *gorm.DB, id string) {
			require.NoError(t, db.Model(&types.StoredResource{}).
				Where("id IN (SELECT resource_id FROM resource_bindings WHERE owner_id = ?)", id).
				Update("size", 0).Error)
		},
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			db := setupRevisionTestDB(t)
			repo := NewKnowledgeRepository(db).(*knowledgeRepository)
			id := seedRevisionKnowledge(t, db, types.ParseStatusProcessing, 1, 0)
			seedRevisionChunk(t, db, id, 1, 0, "first")
			mutate(t, db, id)

			_, err := repo.CommitDirectRevision(context.Background(), id, testRevisionBinding(1))
			require.ErrorIs(t, err, ErrRevisionCommitFailed)
			var revisionCount int64
			require.NoError(t, db.Table("knowledge_revisions").Count(&revisionCount).Error)
			require.Zero(t, revisionCount)
			var sourceCount int64
			require.NoError(t, db.Table("knowledge_revision_sources").Count(&sourceCount).Error)
			require.Zero(t, sourceCount)
		})
	}
}

func TestCommitDirectRevisionRejectsStaleAttemptWithoutPartialWrite(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := seedRevisionKnowledge(t, db, types.ParseStatusProcessing, 2, 0)
	seedRevisionChunk(t, db, id, 1, 0, "stale")

	_, err := repo.CommitDirectRevision(context.Background(), id, testRevisionBinding(1))
	require.ErrorIs(t, err, ErrRevisionSuperseded)

	var status string
	require.NoError(t, db.Raw(`SELECT parse_status FROM knowledges WHERE id = ?`, id).
		Row().Scan(&status))
	require.Equal(t, types.ParseStatusProcessing, status)

	var revisionCount int64
	require.NoError(t, db.Table("knowledge_revisions").Count(&revisionCount).Error)
	require.Zero(t, revisionCount)
}

func TestFailedAndCancelledAttemptsNeverCommitRevision(t *testing.T) {
	for _, status := range []string{types.ParseStatusFailed, types.ParseStatusCancelled} {
		t.Run(status, func(t *testing.T) {
			db := setupRevisionTestDB(t)
			repo := NewKnowledgeRepository(db).(*knowledgeRepository)
			id := seedRevisionKnowledge(t, db, status, 2, 0)
			seedRevisionChunk(t, db, id, 2, 0, "not committed")
			_, err := repo.CommitDirectRevision(context.Background(), id, testRevisionBinding(2))
			require.ErrorIs(t, err, ErrRevisionCommitFailed)
			var count int64
			require.NoError(t, db.Table("knowledge_revisions").Count(&count).Error)
			require.Zero(t, count)
		})
	}
}

func TestFinalizeSubtaskRevisionCommitsOnLastSlotInSameTransaction(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := seedRevisionKnowledge(t, db, types.ParseStatusFinalizing, 5, 1)
	seedRevisionChunk(t, db, id, 5, 0, "ready")

	count, promoted, err := repo.FinalizeSubtaskRevision(
		context.Background(), id, testRevisionBinding(5),
	)
	require.NoError(t, err)
	require.Zero(t, count)
	require.True(t, promoted)

	var status string
	var revisionCount int64
	require.NoError(t, db.Raw(`SELECT parse_status FROM knowledges WHERE id = ?`, id).
		Row().Scan(&status))
	require.NoError(t, db.Table("knowledge_revisions").
		Where("knowledge_id = ? AND parse_attempt = 5", id).
		Count(&revisionCount).Error)
	require.Equal(t, types.ParseStatusCompleted, status)
	require.Equal(t, int64(1), revisionCount)
}

func TestFinalizeSubtaskRevisionRollsBackCounterWhenManifestInvalid(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := seedRevisionKnowledge(t, db, types.ParseStatusFinalizing, 6, 1)
	seedRevisionChunk(t, db, id, 6, 0, "first")
	seedRevisionChunk(t, db, id, 6, 0, "duplicate")

	_, _, err := repo.FinalizeSubtaskRevision(
		context.Background(), id, testRevisionBinding(6),
	)
	require.Error(t, err)
	require.True(t,
		errors.Is(err, types.ErrInvalidRevisionManifest) || errors.Is(err, ErrRevisionCommitFailed),
	)

	var status string
	var pending int
	require.NoError(t, db.Raw(`
SELECT parse_status, pending_subtasks_count FROM knowledges WHERE id = ?
`, id).Row().Scan(&status, &pending))
	require.Equal(t, types.ParseStatusFinalizing, status)
	require.Equal(t, 1, pending)
}

func TestGetRevisionStateAndChunksRemainAttemptBound(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := seedRevisionKnowledge(t, db, types.ParseStatusProcessing, 1, 0)
	seedRevisionChunk(t, db, id, 1, 0, "first")
	seedRevisionChunk(t, db, id, 1, 2, "third")
	_, err := repo.CommitDirectRevision(context.Background(), id, testRevisionBinding(1))
	require.NoError(t, err)

	knowledge, current, last, err := repo.GetRevisionState(context.Background(), id)
	require.NoError(t, err)
	require.Equal(t, int64(1), knowledge.CurrentParseAttempt)
	require.Equal(t, int64(1), current.ParseAttempt)
	require.Equal(t, current.ManifestDigest, last.ManifestDigest)

	page := &types.Pagination{Page: 1, PageSize: 1}
	chunks, total, err := repo.ListRevisionChunks(context.Background(), id, 1, page)
	require.NoError(t, err)
	require.Equal(t, int64(2), total)
	require.Len(t, chunks, 1)
	require.Equal(t, 0, chunks[0].ChunkIndex)

	require.NoError(t, db.Model(&types.Knowledge{}).Where("id = ?", id).
		Update("current_parse_attempt", 2).Error)
	_, current, last, err = repo.GetRevisionState(context.Background(), id)
	require.NoError(t, err)
	require.Nil(t, current)
	require.Equal(t, int64(1), last.ParseAttempt)
}

func TestGetRevisionStateReturnsSoftDeletedTombstone(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := seedRevisionKnowledge(t, db, types.ParseStatusCompleted, 1, 0)
	require.NoError(t, db.Model(&types.Knowledge{}).Where("id = ?", id).Delete(&types.Knowledge{}).Error)

	knowledge, current, last, err := repo.GetRevisionState(context.Background(), id)
	require.NoError(t, err)
	require.True(t, knowledge.DeletedAt.Valid)
	require.Nil(t, current)
	require.Nil(t, last)
}

func TestCommittedManifestRemainsImmutableWhenChunkContentDrifts(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := seedRevisionKnowledge(t, db, types.ParseStatusProcessing, 1, 0)
	seedRevisionChunk(t, db, id, 1, 0, "original")
	committed, err := repo.CommitDirectRevision(context.Background(), id, testRevisionBinding(1))
	require.NoError(t, err)
	require.NoError(t, db.Exec(
		"UPDATE chunks SET content = ? WHERE knowledge_id = ? AND parse_attempt = ?",
		"tampered", id, 1,
	).Error)

	chunks, total, err := repo.ListRevisionChunks(
		context.Background(), id, 1, &types.Pagination{Page: 1, PageSize: 10},
	)
	require.NoError(t, err)
	require.Equal(t, int64(1), total)
	recomputed, err := types.ComputeRevisionManifestDigest(id, 1, []types.RevisionManifestChunk{{
		ID: chunks[0].ID, Index: chunks[0].ChunkIndex, Content: chunks[0].Content,
	}})
	require.NoError(t, err)
	require.NotEqual(t, committed.ManifestDigest, recomputed)
	stored, err := repo.GetRevision(context.Background(), id, 1)
	require.NoError(t, err)
	require.Equal(t, committed.ManifestDigest, stored.ManifestDigest)
}
