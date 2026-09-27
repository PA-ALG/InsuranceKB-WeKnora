package service

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"

	"github.com/Tencent/WeKnora/internal/types"
)

// Reopen immutable published identities through the existing signed projection
// owner. The base need not remain active after its child is published; callers
// independently enforce the current write head and access policy.
func (s *WikiReleaseService) loadPublishedLegacyBase830G3(ctx context.Context, scope types.WikiReleaseScope, id string, epoch uint64) (types.BatchConceptCandidateBundle830G3, bool, error) {
	var empty types.BatchConceptCandidateBundle830G3
	if s == nil || s.repository == nil || id == "" || epoch == 0 {
		return empty, false, ErrConceptSourceAuthorityUnavailable830G2
	}
	release, err := s.repository.GetRelease(ctx, scope, id)
	if err != nil || release == nil || release.ID != id || release.WikiReleaseScope != scope ||
		release.BaseActivationEpoch == ^uint64(0) || release.BaseActivationEpoch+1 != epoch {
		return empty, false, ErrConceptSourceAuthorityUnavailable830G2
	}
	p, bundle, expected, found, err := s.loadPublishedBatchReadProjection830G3(ctx, scope, release.PreparationID)
	if err != nil {
		return empty, false, err
	}
	if !found {
		return empty, false, nil
	}
	base := bundle.Request.BaseRequest
	if p == nil || p.ID != release.PreparationID || p.Status != types.WikiReleasePreparationReady ||
		p.CandidateDigest != release.CandidateDigest || p.ManifestDigest != release.ManifestDigest ||
		p.ExpectedReleaseID != release.BaseReleaseID || p.ExpectedActivationEpoch != release.BaseActivationEpoch ||
		bundle.CandidateHash != release.CandidateDigest || batchConceptScope830G3(bundle) != scope ||
		base.BaseReleaseID != release.BaseReleaseID || base.BaseActivationEpoch != release.BaseActivationEpoch {
		return empty, false, ErrConceptSourceAuthorityUnavailable830G2
	}
	members, err := s.repository.GetReleaseMembers(ctx, scope, id)
	if err != nil || !publishedBatchMemberIdentitiesEqual830G3(expected, members) {
		return empty, false, ErrConceptSourceAuthorityUnavailable830G2
	}
	return bundle, true, nil
}

func conceptLegacyProofKey830G3(scope types.WikiReleaseScope, candidate, base string, epoch uint64) string {
	identity, _ := canonicalJSON830G2(struct {
		Scope           types.WikiReleaseScope
		Candidate, Base string
		Epoch           uint64
	}{scope, candidate, base, epoch})
	return "legacy-" + testSHA256Bytes830G2(identity)
}

func (s *ConceptSourceAuthorityService830G2) reusePublishedLegacyBase830G3(ctx context.Context, scope types.WikiReleaseScope, child types.ConceptCandidateBundle830G2) (map[string]conceptLegacyProof830G2, bool, error) {
	if s.publishedLegacyBase == nil || child.Request.BaseReleaseID == "" {
		return nil, false, nil
	}
	parent, found, err := s.publishedLegacyBase(ctx, scope, child.Request.BaseReleaseID, child.Request.BaseActivationEpoch)
	if err != nil || !found {
		return nil, false, err
	}
	base := parent.Request.BaseRequest
	key := conceptLegacyProofKey830G3(scope, parent.CandidateHash, base.BaseReleaseID, base.BaseActivationEpoch)
	data, err := s.sourceReuse.readArtifact(filepath.Join(s.sourceReuse.root, key+".json"), key)
	if errors.Is(err, os.ErrNotExist) {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	var wire map[string]*types.SchemaWikiCitationContentAuthorityV1
	if json.Unmarshal(data, &wire) != nil || wire == nil {
		return nil, false, ErrConceptSourceAuthorityUnavailable830G2
	}
	proofs, err := remapPublishedLegacyOccurrences830G3(parent.CompileResult.Output.Fields, child, wire)
	return proofs, err == nil, err
}

// A sealed proof is bound to an exact parent field/evidence occurrence, not to
// every field in its product. Changes continue through native source authority.
func remapPublishedLegacyOccurrences830G3(parent []types.ConceptFieldAssertion830G2, child types.ConceptCandidateBundle830G2, wire map[string]*types.SchemaWikiCitationContentAuthorityV1) (map[string]conceptLegacyProof830G2, error) {
	result := map[string]conceptLegacyProof830G2{}
	matched := map[string]bool{}
	for _, field := range parent {
		id, err := field.FieldAssertionID()
		if err != nil {
			return nil, err
		}
		target, carried := conceptLegacyCarryoverTargetField830G2(field, child.Request.ExistingFields, child.CompileResult.Output.Fields)
		for _, evidence := range field.Evidence {
			encoded, err := canonicalJSON830G2(evidence)
			if err != nil {
				return nil, err
			}
			evidenceHash := testSHA256Bytes830G2(encoded)
			key := id + "\x00" + evidenceHash
			authority, exists := wire[key]
			if !exists {
				continue
			}
			if authority == nil || authority.OpaqueToken != "" {
				return nil, ErrConceptSourceAuthorityUnavailable830G2
			}
			matched[key] = true
			if carried {
				targetID, err := target.FieldAssertionID()
				if err != nil {
					return nil, err
				}
				result[targetID+"\x00"+evidenceHash] = conceptLegacyProof830G2{authority: authority}
			}
		}
	}
	if len(matched) != len(wire) {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	return result, nil
}
