package knowledge

import (
	"fmt"
	"html"
	"strconv"
	"strings"

	"github.com/Tencent/WeKnora/internal/types"
)

// fieldText renders a field for every chat surface (Agent, MCP and quick answers) in one wording:
// a present value as itself, and the two absences so that "not compiled" never reads as "the
// material has none" (QA1 §4.1). Any other state is shown as stored.
func fieldText(field Field) string {
	text := FieldTitle(field) + "："
	switch field.State {
	case "present":
		text += field.Value
	case "absent_explicitly":
		text += "材料明确没有"
	case "unknown":
		text += "已发布知识未收录（不代表材料没有）"
	default:
		text += field.State
		if field.Value != "" {
			text += "；" + field.Value
		}
	}
	if field.Origin != "" {
		text += "；来源性质：" + field.Origin
	}
	if field.Review != "" {
		text += "；审核方式：" + field.Review
	}
	for _, evidence := range field.Evidence {
		text += fmt.Sprintf("\n引文：%s（第 %d 页）", evidence.Quote, evidence.Page)
	}
	return text
}

func fieldToolResult(space, id string, fields []Field, notes []string, total int) *types.ToolResult {
	rows := make([]map[string]interface{}, 0, len(fields))
	notes = append([]string(nil), notes...)
	for _, field := range fields {
		content := fieldText(field)
		if len(field.Evidence) == 0 {
			notes = append(notes, content+"（无可回验出处，不作为审核来源）")
			continue
		}
		rows = append(rows, map[string]interface{}{
			"chunk_id":        "release:" + id + ":" + field.Slug,
			"knowledge_title": FieldTitle(field),
			"content":         content,
			"metadata": map[string]string{
				"source_tier": "release", "space_id": space, "release_id": id,
				"logical_slug": field.Slug, "evidence_index": "0",
			},
		})
	}
	return knowledgeResult(rows, notes, total)
}

func pageText(page Page) string {
	text := "模型整理（未逐条审核）：" + page.EntityName + " · " + page.Title
	if page.Summary != "" {
		text += "\n摘要：" + page.Summary
	}
	if page.Excerpt != "" {
		text += "\n" + page.Excerpt
	}
	for _, evidence := range page.Evidence {
		text += fmt.Sprintf("\n引文：%s（第 %d 页）", evidence.Quote, evidence.Page)
	}
	return text
}

// fieldScopeNote and pageScopeNote say what a literal search covered (QA1 §3.2), so that a miss
// or a truncated list is not read as the product lacking the item. scope is "" or "<name>的".
func fieldScopeNote(scope string, total, shown int) string {
	return fmt.Sprintf("检索范围：%s已发布字段中明确存在的值，按字面匹配；命中 %d 条，显示 %d 条。"+
		"没有命中或没有显示的，不代表材料没有；判断某产品有没有某项，用 knowledge_get_fields 读取该产品。",
		scope, total, shown)
}

func pageScopeNote(scope string, total, shown int) string {
	return fmt.Sprintf("检索范围：%s延伸阅读页面，每个词都须字面出现；命中 %d 页，显示 %d 页。没有命中不代表材料没有。",
		scope, total, shown)
}

// pageToolResult cites a page through its first valid evidence entry, by that entry's stored index;
// the given notes (a scope note) come before those of uncited pages.
func pageToolResult(space, id string, pages []Page, total int, notes []string) *types.ToolResult {
	rows := make([]map[string]interface{}, 0, len(pages))
	notes = append([]string(nil), notes...)
	for _, page := range pages {
		content := pageText(page)
		if len(page.Evidence) == 0 {
			notes = append(notes, content+"（无可回验出处，不作为出处）")
			continue
		}
		rows = append(rows, map[string]interface{}{
			"chunk_id":        "release:" + id + ":" + page.Slug,
			"knowledge_title": page.EntityName + " · " + page.Title,
			"content":         content,
			"metadata": map[string]string{
				"source_tier": "wiki_page", "space_id": space, "release_id": id,
				"logical_slug": page.Slug, "evidence_index": strconv.Itoa(page.Evidence[0].Index),
			},
		})
	}
	return knowledgeResult(rows, notes, total)
}

func knowledgeResult(rows []map[string]interface{}, notes []string, total int) *types.ToolResult {
	// The model's existing source renderer replaces Output when rows exist.
	// Keep uncited notes outside the first chunk, rather than granting them its handle.
	if len(rows) > 0 && len(notes) > 0 {
		rows[0]["knowledge_metadata"] = strings.Join(notes, "\n")
	}
	var text []string
	text = append(text, notes...)
	for _, row := range rows {
		text = append(text, row["content"].(string))
	}
	return &types.ToolResult{
		Success: true,
		Output:  "<knowledge_result>" + html.EscapeString(strings.Join(text, "\n")) + "</knowledge_result>",
		Data: map[string]interface{}{
			"display_type": "search_results", "results": rows, "count": len(rows), "total": total, "notes": notes,
		},
	}
}
