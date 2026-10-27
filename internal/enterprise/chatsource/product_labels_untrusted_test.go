// QA1 acceptance added after review #371 R1 (protected, written by Claude; Spec
// docs/design/slices/QA1-问答来源标注与范围说明.md §2.3): a raw result's own entity_names metadata
// is untrusted. Through two pipeline passes over three lists sharing one result, the metadata,
// title and quick-answer passage follow only the turn's mapping, and the title is prefixed once.
// RED until the review fixes land.
package chatsource_test

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/types"
)

func pipelineTwice(
	t *testing.T, r *chatsource.Resolver, external map[string]string,
) (context.Context, *types.ChatManage) {
	t.Helper()
	ctx, _, err := chatsource.ResolveAnswer(context.Background(), r, tenant, types.SearchTargets{kb("raw-1")})
	require.NoError(t, err)
	result := &types.SearchResult{
		ID: "c1", KnowledgeID: "k1", KnowledgeBaseID: "raw-1", KnowledgeTitle: "保险条款.pdf", Content: "正文",
		Metadata: external,
	}
	cm := &types.ChatManage{}
	cm.SearchResult = []*types.SearchResult{result}
	cm.RerankResult = []*types.SearchResult{result}
	cm.MergeResult = []*types.SearchResult{result}
	chunks := chunkRows{rows: []*types.Chunk{
		{ID: "c1", TenantID: tenant, KnowledgeID: "k1", KnowledgeBaseID: "raw-1", ParseAttempt: 2},
	}}
	for pass := 0; pass < 2; pass++ {
		require.NoError(t, chatsource.FilterPipeline(ctx, r, chunks, cm))
	}
	return ctx, cm
}

func TestExternalEntityNamesNeverOverrideTheTurnsLabel(t *testing.T) {
	for name, external := range map[string]string{"wrong name": plus, "empty": ""} {
		t.Run(name, func(t *testing.T) {
			r, _, _, _, _ := labelFixture(nil)
			ctx, cm := pipelineTwice(t, r, map[string]string{"entity_names": external, "keep": "yes"})
			for _, rows := range [][]*types.SearchResult{cm.SearchResult, cm.RerankResult, cm.MergeResult} {
				require.Len(t, rows, 1)
				got := rows[0]
				require.Equal(t, classic, got.Metadata["entity_names"])
				require.Equal(t, "yes", got.Metadata["keep"])
				require.Equal(t, classic+" · 保险条款.pdf", got.KnowledgeTitle, "the turn's label, once")
				require.Equal(t, "原文检索（未经编译审核）｜所属产品："+classic+"\n正文",
					chatsource.AnswerPassage(ctx, got, "正文"))
			}
		})
	}
}

func TestATurnWithoutLabelsDropsExternalEntityNames(t *testing.T) {
	s, h, p, a := fixture()
	ctx, cm := pipelineTwice(t, chatsource.NewResolver(s, h, p, a), map[string]string{"entity_names": plus})
	got := cm.MergeResult[0]
	require.NotContains(t, got.Metadata, "entity_names")
	require.Equal(t, "保险条款.pdf", got.KnowledgeTitle)
	require.Equal(t, "原文检索（未经编译审核）\n正文", chatsource.AnswerPassage(ctx, got, "正文"))
}

func TestWrappedSearchRowsReplaceExternalEntityNames(t *testing.T) {
	labelled, _, _, _, _ := labelFixture(nil)
	s, h, p, a := fixture()
	resolvers := map[string]*chatsource.Resolver{"labelled": labelled, "unlabelled": chatsource.NewResolver(s, h, p, a)}
	for name, r := range resolvers {
		t.Run(name, func(t *testing.T) {
			turn, err := r.Resolve(context.Background(), tenant, types.SearchTargets{kb("raw-1")})
			require.NoError(t, err)
			inner := nativeTool{&types.ToolResult{Success: true, Output: "native", Data: map[string]interface{}{
				"results": []map[string]interface{}{{
					"chunk_id": "c1", "knowledge_id": "k1", "knowledge_base_id": "raw-1",
					"knowledge_title": "保险条款.pdf", "content": "正文",
					"metadata": map[string]interface{}{"entity_names": plus},
				}},
			}}}
			chunks := chunkRows{rows: []*types.Chunk{
				{ID: "c1", TenantID: tenant, KnowledgeID: "k1", KnowledgeBaseID: "raw-1", ParseAttempt: 2},
			}}
			tool := chatsource.WrapTool(inner, r, turn, tenant, chunks)
			got, err := tool.Execute(context.Background(), json.RawMessage(`{}`))
			require.NoError(t, err)
			row := got.Data["results"].([]map[string]interface{})[0]
			metadata := row["metadata"].(map[string]interface{})
			if name == "labelled" {
				require.Equal(t, classic, metadata["entity_names"])
				require.Equal(t, classic+" · 保险条款.pdf", row["knowledge_title"])
			} else {
				require.NotContains(t, metadata, "entity_names")
				require.Equal(t, "保险条款.pdf", row["knowledge_title"])
			}
		})
	}
}
