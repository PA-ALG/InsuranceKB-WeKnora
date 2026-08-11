package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"reflect"
	"strings"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
)

var (
	ErrSchemaWikiPreparationInvalid      = errors.New("schema wiki preparation invalid")
	ErrSchemaWikiCitationUnavailable     = errors.New("schema wiki citation unavailable")
	ErrSchemaWikiCitationPageUnavailable = errors.New("schema wiki citation page unavailable")
	ErrNoSchemaWikiActiveRelease         = errors.New("no schema wiki active release")
)

type CitationRevisionReadRequestV1 struct {
	ReleaseID                  string
	ActivationEpoch            uint64
	CandidateSHA256            string
	FieldID                    string
	Scope                      types.WikiReleaseScope
	Citation                   types.CitationTargetV1
	Binding                    types.CitationMemberBindingV1
	EvidenceReceiptSHA256s     []string
	CoordinateAuthorityReceipt *SchemaWikiCitationCoordinateAuthorityReceiptV1
}

type CitationRevisionReadPort interface {
	ReadExactRevision(context.Context, CitationRevisionReadRequestV1) ([]byte, error)
}

type SchemaWikiCitationContentPort interface {
	IssueExactRevision(
		context.Context, CitationRevisionReadRequestV1,
	) (*types.SchemaWikiCitationContentAuthorityV1, error)
	ResolveOpaqueToken(
		context.Context, types.WikiReleaseScope, string,
	) (*types.SchemaWikiCitationContentAuthorityV1, error)
	ReadByOpaqueToken(
		context.Context, types.WikiReleaseScope, string, CitationRevisionReadRequestV1,
	) ([]byte, error)
}

type SchemaWikiService struct {
	releaseAuthority *WikiReleaseService
	citationPort     CitationRevisionReadPort
	citationContent  SchemaWikiCitationContentPort
}

type schemaWikiPreparationCustodyV1 struct {
	Contract                   string                                     `json:"contract"`
	Release                    types.KnowledgeWikiReleaseV1               `json:"release"`
	CandidateEvidenceAuthority types.Schema67CandidateEvidenceAuthorityV1 `json:"candidate_evidence_authority"`
	ReviewBundle               types.SchemaWikiReviewBundleV1             `json:"review_bundle"`
}

type validatedSchemaWikiCustody struct {
	release                    types.KnowledgeWikiReleaseV1
	candidateEvidenceAuthority types.Schema67CandidateEvidenceAuthorityV1
	reviewBundle               types.SchemaWikiReviewBundleV1
	snapshots                  []types.WikiReleaseMemberSnapshot
}

func NewSchemaWikiService(
	releaseAuthority *WikiReleaseService,
	citationPort CitationRevisionReadPort,
	citationContent ...SchemaWikiCitationContentPort,
) *SchemaWikiService {
	service := &SchemaWikiService{releaseAuthority: releaseAuthority, citationPort: citationPort}
	if len(citationContent) == 1 {
		service.citationContent = citationContent[0]
	}
	return service
}

// CreateSchemaDraft is the sole caller-facing Draft entry. It accepts the
// concrete A1/B release and review bundle, validates both, derives exact
// canonical member snapshots, then delegates persistence to the one existing
// release authority.
func (s *SchemaWikiService) CreateSchemaDraft(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
	release types.KnowledgeWikiReleaseV1,
	evidenceAuthority types.Schema67CandidateEvidenceAuthorityV1,
	bundle types.SchemaWikiReviewBundleV1,
) (*types.WikiReleasePreparation, error) {
	if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
		return nil, err
	}
	if s == nil || s.releaseAuthority == nil || preparationID == "" ||
		types.ValidateKnowledgeWikiRelease(release, release.SchemaPack) != nil ||
		types.ValidateSchema67CandidateEvidenceAuthorityV1(evidenceAuthority, release) != nil ||
		types.ValidateSchemaWikiReviewBundle(bundle, release) != nil ||
		bundle.QualityGateReceipt.CandidateEvidenceAuthoritySHA256 != evidenceAuthority.AuthoritySHA256 {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	head, headErr := s.releaseAuthority.repository.GetHeadForWikiKB(ctx, scope.TenantID, scope.WikiKBID)
	if headErr == nil {
		if head == nil || head.WikiReleaseScope != scope {
			return nil, ErrSchemaWikiPreparationInvalid
		}
	} else if !errors.Is(headErr, wikirepository.ErrWikiReleaseNotFound) {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	for _, citation := range schemaWikiReleaseCitations(release) {
		if citation.SpaceID != scope.SpaceID {
			return nil, ErrSchemaWikiPreparationInvalid
		}
	}
	for _, source := range evidenceAuthority.SourceAuthorities {
		live := source.LiveRevisionSourceReceipt
		if live.TenantID != scope.TenantID || live.SpaceID != scope.SpaceID ||
			live.RawKBID != scope.RawKBID || live.WikiKBID != scope.WikiKBID {
			return nil, ErrSchemaWikiPreparationInvalid
		}
	}
	custody, err := schemaWikiPreparationCustodyBytes(release, evidenceAuthority, bundle)
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	draft, err := s.releaseAuthority.createDraft(ctx, principal, &types.WikiReleasePreparation{
		ID:                 preparationID,
		WikiReleaseScope:   scope,
		CandidateDigest:    release.CandidateSHA256,
		ReadyReceiptDigest: bundle.ReviewBundleSHA256,
		ReviewPolicyID:     release.ReviewPolicySHA256,
		Manifest:           custody,
		Members:            schemaWikiReleaseSnapshots(release),
	})
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrSchemaWikiPreparationInvalid, err)
	}
	return draft, nil
}

func schemaWikiPreparationCustodyBytes(
	release types.KnowledgeWikiReleaseV1,
	evidenceAuthority types.Schema67CandidateEvidenceAuthorityV1,
	bundle types.SchemaWikiReviewBundleV1,
) (json.RawMessage, error) {
	if types.ValidateKnowledgeWikiRelease(release, release.SchemaPack) != nil ||
		types.ValidateSchema67CandidateEvidenceAuthorityV1(evidenceAuthority, release) != nil ||
		types.ValidateSchemaWikiReviewBundle(bundle, release) != nil ||
		bundle.QualityGateReceipt.CandidateEvidenceAuthoritySHA256 != evidenceAuthority.AuthoritySHA256 {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	raw, err := json.Marshal(schemaWikiPreparationCustodyV1{
		Contract: "schema-wiki-preparation-custody.v1", Release: release,
		CandidateEvidenceAuthority: evidenceAuthority, ReviewBundle: bundle,
	})
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	return raw, nil
}

func parseSchemaWikiPreparationCustody(
	raw json.RawMessage,
) (schemaWikiPreparationCustodyV1, json.RawMessage, error) {
	var custody schemaWikiPreparationCustodyV1
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&custody); err != nil {
		return custody, nil, ErrSchemaWikiPreparationInvalid
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return custody, nil, ErrSchemaWikiPreparationInvalid
	}
	if canonicalizeSchemaWikiReleasePayloads(&custody.Release) != nil {
		return custody, nil, ErrSchemaWikiPreparationInvalid
	}
	canonical, err := json.Marshal(custody)
	if err != nil || custody.Contract != "schema-wiki-preparation-custody.v1" ||
		types.ValidateKnowledgeWikiRelease(custody.Release, custody.Release.SchemaPack) != nil ||
		types.ValidateSchema67CandidateEvidenceAuthorityV1(
			custody.CandidateEvidenceAuthority, custody.Release,
		) != nil ||
		types.ValidateSchemaWikiReviewBundle(custody.ReviewBundle, custody.Release) != nil ||
		custody.ReviewBundle.QualityGateReceipt.CandidateEvidenceAuthoritySHA256 !=
			custody.CandidateEvidenceAuthority.AuthoritySHA256 {
		return custody, nil, ErrSchemaWikiPreparationInvalid
	}
	return custody, canonical, nil
}

func canonicalizeSchemaWikiReleasePayloads(release *types.KnowledgeWikiReleaseV1) error {
	if release == nil {
		return ErrSchemaWikiPreparationInvalid
	}
	for index := range release.Members {
		member := &release.Members[index]
		canonical, err := types.CanonicalSchemaWikiMemberPayload(member.MemberKind, member.Payload)
		if err != nil {
			return ErrSchemaWikiPreparationInvalid
		}
		member.Payload = canonical
	}
	return nil
}

func schemaWikiReleaseSnapshots(
	release types.KnowledgeWikiReleaseV1,
) []types.WikiReleaseMemberSnapshot {
	members := make([]types.WikiReleaseMemberSnapshot, len(release.Members))
	for index, member := range release.Members {
		members[index] = types.WikiReleaseMemberSnapshot{
			Kind: member.MemberKind, LogicalSlug: member.MemberRef,
			RevisionID: release.ReleaseSHA256, MemberDigest: member.MemberDigest,
			Title: member.MemberRef, Payload: append(json.RawMessage(nil), member.Payload...),
		}
	}
	return members
}

func (s *SchemaWikiService) ReviewSchemaDraft(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
	rawDecision []byte,
) (*types.WikiReleasePreparation, error) {
	if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
		return nil, err
	}
	if s == nil || s.releaseAuthority == nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	return s.releaseAuthority.reviewDraft(ctx, principal, scope, preparationID, rawDecision)
}

func (s *SchemaWikiService) ReadSchemaDraftMember(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
	logicalSlug string,
	revisionID string,
) (*types.WikiReleaseMemberSnapshot, error) {
	if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
		return nil, err
	}
	if s == nil || s.releaseAuthority == nil {
		return nil, ErrWikiReleaseNotFound
	}
	if err := s.releaseAuthority.verifyAccess(ctx, principal, scope, "read-draft"); err != nil {
		return nil, err
	}
	draft, err := s.releaseAuthority.repository.GetDraftPreparation(ctx, scope, preparationID)
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	validated, err := validateSchemaWikiPreparation(
		draft, types.WikiReleasePreparationDraft, scope,
	)
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	for index := range validated.snapshots {
		member := &validated.snapshots[index]
		if member.LogicalSlug == logicalSlug && member.RevisionID == revisionID {
			copy := *member
			copy.Payload = append(json.RawMessage(nil), member.Payload...)
			return &copy, nil
		}
	}
	return nil, ErrWikiReleaseNotFound
}

func requireSchemaWikiHumanAdmin(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
) error {
	if _, ok := types.TenantAPIKeyScopeFromContext(ctx); ok {
		return ErrWikiReleaseAccessDenied
	}
	userID, userOK := types.UserIDFromContext(ctx)
	tenantID, tenantOK := types.TenantIDFromContext(ctx)
	if !userOK || !tenantOK || userID != principal.ID || tenantID != principal.TenantID ||
		principal.TenantID != scope.TenantID ||
		!types.TenantRoleFromContext(ctx).HasPermission(types.TenantRoleAdmin) {
		return ErrWikiReleaseAccessDenied
	}
	return nil
}

func schemaWikiReleaseCitations(release types.KnowledgeWikiReleaseV1) []types.CitationTargetV1 {
	citations := make([]types.CitationTargetV1, 0, len(release.CitationBindings))
	for _, member := range release.Members {
		if member.MemberKind != "field" {
			continue
		}
		var page types.SchemaFieldPageV1
		if err := json.Unmarshal(member.Payload, &page); err != nil {
			return nil
		}
		citations = append(citations, page.Citations...)
	}
	return citations
}

type SchemaWikiMemberReadV1 struct {
	ReadMode      string
	ReleaseID     string
	PreparationID string
	Member        types.WikiReleaseMemberSnapshot
	Payload       json.RawMessage
}

// SchemaWikiCurrentAuthorityV1 is the minimum server-side projection needed
// by navigation routes after a complete Active custody replay.
type SchemaWikiCurrentAuthorityV1 struct {
	ReleaseID       string
	ActivationEpoch uint64
	Domain          types.KnowledgeDomainV1
	Taxonomy        types.TaxonomySnapshotV1
	SchemaPack      types.SchemaPackV1
	Entity          types.EntityIdentityV1
	EntityVersion   types.EntityVersionV1
	Root            types.SchemaRootPageV1
}

// ReadCurrentSchemaAuthority pins current Head and returns only projections
// from the validated full Schema custody envelope.
func (s *SchemaWikiService) ReadCurrentSchemaAuthority(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
) (*SchemaWikiCurrentAuthorityV1, error) {
	if s == nil || s.releaseAuthority == nil {
		return nil, ErrNoSchemaWikiActiveRelease
	}
	pin, err := s.releaseAuthority.BeginPinnedRead(ctx, principal, scope)
	if err != nil {
		if errors.Is(err, ErrWikiReleaseNotFound) {
			return nil, ErrNoSchemaWikiActiveRelease
		}
		return nil, err
	}
	validated, _, err := s.loadPinnedSchemaRelease(ctx, principal, pin)
	if err != nil {
		return nil, err
	}
	root, err := schemaWikiRootPage(validated.release)
	if err != nil {
		return nil, err
	}
	return &SchemaWikiCurrentAuthorityV1{
		ReleaseID: pin.ReleaseID(), ActivationEpoch: pin.ActivationEpoch(),
		Domain:   validated.release.Domain,
		Taxonomy: validated.release.Taxonomy, SchemaPack: validated.release.SchemaPack,
		Entity: validated.release.Entity, EntityVersion: validated.release.EntityVersion,
		Root: root,
	}, nil
}

// ReadReviewedPreparationRoot replays one Ready preparation and returns its
// unique canonical root payload.
func (s *SchemaWikiService) ReadReviewedPreparationRoot(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
) (*types.SchemaRootPageV1, error) {
	if s == nil || s.releaseAuthority == nil {
		return nil, ErrWikiReleaseNotFound
	}
	if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
		return nil, err
	}
	if err := s.releaseAuthority.verifyAccess(ctx, principal, scope, "read-preparation"); err != nil {
		return nil, err
	}
	preparation, err := s.releaseAuthority.repository.GetReadyPreparation(ctx, scope, preparationID)
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	validated, err := validateSchemaWikiPreparation(
		preparation, types.WikiReleasePreparationReady, scope,
	)
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	root, err := schemaWikiRootPage(validated.release)
	if err != nil {
		return nil, err
	}
	return &root, nil
}

func schemaWikiRootPage(release types.KnowledgeWikiReleaseV1) (types.SchemaRootPageV1, error) {
	var root *types.SchemaRootPageV1
	for _, member := range release.Members {
		if member.MemberKind != "root" {
			continue
		}
		if root != nil {
			return types.SchemaRootPageV1{}, ErrSchemaWikiPreparationInvalid
		}
		var page types.SchemaRootPageV1
		if err := json.Unmarshal(member.Payload, &page); err != nil {
			return types.SchemaRootPageV1{}, ErrSchemaWikiPreparationInvalid
		}
		root = &page
	}
	if root == nil {
		return types.SchemaRootPageV1{}, ErrSchemaWikiPreparationInvalid
	}
	return *root, nil
}

func (s *SchemaWikiService) ReadCurrentSchemaMember(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	logicalSlug string,
) (*SchemaWikiMemberReadV1, error) {
	if s == nil || s.releaseAuthority == nil {
		return nil, ErrNoSchemaWikiActiveRelease
	}
	pin, err := s.releaseAuthority.BeginPinnedRead(ctx, principal, scope)
	if err != nil {
		if errors.Is(err, ErrWikiReleaseNotFound) {
			return nil, ErrNoSchemaWikiActiveRelease
		}
		return nil, err
	}
	member, err := s.ReadPinnedSchemaMember(ctx, principal, pin, logicalSlug)
	if err != nil {
		return nil, err
	}
	return schemaWikiMemberRead("active", pin.ReleaseID(), "", member), nil
}

// ReadPinnedSchemaMember validates the complete immutable release behind one
// opaque pin before returning a member. It never accepts a caller release ID.
func (s *SchemaWikiService) ReadPinnedSchemaMember(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	pin WikiReleasePinnedRead,
	logicalSlug string,
) (*types.WikiReleaseMemberSnapshot, error) {
	validated, snapshots, err := s.loadPinnedSchemaRelease(ctx, principal, pin)
	if err != nil {
		return nil, err
	}
	if !schemaWikiValidatedMemberExists(validated, logicalSlug) {
		return nil, ErrWikiReleaseNotFound
	}
	return schemaWikiSnapshotBySlug(snapshots, logicalSlug)
}

func (s *SchemaWikiService) SearchCurrentSchemaMembers(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	query string,
) ([]SchemaWikiMemberReadV1, error) {
	if s == nil || s.releaseAuthority == nil {
		return nil, ErrNoSchemaWikiActiveRelease
	}
	pin, err := s.releaseAuthority.BeginPinnedRead(ctx, principal, scope)
	if err != nil {
		if errors.Is(err, ErrWikiReleaseNotFound) {
			return nil, ErrNoSchemaWikiActiveRelease
		}
		return nil, err
	}
	validated, members, err := s.loadPinnedSchemaRelease(ctx, principal, pin)
	if err != nil {
		return nil, err
	}
	query = strings.ToLower(strings.TrimSpace(query))
	reads := make([]SchemaWikiMemberReadV1, 0, len(members))
	for index := range members {
		member := &members[index]
		if !schemaWikiValidatedMemberExists(validated, member.LogicalSlug) {
			return nil, ErrSchemaWikiPreparationInvalid
		}
		haystack := strings.ToLower(member.LogicalSlug + "\n" + member.Title + "\n" + member.Content)
		if query == "" || strings.Contains(haystack, query) {
			reads = append(reads, *schemaWikiMemberRead("active", pin.ReleaseID(), "", member))
		}
	}
	return reads, nil
}

func (s *SchemaWikiService) ReadReviewedPreparationMember(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
	logicalSlug string,
) (*SchemaWikiMemberReadV1, error) {
	if s == nil || s.releaseAuthority == nil {
		return nil, ErrWikiReleaseNotFound
	}
	if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
		return nil, err
	}
	if err := s.releaseAuthority.verifyAccess(ctx, principal, scope, "read-preparation"); err != nil {
		return nil, err
	}
	preparation, err := s.releaseAuthority.repository.GetReadyPreparation(ctx, scope, preparationID)
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	validated, err := validateSchemaWikiPreparation(
		preparation, types.WikiReleasePreparationReady, scope,
	)
	if err != nil || !schemaWikiValidatedMemberExists(validated, logicalSlug) {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	member, err := schemaWikiSnapshotBySlug(validated.snapshots, logicalSlug)
	if err == nil {
		return schemaWikiMemberRead("reviewed_preparation", "", preparationID, member), nil
	}
	return nil, ErrWikiReleaseNotFound
}

// ReadSchemaPreparationMember is the single human-control-plane read for an
// immutable Draft or Ready preparation. Member revision is derived from the
// validated custody snapshots and is never accepted from the caller.
func (s *SchemaWikiService) ReadSchemaPreparationMember(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
	logicalSlug string,
) (*SchemaWikiMemberReadV1, error) {
	if s == nil || s.releaseAuthority == nil {
		return nil, ErrWikiReleaseNotFound
	}
	if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
		return nil, err
	}
	if err := s.releaseAuthority.verifyAccess(ctx, principal, scope, "read-preparation"); err != nil {
		return nil, err
	}
	preparation, err := s.releaseAuthority.repository.GetDraftPreparation(ctx, scope, preparationID)
	expectedStatus := types.WikiReleasePreparationDraft
	readMode := "draft"
	if errors.Is(err, wikirepository.ErrWikiReleaseNotFound) {
		preparation, err = s.releaseAuthority.repository.GetReadyPreparation(ctx, scope, preparationID)
		expectedStatus = types.WikiReleasePreparationReady
		readMode = "reviewed_preparation"
	}
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	validated, err := validateSchemaWikiPreparation(preparation, expectedStatus, scope)
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	if logicalSlug == "" {
		for _, member := range validated.snapshots {
			if member.Kind == "root" {
				return schemaWikiMemberRead(readMode, "", preparationID, &member), nil
			}
		}
		return nil, ErrSchemaWikiPreparationInvalid
	}
	member, err := schemaWikiSnapshotBySlug(validated.snapshots, logicalSlug)
	if err != nil {
		return nil, err
	}
	return schemaWikiMemberRead(readMode, "", preparationID, member), nil
}

func (s *SchemaWikiService) loadPinnedSchemaRelease(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	pin WikiReleasePinnedRead,
) (validatedSchemaWikiCustody, []types.WikiReleaseMemberSnapshot, error) {
	var empty validatedSchemaWikiCustody
	if s == nil || s.releaseAuthority == nil || pin.releaseID == "" || pin.activationEpoch == 0 {
		return empty, nil, ErrNoSchemaWikiActiveRelease
	}
	if err := s.releaseAuthority.verifyAccess(ctx, principal, pin.scope, "schema-pinned-release"); err != nil {
		return empty, nil, err
	}
	members, err := s.releaseAuthority.repository.GetReleaseMembers(ctx, pin.scope, pin.releaseID)
	if err != nil {
		return empty, nil, mapWikiReleaseRepositoryError(err)
	}
	release, err := s.releaseAuthority.repository.GetRelease(ctx, pin.scope, pin.releaseID)
	if err != nil {
		return empty, nil, mapWikiReleaseRepositoryError(err)
	}
	preparation, err := s.releaseAuthority.repository.GetReadyPreparation(ctx, pin.scope, release.PreparationID)
	if err != nil {
		return empty, nil, mapWikiReleaseRepositoryError(err)
	}
	validated, err := validateSchemaWikiPreparation(
		preparation, types.WikiReleasePreparationReady, pin.scope,
	)
	alignedMembers, aligned := schemaWikiAlignReleaseMembers(members, validated.snapshots)
	if err != nil || release.CandidateDigest != preparation.CandidateDigest ||
		release.ManifestDigest != preparation.ManifestDigest ||
		!aligned {
		return empty, nil, ErrSchemaWikiPreparationInvalid
	}
	return validated, alignedMembers, nil
}

func schemaWikiAlignReleaseMembers(
	materialized []types.WikiReleaseMemberSnapshot,
	expected []types.WikiReleaseMemberSnapshot,
) ([]types.WikiReleaseMemberSnapshot, bool) {
	if !schemaWikiStoredSnapshotsEqual(materialized, expected, false) {
		return nil, false
	}
	aligned := make([]types.WikiReleaseMemberSnapshot, len(expected))
	for index := range expected {
		aligned[index] = expected[index]
		aligned[index].Payload = append(json.RawMessage(nil), expected[index].Payload...)
	}
	return aligned, true
}

func validateSchemaWikiPreparation(
	preparation *types.WikiReleasePreparation,
	expectedStatus string,
	scope types.WikiReleaseScope,
) (validatedSchemaWikiCustody, error) {
	var empty validatedSchemaWikiCustody
	if preparation == nil || preparation.Status != expectedStatus {
		return empty, ErrSchemaWikiPreparationInvalid
	}
	custody, canonicalCustody, err := parseSchemaWikiPreparationCustody(preparation.Manifest)
	if err != nil || preparation.CandidateDigest != custody.Release.CandidateSHA256 ||
		preparation.ReviewPolicyID != custody.Release.ReviewPolicySHA256 ||
		preparation.ReadyReceiptDigest != custody.ReviewBundle.ReviewBundleSHA256 ||
		digestWikiReleaseBytes(canonicalCustody) != preparation.ManifestDigest ||
		digestWikiReleasePreparation(preparation) != preparation.PreparationDigest {
		return empty, ErrSchemaWikiPreparationInvalid
	}
	expectedMembers := schemaWikiReleaseSnapshots(custody.Release)
	if !schemaWikiStoredSnapshotsEqual(preparation.Members, expectedMembers, true) {
		return empty, ErrSchemaWikiPreparationInvalid
	}
	for _, source := range custody.CandidateEvidenceAuthority.SourceAuthorities {
		live := source.LiveRevisionSourceReceipt
		if live.TenantID != scope.TenantID || live.SpaceID != scope.SpaceID ||
			live.RawKBID != scope.RawKBID || live.WikiKBID != scope.WikiKBID {
			return empty, ErrSchemaWikiPreparationInvalid
		}
	}
	for _, member := range custody.Release.Members {
		if member.MemberKind != "field" {
			continue
		}
		var page types.SchemaFieldPageV1
		if err := json.Unmarshal(member.Payload, &page); err != nil {
			return empty, ErrSchemaWikiPreparationInvalid
		}
		for _, citation := range page.Citations {
			if citation.SpaceID != scope.SpaceID {
				return empty, ErrSchemaWikiPreparationInvalid
			}
		}
	}
	return validatedSchemaWikiCustody{
		release: custody.Release, candidateEvidenceAuthority: custody.CandidateEvidenceAuthority,
		reviewBundle: custody.ReviewBundle, snapshots: expectedMembers,
	}, nil
}

func schemaWikiStoredSnapshotsEqual(
	stored []types.WikiReleaseMemberSnapshot,
	expected []types.WikiReleaseMemberSnapshot,
	requireOrder bool,
) bool {
	if len(stored) != len(expected) {
		return false
	}
	expectedBySlug := make(map[string]types.WikiReleaseMemberSnapshot, len(expected))
	for _, want := range expected {
		if _, exists := expectedBySlug[want.LogicalSlug]; exists {
			return false
		}
		expectedBySlug[want.LogicalSlug] = want
	}
	storedBySlug := make(map[string]types.WikiReleaseMemberSnapshot, len(stored))
	for index := range stored {
		want, exists := expectedBySlug[stored[index].LogicalSlug]
		if !exists {
			return false
		}
		normalized, ok := schemaWikiNormalizeStoredSnapshot(stored[index], want)
		if !ok {
			return false
		}
		if _, exists := storedBySlug[normalized.LogicalSlug]; exists {
			return false
		}
		storedBySlug[normalized.LogicalSlug] = normalized
		if requireOrder && !reflect.DeepEqual(normalized, expected[index]) {
			return false
		}
	}
	if requireOrder {
		return true
	}
	for _, want := range expected {
		if got, exists := storedBySlug[want.LogicalSlug]; !exists || !reflect.DeepEqual(got, want) {
			return false
		}
	}
	return true
}

func schemaWikiNormalizeStoredSnapshot(
	snapshot types.WikiReleaseMemberSnapshot,
	expected types.WikiReleaseMemberSnapshot,
) (types.WikiReleaseMemberSnapshot, bool) {
	if snapshot.LogicalSlug != expected.LogicalSlug {
		return types.WikiReleaseMemberSnapshot{}, false
	}
	canonical, err := types.CanonicalSchemaWikiMemberPayload(expected.Kind, snapshot.Payload)
	if err != nil {
		return types.WikiReleaseMemberSnapshot{}, false
	}
	snapshot.Payload = canonical
	return snapshot, true
}

func schemaWikiValidatedMemberExists(
	validated validatedSchemaWikiCustody,
	logicalSlug string,
) bool {
	for _, member := range validated.release.Members {
		if member.MemberRef == logicalSlug {
			return true
		}
	}
	return false
}

func schemaWikiSnapshotBySlug(
	members []types.WikiReleaseMemberSnapshot,
	logicalSlug string,
) (*types.WikiReleaseMemberSnapshot, error) {
	for index := range members {
		if members[index].LogicalSlug == logicalSlug {
			copy := members[index]
			copy.Payload = append(json.RawMessage(nil), members[index].Payload...)
			return &copy, nil
		}
	}
	return nil, ErrWikiReleaseNotFound
}

func schemaWikiMemberRead(
	mode string,
	releaseID string,
	preparationID string,
	member *types.WikiReleaseMemberSnapshot,
) *SchemaWikiMemberReadV1 {
	copy := *member
	copy.Payload = append(json.RawMessage(nil), member.Payload...)
	return &SchemaWikiMemberReadV1{
		ReadMode: mode, ReleaseID: releaseID, PreparationID: preparationID,
		Member: copy, Payload: append(json.RawMessage(nil), member.Payload...),
	}
}

// ReadPinnedSchemaCitation resolves citation authority only from the complete
// immutable release behind the opaque pin. Callers provide identities, never
// CitationTarget or binding custody.
func (s *SchemaWikiService) ReadPinnedSchemaCitation(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	pin WikiReleasePinnedRead,
	logicalSlug string,
	citationID string,
) ([]byte, error) {
	if s == nil || s.citationPort == nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	validated, _, err := s.loadPinnedSchemaRelease(ctx, principal, pin)
	if err != nil {
		return nil, err
	}
	request, err := schemaWikiCitationRequest(
		validated, pin.scope, pin.ReleaseID(), pin.ActivationEpoch(), logicalSlug, citationID,
	)
	if err != nil {
		return nil, err
	}
	opened, err := s.citationPort.ReadExactRevision(ctx, request)
	if err != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	return opened, nil
}

// ReadCurrentSchemaCitation creates the opaque current pin server-side,
// rejects release-id substitution, and then derives citation authority from
// the complete immutable Schema custody behind that pin.
func (s *SchemaWikiService) ReadCurrentSchemaCitation(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	releaseID string,
	logicalSlug string,
	citationID string,
) ([]byte, error) {
	if s == nil || s.releaseAuthority == nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	pin, err := s.releaseAuthority.BeginPinnedRead(ctx, principal, scope)
	if err != nil {
		return nil, err
	}
	if strings.TrimSpace(releaseID) == "" || releaseID != pin.ReleaseID() {
		return nil, ErrWikiReleaseConflict
	}
	return s.ReadPinnedSchemaCitation(ctx, principal, pin, logicalSlug, citationID)
}

// IssueCurrentSchemaCitationAuthority derives the complete citation request
// from validated Active custody and returns a short-lived, server-signed
// content authority. The caller supplies only bounded release/field/citation
// identities.
func (s *SchemaWikiService) IssueCurrentSchemaCitationAuthority(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	releaseID string,
	logicalSlug string,
	citationID string,
) (*types.SchemaWikiCitationContentAuthorityV1, error) {
	if s == nil || s.releaseAuthority == nil || s.citationContent == nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	pin, err := s.releaseAuthority.BeginPinnedRead(ctx, principal, scope)
	if err != nil {
		return nil, err
	}
	if strings.TrimSpace(releaseID) == "" || releaseID != pin.ReleaseID() {
		return nil, ErrWikiReleaseConflict
	}
	validated, _, err := s.loadPinnedSchemaRelease(ctx, principal, pin)
	if err != nil {
		return nil, err
	}
	request, err := schemaWikiCitationRequest(
		validated, pin.scope, pin.ReleaseID(), pin.ActivationEpoch(), logicalSlug, citationID,
	)
	if err != nil {
		return nil, err
	}
	authority, err := s.citationContent.IssueExactRevision(ctx, request)
	if err != nil {
		return nil, err
	}
	return authority, nil
}

// ReadSchemaCitationContent accepts only the opaque token as revision/page
// authority. Scope is independently sealed by the active dual-ACL route and
// rechecked by the concrete release service before immutable bytes are opened.
func (s *SchemaWikiService) ReadSchemaCitationContent(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	token string,
) ([]byte, error) {
	if s == nil || s.releaseAuthority == nil || s.citationContent == nil ||
		strings.TrimSpace(token) == "" {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	if err := s.releaseAuthority.verifyAccess(ctx, principal, scope, "read-citation-content"); err != nil {
		return nil, err
	}
	authority, err := s.citationContent.ResolveOpaqueToken(ctx, scope, token)
	if err != nil {
		return nil, err
	}
	pin, err := s.releaseAuthority.BeginPinnedRead(ctx, principal, scope)
	if err != nil || authority.ReleaseID != pin.ReleaseID() ||
		authority.ActivationEpoch != pin.ActivationEpoch() {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	validated, _, err := s.loadPinnedSchemaRelease(ctx, principal, pin)
	if err != nil {
		return nil, err
	}
	request, err := schemaWikiCitationRequest(
		validated, scope, pin.ReleaseID(), pin.ActivationEpoch(),
		"field:"+authority.FieldID, authority.CitationID,
	)
	if err != nil {
		return nil, err
	}
	opened, err := s.citationContent.ReadByOpaqueToken(ctx, scope, token, request)
	if err != nil {
		return nil, err
	}
	return opened, nil
}

// ReadReviewedPreparationCitation is the reviewer-only counterpart of the
// pinned Active read. Authorization and dual-ACL seal checks happen before the
// Ready row is loaded.
func (s *SchemaWikiService) ReadReviewedPreparationCitation(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
	logicalSlug string,
	citationID string,
) ([]byte, error) {
	if s == nil || s.releaseAuthority == nil || s.citationPort == nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
		return nil, err
	}
	if err := s.releaseAuthority.verifyAccess(ctx, principal, scope, "read-preparation-citation"); err != nil {
		return nil, err
	}
	preparation, err := s.releaseAuthority.repository.GetReadyPreparation(ctx, scope, preparationID)
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	validated, err := validateSchemaWikiPreparation(
		preparation, types.WikiReleasePreparationReady, scope,
	)
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	request, err := schemaWikiCitationRequest(
		validated,
		scope,
		preparation.ExpectedReleaseID,
		preparation.ExpectedActivationEpoch,
		logicalSlug,
		citationID,
	)
	if err != nil {
		return nil, err
	}
	opened, err := s.citationPort.ReadExactRevision(ctx, request)
	if err != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	return opened, nil
}

func schemaWikiCitationRequest(
	validated validatedSchemaWikiCustody,
	scope types.WikiReleaseScope,
	releaseID string,
	activationEpoch uint64,
	logicalSlug string,
	citationID string,
) (CitationRevisionReadRequestV1, error) {
	if releaseID == "" || activationEpoch == 0 || logicalSlug == "" || citationID == "" {
		return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
	}
	var selected *types.CitationTargetV1
	var evidenceReceipts []string
	fieldID := ""
	for _, member := range validated.release.Members {
		if member.MemberRef != logicalSlug || member.MemberKind != "field" {
			continue
		}
		var page types.SchemaFieldPageV1
		if err := json.Unmarshal(member.Payload, &page); err != nil {
			return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
		}
		for index := range page.Citations {
			if page.Citations[index].CitationID == citationID {
				copy := page.Citations[index]
				selected = &copy
				break
			}
		}
		fieldID = page.FieldID
		evidenceReceipts = append([]string(nil), page.EvidenceReceiptSHA256s...)
	}
	if selected == nil {
		return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
	}
	for _, binding := range validated.release.CitationBindings {
		if binding.LogicalMemberRef == logicalSlug && binding.CitationSHA256 == selected.CitationSHA256 {
			var coordinateReceipt *SchemaWikiCitationCoordinateAuthorityReceiptV1
			for index := range validated.candidateEvidenceAuthority.JoinReceipts {
				join := &validated.candidateEvidenceAuthority.JoinReceipts[index]
				if selected.CitationID == "citation-"+join.ReceiptSHA256[:24] &&
					join.FieldID == fieldID {
					copy := *join
					coordinateReceipt = &copy
					break
				}
			}
			if coordinateReceipt == nil {
				return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
			}
			return CitationRevisionReadRequestV1{
				ReleaseID: releaseID, ActivationEpoch: activationEpoch,
				CandidateSHA256: validated.release.CandidateSHA256, FieldID: fieldID,
				Scope: scope, Citation: *selected, Binding: binding,
				EvidenceReceiptSHA256s:     evidenceReceipts,
				CoordinateAuthorityReceipt: coordinateReceipt,
			}, nil
		}
	}
	return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
}

func mapSchemaWikiRepositoryError(err error) error {
	if errors.Is(err, wikirepository.ErrWikiReleaseNotFound) {
		return ErrNoSchemaWikiActiveRelease
	}
	return err
}
