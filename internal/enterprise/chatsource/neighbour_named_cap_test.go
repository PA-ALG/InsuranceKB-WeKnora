// QA2c acceptance (protected, written by Claude, review R1 on #417): the cap of three named products
// limits extra searches and turn-taking only (QA2b §2a.2); every named product's selected passage
// may be completed (Spec docs/design/slices/QA2c-邻段补全与q22定位.md §2.1). RED until the fix.
package chatsource_test

import (
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

func TestAPassageOfAFourthNamedProductIsCompleted(t *testing.T) {
	for name, products := range map[string]map[string][]string{
		// D3 is named fourth, after A0, B1 and C2 take the three extra-search slots on k1.
		"fourth named": {"A0": {"k1"}, "B1": {"k1"}, "C2": {"k1"}, "D3": {"k2"}},
		// Control: D3 among the first three.
		"third named": {"A0": {"k1"}, "B1": {"k1"}, "D3": {"k2"}},
	} {
		t.Run(name, func(t *testing.T) {
			store := newChunkStore()
			store.chain("k2", 1, 40, "发生约定事故时", "按保险金额给付。", "第十条 保险期间。")
			question := "A0保险、B1保险和D3保险发生约定事故时怎么给付"
			if len(products) == 4 {
				question = "A0保险、B1保险、C2保险和D3保险发生约定事故时怎么给付"
			}
			ctx, r, cm, _, _ := attributionTurn(t, attributed("rel-1", products), release.Release{}, false, question)
			cm.MergeResult = []*types.SearchResult{store.selected("k2-40", 0.9)}
			require.Equal(t, []string{"k2-40", "k2-41"}, topK(ctx, t, r.WithChunks(store), cm, 1))

			// Both are delivered as D3's raw passages.
			require.NoError(t, chatsource.FilterPipeline(ctx, r, store, cm))
			raw := []*types.SearchResult{}
			for _, row := range cm.MergeResult {
				if row.KnowledgeBaseID == "raw-1" {
					raw = append(raw, row)
				}
			}
			require.Equal(t, []string{"k2-40", "k2-41"}, order(raw))
			require.Equal(t, raw[0].Metadata["entity_names"], raw[1].Metadata["entity_names"])
		})
	}
}
