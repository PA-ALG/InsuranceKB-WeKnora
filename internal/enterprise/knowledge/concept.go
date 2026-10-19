package knowledge

import (
	"context"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// Concept omits an entire statement if any referenced fact is invisible or stale.
func (s *Service) Concept(
	ctx context.Context, tenantID uint64, spaceID, releaseID, keyOrTitle string,
) (Concept, error) {
	index, err := s.read(ctx, tenantID, spaceID, releaseID)
	if err != nil {
		return Concept{}, err
	}
	key := normalize(keyOrTitle)
	for _, payload := range index.concepts {
		if key == "" || (normalize(payload.Key) != key && normalize(payload.Title) != key) {
			continue
		}
		out := Concept{
			ReleaseID: releaseID, Key: payload.Key, Title: payload.Title, Definition: payload.Definition,
			Explanation: payload.Explanation, Statements: []Statement{},
		}
		for _, statement := range payload.Statements {
			visible := true
			for _, ref := range statement.Refs {
				claim, exists := index.claimBySlug[ref]
				basis, based := payload.BasedOn[ref]
				if !exists || (payload.BasedOn != nil && (!based || basis != claim.member.MemberDigest)) {
					visible = false
					break
				}
			}
			if visible {
				out.Statements = append(out.Statements, statement)
			} else {
				out.OmittedStatements++
			}
		}
		return out, ctx.Err()
	}
	return Concept{}, &release.Error{Code: "CONCEPT_NOT_FOUND", Detail: "concept is unavailable at the named release"}
}
