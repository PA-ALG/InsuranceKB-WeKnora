// QA1 acceptance (protected, written by Claude): search results say what they covered, field
// states read in Chinese, and each cited material maps to the entities citing it (Spec
// docs/design/slices/QA1-问答来源标注与范围说明.md §2.1, §3, §4.1). Synthetic data in the shape of
// #286 r2 J006 (a literal search that misses one product's wording) and J007 (a page phrasing
// that misses, an unknown field read as absence). RED until QA1.
package knowledge_test

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/modelcontext"
	"github.com/Tencent/WeKnora/internal/types"
)

const scoped = "rel-q"

func ref(knowledgeID string) string {
	return "source:v1:" + knowledgeID + ":1:" + strings.Repeat("ab", 32)
}

func cites(knowledgeID, quote string) map[string]any {
	return map[string]any{
		"quote": quote, "locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": 2}, "source_ref": ref(knowledgeID),
	}
}

type scopeReader struct{ err error }

func (r scopeReader) ReleaseByID(
	_ context.Context, tenantID uint64, spaceID, releaseID string,
) (release.Release, error) {
	if r.err != nil {
		return release.Release{}, r.err
	}
	if tenantID != tenant || spaceID != space || releaseID != scoped {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	return scopeFixture(), nil
}

// scopeFixture: navigation lists A (甲保险) before B (乙保险), although B's entity comes first.
// A has 22 fields whose values say 续保; B says 重新投保 for its grace period, has one 续保 field,
// an unknown and an absent field, and a page. kS is cited by both products; kP only by B's page.
func scopeFixture() release.Release {
	keys := [][2]string{{"grace", "宽限期"}, {"renewal", "续保条件"}, {"age_rule", "年龄错误处理"}, {"exclusion", "责任免除"}}
	for i := 1; i <= 22; i++ {
		keys = append(keys, [2]string{fmt.Sprintf("term_%02d", i), fmt.Sprintf("条款%02d", i)})
	}
	members := []release.Member{
		member("navigation", "navigation/enterprise", map[string]any{
			"navigation_id": "enterprise", "navigation_version": "v1",
			"domains": []map[string]any{{
				"domain_key": "product", "display_name": "产品", "entity_types": []string{"product"},
				"groups": []map[string]any{
					{"group_key": "ga", "display_name": "甲组", "classification_labels": []string{"ga"}},
					{"group_key": "gb", "display_name": "乙组", "classification_labels": []string{"gb"}},
				},
			}},
		}),
		profile("ga", keys...), profile("gb", keys...),
		entity("B", []string{"gb"}, "乙保险（悦享版）"),
		entity("A", []string{"ga"}, "甲保险（经典版）"),
		claim("B", "grace", "present", "重新投保时宽限期为60日", cites("kB", "宽限期为60日")),
		claim("B", "renewal", "present", "续保须重新投保", cites("kS", "续保须重新投保")),
		claim("B", "age_rule", "unknown", nil),
		claim("B", "exclusion", "absent_explicitly", nil),
		member("wiki_page", "wiki/B/age-error", map[string]any{
			"page_key": "age-error", "entity_refs": []string{"B"}, "title": "年龄错误处理", "page_type": "concept",
			"summary": "年龄错误时按实际年龄调整。", "content": "投保年龄错误的，按实际年龄调整。", "origin": "MODEL_GENERATED",
			"evidence": []map[string]any{cites("kP", "按实际年龄调整")},
		}),
	}
	for i := 1; i <= 22; i++ {
		knowledgeID := "kA"
		if i == 1 {
			knowledgeID = "kS"
		}
		members = append(members, claim("A", fmt.Sprintf("term_%02d", i), "present",
			fmt.Sprintf("续保规则%02d", i), cites(knowledgeID, "续保规则")))
	}
	members = append(members, claim("A", "grace", "present", "宽限期为30日", map[string]any{
		"quote": "宽限期为30日", "locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": 2},
		"source_ref": "source:v1:malformed",
	}))
	return release.Release{ID: scoped, Epoch: 9, Members: members}
}

func scopeTool(t *testing.T, name string) types.Tool {
	t.Helper()
	return tool(t, knowledge.NewService(scopeReader{}), name, map[string]string{space: scoped})
}

func rendered(t *testing.T, name string, args string) (string, map[string]interface{}) {
	t.Helper()
	query := scopeTool(t, name)
	result, err := query.Execute(toolContext(), json.RawMessage(args))
	require.NoError(t, err)
	require.True(t, result.Success)
	return modelcontext.NewRegistry(true).ModelToolResultForTool(query.Name(), result), result.Data
}

func TestFieldSearchSaysHowManyMatchedAndThatAMissIsNotAbsence(t *testing.T) {
	text, data := rendered(t, "knowledge_search_fields", `{"query":"续保"}`)
	require.EqualValues(t, 23, data["total"])
	require.Len(t, data["results"], 20)
	notes := data["notes"].([]string)
	require.True(t, strings.HasPrefix(notes[0], "检索范围：已发布字段中明确存在的值，按字面匹配；命中 23 条，显示 20 条。"), notes[0])
	for _, want := range []string{"命中 23 条，显示 20 条", "不代表材料没有", "knowledge_get_fields"} {
		require.Contains(t, text, want, "the model sees the scope note next to the rows")
	}

	text, data = rendered(t, "knowledge_search_fields", `{"query":"续保","entity_id":"B"}`)
	require.EqualValues(t, 1, data["total"])
	rows := data["results"].([]map[string]interface{})
	require.Len(t, rows, 1)
	require.Equal(t, "release:rel-q:B/renewal", rows[0]["chunk_id"])
	require.Contains(t, data["notes"].([]string)[0], "检索范围：乙保险（悦享版）的已发布字段中明确存在的值")
	require.Contains(t, text, "命中 1 条，显示 1 条")

	text, data = rendered(t, "knowledge_search_fields", `{"query":"保证续保期间外"}`)
	require.Empty(t, data["results"])
	require.Contains(t, text, "命中 0 条，显示 0 条", "an empty result still says what it covered")
	require.Contains(t, text, "不代表材料没有")

	_, err := scopeTool(t, "knowledge_search_fields").Execute(toolContext(),
		json.RawMessage(`{"query":"续保","entity_id":"nope"}`))
	require.Equal(t, "ENTITY_NOT_FOUND", code(t, err))
}

func TestSearchFieldsFiltersByEntityBeforeTheLimit(t *testing.T) {
	s := knowledge.NewService(scopeReader{})
	got, total, err := s.SearchFields(context.Background(), tenant, space, scoped, "宽限期", "B", 0)
	require.NoError(t, err)
	require.Equal(t, 1, total)
	require.Equal(t, "B/grace", got[0].Slug)
	got, total, err = s.SearchFields(context.Background(), tenant, space, scoped, "续保", "", 0)
	require.NoError(t, err)
	require.Equal(t, 23, total)
	require.Len(t, got, 20)
	require.Equal(t, "A", got[0].EntityID, "navigation order")

	var schema struct {
		Properties map[string]any `json:"properties"`
		Required   []string       `json:"required"`
	}
	require.NoError(t, json.Unmarshal(scopeTool(t, "knowledge_search_fields").Parameters(), &schema))
	require.Contains(t, schema.Properties, "entity_id")
	require.NotContains(t, schema.Required, "entity_id")
}

func TestPageSearchSaysWhatItCoveredWhenNothingMatched(t *testing.T) {
	text, data := rendered(t, "knowledge_search_pages", `{"query":"年龄错误的处理"}`)
	require.Empty(t, data["results"])
	require.Contains(t, text, "检索范围：延伸阅读页面，每个词都须字面出现；命中 0 页，显示 0 页。")
	require.Contains(t, text, "没有命中不代表材料没有")

	text, data = rendered(t, "knowledge_search_pages", `{"query":"年龄错误","entity_id":"B"}`)
	require.Len(t, data["results"], 1)
	require.Contains(t, text, "检索范围：乙保险（悦享版）的延伸阅读页面")
	require.Contains(t, text, "命中 1 页，显示 1 页")
}

func TestFieldToolsShowStatesInChinese(t *testing.T) {
	text, _ := rendered(t, "knowledge_get_fields", `{"entity_id":"B"}`)
	require.Contains(t, text, "乙保险（悦享版） · 年龄错误处理：已发布知识未收录（不代表材料没有）")
	require.Contains(t, text, "乙保险（悦享版） · 责任免除：材料明确没有")
	require.Contains(t, text, "乙保险（悦享版） · 宽限期：重新投保时宽限期为60日")
	for _, english := range []string{"：unknown", "：absent_explicitly", "：present"} {
		require.NotContains(t, text, english)
	}
	for _, tc := range []struct{ state, value, want string }{
		{"present", "20日", "产品 · 犹豫期：20日"},
		{"absent_explicitly", "", "产品 · 犹豫期：材料明确没有"},
		{"unknown", "", "产品 · 犹豫期：已发布知识未收录（不代表材料没有）"},
		{"disputed", "", "产品 · 犹豫期：disputed"},
	} {
		got := knowledge.FieldText(knowledge.Field{
			EntityName: "产品", FieldTitle: "犹豫期", State: tc.state, Value: tc.value,
		})
		require.True(t, strings.HasPrefix(got, tc.want), got)
	}
}

func TestSourceEntitiesNamesTheProductsCitingEachMaterial(t *testing.T) {
	got, err := knowledge.NewService(scopeReader{}).SourceEntities(context.Background(), tenant, space, scoped)
	require.NoError(t, err)
	require.Equal(t, map[string][]string{
		"kA": {"甲保险（经典版）"},
		"kB": {"乙保险（悦享版）"},
		"kS": {"甲保险（经典版）", "乙保险（悦享版）"},
		"kP": {"乙保险（悦享版）"},
	}, got, "navigation order, no duplicates, page evidence counts, malformed references are skipped")

	boom := &release.Error{Code: release.ErrorServiceUnavailable}
	_, err = knowledge.NewService(scopeReader{err: boom}).SourceEntities(context.Background(), tenant, space, scoped)
	require.ErrorIs(t, err, boom)
}
