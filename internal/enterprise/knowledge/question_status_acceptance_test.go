// PV-5 acceptance (protected, written by Claude): a sales question learns the sale status of every
// product it names, unknown included; raw materials carry their products' version labels; an unnamed
// sales comparison leaves out materials only products not on sale cite; registered identifiers name
// products; a service question with a purchase date follows the supersedes chain to the version sold
// then (Spec docs/design/slices/PV-5-问答销售状态与产品识别.md §1.1, §2, §3, §4.2). RED until PV-5.
package knowledge_test

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

func registered(id, label string, lifecycle map[string]any, identifiers map[string]string, name string) release.Member {
	payload := map[string]any{
		"entity_id": id, "entity_type": "product", "names": []string{name}, "classification_labels": []string{label},
	}
	if lifecycle != nil {
		payload["lifecycle"] = lifecycle
	}
	if identifiers != nil {
		payload["identifiers"] = identifiers
	}
	return member("entity", "entity/"+id, payload)
}

func from(material, text string) map[string]any {
	return map[string]any{
		"quote": text, "locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": 1},
		"source_ref": "source:v1:" + material + ":1:" + strings.Repeat("ab", 32),
	}
}

// P (2635-1) stopped selling before its year version Q (2648-1) began; Q supersedes P. U has no
// version data; F starts selling next year. kP is cited only by P, kS by P and Q, kQ by Q, kU by U
// and kF by F.
func statusFixture(intents map[string]any) release.Release {
	waiting, cooling := [2]string{"waiting_period", "等待期"}, [2]string{"cooling_off_period", "犹豫期"}
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
	return release.Release{ID: pinned, Epoch: 11, Members: []release.Member{
		member("navigation", "navigation/enterprise", navigation),
		profile("nursing", waiting, cooling), profile("medical", waiting, cooling),
		registered("P", "nursing", map[string]any{
			"sale_start": "2023-01-01", "sale_end": "2024-09-01", "source_status": "discontinued",
		}, map[string]string{"product_code": "2635", "version_key": "2635-1"}, "丁护理保险"),
		registered("Q", "nursing", map[string]any{
			"sale_start": "2025-10-22", "source_status": "on_sale", "basis_date": "2026-10-20",
		}, map[string]string{"product_code": "2648", "version_key": "2648-1"}, "丁护理（2026）保险"),
		registered("U", "medical", nil, map[string]string{"product_code": "1847H"}, "戊医疗保险"),
		registered("F", "medical", map[string]any{
			"sale_start": "2027-01-01", "source_status": "on_sale",
		}, nil, "己医疗保险"),
		supersedes("Q", "P"),
		claim("P", "waiting_period", "present", "90日", from("kP", "P等待期90日")),
		claim("P", "cooling_off_period", "present", "15日", from("kS", "P犹豫期15日")),
		claim("Q", "waiting_period", "present", "60日", from("kQ", "Q等待期60日")),
		claim("Q", "cooling_off_period", "present", "20日", from("kS", "Q犹豫期20日")),
		claim("U", "waiting_period", "present", "30日", from("kU", "U等待期30日")),
		claim("U", "cooling_off_period", "present", "15日", from("kU", "U犹豫期15日")),
		claim("F", "waiting_period", "present", "30日", from("kF", "F等待期30日")),
		claim("F", "cooling_off_period", "present", "15日", from("kF", "F犹豫期15日")),
	}}
}

var statusIntents = map[string]any{
	"sales":   [][]string{{"能买"}, {"推荐"}, {"在售"}},
	"service": [][]string{{"投保"}, {"理赔"}},
}

type statusReader struct{ intents map[string]any }

func (r statusReader) ReleaseByID(
	_ context.Context, tenantID uint64, spaceID, releaseID string,
) (release.Release, error) {
	if tenantID != tenant || spaceID != space || releaseID != pinned {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	return statusFixture(r.intents), nil
}

// The evaluation day is 2026-11-01 in the business time zone.
func statusService(intents map[string]any) *knowledge.Service {
	clock := func() time.Time { return time.Date(2026, 11, 1, 2, 0, 0, 0, time.UTC) }
	return knowledge.NewService(statusReader{intents}).WithClock(clock)
}

func statusLines(t *testing.T, intents map[string]any, question string) []knowledge.StatusLine {
	t.Helper()
	lines, err := statusService(intents).QuestionStatuses(context.Background(), tenant, space, pinned, question)
	require.NoError(t, err)
	return lines
}

func TestSalesQuestionsGetTheSaleStatusOfEveryNamedProduct(t *testing.T) {
	require.Equal(t, []knowledge.StatusLine{{
		EntityID: "P", Slug: "entity/P", Title: "丁护理保险 · 销售状态",
		Text: "丁护理保险 · 销售状态：停售；销售期：2023-01-01 至 2024-09-01；后续版本：Q（丁护理（2026）保险）",
	}}, statusLines(t, statusIntents, "丁护理保险现在还能买吗"))
	require.Equal(t, []knowledge.StatusLine{{
		EntityID: "Q", Slug: "entity/Q", Title: "丁护理（2026）保险 · 销售状态",
		Text: "丁护理（2026）保险 · 销售状态：在售（据 2026-10-20 数据）；销售期：2025-10-22 起；前一版本：P（丁护理保险）",
	}}, statusLines(t, statusIntents, "推荐丁护理（2026）保险吗"))
	// No version data: the status is stated as unknown, never left out.
	require.Equal(t, []knowledge.StatusLine{{
		EntityID: "U", Slug: "entity/U", Title: "戊医疗保险 · 销售状态", Text: "戊医疗保险 · 销售状态：未知",
	}}, statusLines(t, statusIntents, "戊医疗保险能买吗"))
	// Navigation order: the nursing group before the medical group.
	lines := statusLines(t, statusIntents, "己医疗保险和丁护理保险哪款能买")
	require.Len(t, lines, 2)
	require.Equal(t, "P", lines[0].EntityID)
	require.Equal(t, "己医疗保险 · 销售状态：未开售；销售期：2027-01-01 起", lines[1].Text)

	for name, question := range map[string]string{
		"a service question":    "2024年投保的丁护理保险理赔要什么材料",
		"both intents at once":  "推荐丁护理保险理赔快吗",
		"no product named":      "现在在售的有哪几款",
		"no sales or service":   "丁护理保险的等待期",
		"a field-only question": "等待期多久",
	} {
		require.Empty(t, statusLines(t, statusIntents, question), name)
	}
	require.Empty(t, statusLines(t, nil, "丁护理保险现在还能买吗"), "without published intents")
}

func TestRawMaterialNamesCarryTheirProductsVersionLabels(t *testing.T) {
	cited, err := statusService(nil).SourceEntities(context.Background(), tenant, space, pinned)
	require.NoError(t, err)
	stopped := "丁护理保险（停售；销售期 2023-01-01 至 2024-09-01）"
	selling := "丁护理（2026）保险（在售，据 2026-10-20 数据；销售期 2025-10-22 起）"
	require.Equal(t, []string{stopped}, cited["kP"])
	require.Equal(t, []string{stopped, selling}, cited["kS"])
	require.Equal(t, []string{selling}, cited["kQ"])
	require.Equal(t, []string{"戊医疗保险"}, cited["kU"], "no version data: the name stays as it was")
}

func offSale(t *testing.T, intents map[string]any, question string) map[string]bool {
	t.Helper()
	materials, err := statusService(intents).OffSaleMaterials(context.Background(), tenant, space, pinned, question)
	require.NoError(t, err)
	return materials
}

func TestUnnamedSalesComparisonsLeaveOutMaterialsOfProductsNotOnSale(t *testing.T) {
	// kS is also cited by Q, which is on sale; kU's product has an unknown status.
	require.Equal(t, map[string]bool{"kP": true, "kF": true}, offSale(t, statusIntents, "现在在售的有哪几款"))
	require.Equal(t, map[string]bool{"kP": true, "kF": true}, offSale(t, statusIntents, "推荐一款等待期短的"))
	for name, question := range map[string]string{
		"a named product is never dropped": "丁护理保险能买吗",
		"a service question":               "投保后理赔要多久",
		"no sales intent":                  "等待期一般多久",
	} {
		require.Empty(t, offSale(t, statusIntents, question), name)
	}
	require.Empty(t, offSale(t, nil, "现在在售的有哪几款"), "without published intents")
}

func namedIDs(t *testing.T, intents map[string]any, question string) []string {
	t.Helper()
	products, err := statusService(intents).QuestionProducts(context.Background(), tenant, space, pinned, question)
	require.NoError(t, err)
	out := []string{}
	for _, product := range products {
		out = append(out, product.EntityID)
	}
	return out
}

func TestQuestionsNameProductsByTheirRegisteredIdentifiers(t *testing.T) {
	cases := map[string][]string{
		"产品代码2635还能买吗":  {"P"},
		"2648-1的犹豫期是多少": {"Q"},
		"1847H现在能买吗":    {"U"},
		"1847h的等待期":     {"U"},
		// Part of a longer number or code is no identifier.
		"代码26351是哪款":      {},
		"保单号2635-0001的理赔": {},
		"12648的等待期":       {},
	}
	for question, want := range cases {
		require.Equal(t, want, namedIDs(t, nil, question), question)
	}
	entities, err := statusService(nil).FindEntities(context.Background(), tenant, space, pinned, "2635-1", 5)
	require.NoError(t, err)
	require.NotEmpty(t, entities)
	require.Equal(t, "P", entities[0].EntityID, "an identifier finds its entity directly")
}

func statusSlugs(t *testing.T, intents map[string]any, question string) []string {
	t.Helper()
	fields, err := statusService(intents).QuestionFields(context.Background(), tenant, space, pinned, question, 20)
	require.NoError(t, err)
	out := []string{}
	for _, field := range fields {
		out = append(out, field.Slug)
	}
	return out
}

func TestServiceQuestionsWithAPurchaseDateFollowTheVersionChain(t *testing.T) {
	cases := map[string][]string{
		// Q is not named, but supersedes P and was the version sold in December 2025.
		"我2025年12月投保的丁护理保险，犹豫期多久": {"Q/cooling_off_period"},
		"2024年6月投保的丁护理保险犹豫期":      {"P/cooling_off_period"},
		// No date: only the named version.
		"丁护理保险投保后犹豫期多久": {"P/cooling_off_period"},
		// No version of the chain was sold then: only the named one stays, labelled.
		"2010年投保的丁护理保险犹豫期": {"P/cooling_off_period"},
	}
	for question, want := range cases {
		require.Equal(t, want, statusSlugs(t, statusIntents, question), question)
	}
	require.Equal(t, []string{"P/cooling_off_period"}, statusSlugs(t, nil, "我2025年12月投保的丁护理保险，犹豫期多久"),
		"without published intents nothing changes")

	// Raw retrieval names the same versions as the published fields.
	require.Equal(t, []string{"Q"}, namedIDs(t, statusIntents, "我2025年12月投保的丁护理保险，犹豫期多久"))
	require.Equal(t, []string{"P"}, namedIDs(t, statusIntents, "2024年6月投保的丁护理保险犹豫期"))
	require.Equal(t, []string{"P"}, namedIDs(t, statusIntents, "丁护理保险投保后犹豫期多久"))
}
