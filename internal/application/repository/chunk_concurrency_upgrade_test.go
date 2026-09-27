package repository

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestCreateChunksAtRevisionRejectsSupersededAttemptWithoutPartialInsert(t *testing.T) {
	db := setupAtomicPinTestDB(t)
	stored := &types.Knowledge{
		ID: "knowledge", TenantID: 7, KnowledgeBaseID: "raw",
		CurrentParseAttempt: 2,
		FileSHA256:          "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
	}
	require.NoError(t, db.Create(stored).Error)
	chunk := &types.Chunk{
		ID: "old-attempt", TenantID: 7, KnowledgeBaseID: "raw", KnowledgeID: stored.ID,
		ParseAttempt: 1, Content: "stale worker output",
	}

	err := (&chunkRepository{db: db}).CreateChunksAtRevision(
		context.Background(), []*types.Chunk{chunk}, 7, "raw", stored.ID, 1,
		"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
	)

	require.ErrorIs(t, err, ErrRevisionSuperseded)
	var count int64
	require.NoError(t, db.Model(&types.Chunk{}).Where("knowledge_id = ?", stored.ID).Count(&count).Error)
	require.Zero(t, count)
}

func TestCreateChunksAtRevisionRejectsCrossScopeBatch(t *testing.T) {
	db := setupAtomicPinTestDB(t)
	stored := &types.Knowledge{
		ID: "knowledge", TenantID: 7, KnowledgeBaseID: "raw", CurrentParseAttempt: 2,
		FileSHA256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
	}
	require.NoError(t, db.Create(stored).Error)
	chunks := []*types.Chunk{
		{ID: "owned", TenantID: 7, KnowledgeBaseID: "raw", KnowledgeID: stored.ID, ParseAttempt: 2, Content: "owned"},
		{ID: "foreign", TenantID: 8, KnowledgeBaseID: "raw", KnowledgeID: stored.ID, ParseAttempt: 2, Content: "foreign"},
	}

	err := (&chunkRepository{db: db}).CreateChunksAtRevision(
		context.Background(), chunks, 7, "raw", stored.ID, 2, stored.FileSHA256,
	)

	require.Error(t, err)
	var count int64
	require.NoError(t, db.Model(&types.Chunk{}).Count(&count).Error)
	require.Zero(t, count)
}

func TestCreateChunksAtRevisionAllowsExactLegacyZeroAttempt(t *testing.T) {
	db := setupAtomicPinTestDB(t)
	stored := &types.Knowledge{ID: "legacy", TenantID: 7, KnowledgeBaseID: "raw"}
	require.NoError(t, db.Create(stored).Error)
	chunk := &types.Chunk{
		ID: "legacy-chunk", TenantID: 7, KnowledgeBaseID: "raw", KnowledgeID: stored.ID,
		ParseAttempt: 0, Content: "legacy worker output",
	}

	require.NoError(t, (&chunkRepository{db: db}).CreateChunksAtRevision(
		context.Background(), []*types.Chunk{chunk}, 7, "raw", stored.ID, 0, "",
	))
	var count int64
	require.NoError(t, db.Model(&types.Chunk{}).Where("knowledge_id = ?", stored.ID).Count(&count).Error)
	require.Equal(t, int64(1), count)
}
