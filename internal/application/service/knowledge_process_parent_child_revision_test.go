package service

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/models/embedding"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

// The upstream parent/child fixture (knowledge_process_parent_child_test.go) stays
// byte-identical to v0.9.0. Every processChunks run in this fork also lists a
// knowledge's chunks for exact-ID cleanup (W1), writes chunks at the parse revision,
// and may delete vectors by chunk ID, so the shared fixture needs these methods. They
// keep no state: tests that assert what was cleaned use the recording wrappers below,
// or their own types (knowledge_process_index_retry_test.go).

func (s *parentChildChunkService) ListAllChunksByKnowledgeID(
	context.Context, uint64, string,
) ([]*types.Chunk, error) {
	return nil, nil
}

func (s *parentChildChunkService) DeleteChunks(context.Context, uint64, []string) error {
	return nil
}

func (s *parentChildChunkService) CreateChunksAtRevision(
	_ context.Context,
	chunks []*types.Chunk,
	_ uint64,
	_ string,
	_ string,
	_ int64,
	_ string,
) error {
	s.created = append([]*types.Chunk(nil), chunks...)
	return nil
}

func (e *parentChildRetrieveEngine) DeleteByChunkIDList(context.Context, []string, int, string) error {
	return nil
}

// recordingChunkService records the chunk IDs an exact-ID cleanup removes. No method of
// the embedded fixture calls DeleteChunks, so every cleanup reaches this override.
type recordingChunkService struct {
	*parentChildChunkService
	deleted []string
}

func newRecordingChunkService() *recordingChunkService {
	return &recordingChunkService{parentChildChunkService: &parentChildChunkService{}}
}

func (s *recordingChunkService) DeleteChunks(_ context.Context, _ uint64, ids []string) error {
	s.deleted = append(s.deleted, ids...)
	return nil
}

// recordingRetrieveEngine records vector deletions by chunk ID and can fail BatchIndex
// or run a hook after it. No method of the embedded fixture calls DeleteByChunkIDList
// or BatchIndex, so both overrides see every call.
type recordingRetrieveEngine struct {
	*parentChildRetrieveEngine
	deleted    []string
	batchErr   error
	afterBatch func()
}

func newRecordingRetrieveEngine(batchErr error) *recordingRetrieveEngine {
	return &recordingRetrieveEngine{parentChildRetrieveEngine: &parentChildRetrieveEngine{}, batchErr: batchErr}
}

func (e *recordingRetrieveEngine) DeleteByChunkIDList(_ context.Context, ids []string, _ int, _ string) error {
	e.deleted = append(e.deleted, ids...)
	return nil
}

func (e *recordingRetrieveEngine) BatchIndex(
	ctx context.Context,
	embedder embedding.Embedder,
	infos []*types.IndexInfo,
	retrieverTypes []types.RetrieverType,
) error {
	if err := e.parentChildRetrieveEngine.BatchIndex(ctx, embedder, infos, retrieverTypes); err != nil {
		return err
	}
	if e.afterBatch != nil {
		e.afterBatch()
	}
	return e.batchErr
}

// The index-retry fixtures (knowledge_process_index_retry_test.go) assert the exact-ID
// cleanup through their own deleted fields; their recording methods live here so that
// file only gains the two fields.

func (s *indexRetryChunkRepo) DeleteChunks(_ context.Context, _ uint64, ids []string) error {
	s.deleted = append(s.deleted, ids...)
	return nil
}

func (e *failingIndexEngine) DeleteByChunkIDList(_ context.Context, ids []string, _ int, _ string) error {
	e.deleted = append(e.deleted, ids...)
	return nil
}

// TestProcessChunksIndexesEveryTextChildSucceeds keeps the success assertion this fork
// had added to the upstream TestProcessChunksIndexesEveryTextChild, with the same setup.
func TestProcessChunksIndexesEveryTextChildSucceeds(t *testing.T) {
	knowledge := &types.Knowledge{
		ID:              "knowledge-1",
		TenantID:        1,
		KnowledgeBaseID: "kb-1",
		ParseStatus:     types.ParseStatusProcessing,
	}
	chunkService := &parentChildChunkService{}
	retrieveEngine := &parentChildRetrieveEngine{}
	tenant := &types.Tenant{
		ID: 1,
		RetrieverEngines: types.RetrieverEngines{Engines: []types.RetrieverEngineParams{
			{
				RetrieverType:       types.VectorRetrieverType,
				RetrieverEngineType: types.PostgresRetrieverEngineType,
			},
		}},
	}
	ctx := context.WithValue(context.Background(), types.TenantInfoContextKey, tenant)
	svc := &knowledgeService{
		repo:           &parentChildKnowledgeRepo{knowledge: knowledge},
		chunkRepo:      chunkService,
		modelService:   parentChildModelService{embedder: parentChildEmbedder{}},
		retrieveEngine: parentChildRetrieveRegistry{engine: retrieveEngine},
		graphEngine:    parentChildGraphRepo{},
		tenantRepo:     parentChildTenantRepo{},
		task:           parentChildTaskEnqueuer{},
	}
	kb := &types.KnowledgeBase{
		ID:               "kb-1",
		TenantID:         1,
		EmbeddingModelID: "embedding-1",
		IndexingStrategy: types.IndexingStrategy{VectorEnabled: true},
	}
	chunks := []types.ParsedChunk{
		{Content: "linked child", Seq: 0, Start: 0, End: 12, ParentIndex: 0},
		{Content: "standalone child", Seq: 1, Start: 12, End: 28, ParentIndex: -1},
	}

	require.NoError(t, svc.processChunks(ctx, kb, knowledge, chunks, ProcessChunksOptions{
		ParentChunks: []types.ParsedParentChunk{
			{Content: "parent context", Seq: 0, Start: 0, End: 28},
		},
	}))
}
