package repository

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func TestMergeG3BoundRecoveryMetadataKeepsCurrentReceipt(t *testing.T) {
	current := types.JSON(`{"product_ingestion_upload":"original:0","product_ingestion_recoveries":{"key":{"dispatch_state":"enqueued"}},"other":"keep"}`)
	stale := types.JSON(`{"product_ingestion_upload":"original:0","product_ingestion_recoveries":{"key":{"dispatch_state":"dispatching"}},"new":"value"}`)
	merged, err := mergeG3BoundRecoveryMetadata(stale, current)
	require.NoError(t, err)
	var metadata map[string]json.RawMessage
	require.NoError(t, json.Unmarshal(merged, &metadata))
	require.JSONEq(t, `{"key":{"dispatch_state":"enqueued"}}`, string(metadata[g3BoundReparseMetadataKey]))
	require.Equal(t, `"value"`, string(metadata["new"]))
	require.NotContains(t, metadata, "other")
}

func TestUpdateKnowledgeCannotClobberBoundRecoveryReceiptOrGeneration(t *testing.T) {
	db, err := gorm.Open(sqlite.Open("file:"+uuid.NewString()+"?mode=memory&cache=shared"), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(&types.Knowledge{}))
	initial := types.Knowledge{ID: "source", TenantID: 7, KnowledgeBaseID: "raw", CurrentParseAttempt: 4,
		Metadata: types.JSON(`{"product_ingestion_upload":"original:0","product_ingestion_recoveries":{"key":{"dispatch_state":"dispatching"}}}`)}
	require.NoError(t, db.Create(&initial).Error)
	var stale types.Knowledge
	require.NoError(t, db.First(&stale, "id = ?", "source").Error)
	currentMetadata := types.JSON(`{"product_ingestion_upload":"original:0","product_ingestion_recoveries":{"key":{"dispatch_state":"enqueued"}}}`)
	require.NoError(t, db.Model(&types.Knowledge{}).Where("id = ?", "source").Update("metadata", currentMetadata).Error)
	stale.Description = "worker result"
	require.NoError(t, (&knowledgeRepository{db: db}).UpdateKnowledge(context.Background(), &stale))
	var stored types.Knowledge
	require.NoError(t, db.First(&stored, "id = ?", "source").Error)
	require.Contains(t, string(stored.Metadata), `"dispatch_state":"enqueued"`)
	require.Equal(t, "worker result", stored.Description)
	require.NoError(t, db.Model(&types.Knowledge{}).Where("id = ?", "source").Update("current_parse_attempt", 5).Error)
	require.ErrorContains(t, (&knowledgeRepository{db: db}).UpdateKnowledge(context.Background(), &stale), "lost parse generation")
}

func TestAllocateG3BoundReparseIsScopedAndIdempotent(t *testing.T) {
	db, err := gorm.Open(sqlite.Open("file:"+uuid.NewString()+"?mode=memory&cache=shared"), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.Exec(`CREATE TABLE knowledges (
		id TEXT PRIMARY KEY, tenant_id INTEGER, knowledge_base_id TEXT, type TEXT,
		metadata TEXT, current_parse_attempt INTEGER, parse_status TEXT, enable_status TEXT,
		file_size INTEGER, file_sha256 TEXT, embedding_model_id TEXT, description TEXT,
		error_message TEXT, pending_subtasks_count INTEGER, processed_at DATETIME, updated_at DATETIME,
		deleted_at DATETIME
	)`).Error)
	require.NoError(t, db.Exec(`INSERT INTO knowledges
		(id,tenant_id,knowledge_base_id,type,metadata,current_parse_attempt,parse_status,enable_status,file_size,file_sha256)
		VALUES ('source',7,'raw','file','{"product_ingestion_upload":"original:0","other":"keep"}',3,'failed','disabled',12,?)`,
		"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa").Error)
	repo := &knowledgeRepository{db: db}
	deadline := time.Now().Add(time.Hour).UTC().Truncate(time.Second)
	receipt, knowledge, fresh, err := repo.AllocateG3BoundReparse(context.Background(), 7, "raw", "source", "original", 0, 3, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", deadline, "embed", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
	require.NoError(t, err)
	require.True(t, fresh)
	require.Equal(t, int64(4), receipt.ParseAttempt)
	require.Equal(t, types.ParseStatusPending, knowledge.ParseStatus)
	dispatching, err := repo.AdvanceG3BoundReparse(context.Background(), 7, "source", receipt.RecoveryKey, receipt.ParseAttempt, "allocated", "dispatching", nil)
	require.NoError(t, err)
	require.Equal(t, "dispatching", dispatching.DispatchState)
	queueID := "g3-reparse-" + receipt.RecoveryKey
	enqueued, err := repo.AdvanceG3BoundReparse(context.Background(), 7, "source", receipt.RecoveryKey, receipt.ParseAttempt, "dispatching", "enqueued", &queueID)
	require.NoError(t, err)
	require.Equal(t, queueID, *enqueued.QueueTaskID)
	_, err = repo.AdvanceG3BoundReparse(context.Background(), 7, "source", receipt.RecoveryKey, receipt.ParseAttempt, "allocated", "failed", nil)
	require.Error(t, err)
	receipt2, _, fresh, err := repo.AllocateG3BoundReparse(context.Background(), 7, "raw", "source", "original", 0, 3, receipt.RecoveryKey, deadline, "embed", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
	require.NoError(t, err)
	require.False(t, fresh)
	require.Equal(t, receipt.ParseAttempt, receipt2.ParseAttempt)
	_, _, _, err = repo.AllocateG3BoundReparse(context.Background(), 8, "raw", "source", "original", 0, 4, "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", deadline, "embed", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
	require.Error(t, err)
	var metadata string
	require.NoError(t, db.Raw("SELECT metadata FROM knowledges WHERE id = 'source'").Scan(&metadata).Error)
	require.Contains(t, metadata, `"other":"keep"`)
}
