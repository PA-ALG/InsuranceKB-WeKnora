package repository

import (
	"context"
	"database/sql"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
)

func TestSealRevisionSourcePageCountIsExactIdempotentWriteOnce(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := seedRevisionKnowledge(t, db, types.ParseStatusProcessing, 1, 0)
	seedRevisionChunk(t, db, id, 1, 0, "first")
	_, err := repo.CommitDirectRevision(context.Background(), id, testRevisionBinding(1))
	require.NoError(t, err)
	var source types.KnowledgeRevisionSource
	require.NoError(t, db.Where(
		"knowledge_id = ? AND parse_attempt = 1", id,
	).First(&source).Error)
	require.Nil(t, source.PageCount)

	sealed, err := repo.SealRevisionSourcePageCount(
		context.Background(), 1, id, 1, source.RevisionSourceID, 39,
	)
	require.NoError(t, err)
	require.NotNil(t, sealed.PageCount)
	require.Equal(t, 39, *sealed.PageCount)
	require.NoError(t, types.ValidateKnowledgeRevisionSourceBinding(*sealed))

	again, err := repo.SealRevisionSourcePageCount(
		context.Background(), 1, id, 1, source.RevisionSourceID, 39,
	)
	require.NoError(t, err)
	require.Equal(t, 39, *again.PageCount)

	_, err = repo.SealRevisionSourcePageCount(
		context.Background(), 1, id, 1, source.RevisionSourceID, 40,
	)
	require.ErrorIs(t, err, ErrRevisionCommitFailed)
	_, err = repo.SealRevisionSourcePageCount(
		context.Background(), 1, id, 1, strings.Repeat("f", 64), 39,
	)
	require.ErrorIs(t, err, ErrRevisionCommitFailed)

	var persisted types.KnowledgeRevisionSource
	require.NoError(t, db.Where(
		"knowledge_id = ? AND parse_attempt = 1", id,
	).First(&persisted).Error)
	require.Equal(t, 39, *persisted.PageCount)
}

func TestSealRevisionSourceBindingReplaysExactSQLiteAuthoritiesAndIsWriteOnce(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := seedRevisionKnowledge(t, db, types.ParseStatusProcessing, 1, 0)
	seedRevisionChunk(t, db, id, 1, 0, "first")
	_, err := repo.CommitDirectRevision(context.Background(), id, testRevisionBinding(1))
	require.NoError(t, err)

	var candidate types.KnowledgeRevisionSource
	require.NoError(t, db.Where(
		"tenant_id = ? AND knowledge_id = ? AND parse_attempt = ?", 1, id, 1,
	).First(&candidate).Error)
	pageCount := 2
	candidate.PageCount = &pageCount
	// S4c-2b-1: the committed row is released; sealing pins it.
	candidate.RetentionState = types.KnowledgeRevisionSourcePinned
	candidate.ReleasedAt = nil
	candidate.BindingDigest, err = types.ComputeKnowledgeRevisionSourceBindingDigest(candidate)
	require.NoError(t, err)

	sealed, err := repo.SealRevisionSourceBinding(context.Background(), candidate)
	require.NoError(t, err)
	require.NoError(t, types.ValidateKnowledgeRevisionSourceBinding(*sealed))
	replayed, resource, err := repo.GetRevisionSource(context.Background(), 1, id, 1)
	require.NoError(t, err)
	require.Equal(t, candidate.BindingDigest, replayed.BindingDigest)
	require.Equal(t, candidate.ResourceID, resource.ID)

	drifted := candidate
	driftedPages := 3
	drifted.PageCount = &driftedPages
	drifted.BindingDigest, err = types.ComputeKnowledgeRevisionSourceBindingDigest(drifted)
	require.NoError(t, err)
	_, err = repo.SealRevisionSourceBinding(context.Background(), drifted)
	require.ErrorIs(t, err, ErrRevisionCommitFailed)

	var after types.KnowledgeRevisionSource
	require.NoError(t, db.Where(
		"tenant_id = ? AND knowledge_id = ? AND parse_attempt = ?", 1, id, 1,
	).First(&after).Error)
	require.Equal(t, candidate.BindingDigest, after.BindingDigest)
	require.Equal(t, pageCount, *after.PageCount)
}

func TestKnowledgeDeletePathsAtomicallyRejectPinnedRevisionSources(t *testing.T) {
	for name, deleteRows := range map[string]func(*knowledgeRepository, string) error{
		"single": func(repo *knowledgeRepository, id string) error {
			return repo.DeleteKnowledge(context.Background(), 1, id)
		},
		"batch": func(repo *knowledgeRepository, id string) error {
			return repo.DeleteKnowledgeList(context.Background(), 1, []string{id})
		},
	} {
		t.Run(name, func(t *testing.T) {
			db := setupRevisionTestDB(t)
			repo := NewKnowledgeRepository(db).(*knowledgeRepository)
			id := seedRevisionKnowledge(t, db, types.ParseStatusProcessing, 1, 0)
			seedRevisionChunk(t, db, id, 1, 0, "first")
			_, err := repo.CommitDirectRevision(context.Background(), id, testRevisionBinding(1))
			require.NoError(t, err)
			// S4c-2b-1: commits no longer pin; a published release does.
			require.NoError(t, pinSources(db, 1, RevisionRef{KnowledgeID: id, ParseAttempt: 1}))

			err = deleteRows(repo, id)
			require.ErrorIs(t, err, ErrResourcePinned)
			var after types.Knowledge
			require.NoError(t, db.Where("tenant_id = ? AND id = ?", 1, id).First(&after).Error)
			require.False(t, after.DeletedAt.Valid)
		})
	}
}

func TestExact3AuthorityReadsAllRowsInsideOneReadOnlySnapshot(t *testing.T) {
	txOptions := exact3ReadOnlyTxOptions()
	require.Equal(t, sql.LevelRepeatableRead, txOptions.Isolation)
	require.True(t, txOptions.ReadOnly)
	db := setupRevisionTestDB(t)
	knowledgeID := seedRevisionKnowledge(t, db, types.ParseStatusProcessing, 2, 0)
	seedRevisionChunk(t, db, knowledgeID, 2, 0, "exact3")
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	_, err := repo.CommitDirectRevision(context.Background(), knowledgeID, testRevisionBinding(2))
	require.NoError(t, err)
	var row *interfaces.KnowledgeRevisionSourceExact3Authority
	err = repo.WithExact3ReadSnapshot(
		context.Background(),
		func(reader interfaces.KnowledgeRevisionSourceExact3SnapshotReader) error {
			var readErr error
			row, readErr = reader.GetExact3RevisionSourceAuthority(
				context.Background(), 1, "kb-1", knowledgeID, 2,
			)
			return readErr
		},
	)
	require.NoError(t, err)
	require.NotNil(t, row)
	require.Equal(t, knowledgeID, row.Knowledge.ID)
	require.Equal(t, int64(2), row.Current.ParseAttempt)
	require.Equal(t, int64(2), row.Last.ParseAttempt)
	require.Equal(t, int64(1), row.ResourceBindingCount)

	err = repo.WithExact3ReadSnapshot(context.Background(), nil)
	require.ErrorIs(t, err, ErrRevisionCommitFailed)
}
