package knowledge_test

import (
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

func productIDs(t *testing.T, members []release.Member, question string) []string {
	t.Helper()
	products, err := knowledge.NewService(membersReader(members)).QuestionProducts(
		context.Background(), tenant, space, pinned, question)
	require.NoError(t, err)
	ids := []string{}
	for _, product := range products {
		ids = append(ids, product.EntityID)
	}
	return ids
}

func TestNamedProductNormalizationAndMinimumLengths(t *testing.T) {
	for _, tc := range []struct {
		name, question string
		members        []release.Member
		want           []string
	}{
		{"unicode names", "介绍 ＡＢＣ【星】＋方案！", []release.Member{
			entity("P1", nil, "abc（星）★方案"),
		}, []string{"P1"}},
		{"normalized ID", "介绍 ｐ－１０", []release.Member{
			entity("P-10", nil, "另一个名称"),
		}, []string{"P-10"}},
		{"single rune ID", "x", []release.Member{
			entity("X", nil, "独特产品名称"),
		}, []string{}},
		{"punctuation is not an ID rune", "p", []release.Member{
			entity("P-", nil, "独特产品名称"),
		}, []string{}},
		{"short full alias", "小星", []release.Member{
			entity("X", nil, "独特产品名称", "小星"),
		}, []string{"X"}},
		{"three rune fragment", "介绍独特产", []release.Member{
			entity("X", nil, "独特产品名称"),
		}, []string{"X"}},
		{"two rune fragment", "独特", []release.Member{
			entity("X", nil, "独特产品名称"),
		}, []string{}},
		{"single product full name", "独特产品名称", []release.Member{
			entity("X", nil, "独特产品名称"),
		}, []string{"X"}},
		{"punctuation only", " ！★（ ）", []release.Member{
			entity("X", nil, "独特产品名称"),
		}, []string{}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			require.Equal(t, tc.want, productIDs(t, tc.members, tc.question))
		})
	}
}

func TestNamedProductFragmentExclusionUsesAllNamesAndProfileTitles(t *testing.T) {
	products := []release.Member{
		entity("A", nil, "公司独特保障计划"),
		entity("B", nil, "公司另款产品", "共享独特保障附约"),
	}
	require.Empty(t, productIDs(t, products, "独特保障"), "another product's alias prevents a fragment hit")
	require.Equal(t, []string{"B"}, productIDs(t, products, "共享独特保障附约"), "a full alias still names its product")

	products = []release.Member{
		entity("A", []string{"a"}, "公司独特保障计划"),
		entity("B", []string{"b"}, "公司另一计划"),
		profile("unused", [2]string{"unclaimed", "独特（保障）条件"}),
	}
	require.Empty(t, productIDs(t, products, "独特保障"),
		"titles without any published claim or matching product label still exclude fragments")
	require.Equal(t, []string{"A"}, productIDs(t, products, "公司独特保障计划"),
		"title exclusion applies only to fragments")

	products = []release.Member{
		entity("A", nil, "ABCDX"), entity("B", nil, "ABCY"), entity("C", nil, "ZBCD"),
	}
	require.Equal(t, []string{"A"}, productIDs(t, products, "ABCD"),
		"a unique four-rune fragment counts even when all its trigrams are shared")
}

func TestNamedProductsPreferLongerDirectNamesAndSuppressContainedFragments(t *testing.T) {
	products := []release.Member{
		entity("A", nil, "BrandAlpha"),
		entity("B", nil, "BrandAlphaExtra"),
		entity("C", nil, "ThirdProduct"),
	}
	require.Equal(t, []string{"B"}, productIDs(t, products, "BrandAlphaExtra"))
	require.Equal(t, []string{"A"}, productIDs(t, products, "BrandAlpha与extra"),
		"a fragment-only longer product is suppressed when its name contains the named product")

	products = []release.Member{
		entity("A", nil, "公司甲乙丙"),
		entity("B", nil, "公司甲乙丙丁戊"),
		entity("C", nil, "公司另一计划"),
	}
	require.Equal(t, []string{"B"}, productIDs(t, products, "甲乙丙丁戊"), "core names use the same dominance rule")
	products = []release.Member{entity("A", nil, "SameName"), entity("B", nil, "SameName")}
	require.Equal(t, []string{"A", "B"}, productIDs(t, products, "SameName"),
		"equal names cannot win over each other")
}

func TestNamedProductDirectAliasesDoNotDefeatLongerNames(t *testing.T) {
	for _, tc := range []struct {
		name, question string
		members        []release.Member
		want           []string
	}{
		{"full name", "公司星享优选", []release.Member{
			entity("A", nil, "公司星享", "星享"),
			entity("B", nil, "公司星享优选", "星享"),
		}, []string{"B"}},
		{"core name", "星享医疗优选", []release.Member{
			entity("A", nil, "公司星享医疗", "星享"),
			entity("B", nil, "公司星享医疗优选", "星享"),
			entity("C", nil, "公司另款产品"),
		}, []string{"B"}},
		{"separate full names", "公司星享优选和公司星享悦选", []release.Member{
			entity("A", nil, "公司星享悦选", "星享"),
			entity("B", nil, "公司星享优选", "星享"),
		}, []string{"A", "B"}},
		{"ID only", "AA", []release.Member{
			entity("AA", nil, "公司星享", "星享"),
			entity("BB", nil, "公司星享优选", "星享"),
		}, []string{"AA"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			require.Equal(t, tc.want, productIDs(t, tc.members, tc.question))
		})
	}
}

func TestNamedProductsKeepClaimAndPageMaterialOwnership(t *testing.T) {
	for _, visibility := range []string{"absent", "restricted", "visible"} {
		t.Run(visibility, func(t *testing.T) {
			members := []release.Member{
				entity("AA", nil, "Product Alpha"),
				claim("ZZ", "f", "present", "claim", sourced("claim-source")),
				claim("AA", "f", "present", "claim", sourced("z-source"), sourced("z-source"),
					map[string]any{"source_ref": "invalid"}),
				member("wiki_page", "wiki/AA/overview", map[string]any{
					"page_key": "overview", "entity_refs": []string{"AA", "ZZ", "missing"},
					"title": "Overview", "page_type": "entity", "origin": "MODEL_GENERATED",
					"evidence": []map[string]any{
						sourced("a-page"), sourced("z-source"),
						{
							"quote": "bad page", "locator": map[string]any{"page": 1.5},
							"source_ref": sourced("invalid-page")["source_ref"],
						},
						{
							"quote": "valid page", "locator": map[string]any{"page": 1},
							"source_ref": "invalid",
						},
					},
				}),
			}
			if visibility != "absent" {
				identity := entity("ZZ", nil, "Product Zeta")
				if visibility == "restricted" {
					identity.AccessScope = "restricted"
				}
				members = append(members, identity)
			}
			value := release.Release{ID: pinned, Members: members}
			service := release.NewService(visibilityStore{}, nil, nil,
				release.WithPublisher(visibilityPublisher{value: value}))
			ctx := context.WithValue(context.Background(), types.TenantIDContextKey, tenant)
			ctx = types.WithPrincipal(ctx, types.Principal{Type: types.PrincipalWebUser, ID: "reader"})
			products, err := knowledge.NewService(knowledge.NewReleaseReader(service)).QuestionProducts(
				ctx, tenant, space, pinned, "AA ZZ")
			require.NoError(t, err)
			require.Len(t, products, 2)
			require.Equal(t, []string{"a-page", "z-source"}, products[0].Materials)
			if visibility == "visible" {
				require.Equal(t, "Product Zeta", products[1].Name)
				require.Equal(t, []string{"a-page", "claim-source", "z-source"}, products[1].Materials)
			} else {
				require.Equal(t, "ZZ", products[1].Name)
				require.Equal(t, []string{"claim-source"}, products[1].Materials,
					"a placeholder receives only its own claims")
			}
		})
	}
}

func TestNamedProductsWithTheSameDisplayNameKeepSeparateMaterials(t *testing.T) {
	members := []release.Member{
		entity("AA", nil, "Shared Name"), entity("BB", nil, "Shared Name"),
		claim("AA", "f", "present", "first", sourced("first-source")),
		claim("BB", "f", "present", "second", sourced("second-source")),
	}
	products, err := knowledge.NewService(membersReader(members)).QuestionProducts(
		context.Background(), tenant, space, pinned, "Shared Name")
	require.NoError(t, err)
	require.Equal(t, []knowledge.NamedProduct{
		{EntityID: "AA", Name: "Shared Name", Materials: []string{"first-source"}},
		{EntityID: "BB", Name: "Shared Name", Materials: []string{"second-source"}},
	}, products)
}

func TestQuestionOverviewSupplementsDeduplicateAndRespectLimit(t *testing.T) {
	members := namedFixture().Members
	// The field may be both explicitly asked and one of the navigation overview fields.
	service := knowledge.NewService(membersReader(members))
	for _, tc := range []struct {
		limit int
		want  []string
	}{
		{1, []string{"A/waiting_period"}},
		{4, []string{"A/waiting_period", "B/rate_adjustable", "B/waiting_period", "A/coverage_renewal"}},
		{0, []string{
			"A/waiting_period", "B/rate_adjustable", "B/waiting_period",
			"A/coverage_renewal", "B/coverage_renewal",
		}},
	} {
		fields, err := service.QuestionFields(context.Background(), tenant, space, pinned,
			"e康惠享版和e康悦享版的费率可调和等待期", tc.limit)
		require.NoError(t, err)
		require.Equal(t, tc.want, slugs(fields))
	}
}

func TestNamedProductsPreserveReadScopeAndFailures(t *testing.T) {
	r := &reader{}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := knowledge.NewService(r).QuestionProducts(ctx, tenant, space, pinned, "1828")
	require.ErrorIs(t, err, context.Canceled)
	require.Empty(t, r.reads)

	failure := errors.New("reader unavailable")
	r.err = failure
	_, err = knowledge.NewService(r).QuestionProducts(context.Background(), tenant, space, pinned, "1828")
	require.ErrorIs(t, err, failure)
	require.Equal(t, []read{{tenant, space, pinned}}, r.reads)

	_, err = knowledge.NewService(membersReader{}).QuestionProducts(
		context.Background(), tenant, space, "historical-release", "1828")
	require.Equal(t, release.ErrorReleaseConflict, code(t, err),
		"never substitute the release the reader happened to return")
}
