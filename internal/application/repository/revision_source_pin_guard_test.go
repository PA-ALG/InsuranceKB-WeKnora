package repository

// U-2a acceptance (protected, written by Claude): the read-only "is anything pinned?" checks follow
// the rule resourceRepository.MarkDeleted already applies. On SQLite a catalog-confirmed missing
// knowledge_revision_sources table means nothing is pinned; every other failure, including a failed
// catalog read and any PostgreSQL error, is returned (Spec docs/design/slices/U-2a-修订来源只读守卫与上游测试还原.md §2–§3).

import (
	"context"
	"errors"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/postgres"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func pinGuardSQLite(t *testing.T, withSources bool) (*gorm.DB, *knowledgeRepository) {
	t.Helper()
	db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(&types.Knowledge{}))
	if withSources {
		require.NoError(t, db.AutoMigrate(&types.KnowledgeRevisionSource{}))
	}
	repo, ok := NewKnowledgeRepository(db).(*knowledgeRepository)
	require.True(t, ok)
	return db, repo
}

func TestPinChecksTreatAConfirmedMissingTableAsNothingPinnedOnSQLite(t *testing.T) {
	ctx := context.Background()
	db, repo := pinGuardSQLite(t, false)

	pinned, err := repo.HasPinnedRevisionSource(ctx, 7, "k-1")
	require.NoError(t, err)
	require.False(t, pinned)

	pinned, err = repo.HasPinnedRevisionSourceInKnowledgeBase(ctx, 7, "kb-1")
	require.NoError(t, err)
	require.False(t, pinned)

	require.NoError(t, rejectPinnedRevisionSourceLocked(db, 7, "k-1"))
}

func TestPinChecksStillSeeAPinnedSource(t *testing.T) {
	ctx := context.Background()
	db, repo := pinGuardSQLite(t, true)
	require.NoError(t, db.Create(&types.KnowledgeRevisionSource{
		TenantID:       7,
		KnowledgeID:    "k-1",
		ParseAttempt:   1,
		RetentionState: types.KnowledgeRevisionSourcePinned,
	}).Error)

	pinned, err := repo.HasPinnedRevisionSource(ctx, 7, "k-1")
	require.NoError(t, err)
	require.True(t, pinned)
	require.ErrorIs(t, rejectPinnedRevisionSourceLocked(db, 7, "k-1"), ErrResourcePinned)
}

func TestPinChecksFailClosedWhenTheStoreCannotBeRead(t *testing.T) {
	for _, withSources := range []bool{false, true} {
		db, repo := pinGuardSQLite(t, withSources)
		sqlDB, err := db.DB()
		require.NoError(t, err)
		require.NoError(t, sqlDB.Close())

		pinned, err := repo.HasPinnedRevisionSource(context.Background(), 7, "k-1")
		require.Error(t, err, "a failed read must not look like an unpinned source (table=%v)", withSources)
		require.False(t, pinned)
		require.Error(t, rejectPinnedRevisionSourceLocked(db, 7, "k-1"))
	}
}

func TestPinChecksOnPostgresReturnTheErrorWithoutConsultingTheCatalog(t *testing.T) {
	sqlDB, mock, err := sqlmock.New()
	require.NoError(t, err)
	t.Cleanup(func() { _ = sqlDB.Close() })
	db, err := gorm.Open(postgres.New(postgres.Config{Conn: sqlDB}), &gorm.Config{})
	require.NoError(t, err)
	repo, ok := NewKnowledgeRepository(db).(*knowledgeRepository)
	require.True(t, ok)

	missing := errors.New(`pq: relation "knowledge_revision_sources" does not exist`)
	mock.ExpectQuery(`SELECT count\(\*\) FROM "knowledge_revision_sources"`).WillReturnError(missing)

	pinned, err := repo.HasPinnedRevisionSource(context.Background(), 7, "k-1")
	require.ErrorIs(t, err, missing)
	require.False(t, pinned)
	require.NoError(t, mock.ExpectationsWereMet(), "PostgreSQL must not fall back to a catalog probe")
}
