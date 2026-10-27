// QA2 acceptance (protected, written by Claude): a quick question names a product only by its
// name, the name without the prefix every product shares, or a name fragment no other product and
// no field title contains; a field title that is part of a named product's name also brings that
// product's overview fields (Spec docs/design/slices/QA2-按产品检索与字段匹配.md §3–§4). Synthetic
// data in the shape of #286 q05/q16/q17/q22: nine products under one company prefix, three of one
// family, one name contained in another. RED until QA2.
package knowledge_test

import (
	"context"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

const namedRelease = "rel-named"

type namedReader struct{}

func (namedReader) ReleaseByID(_ context.Context, tenantID uint64, spaceID, releaseID string) (release.Release, error) {
	if tenantID != tenant || spaceID != space || releaseID != namedRelease {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	return namedFixture(), nil
}

func sourced(knowledgeID string) map[string]any {
	return map[string]any{
		"quote": "条款原文", "locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": 1},
		"source_ref": "source:v1:" + knowledgeID + ":1:" + strings.Repeat("ab", 32),
	}
}

// Nine products share the prefix 庚保. A, B and C are one family (e康); E's name contains D's;
// F and G carry generic words that are also field-title words (意外伤害, 重大疾病).
func namedFixture() release.Release {
	rate, renewal := [2]string{"rate_adjustable", "费率可调"}, [2]string{"coverage_renewal", "保险期间和续保"}
	waiting, accident := [2]string{"waiting_period", "等待期"}, [2]string{"accident_definition", "意外伤害定义与认定标准"}
	waiver := [2]string{"waiver_illness_list", "保费豁免重大疾病清单"}
	return release.Release{ID: namedRelease, Epoch: 9, Members: []release.Member{
		member("navigation", "navigation/enterprise", map[string]any{
			"navigation_id": "enterprise", "navigation_version": "v1",
			"overview_fields": []string{"coverage_renewal", "waiting_period"},
			"domains": []map[string]any{{
				"domain_key": "product", "display_name": "产品", "entity_types": []string{"product"},
				"groups": []map[string]any{
					{"group_key": "medical", "display_name": "医疗", "classification_labels": []string{"medical"}},
					{"group_key": "life", "display_name": "寿险", "classification_labels": []string{"life"}},
					{"group_key": "other", "display_name": "其他", "classification_labels": []string{"other"}},
				},
			}},
		}),
		profile("medical", rate, renewal, waiting),
		profile("life", renewal, waiting),
		profile("other", accident, waiver, waiting),
		entity("A", []string{"medical"}, "庚保e康（悦享版）医疗保险"),
		entity("B", []string{"medical"}, "庚保e康（惠享版）长期医疗保险（费率可调）"),
		entity("C", []string{"medical"}, "庚保e康（尊享版）医疗保险"),
		entity("D", []string{"life"}, "庚保金越（尊享版26）终身寿险"),
		entity("E", []string{"life"}, "庚保金越（尊享版26）终身寿险（分红型）"),
		entity("F", []string{"other"}, "庚保附加意外伤害保险"),
		entity("G", []string{"other"}, "庚保安佑（全能版）重大疾病保险"),
		entity("H", []string{"life"}, "庚保爱满分两全保险"),
		entity("I", []string{"life"}, "庚保守护百分百两全保险"),
		claim("A", "coverage_renewal", "present", "不保证续保。", sourced("k-a")),
		claim("A", "waiting_period", "present", "30日。", sourced("k-a")),
		claim("B", "rate_adjustable", "present", "费率可调整。", sourced("k-b2")),
		claim("B", "coverage_renewal", "present", "每20年为一个保证续保期间。", sourced("k-b1")),
		claim("B", "waiting_period", "present", "90日。", sourced("k-b1")),
		claim("C", "waiting_period", "present", "60日。", sourced("k-c")),
		claim("D", "waiting_period", "present", "180日。", sourced("k-d")),
		claim("E", "waiting_period", "present", "180日。", sourced("k-e")),
		claim("F", "accident_definition", "present", "外来的、突发的。", sourced("k-f")),
		claim("G", "waiting_period", "present", "90日。", sourced("k-g")),
	}}
}

func named(t *testing.T, question string) []string {
	t.Helper()
	products, err := knowledge.NewService(namedReader{}).QuestionProducts(
		context.Background(), tenant, space, namedRelease, question)
	require.NoError(t, err)
	out := []string{}
	for _, product := range products {
		out = append(out, product.EntityID)
	}
	return out
}

func asked(t *testing.T, question string) []string {
	t.Helper()
	fields, err := knowledge.NewService(namedReader{}).QuestionFields(
		context.Background(), tenant, space, namedRelease, question, 0)
	require.NoError(t, err)
	return slugs(fields)
}

func TestAQuestionNamesOnlyTheProductsItDistinguishes(t *testing.T) {
	// q16: the family word e康 and the shared word 医疗 no longer pull in the third family member.
	require.Equal(t, []string{"A", "B"}, named(t, "e康悦享版和e康惠享版长期医疗（费率可调）在续保上有什么不同？"))
	// q17: 意外伤害 is a field-title word, not a mention of the accident rider.
	require.Equal(t, []string{"A", "C"}, named(t, "e康悦享版和e康尊享版的等待期分别是多久？意外伤害有等待期吗？"))
	// q22: 重大疾病 is a field-title word, not a mention of the critical-illness product.
	require.Equal(t, []string{"A"}, named(t, "e康悦享版：被保险人在0至3周岁期间双耳失聪，重大疾病相关的保障赔不赔？"))
	require.Empty(t, named(t, "医疗保险的等待期一般多长"), "words shared by several names name nothing")
	require.Equal(t, []string{"F"}, named(t, "庚保附加意外伤害保险的意外怎么认定"), "the full name still counts")
}

func TestTheNameWithoutTheSharedPrefixNamesAProductAndTheLongerNameWins(t *testing.T) {
	// q05: the question drops the company prefix; D's name is inside E's, so no fragment is D's alone.
	require.Equal(t, []string{"D"}, named(t, "金越（尊享版26）终身寿险的保额每年按多少增长？"))
	require.Equal(t, []string{"E"}, named(t, "金越尊享版26终身寿险分红型的红利怎么分"),
		"both names are in the question; the longer one is the product asked about")
}

func TestNamedProductsCarryTheMaterialsTheReleaseAttributesToThem(t *testing.T) {
	products, err := knowledge.NewService(namedReader{}).QuestionProducts(
		context.Background(), tenant, space, namedRelease, "e康惠享版和e康悦享版")
	require.NoError(t, err)
	require.Len(t, products, 2)
	require.Equal(t, "A", products[0].EntityID, "navigation order, not question order")
	require.Equal(t, "庚保e康（悦享版）医疗保险", products[0].Name)
	require.Equal(t, []string{"k-a"}, products[0].Materials)
	require.Equal(t, []string{"k-b1", "k-b2"}, products[1].Materials, "sorted, without duplicates")

	_, err = knowledge.NewService(namedReader{}).QuestionProducts(
		context.Background(), tenant, space, "active", "e康悦享版")
	require.Equal(t, release.ErrorInvalidRequest, code(t, err), "only a pinned release is read")
}

func TestAFieldTitleInsideANamedProductsNameAlsoBringsItsOverview(t *testing.T) {
	// q16: 费率可调 is both B's name part and a field title; both products' renewal fields come too.
	got := asked(t, "e康悦享版和e康惠享版长期医疗（费率可调）在续保上有什么不同？")
	require.Equal(t, "B/rate_adjustable", got[0], "the field the question names comes first")
	require.Subset(t, got, []string{"A/coverage_renewal", "B/coverage_renewal"})
	require.NotContains(t, got, "C/waiting_period")
	seen := map[string]bool{}
	for _, slug := range got {
		require.False(t, seen[slug], "no field twice: %v", got)
		seen[slug] = true
	}
	require.Equal(t, []string{"B/rate_adjustable", "B/coverage_renewal", "B/waiting_period"},
		asked(t, "e康惠享版的费率可调吗"), "an explicit ask keeps its field, then the overview follows")
	require.Equal(t, []string{"A/waiting_period"}, asked(t, "e康悦享版的等待期是多久"),
		"a title outside every named product's name keeps the asked fields only")
}
