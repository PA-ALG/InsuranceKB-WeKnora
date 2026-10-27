package knowledge

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"sort"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

var knowledgeToolDescriptions = map[string]string{
	"knowledge_find_entity":   "查找本轮固定发布版本中的产品，按名称、别名或编号查找。",
	"knowledge_get_fields":    "读取产品字段、三态和出处。请先查产品；fields 可用字段名或谓词，省略时取全部。",
	"knowledge_search_fields": "按关键词搜索本轮已发布字段（字面匹配，只搜明确存在的字段值），可用 entity_id 限定产品。",
	"knowledge_get_concept":   "读取模型补充的概念说明，以及同一发布版本可回验的字段出处。",
	"knowledge_search_pages": "搜索本轮固定发布版本中的延伸阅读页面（模型整理，未逐条审核），可用 entity_id 限定产品。" +
		"字段查不到的条件、例外和流程说明可用它补充。",
}

type knowledgeTool struct {
	service  *Service
	tenant   uint64
	name     string
	releases map[string]string
}

// NewTools derives read-only tools from an already authorized Wiki selection.
// The copied scope is request-local and never accepts a model-selected release.
func NewTools(service *Service, tenantID uint64, releases map[string]string) []types.Tool {
	scopes := make(map[string]string, len(releases))
	for space, id := range releases {
		scopes[space] = id
	}
	out := make([]types.Tool, 0, 5)
	for _, name := range []string{
		"knowledge_find_entity", "knowledge_get_fields", "knowledge_search_fields", "knowledge_get_concept",
		"knowledge_search_pages",
	} {
		out = append(out, &knowledgeTool{service: service, tenant: tenantID, name: name, releases: scopes})
	}
	return out
}

func (t *knowledgeTool) Name() string        { return t.name }
func (t *knowledgeTool) Description() string { return knowledgeToolDescriptions[t.name] }
func (t *knowledgeTool) Parameters() json.RawMessage {
	spaces := make([]string, 0, len(t.releases))
	for space := range t.releases {
		spaces = append(spaces, space)
	}
	sort.Strings(spaces)
	properties := map[string]any{"space_id": map[string]any{"type": "string", "enum": spaces}}
	required := []string{}
	switch t.name {
	case "knowledge_get_fields":
		properties["entity_id"] = map[string]any{"type": "string"}
		required = append(required, "entity_id")
		properties["fields"] = map[string]any{"type": "array", "items": map[string]any{"type": "string"}}
	case "knowledge_get_concept":
		properties["name"] = map[string]any{"type": "string"}
		required = append(required, "name")
	case "knowledge_search_fields", "knowledge_search_pages":
		properties["query"] = map[string]any{"type": "string"}
		properties["entity_id"] = map[string]any{"type": "string"}
		required = append(required, "query")
	default:
		properties["query"] = map[string]any{"type": "string"}
		required = append(required, "query")
	}
	if len(spaces) != 1 {
		required = append(required, "space_id")
	}
	schema, _ := json.Marshal(map[string]any{
		"type": "object", "properties": properties, "required": required, "additionalProperties": false,
	})
	return schema
}

type knowledgeArguments struct {
	SpaceID  string   `json:"space_id"`
	Query    string   `json:"query"`
	EntityID string   `json:"entity_id"`
	Fields   []string `json:"fields"`
	Name     string   `json:"name"`
}

func (t *knowledgeTool) Execute(ctx context.Context, raw json.RawMessage) (*types.ToolResult, error) {
	tenant, ok := types.TenantIDFromContext(ctx)
	if !ok || tenant != t.tenant || t.tenant == 0 {
		return nil, toolAccess("tool execution tenant differs from the fixed scope")
	}
	var args knowledgeArguments
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&args); err != nil {
		return nil, err
	}
	if err := decoder.Decode(new(any)); err != io.EOF {
		return nil, &release.Error{Code: release.ErrorInvalidRequest, Detail: "one argument object is required"}
	}
	if args.SpaceID == "" && len(t.releases) == 1 {
		for space := range t.releases {
			args.SpaceID = space
		}
	}
	id, allowed := t.releases[args.SpaceID]
	if !allowed {
		return nil, toolAccess("select one of this turn's Wiki Spaces")
	}
	if err := validateRead(ctx, tenant, args.SpaceID, id); err != nil {
		return nil, err
	}
	if t.service == nil {
		return nil, &release.Error{Code: release.ErrorServiceUnavailable, Detail: "knowledge service is unavailable"}
	}
	// One execution observes one immutable release view, including concept refs.
	// A subsequent tool invocation reads again through the production Reader.
	service := NewService(&toolRead{source: t.service.reader, tenant: tenant, space: args.SpaceID, id: id})
	var fields []Field
	var notes []string
	total := 0
	switch t.name {
	case "knowledge_search_pages":
		index, err := service.read(ctx, tenant, args.SpaceID, id)
		if err != nil {
			return nil, err
		}
		pages, total, err := index.searchPages(ctx, args.Query, args.EntityID, 0)
		if err != nil {
			return nil, err
		}
		if len(searchTerms(args.Query)) > 0 {
			notes = append(notes, pageScopeNote(index.pageScope(args.EntityID), total, len(pages)))
		}
		return pageToolResult(args.SpaceID, id, pages, total, notes), nil
	case "knowledge_find_entity":
		entities, err := service.FindEntities(ctx, tenant, args.SpaceID, id, args.Query, 0)
		if err != nil {
			return nil, err
		}
		for _, entity := range entities {
			notes = append(notes, "产品编号："+entity.EntityID+"；名称："+entity.Name)
		}
		total = len(entities)
	case "knowledge_get_fields":
		var err error
		fields, err = service.EntityFields(ctx, tenant, args.SpaceID, id, args.EntityID, args.Fields)
		if err != nil {
			return nil, err
		}
		total = len(fields)
	case "knowledge_search_fields":
		index, err := service.read(ctx, tenant, args.SpaceID, id)
		if err != nil {
			return nil, err
		}
		fields, total, err = index.searchFields(ctx, args.Query, args.EntityID, 0)
		if err != nil {
			return nil, err
		}
		if len(searchTerms(args.Query)) > 0 {
			notes = append(notes, fieldScopeNote(index.fieldScope(args.EntityID), total, len(fields)))
		}
	case "knowledge_get_concept":
		concept, err := service.Concept(ctx, tenant, args.SpaceID, id, args.Name)
		if err != nil {
			return nil, err
		}
		notes = append(notes, "模型补充（概念说明）："+concept.Title, concept.Definition, concept.Explanation)
		var slugs []string
		for _, statement := range concept.Statements {
			notes = append(notes, "模型补充（概念说明）："+statement.Text)
			slugs = append(slugs, statement.Refs...)
		}
		if concept.OmittedStatements > 0 {
			notes = append(notes, "部分陈述因过时或不可见被略去。")
		}
		fields, err = service.fieldsForSlugs(ctx, tenant, args.SpaceID, id, slugs)
		if err != nil {
			return nil, err
		}
		total = len(fields)
	}
	return fieldToolResult(args.SpaceID, id, fields, notes, total), nil
}

func toolAccess(detail string) error {
	return &release.Error{Code: release.ErrorReleaseAccessDenied, Detail: detail}
}

type toolRead struct {
	source    Reader
	tenant    uint64
	space, id string
	loaded    bool
	value     release.Release
	err       error
}

func (r *toolRead) ReleaseByID(ctx context.Context, tenant uint64, space, id string) (release.Release, error) {
	if tenant != r.tenant || space != r.space || id != r.id {
		return release.Release{}, toolAccess("read is outside this tool execution")
	}
	if !r.loaded {
		r.loaded = true
		if missingReader(r.source) {
			r.err = &release.Error{Code: release.ErrorServiceUnavailable, Detail: "knowledge reader is unavailable"}
		} else {
			r.value, r.err = r.source.ReleaseByID(ctx, tenant, space, id)
		}
	}
	return r.value, r.err
}
