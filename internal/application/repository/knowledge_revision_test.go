package repository

import (
	"context"
	"database/sql"
	"errors"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func setupRevisionTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	dsn := "file:" + uuid.NewString() + "?mode=memory&cache=shared&_busy_timeout=5000"
	db, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{})
	require.NoError(t, err)
	sqlDB, err := db.DB()
	require.NoError(t, err)
	sqlDB.SetMaxOpenConns(1)
	require.NoError(t, db.Exec(`
CREATE TABLE knowledges (
	id TEXT PRIMARY KEY,
	tenant_id INTEGER NOT NULL,
	knowledge_base_id TEXT NOT NULL,
	parse_status TEXT NOT NULL,
	enable_status TEXT NOT NULL,
	pending_subtasks_count INTEGER NOT NULL DEFAULT 0,
	current_parse_attempt INTEGER NOT NULL DEFAULT 0,
	file_path TEXT NOT NULL DEFAULT '',
	file_sha256 TEXT NOT NULL DEFAULT '',
	embedding_model_id TEXT NOT NULL DEFAULT '',
	description TEXT NOT NULL DEFAULT '',
	error_message TEXT NOT NULL DEFAULT '',
	processed_at DATETIME,
	updated_at DATETIME,
	deleted_at DATETIME
);
CREATE TABLE chunks (
	id TEXT PRIMARY KEY,
	tenant_id INTEGER NOT NULL,
	knowledge_id TEXT NOT NULL,
	knowledge_base_id TEXT NOT NULL,
	content TEXT NOT NULL,
	chunk_index INTEGER NOT NULL,
	chunk_type TEXT NOT NULL,
	parse_attempt INTEGER NOT NULL DEFAULT 0,
	deleted_at DATETIME
);
CREATE TABLE knowledge_revisions (
	knowledge_id TEXT NOT NULL,
	parse_attempt INTEGER NOT NULL,
	file_sha256 TEXT NOT NULL,
	parser_identity TEXT NOT NULL,
	manifest_algorithm TEXT NOT NULL,
	manifest_digest TEXT NOT NULL,
	chunk_count INTEGER NOT NULL,
	completed_at DATETIME NOT NULL,
	PRIMARY KEY (knowledge_id, parse_attempt)
);
CREATE TABLE resources (
	id TEXT PRIMARY KEY,
	handle TEXT NOT NULL UNIQUE,
	tenant_id INTEGER NOT NULL,
	provider TEXT NOT NULL,
	physical_path TEXT NOT NULL,
	location_hash TEXT NOT NULL,
	kind TEXT NOT NULL,
	mime_type TEXT NOT NULL,
	original_name TEXT NOT NULL,
	size INTEGER NOT NULL,
	content_hash TEXT NOT NULL DEFAULT '',
	lifecycle TEXT NOT NULL,
	state TEXT NOT NULL,
	created_at DATETIME,
	updated_at DATETIME,
	deleted_at DATETIME
);
CREATE TABLE resource_bindings (
	id TEXT PRIMARY KEY,
	resource_id TEXT NOT NULL,
	tenant_id INTEGER NOT NULL,
	owner_type TEXT NOT NULL,
	owner_id TEXT NOT NULL,
	relation TEXT NOT NULL,
	created_at DATETIME
);
CREATE TABLE knowledge_revision_sources (
	tenant_id INTEGER NOT NULL,
	knowledge_id TEXT NOT NULL,
	parse_attempt INTEGER NOT NULL,
	revision_source_id TEXT NOT NULL UNIQUE,
	resource_id TEXT NOT NULL,
	resource_handle TEXT NOT NULL DEFAULT '',
	file_sha256 TEXT NOT NULL,
	object_sha256 TEXT NOT NULL DEFAULT '',
	size INTEGER NOT NULL,
	mime_type TEXT NOT NULL,
	page_count INTEGER,
	manifest_algorithm TEXT NOT NULL DEFAULT '',
	manifest_digest TEXT NOT NULL DEFAULT '',
	chunk_count INTEGER NOT NULL DEFAULT 0,
	immutable_locator TEXT NOT NULL DEFAULT '',
	binding_digest TEXT NOT NULL DEFAULT '',
	retention_state TEXT NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	released_at DATETIME,
	PRIMARY KEY (knowledge_id, parse_attempt)
);
`).Error)
	t.Cleanup(func() { _ = sqlDB.Close() })
	return db
}

func seedRevisionKnowledge(t *testing.T, db *gorm.DB, status string, attempt int64, pending int) string {
	t.Helper()
	id := uuid.NewString()
	resourceID := uuid.NewString()
	handle := strings.ReplaceAll(uuid.NewString(), "-", "")[:types.ResourceHandleLength]
	fileSHA256 := "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	require.NoError(t, db.Exec(`
INSERT INTO resources (
	id, handle, tenant_id, provider, physical_path, location_hash, kind,
	mime_type, original_name, size, content_hash, lifecycle, state, created_at, updated_at
) VALUES (?, ?, 1, 'local', ?, ?, 'file', 'application/pdf', 'input.pdf', 1024, '', 'persistent', 'active', ?, ?)
`, resourceID, handle, "/files/"+id+".pdf", strings.Repeat("f", 64),
		time.Now().UTC(), time.Now().UTC()).Error)
	require.NoError(t, db.Exec(`
INSERT INTO resource_bindings (
	id, resource_id, tenant_id, owner_type, owner_id, relation, created_at
) VALUES (?, ?, 1, 'knowledge', ?, 'source_file', ?)
`, uuid.NewString(), resourceID, id, time.Now().UTC()).Error)
	require.NoError(t, db.Exec(`
INSERT INTO knowledges (
	id, tenant_id, knowledge_base_id, parse_status, enable_status,
	pending_subtasks_count, current_parse_attempt, file_path, file_sha256,
	embedding_model_id, updated_at
) VALUES (?, 1, 'kb-1', ?, 'disabled', ?, ?, ?, ?, 'embed-1', ?)
`, id, status, pending, attempt, types.BuildResourcePath(handle), fileSHA256,
		time.Now().UTC()).Error)
	return id
}

func seedRevisionChunk(t *testing.T, db *gorm.DB, knowledgeID string, attempt int64, index int, content string) {
	t.Helper()
	require.NoError(t, db.Exec(`
INSERT INTO chunks (
	id, tenant_id, knowledge_id, knowledge_base_id, content, chunk_index,
	chunk_type, parse_attempt
) VALUES (?, 1, ?, 'kb-1', ?, ?, 'text', ?)
`, uuid.NewString(), knowledgeID, content, index, attempt).Error)
}

func testRevisionBinding(attempt int64) types.RevisionCommitBinding {
	return types.RevisionCommitBinding{
		ParseAttempt: attempt,
		FileSHA256:   "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		ParserIdentity: types.RevisionParserIdentity{
			AppVersion:       "1.0.0",
			AppCommit:        "deadbeef",
			DocReader:        "docreader-v1",
			ParserEngine:     "builtin",
			ChunkSize:        512,
			ChunkOverlap:     64,
			EmbeddingModelID: "embed-1",
		},
	}
}

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
	require.Equal(t, types.KnowledgeRevisionSourcePinned, source.RetentionState)
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

			err = deleteRows(repo, id)
			require.ErrorIs(t, err, ErrResourcePinned)
			var after types.Knowledge
			require.NoError(t, db.Where("tenant_id = ? AND id = ?", 1, id).First(&after).Error)
			require.False(t, after.DeletedAt.Valid)
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
