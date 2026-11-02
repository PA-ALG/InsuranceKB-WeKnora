package knowledge

import (
	"context"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// SourceEntities maps each material cited by a claim or wiki page of the release (the knowledge
// ID of a source:v1 reference) to the display names of the entities citing it, each followed by its
// version label when it has a lifecycle, in navigation order without duplicates. A claim cites for
// its subject (named by its ID when no visible Entity member exists); a page for every entity it
// refers to that has a visible Entity member.
// Raw passages are labelled with these names (QA1 §2.1), so a material is attributed only
// through the release's own evidence. Malformed references are skipped.
func (s *Service) SourceEntities(
	ctx context.Context, tenantID uint64, spaceID, releaseID string,
) (map[string][]string, error) {
	index, err := s.read(ctx, tenantID, spaceID, releaseID)
	if err != nil {
		return nil, err
	}
	citing := map[string]map[string]bool{} // knowledge ID -> citing entity IDs
	cite := func(entityID, sourceRef string) {
		ref, ok := release.ParseSourceRef(sourceRef)
		if !ok {
			return
		}
		if citing[ref.KnowledgeID] == nil {
			citing[ref.KnowledgeID] = map[string]bool{}
		}
		citing[ref.KnowledgeID][entityID] = true
	}
	for entityID, claims := range index.claims {
		if index.entities[index.entityByID[entityID]].Method {
			continue // a training material is no product's material (SK-3 §3)
		}
		for _, claim := range claims {
			for _, evidence := range claim.payload.Evidence {
				cite(entityID, evidence.SourceRef)
			}
		}
	}
	for _, page := range index.pages {
		for _, raw := range page.payload.Evidence {
			evidence, _, ok := validEvidence(raw)
			if !ok {
				continue
			}
			// The page's slug names one entity, but the page refers to all of them. A claim
			// subject's placeholder entry must not take a page's material.
			for _, entityID := range page.payload.Entities {
				if index.entityMember(entityID) && !index.entities[index.entityByID[entityID]].Method {
					cite(entityID, evidence.SourceRef)
				}
			}
		}
	}
	ordered := index.orderedEntities()
	out := make(map[string][]string, len(citing))
	for knowledgeID, entities := range citing {
		names, seen := []string{}, map[string]bool{}
		for _, entity := range ordered {
			// The version label tells a passage of a discontinued version from one on sale (PV-5 §2.1).
			name := entity.Name + versionLabel(entity.Entity)
			if entities[entity.EntityID] && !seen[name] {
				seen[name] = true
				names = append(names, name)
			}
		}
		out[knowledgeID] = names
	}
	return out, ctx.Err()
}

// entityMember reports whether a visible Entity member defines the ID, rather than only the
// placeholder entry the index keeps for a claim subject.
func (index *releaseIndex) entityMember(entityID string) bool {
	position, ok := index.entityByID[entityID]
	return ok && !index.entities[position].placeholder
}
