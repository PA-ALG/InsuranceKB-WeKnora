package service

import (
	"context"

	"github.com/Tencent/WeKnora/internal/types"
)

// W1 chunk-repository calls on upstream's v0.9.0 inline-image test fakes.
// processChunks snapshots and deletes earlier rows by exact ID and writes its
// batch through CreateChunksAtRevision (the parse-generation fence); these
// methods map those calls onto the fakes' own bookkeeping, so upstream's test
// files stay byte-identical (U-1).

func (r *inlineImageChunkRepo) ListAllChunksByKnowledgeID(
	context.Context, uint64, string,
) ([]*types.Chunk, error) {
	return append([]*types.Chunk(nil), r.chunks...), nil
}

func (r *inlineImageChunkRepo) DeleteChunks(context.Context, uint64, []string) error {
	r.deleted = true
	return nil
}

func (r *inlineImageChunkRepo) CreateChunksAtRevision(
	ctx context.Context, chunks []*types.Chunk, _ uint64, _, _ string, _ int64, _ string,
) error {
	return r.CreateChunks(ctx, chunks)
}

// The lifecycle fake appends across image tasks; keep its CreateChunks.
func (r *inlineLifecycleChunkRepo) CreateChunksAtRevision(
	ctx context.Context, chunks []*types.Chunk, _ uint64, _, _ string, _ int64, _ string,
) error {
	return r.CreateChunks(ctx, chunks)
}

func (r *quotaChunkRepo) ListAllChunksByKnowledgeID(context.Context, uint64, string) ([]*types.Chunk, error) {
	return nil, nil
}

// Same bookkeeping as the fake's DeleteChunksByKnowledgeID: a delete after the
// batch was written is the cleanup the test expects.
func (r *quotaChunkRepo) DeleteChunks(context.Context, uint64, []string) error {
	if r.created {
		r.deletesAfterCreated++
	}
	return nil
}

func (r *quotaChunkRepo) CreateChunksAtRevision(
	ctx context.Context, chunks []*types.Chunk, _ uint64, _, _ string, _ int64, _ string,
) error {
	return r.CreateChunks(ctx, chunks)
}
