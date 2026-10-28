// QA2c acceptance (protected, written by Claude): when a quick answer names products, another
// product's near-identical passage must not displace the named product's own copy in the native
// merge's overlap removal (Spec docs/design/slices/QA2c-邻段补全与q22定位.md §3, q22 of #398).
// Each case runs RetrievalScope, the real native CHUNK_MERGE plugin and the restore, as the
// quick-answer pipeline does; without repositories the plugin expands nothing. RED until QA2c.
package chatsource_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	chatpipeline "github.com/Tencent/WeKnora/internal/application/service/chat_pipeline"
	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

// clause is a standard definition that several products' terms carry word for word.
const clause = "第五十七条 双耳失聪：指因疾病或意外伤害导致双耳听力永久不可逆性丧失。" +
	"被保险人在0至3周岁期间发生的双耳失聪，本公司不承担保险责任。"

func textPassage(id, knowledgeID string, index int, score float64, content string) *types.SearchResult {
	row := scored(id, "raw-1", knowledgeID, score)
	row.ChunkIndex, row.Content, row.ChunkType = index, content, string(types.ChunkTypeText)
	row.KnowledgeTitle = "保险条款.pdf"
	return row
}

// merge runs the scope, the native merge plugin and the restore over cm.RerankResult.
func merge(ctx context.Context, t *testing.T, r *chatsource.Resolver, cm *types.ChatManage) []string {
	t.Helper()
	restore := chatsource.RetrievalScope(ctx, r, types.CHUNK_MERGE, cm)
	plugin := &chatpipeline.PluginMerge{}
	require.Nil(t, plugin.OnEvent(ctx, types.CHUNK_MERGE, cm, func() *chatpipeline.PluginError { return nil }))
	restore()
	return order(cm.MergeResult)
}

// q22Candidates: k1 carries the clause inside a longer passage that ranks higher; k2's own copy is
// shorter. k2 also has an unrelated passage, so the merge result is never empty.
func q22Candidates() []*types.SearchResult {
	return []*types.SearchResult{
		textPassage("k1-copy", "k1", 54, 0.67, clause+"第五十八条 语言能力丧失：指因疾病或意外伤害导致完全丧失语言能力。"),
		textPassage("k2-other", "k2", 3, 0.62, "本合同的等待期为九十日，自本合同生效之日起计算。"),
		textPassage("k2-own", "k2", 40, 0.60, clause),
	}
}

func TestANamedProductsOwnPassageSurvivesAnotherProductsNearDuplicate(t *testing.T) {
	s1 := attributed("rel-1", map[string][]string{"A0": {"k2"}, "B1": {"k1"}})
	ctx, r, cm, _, _ := attributionTurn(t, s1, release.Release{}, false, "A0保险的双耳失聪有什么限制")
	cm.RerankResult = q22Candidates()
	require.ElementsMatch(t, []string{"k2-own", "k2-other"}, merge(ctx, t, r, cm),
		"B1's copy never enters the merge, so it cannot displace A0's own")
	require.ElementsMatch(t, []string{"k2-own", "k2-other"}, topK(ctx, t, r, cm, 5))
}

func TestWithoutANamedProductTheNativeMergeIsUnchanged(t *testing.T) {
	s1 := attributed("rel-1", map[string][]string{"A0": {"k2"}, "B1": {"k1"}})
	ctx, r, cm, _, _ := attributionTurn(t, s1, release.Release{}, false, "双耳失聪有什么限制")
	cm.RerankResult = q22Candidates()
	require.ElementsMatch(t, []string{"k1-copy", "k2-other"}, merge(ctx, t, r, cm),
		"the native overlap removal keeps the higher-scored copy")
}

func TestAnUnreadableAttributionMergesOnlyTheNamedProductsOwnPassages(t *testing.T) {
	// k1 belongs to no product: it may fill while attribution is readable, never when it is not.
	s1 := attributed("rel-1", map[string][]string{"A0": {"k2"}})
	ctx, r, cm, reads, failFrom := attributionTurn(t, s1, release.Release{}, false, "A0保险的双耳失聪有什么限制")
	// Recognition (the next read) succeeds; the attribution read after it fails.
	*failFrom = *reads + 2
	cm.RerankResult = q22Candidates()
	require.ElementsMatch(t, []string{"k2-own", "k2-other"}, merge(ctx, t, r, cm))
}

func TestAnEmptiedRerankListDoesNotLetTheSearchFallbackReturnOtherProducts(t *testing.T) {
	s1 := attributed("rel-1", map[string][]string{"A0": {"k2"}, "B1": {"k1"}})
	ctx, r, cm, _, _ := attributionTurn(t, s1, release.Release{}, false, "A0保险的双耳失聪有什么限制")
	candidates := q22Candidates()
	// Only B1's passage was reranked; the native merge then falls back to the search list.
	cm.RerankResult = []*types.SearchResult{candidates[0]}
	cm.SearchResult = []*types.SearchResult{
		textPassage("k1-copy", "k1", 54, 0.67, candidates[0].Content), textPassage("k2-own", "k2", 40, 0.60, clause),
	}
	require.Equal(t, []string{"k2-own"}, merge(ctx, t, r, cm))
}
