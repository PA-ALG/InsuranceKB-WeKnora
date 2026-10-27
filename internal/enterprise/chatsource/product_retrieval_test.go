// QA2 acceptance (protected, written by Claude): a quick answer whose question names products also
// searches each named product's own materials, keeps every reranked candidate, and puts the named
// products' passages first in turn before the usual top-k cut (Spec
// docs/design/slices/QA2-按产品检索与字段匹配.md §2). Synthetic data in the shape of #286 q22: the
// named product's own clause loses the global ranking to another product's. RED until QA2.
package chatsource_test

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

const (
	plainProduct = "甲保险（经典版）"
	namedProduct = "乙保险（悦享版）"
)

// retrievalReader serves s1/rel-1: the classic product cites k1 and k3 (pinned, since reparsed, so
// not searchable this turn), the named product k2 only.
type retrievalReader struct{ err error }

func (r retrievalReader) ReleaseByID(
	_ context.Context, tenantID uint64, spaceID, releaseID string,
) (release.Release, error) {
	if r.err != nil {
		return release.Release{}, r.err
	}
	if tenantID != tenant || spaceID != "s1" || releaseID != "rel-1" {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	claim := func(subject, predicate, knowledgeID string) release.Member {
		return publishedMember("claim", subject+"/"+predicate, map[string]any{
			"subject_ref": subject, "predicate": predicate, "state": "present", "value": "30日",
			"origin": "SOURCE_SUPPORTED", "review": map[string]any{"mode": "machine"},
			"evidence": []map[string]any{{
				"quote": "等待期", "locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": 1},
				"source_ref": "source:v1:" + knowledgeID + ":1:" + strings.Repeat("ab", 32),
			}},
		})
	}
	entity := func(id, label, name string) release.Member {
		return publishedMember("entity", "entity/"+id, map[string]any{
			"entity_id": id, "entity_type": "product", "names": []string{name},
			"classification_labels": []string{label},
		})
	}
	return release.Release{ID: "rel-1", Epoch: 1, Members: []release.Member{
		publishedMember("navigation", "navigation/enterprise", map[string]any{
			"navigation_id": "enterprise", "navigation_version": "v1",
			"domains": []map[string]any{{
				"domain_key": "product", "display_name": "产品", "entity_types": []string{"product"},
				"groups": []map[string]any{
					{"group_key": "a", "display_name": "a", "classification_labels": []string{"a"}},
					{"group_key": "b", "display_name": "b", "classification_labels": []string{"b"}},
				},
			}},
		}),
		entity("P1", "a", plainProduct),
		entity("P2", "b", namedProduct),
		claim("P1", "waiting_period", "k1"),
		claim("P1", "cooling_off_period", "k3"),
		claim("P2", "waiting_period", "k2"),
	}}, nil
}

// answerTurn resolves a quick answer over wiki-1 with automatic raw k1, k2 and the given question.
func answerTurn(t *testing.T, reader retrievalReader, question string) (context.Context, *chatsource.Resolver,
	*types.ChatManage,
) {
	t.Helper()
	s, h, p, a := fixture()
	d := answerDirectory{s, map[string][2]string{"s1": {"raw-1", "wiki-1"}}}
	r := chatsource.NewResolver(d, h, p, a).WithPublished(knowledge.NewService(reader))
	ctx, targets, err := chatsource.ResolveAnswer(
		context.Background(), r, tenant, types.SearchTargets{kb("wiki-1")}, allowRaw)
	require.NoError(t, err)
	require.True(t, chatsource.IsEnterpriseAnswer(ctx))
	cm := &types.ChatManage{}
	cm.Query, cm.RewriteQuery, cm.SearchTargets, cm.RerankTopK = "原问题", question, targets, 2
	return ctx, r, cm
}

func passage(id, knowledgeID string) *types.SearchResult {
	return &types.SearchResult{ID: id, KnowledgeID: knowledgeID, KnowledgeBaseID: "raw-1"}
}

func order(results []*types.SearchResult) []string {
	out := []string{}
	for _, result := range results {
		out = append(out, result.ID)
	}
	return out
}

// Quick answers search through CHUNK_SEARCH_PARALLEL, which clones the targets; CHUNK_SEARCH is the
// same stage when it runs on its own.
func TestSearchAddsOneTargetPerNamedProductForTheStageOnly(t *testing.T) {
	for _, event := range []types.EventType{types.CHUNK_SEARCH_PARALLEL, types.CHUNK_SEARCH} {
		ctx, r, cm := answerTurn(t, retrievalReader{}, "甲保险经典版和乙保险悦享版的等待期分别多久")
		original := append(types.SearchTargets(nil), cm.SearchTargets...)

		restore := chatsource.RetrievalScope(ctx, r, event, cm)
		require.Len(t, cm.SearchTargets, len(original)+2, event)
		require.Equal(t, original, cm.SearchTargets[:len(original)], "the global search is unchanged")
		for i, want := range [][]string{{"k1"}, {"k2"}} {
			target := cm.SearchTargets[len(original)+i]
			require.Equal(t, types.SearchTargetTypeKnowledge, target.Type)
			require.Equal(t, "raw-1", target.KnowledgeBaseID)
			require.Equal(t, tenant, target.TenantID)
			require.Equal(t, want, target.KnowledgeIDs, "navigation order, the product's pinned materials only")
		}
		restore()
		require.Equal(t, original, cm.SearchTargets, event)
	}
}

func TestRerankKeepsEveryCandidateWhileProductsAreNamed(t *testing.T) {
	ctx, r, cm := answerTurn(t, retrievalReader{}, "乙保险悦享版的等待期多久")
	cm.SearchResult = []*types.SearchResult{
		passage("a", "k1"), passage("b", "k1"), passage("c", "k1"), passage("d", "k2"), passage("e", "k2"),
	}
	restore := chatsource.RetrievalScope(ctx, r, types.CHUNK_RERANK, cm)
	require.GreaterOrEqual(t, cm.RerankTopK, len(cm.SearchResult), "nothing above the threshold is cut here")
	restore()
	require.Equal(t, 2, cm.RerankTopK)
}

func TestTopKTakesTheNamedProductsPassagesFirstInTurn(t *testing.T) {
	ranked := func() []*types.SearchResult {
		return []*types.SearchResult{
			passage("r1", "k1"), passage("r2", "k1"), passage("x", "other"), passage("r4", "k2"), passage("r5", "k2"),
		}
	}
	ctx, r, cm := answerTurn(t, retrievalReader{}, "乙保险悦享版的等待期多久")
	cm.MergeResult, cm.RerankResult = ranked(), ranked()
	restore := chatsource.RetrievalScope(ctx, r, types.FILTER_TOP_K, cm)
	require.Equal(t, []string{"r4", "r5", "r1", "r2", "x"}, order(cm.MergeResult))
	require.Equal(t, []string{"r4", "r5", "r1", "r2", "x"}, order(cm.RerankResult))
	restore()

	ctx, r, cm = answerTurn(t, retrievalReader{}, "甲保险经典版和乙保险悦享版的等待期分别多久")
	cm.MergeResult = ranked()
	chatsource.RetrievalScope(ctx, r, types.FILTER_TOP_K, cm)()
	require.Equal(t, []string{"r1", "r4", "r2", "r5", "x"}, order(cm.MergeResult),
		"one passage per named product per round, then the rest in their ranked order")
}

func TestRetrievalScopeChangesNothingWithoutANamedProduct(t *testing.T) {
	check := func(name string, ctx context.Context, r *chatsource.Resolver, cm *types.ChatManage) {
		t.Helper()
		targets := append(types.SearchTargets(nil), cm.SearchTargets...)
		cm.SearchResult = []*types.SearchResult{passage("a", "k1"), passage("b", "k2"), passage("c", "k1")}
		cm.MergeResult = []*types.SearchResult{passage("a", "k1"), passage("b", "k2")}
		for _, event := range []types.EventType{
			types.CHUNK_SEARCH_PARALLEL, types.CHUNK_SEARCH, types.CHUNK_RERANK, types.FILTER_TOP_K,
		} {
			restore := chatsource.RetrievalScope(ctx, r, event, cm)
			require.Equal(t, targets, cm.SearchTargets, name)
			require.Equal(t, 2, cm.RerankTopK, name)
			require.Equal(t, []string{"a", "b"}, order(cm.MergeResult), name)
			restore()
		}
	}
	ctx, r, cm := answerTurn(t, retrievalReader{}, "等待期一般多久")
	check("no product named", ctx, r, cm)

	ctx, r, cm = answerTurn(t, retrievalReader{err: errors.New("release unreadable")}, "乙保险悦享版的等待期多久")
	check("a failed product lookup keeps the plain retrieval", ctx, r, cm)

	s, h, p, a := fixture()
	agent := chatsource.NewResolver(s, h, p, a).WithPublished(knowledge.NewService(retrievalReader{}))
	turn, err := agent.Resolve(context.Background(), tenant, types.SearchTargets{kb("wiki-1"), kb("raw-1")})
	require.NoError(t, err)
	require.NotEmpty(t, turn.WikiSpaces, "the same release and raw materials as a quick answer")
	require.NotEmpty(t, turn.RawKnowledge)
	agentCtx := chatsource.WithTurn(context.Background(), turn, tenant)
	require.False(t, chatsource.IsEnterpriseAnswer(agentCtx))
	plain := &types.ChatManage{}
	plain.RewriteQuery, plain.SearchTargets, plain.RerankTopK = "乙保险悦享版的等待期多久", turn.Targets, 2
	check("not a quick answer", agentCtx, agent, plain)
}
