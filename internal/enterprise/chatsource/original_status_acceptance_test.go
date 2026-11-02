// PV-5c RED (Codex, #535): an explicit original sales question keeps its status when a
// retrieval rewrite drops the sales terms. Entirely synthetic, through the real FilterPipeline.
package chatsource_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

func saleStatuses(results []*types.SearchResult) []*types.SearchResult {
	var out []*types.SearchResult
	for _, result := range results {
		if result.Metadata["knowledge_class"] == "sale_status" {
			out = append(out, result)
		}
	}
	return out
}

func TestOriginalSalesStatusSurvivesRetrievalRewrites(t *testing.T) {
	cases := []struct{ original, rewrite, id, status string }{
		{"戊医疗保险能买吗", "戊医疗保险等待期", "U", "销售状态：未知"},
		{"丁护理保险能买吗", "丁护理保险理赔等待期", "P", "销售状态：停售"},
		{"己医疗保险能买吗", "己医疗保险等待期", "F", "销售状态：未开售"},
	}
	for _, tc := range cases {
		t.Run(tc.id, func(t *testing.T) {
			ctx, resolver, cm := saleTurn(t, tc.rewrite)
			cm.Query = tc.original
			require.NoError(t, chatsource.FilterPipeline(ctx, resolver, noChunks{t}, cm))
			lines := saleStatuses(cm.MergeResult)
			require.Len(t, lines, 1)
			require.Equal(t, "release:rel-1:entity/"+tc.id, lines[0].ID)
			require.Contains(t, lines[0].Content, tc.status)
			require.NotContains(t, lines[0].Metadata, "evidence_index")
			require.Equal(t, "rel-1", lines[0].Metadata["release_id"])
			require.Equal(t, "s1", lines[0].Metadata["space_id"])
			require.Contains(t, order(cm.MergeResult), "release:rel-1:"+tc.id+"/waiting_period")
			require.Equal(t, tc.rewrite, cm.RewriteQuery, "retrieval text is not changed")
		})
	}
}

func TestOriginalSalesQuestionKeepsEveryExplicitlyNamedProductOnce(t *testing.T) {
	ctx, resolver, cm := saleTurn(t, "戊医疗保险等待期")
	cm.Query = "丁护理保险和戊医疗保险现在能买吗"
	require.NoError(t, chatsource.FilterPipeline(ctx, resolver, noChunks{t}, cm))
	expected := []string{"release:rel-1:entity/P", "release:rel-1:entity/U"}
	require.Equal(t, expected, order(saleStatuses(cm.MergeResult)))
	// The rewrite still determines the fields: adding statuses must not silently broaden them.
	require.Equal(t, "release:rel-1:U/waiting_period", cm.MergeResult[2].ID)
}

func TestOriginalStatusFallbackKeepsOldRewriteAndNonSalesBehaviour(t *testing.T) {
	for _, original := range []string{"", "那款现在能买吗", "原问题"} {
		ctx, resolver, cm := saleTurn(t, "戊医疗保险能买吗")
		cm.Query = original
		require.NoError(t, chatsource.FilterPipeline(ctx, resolver, noChunks{t}, cm))
		require.Len(t, saleStatuses(cm.MergeResult), 1, "old inferred/rewritten naming still works")
	}
	for _, question := range []string{"戊医疗保险理赔", "戊医疗保险能买吗理赔快吗", "等待期", "推荐销售方法"} {
		ctx, resolver, cm := saleTurn(t, question)
		cm.Query = question
		require.NoError(t, chatsource.FilterPipeline(ctx, resolver, noChunks{t}, cm))
		require.Empty(t, saleStatuses(cm.MergeResult))
	}
	ctx, resolver, cm := saleTurn(t, "戊医疗保险能买吗")
	cm.Query = cm.RewriteQuery
	require.NoError(t, chatsource.FilterPipeline(ctx, resolver, noChunks{t}, cm))
	require.Len(t, saleStatuses(cm.MergeResult), 1, "same original/rewrite must not duplicate")
}

type countedOriginalStatusReader struct{ reads int }

func (r *countedOriginalStatusReader) ReleaseByID(
	ctx context.Context, tenantID uint64, spaceID, releaseID string,
) (release.Release, error) {
	r.reads++
	return (saleReader{}).ReleaseByID(ctx, tenantID, spaceID, releaseID)
}

func TestOriginalStatusSharesOnePinnedReadAndSurvivesBothDeliveryPasses(t *testing.T) {
	ctx, resolver, cm := saleTurn(t, "戊医疗保险等待期")
	cm.Query = "戊医疗保险能买吗"
	reader := &countedOriginalStatusReader{}
	resolver = resolver.WithPublished(knowledge.NewService(reader))
	require.NoError(t, chatsource.FilterPipeline(ctx, resolver, noChunks{t}, cm))
	require.Len(t, saleStatuses(cm.MergeResult), 1)
	before := order(cm.MergeResult)
	require.NoError(t, chatsource.FilterPipeline(ctx, resolver, noChunks{t}, cm))
	require.Equal(t, before, order(cm.MergeResult))
	require.Equal(t, 1, reader.reads)
}
