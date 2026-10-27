package chatsource

import (
	"context"
	"encoding/json"
	"encoding/xml"
	"errors"
	"fmt"
	"strings"

	"github.com/Tencent/WeKnora/internal/types"
)

type searchTool struct {
	types.Tool
	resolver *Resolver
	turn     Turn
	tenantID uint64
	chunks   ChunkReader
}

// WrapTool holds the resolved turn for every search invocation in this Agent run.
func WrapTool(inner types.Tool, resolver *Resolver, turn Turn, tenantID uint64, chunks ChunkReader) types.Tool {
	if len(turn.RawKnowledge) == 0 {
		return inner
	}
	return &searchTool{Tool: inner, resolver: resolver, turn: turn, tenantID: tenantID, chunks: chunks}
}

func (t *searchTool) Execute(ctx context.Context, args json.RawMessage) (*types.ToolResult, error) {
	if missing(t.Tool) {
		return nil, errors.New("search tool is unavailable")
	}
	result, err := t.Tool.Execute(ctx, args)
	if err != nil || result == nil {
		return nil, err
	}
	if !result.Success {
		return result, nil
	}
	rows, ok := searchRows(result.Data["results"])
	if !ok {
		return nil, errors.New("search tool returned unreadable results")
	}
	search := make([]*types.SearchResult, 0, len(rows))
	for index, row := range rows {
		id := stringField(row, "chunk_id")
		if id == "" {
			id = stringField(row, "faq_id")
		}
		search = append(search, &types.SearchResult{
			ID: id, Seq: index,
			KnowledgeID: stringField(row, "knowledge_id"), KnowledgeBaseID: stringField(row, "knowledge_base_id"),
		})
	}
	filtered, err := t.resolver.Filter(ctx, t.tenantID, t.turn, t.chunks, search)
	if err != nil {
		return nil, err
	}
	kept, counts := make([]map[string]interface{}, 0, len(filtered)), map[string]int{}
	for _, item := range filtered {
		row := rows[item.Seq]
		if item.Metadata["source_tier"] == "raw_text" {
			cloned := make(map[string]interface{}, len(row)+1)
			for key, value := range row {
				cloned[key] = value
			}
			metadata := copyRowMetadata(row["metadata"])
			metadata["source_tier"], metadata["release_id"] = "raw_text", item.Metadata["release_id"]
			// Native rows are fresh on every execution; their own entity_names are untrusted.
			delete(metadata, entityNamesKey)
			if names, ok := t.turn.rawLabel(stringField(row, "knowledge_id")); ok {
				metadata[entityNamesKey] = names
				cloned["knowledge_title"] = labelledTitle(names, stringField(row, "knowledge_title"))
			}
			cloned["metadata"] = metadata
			row = cloned
		}
		kept = append(kept, row)
		counts[stringField(row, "knowledge_base_id")]++
	}
	cloned := *result
	cloned.Data = make(map[string]interface{}, len(result.Data))
	for key, value := range result.Data {
		cloned.Data[key] = value
	}
	cloned.Data["results"], cloned.Data["count"], cloned.Data["kb_counts"] = kept, len(kept), counts
	cloned.Output, err = renderSearch(kept, cloned.Data)
	if err != nil {
		return nil, err
	}
	return &cloned, nil
}

// Cleanup keeps the native tool's optional resource lifecycle intact.
func (t *searchTool) Cleanup(ctx context.Context) {
	if tool, ok := t.Tool.(types.Cleanable); ok {
		tool.Cleanup(ctx)
	}
}

func searchRows(value any) ([]map[string]interface{}, bool) {
	switch rows := value.(type) {
	case []map[string]interface{}:
		return rows, true
	case []interface{}:
		out := make([]map[string]interface{}, 0, len(rows))
		for _, raw := range rows {
			row, ok := raw.(map[string]interface{})
			if !ok {
				return nil, false
			}
			out = append(out, row)
		}
		return out, true
	default:
		return nil, false
	}
}

func copyRowMetadata(value any) map[string]interface{} {
	out := map[string]interface{}{}
	switch metadata := value.(type) {
	case map[string]string:
		for key, value := range metadata {
			out[key] = value
		}
	case map[string]interface{}:
		for key, value := range metadata {
			out[key] = value
		}
	}
	return out
}

func stringField(row map[string]interface{}, field string) string {
	value, _ := row[field].(string)
	return value
}

// Rebuild from retained rows only: the native XML may contain removed bodies in
// document metadata or snippets as well as in its main content elements.
func renderSearch(rows []map[string]interface{}, data map[string]interface{}) (string, error) {
	var output strings.Builder
	fmt.Fprintf(&output, "<search_results count=\"%d\" mode=\"%s\">\n<query>%s</query>\n",
		len(rows), escaped(stringField(data, "mode")), escaped(stringField(data, "query")))
	for index, row := range rows {
		tag, key := "chunk", "chunk_id"
		if stringField(row, key) == "" {
			tag, key = "faq", "faq_id"
		}
		fmt.Fprintf(&output, "<%s rank=\"%d\" %s=\"%s\" knowledge_id=\"%s\" knowledge_base_id=\"%s\">\n",
			tag, index+1, key, escaped(stringField(row, key)),
			escaped(stringField(row, "knowledge_id")), escaped(stringField(row, "knowledge_base_id")))
		attributes := make(map[string]interface{}, len(row))
		for key, value := range row {
			if key != "content" {
				attributes[key] = value
			}
		}
		raw, err := json.Marshal(attributes)
		if err != nil {
			return "", err
		}
		fmt.Fprintf(&output, "<attributes>%s</attributes>\n<content>%s</content>\n</%s>\n",
			escaped(string(raw)), escaped(stringField(row, "content")), tag)
	}
	output.WriteString("</search_results>")
	return output.String(), nil
}

func escaped(value string) string {
	var out strings.Builder
	_ = xml.EscapeText(&out, []byte(value))
	return out.String()
}
