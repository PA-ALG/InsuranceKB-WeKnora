// SK-3 acceptance: method knowledge in the read projection (Spec docs/design/slices/SK-3-销售方法阅读与问答.md
// §1, §3). Protected file: written by Claude.
//
// A method is an entity whose type a presentation profile with knowledge_class "method" serves; that
// profile titles its fields even when the entity's labels also meet a product profile, and its
// reading note and notices are the only method wording a field text carries. List values cite each
// item with the evidence at its position. Product-only paths (named products, raw passage owners)
// never take a method. RED until SK-3 implements it.
package knowledge_test

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

const (
	methodNote  = "销售方法（培训材料，非产品事实）：只用于怎么讲。"
	productInfo = "其中的产品信息以条款为准。"
)

var (
	methodSHA  = strings.Repeat("ab", 32)
	methodRefA = "source:v1:km1:1:" + methodSHA
	methodRefB = "source:v1:km2:1:" + methodSHA
	productRef = "source:v1:kp:1:" + methodSHA
)

func at(ref, quote string, page int) map[string]any {
	return map[string]any{"quote": quote, "source_ref": ref, "locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": page}}
}

func methodProfile() release.Member {
	return member("presentation_profile", "presentation/sales_method", map[string]any{
		"profile_id": "sales_method", "display_name": "销售方法", "entity_types": []string{"sales_method"},
		"knowledge_class": "method", "reading_note": methodNote, "notices": map[string]string{"product_info": productInfo},
		"sections": []map[string]any{{"section_key": "method", "display_name": "销售方法", "fields": []map[string]any{
			{"field_key": "method_summary", "short_title": "方法摘要"},
			{"field_key": "method_steps", "short_title": "步骤"},
			{"field_key": "key_phrases", "short_title": "关键句"},
		}}},
	})
}

func methodEntity(id string, labels []string, notice string, names ...string) release.Member {
	identifiers := map[string]any{}
	if notice != "" {
		identifiers["notice"] = notice
	}
	return member("entity", "entity/"+id, map[string]any{
		"entity_id": id, "entity_type": "sales_method", "names": names, "classification_labels": labels,
		"identifiers": identifiers,
	})
}

func productWithFamily(id, name, family string) release.Member {
	return member("entity", "entity/"+id, map[string]any{
		"entity_id": id, "entity_type": "product", "names": []string{name}, "classification_labels": []string{"medical"},
		"product_family": map[string]any{"key": family, "display_name": "甲系列"},
	})
}

// methodMembers holds two products, a method tied to the first product's family and labelled
// medical (whose product profile would title method_steps differently), and a general method.
func methodMembers() []release.Member {
	return []release.Member{
		member("navigation", "navigation/enterprise", map[string]any{
			"navigation_id": "enterprise", "navigation_version": "v2", "overview_fields": []string{"cooling_off_period"},
			"question_intents": map[string]any{"method": [][]string{{"怎么讲"}}, "sales": [][]string{{"推荐"}}},
			"domains": []map[string]any{
				{"domain_key": "product", "display_name": "产品", "entity_types": []string{"product"},
					"groups": []map[string]any{{"group_key": "medical", "display_name": "医疗", "classification_labels": []string{"medical"}}}},
				{"domain_key": "sales_method", "display_name": "销售方法", "entity_types": []string{"sales_method"},
					"groups": []map[string]any{
						{"group_key": "medical", "display_name": "医疗", "classification_labels": []string{"medical"}},
						{"group_key": "general", "display_name": "通用", "classification_labels": []string{"scope:general"}},
					}},
			},
		}),
		profile("medical", [2]string{"cooling_off_period", "犹豫期"}, [2]string{"method_steps", "产品步骤"}),
		methodProfile(),
		productWithFamily("M1", "甲医疗保险", "fam"),
		entity("M2", []string{"medical"}, "乙医疗保险"),
		methodEntity("sm-1", []string{"medical", "family:fam"}, "product_info", "需求分析三步法"),
		methodEntity("sm-2", []string{"scope:general"}, "", "异议处理法"),
		claim("M1", "cooling_off_period", "present", "15日", at(productRef, "犹豫期15日", 1)),
		claim("M2", "cooling_off_period", "present", "20日", at(productRef, "犹豫期20日", 2)),
		claim("sm-1", "method_summary", "present", "先问需求再讲产品", at(methodRefA, "先问需求", 2)),
		claim("sm-1", "method_steps", "present", []string{"问家庭", "讲保障"},
			at(methodRefA, "问家庭", 3), at(methodRefA, "讲保障", 4)),
		claim("sm-1", "key_phrases", "unknown", nil),
		claim("sm-2", "method_summary", "present", "处理客户异议的方法", at(methodRefB, "处理客户异议", 1)),
	}
}

func methodService() *knowledge.Service { return knowledge.NewService(membersReader(methodMembers())) }

func fieldBySlug(t *testing.T, fields []knowledge.Field, slug string) knowledge.Field {
	t.Helper()
	for _, field := range fields {
		if field.Slug == slug {
			return field
		}
	}
	t.Fatalf("missing field %s in %v", slug, slugs(fields))
	return knowledge.Field{}
}

func TestMethodFieldsTakeTheirTitlesFromTheMethodProfileAndAlignItems(t *testing.T) {
	ctx := context.Background()
	fields, err := methodService().EntityFields(ctx, tenant, space, pinned, "sm-1", nil)
	require.NoError(t, err)
	require.Equal(t, []string{"sm-1/method_summary", "sm-1/method_steps", "sm-1/key_phrases"}, slugs(fields),
		"method fields follow the method profile's order")
	titles := []string{}
	for _, field := range fields {
		titles = append(titles, field.FieldTitle)
		require.True(t, field.Method, field.Slug)
	}
	require.Equal(t, []string{"方法摘要", "步骤", "关键句"}, titles, "not the medical product profile's 产品步骤")

	steps := fieldBySlug(t, fields, "sm-1/method_steps")
	require.Equal(t, []string{"问家庭", "讲保障"}, steps.Items)
	require.Equal(t, []int{3, 4}, []int{steps.Evidence[0].Page, steps.Evidence[1].Page})
	require.Nil(t, fieldBySlug(t, fields, "sm-1/method_summary").Items, "a text value has no items")

	products, err := methodService().EntityFields(ctx, tenant, space, pinned, "M1", nil)
	require.NoError(t, err)
	require.Len(t, products, 1)
	require.False(t, products[0].Method)
	require.Equal(t, "犹豫期", products[0].FieldTitle)
}

// A list whose evidence does not line up (published before the check) keeps its value, without items.
func TestAMisalignedMethodListHasNoItems(t *testing.T) {
	members := append(methodMembers(), claim("sm-2", "method_steps", "present", []string{"一", "二"},
		at(methodRefB, "一", 1)))
	fields, err := knowledge.NewService(membersReader(members)).EntityFields(
		context.Background(), tenant, space, pinned, "sm-2", []string{"method_steps"})
	require.NoError(t, err)
	require.Len(t, fields, 1)
	require.True(t, fields[0].Method)
	require.Nil(t, fields[0].Items)
	require.Equal(t, "一；二", fields[0].Value)
}

func TestMethodEntitiesCarryTheirKindAndNotice(t *testing.T) {
	ctx := context.Background()
	found, err := methodService().FindEntities(ctx, tenant, space, pinned, "需求分析三步法", 0)
	require.NoError(t, err)
	require.NotEmpty(t, found)
	require.Equal(t, "sm-1", found[0].EntityID)
	require.Equal(t, "sales_method", found[0].Kind)
	require.True(t, found[0].Method)
	require.Equal(t, "product_info", found[0].Notice)

	found, err = methodService().FindEntities(ctx, tenant, space, pinned, "甲医疗保险", 0)
	require.NoError(t, err)
	require.Equal(t, "M1", found[0].EntityID)
	require.Equal(t, "product", found[0].Kind)
	require.False(t, found[0].Method)
}

func TestMethodFieldTextLeadsWithTheProfileNoteAndCitesEachItem(t *testing.T) {
	ctx := context.Background()
	fields, err := methodService().EntityFields(ctx, tenant, space, pinned, "sm-1", nil)
	require.NoError(t, err)
	require.Equal(t, methodNote+productInfo+"\n需求分析三步法 · 步骤：\n"+
		"1. 问家庭（引文：问家庭，第 3 页）\n2. 讲保障（引文：讲保障，第 4 页）\n"+
		"来源性质：SOURCE_SUPPORTED；审核方式：machine",
		knowledge.FieldText(fieldBySlug(t, fields, "sm-1/method_steps")))
	require.Equal(t, methodNote+productInfo+"\n需求分析三步法 · 方法摘要：先问需求再讲产品；"+
		"来源性质：SOURCE_SUPPORTED；审核方式：machine\n引文：先问需求（第 2 页）",
		knowledge.FieldText(fieldBySlug(t, fields, "sm-1/method_summary")))

	general, err := methodService().EntityFields(ctx, tenant, space, pinned, "sm-2", nil)
	require.NoError(t, err)
	require.True(t, strings.HasPrefix(knowledge.FieldText(general[0]), methodNote+"\n异议处理法 · 方法摘要："),
		"no notice without an entity notice")

	products, err := methodService().EntityFields(ctx, tenant, space, pinned, "M1", nil)
	require.NoError(t, err)
	require.Equal(t, "甲医疗保险 · 犹豫期：15日；来源性质：SOURCE_SUPPORTED；审核方式：machine\n引文：犹豫期15日（第 1 页）",
		knowledge.FieldText(products[0]), "a product field's text is unchanged")
}

func TestProductOnlyPathsNeverTakeAMethod(t *testing.T) {
	ctx := context.Background()
	named, err := methodService().QuestionProducts(ctx, tenant, space, pinned, "需求分析三步法和甲医疗保险的犹豫期")
	require.NoError(t, err)
	got := []string{}
	for _, product := range named {
		got = append(got, product.EntityID)
	}
	require.Equal(t, []string{"M1"}, got)

	owners, err := methodService().SourceEntities(ctx, tenant, space, pinned)
	require.NoError(t, err)
	require.Equal(t, []string{"甲医疗保险", "乙医疗保险"}, owners["kp"])
	require.NotContains(t, owners, "km1", "a training material is no product's material")
	require.NotContains(t, owners, "km2")
}

func TestToolsDescribeMethodsWithTheirNoteAndMarkTheirRows(t *testing.T) {
	s := methodService()
	bound := map[string]string{space: pinned}
	result, err := tool(t, s, "knowledge_find_entity", bound).Execute(toolContext(), json.RawMessage(`{"query":"需求分析三步法"}`))
	require.NoError(t, err)
	require.Contains(t, result.Output, "编号：sm-1；名称：需求分析三步法；标签：medical、family:fam；"+methodNote)

	result, err = tool(t, s, "knowledge_find_entity", bound).Execute(toolContext(), json.RawMessage(`{"query":"甲医疗保险"}`))
	require.NoError(t, err)
	require.Contains(t, result.Output, "产品编号：M1；名称：甲医疗保险；系列：甲系列", "a product's line is unchanged")

	result, err = tool(t, s, "knowledge_get_fields", bound).Execute(toolContext(), json.RawMessage(`{"entity_id":"sm-1"}`))
	require.NoError(t, err)
	rows := result.Data["results"].([]map[string]interface{})
	require.Len(t, rows, 2, "the unknown key_phrases has no evidence and stays a note")
	require.Equal(t, map[string]string{
		"source_tier": "release", "space_id": space, "release_id": pinned,
		"logical_slug": "sm-1/method_summary", "evidence_index": "0", "knowledge_class": "method",
	}, rows[0]["metadata"])
	require.True(t, strings.HasPrefix(rows[0]["content"].(string), methodNote))
}
