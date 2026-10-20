package releasestore

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

// ReleaseReference validates scope, preparation and retirement on every request,
// without reading the immutable member rows.
func (s *Store) ReleaseReference(ctx context.Context, tenantID uint64, spaceID, id string) (release.Reference, error) {
	scope, err := s.spaces.Scope(tenantID, spaceID)
	if err != nil {
		return release.Reference{}, err
	}
	header, err := s.releaseHeader(ctx, scope, id)
	if err != nil {
		return release.Reference{}, err
	}
	return release.Reference{ID: header.ID, Retired: header.RetiredAt != nil}, nil
}

func (s *Store) releaseHeader(
	ctx context.Context, scope types.WikiReleaseScope, releaseID string,
) (release.Release, error) {
	if releaseID == "" {
		head, err := s.activeHead(ctx, scope)
		if err != nil {
			return release.Release{}, notFound(err)
		}
		releaseID = head.ActiveReleaseID
	}
	rel, err := s.releases.GetRelease(ctx, scope, releaseID)
	if err != nil {
		return release.Release{}, notFound(err)
	}
	var preparation types.WikiReleasePreparation
	// Preparations also contain the full member snapshot. Select only the
	// manifest, otherwise even a 304 would fetch and deserialize that second copy.
	if err := s.db.WithContext(ctx).Select("manifest").Where("preparation_id = ? AND tenant_id = ? AND space_id = ?",
		rel.PreparationID, scope.TenantID, scope.SpaceID).Take(&preparation).Error; err != nil {
		return release.Release{}, fmt.Errorf("release %s has no readable preparation: %w", rel.ID, err)
	}
	var manifest releaseManifest
	if err := json.Unmarshal(preparation.Manifest, &manifest); err != nil {
		return release.Release{}, fmt.Errorf("release %s was not published by this adapter: %w", rel.ID, err)
	}
	retiredAt, err := s.retiredAt(ctx, scope, rel.ID)
	if err != nil {
		return release.Release{}, err
	}
	return release.Release{
		RetiredAt: retiredAt,
		ID:        rel.ID, Epoch: rel.BaseActivationEpoch + 1, BaseReleaseID: rel.BaseReleaseID,
		CandidateID: manifest.CandidateID, DecisionDigest: manifest.DecisionDigest,
	}, nil
}
