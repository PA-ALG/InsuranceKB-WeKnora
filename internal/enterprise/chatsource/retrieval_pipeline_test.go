package chatsource_test

import (
	"fmt"
	"testing"

	chatpipeline "github.com/Tencent/WeKnora/internal/application/service/chat_pipeline"
	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

// Exercise the real final stage: checking only the pre-Trigger order cannot prove that
// the named product survives the native TopK cut.
func TestNamedProductOrderSurvivesNativeTopK(t *testing.T) {
	for _, list := range []string{"merged", "reranked"} {
		for _, topK := range []int{1, 2, 5, 0, -1} {
			t.Run(fmt.Sprintf("%s/k%d", list, topK), func(t *testing.T) {
				ctx, resolver, cm := answerTurn(t, retrievalReader{}, "乙保险悦享版的等待期多久")
				other, named := passage("other-high", "k1"), passage("named-low", "k2")
				second := passage("global-second", "k1")
				other.Score, second.Score, named.Score = 0.95, 0.9, 0.8
				cm.RerankTopK = topK
				if list == "merged" {
					cm.MergeResult = []*types.SearchResult{other, second, named}
				} else {
					cm.RerankResult = []*types.SearchResult{other, second, named}
				}
				restore := chatsource.RetrievalScope(ctx, resolver, types.FILTER_TOP_K, cm)
				want := []string{"named-low", "other-high", "global-second"}
				if topK > 0 && topK < len(want) {
					want = want[:topK]
				}
				require.Equal(t, len(want), cm.RerankTopK, "the stage cap equals the selected count")
				plugin := &chatpipeline.PluginFilterTopK{}
				require.Nil(t, plugin.OnEvent(ctx, types.FILTER_TOP_K, cm,
					func() *chatpipeline.PluginError { return nil }))
				restore()
				if list == "merged" {
					require.ElementsMatch(t, want, order(cm.MergeResult))
				} else {
					require.ElementsMatch(t, want, order(cm.RerankResult))
				}
				require.Equal(t, topK, cm.RerankTopK, "restore the caller's cap without resurrecting discarded rows")
				require.Equal(t, 0.95, other.Score, "retrieval must not falsify relevance scores")
				require.Equal(t, 0.9, second.Score)
				require.Equal(t, 0.8, named.Score)
			})
		}
	}
}

func TestProductSelectionKeepsEmptyResultsAndNativeSearchFallbackBounded(t *testing.T) {
	for _, hasSearch := range []bool{false, true} {
		ctx, resolver, cm := answerTurn(t, retrievalReader{}, "乙保险悦享版")
		cm.RerankTopK = 1
		if hasSearch {
			cm.SearchResult = []*types.SearchResult{passage("one", "k1"), passage("two", "k2")}
		}
		restore := chatsource.RetrievalScope(ctx, resolver, types.FILTER_TOP_K, cm)
		require.Equal(t, 1, cm.RerankTopK, "empty merge/rerank must not turn the fallback cap into unbounded zero")
		plugin := &chatpipeline.PluginFilterTopK{}
		require.Nil(t, plugin.OnEvent(ctx, types.FILTER_TOP_K, cm, func() *chatpipeline.PluginError { return nil }))
		restore()
		require.Empty(t, cm.MergeResult)
		require.Empty(t, cm.RerankResult)
		if hasSearch {
			require.Len(t, cm.SearchResult, 1)
		}
	}
}
