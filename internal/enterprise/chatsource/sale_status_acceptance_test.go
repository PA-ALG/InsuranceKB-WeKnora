// PV-5 acceptance (protected, written by Claude): a sales quick answer puts the named products' sale
// status first, as its own reference without an evidence index; raw passages name their products
// with version labels; an unnamed sales comparison drops passages of materials only products not
// on sale cite (Spec docs/design/slices/PV-5-问答销售状态与产品识别.md §1.2, §2). RED until PV-5.
package chatsource_test

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

const (
	stoppedProduct = "丁护理保险"
	stoppedLabel   = "丁护理保险（停售；销售期 2023-01-01 至 2024-09-01）"
)

// saleReader serves s1/rel-1: P stopped selling before its year version Q began (Q supersedes P);
// U has no version data; F starts selling next year. k1 is cited by P only, k2 by Q, k4 by P and
// Q, k5 by U and k6 by F.
type saleReader struct{}

func (saleReader) ReleaseByID(_ context.Context, tenantID uint64, spaceID, releaseID string) (release.Release, error) {
	if tenantID != tenant || spaceID != "s1" || releaseID != "rel-1" {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	claim := func(subject, predicate, knowledgeID string) release.Member {
		return publishedMember("claim", subject+"/"+predicate, map[string]any{
			"subject_ref": subject, "predicate": predicate, "state": "present", "value": "30日",
			"origin": "SOURCE_SUPPORTED", "review": map[string]any{"mode": "machine"},
			"evidence": []map[string]any{{
				"quote": "等待期30日", "locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": 1},
				"source_ref": "source:v1:" + knowledgeID + ":1:" + strings.Repeat("ef", 32),
			}},
		})
	}
	entity := func(id, name string, lifecycle map[string]any) release.Member {
		payload := map[string]any{
			"entity_id": id, "entity_type": "product", "names": []string{name},
			"classification_labels": []string{"a"},
		}
		if lifecycle != nil {
			payload["lifecycle"] = lifecycle
		}
		return publishedMember("entity", "entity/"+id, payload)
	}
	return release.Release{ID: "rel-1", Epoch: 1, Members: []release.Member{
		publishedMember("navigation", "navigation/enterprise", map[string]any{
			"navigation_id": "enterprise", "navigation_version": "v1",
			"overview_fields":  []string{"waiting_period"},
			"question_intents": map[string]any{"sales": [][]string{{"能买"}, {"在售"}}, "service": [][]string{{"理赔"}}},
			"domains": []map[string]any{{
				"domain_key": "product", "display_name": "产品", "entity_types": []string{"product"},
				"groups": []map[string]any{
					{"group_key": "a", "display_name": "a", "classification_labels": []string{"a"}},
				},
			}},
		}),
		publishedMember("presentation_profile", "presentation/a", map[string]any{
			"profile_id": "a", "display_name": "a", "classification_labels": []string{"a"},
			"sections": []map[string]any{{"section_key": "main", "display_name": "main", "fields": []map[string]any{
				{"field_key": "waiting_period", "short_title": "等待期"},
			}}},
		}),
		entity("P", stoppedProduct, map[string]any{
			"sale_start": "2023-01-01", "sale_end": "2024-09-01", "source_status": "discontinued",
		}),
		entity("Q", "丁护理（2026）保险", map[string]any{
			"sale_start": "2025-10-22", "source_status": "on_sale", "basis_date": "2026-10-20",
		}),
		entity("U", "戊医疗保险", nil),
		entity("F", "己医疗保险", map[string]any{"sale_start": "2027-01-01", "source_status": "on_sale"}),
		publishedMember("relation", "relation/supersedes/Q/P", map[string]any{
			"relation_id": "supersedes/Q/P", "predicate": "supersedes", "from": "Q", "to": "P",
		}),
		claim("P", "waiting_period", "k1"),
		claim("P", "cooling_off_period", "k4"),
		claim("Q", "waiting_period", "k2"),
		claim("Q", "cooling_off_period", "k4"),
		claim("U", "waiting_period", "k5"),
		claim("F", "waiting_period", "k6"),
	}}, nil
}

// The evaluation day is 2026-11-01 in the business time zone.
func saleService() *knowledge.Service {
	return knowledge.NewService(saleReader{}).
		WithClock(func() time.Time { return time.Date(2026, 11, 1, 2, 0, 0, 0, time.UTC) })
}

// saleTurn resolves a quick answer over wiki-1 with automatic raw k1, k2, k4, k5 and k6.
func saleTurn(t *testing.T, question string) (context.Context, *chatsource.Resolver, *types.ChatManage) {
	t.Helper()
	s, h, p, a := fixture()
	for _, id := range []string{"k4", "k5", "k6"} {
		p.byRelease["s1/rel-1"] = append(p.byRelease["s1/rel-1"], chatsource.Pin{KnowledgeID: id, ParseAttempt: 1})
		a.current[id] = 1
	}
	d := answerDirectory{s, map[string][2]string{"s1": {"raw-1", "wiki-1"}}}
	r := chatsource.NewResolver(d, h, p, a).WithPublished(saleService())
	ctx, targets, err := chatsource.ResolveAnswer(
		context.Background(), r, tenant, types.SearchTargets{kb("wiki-1")}, allowRaw)
	require.NoError(t, err)
	cm := &types.ChatManage{}
	cm.Query, cm.RewriteQuery, cm.SearchTargets, cm.RerankTopK = "原问题", question, targets, 10
	return ctx, r, cm
}

func TestSalesAnswersPutTheNamedProductsSaleStatusFirst(t *testing.T) {
	ctx, r, cm := saleTurn(t, "丁护理保险现在还能买吗")
	require.NoError(t, chatsource.FilterPipeline(ctx, r, noChunks{t}, cm))
	require.Equal(t, []string{"release:rel-1:entity/P", "release:rel-1:P/waiting_period"}, order(cm.MergeResult))
	status := cm.MergeResult[0]
	require.Equal(t, map[string]string{
		"source_tier": "release", "space_id": "s1", "release_id": "rel-1",
		"logical_slug": "entity/P", "knowledge_class": "sale_status",
	}, status.Metadata, "a sale status has no evidence to open")
	require.Equal(t, stoppedProduct+" · 销售状态", status.KnowledgeTitle)
	content := stoppedProduct + " · 销售状态：停售；销售期：2023-01-01 至 2024-09-01；后续版本：Q（丁护理（2026）保险）"
	require.Equal(t, content, status.Content)
	require.Equal(t, "销售状态（已发布版本的产品登记数据）\n"+content, chatsource.AnswerPassage(ctx, status, status.Content))
	require.Equal(t, "已发布知识（审核过）\n正文", chatsource.AnswerPassage(ctx, cm.MergeResult[1], "正文"))

	ctx, r, cm = saleTurn(t, "戊医疗保险能买吗")
	require.NoError(t, chatsource.FilterPipeline(ctx, r, noChunks{t}, cm))
	require.Equal(t, "release:rel-1:entity/U", cm.MergeResult[0].ID)
	require.Equal(t, "戊医疗保险 · 销售状态：未知", cm.MergeResult[0].Content)

	ctx, r, cm = saleTurn(t, "丁护理保险的等待期")
	require.NoError(t, chatsource.FilterPipeline(ctx, r, noChunks{t}, cm))
	require.Equal(t, []string{"release:rel-1:P/waiting_period"}, order(cm.MergeResult), "not a sales question")
}

func TestRawPassagesNameTheirProductsWithVersionLabels(t *testing.T) {
	ctx, _, _ := saleTurn(t, "等待期多久")
	turn, ok := chatsource.TurnFromContext(ctx)
	require.True(t, ok)
	require.Equal(t, []string{stoppedLabel}, turn.RawEntities["k1"])
	require.Equal(t, []string{"戊医疗保险"}, turn.RawEntities["k5"], "no version data: the name stays")
	passage := rawResult("c1", "k1", "保险条款.pdf")
	turn.Label([]*types.SearchResult{passage})
	require.Equal(t, stoppedLabel+" · 保险条款.pdf", passage.KnowledgeTitle)
	require.Equal(t, "原文检索（未经编译审核）｜所属产品："+stoppedLabel+"\n正文",
		chatsource.AnswerPassage(ctx, passage, "正文"))
}

func salePassages() []*types.SearchResult {
	return []*types.SearchResult{
		passage("p1", "k1"), passage("q2", "k2"), passage("pq4", "k4"), passage("u5", "k5"),
		passage("f6", "k6"), passage("x", "other"),
	}
}

func TestUnnamedSalesComparisonsDropPassagesOfProductsNotOnSale(t *testing.T) {
	kept := []string{"q2", "pq4", "u5", "x"}
	ctx, r, cm := saleTurn(t, "现在在售的有哪几款")
	cm.MergeResult, cm.RerankResult = salePassages(), salePassages()
	chatsource.RetrievalScope(ctx, r, types.FILTER_TOP_K, cm)()
	require.Equal(t, kept, order(cm.MergeResult))
	require.Equal(t, kept, order(cm.RerankResult))

	ctx, r, cm = saleTurn(t, "现在在售的有哪几款")
	cm.RerankResult = salePassages()
	chatsource.RetrievalScope(ctx, r, types.CHUNK_MERGE, cm)()
	require.Equal(t, kept, order(cm.RerankResult), "removed before the native merge")

	// The native stages fall back to the search list when the other lists are empty.
	ctx, r, cm = saleTurn(t, "现在在售的有哪几款")
	cm.SearchResult = salePassages()
	chatsource.RetrievalScope(ctx, r, types.FILTER_TOP_K, cm)()
	require.Equal(t, kept, order(cm.SearchResult))

	for _, question := range []string{"等待期一般多久", "丁护理保险能买吗"} {
		ctx, r, cm = saleTurn(t, question)
		cm.MergeResult = salePassages()
		chatsource.RetrievalScope(ctx, r, types.FILTER_TOP_K, cm)()
		require.Contains(t, order(cm.MergeResult), "p1", question)
	}
}
