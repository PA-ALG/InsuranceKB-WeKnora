package chatsource_test

import (
	"context"
	"testing"

	chatpipeline "github.com/Tencent/WeKnora/internal/application/service/chat_pipeline"
	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestFilterRecoversVerifiedPrimaryBodyFromNativeMixedAttemptMerge(t *testing.T) {
	s, h, p, a := fixture()
	r := resolver(s, h, p, a)
	turn, err := r.Resolve(context.Background(), tenant, types.SearchTargets{kb("raw-1")})
	require.NoError(t, err)
	cm := &types.ChatManage{}
	cm.SearchResult = []*types.SearchResult{
		{
			ID: "good", KnowledgeID: "k1", KnowledgeBaseID: "raw-1",
			ChunkType: "text", ChunkIndex: 1, Content: "fixed body", Score: 0.9,
		},
		{
			ID: "old", KnowledgeID: "k1", KnowledgeBaseID: "raw-1",
			ChunkType: "text", ChunkIndex: 2, Content: "old parse body", Score: 0.8,
		},
	}
	plugin := chatpipeline.NewPluginMerge(chatpipeline.NewEventManager(), nil, nil)
	require.Nil(t, plugin.OnEvent(context.Background(), types.CHUNK_MERGE, cm,
		func() *chatpipeline.PluginError { return nil }))
	require.Len(t, cm.MergeResult, 1)
	require.Contains(t, cm.MergeResult[0].Content, "old parse body", "native merge reproduced the unsafe contribution")
	rows := chunkRows{rows: []*types.Chunk{{
		ID: "good", TenantID: tenant, KnowledgeID: "k1", KnowledgeBaseID: "raw-1", ParseAttempt: 2,
		Content: "fixed body", ChunkType: types.ChunkTypeText, ChunkIndex: 1,
	}}}
	got, err := r.Filter(context.Background(), tenant, turn, rows, cm.MergeResult)
	require.NoError(t, err)
	require.Len(t, got, 1)
	require.Equal(t, "fixed body", got[0].Content)
	require.Empty(t, got[0].SubChunkID)
	require.Equal(t, 0.9, got[0].Score)
}

func TestFilterPipelineRemovesAlreadyRenderedParentExpansion(t *testing.T) {
	s, h, p, a := fixture()
	r := resolver(s, h, p, a)
	turn, err := r.Resolve(context.Background(), tenant, types.SearchTargets{kb("raw-1")})
	require.NoError(t, err)
	cm := &types.ChatManage{}
	cm.MergeResult = []*types.SearchResult{{
		ID: "good", KnowledgeID: "k1", KnowledgeBaseID: "raw-1",
		Content: "unverified parent", ImageInfo: "parent image", ContentRewritten: true,
	}}
	cm.RenderedContexts = "rendered: unverified parent"
	cm.UserContent = "question; " + cm.RenderedContexts + "; image; attachment"
	rows := chunkRows{rows: []*types.Chunk{{
		ID: "good", TenantID: tenant, KnowledgeID: "k1", KnowledgeBaseID: "raw-1", ParseAttempt: 2,
		Content: "safe child", ImageInfo: "safe image", StartAt: 4, EndAt: 14,
		ChunkIndex: 3, ChunkType: types.ChunkTypeText, ParentChunkID: "safe-parent",
	}}}
	require.NoError(t, chatsource.FilterPipeline(chatsource.WithTurn(context.Background(), turn, tenant), r, rows, cm))
	require.Equal(t, "safe child", cm.MergeResult[0].Content)
	require.Equal(t, "safe image", cm.MergeResult[0].ImageInfo)
	require.Equal(t, 4, cm.MergeResult[0].StartAt)
	require.Equal(t, 14, cm.MergeResult[0].EndAt)
	require.Equal(t, 3, cm.MergeResult[0].ChunkIndex)
	require.Equal(t, "text", cm.MergeResult[0].ChunkType)
	require.Equal(t, "safe-parent", cm.MergeResult[0].ParentChunkID)
	require.False(t, cm.MergeResult[0].ContentRewritten)
	require.Empty(t, cm.RenderedContexts)
	require.Equal(t, "question; ; image; attachment", cm.UserContent)
}
