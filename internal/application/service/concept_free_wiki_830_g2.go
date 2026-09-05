package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"reflect"
	"sort"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
)

type ConceptPageCitation830G2 struct {
	CitationID string `json:"citation_id"`
	PageNumber int    `json:"page_number"`
	Quote      string `json:"quote"`
}

type ConceptPageRead830G2 struct {
	Contract        string                         `json:"contract"`
	ReadMode        string                         `json:"read_mode"`
	ReleaseID       string                         `json:"release_id"`
	ActivationEpoch uint64                         `json:"activation_epoch"`
	CandidateHash   string                         `json:"candidate_hash"`
	SpaceID         string                         `json:"space_id"`
	RawKBID         string                         `json:"raw_kb_id"`
	WikiKBID        string                         `json:"wiki_kb_id"`
	Member          types.ConceptPageMember830G2   `json:"member"`
	RelatedMembers  []types.ConceptPageMember830G2 `json:"related_members"`
	Citations       []ConceptPageCitation830G2     `json:"citations"`
	DefinitionHash  string                         `json:"definition_hash"`
	AggregateHash   string                         `json:"aggregate_hash"`
}

func (s *SchemaWikiService) CreateConceptFreeWikiDraft830G2(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
	rawBundle json.RawMessage,
) (*types.WikiReleasePreparation, error) {
	if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
		return nil, err
	}
	if s == nil || s.releaseAuthority == nil || preparationID == "" {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	bundle, err := types.ParseConceptCandidateBundle830G2(rawBundle)
	if err != nil || bundle.Request.TenantID != scope.TenantID ||
		bundle.Request.SpaceID != scope.SpaceID || bundle.Request.RawKBID != scope.RawKBID ||
		bundle.Request.WikiKBID != scope.WikiKBID {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	if err := s.validateConceptBase830G2(ctx, scope, bundle); err != nil {
		return nil, err
	}
	members, err := bundle.SnapshotMembers()
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	canonicalBundle, err := json.Marshal(bundle)
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	draft, err := s.releaseAuthority.createDraftAtExpectedHead(ctx, principal, &types.WikiReleasePreparation{
		ID: preparationID, WikiReleaseScope: scope,
		CandidateDigest:    bundle.CandidateHash,
		ReadyReceiptDigest: bundle.ReviewResult.Execution.RawOutputHash,
		ReviewPolicyID:     conceptReviewPolicyHash830G2(bundle.Request.PolicyIdentity),
		Manifest:           canonicalBundle, Members: members,
	}, &wikiReleaseDraftExpectedHead{
		releaseID: bundle.Request.BaseReleaseID, activationEpoch: bundle.Request.BaseActivationEpoch,
	})
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	return draft, nil
}

func (s *SchemaWikiService) validateConceptBase830G2(
	ctx context.Context,
	scope types.WikiReleaseScope,
	bundle types.ConceptCandidateBundle830G2,
) error {
	head, err := s.releaseAuthority.repository.GetHead(ctx, scope)
	if errors.Is(err, wikirepository.ErrWikiReleaseNotFound) {
		if bundle.Request.BaseReleaseID != "" || bundle.Request.BaseActivationEpoch != 0 ||
			len(bundle.Request.ExistingDefinitions) != 0 || len(bundle.Request.ExistingFields) != 0 ||
			len(bundle.Request.ExistingPages) != 0 || len(bundle.Request.ExistingEntityVersions) != 0 {
			return ErrSchemaWikiPreparationInvalid
		}
		return nil
	}
	if err != nil || head == nil || head.WikiReleaseScope != scope ||
		bundle.Request.BaseReleaseID != head.ActiveReleaseID ||
		bundle.Request.BaseActivationEpoch != head.ActivationEpoch {
		return ErrSchemaWikiPreparationInvalid
	}
	release, err := s.releaseAuthority.repository.GetRelease(ctx, scope, head.ActiveReleaseID)
	if err != nil {
		return ErrSchemaWikiPreparationInvalid
	}
	preparation, err := s.releaseAuthority.repository.GetReadyPreparation(ctx, scope, release.PreparationID)
	if err != nil {
		return ErrSchemaWikiPreparationInvalid
	}
	storedMembers, err := s.releaseAuthority.repository.GetReleaseMembers(ctx, scope, release.ID)
	if err != nil || release.ID != head.ActiveReleaseID || release.WikiReleaseScope != scope ||
		release.PreparationID != preparation.ID || preparation.WikiReleaseScope != scope ||
		preparation.Status != types.WikiReleasePreparationReady ||
		release.CandidateDigest != preparation.CandidateDigest ||
		release.ManifestDigest != preparation.ManifestDigest ||
		release.BaseActivationEpoch == ^uint64(0) ||
		head.ActivationEpoch != release.BaseActivationEpoch+1 {
		return ErrSchemaWikiPreparationInvalid
	}
	var header struct {
		Contract string `json:"contract"`
	}
	if json.Unmarshal(preparation.Manifest, &header) != nil {
		return ErrSchemaWikiPreparationInvalid
	}
	if header.Contract == "entity-page-manifest.830.g1.v1" {
		manifest, expectedMembers, validationErr := validateEntityPageGraphPreparation830G1(
			preparation, types.WikiReleasePreparationReady, scope,
		)
		if validationErr != nil || release.BaseReleaseID != manifest.ReleaseID ||
			release.BaseActivationEpoch != manifest.ActivationEpoch ||
			!entityPageGraphMemberSetsEqual830G1(expectedMembers, storedMembers) {
			return ErrSchemaWikiPreparationInvalid
		}
		sourceCustody, sourceErr := s.loadConceptG1SourceCustody830G2(
			ctx, scope, manifest.ReleaseID, manifest.ActivationEpoch,
		)
		existingFields, existingVersions, migrationErr := conceptG1ExistingSnapshot830G2(
			ctx, scope, manifest, sourceCustody, bundle.Request.Sources,
			s.verifyConceptG1Citation830G2,
		)
		if sourceErr != nil || migrationErr != nil || len(bundle.Request.ExistingDefinitions) != 0 ||
			len(bundle.Request.ExistingPages) != 0 ||
			!reflect.DeepEqual(bundle.Request.ExistingFields, existingFields) ||
			!reflect.DeepEqual(bundle.Request.ExistingEntityVersions, existingVersions) {
			return ErrSchemaWikiPreparationInvalid
		}
		return nil
	}
	base, expectedMembers, err := validateConceptPreparation830G2(
		preparation, types.WikiReleasePreparationReady, scope,
	)
	if err != nil ||
		release.BaseReleaseID != base.Request.BaseReleaseID ||
		release.BaseActivationEpoch != base.Request.BaseActivationEpoch ||
		!wikiReleaseMemberSnapshotsEqual(expectedMembers, storedMembers) ||
		!reflect.DeepEqual(bundle.Request.ExistingDefinitions, base.CompileResult.Output.Definitions) ||
		!reflect.DeepEqual(bundle.Request.ExistingFields, base.CompileResult.Output.Fields) ||
		!reflect.DeepEqual(bundle.Request.ExistingPages, base.CompileResult.Output.Pages) ||
		!reflect.DeepEqual(bundle.Request.ExistingEntityVersions, base.Request.EntityVersions) {
		return ErrSchemaWikiPreparationInvalid
	}
	return nil
}

func (s *SchemaWikiService) loadConceptG1SourceCustody830G2(
	ctx context.Context,
	scope types.WikiReleaseScope,
	releaseID string,
	activationEpoch uint64,
) (validatedSchemaWikiCustody, error) {
	var empty validatedSchemaWikiCustody
	if s == nil || s.releaseAuthority == nil || releaseID == "" || activationEpoch == 0 {
		return empty, ErrSchemaWikiPreparationInvalid
	}
	release, err := s.releaseAuthority.repository.GetRelease(ctx, scope, releaseID)
	if err != nil {
		return empty, ErrSchemaWikiPreparationInvalid
	}
	preparation, err := s.releaseAuthority.repository.GetReadyPreparation(
		ctx, scope, release.PreparationID,
	)
	if err != nil {
		return empty, ErrSchemaWikiPreparationInvalid
	}
	storedMembers, err := s.releaseAuthority.repository.GetReleaseMembers(ctx, scope, releaseID)
	if err != nil {
		return empty, ErrSchemaWikiPreparationInvalid
	}
	validated, err := validateSchemaWikiPreparation(
		preparation, types.WikiReleasePreparationReady, scope,
	)
	if err != nil || release.ID != releaseID || release.WikiReleaseScope != scope ||
		release.PreparationID != preparation.ID || release.CandidateDigest != preparation.CandidateDigest ||
		release.ManifestDigest != preparation.ManifestDigest || release.BaseActivationEpoch == ^uint64(0) ||
		release.BaseActivationEpoch+1 != activationEpoch {
		return empty, ErrSchemaWikiPreparationInvalid
	}
	expectedMembers := validated.snapshots
	if validated.isolatedC6 {
		expectedMembers = validated.storedSnapshots
	}
	if _, aligned := schemaWikiAlignReleaseMembers(
		storedMembers, expectedMembers, validated.isolatedC6,
	); !aligned {
		return empty, ErrSchemaWikiPreparationInvalid
	}
	return validated, nil
}

type conceptG1CitationVerifier830G2 func(
	context.Context,
	validatedSchemaWikiCustody,
	CitationRevisionReadRequestV1,
) error

func (s *SchemaWikiService) verifyConceptG1Citation830G2(
	ctx context.Context,
	custody validatedSchemaWikiCustody,
	request CitationRevisionReadRequestV1,
) error {
	_, err := s.issueConceptG1Citation830G2(ctx, custody, request)
	return err
}

func (s *SchemaWikiService) issueConceptG1Citation830G2(
	ctx context.Context,
	custody validatedSchemaWikiCustody,
	request CitationRevisionReadRequestV1,
) (*types.SchemaWikiCitationContentAuthorityV1, error) {
	if s == nil || s.citationContent == nil || !custody.isolatedC6 ||
		request.CoordinateAuthorityReceipt == nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	receipt := request.CoordinateAuthorityReceipt
	if request.Scope.TenantID == 0 || request.Scope.SpaceID == "" || request.Scope.RawKBID == "" ||
		request.Scope.WikiKBID == "" || receipt.TenantID != request.Scope.TenantID ||
		receipt.SpaceID != request.Scope.SpaceID || receipt.RawKBID != request.Scope.RawKBID ||
		receipt.LiveRevisionSourceReceipt.WikiKBID != request.Scope.WikiKBID {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	bound, err := s.bindSchemaWikiC6FrozenNativeSource(custody, request)
	if err != nil || bound.frozenNativeSource == nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	authority, err := s.citationContent.IssueExactRevision(ctx, bound)
	if err != nil || authority == nil || authority.OpaqueToken == "" {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	authorityDigest, digestErr := types.ComputeSchemaWikiCitationContentAuthoritySHA256(*authority)
	if digestErr != nil || authorityDigest != authority.AuthoritySHA256 ||
		authority.ReleaseID != request.ReleaseID || authority.ActivationEpoch != request.ActivationEpoch ||
		authority.CandidateSHA256 != request.CandidateSHA256 || authority.FieldID != request.FieldID ||
		authority.CitationID != request.Citation.CitationID ||
		authority.RevisionSource != receipt.LiveRevisionSourceReceipt ||
		authority.CitationSHA256 != request.Citation.CitationSHA256 ||
		authority.BindingSHA256 != request.Binding.BindingSHA256 ||
		authority.PageNumber != request.Citation.PageNumber || authority.BBox != request.Citation.BBox ||
		authority.QuoteSHA256 != request.Citation.QuoteSHA256 ||
		authority.ContentSnapshotSHA256 != request.Citation.ContentSnapshotSHA256 {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	return authority, nil
}

func conceptG1ExistingSnapshot830G2(
	ctx context.Context,
	scope types.WikiReleaseScope,
	manifest types.EntityPageManifest830G1,
	custody validatedSchemaWikiCustody,
	sources []types.ConceptSourceBlock830G2,
	verifyCitation conceptG1CitationVerifier830G2,
) ([]types.ConceptFieldAssertion830G2, map[string]string, error) {
	if !manifest.FreeWikiEmpty || !entityPageGraphManifestMatchesSchemaSource830G1(manifest, custody) {
		return nil, nil, ErrSchemaWikiPreparationInvalid
	}
	sourceByBlock := make(map[string]types.ConceptSourceBlock830G2, len(sources))
	for _, source := range sources {
		key := source.RevisionID + "\x00" + source.BlockID
		if _, duplicate := sourceByBlock[key]; duplicate {
			return nil, nil, ErrSchemaWikiPreparationInvalid
		}
		sourceByBlock[key] = source
	}
	fields := make([]types.ConceptFieldAssertion830G2, 0, manifest.FieldAssertionCount)
	usedCitations := make(map[string]struct{})
	for _, member := range manifest.Members {
		if member.PageKind != "field" {
			continue
		}
		payload, err := member.FieldAssertionPayload()
		if err != nil {
			return nil, nil, ErrSchemaWikiPreparationInvalid
		}
		field := types.ConceptFieldAssertion830G2{
			SpaceID: scope.SpaceID, EntityID: manifest.EntityID, FieldKey: payload.FieldKey,
			State: payload.State, Attempted: true, ConceptIDs: []string{}, Conditions: []string{},
			Exceptions: []string{}, EntityVersion: manifest.EntityVersionID, ValidTime: "",
		}
		switch payload.State {
		case "unknown":
			reason := payload.SourceTypedReason
			if reason == nil || *reason == "" {
				reason = payload.UnknownReason
			}
			if reason == nil || *reason == "" || payload.ValueSnapshot != nil || len(payload.Citations) != 0 {
				return nil, nil, ErrSchemaWikiPreparationInvalid
			}
			value := *reason
			field.UnknownReason = &value
			field.Evidence = []types.ConceptEvidence830G2{}
		case "present", "absent_explicitly":
			if payload.ValueSnapshot == nil || *payload.ValueSnapshot == "" || len(payload.Citations) == 0 || verifyCitation == nil {
				return nil, nil, ErrSchemaWikiPreparationInvalid
			}
			value := *payload.ValueSnapshot
			field.Value = &value
			field.Evidence = make([]types.ConceptEvidence830G2, 0, len(payload.Citations))
			for _, citation := range payload.Citations {
				if _, duplicate := usedCitations[citation.JoinReceiptSHA256]; duplicate ||
					len(citation.JoinReceiptSHA256) < 24 {
					return nil, nil, ErrSchemaWikiPreparationInvalid
				}
				request, requestErr := schemaWikiCitationRequest(
					custody, scope, manifest.ReleaseID, manifest.ActivationEpoch,
					"field:"+payload.FieldKey, "citation-"+citation.JoinReceiptSHA256[:24],
				)
				if requestErr != nil || request.CoordinateAuthorityReceipt == nil ||
					types.ValidateCitationTarget(request.Citation) != nil ||
					!entityPageGraphCitationMatchesSchemaSource830G1(
						citation, *request.CoordinateAuthorityReceipt, request.Citation,
					) {
					return nil, nil, ErrSchemaWikiPreparationInvalid
				}
				if verifyErr := verifyCitation(ctx, custody, request); verifyErr != nil {
					return nil, nil, ErrSchemaWikiPreparationInvalid
				}
				join := request.CoordinateAuthorityReceipt
				source, exists := sourceByBlock[join.LiveRevisionSourceReceipt.RevisionSourceID+"\x00"+join.LocatorRef]
				textDigest := sha256.Sum256([]byte(source.Text))
				identity := types.ConceptSourceIdentity830G2{
					TenantID: join.TenantID, SpaceID: join.SpaceID, RawKBID: join.RawKBID,
					KnowledgeID: join.KnowledgeID, ParseAttempt: join.WeKnoraParseAttempt,
					RevisionID: join.LiveRevisionSourceReceipt.RevisionSourceID,
					SourceHash: join.SourceSHA256, ParseHash: join.ParseManifestSHA256,
					ParserIdentity: join.ParserIdentitySHA256,
				}
				textRunes := []rune(source.Text)
				if !exists || source.ConceptSourceIdentity830G2 != identity ||
					source.SourceType != "DOCUMENT" || source.BlockID != join.LocatorRef ||
					source.PageNumber != join.PageNumber ||
					hex.EncodeToString(textDigest[:]) != join.ChunkContentSHA256 ||
					join.QuoteOccurrenceStart < 0 || join.QuoteOccurrenceEnd <= join.QuoteOccurrenceStart ||
					join.QuoteOccurrenceEnd > len(textRunes) ||
					string(textRunes[join.QuoteOccurrenceStart:join.QuoteOccurrenceEnd]) != citation.QuoteSnapshot {
					return nil, nil, ErrSchemaWikiPreparationInvalid
				}
				quoteDigest := sha256.Sum256([]byte(citation.QuoteSnapshot))
				field.Evidence = append(field.Evidence, types.ConceptEvidence830G2{
					ConceptSourceIdentity830G2: identity, SourceType: source.SourceType,
					BlockID: source.BlockID, PageNumber: source.PageNumber,
					OffsetUnit: "UNICODE_CODE_POINT", Start: join.QuoteOccurrenceStart,
					End: join.QuoteOccurrenceEnd, Quote: citation.QuoteSnapshot,
					QuoteHash: hex.EncodeToString(quoteDigest[:]),
				})
				usedCitations[citation.JoinReceiptSHA256] = struct{}{}
			}
		default:
			return nil, nil, ErrSchemaWikiPreparationInvalid
		}
		fields = append(fields, field)
	}
	if len(fields) != manifest.FieldAssertionCount || len(usedCitations) != len(custody.candidateEvidenceAuthority.JoinReceipts) {
		return nil, nil, ErrSchemaWikiPreparationInvalid
	}
	return fields, map[string]string{manifest.EntityID: manifest.EntityVersionID}, nil
}

func validateConceptPreparation830G2(
	preparation *types.WikiReleasePreparation,
	expectedStatus string,
	scope types.WikiReleaseScope,
) (types.ConceptCandidateBundle830G2, []types.WikiReleaseMemberSnapshot, error) {
	if preparation == nil || preparation.WikiReleaseScope != scope || preparation.ID == "" ||
		preparation.Status != expectedStatus || preparation.ManifestDigest != digestWikiReleaseBytes(preparation.Manifest) ||
		digestWikiReleasePreparation(preparation) != preparation.PreparationDigest {
		return types.ConceptCandidateBundle830G2{}, nil, ErrSchemaWikiPreparationInvalid
	}
	bundle, err := types.ParseConceptCandidateBundle830G2(preparation.Manifest)
	if err != nil || bundle.Request.TenantID != scope.TenantID || bundle.Request.SpaceID != scope.SpaceID ||
		bundle.Request.RawKBID != scope.RawKBID || bundle.Request.WikiKBID != scope.WikiKBID ||
		preparation.CandidateDigest != bundle.CandidateHash ||
		preparation.ReadyReceiptDigest != bundle.ReviewResult.Execution.RawOutputHash ||
		preparation.ReviewPolicyID != conceptReviewPolicyHash830G2(bundle.Request.PolicyIdentity) ||
		preparation.ExpectedReleaseID != bundle.Request.BaseReleaseID ||
		preparation.ExpectedActivationEpoch != bundle.Request.BaseActivationEpoch {
		return types.ConceptCandidateBundle830G2{}, nil, ErrSchemaWikiPreparationInvalid
	}
	if expectedStatus == types.WikiReleasePreparationDraft && preparation.ReviewDecisionDigest != "" ||
		expectedStatus == types.WikiReleasePreparationReady && preparation.ReviewDecisionDigest == "" {
		return types.ConceptCandidateBundle830G2{}, nil, ErrSchemaWikiPreparationInvalid
	}
	snapshots, err := bundle.SnapshotMembers()
	if err != nil || !wikiReleaseMemberSnapshotsEqual(snapshots, preparation.Members) {
		return types.ConceptCandidateBundle830G2{}, nil, ErrSchemaWikiPreparationInvalid
	}
	return bundle, snapshots, nil
}

func (s *SchemaWikiService) ReadConceptPage830G2(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	memberID string,
	exactReleaseID string,
) (*ConceptPageRead830G2, error) {
	if s == nil || s.releaseAuthority == nil || memberID == "" {
		return nil, ErrWikiReleaseNotFound
	}
	readMode := "current"
	var pin WikiReleasePinnedRead
	var err error
	if exactReleaseID != "" {
		pin, err = s.releaseAuthority.BeginExactPinnedRead(ctx, principal, scope, exactReleaseID)
		readMode = "pinned"
	} else {
		pin, err = s.releaseAuthority.BeginPinnedRead(ctx, principal, scope)
	}
	if err != nil {
		return nil, err
	}
	members, err := s.releaseAuthority.SearchPinned(ctx, principal, pin, "")
	if err != nil {
		return nil, err
	}
	release, err := s.releaseAuthority.repository.GetRelease(ctx, scope, pin.ReleaseID())
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	preparation, err := s.releaseAuthority.repository.GetReadyPreparation(ctx, scope, release.PreparationID)
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	bundle, expected, err := validateConceptPreparation830G2(
		preparation, types.WikiReleasePreparationReady, scope,
	)
	if err != nil || release.CandidateDigest != bundle.CandidateHash ||
		release.ManifestDigest != preparation.ManifestDigest ||
		release.BaseReleaseID != preparation.ExpectedReleaseID ||
		release.BaseActivationEpoch != preparation.ExpectedActivationEpoch ||
		release.BaseReleaseID != bundle.Request.BaseReleaseID ||
		release.BaseActivationEpoch != bundle.Request.BaseActivationEpoch ||
		release.BaseActivationEpoch == ^uint64(0) ||
		pin.ActivationEpoch() != release.BaseActivationEpoch+1 ||
		!wikiReleaseMemberSnapshotsEqual(expected, members) {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	member, ok := conceptPageMemberByID830G2(bundle.PageManifest.Members, memberID)
	if !ok {
		return nil, ErrWikiReleaseNotFound
	}
	result := &ConceptPageRead830G2{
		Contract: "concept-page-read.830.g2.v1", ReadMode: readMode,
		ReleaseID: pin.ReleaseID(), ActivationEpoch: pin.ActivationEpoch(),
		CandidateHash: bundle.CandidateHash, SpaceID: scope.SpaceID,
		RawKBID: scope.RawKBID, WikiKBID: scope.WikiKBID, Member: member,
		RelatedMembers: conceptRelatedMembers830G2(bundle, member),
		Citations:      conceptMemberCitations830G2(bundle, member),
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
			if err != nil {
				return nil, ErrSchemaWikiPreparationInvalid
			}
			break
		}
		if result.DefinitionHash == "" || result.AggregateHash == "" {
			return nil, ErrSchemaWikiPreparationInvalid
		}
	}
	return result, nil
}

// IssueConceptCitationAuthority830G2 replays one citation from an exact,
// immutable G2 release before the trusted source bridge signs a short-lived
// content capability.
func (s *SchemaWikiService) IssueConceptCitationAuthority830G2(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	releaseID string,
	memberID string,
	citationID string,
) (*ConceptCitationContentAuthority830G2, error) {
	if s == nil || s.releaseAuthority == nil || s.releaseAuthority.repository == nil || s.conceptSourceAuthority == nil || releaseID == "" || memberID == "" || citationID == "" {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	pin, bundle, err := s.loadExactConceptBundle830G2(ctx, principal, scope, releaseID)
	if err != nil {
		return nil, err
	}
	evidence, ok := conceptEvidenceByCitationID830G2(bundle, memberID, citationID)
	if !ok {
		return nil, ErrWikiReleaseNotFound
	}
	sourceBlock, ok := conceptSourceBlockForEvidence830G2(bundle, evidence)
	if !ok {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	return s.conceptSourceAuthority.IssueConceptCitationAuthority830G2(ctx, ConceptCitationAuthorityRequest830G2{
		Scope: scope, ReleaseID: pin.ReleaseID(), ActivationEpoch: pin.ActivationEpoch(),
		CandidateHash: bundle.CandidateHash, MemberID: memberID, CitationID: citationID, Evidence: evidence, SourceBlock: sourceBlock, Bundle: &bundle,
	})
}

func (s *SchemaWikiService) loadExactConceptBundle830G2(ctx context.Context, principal types.WikiReleasePrincipal, scope types.WikiReleaseScope, releaseID string) (WikiReleasePinnedRead, types.ConceptCandidateBundle830G2, error) {
	empty := WikiReleasePinnedRead{}
	if s == nil || s.releaseAuthority == nil || s.releaseAuthority.repository == nil {
		return empty, types.ConceptCandidateBundle830G2{}, ErrConceptSourceAuthorityUnavailable830G2
	}
	pin, err := s.releaseAuthority.BeginExactPinnedRead(ctx, principal, scope, releaseID)
	if err != nil {
		return empty, types.ConceptCandidateBundle830G2{}, err
	}
	members, err := s.releaseAuthority.SearchPinned(ctx, principal, pin, "")
	if err != nil {
		return empty, types.ConceptCandidateBundle830G2{}, err
	}
	release, err := s.releaseAuthority.repository.GetRelease(ctx, scope, pin.ReleaseID())
	if err != nil {
		return empty, types.ConceptCandidateBundle830G2{}, mapWikiReleaseRepositoryError(err)
	}
	preparation, err := s.releaseAuthority.repository.GetReadyPreparation(ctx, scope, release.PreparationID)
	if err != nil {
		return empty, types.ConceptCandidateBundle830G2{}, mapWikiReleaseRepositoryError(err)
	}
	bundle, expected, err := validateConceptPreparation830G2(preparation, types.WikiReleasePreparationReady, scope)
	if err != nil || release.CandidateDigest != bundle.CandidateHash || release.ManifestDigest != preparation.ManifestDigest || release.BaseReleaseID != preparation.ExpectedReleaseID || release.BaseActivationEpoch != preparation.ExpectedActivationEpoch || release.BaseReleaseID != bundle.Request.BaseReleaseID || release.BaseActivationEpoch != bundle.Request.BaseActivationEpoch || release.BaseActivationEpoch == ^uint64(0) || pin.ActivationEpoch() != release.BaseActivationEpoch+1 || !wikiReleaseMemberSnapshotsEqual(expected, members) {
		return empty, types.ConceptCandidateBundle830G2{}, ErrSchemaWikiPreparationInvalid
	}
	return pin, bundle, nil
}

func conceptEvidenceByCitationID830G2(bundle types.ConceptCandidateBundle830G2, memberID, citationID string) (types.ConceptEvidence830G2, bool) {
	member, ok := conceptPageMemberByID830G2(bundle.PageManifest.Members, memberID)
	if !ok {
		return types.ConceptEvidence830G2{}, false
	}
	for _, evidence := range conceptMemberEvidence830G2(bundle, member.MemberID) {
		raw, _ := json.Marshal([]any{bundle.CandidateHash, member.MemberID, evidence.RevisionID, evidence.BlockID, evidence.PageNumber, evidence.Start, evidence.End, evidence.QuoteHash})
		sum := sha256.Sum256(raw)
		if citationID == "citation-"+hex.EncodeToString(sum[:])[:24] {
			return evidence, true
		}
	}
	return types.ConceptEvidence830G2{}, false
}

func conceptPageMemberByID830G2(
	members []types.ConceptPageMember830G2,
	memberID string,
) (types.ConceptPageMember830G2, bool) {
	for _, member := range members {
		if member.MemberID == memberID {
			member.Payload = append(json.RawMessage(nil), member.Payload...)
			return member, true
		}
	}
	return types.ConceptPageMember830G2{}, false
}

func conceptRelatedMembers830G2(
	bundle types.ConceptCandidateBundle830G2,
	target types.ConceptPageMember830G2,
) []types.ConceptPageMember830G2 {
	ids := map[string]bool{}
	if target.Kind == "concept" {
		for _, field := range bundle.CompileResult.Output.Fields {
			for _, conceptID := range field.ConceptIDs {
				if conceptID == target.MemberID {
					fieldID, _ := field.FieldAssertionID()
					ids[fieldID] = true
				}
			}
		}
	} else if target.Kind == "entity_overview" || target.Kind == "free_wiki" {
		var navigation struct {
			MemberIDs []string `json:"member_ids"`
		}
		if json.Unmarshal(target.Payload, &navigation) == nil {
			for _, memberID := range navigation.MemberIDs {
				ids[memberID] = true
			}
		}
	} else if target.Kind == "field_assertion" {
		for _, field := range bundle.CompileResult.Output.Fields {
			fieldID, _ := field.FieldAssertionID()
			if fieldID == target.MemberID {
				for _, conceptID := range field.ConceptIDs {
					ids[conceptID] = true
				}
			}
		}
	} else if target.Kind == "free_wiki_item" {
		for _, page := range bundle.CompileResult.Output.Pages {
			pageID, _ := page.FreeWikiPageID()
			if pageID == target.MemberID {
				for _, conceptID := range page.ConceptIDs {
					ids[conceptID] = true
				}
			}
		}
	}
	related := make([]types.ConceptPageMember830G2, 0, len(ids))
	for _, member := range bundle.PageManifest.Members {
		if ids[member.MemberID] {
			member.Payload = append(json.RawMessage(nil), member.Payload...)
			related = append(related, member)
		}
	}
	return related
}

func conceptMemberCitations830G2(
	bundle types.ConceptCandidateBundle830G2,
	member types.ConceptPageMember830G2,
) []ConceptPageCitation830G2 {
	evidence := []types.ConceptEvidence830G2{}
	for _, definition := range bundle.CompileResult.Output.Definitions {
		id, _ := definition.DefinitionID()
		if id == member.MemberID {
			evidence = append(evidence, definition.Evidence...)
		}
	}
	for _, field := range bundle.CompileResult.Output.Fields {
		id, _ := field.FieldAssertionID()
		if id == member.MemberID {
			evidence = append(evidence, field.Evidence...)
		}
	}
	for _, page := range bundle.CompileResult.Output.Pages {
		id, _ := page.FreeWikiPageID()
		if id == member.MemberID {
			evidence = append(evidence, page.Evidence...)
		}
	}
	result := make([]ConceptPageCitation830G2, 0, len(evidence))
	for _, item := range evidence {
		raw, _ := json.Marshal([]any{
			bundle.CandidateHash, member.MemberID, item.RevisionID, item.BlockID,
			item.PageNumber, item.Start, item.End, item.QuoteHash,
		})
		sum := sha256.Sum256(raw)
		result = append(result, ConceptPageCitation830G2{
			CitationID: "citation-" + hex.EncodeToString(sum[:])[:24],
			PageNumber: item.PageNumber, Quote: item.Quote,
		})
	}
	sort.Slice(result, func(i, j int) bool { return result[i].CitationID < result[j].CitationID })
	return result
}

func conceptReviewPolicyHash830G2(policyIdentity string) string {
	return digestWikiReleaseBytes([]byte("concept-review-policy.830.g2.v1\x00" + policyIdentity))
}
