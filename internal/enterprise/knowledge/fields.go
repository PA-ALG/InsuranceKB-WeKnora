package knowledge

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// EntityFields retains every Claim, including distinct Claims for the same predicate.
func (s *Service) EntityFields(
	ctx context.Context, tenantID uint64, spaceID, releaseID, entityID string, fields []string,
) ([]Field, error) {
	index, err := s.read(ctx, tenantID, spaceID, releaseID)
	if err != nil {
		return nil, err
	}
	entity, ok := index.entity(entityID)
	if !ok {
		return nil, &release.Error{Code: "ENTITY_NOT_FOUND", Detail: "entity is unavailable at the named release"}
	}
	all := index.fields(entity)
	if len(fields) == 0 {
		return all, ctx.Err()
	}
	selected := map[string]bool{}
	for _, item := range fields {
		item = normalize(item)
		if item == "" {
			continue
		}
		exact := false
		for _, field := range all {
			if item == normalize(field.FieldKey) || item == normalize(field.FieldTitle) {
				selected[field.Slug], exact = true, true
			}
		}
		if exact {
			continue
		}
		pairs := bigrams(item)
		for _, field := range all {
			titlePairs := bigrams(normalize(field.FieldTitle))
			if len(titlePairs) > 0 && sharedBigrams(titlePairs, pairs) == len(titlePairs) {
				selected[field.Slug] = true
			}
		}
	}
	out := []Field{}
	for _, field := range all {
		if selected[field.Slug] {
			out = append(out, field)
		}
	}
	return out, ctx.Err()
}

// SearchFields follows the published UI's whitespace-token and navigation ordering. A non-empty
// entityID limits the search to that entity before the limit applies; an unknown entity is
// ENTITY_NOT_FOUND, as for EntityFields.
func (s *Service) SearchFields(
	ctx context.Context, tenantID uint64, spaceID, releaseID, query, entityID string, limit int,
) ([]Field, int, error) {
	index, err := s.read(ctx, tenantID, spaceID, releaseID)
	if err != nil {
		return nil, 0, err
	}
	return index.searchFields(ctx, query, entityID, limit)
}

func (index *releaseIndex) searchFields(ctx context.Context, query, entityID string, limit int) ([]Field, int, error) {
	entities := index.orderedEntities()
	if entityID != "" {
		entity, ok := index.entity(entityID)
		if !ok {
			return nil, 0, &release.Error{
				Code: "ENTITY_NOT_FOUND", Detail: "entity is unavailable at the named release",
			}
		}
		entities = []indexedEntity{entity}
	}
	terms := searchTerms(query)
	if len(terms) == 0 {
		return []Field{}, 0, nil
	}
	if limit <= 0 {
		limit = 20
	}
	out, total := []Field{}, 0
	for _, entity := range entities {
		if err := ctx.Err(); err != nil {
			return nil, 0, err
		}
		for _, field := range index.fields(entity) {
			if field.State != "present" || strings.TrimFunc(field.Value, browserWhitespace) == "" {
				continue
			}
			title, value, matched := searchFold(field.FieldTitle), searchFold(field.Value), true
			for _, term := range terms {
				if !strings.Contains(title, term) && !strings.Contains(value, term) {
					matched = false
					break
				}
			}
			if !matched {
				continue
			}
			total++
			if len(out) < limit {
				out = append(out, field)
			}
		}
	}
	if err := ctx.Err(); err != nil {
		return nil, 0, err
	}
	return out, total, nil
}

// searchTerms splits a query into the folded, whitespace-separated terms every search matches.
func searchTerms(query string) []string {
	return strings.FieldsFunc(searchFold(query), browserWhitespace)
}

// fieldsForSlugs resolves complete opaque slugs within the same visible release.
func (s *Service) fieldsForSlugs(
	ctx context.Context, tenantID uint64, spaceID, releaseID string, slugs []string,
) ([]Field, error) {
	index, err := s.read(ctx, tenantID, spaceID, releaseID)
	if err != nil {
		return nil, err
	}
	out, seen := []Field{}, map[string]bool{}
	for _, slug := range slugs {
		if seen[slug] {
			continue
		}
		seen[slug] = true
		claim, ok := index.claimBySlug[slug]
		if !ok {
			continue
		}
		entity := index.entities[index.entityByID[claim.payload.Subject]]
		titles, _ := index.profileFields(entity)
		out = append(out, index.field(entity, claim, titles))
	}
	return out, ctx.Err()
}

func (index *releaseIndex) profileFields(entity indexedEntity) (map[string]string, map[string]int) {
	titles, order := map[string]string{}, map[string]int{}
	if profile := index.profileFor(entity.kind, entity.Labels); profile != nil {
		for _, section := range profile.Sections {
			for _, field := range section.Fields {
				if field.Key == "" {
					continue
				}
				if _, exists := order[field.Key]; exists {
					continue
				}
				order[field.Key] = len(order)
				titles[field.Key] = field.Title
			}
		}
	}
	return titles, order
}

func (index *releaseIndex) fields(entity indexedEntity) []Field {
	titles, order := index.profileFields(entity)
	claims := append([]indexedClaim(nil), index.claims[entity.EntityID]...)
	rank := func(key string) int {
		if position, ok := order[key]; ok {
			return position
		}
		return len(order)
	}
	sort.SliceStable(claims, func(i, j int) bool {
		return rank(claims[i].payload.Predicate) < rank(claims[j].payload.Predicate)
	})
	out := make([]Field, 0, len(claims))
	for _, claim := range claims {
		out = append(out, index.field(entity, claim, titles))
	}
	return out
}

func (index *releaseIndex) field(entity indexedEntity, claim indexedClaim, titles map[string]string) Field {
	payload := claim.payload
	title := titles[payload.Predicate]
	if title == "" {
		title = payload.Predicate
	}
	value := ""
	if payload.State == "present" {
		value = valueText(payload.Value)
	}
	evidence := make([]Evidence, 0, len(payload.Evidence))
	for position, item := range payload.Evidence {
		evidence = append(evidence, Evidence{
			Index: position, Quote: item.Quote, Page: item.Locator.Page, SourceRef: item.SourceRef,
		})
	}
	out := Field{
		ReleaseID: index.id, Slug: claim.member.LogicalSlug, EntityID: entity.EntityID, EntityName: entity.Name,
		EntityVersion: versionLabel(entity.Entity), FieldKey: payload.Predicate, FieldTitle: title,
		State: payload.State, Value: value, Origin: payload.Origin, Review: payload.Review.Mode, Evidence: evidence,
	}
	if entity.Method {
		out.Method, out.Note = true, index.methodNote(entity)
		if payload.State == "present" {
			out.Items = alignedItems(payload.Value, len(evidence))
		}
	}
	return out
}

func valueText(value any) string {
	if value == nil {
		return ""
	}
	switch typed := value.(type) {
	case string:
		return typed
	case []any:
		values := []string{}
		for _, item := range typed {
			if text := valueText(item); strings.TrimFunc(text, browserWhitespace) != "" {
				values = append(values, text)
			}
		}
		return strings.Join(values, "；")
	case map[string]any:
		raw, _ := json.Marshal(typed)
		return string(raw)
	default:
		return fmt.Sprint(value)
	}
}
