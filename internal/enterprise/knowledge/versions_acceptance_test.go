// PV-4b acceptance (protected, written by Claude): reads derive a version's sale status, sale
// period, family and supersedes links from the pinned release (Spec docs/design/slices/
// PV-4b-读取侧.md §1–§2). Status uses the shared vectors; tool and field texts carry a version
// label only for entities with a lifecycle, so text without version data is unchanged.
package knowledge_test

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/modelcontext"
)

func TestSaleStatusVectors(t *testing.T) {
	raw, err := os.ReadFile("testdata/sale_status_vectors.json")
	require.NoError(t, err)
	var vectors struct {
		Status []struct {
			Name      string               `json:"name"`
			Lifecycle *knowledge.Lifecycle `json:"lifecycle"`
			Day       string               `json:"day"`
			Status    string               `json:"status"`
		} `json:"status"`
		BusinessDay []struct {
			Instant string `json:"instant"`
			Day     string `json:"day"`
		} `json:"business_day"`
	}
	require.NoError(t, json.Unmarshal(raw, &vectors))
	require.NotEmpty(t, vectors.Status)
	for _, vector := range vectors.Status {
		require.Equal(t, vector.Status, string(knowledge.SaleStatusOn(vector.Lifecycle, vector.Day)), vector.Name)
	}
	require.NotEmpty(t, vectors.BusinessDay)
	for _, vector := range vectors.BusinessDay {
		instant, err := time.Parse(time.RFC3339, vector.Instant)
		require.NoError(t, err)
		require.Equal(t, vector.Day, knowledge.BusinessDay(instant), vector.Instant)
	}
}

type versionReader struct{ release release.Release }

func (r versionReader) ReleaseByID(
	_ context.Context, tenantID uint64, spaceID, releaseID string,
) (release.Release, error) {
	if tenantID != tenant || spaceID != space || releaseID != pinned {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	return r.release, nil
}

func versioned(id, label string, lifecycle, family map[string]any, names ...string) release.Member {
	payload := map[string]any{
		"entity_id": id, "entity_type": "product", "names": names, "classification_labels": []string{label},
	}
	if lifecycle != nil {
		payload["lifecycle"] = lifecycle
	}
	if family != nil {
		payload["product_family"] = family
	}
	return member("entity", "entity/"+id, payload)
}

func supersedes(newer, older string) release.Member {
	id := "supersedes/" + newer + "/" + older
	return member("relation", "relation/"+id, map[string]any{
		"relation_id": id, "predicate": "supersedes", "from": newer, "to": older,
	})
}

// V1 and V2 are two filings of one name (V2 supersedes V1); N1 starts selling next year; U1 has
// no version data. GHOST is not in the release, so its relation is ignored.
func versionFixture(intents map[string]any) release.Release {
	waiting, cooling := [2]string{"waiting_period", "等待期"}, [2]string{"cooling_off_period", "犹豫期"}
	family := map[string]any{"key": "甲护理", "display_name": "甲护理"}
	navigation := map[string]any{
		"navigation_id": "enterprise", "navigation_version": "v1",
		"overview_fields": []string{"waiting_period"},
		"domains": []map[string]any{{
			"domain_key": "product", "display_name": "产品", "entity_types": []string{"product"},
			"groups": []map[string]any{
				{"group_key": "nursing", "display_name": "护理", "classification_labels": []string{"nursing"}},
				{"group_key": "medical", "display_name": "医疗", "classification_labels": []string{"medical"}},
			},
		}},
	}
	if intents != nil {
		navigation["question_intents"] = intents
	}
	members := []release.Member{
		member("navigation", "navigation/enterprise", navigation),
		profile("nursing", waiting, cooling), profile("medical", waiting, cooling),
		versioned("V1", "nursing", map[string]any{
			"sale_start": "2023-01-01", "sale_end": "2024-04-23", "source_status": "discontinued",
		}, family, "甲护理保险"),
		versioned("V2", "nursing", map[string]any{
			"sale_start": "2024-04-23", "source_status": "on_sale", "basis_date": "2026-10-20",
		}, family, "甲护理保险"),
		versioned("N1", "medical", map[string]any{
			"sale_start": "2027-01-01", "source_status": "on_sale",
		}, nil, "乙医疗保险"),
		versioned("U1", "medical", nil, nil, "丙医疗保险"),
		supersedes("V2", "V1"), supersedes("V2", "GHOST"),
	}
	for _, id := range []string{"V1", "V2", "N1", "U1"} {
		members = append(members,
			claim(id, "waiting_period", "present", "90日", cited(id+"等待期90日", 2)),
			claim(id, "cooling_off_period", "present", "15日", cited(id+"犹豫期15日", 3)))
	}
	return release.Release{ID: pinned, Epoch: 9, Members: members}
}

// 02:00 UTC on 2026-11-01 is 10:00 in the business time zone: the evaluation day is 2026-11-01.
func versionService(intents map[string]any) *knowledge.Service {
	clock := func() time.Time { return time.Date(2026, 11, 1, 2, 0, 0, 0, time.UTC) }
	return knowledge.NewService(versionReader{versionFixture(intents)}).WithClock(clock)
}

func TestEntitiesCarryStatusPeriodFamilyAndSupersedesLinks(t *testing.T) {
	entities, err := versionService(nil).FindEntities(context.Background(), tenant, space, pinned, "甲护理", 5)
	require.NoError(t, err)
	byID := map[string]knowledge.Entity{}
	for _, entity := range entities {
		byID[entity.EntityID] = entity
	}
	require.Contains(t, byID, "V1")
	require.Contains(t, byID, "V2")
	require.Equal(t, knowledge.SaleDiscontinued, byID["V1"].Status)
	require.Equal(t, knowledge.SaleOnSale, byID["V2"].Status)
	require.Equal(t, "2024-04-23", byID["V1"].Lifecycle.SaleEnd)
	require.Equal(t, &knowledge.Family{Key: "甲护理", DisplayName: "甲护理"}, byID["V2"].Family)
	require.Equal(t, []string{"V2"}, byID["V1"].Successors)
	require.Empty(t, byID["V1"].Predecessors)
	require.Equal(t, []string{"V1"}, byID["V2"].Predecessors) // the GHOST end is not in the release
	require.Empty(t, byID["V2"].Successors)

	plain, err := versionService(nil).FindEntities(context.Background(), tenant, space, pinned, "丙医疗", 5)
	require.NoError(t, err)
	require.Len(t, plain, 1)
	require.Nil(t, plain[0].Lifecycle)
	require.Nil(t, plain[0].Family)
	require.Equal(t, knowledge.SaleUnknown, plain[0].Status)
}

func versionTool(t *testing.T, name, args string) (string, []map[string]interface{}) {
	t.Helper()
	query := tool(t, versionService(nil), name, map[string]string{space: pinned})
	result, err := query.Execute(toolContext(), json.RawMessage(args))
	require.NoError(t, err)
	rows, _ := result.Data["results"].([]map[string]interface{})
	return modelcontext.NewRegistry(true).ModelToolResultForTool(query.Name(), result), rows
}

func TestFindEntityToolLabelsVersionsAndLeavesUnversionedLinesUnchanged(t *testing.T) {
	rendered, _ := versionTool(t, "knowledge_find_entity", `{"query":"甲护理保险"}`)
	require.Contains(t, rendered,
		"产品编号：V1；名称：甲护理保险；销售状态：停售；销售期：2023-01-01 至 2024-04-23；系列：甲护理；后续版本：V2（甲护理保险）")
	require.Contains(t, rendered,
		"产品编号：V2；名称：甲护理保险；销售状态：在售（据 2026-10-20 数据）；销售期：2024-04-23 起；系列：甲护理；前一版本：V1（甲护理保险）")

	rendered, _ = versionTool(t, "knowledge_find_entity", `{"query":"乙医疗保险"}`)
	require.Contains(t, rendered, "产品编号：N1；名称：乙医疗保险；销售状态：未开售；销售期：2027-01-01 起")

	// 丙医疗保险 also finds 乙医疗保险 by shared bigrams; only its own line is checked.
	rendered, _ = versionTool(t, "knowledge_find_entity", `{"query":"丙医疗保险"}`)
	require.Regexp(t, "产品编号：U1；名称：丙医疗保险(\n|</knowledge_result>)", rendered)
}

func TestFieldTextAndTitlesCarryTheVersionLabelOnlyWithALifecycle(t *testing.T) {
	rendered, rows := versionTool(t, "knowledge_get_fields", `{"entity_id":"V1","fields":["等待期"]}`)
	label := "甲护理保险（停售；销售期 2023-01-01 至 2024-04-23） · 等待期"
	require.Contains(t, rendered, label+"：90日")
	require.Len(t, rows, 1)
	require.Equal(t, label, rows[0]["knowledge_title"])

	rendered, rows = versionTool(t, "knowledge_get_fields", `{"entity_id":"U1","fields":["等待期"]}`)
	require.Contains(t, rendered, "丙医疗保险 · 等待期：90日")
	require.NotContains(t, rendered, "丙医疗保险（")
	require.Len(t, rows, 1)
	require.Equal(t, "丙医疗保险 · 等待期", rows[0]["knowledge_title"])
	require.Equal(t, "丙医疗保险 · 等待期", knowledge.FieldTitle(knowledge.Field{EntityName: "丙医疗保险", FieldTitle: "等待期"}))
}

func TestBusinessDayFollowsTheServiceClockAcrossMidnight(t *testing.T) {
	// 16:30 UTC on 2026-12-31 is already 2027-01-01 in the business time zone.
	late := knowledge.NewService(versionReader{versionFixture(nil)}).
		WithClock(func() time.Time { return time.Date(2026, 12, 31, 16, 30, 0, 0, time.UTC) })
	entities, err := late.FindEntities(context.Background(), tenant, space, pinned, "乙医疗保险", 5)
	require.NoError(t, err)
	require.NotEmpty(t, entities)
	require.Equal(t, "N1", entities[0].EntityID)               // the direct name match ranks first
	require.Equal(t, knowledge.SaleOnSale, entities[0].Status) // 2027-01-01 has begun
	early := knowledge.NewService(versionReader{versionFixture(nil)}).
		WithClock(func() time.Time { return time.Date(2026, 12, 31, 15, 59, 0, 0, time.UTC) })
	entities, err = early.FindEntities(context.Background(), tenant, space, pinned, "乙医疗保险", 5)
	require.NoError(t, err)
	require.Equal(t, "N1", entities[0].EntityID)
	require.Equal(t, knowledge.SaleNotYet, entities[0].Status)
}

func questionSlugs(t *testing.T, intents map[string]any, question string) []string {
	t.Helper()
	fields, err := versionService(intents).QuestionFields(context.Background(), tenant, space, pinned, question, 20)
	require.NoError(t, err)
	out := []string{}
	for _, field := range fields {
		out = append(out, field.Slug)
	}
	return out
}

var intents = map[string]any{
	"sales":   [][]string{{"推荐"}, {"哪款"}},
	"service": [][]string{{"理赔"}, {"投保"}},
}

func TestSalesQuestionsCompareOnlyProductsOnSaleOrOfUnknownStatus(t *testing.T) {
	require.ElementsMatch(t, []string{"V2/waiting_period", "U1/waiting_period"},
		questionSlugs(t, intents, "推荐哪款产品的等待期短"))
	// Without published intents nothing is filtered.
	require.ElementsMatch(t,
		[]string{"V1/waiting_period", "V2/waiting_period", "N1/waiting_period", "U1/waiting_period"},
		questionSlugs(t, nil, "推荐哪款产品的等待期短"))
	// A named product is never dropped: a question about a discontinued one must learn that it is.
	require.ElementsMatch(t, []string{"V1/waiting_period", "V2/waiting_period"},
		questionSlugs(t, intents, "推荐甲护理保险吗，等待期多久"))
	// Both intents at once: ambiguous, nothing is filtered.
	require.ElementsMatch(t,
		[]string{"V1/waiting_period", "V2/waiting_period", "N1/waiting_period", "U1/waiting_period"},
		questionSlugs(t, intents, "推荐哪款产品理赔的等待期短"))
}

func TestServiceQuestionsPickTheVersionSoldOnThePurchaseDate(t *testing.T) {
	cases := map[string][]string{
		"2023年6月投保的甲护理保险理赔等待期":    {"V1/waiting_period"},
		"2023年6月18日投保的甲护理保险理赔等待期": {"V1/waiting_period"},
		"2025-03-01投保的甲护理保险理赔等待期": {"V2/waiting_period"},
		"2025/3/1投保的甲护理保险理赔等待期":   {"V2/waiting_period"},
		// Year precision: both sale periods overlap 2024.
		"2024年投保的甲护理保险理赔等待期": {"V1/waiting_period", "V2/waiting_period"},
		// No version was sold then: keep every version, labelled, so the model asks.
		"2010年投保的甲护理保险理赔等待期": {"V1/waiting_period", "V2/waiting_period"},
		// No date: nothing to select by.
		"甲护理保险理赔的等待期": {"V1/waiting_period", "V2/waiting_period"},
	}
	for question, want := range cases {
		require.ElementsMatch(t, want, questionSlugs(t, intents, question), question)
	}
	require.ElementsMatch(t, []string{"V1/waiting_period", "V2/waiting_period"},
		questionSlugs(t, nil, "2023年6月投保的甲护理保险理赔等待期"))
}
