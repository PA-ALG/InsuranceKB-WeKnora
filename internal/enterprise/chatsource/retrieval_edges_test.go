package chatsource_test

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type materialReader func(context.Context, uint64, string, string) (release.Release, error)

func (f materialReader) ReleaseByID(ctx context.Context, tenant uint64, space, id string) (release.Release, error) {
	return f(ctx, tenant, space, id)
}

func materialRelease(id string, ids, materials []string) release.Release {
	r := release.Release{ID: id}
	for i, entityID := range ids {
		r.Members = append(r.Members, publishedMember("entity", "entity/"+entityID, map[string]any{
			"entity_id": entityID, "entity_type": "product", "names": []string{"Company " + entityID},
		}))
		if materials[i] != "" {
			r.Members = append(r.Members, publishedMember("claim", entityID+"/field", map[string]any{
				"subject_ref": entityID, "predicate": "field", "state": "present", "value": "test",
				"evidence": []map[string]any{{
					"source_ref": "source:v1:" + materials[i] + ":1:" + strings.Repeat("ab", 32),
				}},
			}))
		}
	}
	return r
}

func TestProductRetrievalCapsOnlySearchableProductsInReleaseOrder(t *testing.T) {
	ctx, resolver, cm := answerTurn(t, retrievalReader{}, "D3 C2 B1 A0 Empty")
	turn, _ := chatsource.TurnFromContext(ctx)
	turn.RawKnowledge = map[string]string{"doc-a": "s1", "doc-b": "s1", "doc-c": "s1", "doc-d": "s1"}
	ctx = chatsource.WithTurn(ctx, turn, tenant)
	resolver = resolver.WithPublished(knowledge.NewService(materialReader(
		func(_ context.Context, gotTenant uint64, space, id string) (release.Release, error) {
			require.Equal(t, tenant, gotTenant)
			require.Equal(t, "s1", space)
			require.Equal(t, "rel-1", id)
			return materialRelease(id, []string{"Empty", "A0", "B1", "C2", "D3"},
				[]string{"outside-pins", "doc-a", "doc-b", "doc-c", "doc-d"}), nil
		})))
	original := cm.SearchTargets
	defer chatsource.RetrievalScope(ctx, resolver, types.CHUNK_SEARCH_PARALLEL, cm)()
	require.Equal(t, 3, chatsource.MaxNamedProducts)
	require.Len(t, cm.SearchTargets, len(original)+3)
	for i, doc := range []string{"doc-a", "doc-b", "doc-c"} {
		require.Equal(t, []string{doc}, cm.SearchTargets[len(original)+i].KnowledgeIDs)
	}
}

func TestProductRetrievalUsesPinnedSpaceAndRewriteWithoutChangingTheTurn(t *testing.T) {
	ctx, resolver, cm := answerTurn(t, retrievalReader{}, "A0")
	turn, _ := chatsource.TurnFromContext(ctx)
	turn.Releases["s2"] = "old-second"
	turn.RawKnowledge["foreign"] = "s2"
	turn.RawKnowledge["k9"] = "s2"
	ctx = chatsource.WithTurn(ctx, turn, tenant)
	cm.Query = "B1"
	cm.SearchTargets = append(cm.SearchTargets, kb("raw-2"))
	resolver = resolver.WithPublished(knowledge.NewService(materialReader(
		func(_ context.Context, gotTenant uint64, space, id string) (release.Release, error) {
			require.Equal(t, tenant, gotTenant)
			if space == "s1" {
				require.Equal(t, "rel-1", id)
				return materialRelease(id, []string{"A0", "B1"}, []string{"foreign", "k2"}), nil
			}
			require.Equal(t, "s2", space)
			require.Equal(t, "old-second", id)
			return materialRelease(id, []string{"A0"}, []string{"k9"}), nil
		})))
	original := cm.SearchTargets
	restore := chatsource.RetrievalScope(ctx, resolver, types.CHUNK_SEARCH, cm)
	require.Len(t, cm.SearchTargets, len(original)+1)
	last := cm.SearchTargets[len(original)]
	require.Equal(t, "raw-2", last.KnowledgeBaseID)
	require.Equal(t, []string{"k9"}, last.KnowledgeIDs, "s1 must not take a material fixed for s2")
	restore()
	require.Same(t, original[0], cm.SearchTargets[0])
	cm.RewriteQuery = "  "
	restore = chatsource.RetrievalScope(ctx, resolver, types.CHUNK_SEARCH, cm)
	require.Equal(t, []string{"k2"}, cm.SearchTargets[len(original)].KnowledgeIDs, "empty rewrite uses Query")
	restore()
	require.Equal(t, original, cm.SearchTargets)
	require.Equal(t, "s2", turn.RawKnowledge["foreign"])
}

func TestProductRoundRobinKeepsSharedChunksOnceAndGlobalTailStable(t *testing.T) {
	ctx, resolver, cm := answerTurn(t, retrievalReader{}, "A0 B1")
	resolver = resolver.WithPublished(knowledge.NewService(materialReader(
		func(_ context.Context, _ uint64, _, id string) (release.Release, error) {
			return materialRelease(id, []string{"A0", "B1"}, []string{"k1", "k1"}), nil
		})))
	wrongKB := passage("wrong-kb", "k1")
	wrongKB.KnowledgeBaseID = "ordinary"
	cm.MergeResult = []*types.SearchResult{
		passage("tail-b", "other"), passage("shared-first", "k1"), wrongKB,
		passage("tail-a", "other"), passage("shared-second", "k1"), passage("shared-first", "k1"), nil,
	}
	original := append([]*types.SearchResult(nil), cm.MergeResult...)
	chatsource.RetrievalScope(ctx, resolver, types.FILTER_TOP_K, cm)()
	require.Len(t, cm.MergeResult, 6)
	require.Equal(t, []string{"shared-first", "shared-second", "tail-b", "wrong-kb", "tail-a"},
		order(cm.MergeResult[:5]))
	require.Nil(t, cm.MergeResult[5])
	require.Equal(t, "tail-b", original[0].ID, "reordering must not mutate a shared result slice")
}

func TestProductScopeNoOpsWithoutRawOrOnFailedIdentification(t *testing.T) {
	for _, mode := range []string{"no-target", "no-pins", "foreign-tenant", "nil-resolver", "read-error", "cancelled"} {
		t.Run(mode, func(t *testing.T) {
			ctx, resolver, cm := answerTurn(t, retrievalReader{}, "乙保险悦享版")
			switch mode {
			case "no-target":
				cm.SearchTargets = types.SearchTargets{nil, kb("plain")}
			case "no-pins":
				turn, _ := chatsource.TurnFromContext(ctx)
				turn.RawKnowledge = nil
				ctx = chatsource.WithTurn(ctx, turn, tenant)
			case "foreign-tenant":
				cm.SearchTargets[0].TenantID = tenant + 1
			case "nil-resolver":
				resolver = nil
			case "read-error":
				resolver = resolver.WithPublished(knowledge.NewService(retrievalReader{err: errors.New("offline")}))
			case "cancelled":
				var cancel context.CancelFunc
				ctx, cancel = context.WithCancel(ctx)
				cancel()
			}
			original := append(types.SearchTargets(nil), cm.SearchTargets...)
			cm.RerankTopK = 1
			cm.SearchResult = []*types.SearchResult{passage("a", "k1"), passage("b", "k2")}
			cm.MergeResult = append([]*types.SearchResult(nil), cm.SearchResult...)
			for _, event := range []types.EventType{
				types.CHUNK_SEARCH, types.CHUNK_SEARCH_PARALLEL, types.CHUNK_RERANK, types.FILTER_TOP_K,
			} {
				chatsource.RetrievalScope(ctx, resolver, event, cm)()
				require.Equal(t, original, cm.SearchTargets)
				require.Equal(t, 1, cm.RerankTopK)
				require.Equal(t, []string{"a", "b"}, order(cm.MergeResult))
			}
		})
	}
}

func TestProductScopeDiscardsPartialRecognitionOnAnotherSpacesFailure(t *testing.T) {
	ctx, resolver, cm := answerTurn(t, retrievalReader{}, "A0")
	turn, _ := chatsource.TurnFromContext(ctx)
	turn.Releases["s2"], turn.RawKnowledge["k9"] = "rel-2", "s2"
	ctx = chatsource.WithTurn(ctx, turn, tenant)
	cm.SearchTargets = append(cm.SearchTargets, kb("raw-2"))
	resolver = resolver.WithPublished(knowledge.NewService(materialReader(
		func(_ context.Context, _ uint64, space, id string) (release.Release, error) {
			if space == "s2" {
				return release.Release{}, errors.New("second release unavailable")
			}
			return materialRelease(id, []string{"A0"}, []string{"k1"}), nil
		})))
	original := append(types.SearchTargets(nil), cm.SearchTargets...)
	cm.RerankTopK = 1
	cm.SearchResult = []*types.SearchResult{passage("global-first", "k2"), passage("named", "k1")}
	cm.MergeResult = append([]*types.SearchResult(nil), cm.SearchResult...)
	for _, event := range []types.EventType{
		types.CHUNK_SEARCH, types.CHUNK_SEARCH_PARALLEL, types.CHUNK_RERANK, types.FILTER_TOP_K,
	} {
		chatsource.RetrievalScope(ctx, resolver, event, cm)()
		require.Equal(t, original, cm.SearchTargets)
		require.Equal(t, 1, cm.RerankTopK)
		require.Equal(t, []string{"global-first", "named"}, order(cm.MergeResult))
	}
}
