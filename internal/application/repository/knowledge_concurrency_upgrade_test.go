package repository

import (
	"context"
	"fmt"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func setupAtomicPinTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	dsn := "file:" + uuid.NewString() + "?mode=memory&cache=shared&_busy_timeout=5000"
	db, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(
		&types.Knowledge{},
		&types.KnowledgeRevisionSource{},
		&types.Tenant{},
		&types.Chunk{},
	))
	sqlDB, err := db.DB()
	require.NoError(t, err)
	sqlDB.SetMaxOpenConns(1)
	t.Cleanup(func() { _ = sqlDB.Close() })
	return db
}

func injectPinnedSourceAfterKnowledgeLock(
	t *testing.T,
	db *gorm.DB,
	tenantID uint64,
	knowledgeID string,
) *atomic.Bool {
	t.Helper()
	var injected atomic.Bool
	callbackName := "test:pin-after-knowledge-lock:" + uuid.NewString()
	require.NoError(t, db.Callback().Query().After("gorm:query").Register(
		callbackName,
		func(tx *gorm.DB) {
			if tx.Statement == nil || tx.Statement.Table != "knowledges" ||
				!injected.CompareAndSwap(false, true) {
				return
			}
			now := time.Now().UTC()
			pin := &types.KnowledgeRevisionSource{
				TenantID: tenantID, KnowledgeID: knowledgeID, ParseAttempt: 1,
				RevisionSourceID: "injected-" + uuid.NewString(), ResourceID: uuid.NewString(),
				FileSHA256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
				Size:       1, MimeType: "application/pdf",
				RetentionState: types.KnowledgeRevisionSourcePinned,
				CreatedAt:      now, UpdatedAt: now,
			}
			if err := tx.Session(&gorm.Session{NewDB: true, SkipHooks: true}).Create(pin).Error; err != nil {
				_ = tx.AddError(err) // AddError stores the error on tx; its return repeats tx.Error.
			}
		},
	))
	t.Cleanup(func() {
		require.NoError(t, db.Callback().Query().Remove(callbackName))
	})
	return &injected
}

func TestAttemptAndTransferMutationsRejectPinInsertedAfterKnowledgeLock(t *testing.T) {
	t.Run("allocate parse attempt", func(t *testing.T) {
		db := setupAtomicPinTestDB(t)
		row := &types.Knowledge{
			ID: "ordinary", TenantID: 7, KnowledgeBaseID: "raw",
			ParseStatus: types.ParseStatusCompleted, CurrentParseAttempt: 3,
			FileSHA256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		}
		require.NoError(t, db.Create(row).Error)
		injected := injectPinnedSourceAfterKnowledgeLock(t, db, 7, row.ID)

		_, err := (&knowledgeRepository{db: db}).AllocateParseAttempt(
			context.Background(), row.ID, "embed", row.FileSHA256,
		)

		require.True(t, injected.Load(), "test barrier must insert the pin after the locked read")
		require.ErrorIs(t, err, ErrResourcePinned)
		var stored types.Knowledge
		require.NoError(t, db.First(&stored, "id = ?", row.ID).Error)
		require.Equal(t, int64(3), stored.CurrentParseAttempt)
		require.Equal(t, types.ParseStatusCompleted, stored.ParseStatus)
	})

	t.Run("allocate G3 bound reparse", func(t *testing.T) {
		db := setupAtomicPinTestDB(t)
		fileSHA := "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
		row := &types.Knowledge{
			ID: "g3", TenantID: 7, KnowledgeBaseID: "raw", Type: "file",
			ParseStatus: types.ParseStatusFailed, CurrentParseAttempt: 3,
			FileSHA256: fileSHA, FileSize: 12,
			Metadata: types.JSON(`{"product_ingestion_upload":"run:0"}`),
		}
		require.NoError(t, db.Create(row).Error)
		injected := injectPinnedSourceAfterKnowledgeLock(t, db, 7, row.ID)

		_, _, _, err := (&knowledgeRepository{db: db}).AllocateG3BoundReparse(
			context.Background(), 7, "raw", row.ID, "run", 0, 3,
			"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
			time.Now().Add(time.Hour), "embed", fileSHA,
		)

		require.True(t, injected.Load(), "test barrier must insert the pin after the locked read")
		require.ErrorIs(t, err, ErrResourcePinned)
		var stored types.Knowledge
		require.NoError(t, db.First(&stored, "id = ?", row.ID).Error)
		require.Equal(t, int64(3), stored.CurrentParseAttempt)
		require.Equal(t, types.ParseStatusFailed, stored.ParseStatus)
	})

	t.Run("transfer checkpoint", func(t *testing.T) {
		db := setupAtomicPinTestDB(t)
		row := &types.Knowledge{
			ID: "moving", TenantID: 7, KnowledgeBaseID: "source",
			ParseStatus: types.ParseStatusCompleted,
			FileSHA256:  "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		}
		require.NoError(t, db.Create(row).Error)
		var before types.Knowledge
		require.NoError(t, db.First(&before, "id = ?", row.ID).Error)
		after := before
		after.KnowledgeBaseID = "target"
		after.ParseStatus = types.ParseStatusProcessing
		injected := injectPinnedSourceAfterKnowledgeLock(t, db, 7, row.ID)

		err := (&knowledgeRepository{db: db}).UpdateKnowledgeForTransfer(
			context.Background(), &before, &after,
		)

		require.True(t, injected.Load(), fmt.Sprintf("test barrier did not observe %s", row.ID))
		require.ErrorIs(t, err, ErrResourcePinned)
		var stored types.Knowledge
		require.NoError(t, db.First(&stored, "id = ?", row.ID).Error)
		require.Equal(t, "source", stored.KnowledgeBaseID)
		require.Equal(t, types.ParseStatusCompleted, stored.ParseStatus)
	})
}

func TestUpdateKnowledgeRejectsSupersededWorkerAndControlStateRegression(t *testing.T) {
	t.Run("newer parse generation and source digest", func(t *testing.T) {
		db := setupAtomicPinTestDB(t)
		stored := &types.Knowledge{
			ID: "newer", TenantID: 7, KnowledgeBaseID: "raw", Title: "current",
			ParseStatus: types.ParseStatusProcessing, CurrentParseAttempt: 4,
			FileSHA256: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
			Metadata:   types.JSON(`{"native":"current"}`),
		}
		require.NoError(t, db.Create(stored).Error)
		stale := *stored
		stale.Title = "stale"
		stale.ParseStatus = types.ParseStatusFailed
		stale.CurrentParseAttempt = 3
		stale.FileSHA256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

		err := (&knowledgeRepository{db: db}).UpdateKnowledge(context.Background(), &stale)

		require.ErrorIs(t, err, ErrRevisionSuperseded)
		var got types.Knowledge
		require.NoError(t, db.First(&got, "id = ?", stored.ID).Error)
		require.Equal(t, "current", got.Title)
		require.Equal(t, types.ParseStatusProcessing, got.ParseStatus)
	})

	t.Run("deleting is terminal for a stale full row", func(t *testing.T) {
		db := setupAtomicPinTestDB(t)
		stored := &types.Knowledge{
			ID: "deleting", TenantID: 7, KnowledgeBaseID: "raw", Title: "current",
			ParseStatus: types.ParseStatusDeleting, CurrentParseAttempt: 4,
			FileSHA256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
			Metadata:   types.JSON(`{"native":"current"}`),
		}
		require.NoError(t, db.Create(stored).Error)
		stale := *stored
		stale.Title = "stale"
		stale.ParseStatus = types.ParseStatusFailed

		err := (&knowledgeRepository{db: db}).UpdateKnowledge(context.Background(), &stale)

		require.ErrorIs(t, err, ErrRevisionSuperseded)
		var got types.Knowledge
		require.NoError(t, db.First(&got, "id = ?", stored.ID).Error)
		require.Equal(t, types.ParseStatusDeleting, got.ParseStatus)
		require.Equal(t, "current", got.Title)
	})

	t.Run("moving metadata and knowledge base cannot be rolled back", func(t *testing.T) {
		db := setupAtomicPinTestDB(t)
		stored := &types.Knowledge{
			ID: "moving", TenantID: 7, KnowledgeBaseID: "target", Title: "current",
			ParseStatus: types.ParseStatusProcessing, CurrentParseAttempt: 4,
			FileSHA256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
			Metadata:   types.JSON(`{"native":"current","_knowledge_transfer":{"phase":"moving"}}`),
		}
		require.NoError(t, db.Create(stored).Error)
		stale := *stored
		stale.KnowledgeBaseID = "source"
		stale.Title = "stale"
		stale.ParseStatus = types.ParseStatusFailed
		stale.Metadata = types.JSON(`{"native":"stale"}`)

		err := (&knowledgeRepository{db: db}).UpdateKnowledge(context.Background(), &stale)

		require.ErrorIs(t, err, ErrRevisionSuperseded)
		var got types.Knowledge
		require.NoError(t, db.First(&got, "id = ?", stored.ID).Error)
		require.Equal(t, "target", got.KnowledgeBaseID)
		require.JSONEq(t, string(stored.Metadata), string(got.Metadata))
	})
}

func TestUpdateKnowledgeKeepsNativeFullRowSemanticsWithinGeneration(t *testing.T) {
	db := setupAtomicPinTestDB(t)
	stored := &types.Knowledge{
		ID: "current", TenantID: 7, KnowledgeBaseID: "raw", Title: "before",
		ParseStatus: types.ParseStatusProcessing, CurrentParseAttempt: 4,
		FileSHA256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		Metadata:   types.JSON(`{"native":"before"}`),
	}
	require.NoError(t, db.Create(stored).Error)
	incoming := *stored
	incoming.Title = "after"
	incoming.Description = "native description"
	incoming.ParseStatus = types.ParseStatusCompleted
	incoming.Metadata = types.JSON(`{"native":"after"}`)

	require.NoError(t, (&knowledgeRepository{db: db}).UpdateKnowledge(context.Background(), &incoming))

	var got types.Knowledge
	require.NoError(t, db.First(&got, "id = ?", stored.ID).Error)
	require.Equal(t, "after", got.Title)
	require.Equal(t, "native description", got.Description)
	require.Equal(t, types.ParseStatusCompleted, got.ParseStatus)
	require.JSONEq(t, string(incoming.Metadata), string(got.Metadata))
	require.Equal(t, int64(4), got.CurrentParseAttempt)
	require.Equal(t, stored.FileSHA256, got.FileSHA256)
}

func TestUpdateKnowledgeMissingRowNeverFallsBackToInsert(t *testing.T) {
	db := setupAtomicPinTestDB(t)
	missing := &types.Knowledge{
		ID: "missing", TenantID: 7, KnowledgeBaseID: "raw",
		ParseStatus: types.ParseStatusFailed, CurrentParseAttempt: 1,
		FileSHA256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
	}

	err := (&knowledgeRepository{db: db}).UpdateKnowledge(context.Background(), missing)

	require.Error(t, err)
	var count int64
	require.NoError(t, db.Model(&types.Knowledge{}).Where("id = ?", missing.ID).Count(&count).Error)
	require.Zero(t, count)
}
