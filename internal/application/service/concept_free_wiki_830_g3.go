package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"sync/atomic"
	"unicode/utf8"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"golang.org/x/text/unicode/norm"
)

const batchConceptPreparationReadContract830G3 = "batch-concept-preparation-read.830.g3.v1"

func conceptCandidateBundleContract830G3(contract string) bool {
	return contract == "batch-concept-candidate-bundle.830.g3.v1"
}

func validBatchConceptPreparationID830G3(value string) bool {
	if value == "" || !utf8.ValidString(value) || !norm.NFC.IsNormalString(value) ||
		strings.TrimSpace(value) != value {
		return false
	}
	for _, character := range value {
		if character < 0x20 || character == 0x7f {
			return false
		}
	}
	return true
}

type BatchConceptPreparationRead830G3 struct {
	Contract                    string                              `json:"contract"`
	ReadMode                    string                              `json:"read_mode"`
	TenantID                    uint64                              `json:"tenant_id"`
	SpaceID                     string                              `json:"space_id"`
	RawKBID                     string                              `json:"raw_kb_id"`
	WikiKBID                    string                              `json:"wiki_kb_id"`
	PreparationID               string                              `json:"preparation_id"`
	Status                      string                              `json:"status"`
	CandidateSHA256             string                              `json:"candidate_sha256"`
	ExpectedBaseReleaseID       string                              `json:"expected_base_release_id"`
	ExpectedBaseActivationEpoch uint64                              `json:"expected_base_activation_epoch"`
	PageManifest                types.BatchConceptPageManifest830G3 `json:"page_manifest"`
	ReadSHA256                  string                              `json:"read_sha256"`
}

func (s *SchemaWikiService) CreateBatchConceptDraft830G3(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
	rawBundle json.RawMessage,
) (*types.WikiReleasePreparation, error) {
	if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
		return nil, err
	}
	if s == nil || s.releaseAuthority == nil || !validBatchConceptPreparationID830G3(preparationID) {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	bundle, canonicalBundle, err := types.CanonicalBatchConceptCandidateBundle830G3(rawBundle)
	if err != nil || batchConceptScope830G3(bundle) != scope {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	if err := s.validateBatchConceptBase830G3(ctx, scope, bundle); err != nil {
		return nil, err
	}
	members, err := bundle.SnapshotMembers()
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	base := bundle.Request.BaseRequest
	input := &types.WikiReleasePreparation{
		ID: preparationID, WikiReleaseScope: scope,
		CandidateDigest:         bundle.CandidateHash,
		ManifestDigest:          digestWikiReleaseBytes(canonicalBundle),
		ReadyReceiptDigest:      bundle.ReviewResult.Execution.RawOutputHash,
		ReviewPolicyID:          conceptReviewPolicyHash830G2(base.PolicyIdentity),
		ExpectedReleaseID:       base.BaseReleaseID,
		ExpectedActivationEpoch: base.BaseActivationEpoch,
		Manifest:                canonicalBundle, Members: members,
	}
	if err := s.releaseAuthority.verifyConceptSourceAuthority830G2(
		ctx, principal, scope, input, "create-draft",
	); err != nil {
		return nil, err
	}
	draft, err := s.releaseAuthority.createDraftAtExpectedHead(
		ctx, principal, input,
		&wikiReleaseDraftExpectedHead{releaseID: base.BaseReleaseID, activationEpoch: base.BaseActivationEpoch},
	)
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	return draft, nil
}

func batchConceptScope830G3(bundle types.BatchConceptCandidateBundle830G3) types.WikiReleaseScope {
	request := bundle.Request.BaseRequest
	return types.WikiReleaseScope{
		TenantID: request.TenantID, SpaceID: request.SpaceID,
		RawKBID: request.RawKBID, WikiKBID: request.WikiKBID,
	}
}

func (s *SchemaWikiService) validateBatchConceptBase830G3(
	ctx context.Context,
	scope types.WikiReleaseScope,
	bundle types.BatchConceptCandidateBundle830G3,
) error {
	if batchConceptScope830G3(bundle) != scope {
		return ErrSchemaWikiPreparationInvalid
	}
	// The frozen G3 base_request is the existing G2 request shape. Reuse the
	// G2 active-release reopening and compare against its final logical output;
	// the G3 parser already validates MATCH bindings and the two exact key
	// alignments across the complete outer bundle.
	return s.validateConceptBase830G2(ctx, scope, types.ConceptCandidateBundle830G2{
		Request: bundle.Request.BaseRequest,
	})
}

var batchPreparationValidations830G3 atomic.Uint64

func validateBatchConceptPreparation830G3(
	preparation *types.WikiReleasePreparation,
	expectedStatus string,
	scope types.WikiReleaseScope,
) (types.BatchConceptCandidateBundle830G3, []types.WikiReleaseMemberSnapshot, error) {
	batchPreparationValidations830G3.Add(1)
	if preparation == nil || preparation.WikiReleaseScope != scope ||
		!validBatchConceptPreparationID830G3(preparation.ID) ||
		preparation.Status != expectedStatus ||
		digestWikiReleasePreparation(preparation) != preparation.PreparationDigest {
		return types.BatchConceptCandidateBundle830G3{}, nil, ErrSchemaWikiPreparationInvalid
	}
	bundle, canonical, err := types.CanonicalBatchConceptCandidateBundle830G3(preparation.Manifest)
	base := bundle.Request.BaseRequest
	if err != nil || batchConceptScope830G3(bundle) != scope ||
		preparation.ManifestDigest != digestWikiReleaseBytes(canonical) ||
		preparation.CandidateDigest != bundle.CandidateHash ||
		preparation.ReadyReceiptDigest != bundle.ReviewResult.Execution.RawOutputHash ||
		preparation.ReviewPolicyID != conceptReviewPolicyHash830G2(base.PolicyIdentity) ||
		preparation.ExpectedReleaseID != base.BaseReleaseID ||
		preparation.ExpectedActivationEpoch != base.BaseActivationEpoch {
		return types.BatchConceptCandidateBundle830G3{}, nil, ErrSchemaWikiPreparationInvalid
	}
	if expectedStatus == types.WikiReleasePreparationDraft && preparation.ReviewDecisionDigest != "" ||
		expectedStatus == types.WikiReleasePreparationReady && preparation.ReviewDecisionDigest == "" {
		return types.BatchConceptCandidateBundle830G3{}, nil, ErrSchemaWikiPreparationInvalid
	}
	members, err := bundle.SnapshotMembers()
	if err != nil || !conceptMemberSnapshotsEqual830G2(members, preparation.Members) {
		return types.BatchConceptCandidateBundle830G3{}, nil, ErrSchemaWikiPreparationInvalid
	}
	return bundle, members, nil
}

func (s *SchemaWikiService) LoadBatchConceptPreparation830G3(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
) (*BatchConceptPreparationRead830G3, error) {
	return s.loadBatchConceptPreparation830G3(ctx, principal, scope, preparationID, false)
}

// PrepareBatchConceptRead830G3 is the explicit, idempotent import/prepare gate
// for historical releases. Public page/citation/PDF GETs never call it.
func (s *SchemaWikiService) PrepareBatchConceptRead830G3(ctx context.Context, principal types.WikiReleasePrincipal, scope types.WikiReleaseScope, preparationID string) (*BatchConceptPreparationRead830G3, error) {
	return s.loadBatchConceptPreparation830G3(ctx, principal, scope, preparationID, true)
}

func (s *SchemaWikiService) loadBatchConceptPreparation830G3(ctx context.Context, principal types.WikiReleasePrincipal, scope types.WikiReleaseScope, preparationID string, prepareSources bool) (*BatchConceptPreparationRead830G3, error) {
	if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
		return nil, err
	}
	if s == nil || s.releaseAuthority == nil || s.releaseAuthority.repository == nil ||
		!validBatchConceptPreparationID830G3(preparationID) {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	preparation, err := s.releaseAuthority.repository.GetDraftPreparation(ctx, scope, preparationID)
	status := types.WikiReleasePreparationDraft
	if errors.Is(err, wikirepository.ErrWikiReleaseNotFound) {
		preparation, err = s.releaseAuthority.repository.GetReadyPreparation(ctx, scope, preparationID)
		status = types.WikiReleasePreparationReady
	}
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	if preparation == nil || preparation.ID != preparationID {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	bundle, _, err := validateBatchConceptPreparation830G3(preparation, status, scope)
	if err != nil {
		return nil, err
	}
	if prepareSources {
		if status != types.WikiReleasePreparationReady {
			return nil, ErrSchemaWikiPreparationInvalid
		}
		if err := s.releaseAuthority.verifyConceptSourceAuthority830G2(ctx, principal, scope, preparation, "prepare-read"); err != nil {
			return nil, err
		}
	}
	if status == types.WikiReleasePreparationReady {
		if err := s.releaseAuthority.publishedBatchReuse830G3().rememberValidated(preparation, scope); err != nil {
			return nil, err
		}
	}
	result := &BatchConceptPreparationRead830G3{
		Contract: batchConceptPreparationReadContract830G3, ReadMode: "preparation",
		TenantID: scope.TenantID, SpaceID: scope.SpaceID, RawKBID: scope.RawKBID, WikiKBID: scope.WikiKBID,
		PreparationID: preparation.ID, Status: map[string]string{
			types.WikiReleasePreparationDraft: "DRAFT",
			types.WikiReleasePreparationReady: "READY",
		}[status],
		CandidateSHA256:             bundle.CandidateHash,
		ExpectedBaseReleaseID:       preparation.ExpectedReleaseID,
		ExpectedBaseActivationEpoch: preparation.ExpectedActivationEpoch,
		PageManifest:                bundle.PageManifest,
	}
	result.ReadSHA256, err = batchConceptPreparationReadHash830G3(*result)
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	return result, nil
}

func batchConceptG2View830G3(
	bundle types.BatchConceptCandidateBundle830G3,
) types.ConceptCandidateBundle830G2 {
	return types.ConceptCandidateBundle830G2{
		Request: bundle.Request.BaseRequest, CompileResult: bundle.CompileResult,
		ReviewResult: bundle.ReviewResult,
		PageManifest: types.ConceptPageManifest830G2{
			Members: bundle.PageManifest.Members, Audit: bundle.PageManifest.Audit,
		},
		CandidateHash: bundle.CandidateHash,
	}
}

func (s *SchemaWikiService) readBatchConceptPage830G3(
	pin WikiReleasePinnedRead,
	storedMembers []types.WikiReleaseMemberSnapshot,
	release *types.WikiRelease,
	preparation *types.WikiReleasePreparation,
	scope types.WikiReleaseScope,
	memberID string,
	readMode string,
) (*ConceptPageRead830G2, error) {
	bundle, expected, err := s.releaseAuthority.validatePublishedBatchConceptPreparation830G3(
		preparation, scope,
	)
	if err != nil || release == nil || release.CandidateDigest != bundle.CandidateHash ||
		release.ManifestDigest != preparation.ManifestDigest ||
		release.BaseReleaseID != preparation.ExpectedReleaseID ||
		release.BaseActivationEpoch != preparation.ExpectedActivationEpoch ||
		release.BaseReleaseID != bundle.Request.BaseRequest.BaseReleaseID ||
		release.BaseActivationEpoch != bundle.Request.BaseRequest.BaseActivationEpoch ||
		release.BaseActivationEpoch == ^uint64(0) ||
		pin.ActivationEpoch() != release.BaseActivationEpoch+1 ||
		!conceptMemberSnapshotSetsEqual830G2(expected, storedMembers) {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	member, ok := conceptPageMemberByID830G2(bundle.PageManifest.Members, memberID)
	if !ok {
		return nil, ErrWikiReleaseNotFound
	}
	view := batchConceptG2View830G3(bundle)
	result := &ConceptPageRead830G2{
		Contract: "concept-page-read.830.g2.v1", ReadMode: readMode,
		ReleaseID: pin.ReleaseID(), ActivationEpoch: pin.ActivationEpoch(),
		CandidateHash: bundle.CandidateHash, SpaceID: scope.SpaceID,
		RawKBID: scope.RawKBID, WikiKBID: scope.WikiKBID, Member: member,
		Citations: conceptMemberCitations830G2(view, member),
	}
	if member.Kind == "entity_overview" {
		result.RelatedMembers, err = batchConceptOverviewRelatedMembers830G3(bundle, member)
	} else {
		result.RelatedMembers = conceptRelatedMembers830G2(view, member)
	}
	if err != nil {
		return nil, err
	}
	if member.Kind == "concept" {
		for _, definition := range bundle.CompileResult.Output.Definitions {
			definitionID, _ := definition.DefinitionID()
			if definitionID != member.MemberID {
				continue
			}
			result.DefinitionHash, err = definition.DefinitionHash()
			if err == nil {
				result.AggregateHash, err = types.ConceptAggregateHash830G2(
					pin.ReleaseID(), pin.ActivationEpoch(), definition,
					bundle.CompileResult.Output.Fields,
				)
			}
			break
		}
		if err != nil || result.DefinitionHash == "" || result.AggregateHash == "" {
			return nil, ErrSchemaWikiPreparationInvalid
		}
	}
	return result, nil
}

func batchConceptOverviewRelatedMembers830G3(
	bundle types.BatchConceptCandidateBundle830G3,
	overview types.ConceptPageMember830G2,
) ([]types.ConceptPageMember830G2, error) {
	var directory types.EntityDirectoryEntry830G3
	if overview.Kind != "entity_overview" || json.Unmarshal(overview.Payload, &directory) != nil ||
		directory.Contract != "entity-directory-entry.830.g3.v1" || directory.EntityID != overview.OwnerID {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	ids := map[string]struct{}{}
	for _, section := range directory.Sections {
		for _, field := range section.Fields {
			if field.MemberID == "" {
				return nil, ErrSchemaWikiPreparationInvalid
			}
			if _, duplicate := ids[field.MemberID]; duplicate {
				return nil, ErrSchemaWikiPreparationInvalid
			}
			ids[field.MemberID] = struct{}{}
		}
	}
	result := make([]types.ConceptPageMember830G2, 0, len(ids))
	for _, member := range bundle.PageManifest.Members {
		if _, selected := ids[member.MemberID]; !selected {
			continue
		}
		if member.Kind != "field_assertion" || member.OwnerID != overview.OwnerID {
			return nil, ErrSchemaWikiPreparationInvalid
		}
		member.Payload = append(json.RawMessage(nil), member.Payload...)
		result = append(result, member)
		delete(ids, member.MemberID)
	}
	if len(ids) != 0 {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	return result, nil
}

func batchConceptPreparationReadHash830G3(value BatchConceptPreparationRead830G3) (string, error) {
	payload := struct {
		Contract                    string                              `json:"contract"`
		ReadMode                    string                              `json:"read_mode"`
		TenantID                    uint64                              `json:"tenant_id"`
		SpaceID                     string                              `json:"space_id"`
		RawKBID                     string                              `json:"raw_kb_id"`
		WikiKBID                    string                              `json:"wiki_kb_id"`
		PreparationID               string                              `json:"preparation_id"`
		Status                      string                              `json:"status"`
		CandidateSHA256             string                              `json:"candidate_sha256"`
		ExpectedBaseReleaseID       string                              `json:"expected_base_release_id"`
		ExpectedBaseActivationEpoch uint64                              `json:"expected_base_activation_epoch"`
		PageManifest                types.BatchConceptPageManifest830G3 `json:"page_manifest"`
	}{
		value.Contract, value.ReadMode, value.TenantID, value.SpaceID, value.RawKBID, value.WikiKBID,
		value.PreparationID, value.Status, value.CandidateSHA256, value.ExpectedBaseReleaseID,
		value.ExpectedBaseActivationEpoch, value.PageManifest,
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	canonical, err := types.CanonicalConceptMemberPayload830G2(raw)
	if err != nil {
		return "", err
	}
	preimage := append([]byte("schema-wiki-canonical.v1\x00"+value.Contract+"\x00"), canonical...)
	sum := sha256.Sum256(preimage)
	return hex.EncodeToString(sum[:]), nil
}

func batchConceptManifestEqual830G3(left, right json.RawMessage) bool {
	_, leftCanonical, leftErr := types.CanonicalBatchConceptCandidateBundle830G3(left)
	_, rightCanonical, rightErr := types.CanonicalBatchConceptCandidateBundle830G3(right)
	return leftErr == nil && rightErr == nil && bytes.Equal(leftCanonical, rightCanonical)
}
