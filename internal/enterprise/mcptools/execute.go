package mcptools

import (
	"context"
	"encoding/json"
	"slices"
	"sort"
	"strings"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/mark3labs/mcp-go/mcp"
)

func execute(
	ctx context.Context, deps Deps, name string, schema argumentSchema, value any,
) (*mcp.CallToolResult, error) {
	if ctx == nil {
		return nil, accessDenied()
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if deps.Caller == nil {
		return nil, accessDenied()
	}
	caller, ok := deps.Caller(ctx)
	if !ok || caller.TenantID == 0 || caller.Readable == nil {
		return nil, accessDenied()
	}
	args, err := parseArguments(value, schema)
	if err != nil {
		return nil, err
	}
	if deps.Spaces == nil {
		return nil, unavailable()
	}
	if name == "knowledge_list_spaces" {
		return listSpaces(ctx, deps, caller)
	}
	space := args.string("space_id")
	if !slices.Contains(deps.Spaces.SpaceIDs(caller.TenantID), space) || !readable(deps, caller, space) {
		return nil, accessDenied()
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	id := args.string("release_id")
	if _, explicit := args["release_id"]; !explicit {
		id, err = activeRelease(ctx, deps, caller, space)
		if err != nil {
			return nil, err
		}
		if id == "" {
			return nil, &release.Error{Code: release.ErrorReleaseNotFound}
		}
	}
	if name == "knowledge_read_citation" {
		return readCitation(ctx, deps, caller, space, id, args)
	}
	delete(args, "release_id")
	raw, err := json.Marshal(args)
	if err != nil {
		return nil, invalidArguments()
	}
	for _, tool := range knowledge.NewTools(deps.Knowledge, caller.TenantID, map[string]string{space: id}) {
		if tool.Name() != name {
			continue
		}
		result, err := tool.Execute(ctx, raw)
		if err != nil {
			return nil, err
		}
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		if result == nil || !result.Success {
			return nil, unavailable()
		}
		data := make(map[string]any, len(result.Data)+2)
		for key, value := range result.Data {
			data[key] = value
		}
		data["space_id"], data["release_id"] = space, id
		return mcp.NewToolResultStructured(data, result.Output), nil
	}
	return nil, invalidArguments()
}

func readable(deps Deps, caller Caller, space string) bool {
	raw, wiki, ok := deps.Spaces.KnowledgeBases(caller.TenantID, space)
	return ok && raw != "" && wiki != "" && caller.Readable(raw) && caller.Readable(wiki)
}

func activeRelease(ctx context.Context, deps Deps, caller Caller, space string) (string, error) {
	if err := ctx.Err(); err != nil {
		return "", err
	}
	if deps.Heads == nil {
		return "", unavailable()
	}
	id, err := deps.Heads.ActiveRelease(ctx, caller.TenantID, space)
	if err != nil {
		return "", err
	}
	if err := ctx.Err(); err != nil {
		return "", err
	}
	if strings.TrimSpace(id) == "" {
		return "", nil
	}
	if strings.EqualFold(strings.TrimSpace(id), "active") {
		return "", unavailable()
	}
	return id, nil
}

func listSpaces(ctx context.Context, deps Deps, caller Caller) (*mcp.CallToolResult, error) {
	ids := append([]string(nil), deps.Spaces.SpaceIDs(caller.TenantID)...)
	sort.Strings(ids)
	spaces := make([]map[string]string, 0, len(ids))
	for _, space := range slices.Compact(ids) {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		if !readable(deps, caller, space) {
			continue
		}
		id, err := activeRelease(ctx, deps, caller, space)
		if err != nil {
			return nil, err
		}
		if id != "" {
			spaces = append(spaces, map[string]string{"space_id": space, "release_id": id})
		}
	}
	data := map[string]any{"spaces": spaces}
	return mcp.NewToolResultStructuredOnly(data), nil
}

func readCitation(
	ctx context.Context, deps Deps, caller Caller, space, id string, args arguments,
) (*mcp.CallToolResult, error) {
	if deps.Citations == nil {
		return nil, unavailable()
	}
	index, _ := nonnegativeInteger(args["evidence"])
	citation, err := deps.Citations.Citation(ctx, caller.TenantID, space, id, args.string("member"), index)
	if err != nil {
		return nil, err
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	return mcp.NewToolResultStructuredOnly(map[string]any{
		"document": citation.Document, "page": citation.Page, "quote": citation.Quote,
	}), nil
}

func accessDenied() error { return &release.Error{Code: release.ErrorReleaseAccessDenied} }
func unavailable() error  { return &release.Error{Code: release.ErrorServiceUnavailable} }
