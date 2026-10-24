package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"

	"github.com/Tencent/WeKnora/internal/enterprise/capture"
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
	key := conceptLegacyProofKey830G3(scope, bundle.CandidateHash, bundle.Request.BaseReleaseID, bundle.Request.BaseActivationEpoch)
	result := s.sourceReuse.flight.DoChan(key, func() (any, error) {
		path := filepath.Join(s.sourceReuse.root, key+".json")
		data, err := s.sourceReuse.readArtifact(path, key)
		if errors.Is(err, os.ErrNotExist) {
			if !prepare {
				return nil, ErrConceptSourceAuthorityUnavailable830G2
			}
			proofs, reused, err := s.reusePublishedLegacyBase830G3(ctx, scope, bundle)
			if err == nil && !reused {
				proofs, err = s.computeLegacyCarryover830G2(ctx, scope, bundle)
			}
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
	manifestDigest := receipt.WeKnoraManifestDigest
	if manifestDigest != source.ManifestDigest {
		reader, ok := s.formalCandidatePreview.(interface {
			ReadOriginalRevisionManifestDigestExact(uint64, string, types.LiveRevisionSourceReceiptV1) (string, error)
		})
		if !ok {
			return false
		}
		var err error
		manifestDigest, err = reader.ReadOriginalRevisionManifestDigestExact(request.Scope.TenantID, authority.CandidateSHA256, receipt)
		if err != nil {
			return false
		}
	}
	return source.TenantID == request.Scope.TenantID && source.KnowledgeID == request.Evidence.KnowledgeID && source.ParseAttempt == request.Evidence.ParseAttempt &&
		source.RetentionState == types.KnowledgeRevisionSourcePinned && resource.Handle == source.ResourceHandle && resource.ContentHash == source.ObjectSHA256 && resource.State == types.ResourceStateActive && resource.Lifecycle == types.ResourceLifecyclePersistent &&
		receipt.TenantID == source.TenantID && receipt.KnowledgeID == source.KnowledgeID && receipt.WeKnoraParseAttempt == source.ParseAttempt && receipt.FileSHA256 == source.FileSHA256 && receipt.ResourceID == source.ResourceID && receipt.PageCount == *source.PageCount && receipt.WeKnoraManifestAlgorithm == source.ManifestAlgorithm && manifestDigest == source.ManifestDigest && receipt.WeKnoraChunkCount == source.ChunkCount
}

// First-parse reads of the 830 citation family, kept here until the family is deleted (S7d-2c-3c).
func (s *conceptSourceReuseStore830G3) firstParseStore() *capture.Store {
	var keys *capture.Keys
	if s.codec != nil {
		keys = capture.NewKeys(s.codec.activeKeyID, s.codec.privateKeys)
	}
	return capture.NewStore(s.root, keys)
}

func (s *conceptSourceReuseStore830G3) readFirstParse(id g3FirstParseIdentity) (*g3FirstParseRecord, error) {
	if s == nil {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	return s.firstParseStore().Read(id)
}

func conceptSourceReuseKey830G3(identity types.ConceptSourceIdentity830G2, binding string) (string, error) {
	data, err := canonicalJSON830G2(struct {
		Source  types.ConceptSourceIdentity830G2
		Binding string
	}{identity, binding})
	if err != nil {
		return "", err
	}
	return testSHA256Bytes830G2(data), nil
}

func (s *conceptSourceReuseStore830G3) validateFirstParseCache(record *conceptSourceReuseRecord830G3) error {
	return s.validateFirstParseCacheProof(record, nil)
}

func (s *conceptSourceReuseStore830G3) validateFirstParseCacheProof(
	record *conceptSourceReuseRecord830G3, proof *conceptSourceBindingProof830G3,
) error {
	id := g3FirstParseIdentity{
		TenantID: record.Identity.TenantID, RawKBID: record.Identity.RawKBID, KnowledgeID: record.Identity.KnowledgeID,
		ParseAttempt: record.Identity.ParseAttempt, SourceSHA256: record.Identity.SourceHash,
	}
	key, err := g3FirstParseKey(id)
	if err != nil {
		return err
	}
	data, err := s.readArtifact(filepath.Join(s.root, key+".json"), key)
	if errors.Is(err, os.ErrNotExist) && record.FirstParseSHA256 == "" {
		return nil
	} // frozen legacy sources only
	if err != nil {
		return err
	}
	// A first artifact that exists makes legacy same-key caches ineligible.
	if record.FirstParseSHA256 == "" || testSHA256Bytes830G2(data) != record.FirstParseSHA256 {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	// The current signature and complete payload digest still passed above.
	// Identical authenticated bytes have the same already-proved bindings to
	// this exact immutable owned record; avoid reconstructing them per quote.
	if proof.matches(record) {
		return nil
	}
	var first g3FirstParseRecord
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&first) != nil || !jsonEOF830G2(decoder) || first.Contract != capture.Contract ||
		first.Identity != id {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	// The native index is already owned/validated by the cached record. Only the
	// signed first capture and its complete binding are reopened on a cache hit.
	return g3CachedFirstParseMatches(&first, record)
}

func g3CachedFirstParseMatches(first *g3FirstParseRecord, record *conceptSourceReuseRecord830G3) error {
	if first == nil || record == nil || record.FirstParseSHA256 != g3FirstParseRecordSHA(first) ||
		first.ParserIdentitySHA256 != record.Identity.ParserIdentity || first.Markdown != record.Markdown ||
		first.Native == nil || record.Native == nil || first.Native.SanitizedSHA256 != record.Native.SanitizedSHA256 ||
		first.Native.SourceSHA256 != record.Native.SourceSHA256 {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	ranges, err := g3FirstParseBindings(first, record.Chunks)
	if err != nil {
		return err
	}
	if len(ranges) != len(record.ChunkRanges) {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	for id, r := range ranges {
		if stored, ok := record.ChunkRanges[id]; !ok || stored != r {
			return ErrConceptSourceAuthorityUnavailable830G2
		}
	}
	return nil
}
