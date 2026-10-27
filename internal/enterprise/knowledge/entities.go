package knowledge

import (
	"context"
	"sort"
	"strings"
)

// FindEntities ranks explicit IDs and matching names before shared rune bigrams.
func (s *Service) FindEntities(
	ctx context.Context, tenantID uint64, spaceID, releaseID, query string, limit int,
) ([]Entity, error) {
	index, err := s.read(ctx, tenantID, spaceID, releaseID)
	if err != nil {
		return nil, err
	}
	query = normalize(query)
	if query == "" {
		return []Entity{}, nil
	}
	if limit <= 0 {
		limit = 5
	}
	type match struct {
		entity Entity
		direct bool
		shared int
	}
	matches := []match{}
	pairs := bigrams(query)
	for _, entity := range index.entities {
		candidate := match{entity: entity.Entity, direct: query == normalize(entity.EntityID)}
		for _, name := range entity.Names {
			name = normalize(name)
			if name == "" {
				continue
			}
			candidate.direct = candidate.direct || strings.Contains(name, query) || strings.Contains(query, name)
			if count := sharedBigrams(pairs, bigrams(name)); count > candidate.shared {
				candidate.shared = count
			}
		}
		if candidate.direct || candidate.shared >= 2 {
			matches = append(matches, candidate)
		}
	}
	sort.SliceStable(matches, func(i, j int) bool {
		if matches[i].direct != matches[j].direct {
			return matches[i].direct
		}
		return matches[i].shared > matches[j].shared
	})
	if len(matches) > limit {
		matches = matches[:limit]
	}
	out := make([]Entity, 0, len(matches))
	for _, match := range matches {
		out = append(out, match.entity)
	}
	return out, ctx.Err()
}

func (index *releaseIndex) entity(id string) (indexedEntity, bool) {
	id = normalize(id)
	for _, entity := range index.entities {
		if normalize(entity.EntityID) == id {
			return entity, true
		}
	}
	return indexedEntity{}, false
}

// scopeOf names a search's entity filter for its scope note: "" for every entity, otherwise the
// entity's display name, or the requested ID when the release has no such entity.
func (index *releaseIndex) scopeOf(entityID string) string {
	if entityID == "" {
		return ""
	}
	if entity, ok := index.entity(entityID); ok {
		return entity.Name + "的"
	}
	return entityID + "的"
}

func (index *releaseIndex) orderedEntities() []indexedEntity {
	if index.navigation == nil {
		return index.entities
	}
	out := make([]indexedEntity, 0, len(index.entities))
	claimedByDomain, claimedByGroup, grouped := map[string]bool{}, map[string]bool{}, map[string]bool{}
	for _, domain := range index.navigation.Domains {
		matching := []indexedEntity{}
		for _, entity := range index.entities {
			if !claimedByDomain[entity.EntityID] && intersects(domain.Types, []string{entity.kind}) {
				claimedByDomain[entity.EntityID] = true
				matching = append(matching, entity)
			}
		}
		for _, group := range domain.Groups {
			for _, entity := range matching {
				if !claimedByGroup[entity.EntityID] && intersects(group.Labels, entity.Labels) {
					claimedByGroup[entity.EntityID] = true
					// S3h-1 reserves __other__ for ungrouped entries, which belong last.
					if group.Key != "__other__" {
						out = append(out, entity)
						grouped[entity.EntityID] = true
					}
				}
			}
		}
	}
	for _, entity := range index.entities {
		if !grouped[entity.EntityID] {
			out = append(out, entity)
		}
	}
	return out
}
