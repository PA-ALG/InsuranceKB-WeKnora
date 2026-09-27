package service

import (
	"context"

	"github.com/Tencent/WeKnora/internal/models/embedding"
	"github.com/Tencent/WeKnora/internal/types"
)

type attemptChunkIndexDeleter interface {
	DeleteByChunkIDList(context.Context, []string, int, string) error
}

func knowledgeChunkIDs(chunks []*types.Chunk) []string {
	ids := make([]string, 0, len(chunks))
	seen := make(map[string]struct{}, len(chunks))
	for _, chunk := range chunks {
		if chunk == nil || chunk.ID == "" {
			continue
		}
		if _, ok := seen[chunk.ID]; ok {
			continue
		}
		seen[chunk.ID] = struct{}{}
		ids = append(ids, chunk.ID)
	}
	return ids
}

// cleanupChunkIDsForAttempt returns a stable pre-write snapshot. Exact IDs
// avoid deleting chunks that a newer generation creates after this read.
func cleanupChunkIDsForAttempt(chunks []*types.Chunk, parseAttempt int64) []string {
	eligible := make([]*types.Chunk, 0, len(chunks))
	for _, chunk := range chunks {
		if chunk == nil {
			continue
		}
		if parseAttempt > 0 && chunk.ParseAttempt > parseAttempt {
			continue
		}
		eligible = append(eligible, chunk)
	}
	return knowledgeChunkIDs(eligible)
}

func (s *knowledgeService) cleanupAttemptChunkRows(
	ctx context.Context,
	knowledge *types.Knowledge,
	chunks []*types.Chunk,
) error {
	ids := knowledgeChunkIDs(chunks)
	if len(ids) == 0 {
		return nil
	}
	return s.chunkRepo.DeleteChunks(ctx, knowledge.TenantID, ids)
}

func cleanupAttemptChunkIndex(
	ctx context.Context,
	engine attemptChunkIndexDeleter,
	embedder embedding.Embedder,
	knowledgeType string,
	chunks []*types.Chunk,
) error {
	ids := knowledgeChunkIDs(chunks)
	if len(ids) == 0 || engine == nil || embedder == nil {
		return nil
	}
	return engine.DeleteByChunkIDList(ctx, ids, embedder.GetDimensions(), knowledgeType)
}
