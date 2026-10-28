// QA2b acceptance (protected, written by Claude): a series name at the start of two or three
// products' core names names all of them, unless one of them is named more specifically; a series
// name shared by more products, or a category word inside the names, names nothing (Spec
// docs/design/slices/QA2b-共用名称与只用本品补足.md §1). Synthetic data in the shape of the
// 2026-10-28 recheck q14: two products of the 安佑福 series, four of the 盛世金越 series.
package knowledge_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

const seriesRelease = "rel-series"

type seriesReader struct{}

func (seriesReader) ReleaseByID(
	_ context.Context, tenantID uint64, spaceID, releaseID string,
) (release.Release, error) {
	if tenantID != tenant || spaceID != space || releaseID != seriesRelease {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	cooling, waiting := [2]string{"cooling_off_period", "犹豫期"}, [2]string{"waiting_period", "等待期"}
	dividend := [2]string{"dividend_rules", "红利分配"}
	return release.Release{ID: seriesRelease, Epoch: 3, Members: []release.Member{
		member("navigation", "navigation/enterprise", map[string]any{
			"navigation_id": "enterprise", "navigation_version": "v1",
			"overview_fields": []string{"waiting_period"},
			"domains": []map[string]any{{
				"domain_key": "product", "display_name": "产品", "entity_types": []string{"product"},
				"groups": []map[string]any{
					{"group_key": "critical", "display_name": "重疾", "classification_labels": []string{"critical"}},
					{"group_key": "life", "display_name": "寿险", "classification_labels": []string{"life"}},
				},
			}},
		}),
		profile("critical", cooling, waiting),
		profile("life", cooling, dividend),
		entity("J", []string{"critical"}, "庚保安佑福（全能版）重大疾病保险"),
		entity("K", []string{"critical"}, "庚保安佑福重大疾病保险"),
		entity("L", []string{"life"}, "庚保盛世金越（尊享版26）终身寿险"),
		entity("M", []string{"life"}, "庚保盛世金越（至尊版26）年金保险（分红型）"),
		entity("N", []string{"life"}, "庚保盛世金越（尊享版26）终身寿险（分红型）"),
		entity("O", []string{"life"}, "庚保盛世金越养老年金保险（分红型）"),
		claim("J", "cooling_off_period", "present", "15日。", sourced("k-j")),
		claim("J", "waiting_period", "present", "90日。", sourced("k-j")),
		claim("K", "cooling_off_period", "present", "20日。", sourced("k-k")),
		claim("K", "waiting_period", "present", "180日。", sourced("k-k")),
		claim("M", "dividend_rules", "present", "现金红利。", sourced("k-m")),
		claim("N", "dividend_rules", "present", "累积生息。", sourced("k-n")),
	}}, nil
}

func seriesNamed(t *testing.T, question string) []string {
	t.Helper()
	products, err := knowledge.NewService(seriesReader{}).QuestionProducts(
		context.Background(), tenant, space, seriesRelease, question)
	require.NoError(t, err)
	out := []string{}
	for _, product := range products {
		out = append(out, product.EntityID)
	}
	return out
}

func TestASeriesNameSharedByTwoProductsNamesBoth(t *testing.T) {
	// q14: 安佑福 begins both cores; neither product is named more specifically.
	require.Equal(t, []string{"J", "K"}, seriesNamed(t, "安佑福的犹豫期多久？"), "navigation order")
	fields, err := knowledge.NewService(seriesReader{}).QuestionFields(
		context.Background(), tenant, space, seriesRelease, "安佑福的犹豫期多久？", 0)
	require.NoError(t, err)
	require.Equal(t, []string{"J/cooling_off_period", "K/cooling_off_period"}, slugs(fields),
		"the asked field of every product the series names")
}

func TestAMoreSpecificMatchKeepsTheSeriesNameFromNamingTheRest(t *testing.T) {
	require.Equal(t, []string{"J"}, seriesNamed(t, "安佑福全能版的等待期是多久"), "a fragment only J carries")
	require.Equal(t, []string{"K"}, seriesNamed(t, "庚保安佑福重大疾病保险的等待期是多久"), "K's full name")
}

func TestABroadSeriesNameOrACategoryWordNamesNothing(t *testing.T) {
	require.Empty(t, seriesNamed(t, "盛世金越的红利怎么分？"), "four products share it")
	require.Empty(t, seriesNamed(t, "重大疾病保险的犹豫期一般多长"), "a category word, not at the start of a core")
}
