package service

import (
	"context"

	"github.com/Tencent/WeKnora/internal/types"
)

// v0.9.0's map reads text and scanned-page OCR chunks through
// ListChunksByKnowledgeIDAndTypes; our wiki fixtures answer it from the same
// rows their ListChunksByKnowledgeID returns (untyped fixture rows are text).
func typedChunks(all []*types.Chunk, err error, chunkTypes []types.ChunkType) ([]*types.Chunk, error) {
	var out []*types.Chunk
	for _, chunk := range all {
		if chunk == nil { // fixtures probe nil-row handling; pass it through
			out = append(out, chunk)
			continue
		}
		for _, want := range chunkTypes {
			if chunk.ChunkType == want || (chunk.ChunkType == "" && want == types.ChunkTypeText) {
				out = append(out, chunk)
				break
			}
		}
	}
	return out, err
}

func (c wikiOutcomeChunks) ListChunksByKnowledgeIDAndTypes(
	ctx context.Context, tenantID uint64, knowledgeID string, chunkTypes []types.ChunkType,
) ([]*types.Chunk, error) {
	all, err := c.ListChunksByKnowledgeID(ctx, tenantID, knowledgeID)
	return typedChunks(all, err, chunkTypes)
}

func (c longDocChunks) ListChunksByKnowledgeIDAndTypes(
	ctx context.Context, tenantID uint64, knowledgeID string, chunkTypes []types.ChunkType,
) ([]*types.Chunk, error) {
	all, err := c.ListChunksByKnowledgeID(ctx, tenantID, knowledgeID)
	return typedChunks(all, err, chunkTypes)
}

func (r *windowChunks) ListChunksByKnowledgeIDAndTypes(
	ctx context.Context, tenantID uint64, knowledgeID string, chunkTypes []types.ChunkType,
) ([]*types.Chunk, error) {
	all, err := r.ListChunksByKnowledgeID(ctx, tenantID, knowledgeID)
	return typedChunks(all, err, chunkTypes)
}
