package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"html"
	"sort"
	"strings"
	"unicode"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

type wikiReleaseSearchTool830G2 struct {
	metadata         types.Tool
	legacy           types.Tool
	knowledgeService interfaces.KnowledgeService
	releases         map[string]interfaces.ConceptAgentRelease830G2
	scopes           []WikiScope
}

type wikiReleaseReadPageTool830G2 struct {
	metadata         types.Tool
	legacy           types.Tool
	knowledgeService interfaces.KnowledgeService
	releases         map[string]interfaces.ConceptAgentRelease830G2
	scopes           []WikiScope
}

func NewWikiReleaseSearchTool830G2(
	wikiService interfaces.WikiPageService,
	knowledgeService interfaces.KnowledgeService,
	scopes []WikiScope,
	routes *WikiRouteResolver,
	turn *interfaces.ConceptAgentTurn830G2,
) types.Tool {
	managed, unmanaged := splitWikiReleaseScopes830G2(scopes, turn)
	metadata := NewWikiSearchTool(wikiService, knowledgeService, scopes, routes)
	var legacy types.Tool
	if len(unmanaged) > 0 {
		legacy = NewWikiSearchTool(wikiService, knowledgeService, unmanaged, routes)
	}
	return &wikiReleaseSearchTool830G2{
		metadata: metadata, legacy: legacy, knowledgeService: knowledgeService,
		releases: managed, scopes: append([]WikiScope(nil), scopes...),
	}
}

func NewWikiReleaseReadPageTool830G2(
	wikiService interfaces.WikiPageService,
	knowledgeService interfaces.KnowledgeService,
	scopes []WikiScope,
	routes *WikiRouteResolver,
	turn *interfaces.ConceptAgentTurn830G2,
) types.Tool {
	managed, unmanaged := splitWikiReleaseScopes830G2(scopes, turn)
	metadata := NewWikiReadPageTool(wikiService, knowledgeService, scopes, routes)
	var legacy types.Tool
	if len(unmanaged) > 0 {
		legacy = NewWikiReadPageTool(wikiService, knowledgeService, unmanaged, routes)
	}
	return &wikiReleaseReadPageTool830G2{
		metadata: metadata, legacy: legacy, knowledgeService: knowledgeService,
		releases: managed, scopes: append([]WikiScope(nil), scopes...),
	}
}

func (t *wikiReleaseSearchTool830G2) Name() string                { return t.metadata.Name() }
func (t *wikiReleaseSearchTool830G2) Description() string         { return t.metadata.Description() }
func (t *wikiReleaseSearchTool830G2) Parameters() json.RawMessage { return t.metadata.Parameters() }
func (t *wikiReleaseReadPageTool830G2) Name() string              { return t.metadata.Name() }
func (t *wikiReleaseReadPageTool830G2) Description() string       { return t.metadata.Description() }
func (t *wikiReleaseReadPageTool830G2) Parameters() json.RawMessage {
	return t.metadata.Parameters()
}

func splitWikiReleaseScopes830G2(
	scopes []WikiScope,
	turn *interfaces.ConceptAgentTurn830G2,
) (map[string]interfaces.ConceptAgentRelease830G2, []WikiScope) {
	managed := make(map[string]interfaces.ConceptAgentRelease830G2)
	unmanaged := make([]WikiScope, 0, len(scopes))
	for _, scope := range scopes {
		release, ok := conceptReleaseForScope830G2(turn, scope.KnowledgeBaseID)
		if !ok {
			unmanaged = append(unmanaged, scope)
			continue
		}
		managed[scope.KnowledgeBaseID] = release
	}
	return managed, unmanaged
}

func conceptReleaseForScope830G2(
	turn *interfaces.ConceptAgentTurn830G2,
	wikiKBID string,
) (interfaces.ConceptAgentRelease830G2, bool) {
	if turn == nil || turn.Releases == nil {
		return interfaces.ConceptAgentRelease830G2{}, false
	}
	release, ok := turn.Releases[wikiKBID]
	if !ok || release.WikiKBID != wikiKBID || release.ReleaseID == "" || release.ActivationEpoch == 0 {
		return interfaces.ConceptAgentRelease830G2{}, false
	}
	release.Members = append([]interfaces.ConceptAgentMember830G2(nil), release.Members...)
	for index := range release.Members {
		release.Members[index].Sources = append(
			[]interfaces.ConceptAgentSource830G2(nil), release.Members[index].Sources...,
		)
	}
	return release, true
}

func (t *wikiReleaseSearchTool830G2) Execute(
	ctx context.Context,
	args json.RawMessage,
) (*types.ToolResult, error) {
	var params struct {
		Query           any    `json:"query"`
		Queries         any    `json:"queries"`
		Limit           int    `json:"limit"`
		KnowledgeBaseID string `json:"knowledge_base_id"`
	}
	if err := json.Unmarshal(args, &params); err != nil {
		return &types.ToolResult{Success: false, Error: "Invalid parameters: " + err.Error()}, nil
	}
	queries := append(parseStringOrArray(params.Queries), parseStringOrArray(params.Query)...)
	if len(queries) == 0 {
		return &types.ToolResult{Success: false, Error: "Missing 'queries' parameter"}, nil
	}
	if params.Limit <= 0 {
		params.Limit = 10
	}
	if params.KnowledgeBaseID != "" && !wikiScopeContainsKB830G2(t.scopes, params.KnowledgeBaseID) {
		return &types.ToolResult{Success: false, Error: "knowledge_base_id is not within the current wiki scope"}, nil
	}

	outputs := make([]string, 0, len(queries)+1)
	foundKBs := make(map[string][]string)
	managedSelected := params.KnowledgeBaseID == "" || t.releases[params.KnowledgeBaseID].WikiKBID != ""
	if managedSelected {
		for _, query := range queries {
			output, err := t.searchManaged830G2(ctx, query, params.Limit, params.KnowledgeBaseID, foundKBs)
			if err != nil {
				return nil, err
			}
			outputs = append(outputs, output)
		}
	}
	if t.legacy != nil && (params.KnowledgeBaseID == "" || t.releases[params.KnowledgeBaseID].WikiKBID == "") {
		legacy, err := t.legacy.Execute(ctx, args)
		if err != nil {
			return nil, err
		}
		if legacy.Success {
			if legacy.Output != "" {
				outputs = append(outputs, legacy.Output)
			}
			mergeFoundKBs830G2(foundKBs, legacy.Data)
		} else if len(outputs) == 0 {
			return legacy, nil
		}
	}
	return &types.ToolResult{Success: true, Output: strings.Join(outputs, "\n\n"), Data: map[string]any{
		"found_kbs": foundKBs, "release_authorities": releaseAuthorities830G2(t.releases),
	}}, nil
}

func (t *wikiReleaseSearchTool830G2) searchManaged830G2(
	ctx context.Context,
	query string,
	limit int,
	onlyKB string,
	foundKBs map[string][]string,
) (string, error) {
	queryFolded := strings.ToLower(strings.TrimSpace(query))
	var body strings.Builder
	count := 0
	for _, kbID := range sortedReleaseKBIDs830G2(t.releases) {
		if onlyKB != "" && kbID != onlyKB {
			continue
		}
		release := t.releases[kbID]
		scope, ok := wikiScopeForKB830G2(t.scopes, kbID)
		if !ok {
			continue
		}
		perKB := 0
		for _, member := range release.Members {
			passes, err := conceptMemberPassesWikiScope830G2(ctx, member, scope, t.knowledgeService)
			if err != nil {
				return "", err
			}
			if !passes {
				continue
			}
			haystack := strings.ToLower(member.Kind + "\n" + member.MemberID + "\n" + member.Title + "\n" + member.Content)
			if queryFolded != "" && !strings.Contains(haystack, queryFolded) || perKB >= limit {
				continue
			}
			perKB++
			count++
			foundKBs[member.MemberID] = append(foundKBs[member.MemberID], kbID)
			fmt.Fprintf(&body, "<page release_id=\"%s\" activation_epoch=\"%d\">\n<knowledge_base_id>%s</knowledge_base_id>\n<release_id>%s</release_id>\n<activation_epoch>%d</activation_epoch>\n<member_id>%s</member_id>\n<owner_id>%s</owner_id>\n<link>[[%s|%s]]</link>\n<type>%s</type>\n<match_snippet>%s</match_snippet>\n%s</page>\n",
				xml830G2(release.ReleaseID), release.ActivationEpoch,
				xml830G2(kbID), xml830G2(release.ReleaseID), release.ActivationEpoch,
				xml830G2(member.MemberID), xml830G2(member.OwnerID), xml830G2(member.MemberID),
				xml830G2(member.Title), xml830G2(member.Kind), xml830G2(conceptSnippet830G2(member.Content, queryFolded)),
				renderSources830G2(member.Sources),
			)
		}
	}
	if count == 0 {
		return fmt.Sprintf(`<search_results count="0" query="%s" />`, xml830G2(query)), nil
	}
	return fmt.Sprintf(`<search_results count="%d" query="%s">`+"\n%s</search_results>", count, xml830G2(query), body.String()), nil
}

func (t *wikiReleaseReadPageTool830G2) Execute(
	ctx context.Context,
	args json.RawMessage,
) (*types.ToolResult, error) {
	var params struct {
		Slug  any `json:"slug"`
		Slugs any `json:"slugs"`
	}
	if err := json.Unmarshal(args, &params); err != nil {
		return &types.ToolResult{Success: false, Error: "Invalid parameters: " + err.Error()}, nil
	}
	slugs := dedupNonEmptyStrings(append(parseStringOrArray(params.Slugs), parseStringOrArray(params.Slug)...))
	if len(slugs) == 0 {
		return &types.ToolResult{Success: false, Error: "Missing 'slugs' parameter"}, nil
	}

	var outputs []string
	foundKBs := make(map[string][]string)
	for _, slug := range slugs {
		for _, kbID := range sortedReleaseKBIDs830G2(t.releases) {
			release := t.releases[kbID]
			scope, ok := wikiScopeForKB830G2(t.scopes, kbID)
			if !ok {
				continue
			}
			for _, member := range release.Members {
				if member.MemberID != slug {
					continue
				}
				passes, err := conceptMemberPassesWikiScope830G2(ctx, member, scope, t.knowledgeService)
				if err != nil {
					return nil, err
				}
				if !passes {
					continue
				}
				foundKBs[slug] = append(foundKBs[slug], kbID)
				outputs = append(outputs, renderManagedMember830G2(release, member))
			}
		}
	}
	if t.legacy != nil {
		legacy, err := t.legacy.Execute(ctx, args)
		if err != nil {
			return nil, err
		}
		if legacy.Success {
			if legacy.Output != "" {
				outputs = append(outputs, legacy.Output)
			}
			mergeFoundKBs830G2(foundKBs, legacy.Data)
		} else if len(outputs) == 0 {
			return legacy, nil
		}
	}
	if len(outputs) == 0 {
		return &types.ToolResult{Success: false, Error: "Wiki page not found"}, nil
	}
	return &types.ToolResult{Success: true, Output: strings.Join(outputs, "\n\n"), Data: map[string]any{
		"found_kbs": foundKBs, "release_authorities": releaseAuthorities830G2(t.releases),
	}}, nil
}

func renderManagedMember830G2(
	release interfaces.ConceptAgentRelease830G2,
	member interfaces.ConceptAgentMember830G2,
) string {
	return fmt.Sprintf("<wiki_release_page knowledge_base_id=\"%s\" release_id=\"%s\" activation_epoch=\"%d\" member_id=\"%s\" member_digest=\"%s\">\n<type>%s</type>\n<owner_id>%s</owner_id>\n<title>%s</title>\n<content>%s</content>\n%s</wiki_release_page>",
		xml830G2(release.WikiKBID), xml830G2(release.ReleaseID), release.ActivationEpoch,
		xml830G2(member.MemberID), xml830G2(member.MemberDigest), xml830G2(member.Kind),
		xml830G2(member.OwnerID), xml830G2(member.Title), xml830G2(member.Content),
		renderSources830G2(member.Sources),
	)
}

func renderSources830G2(sources []interfaces.ConceptAgentSource830G2) string {
	if len(sources) == 0 {
		return "<source_identities />\n"
	}
	var body strings.Builder
	body.WriteString("<source_identities>\n")
	for _, source := range sources {
		fmt.Fprintf(&body, "<source source_type=\"%s\" knowledge_id=\"%s\" revision_id=\"%s\" parse_attempt=\"%d\" block_id=\"%s\" page_number=\"%d\" source_hash=\"%s\" parse_hash=\"%s\" quote_hash=\"%s\" />\n",
			xml830G2(source.SourceType), xml830G2(source.KnowledgeID), xml830G2(source.RevisionID),
			source.ParseAttempt, xml830G2(source.BlockID), source.PageNumber, xml830G2(source.SourceHash),
			xml830G2(source.ParseHash), xml830G2(source.QuoteHash),
		)
	}
	body.WriteString("</source_identities>\n")
	return body.String()
}

func releaseAuthorities830G2(releases map[string]interfaces.ConceptAgentRelease830G2) []map[string]any {
	result := make([]map[string]any, 0, len(releases))
	for _, kbID := range sortedReleaseKBIDs830G2(releases) {
		release := releases[kbID]
		result = append(result, map[string]any{
			"wiki_kb_id": kbID, "space_id": release.SpaceID, "raw_kb_id": release.RawKBID,
			"release_id": release.ReleaseID, "activation_epoch": release.ActivationEpoch,
		})
	}
	return result
}

func sortedReleaseKBIDs830G2(releases map[string]interfaces.ConceptAgentRelease830G2) []string {
	ids := make([]string, 0, len(releases))
	for id := range releases {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

func wikiScopeContainsKB830G2(scopes []WikiScope, kbID string) bool {
	_, ok := wikiScopeForKB830G2(scopes, kbID)
	return ok
}

func wikiScopeForKB830G2(scopes []WikiScope, kbID string) (WikiScope, bool) {
	for _, scope := range scopes {
		if scope.KnowledgeBaseID == kbID {
			return scope, true
		}
	}
	return WikiScope{}, false
}

func conceptMemberPassesWikiScope830G2(
	ctx context.Context,
	member interfaces.ConceptAgentMember830G2,
	scope WikiScope,
	knowledgeService interfaces.KnowledgeService,
) (bool, error) {
	page := &types.WikiPage{KnowledgeBaseID: scope.KnowledgeBaseID}
	for _, source := range member.Sources {
		if source.KnowledgeID != "" {
			page.SourceRefs = append(page.SourceRefs, source.KnowledgeID)
		}
	}
	var fetchTags knowledgeTagsFetcher
	if knowledgeService != nil {
		fetchTags = knowledgeService.GetKnowledgeTags
	}
	return pagePassesWikiScope(ctx, page, scope, fetchTags)
}

func conceptSnippet830G2(content, query string) string {
	if query == "" {
		return truncateRunes(content, 240)
	}
	originalRunes := []rune(content)
	lowerRunes := make([]rune, len(originalRunes))
	for index, value := range originalRunes {
		lowerRunes[index] = unicode.ToLower(value)
	}
	queryRunes := []rune(strings.ToLower(query))
	index := runeSliceIndex830G2(lowerRunes, queryRunes)
	if index < 0 {
		return truncateRunes(content, 240)
	}
	start := index - 80
	if start < 0 {
		start = 0
	}
	end := index + len(queryRunes) + 120
	if end > len(originalRunes) {
		end = len(originalRunes)
	}
	return string(originalRunes[start:end])
}

func runeSliceIndex830G2(haystack, needle []rune) int {
	if len(needle) == 0 {
		return 0
	}
	for start := 0; start+len(needle) <= len(haystack); start++ {
		matched := true
		for offset := range needle {
			if haystack[start+offset] != needle[offset] {
				matched = false
				break
			}
		}
		if matched {
			return start
		}
	}
	return -1
}

func mergeFoundKBs830G2(destination map[string][]string, data map[string]any) {
	if data == nil {
		return
	}
	source, ok := data["found_kbs"].(map[string][]string)
	if !ok {
		return
	}
	for slug, kbIDs := range source {
		destination[slug] = append(destination[slug], kbIDs...)
	}
}

func xml830G2(value string) string { return html.EscapeString(value) }
