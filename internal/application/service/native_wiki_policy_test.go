package service

import (
	"context"
	"encoding/json"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/hibiken/asynq"
	"github.com/stretchr/testify/require"
	"testing"
)

func TestNativeCandidatePolicyStopsQueuedWorkersBeforeAnyIO(t *testing.T) {
	cfg := &config.Config{ProductIngestion: &config.ProductIngestionConfig{
		Enabled: true, TenantID: 42, SpaceID: "space", RawKBID: "raw", WikiKBID: "wiki",
		WikiProducerPolicy: config.NativeCandidatesPolicy,
	}}
	// All dependencies are nil: reaching any persistence/model/page operation
	// is a failure. Old durable entries remain available for operator recovery.
	svc := &wikiIngestService{config: cfg}
	for _, kb := range []string{"raw", "wiki"} {
		payload, err := json.Marshal(WikiIngestPayload{TenantID: 42, KnowledgeBaseID: kb})
		require.NoError(t, err)
		task := asynq.NewTask("wiki:test", payload)
		require.ErrorIs(t, svc.ProcessWikiIngest(context.Background(), task), asynq.SkipRetry)
		require.ErrorIs(t, svc.ProcessWikiFinalize(context.Background(), task), asynq.SkipRetry)
	}
}

type nativePolicyKnowledgeRepo struct {
	interfaces.KnowledgeRepository
	expected int
}

func (r *nativePolicyKnowledgeRepo) GetKnowledgeByIDOnly(context.Context, string) (*types.Knowledge, error) {
	return &types.Knowledge{ID: "doc", ParseStatus: types.ParseStatusProcessing}, nil
}
func (r *nativePolicyKnowledgeRepo) SetFinalizing(_ context.Context, _ string, count int) (bool, error) {
	r.expected = count
	return false, nil // stop after observing the exact counter, before queue mutation
}

type nativePolicyKB struct {
	interfaces.KnowledgeBaseService
}

func (nativePolicyKB) GetKnowledgeBaseByIDOnly(context.Context, string) (*types.KnowledgeBase, error) {
	return &types.KnowledgeBase{ID: "raw", TenantID: 42, IndexingStrategy: types.IndexingStrategy{WikiEnabled: true}}, nil
}

type nativePolicyChunks struct{ interfaces.ChunkService }

func (nativePolicyChunks) ListChunksByKnowledgeID(context.Context, string) ([]*types.Chunk, error) {
	return []*types.Chunk{{ID: "chunk", ChunkType: types.ChunkTypeText, Content: "original source"}}, nil
}
func TestNativeCandidatePolicyRemovesWikiSlotFromPostprocess(t *testing.T) {
	for _, policy := range []string{"", config.NativeCandidatesPolicy} {
		repo := &nativePolicyKnowledgeRepo{}
		svc := &KnowledgePostProcessService{config: &config.Config{ProductIngestion: &config.ProductIngestionConfig{
			Enabled: true, TenantID: 42, SpaceID: "space", RawKBID: "raw", WikiKBID: "wiki", WikiProducerPolicy: policy,
		}}, knowledgeRepo: repo, kbService: nativePolicyKB{}, chunkService: nativePolicyChunks{}}
		payload, err := json.Marshal(types.KnowledgePostProcessPayload{TenantID: 42, KnowledgeID: "doc", KnowledgeBaseID: "raw", Attempt: 1})
		require.NoError(t, err)
		require.NoError(t, svc.Handle(context.Background(), asynq.NewTask("postprocess", payload)))
		want := 2 // unchanged: document summary + native wiki
		if policy != "" {
			want = 1
		}
		require.Equal(t, want, repo.expected)
	}
}
