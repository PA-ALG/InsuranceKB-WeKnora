package chatsource_test

import (
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
		t.Run(list, func(t *testing.T) {
			ctx, resolver, cm := answerTurn(t, retrievalReader{}, "乙保险悦享版的等待期多久")
			other, named := passage("other-high", "k1"), passage("named-low", "k2")
			other.Score, named.Score = 0.95, 0.8
			cm.RerankTopK = 1
			if list == "merged" {
				cm.MergeResult = []*types.SearchResult{other, named}
			} else {
				cm.RerankResult = []*types.SearchResult{other, named}
			}
			restore := chatsource.RetrievalScope(ctx, resolver, types.FILTER_TOP_K, cm)
			plugin := &chatpipeline.PluginFilterTopK{}
			require.Nil(t, plugin.OnEvent(ctx, types.FILTER_TOP_K, cm, func() *chatpipeline.PluginError { return nil }))
			restore()
			if list == "merged" {
				require.Equal(t, []string{"named-low"}, order(cm.MergeResult))
			} else {
				require.Equal(t, []string{"named-low"}, order(cm.RerankResult))
			}
			require.Equal(t, 0.95, other.Score, "retrieval must not falsify relevance scores")
			require.Equal(t, 0.8, named.Score)
		})
	}
}
