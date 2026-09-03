package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"reflect"
	"strings"

	"github.com/Tencent/WeKnora/internal/types"
)

var (
	ErrEntityPageGraphNotFound830G1  = errors.New("entity page graph 830 g1 not found")
	ErrEntityPageGraphForbidden830G1 = errors.New("entity page graph 830 g1 forbidden")
	ErrEntityPageGraphIntegrity830G1 = errors.New("entity page graph 830 g1 integrity failure")
)

type EntityPageGraphReleaseSnapshot830G1 struct {
	ReleaseID             string
	ActivationEpoch       uint64
	SourceReleaseID       string
	SourceActivationEpoch uint64
	Manifest              json.RawMessage
	Members               []types.WikiReleaseMemberSnapshot
}

type EntityPageGraphReleaseSource830G1 interface {
	LoadCurrentEntityPageGraphRelease830G1(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
	) (EntityPageGraphReleaseSnapshot830G1, error)
	LoadPinnedEntityPageGraphRelease830G1(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
	) (EntityPageGraphReleaseSnapshot830G1, error)
	LoadPreparationEntityPageGraph830G1(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
	) (EntityPageGraphReleaseSnapshot830G1, error)
}

type EntityPageGraphSelector830G1 struct {
	EntityID  string
	PageKind  string
	StableKey string
}

type EntityPageGraphRead830G1 struct {
	Contract        string                                   `json:"contract"`
	ReadMode        string                                   `json:"read_mode"`
	ReleaseID       string                                   `json:"release_id"`
	PreparationID   string                                   `json:"preparation_id,omitempty"`
	ActivationEpoch uint64                                   `json:"activation_epoch"`
	ManifestSHA256  string                                   `json:"manifest_sha256"`
	EntityID        string                                   `json:"entity_id"`
	EntityVersionID string                                   `json:"entity_version_id"`
	DisplayName     string                                   `json:"display_name"`
	Classification  string                                   `json:"classification_display_name"`
	Profile         types.EntityPagePresentationProfile830G1 `json:"profile"`
	Member          types.EntityPageMember830G1              `json:"member"`
}

type EntityPageGraphService830G1 struct {
	source EntityPageGraphReleaseSource830G1
}

func NewEntityPageGraphService830G1(source EntityPageGraphReleaseSource830G1) *EntityPageGraphService830G1 {
	return &EntityPageGraphService830G1{source: source}
}

func (s *EntityPageGraphService830G1) ReadCurrentEntityPage830G1(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	selector EntityPageGraphSelector830G1,
) (*EntityPageGraphRead830G1, error) {
	if s == nil || s.source == nil {
		return nil, ErrEntityPageGraphIntegrity830G1
	}
	snapshot, err := s.source.LoadCurrentEntityPageGraphRelease830G1(ctx, principal, scope)
	if err != nil {
		return nil, mapEntityPageGraphSourceError830G1(err)
	}
	return readEntityPageGraphSnapshot830G1(scope, snapshot, selector, "current")
}

func (s *EntityPageGraphService830G1) ReadPinnedEntityPage830G1(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	releaseID string,
	selector EntityPageGraphSelector830G1,
) (*EntityPageGraphRead830G1, error) {
	releaseID = strings.TrimSpace(releaseID)
	if s == nil || s.source == nil {
		return nil, ErrEntityPageGraphIntegrity830G1
	}
	if releaseID == "" || releaseID == "current" || releaseID == "latest" {
		return nil, ErrEntityPageGraphNotFound830G1
	}
	snapshot, err := s.source.LoadPinnedEntityPageGraphRelease830G1(ctx, principal, scope, releaseID)
	if err != nil {
		return nil, mapEntityPageGraphSourceError830G1(err)
	}
	if snapshot.ReleaseID != releaseID {
		return nil, ErrEntityPageGraphIntegrity830G1
	}
	return readEntityPageGraphSnapshot830G1(scope, snapshot, selector, "pinned")
}

func (s *EntityPageGraphService830G1) ReadPreparationEntityPage830G1(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
	selector EntityPageGraphSelector830G1,
) (*EntityPageGraphRead830G1, error) {
	preparationID = strings.TrimSpace(preparationID)
	if s == nil || s.source == nil {
		return nil, ErrEntityPageGraphIntegrity830G1
	}
	if preparationID == "" || strings.EqualFold(preparationID, "current") ||
		strings.EqualFold(preparationID, "latest") {
		return nil, ErrEntityPageGraphNotFound830G1
	}
	snapshot, err := s.source.LoadPreparationEntityPageGraph830G1(ctx, principal, scope, preparationID)
	if err != nil {
		return nil, mapEntityPageGraphSourceError830G1(err)
	}
	read, err := readEntityPageGraphSnapshot830G1(scope, snapshot, selector, "preparation")
	if err != nil {
		return nil, err
	}
	read.PreparationID = preparationID
	return read, nil
}

func readEntityPageGraphSnapshot830G1(
	scope types.WikiReleaseScope,
	snapshot EntityPageGraphReleaseSnapshot830G1,
	selector EntityPageGraphSelector830G1,
	readMode string,
) (*EntityPageGraphRead830G1, error) {
	manifest, err := types.ParseEntityPageManifest830G1(snapshot.Manifest)
	if err != nil || scope.SpaceID != manifest.SpaceID || scope.WikiKBID != manifest.WikiKBID ||
		len(snapshot.Members) != len(manifest.Members) {
		return nil, ErrEntityPageGraphIntegrity830G1
	}
	switch readMode {
	case "preparation":
		if snapshot.ReleaseID != manifest.ReleaseID ||
			snapshot.ActivationEpoch == 0 || snapshot.ActivationEpoch != manifest.ActivationEpoch ||
			snapshot.SourceReleaseID != manifest.ReleaseID ||
			snapshot.SourceActivationEpoch != manifest.ActivationEpoch {
			return nil, ErrEntityPageGraphIntegrity830G1
		}
	case "current", "pinned":
		if snapshot.ReleaseID == "" || snapshot.ReleaseID == manifest.ReleaseID ||
			snapshot.ActivationEpoch == 0 ||
			snapshot.SourceReleaseID != manifest.ReleaseID ||
			snapshot.SourceActivationEpoch != manifest.ActivationEpoch ||
			snapshot.SourceActivationEpoch == ^uint64(0) ||
			snapshot.ActivationEpoch != snapshot.SourceActivationEpoch+1 {
			return nil, ErrEntityPageGraphIntegrity830G1
		}
	default:
		return nil, ErrEntityPageGraphIntegrity830G1
	}
	storedByPageID := make(map[string]types.WikiReleaseMemberSnapshot, len(snapshot.Members))
	for _, stored := range snapshot.Members {
		if stored.LogicalSlug == "" {
			return nil, ErrEntityPageGraphIntegrity830G1
		}
		if _, duplicate := storedByPageID[stored.LogicalSlug]; duplicate {
			return nil, ErrEntityPageGraphIntegrity830G1
		}
		storedByPageID[stored.LogicalSlug] = stored
	}
	for _, member := range manifest.Members {
		stored, exists := storedByPageID[member.PageID]
		if !exists {
			return nil, ErrEntityPageGraphIntegrity830G1
		}
		if stored.Kind != member.PageKind || stored.LogicalSlug != member.PageID ||
			stored.RevisionID != member.PayloadSHA256 || stored.MemberDigest != member.MemberDigest ||
			stored.Title != member.ShortTitle || !entityPageGraphJSONEqual830G1(stored.Payload, member.Payload) {
			return nil, ErrEntityPageGraphIntegrity830G1
		}
	}
	if !validEntityPageGraphSelector830G1(selector) || selector.EntityID != manifest.EntityID {
		return nil, ErrEntityPageGraphNotFound830G1
	}
	member, found := manifest.Member(selector.PageKind, selector.StableKey)
	if !found {
		return nil, ErrEntityPageGraphNotFound830G1
	}
	return &EntityPageGraphRead830G1{
		Contract: "entity-page-read.830.g1.v1", ReadMode: readMode,
		ReleaseID: snapshot.ReleaseID, ActivationEpoch: snapshot.ActivationEpoch,
		ManifestSHA256: manifest.ManifestSHA256, EntityID: manifest.EntityID,
		EntityVersionID: manifest.EntityVersionID, DisplayName: manifest.DisplayName,
		Classification: manifest.ClassificationDisplayName, Profile: manifest.Profile, Member: member,
	}, nil
}

func entityPageGraphSnapshots830G1(
	manifest types.EntityPageManifest830G1,
) []types.WikiReleaseMemberSnapshot {
	snapshots := make([]types.WikiReleaseMemberSnapshot, 0, len(manifest.Members))
	for _, member := range manifest.Members {
		snapshots = append(snapshots, types.WikiReleaseMemberSnapshot{
			Kind: member.PageKind, LogicalSlug: member.PageID,
			RevisionID: member.PayloadSHA256, MemberDigest: member.MemberDigest,
			Title: member.ShortTitle, Content: "",
			Payload: append(json.RawMessage(nil), member.Payload...),
		})
	}
	return snapshots
}

func validateEntityPageGraphPreparation830G1(
	preparation *types.WikiReleasePreparation,
	expectedStatus string,
	scope types.WikiReleaseScope,
) (types.EntityPageManifest830G1, []types.WikiReleaseMemberSnapshot, error) {
	var empty types.EntityPageManifest830G1
	if preparation == nil || preparation.Status != expectedStatus || preparation.WikiReleaseScope != scope ||
		(preparation.ExpectedReleaseID == "") != (preparation.ExpectedActivationEpoch == 0) {
		return empty, nil, ErrSchemaWikiPreparationInvalid
	}
	manifest, err := types.ParseEntityPageManifest830G1(preparation.Manifest)
	if err != nil || preparation.ID == "" || preparation.CandidateDigest != manifest.InputAuthority.CandidateSHA256 ||
		preparation.ManifestDigest != manifest.ManifestSHA256 ||
		preparation.ExpectedReleaseID != manifest.ReleaseID ||
		preparation.ExpectedActivationEpoch != manifest.ActivationEpoch ||
		preparation.ReadyReceiptDigest == "" || preparation.ReviewPolicyID == "" ||
		manifest.SpaceID != scope.SpaceID || manifest.WikiKBID != scope.WikiKBID ||
		digestWikiReleasePreparation(preparation) != preparation.PreparationDigest {
		return empty, nil, ErrSchemaWikiPreparationInvalid
	}
	expectedMembers := entityPageGraphSnapshots830G1(manifest)
	if !entityPageGraphMemberSetsEqual830G1(preparation.Members, expectedMembers) {
		return empty, nil, ErrSchemaWikiPreparationInvalid
	}
	return manifest, expectedMembers, nil
}

func (s *SchemaWikiService) CreateEntityPageGraphDraft830G1(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
	rawManifest json.RawMessage,
) (*types.WikiReleasePreparation, error) {
	if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
		return nil, err
	}
	preparationID = strings.TrimSpace(preparationID)
	manifest, err := types.ParseEntityPageManifest830G1(rawManifest)
	if s == nil || s.releaseAuthority == nil || preparationID == "" ||
		strings.EqualFold(preparationID, "current") || strings.EqualFold(preparationID, "latest") || err != nil ||
		manifest.SpaceID != scope.SpaceID || manifest.WikiKBID != scope.WikiKBID {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	pin, err := s.releaseAuthority.BeginPinnedRead(ctx, principal, scope)
	if err != nil || pin.ReleaseID() != manifest.ReleaseID || pin.ActivationEpoch() != manifest.ActivationEpoch {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	validated, _, err := s.loadPinnedSchemaRelease(ctx, principal, pin)
	if err != nil || !entityPageGraphManifestMatchesSchemaSource830G1(manifest, validated) {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	release, err := s.releaseAuthority.repository.GetRelease(ctx, scope, pin.ReleaseID())
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	sourcePreparation, err := s.releaseAuthority.repository.GetReadyPreparation(
		ctx, scope, release.PreparationID,
	)
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	if _, validationErr := validateSchemaWikiPreparation(
		sourcePreparation, types.WikiReleasePreparationReady, scope,
	); validationErr != nil || sourcePreparation.CandidateDigest != manifest.InputAuthority.CandidateSHA256 {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	draft, err := s.releaseAuthority.createDraftWithExpectedHead(ctx, principal, &types.WikiReleasePreparation{
		ID: preparationID, WikiReleaseScope: scope,
		CandidateDigest:    manifest.InputAuthority.CandidateSHA256,
		ReadyReceiptDigest: sourcePreparation.ReadyReceiptDigest,
		ReviewPolicyID:     sourcePreparation.ReviewPolicyID,
		Manifest:           append(json.RawMessage(nil), rawManifest...),
		Members:            entityPageGraphSnapshots830G1(manifest),
	}, manifest.ReleaseID, manifest.ActivationEpoch)
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	if _, _, err := validateEntityPageGraphPreparation830G1(
		draft, types.WikiReleasePreparationDraft, scope,
	); err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	return draft, nil
}

func entityPageGraphManifestMatchesSchemaSource830G1(
	manifest types.EntityPageManifest830G1,
	validated validatedSchemaWikiCustody,
) bool {
	release := validated.release
	evidence := validated.candidateEvidenceAuthority
	if manifest.ReleaseID == "" || manifest.EntityID != release.Entity.EntityID ||
		manifest.EntityVersionID != release.EntityVersion.VersionID ||
		manifest.InputAuthority.ProductVersionID != release.EntityVersion.ProductVersionID ||
		manifest.Profile.SchemaPackID != release.SchemaPack.SchemaPackID ||
		manifest.Profile.SchemaVersion != release.SchemaPack.SchemaVersion ||
		manifest.Profile.SchemaPackSHA256 != release.SchemaPack.SchemaPackSHA256 ||
		manifest.InputAuthority.CandidateContract != "schema67-candidate.v2" ||
		manifest.InputAuthority.CandidateSHA256 != release.CandidateSHA256 ||
		manifest.InputAuthority.EvidenceAuthorityContract != evidence.Contract ||
		manifest.InputAuthority.EvidenceAuthoritySHA256 != evidence.AuthoritySHA256 ||
		len(manifest.InputAuthority.SourceAuthorities) != len(evidence.SourceAuthorities) {
		return false
	}
	for index, source := range evidence.SourceAuthorities {
		actual := manifest.InputAuthority.SourceAuthorities[index]
		live := source.LiveRevisionSourceReceipt
		if actual.SourceRole != source.SourceRole || actual.SourceSHA256 != source.SourceSHA256 ||
			actual.KnowledgeID != live.KnowledgeID || actual.ResourceID != live.ResourceID ||
			actual.RevisionSourceID != live.RevisionSourceID ||
			actual.EvidenceParseAttemptID != live.EvidenceParseAttemptID ||
			int64(actual.WeKnoraParseAttempt) != live.WeKnoraParseAttempt ||
			actual.ParsedDocumentSHA256 != live.ParsedDocumentSHA256 ||
			actual.ParseManifestSHA256 != live.ParseManifestSHA256 ||
			actual.SourceReceiptSHA256 != live.SourceReceiptSHA256 {
			return false
		}
	}
	oldFields := make(map[string]types.SchemaFieldPageV1, len(release.SchemaPack.OrderedFieldIDs))
	for _, member := range release.Members {
		if member.MemberKind != "field" {
			continue
		}
		var field types.SchemaFieldPageV1
		if json.Unmarshal(member.Payload, &field) != nil {
			return false
		}
		oldFields[field.FieldID] = field
	}
	joins := make(map[string]types.Schema67CitationAuthorityJoinReceiptV1, len(evidence.JoinReceipts))
	for _, join := range evidence.JoinReceipts {
		if _, duplicate := joins[join.ReceiptSHA256]; duplicate {
			return false
		}
		joins[join.ReceiptSHA256] = join
	}
	usedJoins := make(map[string]struct{}, len(joins))
	for _, member := range manifest.Members {
		if member.PageKind != "field" {
			continue
		}
		candidate, payloadErr := member.FieldAssertionPayload()
		old, exists := oldFields[member.StableKey]
		if payloadErr != nil || !exists || candidate.State != old.State ||
			!reflect.DeepEqual(candidate.ValueSnapshot, old.ValueSnapshot) ||
			candidate.Reference.SourceReleaseID != manifest.ReleaseID ||
			candidate.Reference.SourceCandidateSHA256 != release.CandidateSHA256 ||
			candidate.Reference.ProductVersionID != release.EntityVersion.ProductVersionID ||
			!reflect.DeepEqual(candidate.Reference.EvidenceReceiptSHA256s, old.EvidenceReceiptSHA256s) ||
			len(candidate.Citations) != len(old.Citations) {
			return false
		}
		for _, citation := range candidate.Citations {
			join, exists := joins[citation.JoinReceiptSHA256]
			if !exists || citation.CitationID != "citation_"+join.ReceiptSHA256 ||
				join.FieldID != member.StableKey {
				return false
			}
			if _, duplicate := usedJoins[join.ReceiptSHA256]; duplicate {
				return false
			}
			usedJoins[join.ReceiptSHA256] = struct{}{}
			oldCitationID := "citation-" + join.ReceiptSHA256[:24]
			matched := false
			for _, sourceCitation := range old.Citations {
				if sourceCitation.CitationID != oldCitationID {
					continue
				}
				matched = entityPageGraphCitationMatchesSchemaSource830G1(
					citation, join, sourceCitation,
				)
				break
			}
			if !matched {
				return false
			}
		}
	}
	return len(oldFields) == manifest.FieldAssertionCount && len(usedJoins) == len(joins)
}

func entityPageGraphCitationMatchesSchemaSource830G1(
	candidate types.EntityPageExactCitation830G1,
	join types.Schema67CitationAuthorityJoinReceiptV1,
	source types.CitationTargetV1,
) bool {
	return candidate.JoinReceiptSHA256 == join.ReceiptSHA256 &&
		candidate.EvidenceReceiptSHA256 == join.EvidenceReceiptSHA256 &&
		candidate.SourceRole == join.SourceRole && candidate.SourceSHA256 == join.SourceSHA256 &&
		candidate.SourceRevisionID == join.LiveRevisionSourceReceipt.RevisionSourceID &&
		candidate.KnowledgeID == join.KnowledgeID && candidate.ChunkID == join.ChunkID &&
		candidate.ParseAttemptID == join.EvidenceParseAttemptID &&
		candidate.ParsedDocumentSHA256 == join.ParsedDocumentSHA256 &&
		candidate.ParseManifestSHA256 == join.ParseManifestSHA256 &&
		candidate.PageNumber == join.PageNumber && candidate.LocatorKind == join.LocatorKind &&
		candidate.LocatorRef == join.LocatorRef &&
		candidate.LocatorContentSHA256 == join.LocatorContentSHA256 &&
		candidate.BBox == join.NormalizedBBox && candidate.QuoteSnapshot == source.QuoteSnapshot &&
		candidate.QuoteSHA256 == join.QuoteSHA256 && source.SourceRole == join.SourceRole &&
		source.KnowledgeID == join.KnowledgeID && source.ChunkID == join.ChunkID &&
		source.SourceRevisionID == join.LiveRevisionSourceReceipt.RevisionSourceID &&
		source.ParseAttemptID == join.EvidenceParseAttemptID &&
		source.ParsedDocumentSHA256 == join.ParsedDocumentSHA256 &&
		source.ParseManifestSHA256 == join.ParseManifestSHA256 &&
		source.PageNumber == join.PageNumber && source.LocatorRef == join.LocatorRef &&
		source.BBox == join.NormalizedBBox && source.QuoteSHA256 == join.QuoteSHA256 &&
		source.ContentSnapshotSHA256 == join.LocatorContentSHA256
}

func entityPageGraphCitationRequestFromSource830G1(
	manifest types.EntityPageManifest830G1,
	serving EntityPageGraphReleaseSnapshot830G1,
	validatedSource validatedSchemaWikiCustody,
	scope types.WikiReleaseScope,
	logicalSlug string,
	citationID string,
) (CitationRevisionReadRequestV1, error) {
	fieldKey, fieldRoute := strings.CutPrefix(logicalSlug, "field:")
	servingManifest, manifestErr := types.ParseEntityPageManifest830G1(serving.Manifest)
	if !fieldRoute || strings.TrimSpace(fieldKey) == "" || logicalSlug != "field:"+fieldKey ||
		strings.TrimSpace(citationID) == "" || manifestErr != nil ||
		servingManifest.ManifestSHA256 != manifest.ManifestSHA256 ||
		serving.SourceReleaseID != manifest.ReleaseID ||
		serving.SourceActivationEpoch != manifest.ActivationEpoch ||
		!entityPageGraphManifestMatchesSchemaSource830G1(manifest, validatedSource) {
		return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
	}
	if _, err := readEntityPageGraphSnapshot830G1(
		scope,
		serving,
		EntityPageGraphSelector830G1{
			EntityID: manifest.EntityID, PageKind: "field", StableKey: fieldKey,
		},
		"pinned",
	); err != nil {
		return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
	}
	member, found := manifest.Member("field", fieldKey)
	if !found {
		return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
	}
	payload, err := member.FieldAssertionPayload()
	if err != nil {
		return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
	}
	var candidate *types.EntityPageExactCitation830G1
	for index := range payload.Citations {
		joinSHA256 := payload.Citations[index].JoinReceiptSHA256
		if !validServiceSHA256(joinSHA256) || citationID != "citation-"+joinSHA256[:24] {
			continue
		}
		copy := payload.Citations[index]
		candidate = &copy
		break
	}
	if candidate == nil || candidate.CitationID != "citation_"+candidate.JoinReceiptSHA256 {
		return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
	}
	var join *types.Schema67CitationAuthorityJoinReceiptV1
	for index := range validatedSource.candidateEvidenceAuthority.JoinReceipts {
		receipt := &validatedSource.candidateEvidenceAuthority.JoinReceipts[index]
		if receipt.ReceiptSHA256 == candidate.JoinReceiptSHA256 && receipt.FieldID == fieldKey {
			copy := *receipt
			join = &copy
			break
		}
	}
	if join == nil {
		return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
	}
	request, err := schemaWikiCitationRequest(
		validatedSource,
		scope,
		manifest.ReleaseID,
		manifest.ActivationEpoch,
		logicalSlug,
		citationID,
	)
	if err != nil || request.CoordinateAuthorityReceipt == nil ||
		request.ReleaseID != serving.SourceReleaseID ||
		request.ActivationEpoch != serving.SourceActivationEpoch ||
		request.CandidateSHA256 != manifest.InputAuthority.CandidateSHA256 ||
		request.FieldID != fieldKey ||
		request.CoordinateAuthorityReceipt.ReceiptSHA256 != join.ReceiptSHA256 ||
		!entityPageGraphCitationMatchesSchemaSource830G1(*candidate, *join, request.Citation) {
		return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
	}
	request.citationRouteAuthorityKind = "release"
	request.citationServingReleaseID = serving.ReleaseID
	request.citationServingActivationEpoch = serving.ActivationEpoch
	return request, nil
}

func (s *SchemaWikiService) entityPageGraphCitationRequest830G1(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	servingReleaseID string,
	logicalSlug string,
	citationID string,
) (CitationRevisionReadRequestV1, error) {
	if s == nil || s.releaseAuthority == nil || strings.TrimSpace(servingReleaseID) == "" {
		return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
	}
	serving, err := s.loadEntityPageGraphRelease830G1(
		ctx, principal, scope, servingReleaseID, 0,
	)
	if err != nil {
		return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
	}
	manifest, err := types.ParseEntityPageManifest830G1(serving.Manifest)
	if err != nil {
		return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
	}
	sourcePin := WikiReleasePinnedRead{
		scope: scope, releaseID: serving.SourceReleaseID,
		activationEpoch: serving.SourceActivationEpoch,
	}
	validatedSource, _, err := s.loadPinnedSchemaRelease(ctx, principal, sourcePin)
	if err != nil {
		return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
	}
	request, err := entityPageGraphCitationRequestFromSource830G1(
		manifest, serving, validatedSource, scope, logicalSlug, citationID,
	)
	if err != nil {
		return CitationRevisionReadRequestV1{}, err
	}
	request, err = s.bindSchemaWikiC6FrozenNativeSource(validatedSource, request)
	if err != nil {
		return CitationRevisionReadRequestV1{}, err
	}
	return request, nil
}

func (s *SchemaWikiService) IssueEntityPageGraphPreparationCitationAuthority830G1(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
	entityID string,
	fieldKey string,
	citationID string,
) (*types.SchemaWikiCitationContentAuthorityV1, error) {
	if s == nil || s.releaseAuthority == nil || s.citationContent == nil ||
		strings.TrimSpace(preparationID) == "" || strings.TrimSpace(entityID) == "" ||
		strings.TrimSpace(fieldKey) == "" ||
		strings.TrimSpace(citationID) == "" {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
		return nil, err
	}
	preparation, err := s.releaseAuthority.repository.GetDraftPreparation(ctx, scope, preparationID)
	status := types.WikiReleasePreparationDraft
	if err != nil {
		preparation, err = s.releaseAuthority.repository.GetReadyPreparation(ctx, scope, preparationID)
		status = types.WikiReleasePreparationReady
	}
	if err != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	manifest, _, err := validateEntityPageGraphPreparation830G1(preparation, status, scope)
	if err != nil || manifest.EntityID != entityID {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	member, found := manifest.Member("field", fieldKey)
	if !found {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	payload, err := member.FieldAssertionPayload()
	if err != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	var candidate *types.EntityPageExactCitation830G1
	for index := range payload.Citations {
		if payload.Citations[index].CitationID == citationID {
			copy := payload.Citations[index]
			candidate = &copy
			break
		}
	}
	if candidate == nil || candidate.CitationID != "citation_"+candidate.JoinReceiptSHA256 {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	pin, err := s.releaseAuthority.BeginPinnedRead(ctx, principal, scope)
	if err != nil || pin.ReleaseID() != manifest.ReleaseID || pin.ActivationEpoch() != manifest.ActivationEpoch {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	validated, _, err := s.loadPinnedSchemaRelease(ctx, principal, pin)
	if err != nil || !entityPageGraphManifestMatchesSchemaSource830G1(manifest, validated) {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	var join *types.Schema67CitationAuthorityJoinReceiptV1
	for index := range validated.candidateEvidenceAuthority.JoinReceipts {
		receipt := &validated.candidateEvidenceAuthority.JoinReceipts[index]
		if receipt.ReceiptSHA256 == candidate.JoinReceiptSHA256 && receipt.FieldID == fieldKey {
			join = receipt
			break
		}
	}
	if join == nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	request, err := schemaWikiCitationRequest(
		validated, scope, pin.ReleaseID(), pin.ActivationEpoch(),
		"field:"+fieldKey, "citation-"+join.ReceiptSHA256[:24],
	)
	if err != nil || request.CoordinateAuthorityReceipt == nil ||
		!entityPageGraphCitationMatchesSchemaSource830G1(
			*candidate, *join, request.Citation,
		) || request.CandidateSHA256 != manifest.InputAuthority.CandidateSHA256 ||
		request.FieldID != fieldKey || request.CoordinateAuthorityReceipt.ReceiptSHA256 != join.ReceiptSHA256 {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	request, err = s.bindSchemaWikiC6FrozenNativeSource(validated, request)
	if err != nil {
		return nil, err
	}
	authority, err := s.citationContent.IssueExactRevision(ctx, request)
	if err != nil {
		return nil, err
	}
	return authority, nil
}

func entityPageGraphJSONEqual830G1(left, right json.RawMessage) bool {
	decode := func(raw json.RawMessage) (any, bool) {
		decoder := json.NewDecoder(bytes.NewReader(raw))
		decoder.UseNumber()
		var value any
		if err := decoder.Decode(&value); err != nil {
			return nil, false
		}
		var trailing any
		if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
			return nil, false
		}
		return value, true
	}
	leftValue, leftOK := decode(left)
	rightValue, rightOK := decode(right)
	return leftOK && rightOK && reflect.DeepEqual(leftValue, rightValue)
}

func validEntityPageGraphSelector830G1(selector EntityPageGraphSelector830G1) bool {
	if strings.TrimSpace(selector.EntityID) == "" || strings.TrimSpace(selector.StableKey) == "" {
		return false
	}
	switch selector.PageKind {
	case "overview":
		return selector.StableKey == "overview"
	case "section", "field":
		return true
	case "free_wiki":
		return selector.StableKey == "free-wiki"
	default:
		return false
	}
}

func mapEntityPageGraphSourceError830G1(err error) error {
	switch {
	case errors.Is(err, ErrEntityPageGraphNotFound830G1), errors.Is(err, ErrWikiReleaseNotFound):
		return ErrEntityPageGraphNotFound830G1
	case errors.Is(err, ErrEntityPageGraphForbidden830G1), errors.Is(err, ErrWikiReleaseAccessDenied):
		return ErrEntityPageGraphForbidden830G1
	case errors.Is(err, ErrEntityPageGraphIntegrity830G1), errors.Is(err, ErrWikiReleaseInvalidAuthorization),
		errors.Is(err, ErrSchemaWikiPreparationInvalid):
		return ErrEntityPageGraphIntegrity830G1
	default:
		return ErrEntityPageGraphIntegrity830G1
	}
}

func (s *SchemaWikiService) LoadCurrentEntityPageGraphRelease830G1(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
) (EntityPageGraphReleaseSnapshot830G1, error) {
	if s == nil || s.releaseAuthority == nil {
		return EntityPageGraphReleaseSnapshot830G1{}, ErrEntityPageGraphNotFound830G1
	}
	pin, err := s.releaseAuthority.BeginPinnedRead(ctx, principal, scope)
	if err != nil {
		return EntityPageGraphReleaseSnapshot830G1{}, err
	}
	return s.loadEntityPageGraphRelease830G1(ctx, principal, scope, pin.ReleaseID(), pin.ActivationEpoch())
}

func (s *SchemaWikiService) LoadPinnedEntityPageGraphRelease830G1(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	releaseID string,
) (EntityPageGraphReleaseSnapshot830G1, error) {
	if s == nil || s.releaseAuthority == nil {
		return EntityPageGraphReleaseSnapshot830G1{}, ErrEntityPageGraphNotFound830G1
	}
	return s.loadEntityPageGraphRelease830G1(ctx, principal, scope, releaseID, 0)
}

func (s *SchemaWikiService) LoadPreparationEntityPageGraph830G1(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
) (EntityPageGraphReleaseSnapshot830G1, error) {
	if s == nil || s.releaseAuthority == nil || strings.TrimSpace(preparationID) == "" {
		return EntityPageGraphReleaseSnapshot830G1{}, ErrEntityPageGraphNotFound830G1
	}
	if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
		return EntityPageGraphReleaseSnapshot830G1{}, err
	}
	if err := s.releaseAuthority.verifyAccess(ctx, principal, scope, "entity-page-graph-preparation-830-g1"); err != nil {
		return EntityPageGraphReleaseSnapshot830G1{}, err
	}
	preparation, err := s.releaseAuthority.repository.GetDraftPreparation(ctx, scope, preparationID)
	status := types.WikiReleasePreparationDraft
	if err != nil {
		preparation, err = s.releaseAuthority.repository.GetReadyPreparation(ctx, scope, preparationID)
		status = types.WikiReleasePreparationReady
	}
	if err != nil {
		return EntityPageGraphReleaseSnapshot830G1{}, mapWikiReleaseRepositoryError(err)
	}
	manifest, members, err := validateEntityPageGraphPreparation830G1(preparation, status, scope)
	if err != nil {
		return EntityPageGraphReleaseSnapshot830G1{}, ErrEntityPageGraphIntegrity830G1
	}
	return EntityPageGraphReleaseSnapshot830G1{
		ReleaseID: manifest.ReleaseID, ActivationEpoch: manifest.ActivationEpoch,
		SourceReleaseID: manifest.ReleaseID, SourceActivationEpoch: manifest.ActivationEpoch,
		Manifest: append(json.RawMessage(nil), preparation.Manifest...), Members: members,
	}, nil
}

func (s *SchemaWikiService) loadEntityPageGraphRelease830G1(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	releaseID string,
	activationEpoch uint64,
) (EntityPageGraphReleaseSnapshot830G1, error) {
	if strings.TrimSpace(releaseID) == "" {
		return EntityPageGraphReleaseSnapshot830G1{}, ErrEntityPageGraphNotFound830G1
	}
	if err := s.releaseAuthority.verifyAccess(ctx, principal, scope, "entity-page-graph-830-g1"); err != nil {
		return EntityPageGraphReleaseSnapshot830G1{}, err
	}
	members, err := s.releaseAuthority.repository.GetReleaseMembers(ctx, scope, releaseID)
	if err != nil {
		return EntityPageGraphReleaseSnapshot830G1{}, mapWikiReleaseRepositoryError(err)
	}
	release, err := s.releaseAuthority.repository.GetRelease(ctx, scope, releaseID)
	if err != nil {
		return EntityPageGraphReleaseSnapshot830G1{}, mapWikiReleaseRepositoryError(err)
	}
	preparation, err := s.releaseAuthority.repository.GetReadyPreparation(ctx, scope, release.PreparationID)
	if err != nil {
		return EntityPageGraphReleaseSnapshot830G1{}, mapWikiReleaseRepositoryError(err)
	}
	manifest, manifestErr := types.ParseEntityPageManifest830G1(preparation.Manifest)
	if manifestErr != nil || release.ID != releaseID || release.WikiReleaseScope != scope ||
		release.ID == release.BaseReleaseID ||
		preparation.WikiReleaseScope != scope || preparation.ID != release.PreparationID ||
		preparation.Status != types.WikiReleasePreparationReady ||
		preparation.CandidateDigest != release.CandidateDigest ||
		preparation.ManifestDigest != release.ManifestDigest ||
		manifest.ManifestSHA256 != preparation.ManifestDigest ||
		digestWikiReleasePreparation(preparation) != preparation.PreparationDigest ||
		release.BaseReleaseID != manifest.ReleaseID ||
		release.BaseActivationEpoch != manifest.ActivationEpoch ||
		preparation.ExpectedReleaseID != manifest.ReleaseID ||
		preparation.ExpectedActivationEpoch != manifest.ActivationEpoch ||
		manifest.SpaceID != scope.SpaceID ||
		manifest.WikiKBID != scope.WikiKBID ||
		manifest.InputAuthority.CandidateSHA256 != release.CandidateDigest ||
		!entityPageGraphMemberSetsEqual830G1(preparation.Members, members) {
		return EntityPageGraphReleaseSnapshot830G1{}, ErrEntityPageGraphIntegrity830G1
	}
	if release.BaseActivationEpoch == ^uint64(0) {
		return EntityPageGraphReleaseSnapshot830G1{}, ErrEntityPageGraphIntegrity830G1
	}
	servingActivationEpoch := activationEpoch
	if servingActivationEpoch == 0 {
		servingActivationEpoch = release.BaseActivationEpoch + 1
	}
	if servingActivationEpoch != release.BaseActivationEpoch+1 {
		return EntityPageGraphReleaseSnapshot830G1{}, ErrEntityPageGraphIntegrity830G1
	}
	return EntityPageGraphReleaseSnapshot830G1{
		ReleaseID: releaseID, ActivationEpoch: servingActivationEpoch,
		SourceReleaseID: release.BaseReleaseID, SourceActivationEpoch: release.BaseActivationEpoch,
		Manifest: append(json.RawMessage(nil), preparation.Manifest...), Members: members,
	}, nil
}

func entityPageGraphMemberSetsEqual830G1(
	left []types.WikiReleaseMemberSnapshot,
	right []types.WikiReleaseMemberSnapshot,
) bool {
	if len(left) != len(right) {
		return false
	}
	rightBySlug := make(map[string]types.WikiReleaseMemberSnapshot, len(right))
	for _, member := range right {
		if member.LogicalSlug == "" || member.Content != "" {
			return false
		}
		if _, duplicate := rightBySlug[member.LogicalSlug]; duplicate {
			return false
		}
		rightBySlug[member.LogicalSlug] = member
	}
	for _, member := range left {
		stored, exists := rightBySlug[member.LogicalSlug]
		if !exists || member.Content != "" || stored.Content != "" ||
			member.Kind != stored.Kind || member.RevisionID != stored.RevisionID ||
			member.MemberDigest != stored.MemberDigest || member.Title != stored.Title ||
			!entityPageGraphJSONEqual830G1(member.Payload, stored.Payload) {
			return false
		}
		delete(rightBySlug, member.LogicalSlug)
	}
	return len(rightBySlug) == 0
}
