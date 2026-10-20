package knowledge

import (
	"fmt"
	"html"
	"strconv"
	"strings"

	"github.com/Tencent/WeKnora/internal/types"
)

func fieldText(field Field) string {
	text := field.EntityName + " · " + field.FieldTitle + "：" + field.State
	if field.Value != "" {
		text += "；" + field.Value
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
			"knowledge_title": field.EntityName + " · " + field.FieldTitle,
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

// pageToolResult cites a page through its first valid evidence entry, by that entry's stored index.
func pageToolResult(space, id string, pages []Page, total int) *types.ToolResult {
	rows := make([]map[string]interface{}, 0, len(pages))
	var notes []string
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
