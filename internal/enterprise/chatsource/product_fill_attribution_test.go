// QA2b acceptance (protected, written by Claude, review R1–R3 on #399): the fill exclusion holds
// when the named product has no usable material this turn, covers every selected enterprise RAW
// Space independently of the extra-search cap, and fails closed when attribution cannot be read
// (Spec docs/design/slices/QA2b-共用名称与只用本品补足.md §2a). Each case runs RetrievalScope, the
// real native FILTER_TOP_K plugin and the restore, as the quick-answer pipeline does.
package chatsource_test

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	chatpipeline "github.com/Tencent/WeKnora/internal/application/service/chat_pipeline"
	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

// attributionReader serves fixed releases per "space/release"; reads numbered failFrom and later
// fail, so a test can let recognition succeed and the attribution read fail.
type attributionReader struct {
	releases map[string]release.Release
	reads    *int
	failFrom *int
}

func (r attributionReader) ReleaseByID(
	_ context.Context, tenantID uint64, spaceID, releaseID string,
) (release.Release, error) {
	*r.reads++
	if *r.failFrom > 0 && *r.reads >= *r.failFrom {
		return release.Release{}, errors.New("reader down")
	}
	out, ok := r.releases[spaceID+"/"+releaseID]
	if !ok || tenantID != tenant {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	return out, nil
}

func attributed(id string, products map[string][]string) release.Release {
	members := []release.Member{}
	for _, entityID := range sortedKeys(products) {
		members = append(members, publishedMember("entity", "entity/"+entityID, map[string]any{
			"entity_id": entityID, "entity_type": "product", "names": []string{entityID + "保险"},
			"classification_labels": []string{"a"},
		}))
		for i, knowledgeID := range products[entityID] {
			members = append(members, publishedMember("claim", entityID+"/f"+string(rune('0'+i)), map[string]any{
				"subject_ref": entityID, "predicate": "f" + string(rune('0'+i)), "state": "present", "value": "v",
				"origin": "SOURCE_SUPPORTED", "review": map[string]any{"mode": "machine"},
				"evidence": []map[string]any{{
					"quote": "q", "locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": 1},
					"source_ref": "source:v1:" + knowledgeID + ":1:" + strings.Repeat("ab", 32),
				}},
			}))
		}
	}
	return release.Release{ID: id, Epoch: 1, Members: members}
}

func sortedKeys(m map[string][]string) []string {
	out := make([]string, 0, len(m))
	for key := range m {
		out = append(out, key)
	}
	for i := 1; i < len(out); i++ {
		for j := i; j > 0 && out[j] < out[j-1]; j-- {
			out[j], out[j-1] = out[j-1], out[j]
		}
	}
	return out
}

// attributionTurn resolves a quick answer over s1 (raw-1: k1, k2 searchable, k3 reparsed) and,
// when twoSpaces, s2 (raw-2: k9). It returns the reader counters so a test can fail later reads.
func attributionTurn(
	t *testing.T, s1, s2 release.Release, twoSpaces bool, question string,
) (context.Context, *chatsource.Resolver, *types.ChatManage, *int, *int) {
	t.Helper()
	s, h, p, a := fixture()
	targets := types.SearchTargets{kb("wiki-1")}
	pairs := map[string][2]string{"s1": {"raw-1", "wiki-1"}}
	if twoSpaces {
		v := s["wiki-1"]
		v.space = "s2"
		s["wiki-2"] = v
		pairs["s2"] = [2]string{"raw-2", "wiki-2"}
		targets = append(targets, kb("wiki-2"))
	}
	reads, failFrom := 0, 0
	reader := attributionReader{
		releases: map[string]release.Release{"s1/rel-1": s1, "s2/rel-2": s2}, reads: &reads, failFrom: &failFrom,
	}
	r := chatsource.NewResolver(answerDirectory{s, pairs}, h, p, a).WithPublished(knowledge.NewService(reader))
	ctx, resolved, err := chatsource.ResolveAnswer(context.Background(), r, tenant, targets, allowRaw)
	require.NoError(t, err)
	cm := &types.ChatManage{}
	cm.Query, cm.RewriteQuery, cm.SearchTargets = question, question, resolved
	return ctx, r, cm, &reads, &failFrom
}

func scored(id, kbID, knowledgeID string, score float64) *types.SearchResult {
	return &types.SearchResult{ID: id, KnowledgeID: knowledgeID, KnowledgeBaseID: kbID, Score: score}
}

// topK runs the scope, the native plugin and the restore over cm.MergeResult.
func topK(ctx context.Context, t *testing.T, r *chatsource.Resolver, cm *types.ChatManage, k int) []string {
	t.Helper()
	cm.RerankTopK = k
	restore := chatsource.RetrievalScope(ctx, r, types.FILTER_TOP_K, cm)
	plugin := &chatpipeline.PluginFilterTopK{}
	require.Nil(t, plugin.OnEvent(ctx, types.FILTER_TOP_K, cm, func() *chatpipeline.PluginError { return nil }))
	restore()
	require.Equal(t, k, cm.RerankTopK)
	return order(cm.MergeResult)
}

func TestANamedProductWithoutUsableMaterialStillExcludesOtherProducts(t *testing.T) {
	for name, a0 := range map[string][]string{"reparsed only": {"k3"}, "no evidence": nil} {
		t.Run(name, func(t *testing.T) {
			// A0 is named; its only material (k3) is not searchable this turn, or it has none.
			// B1 owns k1; k2 belongs to no product.
			s1 := attributed("rel-1", map[string][]string{"A0": a0, "B1": {"k1"}})
			ctx, r, cm, _, _ := attributionTurn(t, s1, release.Release{}, false, "A0保险的等待期多久")
			cm.MergeResult = []*types.SearchResult{
				scored("b1", "raw-1", "k1", 0.99), scored("free", "raw-1", "k2", 0.1),
			}
			require.Equal(t, []string{"free"}, topK(ctx, t, r, cm, 1), "B1's passage never fills A0's answer")
		})
	}
}

func TestOtherProductsOfEverySelectedSpaceAreExcluded(t *testing.T) {
	s2 := attributed("rel-2", map[string][]string{"C2": {"k9"}})
	merged := func() []*types.SearchResult {
		return []*types.SearchResult{
			scored("c2", "raw-2", "k9", 0.99), scored("free", "raw-1", "k1", 0.5), scored("a0", "raw-1", "k2", 0.1),
		}
	}
	// s1 names only A0; s2 names nothing, but C2 owns k9 there.
	s1 := attributed("rel-1", map[string][]string{"A0": {"k2"}})
	ctx, r, cm, _, _ := attributionTurn(t, s1, s2, true, "A0保险的等待期多久")
	cm.MergeResult = merged()
	require.ElementsMatch(t, []string{"a0", "free"}, topK(ctx, t, r, cm, 3))

	// Four named products in s1 exceed the extra-search cap of three; s2 is still checked.
	s1 = attributed("rel-1", map[string][]string{"A0": {"k2"}, "A1": {"k2"}, "A2": {"k2"}, "A3": {"k2"}})
	ctx, r, cm, _, _ = attributionTurn(t, s1, s2, true, "A0保险、A1保险、A2保险和A3保险的等待期")
	cm.MergeResult = merged()
	require.ElementsMatch(t, []string{"a0", "free"}, topK(ctx, t, r, cm, 3))
}

func TestAnUnreadableAttributionKeepsOnlyTheNamedProductsOwnPassages(t *testing.T) {
	s1 := attributed("rel-1", map[string][]string{"A0": {"k2"}, "B1": {"k1"}})
	ctx, r, cm, reads, failFrom := attributionTurn(t, s1, release.Release{}, false, "A0保险的等待期多久")
	// Recognition (the next read) succeeds; the attribution read after it fails.
	*failFrom = *reads + 2
	cm.MergeResult = []*types.SearchResult{scored("b1", "raw-1", "k1", 0.99), scored("a0", "raw-1", "k2", 0.1)}
	require.Equal(t, []string{"a0"}, topK(ctx, t, r, cm, 2), "unknown attribution never fills")
}
