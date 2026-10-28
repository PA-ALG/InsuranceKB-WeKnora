// QA2b acceptance (protected, written by Claude): when a quick question names products, the global
// fill after the named products' passages skips passages whose material the release attributes
// only to other products, and keeps fewer than k rather than pad with them (Spec
// docs/design/slices/QA2b-共用名称与只用本品补足.md §2). Fixture: product_retrieval_test.go — 甲 owns
// k1, 乙 owns k2, material "other" belongs to no product. Shape of the 2026-10-28 recheck q23.
package chatsource_test

import (
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/types"
)

func fillRanked() []*types.SearchResult {
	return []*types.SearchResult{
		passage("r1", "k1"), passage("r2", "k1"), passage("x", "other"), passage("r4", "k2"), passage("r5", "k2"),
	}
}

func TestTheFillSkipsPassagesOfOtherProducts(t *testing.T) {
	ctx, r, cm := answerTurn(t, retrievalReader{}, "乙保险悦享版的等待期多久")
	cm.RerankTopK = 3
	cm.MergeResult, cm.RerankResult = fillRanked(), fillRanked()
	restore := chatsource.RetrievalScope(ctx, r, types.FILTER_TOP_K, cm)
	require.Equal(t, []string{"r4", "r5", "x"}, order(cm.MergeResult), "甲's k1 passages never fill 乙's answer")
	require.Equal(t, []string{"r4", "r5", "x"}, order(cm.RerankResult))
	restore()
	require.Equal(t, 3, cm.RerankTopK)
}

func TestTheFillKeepsFewerThanKRatherThanBorrow(t *testing.T) {
	ctx, r, cm := answerTurn(t, retrievalReader{}, "乙保险悦享版的等待期多久")
	cm.RerankTopK = 5
	cm.MergeResult = fillRanked()
	chatsource.RetrievalScope(ctx, r, types.FILTER_TOP_K, cm)()
	require.Equal(t, []string{"r4", "r5", "x"}, order(cm.MergeResult))
}

func TestTheSearchListIsSelectedWhenTheNativeStageWouldUseIt(t *testing.T) {
	// With merged and reranked lists empty, the native top-k cuts the search list instead.
	ctx, r, cm := answerTurn(t, retrievalReader{}, "乙保险悦享版的等待期多久")
	cm.RerankTopK = 3
	cm.SearchResult = []*types.SearchResult{passage("r1", "k1"), passage("x", "other"), passage("r4", "k2")}
	restore := chatsource.RetrievalScope(ctx, r, types.FILTER_TOP_K, cm)
	require.Equal(t, []string{"r4", "x"}, order(cm.SearchResult))
	require.GreaterOrEqual(t, cm.RerankTopK, len(cm.SearchResult), "the native cut keeps the selection")
	restore()
	require.Equal(t, 3, cm.RerankTopK)
}
