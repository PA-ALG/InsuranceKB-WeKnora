// Q1b-2 acceptance: quick answers find published fields from the question itself (Spec
// docs/design/slices/Q1b-2-快问快答读取已发布字段.md §2.1). Protected file: written by Claude.
//
// A field is asked about when its title is in the question; a product when the question holds
// its ID or a name, or shares two distinctive name bigrams. Products and fields combine; fields
// alone compare every product; a product alone gives its overview fields. RED until Q1b-2.
package knowledge_test

import (
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

type questionReader struct{ reads []read }

func (r *questionReader) ReleaseByID(
	_ context.Context, tenantID uint64, spaceID, releaseID string,
) (release.Release, error) {
	r.reads = append(r.reads, read{tenantID, spaceID, releaseID})
	if tenantID != tenant || spaceID != space || releaseID != pinned {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	return questionFixture(), nil
}

func cited(text string, page int) map[string]any {
	return map[string]any{
		"quote": text, "locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": page},
		"source_ref": "source:v1:k1:1:abc",
	}
}

// Navigation puts the medical group (M1, M2) before the critical-illness product 1828, and lists
// overview fields in an order unlike the profile's.
func questionFixture() release.Release {
	cooling, waiting, grace := [2]string{"cooling_off_period", "犹豫期"}, [2]string{"waiting_period", "等待期"},
		[2]string{"premium_grace_period", "宽限期"}
	return release.Release{ID: pinned, Epoch: 3, Members: []release.Member{
		member("navigation", "navigation/enterprise", map[string]any{
			"navigation_id": "enterprise", "navigation_version": "v1",
			"overview_fields": []string{"waiting_period", "cooling_off_period"},
			"domains": []map[string]any{{
				"domain_key": "product", "display_name": "产品", "entity_types": []string{"product"},
				"groups": []map[string]any{
					{"group_key": "medical", "display_name": "医疗", "classification_labels": []string{"medical"}},
					{"group_key": "critical", "display_name": "重疾", "classification_labels": []string{"critical"}},
				},
			}},
		}),
		profile("medical", cooling, waiting, grace),
		profile("critical", cooling, waiting, grace),
		entity("1828", []string{"critical"}, "丙安佑福（全能版）重大疾病保险"),
		entity("M1", []string{"medical"}, "甲医疗保险（尊享版）", "甲医疗"),
		entity("M2", []string{"medical"}, "乙医疗保险"),
		claim("1828", "cooling_off_period", "present", "20日", cited("自签收之日起20日内", 3)),
		claim("1828", "waiting_period", "present", "90日", cited("等待期为90日", 4)),
		claim("M1", "cooling_off_period", "present", "15日", cited("犹豫期为15日", 2)),
		claim("M1", "waiting_period", "unknown", nil),
		claim("M2", "cooling_off_period", "present", "15日", cited("十五日犹豫期", 2)),
	}}
}

func ask(t *testing.T, question string, limit int) []string {
	t.Helper()
	r := &questionReader{}
	fields, err := knowledge.NewService(r).QuestionFields(context.Background(), tenant, space, pinned, question, limit)
	require.NoError(t, err)
	require.Equal(t, []read{{tenant, space, pinned}}, r.reads)
	return slugs(fields)
}

func TestQuestionNamingAProductAndFieldsGetsThoseFieldsInProfileOrder(t *testing.T) {
	require.Equal(t, []string{"1828/cooling_off_period"}, ask(t, "安佑福的犹豫期是多久", 0))
	require.Equal(t, []string{"1828/cooling_off_period", "1828/waiting_period"},
		ask(t, "安佑福的等待期和犹豫期", 0))
	require.Equal(t, []string{"1828/waiting_period"}, ask(t, "1828的等待期", 0), "a product ID in the question")
	require.Equal(t, []string{"M1/cooling_off_period", "M2/cooling_off_period"},
		ask(t, "甲医疗和乙医疗保险的犹豫期分别多长", 0), "several products, in product order")
}

func TestQuestionWithFieldsOnlyComparesEveryProduct(t *testing.T) {
	require.Equal(t, []string{"M1/cooling_off_period", "M2/cooling_off_period", "1828/cooling_off_period"},
		ask(t, "犹豫期一般多长", 0))
	require.Equal(t, []string{"M1/cooling_off_period", "M2/cooling_off_period"}, ask(t, "犹豫期一般多长", 2))
	// "医疗" and "保险" are in most product names, so they select no product.
	require.Equal(t, []string{"M1/cooling_off_period", "M2/cooling_off_period", "1828/cooling_off_period"},
		ask(t, "医疗保险的犹豫期", 0))
}

func TestQuestionWithAProductOnlyGetsItsOverviewFields(t *testing.T) {
	require.Equal(t, []string{"1828/waiting_period", "1828/cooling_off_period"}, ask(t, "介绍一下安佑福", 0))
}

func TestQuestionWithNeitherGetsNothing(t *testing.T) {
	require.Empty(t, ask(t, "医疗保险怎么买", 0))
	require.Empty(t, ask(t, "  ", 0))
}

func TestQuestionFieldsReadOnlyTheNamedRelease(t *testing.T) {
	r := &questionReader{}
	_, err := knowledge.NewService(r).QuestionFields(context.Background(), tenant, space, "active", "犹豫期", 0)
	var typed *release.Error
	require.True(t, errors.As(err, &typed))
	require.Equal(t, release.ErrorInvalidRequest, typed.Code)
	require.Empty(t, r.reads)
}
