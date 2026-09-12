package service

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"

	"github.com/Tencent/WeKnora/internal/types"
)

type conceptSourceReuseReadOnlyKey830G3 struct{}

// PrepareConceptLegacySourceReuse830G3 replays the immutable legacy chain once
// during explicit preparation. Serving reads only consume its sealed result.
func (s *ConceptSourceAuthorityService830G2) PrepareConceptLegacySourceReuse830G3(ctx context.Context, scope types.WikiReleaseScope, bundle types.ConceptCandidateBundle830G2) error {
	ctx = context.WithValue(ctx, conceptSourceReusePrepareKey830G3{}, true)
	_, err := s.verifyLegacyCarryover830G2(ctx, scope, bundle)
	return err
}

func (s *ConceptSourceAuthorityService830G2) verifyLegacyCarryover830G2(ctx context.Context, scope types.WikiReleaseScope, bundle types.ConceptCandidateBundle830G2) (map[string]conceptLegacyProof830G2, error) {
	prepare, _ := ctx.Value(conceptSourceReusePrepareKey830G3{}).(bool)
	readOnly, _ := ctx.Value(conceptSourceReuseReadOnlyKey830G3{}).(bool)
	if s == nil || s.sourceReuse == nil || (!prepare && !readOnly) {
		return s.computeLegacyCarryover830G2(ctx, scope, bundle)
	}
	if !validServiceSHA256(bundle.CandidateHash) {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	// CandidateHash is provided only after the release service validates the
	// persisted preparation, not from a caller's standalone hash claim.
	identity, _ := canonicalJSON830G2(struct {
		Scope           types.WikiReleaseScope
		Candidate, Base string
		Epoch           uint64
	}{scope, bundle.CandidateHash, bundle.Request.BaseReleaseID, bundle.Request.BaseActivationEpoch})
	key := "legacy-" + testSHA256Bytes830G2(identity)
	result := s.sourceReuse.flight.DoChan(key, func() (any, error) {
		path := filepath.Join(s.sourceReuse.root, key+".json")
		data, err := s.sourceReuse.readArtifact(path, key)
		if errors.Is(err, os.ErrNotExist) {
			if !prepare {
				return nil, ErrConceptSourceAuthorityUnavailable830G2
			}
			proofs, err := s.computeLegacyCarryover830G2(ctx, scope, bundle)
			if err != nil {
				return nil, err
			}
			wire := map[string]*types.SchemaWikiCitationContentAuthorityV1{}
			for member, proof := range proofs {
				if proof.authority == nil {
					return nil, ErrConceptSourceAuthorityUnavailable830G2
				}
				copy := *proof.authority
				copy.OpaqueToken = ""
				wire[member] = &copy
			}
			data, err = json.Marshal(wire)
			if err != nil {
				return nil, err
			}
			if err = s.sourceReuse.writeArtifact(path, key, data); err != nil {
				return nil, err
			}
		} else if err != nil {
			return nil, err
		}
		var wire map[string]*types.SchemaWikiCitationContentAuthorityV1
		if json.Unmarshal(data, &wire) != nil || wire == nil {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		proofs := make(map[string]conceptLegacyProof830G2, len(wire))
		for member, authority := range wire {
			if authority == nil || authority.OpaqueToken != "" {
				return nil, ErrConceptSourceAuthorityUnavailable830G2
			}
			proofs[member] = conceptLegacyProof830G2{authority: authority}
		}
		return proofs, nil
	})
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	case loaded := <-result:
		if loaded.Err != nil {
			return nil, loaded.Err
		}
		proofs := loaded.Val.(map[string]conceptLegacyProof830G2)
		// Reuse immutable history, but publication gates must still observe source
		// revocation. Deduplicate only identical source receipts within this call.
		if prepare {
			seen := map[string]bool{}
			for _, proof := range proofs {
				if proof.authority == nil || s.revisions == nil {
					return nil, ErrConceptSourceAuthorityUnavailable830G2
				}
				receipt := proof.authority.RevisionSource
				encoded, err := json.Marshal(receipt)
				if err != nil {
					return nil, ErrConceptSourceAuthorityUnavailable830G2
				}
				sourceKey := string(encoded)
				if seen[sourceKey] {
					continue
				}
				source, resource, err := s.revisions.GetRevisionSource(ctx, scope.TenantID, receipt.KnowledgeID, receipt.WeKnoraParseAttempt)
				if err != nil || source == nil || resource == nil || resource.ID != source.ResourceID {
					return nil, ErrConceptSourceAuthorityUnavailable830G2
				}
				binding, err := types.ComputeKnowledgeRevisionSourceBindingDigest(*source)
				if err != nil || binding != source.BindingDigest {
					return nil, ErrConceptSourceAuthorityUnavailable830G2
				}
				request := ConceptCitationAuthorityRequest830G2{Scope: scope, Evidence: types.ConceptEvidence830G2{ConceptSourceIdentity830G2: types.ConceptSourceIdentity830G2{KnowledgeID: receipt.KnowledgeID, ParseAttempt: receipt.WeKnoraParseAttempt}}}
				if !s.reusableLegacySourceCurrent830G3(ctx, request, source, resource, proof.authority) {
					return nil, ErrConceptSourceAuthorityUnavailable830G2
				}
				seen[sourceKey] = true
			}
		}
		return proofs, nil
	}
}

func (s *ConceptSourceAuthorityService830G2) reusableLegacySourceCurrent830G3(ctx context.Context, request ConceptCitationAuthorityRequest830G2, source *types.KnowledgeRevisionSource, resource *types.StoredResource, authority *types.SchemaWikiCitationContentAuthorityV1) bool {
	if s == nil || s.knowledge == nil || s.revisions == nil || source == nil || resource == nil || authority == nil || source.PageCount == nil {
		return false
	}
	knowledge, err := s.knowledge.GetKnowledgeByID(ctx, request.Scope.TenantID, request.Evidence.KnowledgeID)
	if err != nil || knowledge == nil || knowledge.DeletedAt.Valid || knowledge.TenantID != request.Scope.TenantID || knowledge.KnowledgeBaseID != request.Scope.RawKBID {
		return false
	}
	revision, err := s.revisions.GetRevision(ctx, request.Evidence.KnowledgeID, request.Evidence.ParseAttempt)
	if err != nil || revision == nil || revision.FileSHA256 != source.FileSHA256 || revision.ManifestDigest != source.ManifestDigest || revision.ManifestAlgorithm != source.ManifestAlgorithm || revision.ChunkCount != source.ChunkCount {
		return false
	}
	receipt := authority.RevisionSource
	return source.TenantID == request.Scope.TenantID && source.KnowledgeID == request.Evidence.KnowledgeID && source.ParseAttempt == request.Evidence.ParseAttempt &&
		source.RetentionState == types.KnowledgeRevisionSourcePinned && resource.Handle == source.ResourceHandle && resource.ContentHash == source.ObjectSHA256 && resource.State == types.ResourceStateActive && resource.Lifecycle == types.ResourceLifecyclePersistent &&
		receipt.TenantID == source.TenantID && receipt.KnowledgeID == source.KnowledgeID && receipt.WeKnoraParseAttempt == source.ParseAttempt && receipt.FileSHA256 == source.FileSHA256 && receipt.ResourceID == source.ResourceID && receipt.PageCount == *source.PageCount && receipt.WeKnoraManifestAlgorithm == source.ManifestAlgorithm && receipt.WeKnoraManifestDigest == source.ManifestDigest && receipt.WeKnoraChunkCount == source.ChunkCount
}
