package service

import (
	"context"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/access"
	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
)

type pinRaceReparseRepo struct {
	*docreaderAllocationProbe
}

func (r *pinRaceReparseRepo) AllocateParseAttempt(context.Context, string, string, string) (int64, error) {
	r.allocations++
	return 0, repository.ErrResourcePinned
}

type openAttemptProbe struct {
	noopSpanTracker
	calls int
}

func (p *openAttemptProbe) OpenAttempt(context.Context, string, string) (*Span, int, error) {
	p.calls++
	return nil, 0, nil
}

type attemptFenceKnowledgeRepo struct {
	interfaces.KnowledgeRepository
	current   *types.Knowledge
	updateErr error
	updates   int
}

func (r *attemptFenceKnowledgeRepo) GetKnowledgeByID(context.Context, uint64, string) (*types.Knowledge, error) {
	return r.current, nil
}

func (r *attemptFenceKnowledgeRepo) UpdateKnowledge(_ context.Context, incoming *types.Knowledge) error {
	r.updates++
	if r.updateErr != nil {
		return r.updateErr
	}
	if r.current.CurrentParseAttempt != incoming.CurrentParseAttempt ||
		r.current.FileSHA256 != incoming.FileSHA256 ||
		r.current.KnowledgeBaseID != incoming.KnowledgeBaseID {
		return repository.ErrRevisionSuperseded
	}
	r.current.ParseStatus = incoming.ParseStatus
	r.current.ErrorMessage = incoming.ErrorMessage
	return nil
}

func attemptFenceProcessFixture(
	t *testing.T,
	repo *attemptFenceKnowledgeRepo,
	engine *parentChildRetrieveEngine,
) (*knowledgeService, context.Context, *types.KnowledgeBase, *types.Knowledge, *parentChildChunkService) {
	t.Helper()
	worker := &types.Knowledge{
		ID: "knowledge-1", TenantID: 1, KnowledgeBaseID: "kb-1",
		ParseStatus: types.ParseStatusProcessing, CurrentParseAttempt: 1,
		FileSHA256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
	}
	current := *worker
	repo.current = &current
	chunks := &parentChildChunkService{}
	tenant := &types.Tenant{
		ID: 1,
		RetrieverEngines: types.RetrieverEngines{Engines: []types.RetrieverEngineParams{{
			RetrieverType: types.VectorRetrieverType, RetrieverEngineType: types.PostgresRetrieverEngineType,
		}}},
	}
	ctx := context.WithValue(context.Background(), types.TenantInfoContextKey, tenant)
	svc := &knowledgeService{
		repo: repo, chunkRepo: chunks,
		modelService:   parentChildModelService{embedder: parentChildEmbedder{}},
		retrieveEngine: parentChildRetrieveRegistry{engine: engine},
		graphEngine:    parentChildGraphRepo{}, tenantRepo: parentChildTenantRepo{},
		task: parentChildTaskEnqueuer{},
	}
	kb := &types.KnowledgeBase{
		ID: "kb-1", TenantID: 1, EmbeddingModelID: "embedding-1",
		IndexingStrategy: types.IndexingStrategy{VectorEnabled: true},
	}
	return svc, ctx, kb, worker, chunks
}

func TestBatchIndexFailureCleansOnlyItsStableBatchIDs(t *testing.T) {
	t.Run("lost state claim still removes partial late vector writes", func(t *testing.T) {
		repo := &attemptFenceKnowledgeRepo{updateErr: repository.ErrRevisionSuperseded}
		engine := &parentChildRetrieveEngine{batchErr: errors.New("index failed")}
		svc, ctx, kb, worker, chunks := attemptFenceProcessFixture(t, repo, engine)

		err := svc.processChunks(ctx, kb, worker,
			[]types.ParsedChunk{{Content: "body", Seq: 0, Start: 0, End: 4}},
			ProcessChunksOptions{ParseAttempt: 1},
		)

		require.ErrorIs(t, err, repository.ErrRevisionSuperseded)
		require.Equal(t, 1, repo.updates)
		require.Len(t, chunks.created, 1)
		require.Equal(t, []string{chunks.created[0].ID}, chunks.deleted)
		require.Equal(t, []string{chunks.created[0].ID}, engine.deleted)
	})

	t.Run("successful claim cleans this batch UUIDs only", func(t *testing.T) {
		repo := &attemptFenceKnowledgeRepo{}
		engine := &parentChildRetrieveEngine{batchErr: errors.New("index failed")}
		svc, ctx, kb, worker, chunks := attemptFenceProcessFixture(t, repo, engine)

		require.NoError(t, svc.processChunks(ctx, kb, worker,
			[]types.ParsedChunk{{Content: "body", Seq: 0, Start: 0, End: 4}},
			ProcessChunksOptions{ParseAttempt: 1},
		))

		require.Len(t, chunks.created, 1)
		require.Equal(t, []string{chunks.created[0].ID}, chunks.deleted)
		require.Equal(t, []string{chunks.created[0].ID}, engine.deleted)
	})
}

func TestSuccessfulOldBatchIndexCleansOwnArtifactsAfterNewAttemptWins(t *testing.T) {
	repo := &attemptFenceKnowledgeRepo{}
	engine := &parentChildRetrieveEngine{}
	svc, ctx, kb, worker, chunks := attemptFenceProcessFixture(t, repo, engine)
	engine.afterBatch = func() {
		newer := *repo.current
		newer.CurrentParseAttempt = 2
		newer.FileSHA256 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
		repo.current = &newer
	}

	require.NoError(t, svc.processChunks(ctx, kb, worker,
		[]types.ParsedChunk{{Content: "body", Seq: 0, Start: 0, End: 4}},
		ProcessChunksOptions{ParseAttempt: 1},
	))

	require.Len(t, chunks.created, 1)
	require.Equal(t, []string{chunks.created[0].ID}, chunks.deleted)
	require.Equal(t, []string{chunks.created[0].ID}, engine.deleted)
	require.Zero(t, repo.updates, "superseded success must stop before publishing old state")
}

func TestCleanupChunkIDsForAttemptExcludesNewerGeneration(t *testing.T) {
	chunks := []*types.Chunk{
		{ID: "legacy", ParseAttempt: 0},
		{ID: "current", ParseAttempt: 4},
		{ID: "newer", ParseAttempt: 5},
		{ID: "current", ParseAttempt: 4},
	}
	require.Equal(t, []string{"legacy", "current"}, cleanupChunkIDsForAttempt(chunks, 4))
}

func TestReparsePinRaceDoesNotOpenAttemptBeforeAtomicAllocation(t *testing.T) {
	svc, knowledge, kb, _, _, _, _ := docreaderRecoveryFixture(t)
	knowledge.CurrentParseAttempt = 1
	knowledge.ParseStatus = types.ParseStatusFailed
	base := &docreaderAllocationProbe{
		firstParseKnowledgeRepo: &firstParseKnowledgeRepo{knowledge: knowledge},
	}
	repo := &pinRaceReparseRepo{docreaderAllocationProbe: base}
	tracker := &openAttemptProbe{}
	svc.repo = repo
	svc.kbService = &createKnowledgeFileKBServiceStub{kb: kb}
	svc.spanTracker = tracker
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(17))
	ctx, err := access.WithKBTaskWrite(ctx, kb, 17)
	require.NoError(t, err)

	_, err = svc.ReparseKnowledge(ctx, knowledge.ID, nil)

	require.ErrorIs(t, err, ErrKnowledgeRevisionSourcePinned)
	require.Equal(t, 1, repo.allocations)
	require.Zero(t, tracker.calls, "span attempt is a persistent mutation and must follow generation allocation")
}
