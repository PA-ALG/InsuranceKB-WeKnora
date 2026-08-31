package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"reflect"
	"sort"
	"strings"
	"time"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
)

func validServiceSHA256(value string) bool {
	if len(value) != 64 || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}

var (
	ErrSchemaWikiPreparationInvalid                    = errors.New("schema wiki preparation invalid")
	ErrSchemaWikiCitationUnavailable                   = errors.New("schema wiki citation unavailable")
	ErrSchemaWikiCitationPageUnavailable               = errors.New("schema wiki citation page unavailable")
	ErrNoSchemaWikiActiveRelease                       = errors.New("no schema wiki active release")
	ErrNoGoldenSuccessorStatus                         = errors.New("no golden successor status")
	ErrSchemaWikiFormalCandidatePreviewRequestInvalid  = errors.New("schema wiki formal candidate preview request invalid")
	ErrSchemaWikiFormalCandidatePreviewNotFound        = errors.New("schema wiki formal candidate preview not found")
	ErrSchemaWikiFormalCandidatePreviewBindingMismatch = errors.New("schema wiki formal candidate preview binding mismatch")
)

type CitationRevisionReadRequestV1 struct {
	ReleaseID                  string
	ActivationEpoch            uint64
	PreparationID              string
	EvaluationID               string
	EvidenceID                 string
	CandidateSHA256            string
	FieldID                    string
	Scope                      types.WikiReleaseScope
	Citation                   types.CitationTargetV1
	Binding                    types.CitationMemberBindingV1
	EvidenceReceiptSHA256s     []string
	CoordinateAuthorityReceipt *SchemaWikiCitationCoordinateAuthorityReceiptV1
	frozenNativeSource         *schemaWikiC5FrozenNativeSource
}

type schemaWikiC5FrozenNativeSource struct {
	experimentID      string
	versionIdentity   string
	revisionSetSHA256 string
	sourceRole        string
	manifest          []byte
	sourceBytes       []byte
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
	IssuePreparationExactRevision(
		context.Context, string, string, string, CitationRevisionReadRequestV1,
	) (*types.SchemaWikiGoldenEvidencePreviewAuthorityV1, error)
	ResolvePreparationOpaqueToken(
		context.Context, types.WikiReleaseScope, string,
	) (*types.SchemaWikiGoldenEvidencePreviewAuthorityV1, error)
	ReadPreparationByOpaqueToken(
		context.Context, types.WikiReleaseScope, string, string, string, string,
		CitationRevisionReadRequestV1,
	) ([]byte, error)
	ResolveRouteAuthority(
		context.Context, string,
	) (*SchemaWikiCitationContentRouteAuthorityV1, error)
}

type SchemaWikiCitationContentRouteAuthorityV1 struct {
	Kind          string
	Scope         types.WikiReleaseScope
	PreparationID string
}

type SchemaWikiService struct {
	releaseAuthority       *WikiReleaseService
	citationPort           CitationRevisionReadPort
	citationContent        SchemaWikiCitationContentPort
	goldenSuccessorStatus  SchemaWikiGoldenSuccessorStatusProvider
	formalCandidatePreview SchemaWikiFormalCandidatePreviewReader
	formalCandidateScope   *types.WikiReleaseScope
}

type SchemaWikiFormalCandidatePreviewReader interface {
	ReadExact(
		uint64, wikirepository.SchemaWikiFormalCandidatePreviewKey,
	) (wikirepository.SchemaWikiFormalCandidatePreviewRecord, error)
	ReadContentExact(
		uint64, wikirepository.SchemaWikiFormalCandidatePreviewKey,
		wikirepository.SchemaWikiFormalCandidatePreviewContentRequest,
	) (wikirepository.SchemaWikiFormalCandidatePreviewContent, error)
}

type schemaWikiFormalCandidateReleaseMemberReader interface {
	ReadReleaseMembersExact(
		uint64, wikirepository.SchemaWikiFormalCandidatePreviewKey,
	) ([]types.WikiReleaseMemberSnapshot, error)
}

type schemaWikiFormalCandidateEvidenceAuthorityReader interface {
	ReadCandidateEvidenceAuthorityExact(
		uint64, wikirepository.SchemaWikiFormalCandidatePreviewKey,
	) (types.Schema67CandidateEvidenceAuthorityV1, error)
}

type schemaWikiFormalCandidateNativeSourceReader interface {
	ReadNativeSourceExact(
		uint64, wikirepository.SchemaWikiFormalCandidatePreviewKey, string,
	) ([]byte, []byte, error)
}

type SchemaWikiFormalCandidatePreviewResponseV1 struct {
	Contract          string          `json:"contract"`
	TenantID          uint64          `json:"tenant_id"`
	WikiKBID          string          `json:"wiki_kb_id"`
	ExperimentID      string          `json:"experiment_id"`
	VersionIdentity   string          `json:"version_identity"`
	ManifestSHA256    string          `json:"manifest_sha256"`
	CandidateSHA256   string          `json:"candidate_sha256"`
	CompanionSHA256   string          `json:"companion_sha256"`
	TerminalSHA256    string          `json:"terminal_sha256"`
	RevisionSetSHA256 string          `json:"revision_set_sha256"`
	PreviewSHA256     string          `json:"preview_sha256"`
	Preview           json.RawMessage `json:"preview"`
	ResponseSHA256    string          `json:"response_sha256"`
}

type schemaWikiPreparationCustodyV1 struct {
	Contract                   string                                        `json:"contract"`
	Release                    types.KnowledgeWikiReleaseV1                  `json:"release"`
	CandidateEvidenceAuthority types.Schema67CandidateEvidenceAuthorityV1    `json:"candidate_evidence_authority"`
	ReviewBundle               types.SchemaWikiReviewBundleV1                `json:"review_bundle"`
	EvaluationBundle           types.Schema67GoldenEvaluationReviewBundleV1  `json:"evaluation_bundle"`
	ReviewSuccessor            types.Schema67GoldenReviewSuccessorMetadataV1 `json:"review_successor"`
}

type schemaWikiC6IsolatedCustodyV1 struct {
	Contract                   string                                      `json:"contract"`
	ExperimentID               string                                      `json:"experiment_id"`
	VersionIdentity            string                                      `json:"version_identity"`
	CandidateSHA256            string                                      `json:"candidate_sha256"`
	PreviewSHA256              string                                      `json:"preview_sha256"`
	CompanionSHA256            string                                      `json:"companion_sha256"`
	TerminalSHA256             string                                      `json:"terminal_sha256"`
	RevisionSetSHA256          string                                      `json:"revision_set_sha256"`
	CandidateEvidenceAuthority *types.Schema67CandidateEvidenceAuthorityV1 `json:"candidate_evidence_authority,omitempty"`
	C4StatusSidecar            map[string]any                              `json:"c4_status_sidecar"`
	C4GateHash                 string                                      `json:"c4_gate_hash"`
	ReviewPatchSHA256          string                                      `json:"review_patch_sha256"`
	ReviewPolicySHA256         string                                      `json:"review_policy_sha256"`
	HumanBatchSHA256           string                                      `json:"human_batch_sha256"`
	HumanDecisionSHA256        string                                      `json:"human_decision_sha256"`
	QualityStatus              string                                      `json:"quality_status"`
	MVPStatus                  string                                      `json:"mvp_status"`
	ProductionStatus           string                                      `json:"production_status"`
	Publishing                 bool                                        `json:"publishing"`
	ContentUnchanged           bool                                        `json:"content_unchanged"`
	OrderedMemberCount         int                                         `json:"ordered_member_count"`
	OrderedMembers             []types.WikiReleaseMemberSnapshot           `json:"ordered_members"`
	OrderedMemberSHA256s       []string                                    `json:"ordered_member_sha256s"`
}

type validatedSchemaWikiCustody struct {
	release                    types.KnowledgeWikiReleaseV1
	candidateEvidenceAuthority types.Schema67CandidateEvidenceAuthorityV1
	reviewBundle               types.SchemaWikiReviewBundleV1
	evaluationBundle           types.Schema67GoldenEvaluationReviewBundleV1
	reviewSuccessor            types.Schema67GoldenReviewSuccessorMetadataV1
	snapshots                  []types.WikiReleaseMemberSnapshot
	storedSnapshots            []types.WikiReleaseMemberSnapshot
	isolatedC6                 bool
	experimentID               string
	versionIdentity            string
	revisionSetSHA256          string
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

// ResolveSchemaCitationContentRouteAuthority verifies the opaque token and
// returns only the server-owned scope needed by the HTTP dual-ACL gate. The
// full token is replayed again by ReadSchemaCitationContent before bytes open.
func (s *SchemaWikiService) ResolveSchemaCitationContentRouteAuthority(
	ctx context.Context,
	token string,
) (*SchemaWikiCitationContentRouteAuthorityV1, error) {
	if s == nil || s.citationContent == nil || strings.TrimSpace(token) == "" {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	return s.citationContent.ResolveRouteAuthority(ctx, token)
}

// NewSchemaWikiServiceWithGoldenSuccessorStatus is the production composition
// seam for the deployment-owned, non-serving 596-1 successor status. The
// existing constructor remains unchanged for callers that intentionally run
// with this status unavailable.
func NewSchemaWikiServiceWithGoldenSuccessorStatus(
	releaseAuthority *WikiReleaseService,
	citationPort CitationRevisionReadPort,
	citationContent SchemaWikiCitationContentPort,
	statusProvider SchemaWikiGoldenSuccessorStatusProvider,
) *SchemaWikiService {
	service := NewSchemaWikiService(releaseAuthority, citationPort, citationContent)
	service.goldenSuccessorStatus = statusProvider
	return service
}

func NewSchemaWikiServiceWithFormalCandidatePreview(
	reader SchemaWikiFormalCandidatePreviewReader,
) *SchemaWikiService {
	return &SchemaWikiService{formalCandidatePreview: reader}
}

// NewSchemaWikiServiceWithFormalCandidatePreviewDecision composes the existing
// Schema Wiki service with the controller-frozen isolated C6 scope. It adds no
// release service or read path; the same WikiReleaseService owns the sole Head.
func NewSchemaWikiServiceWithFormalCandidatePreviewDecision(
	releaseAuthority *WikiReleaseService,
	reader SchemaWikiFormalCandidatePreviewReader,
	scope types.WikiReleaseScope,
) *SchemaWikiService {
	frozenScope := scope
	return &SchemaWikiService{
		releaseAuthority: releaseAuthority, formalCandidatePreview: reader,
		formalCandidateScope: &frozenScope,
	}
}

func NewSchemaWikiServiceWithGoldenSuccessorStatusAndFormalCandidatePreview(
	releaseAuthority *WikiReleaseService,
	citationPort CitationRevisionReadPort,
	citationContent SchemaWikiCitationContentPort,
	statusProvider SchemaWikiGoldenSuccessorStatusProvider,
	reader SchemaWikiFormalCandidatePreviewReader,
	formalCandidateScope ...types.WikiReleaseScope,
) *SchemaWikiService {
	service := NewSchemaWikiServiceWithGoldenSuccessorStatus(
		releaseAuthority, citationPort, citationContent, statusProvider,
	)
	service.formalCandidatePreview = reader
	if len(formalCandidateScope) == 1 {
		frozenScope := formalCandidateScope[0]
		service.formalCandidateScope = &frozenScope
	}
	return service
}

func (s *SchemaWikiService) ReadSchemaWikiFormalCandidatePreview(
	_ context.Context,
	tenantID uint64,
	key wikirepository.SchemaWikiFormalCandidatePreviewKey,
) (*SchemaWikiFormalCandidatePreviewResponseV1, error) {
	if s == nil || s.formalCandidatePreview == nil || tenantID == 0 ||
		strings.TrimSpace(key.KBID) == "" || strings.TrimSpace(key.ExperimentID) == "" ||
		!validServiceSHA256(key.VersionIdentity) {
		return nil, ErrSchemaWikiFormalCandidatePreviewRequestInvalid
	}
	record, err := s.formalCandidatePreview.ReadExact(tenantID, key)
	if err != nil {
		return nil, mapSchemaWikiFormalCandidatePreviewRepositoryError(err)
	}
	if record.TenantID != tenantID || record.KBID != key.KBID ||
		record.ExperimentID != key.ExperimentID || record.ManifestSHA256 != key.VersionIdentity {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	for _, digest := range []string{
		record.ManifestSHA256, record.CandidateSHA256, record.CompanionSHA256,
		record.TerminalSHA256, record.RevisionSetSHA256, record.PreviewSHA256,
	} {
		if !validServiceSHA256(digest) {
			return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
		}
	}
	var preview map[string]any
	decoder := json.NewDecoder(bytes.NewReader(record.Preview))
	decoder.UseNumber()
	if decoder.Decode(&preview) != nil || preview == nil ||
		preview["contract"] != "schema-wiki-formal-candidate-preview.815.v1" ||
		preview["preview_sha256"] != record.PreviewSHA256 {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	var trailing any
	if !errors.Is(decoder.Decode(&trailing), io.EOF) {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	response := &SchemaWikiFormalCandidatePreviewResponseV1{
		Contract: "schema-wiki-formal-candidate-preview-response.815.v1",
		TenantID: tenantID, WikiKBID: record.KBID, ExperimentID: record.ExperimentID,
		VersionIdentity: record.ManifestSHA256, ManifestSHA256: record.ManifestSHA256,
		CandidateSHA256: record.CandidateSHA256, CompanionSHA256: record.CompanionSHA256,
		TerminalSHA256: record.TerminalSHA256, RevisionSetSHA256: record.RevisionSetSHA256,
		PreviewSHA256: record.PreviewSHA256, Preview: append(json.RawMessage(nil), record.Preview...),
	}
	responseHash, err := schemaWikiFormalCandidatePreviewResponseSHA256(response)
	if err != nil {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	response.ResponseSHA256 = responseHash
	return response, nil
}

func (s *SchemaWikiService) ReadSchemaWikiFormalCandidatePreviewContent(
	_ context.Context,
	tenantID uint64,
	key wikirepository.SchemaWikiFormalCandidatePreviewKey,
	request wikirepository.SchemaWikiFormalCandidatePreviewContentRequest,
) ([]byte, error) {
	if s == nil || s.formalCandidatePreview == nil || tenantID == 0 ||
		strings.TrimSpace(key.KBID) == "" || strings.TrimSpace(key.ExperimentID) == "" ||
		!validServiceSHA256(key.VersionIdentity) || strings.TrimSpace(request.FieldID) == "" ||
		strings.TrimSpace(request.SelectionID) == "" {
		return nil, ErrSchemaWikiFormalCandidatePreviewRequestInvalid
	}
	content, err := s.formalCandidatePreview.ReadContentExact(tenantID, key, request)
	if err != nil {
		return nil, mapSchemaWikiFormalCandidatePreviewRepositoryError(err)
	}
	if len(content.Bytes) == 0 || !validServiceSHA256(content.OriginalFileSHA256) {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	sum := sha256.Sum256(content.Bytes)
	if hex.EncodeToString(sum[:]) != content.OriginalFileSHA256 {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	return append([]byte(nil), content.Bytes...), nil
}

// DecideSchemaWikiFormalCandidatePreview applies one named-human whole-batch
// decision to the exact C5 preview. Reject is a verified zero-write result;
// approve creates one isolated immutable release through the existing atomic
// preparation/release/member/Head/receipt transaction.
func (s *SchemaWikiService) DecideSchemaWikiFormalCandidatePreview(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	key wikirepository.SchemaWikiFormalCandidatePreviewKey,
	rawDecision []byte,
	rawAuthorization []byte,
) (*types.HumanBatchDecisionReceiptV1, *types.WikiReleaseReceipt, error) {
	if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
		return nil, nil, err
	}
	if s == nil || s.releaseAuthority == nil || s.formalCandidatePreview == nil ||
		s.formalCandidateScope == nil || *s.formalCandidateScope != scope ||
		scope.RawKBID != key.KBID || scope.WikiKBID == key.KBID {
		return nil, nil, ErrSchemaWikiFormalCandidatePreviewRequestInvalid
	}
	if err := s.releaseAuthority.verifyAccess(ctx, principal, scope, "c6-formal-candidate-decision"); err != nil {
		return nil, nil, err
	}
	response, err := s.ReadSchemaWikiFormalCandidatePreview(ctx, scope.TenantID, key)
	if err != nil {
		return nil, nil, err
	}
	if !schemaWikiC6PreviewStatusExact(response.Preview) {
		return nil, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	decision, decisionDigest, err := s.requireSchemaWikiC6Decision(
		ctx, principal, scope, response, rawDecision,
	)
	if err != nil {
		return nil, nil, err
	}
	if decision.Decision == "reject" {
		if rawAuthorization != nil && !bytes.Equal(rawAuthorization, []byte("null")) {
			return nil, nil, fmt.Errorf("%w: reject authorization must be null", ErrWikiReleaseInvalidAuthorization)
		}
		return decision, nil, nil
	}
	if rawAuthorization == nil || bytes.Equal(rawAuthorization, []byte("null")) {
		return nil, nil, fmt.Errorf("%w: approve authorization missing", ErrWikiReleaseInvalidAuthorization)
	}
	memberReader, ok := s.formalCandidatePreview.(schemaWikiFormalCandidateReleaseMemberReader)
	if !ok {
		return nil, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	members, err := memberReader.ReadReleaseMembersExact(scope.TenantID, key)
	if err != nil || !schemaWikiC6ReleaseMembersExact(response, members) {
		return nil, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	evidenceReader, ok := s.formalCandidatePreview.(schemaWikiFormalCandidateEvidenceAuthorityReader)
	if !ok {
		return nil, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	evidenceAuthority, err := evidenceReader.ReadCandidateEvidenceAuthorityExact(scope.TenantID, key)
	if err != nil || evidenceAuthority.CandidateSHA256 != response.CandidateSHA256 {
		return nil, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	expectedReleaseID, expectedActivationEpoch, err :=
		s.releaseAuthority.isolatedFormalCandidatePreparationHead(ctx, scope, decision.Nonce)
	if err != nil {
		return nil, nil, err
	}
	preparation, err := schemaWikiC6ReadyPreparation(
		scope, response, decisionDigest, members, evidenceAuthority,
		expectedReleaseID, expectedActivationEpoch, s.releaseAuthority.now().UTC(),
	)
	if err != nil {
		return nil, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	authorizationDigest, exactReceipt, err := s.releaseAuthority.requireIsolatedFormalCandidateAuthorization(
		ctx, principal, preparation, decision, decisionDigest, rawAuthorization,
	)
	if err != nil {
		return nil, nil, err
	}
	if exactReceipt != nil {
		return decision, exactReceipt, nil
	}
	releaseReceipt, err := s.releaseAuthority.activateIsolatedFormalCandidatePreview(
		ctx, principal, preparation, decision.Nonce, authorizationDigest,
	)
	if err != nil {
		return nil, nil, err
	}
	return decision, releaseReceipt, nil
}

func (s *SchemaWikiService) requireSchemaWikiC6Decision(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preview *SchemaWikiFormalCandidatePreviewResponseV1,
	raw []byte,
) (*types.HumanBatchDecisionReceiptV1, string, error) {
	decision, err := ParseHumanBatchDecisionReceiptV1(raw)
	if err != nil {
		return nil, "", err
	}
	canonical, err := CanonicalHumanBatchDecisionReceiptV1(decision, true)
	if err != nil || !bytes.Equal(raw, canonical) || s.releaseAuthority.humanDecisionVerifier == nil {
		return nil, "", fmt.Errorf("%w: non-canonical human decision", ErrWikiReleaseInvalidAuthorization)
	}
	if err := s.releaseAuthority.humanDecisionVerifier.Verify(decision); err != nil {
		return nil, "", err
	}
	now := s.releaseAuthority.now().Unix()
	_, _, reviewPolicyHash, humanBatchHash, hashErr := schemaWikiC6DecisionHashes(preview)
	receiptExists := false
	if decision.Nonce != "" {
		_, receiptErr := s.releaseAuthority.repository.GetReceipt(ctx, scope, decision.Nonce)
		switch {
		case receiptErr == nil:
			receiptExists = true
		case !errors.Is(receiptErr, wikirepository.ErrWikiReleaseNotFound):
			return nil, "", receiptErr
		}
	}
	if hashErr != nil || decision.Version != "1" ||
		(decision.Decision != "approve" && decision.Decision != "reject") ||
		(receiptExists && decision.Decision != "approve") ||
		decision.PrincipalID == "" || decision.PrincipalID != principal.ID ||
		decision.WikiReleaseScope != scope || decision.Nonce == "" ||
		decision.IssuedAt <= 0 || decision.ExpiresAt <= decision.IssuedAt ||
		decision.IssuedAt > now || (!receiptExists && decision.ExpiresAt <= now) ||
		decision.CandidateHash != preview.CandidateSHA256 ||
		decision.HumanBatchHash != humanBatchHash ||
		decision.ReviewPolicyHash != reviewPolicyHash {
		if receiptExists {
			return nil, "", &WikiReleaseConflictError{Cause: errors.New("decision nonce input mismatch")}
		}
		return nil, "", fmt.Errorf("%w: invalid C6 human decision", ErrWikiReleaseInvalidAuthorization)
	}
	sum := sha256.Sum256(canonical)
	return decision, hex.EncodeToString(sum[:]), nil
}

func schemaWikiC6DecisionHashes(
	preview *SchemaWikiFormalCandidatePreviewResponseV1,
) (string, string, string, string, error) {
	if preview == nil {
		return "", "", "", "", ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	emptyReviewPatchSum := sha256.Sum256([]byte(
		"insurancekb.c6-review-patch.815.v1\x00schema-wiki-canonical.v1\x00[]",
	))
	emptyReviewPatch := hex.EncodeToString(emptyReviewPatchSum[:])
	digest := func(domain string, value any) (string, error) {
		canonical, err := json.Marshal(value)
		if err != nil {
			return "", err
		}
		sum := sha256.Sum256(append([]byte(domain), canonical...))
		return hex.EncodeToString(sum[:]), nil
	}
	c4Gate, err := digest(
		"insurancekb.c4-status-sidecar.815.v1\x00schema-wiki-canonical.v1\x00c4-status-sidecar.815.v1\x00",
		map[string]any{
			"candidate_sha256": preview.CandidateSHA256,
			"experiment_id":    preview.ExperimentID,
			"quality_status":   "NOT_EVALUATED",
			"version_identity": preview.VersionIdentity,
		},
	)
	if err != nil {
		return "", "", "", "", err
	}
	policy, err := digest(
		"insurancekb.c6-whole-candidate-review-policy.815.v1\x00schema-wiki-canonical.v1\x00",
		map[string]any{
			"c4_gate_hash": c4Gate, "decision_scope": "WHOLE_CANDIDATE",
			"publish_scope": "ISOLATED_R1_ONLY", "review_patch_sha256": emptyReviewPatch,
			"unknown_edit": "FORBIDDEN",
		},
	)
	if err != nil {
		return "", "", "", "", err
	}
	batch, err := digest(
		"insurancekb.c6-whole-candidate-review-subject.815.v1\x00schema-wiki-canonical.v1\x00",
		map[string]any{
			"c4_gate_hash": c4Gate, "candidate_sha256": preview.CandidateSHA256,
			"experiment_id": preview.ExperimentID, "preview_sha256": preview.PreviewSHA256,
			"review_patch_sha256": emptyReviewPatch, "version_identity": preview.VersionIdentity,
		},
	)
	if err != nil {
		return "", "", "", "", err
	}
	return emptyReviewPatch, c4Gate, policy, batch, nil
}

func schemaWikiC6PreviewStatusExact(raw json.RawMessage) bool {
	var value map[string]any
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if decoder.Decode(&value) != nil || value == nil {
		return false
	}
	var trailing any
	return errors.Is(decoder.Decode(&trailing), io.EOF) &&
		value["quality_status"] == "NOT_EVALUATED" &&
		value["mvp_status"] == "NOT_ACCEPTED" && value["publishing"] == false
}

func schemaWikiC6ReleaseMembersExact(
	preview *SchemaWikiFormalCandidatePreviewResponseV1,
	members []types.WikiReleaseMemberSnapshot,
) bool {
	if len(members) != 75 {
		return false
	}
	seen := make(map[string]struct{}, len(members))
	for index, member := range members {
		wantKind := "field"
		if index == 0 {
			wantKind = "root"
		} else if index <= 7 {
			wantKind = "section"
		}
		if member.Kind != wantKind || member.RevisionID != preview.ManifestSHA256 ||
			member.Content != string(member.Payload) ||
			digestWikiReleaseBytes(member.Payload) != member.MemberDigest {
			return false
		}
		if _, exists := seen[member.LogicalSlug]; exists {
			return false
		}
		seen[member.LogicalSlug] = struct{}{}
		var payload map[string]any
		decoder := json.NewDecoder(bytes.NewReader(member.Payload))
		decoder.UseNumber()
		if decoder.Decode(&payload) != nil || len(payload) != 10 ||
			payload["contract"] != "schema-wiki-isolated-r1-member.815.v1" ||
			payload["candidate_sha256"] != preview.CandidateSHA256 ||
			payload["c5_manifest_sha256"] != preview.ManifestSHA256 ||
			payload["c5_preview_sha256"] != preview.PreviewSHA256 ||
			payload["quality_status"] != "NOT_EVALUATED" ||
			payload["mvp_status"] != "NOT_ACCEPTED" ||
			payload["production_status"] != "NOT_FOR_PRODUCTION" ||
			payload["publishing"] != false || payload["member_kind"] != member.Kind ||
			!schemaWikiC6MemberBodyMatches(index, member, payload["body"]) {
			return false
		}
		var trailing any
		if !errors.Is(decoder.Decode(&trailing), io.EOF) {
			return false
		}
	}
	return true
}

func schemaWikiC6MemberBodyMatches(index int, member types.WikiReleaseMemberSnapshot, raw any) bool {
	body, ok := raw.(map[string]any)
	if !ok {
		return false
	}
	identityKey := "field_id"
	wantPrefix := "field:"
	if index == 0 {
		identityKey, wantPrefix = "entity_version_id", "root:"
	} else if index <= 7 {
		identityKey, wantPrefix = "section_id", "section:"
	}
	identity, ok := body[identityKey].(string)
	if !ok || member.LogicalSlug != wantPrefix+identity {
		return false
	}
	if index >= 8 {
		order, ok := body["schema_order"].(json.Number)
		return ok && order.String() == fmt.Sprint(index-7)
	}
	return true
}

func schemaWikiC6ReadyPreparation(
	scope types.WikiReleaseScope,
	preview *SchemaWikiFormalCandidatePreviewResponseV1,
	decisionDigest string,
	members []types.WikiReleaseMemberSnapshot,
	evidenceAuthority types.Schema67CandidateEvidenceAuthorityV1,
	expectedReleaseID string,
	expectedActivationEpoch uint64,
	createdAt time.Time,
) (*types.WikiReleasePreparation, error) {
	if (expectedReleaseID == "") != (expectedActivationEpoch == 0) {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	frozenMembers, err := wikiReleaseMembersPreservingOrder(members)
	if err != nil {
		return nil, err
	}
	memberDigests := make([]string, len(frozenMembers))
	for index := range frozenMembers {
		memberDigests[index] = frozenMembers[index].MemberDigest
	}
	emptyPatch, c4Gate, policy, batch, err := schemaWikiC6DecisionHashes(preview)
	if err != nil {
		return nil, err
	}
	manifest, err := json.Marshal(schemaWikiC6IsolatedCustodyV1{
		Contract:     "schema-wiki-isolated-r1-custody.815.v1",
		ExperimentID: preview.ExperimentID, VersionIdentity: preview.VersionIdentity,
		CandidateSHA256: preview.CandidateSHA256, PreviewSHA256: preview.PreviewSHA256,
		CompanionSHA256: preview.CompanionSHA256, TerminalSHA256: preview.TerminalSHA256,
		RevisionSetSHA256:          preview.RevisionSetSHA256,
		CandidateEvidenceAuthority: &evidenceAuthority,
		C4StatusSidecar: map[string]any{
			"candidate_sha256": preview.CandidateSHA256, "experiment_id": preview.ExperimentID,
			"quality_status": "NOT_EVALUATED", "version_identity": preview.VersionIdentity,
		},
		C4GateHash: c4Gate, ReviewPatchSHA256: emptyPatch,
		ReviewPolicySHA256: policy, HumanBatchSHA256: batch,
		HumanDecisionSHA256: decisionDigest, QualityStatus: "NOT_EVALUATED",
		MVPStatus: "NOT_ACCEPTED", ProductionStatus: "NOT_FOR_PRODUCTION",
		Publishing: false, ContentUnchanged: true, OrderedMemberCount: len(frozenMembers),
		OrderedMembers: frozenMembers, OrderedMemberSHA256s: memberDigests,
	})
	if err != nil {
		return nil, err
	}
	preparation := &types.WikiReleasePreparation{
		ID: decisionDigest, WikiReleaseScope: scope,
		CandidateDigest: preview.CandidateSHA256, ManifestDigest: digestWikiReleaseBytes(manifest),
		ReadyReceiptDigest: batch, ReviewDecisionDigest: decisionDigest,
		ReviewPolicyID: policy, ExpectedReleaseID: expectedReleaseID,
		ExpectedActivationEpoch: expectedActivationEpoch,
		Status:                  types.WikiReleasePreparationReady, Manifest: manifest, Members: frozenMembers,
		CreatedAt: createdAt,
	}
	preparation.PreparationDigest = digestWikiReleasePreparation(preparation)
	return preparation, nil
}

func mapSchemaWikiFormalCandidatePreviewRepositoryError(err error) error {
	switch {
	case errors.Is(err, wikirepository.ErrSchemaWikiFormalCandidatePreviewNotFound):
		return ErrSchemaWikiFormalCandidatePreviewNotFound
	default:
		return ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
}

func schemaWikiFormalCandidatePreviewResponseSHA256(
	response *SchemaWikiFormalCandidatePreviewResponseV1,
) (string, error) {
	raw, err := json.Marshal(response)
	if err != nil {
		return "", err
	}
	var value map[string]any
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if decoder.Decode(&value) != nil || value == nil {
		return "", ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	delete(value, "response_sha256")
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(value); err != nil {
		return "", err
	}
	canonical := bytes.TrimSuffix(buffer.Bytes(), []byte("\n"))
	frontendCanonical := make([]byte, 0, len(canonical))
	for index := 0; index < len(canonical); {
		if canonical[index] != '\\' {
			frontendCanonical = append(frontendCanonical, canonical[index])
			index++
			continue
		}
		start := index
		for index < len(canonical) && canonical[index] == '\\' {
			index++
		}
		if (index-start)%2 == 1 {
			switch {
			case bytes.HasPrefix(canonical[index:], []byte("u2028")):
				frontendCanonical = append(frontendCanonical, canonical[start:index-1]...)
				frontendCanonical = append(frontendCanonical, "\u2028"...)
				index += len("u2028")
				continue
			case bytes.HasPrefix(canonical[index:], []byte("u2029")):
				frontendCanonical = append(frontendCanonical, canonical[start:index-1]...)
				frontendCanonical = append(frontendCanonical, "\u2029"...)
				index += len("u2029")
				continue
			}
		}
		frontendCanonical = append(frontendCanonical, canonical[start:index]...)
	}
	preimage := append(
		[]byte("weknora.schema-wiki-c5.815.v1\x00schema-wiki-formal-candidate-preview-response.815.v1\x00"),
		frontendCanonical...,
	)
	sum := sha256.Sum256(preimage)
	return hex.EncodeToString(sum[:]), nil
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
	evaluation types.Schema67GoldenEvaluationReviewBundleV1,
	reviewSuccessor types.Schema67GoldenReviewSuccessorMetadataV1,
) (*types.WikiReleasePreparation, error) {
	if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
		return nil, err
	}
	if s == nil || s.releaseAuthority == nil || preparationID == "" ||
		types.ValidateKnowledgeWikiRelease(release, release.SchemaPack) != nil ||
		types.ValidateSchema67CandidateEvidenceAuthorityV1(evidenceAuthority, release) != nil ||
		types.ValidateSchemaWikiReviewBundle(bundle, release) != nil ||
		types.ValidateSchema67GoldenEvaluationReviewBundleV1(evaluation) != nil ||
		types.ValidateSchema67GoldenReviewSuccessorMetadataV1(
			reviewSuccessor, evaluation, evidenceAuthority,
		) != nil ||
		!schemaWikiGoldenReviewSuccessorMatchesRelease(reviewSuccessor, release) ||
		bundle.QualityGateReceipt.CandidateEvidenceAuthoritySHA256 != evidenceAuthority.AuthoritySHA256 ||
		!reflect.DeepEqual(bundle.QualityGateReceipt, evaluation.QualityGateReceipt) ||
		evaluation.PrivateDossier.CandidateEvidenceAuthoritySHA256 != evidenceAuthority.AuthoritySHA256 ||
		evaluation.QualityGateReceipt.CandidateSHA256 != release.CandidateSHA256 ||
		!schemaWikiGoldenFieldOrderMatchesPack(evaluation.PrivateDossier, release.SchemaPack) {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	if s.releaseAuthority.qualityGateReceiptVerifier.Verify(&evaluation.QualityGateReceipt) != nil {
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
	custody, err := schemaWikiPreparationCustodyBytes(
		release, evidenceAuthority, bundle, evaluation, reviewSuccessor,
	)
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
	evaluation types.Schema67GoldenEvaluationReviewBundleV1,
	reviewSuccessor types.Schema67GoldenReviewSuccessorMetadataV1,
) (json.RawMessage, error) {
	if types.ValidateKnowledgeWikiRelease(release, release.SchemaPack) != nil ||
		types.ValidateSchema67CandidateEvidenceAuthorityV1(evidenceAuthority, release) != nil ||
		types.ValidateSchemaWikiReviewBundle(bundle, release) != nil ||
		types.ValidateSchema67GoldenEvaluationReviewBundleV1(evaluation) != nil ||
		types.ValidateSchema67GoldenReviewSuccessorMetadataV1(
			reviewSuccessor, evaluation, evidenceAuthority,
		) != nil ||
		!schemaWikiGoldenReviewSuccessorMatchesRelease(reviewSuccessor, release) ||
		bundle.QualityGateReceipt.CandidateEvidenceAuthoritySHA256 != evidenceAuthority.AuthoritySHA256 ||
		!reflect.DeepEqual(bundle.QualityGateReceipt, evaluation.QualityGateReceipt) ||
		evaluation.PrivateDossier.CandidateEvidenceAuthoritySHA256 != evidenceAuthority.AuthoritySHA256 ||
		evaluation.QualityGateReceipt.CandidateSHA256 != release.CandidateSHA256 ||
		!schemaWikiGoldenFieldOrderMatchesPack(evaluation.PrivateDossier, release.SchemaPack) {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	raw, err := json.Marshal(schemaWikiPreparationCustodyV1{
		Contract: "schema-wiki-preparation-custody.v1", Release: release,
		CandidateEvidenceAuthority: evidenceAuthority, ReviewBundle: bundle,
		EvaluationBundle: evaluation, ReviewSuccessor: reviewSuccessor,
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
		types.ValidateSchema67GoldenEvaluationReviewBundleV1(custody.EvaluationBundle) != nil ||
		types.ValidateSchema67GoldenReviewSuccessorMetadataV1(
			custody.ReviewSuccessor, custody.EvaluationBundle,
			custody.CandidateEvidenceAuthority,
		) != nil ||
		!schemaWikiGoldenReviewSuccessorMatchesRelease(
			custody.ReviewSuccessor, custody.Release,
		) ||
		custody.ReviewBundle.QualityGateReceipt.CandidateEvidenceAuthoritySHA256 !=
			custody.CandidateEvidenceAuthority.AuthoritySHA256 ||
		!reflect.DeepEqual(
			custody.ReviewBundle.QualityGateReceipt,
			custody.EvaluationBundle.QualityGateReceipt,
		) || custody.EvaluationBundle.PrivateDossier.CandidateEvidenceAuthoritySHA256 !=
		custody.CandidateEvidenceAuthority.AuthoritySHA256 ||
		!schemaWikiGoldenFieldOrderMatchesPack(
			custody.EvaluationBundle.PrivateDossier, custody.Release.SchemaPack,
		) {
		return custody, nil, ErrSchemaWikiPreparationInvalid
	}
	return custody, canonical, nil
}

func schemaWikiGoldenReviewSuccessorMatchesRelease(
	metadata types.Schema67GoldenReviewSuccessorMetadataV1,
	release types.KnowledgeWikiReleaseV1,
) bool {
	if metadata.CandidateSHA256 != release.CandidateSHA256 ||
		len(metadata.OrderedFields) != len(release.SchemaPack.OrderedFieldIDs) {
		return false
	}
	pageByField := make(map[string]types.SchemaFieldPageV1, len(metadata.OrderedFields))
	for _, member := range release.Members {
		if member.MemberKind != "field" {
			continue
		}
		var page types.SchemaFieldPageV1
		if err := json.Unmarshal(member.Payload, &page); err != nil {
			return false
		}
		pageByField[page.FieldID] = page
	}
	for index, field := range metadata.OrderedFields {
		page, exists := pageByField[field.FieldID]
		if !exists || field.FieldID != release.SchemaPack.OrderedFieldIDs[index] ||
			field.CandidateState != page.State {
			return false
		}
		if page.ValueSnapshot == nil {
			if field.CandidateValue.Mode != "NONE" || field.CandidateValue.Literal != nil ||
				field.CandidateValue.SHA256 != nil {
				return false
			}
			continue
		}
		if field.CandidateValue.Mode != "LITERAL" || field.CandidateValue.Literal == nil ||
			*field.CandidateValue.Literal != *page.ValueSnapshot {
			return false
		}
	}
	return true
}

func schemaWikiGoldenFieldOrderMatchesPack(
	dossier types.Schema67GoldenPrivateDossierV1,
	pack types.SchemaPackV1,
) bool {
	if len(dossier.FieldDecisions) != len(pack.OrderedFieldIDs) {
		return false
	}
	for index, fieldID := range pack.OrderedFieldIDs {
		if dossier.FieldDecisions[index].FieldID != fieldID {
			return false
		}
	}
	return true
}

func (s *SchemaWikiService) loadSchemaPreparationGoldenEvaluation(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
	evaluationID string,
	action string,
) (*types.WikiReleasePreparation, validatedSchemaWikiCustody, error) {
	var empty validatedSchemaWikiCustody
	if s == nil || s.releaseAuthority == nil || strings.TrimSpace(preparationID) == "" ||
		strings.TrimSpace(evaluationID) == "" {
		return nil, empty, ErrSchemaWikiPreparationInvalid
	}
	if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
		return nil, empty, err
	}
	if err := s.releaseAuthority.verifyAccess(ctx, principal, scope, action); err != nil {
		return nil, empty, err
	}
	preparation, err := s.releaseAuthority.repository.GetDraftPreparation(ctx, scope, preparationID)
	expectedStatus := types.WikiReleasePreparationDraft
	if errors.Is(err, wikirepository.ErrWikiReleaseNotFound) {
		preparation, err = s.releaseAuthority.repository.GetReadyPreparation(ctx, scope, preparationID)
		expectedStatus = types.WikiReleasePreparationReady
	}
	if err != nil {
		return nil, empty, mapWikiReleaseRepositoryError(err)
	}
	validated, err := validateSchemaWikiPreparation(preparation, expectedStatus, scope)
	if err != nil || validated.evaluationBundle.EvaluationID != evaluationID {
		return nil, empty, ErrSchemaWikiPreparationInvalid
	}
	return preparation, validated, nil
}

func (s *SchemaWikiService) ReadSchemaPreparationGoldenQualitySummary(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
	evaluationID string,
) (*types.SchemaWikiGoldenQualitySummaryV1, error) {
	_, validated, err := s.loadSchemaPreparationGoldenEvaluation(
		ctx, principal, scope, preparationID, evaluationID, "read-golden-quality-summary",
	)
	if err != nil {
		return nil, err
	}
	bundle := validated.evaluationBundle
	return &types.SchemaWikiGoldenQualitySummaryV1{
		Version:                  "schema-wiki-golden-quality-summary.v1",
		PreparationID:            preparationID,
		EvaluationID:             evaluationID,
		QualityGateReceiptSHA256: bundle.QualityGateReceipt.ReceiptSHA256,
		PublicAggregate:          bundle.PublicAggregate,
		EvaluationBundleSHA256:   bundle.EvaluationBundleSHA256,
		WikiAdmissionAllowed:     false,
		ServingEffect:            "NONE",
	}, nil
}

func (s *SchemaWikiService) ReadSchemaPreparationGoldenQualityDossier(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
	evaluationID string,
) (*types.SchemaWikiGoldenQualityDossierV2, error) {
	_, validated, err := s.loadSchemaPreparationGoldenEvaluation(
		ctx, principal, scope, preparationID, evaluationID, "read-golden-quality-dossier",
	)
	if err != nil {
		return nil, err
	}
	bundle := validated.evaluationBundle
	return &types.SchemaWikiGoldenQualityDossierV2{
		Version:                  "schema-wiki-golden-quality-dossier.v2",
		PreparationID:            preparationID,
		EvaluationID:             evaluationID,
		QualityGateReceiptSHA256: bundle.QualityGateReceipt.ReceiptSHA256,
		PrivateDossier:           bundle.PrivateDossier,
		ReviewSuccessor:          validated.reviewSuccessor,
		EvaluationBundleSHA256:   bundle.EvaluationBundleSHA256,
		ServingEffect:            "NONE",
	}, nil
}

func (s *SchemaWikiService) IssueSchemaPreparationGoldenEvidencePreview(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
	evaluationID string,
	fieldID string,
	evidenceID string,
) (*types.SchemaWikiGoldenEvidencePreviewAuthorityV1, error) {
	if s == nil || s.citationContent == nil || strings.TrimSpace(fieldID) == "" ||
		!validServiceSHA256(evidenceID) {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	_, validated, err := s.loadSchemaPreparationGoldenEvaluation(
		ctx, principal, scope, preparationID, evaluationID, "read-golden-evidence-preview",
	)
	if err != nil {
		return nil, err
	}
	fieldPresent := false
	for _, decision := range validated.evaluationBundle.PrivateDossier.FieldDecisions {
		if decision.FieldID == fieldID && decision.EvidenceFragments > 0 {
			fieldPresent = true
			break
		}
	}
	if !fieldPresent || len(evidenceID) < 24 {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	request, err := schemaWikiPreparationCitationRequest(
		validated,
		scope,
		preparationID,
		evaluationID,
		evidenceID,
		"field:"+fieldID,
		"citation-"+evidenceID[:24],
	)
	if err != nil || request.CoordinateAuthorityReceipt == nil ||
		request.CoordinateAuthorityReceipt.ReceiptSHA256 != evidenceID ||
		request.CoordinateAuthorityReceipt.FieldID != fieldID {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	authority, err := s.citationContent.IssuePreparationExactRevision(
		ctx, preparationID, evaluationID, evidenceID, request,
	)
	if err != nil {
		return nil, err
	}
	if authority == nil || authority.PreparationID != preparationID ||
		authority.EvaluationID != evaluationID || authority.FieldID != fieldID ||
		authority.EvidenceID != evidenceID ||
		authority.CandidateSHA256 != validated.release.CandidateSHA256 ||
		types.ValidateSchemaWikiGoldenEvidencePreviewAuthorityV1(*authority) != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	return authority, nil
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
	contextPrincipal, contextPrincipalOK := types.PrincipalFromContext(ctx)
	contextPrincipal = contextPrincipal.Normalize()
	canonicalPrincipalID := principal.ID
	if canonicalPrincipalID == contextPrincipal.ID {
		canonicalPrincipalID = (types.Principal{
			Type: types.PrincipalWebUser,
			ID:   canonicalPrincipalID,
		}).StorageID()
	}
	if !userOK || !tenantOK || !contextPrincipalOK ||
		contextPrincipal.Type != types.PrincipalWebUser ||
		contextPrincipal.ID != strings.TrimSpace(userID) ||
		canonicalPrincipalID != contextPrincipal.StorageID() ||
		tenantID != principal.TenantID ||
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
	if err != nil {
		return empty, nil, err
	}
	expectedSnapshots := validated.snapshots
	if validated.isolatedC6 {
		expectedSnapshots = validated.storedSnapshots
	}
	alignedMembers, aligned := schemaWikiAlignReleaseMembers(
		members, expectedSnapshots, validated.isolatedC6,
	)
	baseIdentityMatches := !validated.isolatedC6 ||
		(release.BaseReleaseID == preparation.ExpectedReleaseID &&
			release.BaseActivationEpoch == preparation.ExpectedActivationEpoch &&
			release.BaseActivationEpoch == pin.activationEpoch-1)
	if release.CandidateDigest != preparation.CandidateDigest ||
		release.ManifestDigest != preparation.ManifestDigest ||
		!baseIdentityMatches || !aligned {
		return empty, nil, ErrSchemaWikiPreparationInvalid
	}
	if validated.isolatedC6 {
		alignedMembers = make([]types.WikiReleaseMemberSnapshot, len(validated.snapshots))
		for index := range validated.snapshots {
			alignedMembers[index] = validated.snapshots[index]
			alignedMembers[index].Payload = append(
				json.RawMessage(nil), validated.snapshots[index].Payload...,
			)
		}
	}
	return validated, alignedMembers, nil
}

func schemaWikiAlignReleaseMembers(
	materialized []types.WikiReleaseMemberSnapshot,
	expected []types.WikiReleaseMemberSnapshot,
	isolatedC6 bool,
) ([]types.WikiReleaseMemberSnapshot, bool) {
	if isolatedC6 {
		var ok bool
		materialized, ok = restoreSchemaWikiC6JSONBMemberPayloads(materialized)
		if !ok {
			return nil, false
		}
	}
	if (isolatedC6 && !wikiReleaseMemberSnapshotsEqual(materialized, expected)) ||
		(!isolatedC6 && !schemaWikiStoredSnapshotsEqual(materialized, expected, false)) {
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
	if err != nil {
		return validateSchemaWikiC6IsolatedPreparation(preparation, expectedStatus, scope)
	}
	if preparation.CandidateDigest != custody.Release.CandidateSHA256 ||
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
		reviewBundle: custody.ReviewBundle, evaluationBundle: custody.EvaluationBundle,
		reviewSuccessor: custody.ReviewSuccessor,
		snapshots:       expectedMembers,
	}, nil
}

func validateSchemaWikiC6IsolatedPreparation(
	preparation *types.WikiReleasePreparation,
	expectedStatus string,
	scope types.WikiReleaseScope,
) (validatedSchemaWikiCustody, error) {
	var empty validatedSchemaWikiCustody
	if preparation == nil || preparation.Status != expectedStatus ||
		preparation.WikiReleaseScope != scope ||
		(preparation.ExpectedReleaseID == "") != (preparation.ExpectedActivationEpoch == 0) {
		return empty, ErrSchemaWikiPreparationInvalid
	}
	custody, canonical, err := canonicalSchemaWikiC6StoredManifest(preparation.Manifest)
	if err != nil || custody.Contract != "schema-wiki-isolated-r1-custody.815.v1" ||
		custody.ExperimentID == "" || !validServiceSHA256(custody.VersionIdentity) ||
		!validServiceSHA256(custody.CandidateSHA256) ||
		!validServiceSHA256(custody.PreviewSHA256) ||
		!validServiceSHA256(custody.CompanionSHA256) ||
		!validServiceSHA256(custody.TerminalSHA256) ||
		!validServiceSHA256(custody.RevisionSetSHA256) ||
		!validServiceSHA256(custody.HumanDecisionSHA256) ||
		custody.QualityStatus != "NOT_EVALUATED" || custody.MVPStatus != "NOT_ACCEPTED" ||
		custody.ProductionStatus != "NOT_FOR_PRODUCTION" || custody.Publishing ||
		!custody.ContentUnchanged || custody.OrderedMemberCount != 75 ||
		len(custody.OrderedMembers) != 75 || len(custody.OrderedMemberSHA256s) != 75 {
		return empty, ErrSchemaWikiPreparationInvalid
	}
	storedMembers, ok := restoreSchemaWikiC6JSONBMemberPayloads(preparation.Members)
	if !ok {
		return empty, ErrSchemaWikiPreparationInvalid
	}
	preview := &SchemaWikiFormalCandidatePreviewResponseV1{
		ExperimentID: custody.ExperimentID, VersionIdentity: custody.VersionIdentity,
		ManifestSHA256: custody.VersionIdentity, CandidateSHA256: custody.CandidateSHA256,
		CompanionSHA256: custody.CompanionSHA256, TerminalSHA256: custody.TerminalSHA256,
		RevisionSetSHA256: custody.RevisionSetSHA256, PreviewSHA256: custody.PreviewSHA256,
	}
	emptyPatch, c4Gate, policy, batch, err := schemaWikiC6DecisionHashes(preview)
	expectedSidecar := map[string]any{
		"candidate_sha256": custody.CandidateSHA256, "experiment_id": custody.ExperimentID,
		"quality_status": "NOT_EVALUATED", "version_identity": custody.VersionIdentity,
	}
	if err != nil || custody.ReviewPatchSHA256 != emptyPatch || custody.C4GateHash != c4Gate ||
		custody.ReviewPolicySHA256 != policy || custody.HumanBatchSHA256 != batch ||
		!reflect.DeepEqual(custody.C4StatusSidecar, expectedSidecar) ||
		preparation.ID != custody.HumanDecisionSHA256 ||
		preparation.CandidateDigest != custody.CandidateSHA256 ||
		preparation.ReadyReceiptDigest != batch || preparation.ReviewPolicyID != policy ||
		preparation.ReviewDecisionDigest != custody.HumanDecisionSHA256 ||
		digestWikiReleaseBytes(canonical) != preparation.ManifestDigest ||
		digestWikiReleasePreparation(preparation) != preparation.PreparationDigest ||
		!reflect.DeepEqual(storedMembers, custody.OrderedMembers) ||
		!schemaWikiC6ReleaseMembersExact(preview, custody.OrderedMembers) {
		return empty, ErrSchemaWikiPreparationInvalid
	}
	for index := range custody.OrderedMembers {
		if custody.OrderedMemberSHA256s[index] != custody.OrderedMembers[index].MemberDigest {
			return empty, ErrSchemaWikiPreparationInvalid
		}
	}
	frozen, err := wikiReleaseMembersPreservingOrder(custody.OrderedMembers)
	if err != nil || !reflect.DeepEqual(frozen, custody.OrderedMembers) {
		return empty, ErrSchemaWikiPreparationInvalid
	}
	release, err := schemaWikiC6ReleaseProjection(scope, custody, frozen)
	if err != nil {
		return empty, ErrSchemaWikiPreparationInvalid
	}
	projected := schemaWikiReleaseSnapshots(release)
	for index := range projected {
		projected[index].Title = frozen[index].Title
		projected[index].Content = string(projected[index].Payload)
	}
	return validatedSchemaWikiCustody{
		release: release, snapshots: projected, storedSnapshots: frozen, isolatedC6: true,
		experimentID: custody.ExperimentID, versionIdentity: custody.VersionIdentity,
		revisionSetSHA256: custody.RevisionSetSHA256,
		candidateEvidenceAuthority: func() types.Schema67CandidateEvidenceAuthorityV1 {
			if custody.CandidateEvidenceAuthority == nil {
				return types.Schema67CandidateEvidenceAuthorityV1{}
			}
			return *custody.CandidateEvidenceAuthority
		}(),
	}, nil
}

func schemaWikiC6ReleaseProjection(
	scope types.WikiReleaseScope,
	custody schemaWikiC6IsolatedCustodyV1,
	members []types.WikiReleaseMemberSnapshot,
) (types.KnowledgeWikiReleaseV1, error) {
	const (
		medicalDomainID       = "medical-insurance"
		medicalDomainSHA256   = "6b2305a05875d8634a78530cb5de7fe6240d8369a55c641381d1e800cd144dce"
		medicalSchemaSHA256   = "fe3b390222108614d3ff07409fbd81d17e915e066eb9c25c03d3268bc49ef7ac"
		medicalTaxonomySHA256 = "f9e4e271c412d7beb032191a7211d8e752179349e4e3db2d59d6336f7a27efce"
	)
	release := types.KnowledgeWikiReleaseV1{
		Contract:           "knowledge-wiki-release.v1",
		ReleaseState:       "draft",
		CandidateSHA256:    custody.CandidateSHA256,
		ReviewPolicySHA256: custody.ReviewPolicySHA256,
		ReleaseSHA256:      custody.VersionIdentity,
		Members:            make([]types.SchemaWikiMemberV1, len(members)),
	}
	type sourceSelection struct {
		SelectionID         string     `json:"selection_id"`
		FieldID             string     `json:"field_id"`
		SourceRole          string     `json:"source_role"`
		SourceRevisionID    string     `json:"source_revision_id"`
		OriginalFileSHA256  string     `json:"original_file_sha256"`
		ParseManifestSHA256 string     `json:"parse_manifest_sha256"`
		PageNumber          uint64     `json:"page_number"`
		CoordinateSpace     string     `json:"coordinate_space"`
		PageWidthPoints     string     `json:"page_width_points"`
		PageHeightPoints    string     `json:"page_height_points"`
		BBox                []string   `json:"bbox"`
		Rects               [][]string `json:"rects"`
		BlockID             *string    `json:"block_id"`
		SpanID              *string    `json:"span_id"`
		TableID             *string    `json:"table_id"`
		TableSliceID        *string    `json:"table_slice_id"`
		CellIDs             []string   `json:"cell_ids"`
		Quote               string     `json:"quote"`
		QuoteSHA256         string     `json:"quote_sha256"`
		PageTextCharStart   *uint64    `json:"page_text_char_start"`
		PageTextCharEnd     *uint64    `json:"page_text_char_end"`
	}
	type fieldBody struct {
		SchemaOrder      uint64            `json:"schema_order"`
		SectionID        string            `json:"section_id"`
		FieldID          string            `json:"field_id"`
		DisplayName      string            `json:"display_name"`
		State            string            `json:"state"`
		ValueSnapshot    *string           `json:"value_snapshot"`
		TypedReason      *string           `json:"typed_reason"`
		SourceSelections []sourceSelection `json:"source_selections"`
	}
	sections := make([]types.SchemaSectionV1, 0, 7)
	fields := make([]fieldBody, 0, 67)
	orderedFieldIDs := make([]string, 0, 67)
	fieldSections := make(map[string]string, 67)
	var product struct {
		EntityID         string `json:"entity_id"`
		EntityVersionID  string `json:"entity_version_id"`
		ProductVersionID string `json:"product_version_id"`
		DisplayName      string `json:"display_name"`
	}
	for _, member := range members {
		var envelope map[string]json.RawMessage
		if json.Unmarshal(member.Payload, &envelope) != nil || len(envelope) != 10 {
			return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
		}
		body, ok := envelope["body"]
		if !ok || len(body) == 0 {
			return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
		}
		switch member.Kind {
		case "root":
			if json.Unmarshal(body, &product) != nil {
				return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
			}
		case "section":
			var section types.SchemaSectionV1
			if json.Unmarshal(body, &section) != nil {
				return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
			}
			sections = append(sections, section)
			for _, fieldID := range section.OrderedFieldIDs {
				if _, exists := fieldSections[fieldID]; exists {
					return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
				}
				fieldSections[fieldID] = section.SectionID
			}
		case "field":
			var field fieldBody
			if json.Unmarshal(body, &field) != nil || field.SchemaOrder != uint64(len(orderedFieldIDs)+1) ||
				fieldSections[field.FieldID] != field.SectionID {
				return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
			}
			orderedFieldIDs = append(orderedFieldIDs, field.FieldID)
			fields = append(fields, field)
		default:
			return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
		}
	}
	if product.EntityID != "ping-an-e-sheng-bao" ||
		product.EntityVersionID != "ping-an-e-sheng-bao@596-1" ||
		product.ProductVersionID != "596-1" || product.DisplayName == "" {
		return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
	}
	release.Domain = types.KnowledgeDomainV1{
		Contract: "knowledge-domain.v1", DomainID: medicalDomainID,
		DisplayName: "医疗险", DomainSHA256: medicalDomainSHA256,
	}
	stableEntityID := product.EntityID
	parentNodeID := "medical-products"
	release.Taxonomy = types.TaxonomySnapshotV1{
		Contract: "taxonomy-snapshot.v1", DomainID: medicalDomainID,
		TaxonomyVersion: "medical-insurance-taxonomy.v1",
		Nodes: []types.TaxonomyNodeV1{
			{NodeID: parentNodeID, NodeKind: "category", Slug: parentNodeID, Position: 0},
			{NodeID: product.EntityID, ParentNodeID: &parentNodeID, NodeKind: "entity",
				Slug: product.EntityID, StableEntityID: &stableEntityID, Position: 0},
		},
		Redirects: []types.TaxonomyRedirectV1{}, TaxonomySHA256: medicalTaxonomySHA256,
	}
	release.SchemaPack = types.SchemaPackV1{
		Contract: "schema-pack.v1", SchemaPackID: "medical-schema67.v1",
		SchemaVersion: "v1", DomainID: medicalDomainID,
		OrderedFieldIDs: orderedFieldIDs, Sections: sections, SchemaPackSHA256: medicalSchemaSHA256,
	}
	if types.ValidateSchemaPack(release.SchemaPack) != nil {
		return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
	}
	release.Entity = types.EntityIdentityV1{DomainID: medicalDomainID, EntityID: product.EntityID}
	release.EntityVersion = types.EntityVersionV1{
		EntityID: product.EntityID, VersionID: product.EntityVersionID,
		ProductVersionID: product.ProductVersionID,
	}
	hash := func(objectType string, value any, omitted string) (string, error) {
		raw, err := json.Marshal(value)
		if err != nil {
			return "", err
		}
		decoder := json.NewDecoder(bytes.NewReader(raw))
		decoder.UseNumber()
		var payload map[string]any
		if decoder.Decode(&payload) != nil {
			return "", ErrSchemaWikiPreparationInvalid
		}
		if omitted != "" {
			delete(payload, omitted)
		}
		var canonical bytes.Buffer
		encoder := json.NewEncoder(&canonical)
		encoder.SetEscapeHTML(false)
		if encoder.Encode(payload) != nil {
			return "", ErrSchemaWikiPreparationInvalid
		}
		preimage := append(
			[]byte("schema-wiki-canonical.v1\x00"+objectType+"\x00"),
			bytes.TrimSuffix(canonical.Bytes(), []byte("\n"))...,
		)
		sum := sha256.Sum256(preimage)
		return hex.EncodeToString(sum[:]), nil
	}
	projectMember := func(
		index int, memberKind string, sectionID *string, fieldID *string,
		page any, pageHash string,
	) error {
		payload, err := json.Marshal(page)
		if err != nil {
			return err
		}
		canonical, err := types.CanonicalSchemaWikiMemberPayload(memberKind, payload)
		if err != nil {
			return err
		}
		projected := types.SchemaWikiMemberV1{
			Contract: "schema-wiki-member.v1", MemberRef: members[index].LogicalSlug,
			MemberKind: memberKind, SectionID: sectionID, FieldID: fieldID,
			Payload: canonical, PayloadSHA256: pageHash,
		}
		projected.MemberDigest, err = hash(projected.Contract, projected, "member_digest")
		if err != nil {
			return err
		}
		release.Members[index] = projected
		return nil
	}
	orderedSectionIDs := make([]string, len(sections))
	for index := range sections {
		orderedSectionIDs[index] = sections[index].SectionID
	}
	root := types.SchemaRootPageV1{
		Contract: "schema-root-page.v1", DomainID: release.Domain.DomainID,
		DomainSHA256: release.Domain.DomainSHA256, SchemaPackID: release.SchemaPack.SchemaPackID,
		SchemaVersion:    release.SchemaPack.SchemaVersion,
		SchemaPackSHA256: release.SchemaPack.SchemaPackSHA256,
		EntityID:         release.Entity.EntityID, EntityVersionID: release.EntityVersion.VersionID,
		ProductVersionID:   release.EntityVersion.ProductVersionID,
		TaxonomyVersion:    release.Taxonomy.TaxonomyVersion,
		TaxonomySHA256:     release.Taxonomy.TaxonomySHA256,
		ProductDisplayName: product.DisplayName, OrderedSectionIDs: orderedSectionIDs,
	}
	var err error
	root.RootPageSHA256, err = hash(root.Contract, root, "root_page_sha256")
	if err != nil || projectMember(0, "root", nil, nil, root, root.RootPageSHA256) != nil {
		return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
	}
	for index, section := range sections {
		page := types.SchemaSectionPageV1{
			Contract: "schema-section-page.v1", DomainID: release.Domain.DomainID,
			DomainSHA256: release.Domain.DomainSHA256, SchemaPackID: release.SchemaPack.SchemaPackID,
			SchemaVersion:    release.SchemaPack.SchemaVersion,
			SchemaPackSHA256: release.SchemaPack.SchemaPackSHA256,
			EntityID:         release.Entity.EntityID, EntityVersionID: release.EntityVersion.VersionID,
			ProductVersionID: release.EntityVersion.ProductVersionID,
			TaxonomyVersion:  release.Taxonomy.TaxonomyVersion,
			TaxonomySHA256:   release.Taxonomy.TaxonomySHA256,
			SectionID:        section.SectionID, DisplayName: section.DisplayName,
			OrderedFieldIDs: append([]string(nil), section.OrderedFieldIDs...),
		}
		page.SectionPageSHA256, err = hash(page.Contract, page, "section_page_sha256")
		sectionID := section.SectionID
		if err != nil || projectMember(
			index+1, "section", &sectionID, nil, page, page.SectionPageSHA256,
		) != nil {
			return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
		}
	}
	normalizedCoordinate := func(value, dimension string) (int, bool) {
		coordinate, coordinateOK := new(big.Rat).SetString(value)
		maximum, maximumOK := new(big.Rat).SetString(dimension)
		if !coordinateOK || !maximumOK || coordinate.Sign() < 0 || maximum.Sign() <= 0 ||
			coordinate.Cmp(maximum) > 0 {
			return 0, false
		}
		scaled := new(big.Rat).Mul(coordinate, big.NewRat(1_000_000, 1))
		scaled.Quo(scaled, maximum)
		quotient, remainder := new(big.Int), new(big.Int)
		quotient.QuoRem(scaled.Num(), scaled.Denom(), remainder)
		if new(big.Int).Lsh(remainder, 1).Cmp(scaled.Denom()) >= 0 {
			quotient.Add(quotient, big.NewInt(1))
		}
		if !quotient.IsInt64() || quotient.Int64() > 1_000_000 {
			return 0, false
		}
		return int(quotient.Int64()), true
	}
	authorityReceiptsByField := make(map[string][]types.Schema67CitationAuthorityJoinReceiptV1)
	if custody.CandidateEvidenceAuthority != nil {
		authority := custody.CandidateEvidenceAuthority
		digest, digestErr := types.ComputeSchema67CandidateEvidenceAuthoritySHA256(*authority)
		if digestErr != nil || digest != authority.AuthoritySHA256 ||
			authority.CandidateSHA256 != custody.CandidateSHA256 {
			return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
		}
		for _, source := range authority.SourceAuthorities {
			live := source.LiveRevisionSourceReceipt
			if live.TenantID != scope.TenantID || live.SpaceID != scope.SpaceID ||
				live.RawKBID != scope.RawKBID || live.WikiKBID != scope.WikiKBID {
				return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
			}
		}
		for _, receipt := range authority.JoinReceipts {
			authorityReceiptsByField[receipt.FieldID] = append(
				authorityReceiptsByField[receipt.FieldID], receipt,
			)
		}
	}
	authorityFieldEvidence := func(
		field fieldBody,
		logicalMemberRef string,
	) ([]types.CitationTargetV1, []string, error) {
		receipts := authorityReceiptsByField[field.FieldID]
		if len(receipts) == 0 {
			return nil, nil, ErrSchemaWikiPreparationInvalid
		}
		citations := make([]types.CitationTargetV1, 0, len(receipts))
		evidenceReceipts := make([]string, 0, len(receipts))
		usedSelections := make(map[int]struct{}, len(field.SourceSelections))
		for _, receipt := range receipts {
			matchingIndex := -1
			matchingQuote := ""
			for selectionIndex, selection := range field.SourceSelections {
				quoteSHA256, quoteErr := hash(
					"schema-wiki-text.v1", map[string]any{"text": selection.Quote}, "",
				)
				locatorMatches := selection.SelectionID == receipt.LocatorRef ||
					(selection.BlockID != nil && *selection.BlockID == receipt.LocatorRef) ||
					(selection.SpanID != nil && *selection.SpanID == receipt.LocatorRef) ||
					(selection.TableID != nil && *selection.TableID == receipt.LocatorRef) ||
					(selection.TableSliceID != nil && *selection.TableSliceID == receipt.LocatorRef)
				if !locatorMatches {
					for _, cellID := range selection.CellIDs {
						if cellID == receipt.LocatorRef {
							locatorMatches = true
							break
						}
					}
				}
				if quoteErr == nil && locatorMatches && selection.FieldID == receipt.FieldID &&
					selection.SourceRole == receipt.SourceRole &&
					selection.OriginalFileSHA256 == receipt.FileSHA256 &&
					selection.ParseManifestSHA256 == receipt.RawStructureSHA256 &&
					int(selection.PageNumber) == receipt.PageNumber && quoteSHA256 == receipt.QuoteSHA256 {
					if matchingIndex >= 0 {
						return nil, nil, ErrSchemaWikiPreparationInvalid
					}
					matchingIndex, matchingQuote = selectionIndex, selection.Quote
				}
			}
			if matchingIndex < 0 {
				return nil, nil, ErrSchemaWikiPreparationInvalid
			}
			usedSelections[matchingIndex] = struct{}{}
			citation := types.CitationTargetV1{
				Contract: "citation-target.v1", CitationID: "citation-" + receipt.ReceiptSHA256[:24],
				SourceRole: receipt.SourceRole, SpaceID: receipt.SpaceID,
				EntityVersionID: release.EntityVersion.VersionID,
				KnowledgeID:     receipt.KnowledgeID, ChunkID: receipt.ChunkID,
				SourceRevisionID:     receipt.LiveRevisionSourceReceipt.RevisionSourceID,
				ParseAttemptID:       receipt.EvidenceParseAttemptID,
				ParsedDocumentSHA256: receipt.ParsedDocumentSHA256,
				ParseManifestSHA256:  receipt.ParseManifestSHA256,
				PageNumber:           receipt.PageNumber, LocatorRef: receipt.LocatorRef,
				BBox: receipt.NormalizedBBox, QuoteSnapshot: matchingQuote,
				QuoteSHA256:           receipt.QuoteSHA256,
				ContentSnapshotSHA256: receipt.LocatorContentSHA256,
				LogicalMemberRef:      logicalMemberRef,
			}
			var citationErr error
			citation.CitationSHA256, citationErr = hash(
				citation.Contract, citation, "citation_sha256",
			)
			if citationErr != nil || types.ValidateCitationTarget(citation) != nil {
				return nil, nil, ErrSchemaWikiPreparationInvalid
			}
			citations = append(citations, citation)
			if len(evidenceReceipts) == 0 ||
				evidenceReceipts[len(evidenceReceipts)-1] != receipt.EvidenceReceiptSHA256 {
				evidenceReceipts = append(evidenceReceipts, receipt.EvidenceReceiptSHA256)
			}
		}
		if len(usedSelections) != len(field.SourceSelections) {
			return nil, nil, ErrSchemaWikiPreparationInvalid
		}
		return citations, evidenceReceipts, nil
	}
	for index, field := range fields {
		page := types.SchemaFieldPageV1{
			Contract: "schema-field-page.v1", FieldID: field.FieldID,
			Citations: []types.CitationTargetV1{}, EvidenceReceiptSHA256s: []string{},
		}
		switch field.State {
		case "present", "absent":
			if field.ValueSnapshot == nil || *field.ValueSnapshot == "" || field.TypedReason != nil ||
				len(field.SourceSelections) == 0 {
				return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
			}
			page.State = field.State
			if page.State == "absent" {
				page.State = "absent_explicitly"
			}
			value := *field.ValueSnapshot
			page.ValueSnapshot = &value
			if custody.CandidateEvidenceAuthority != nil {
				page.Citations, page.EvidenceReceiptSHA256s, err = authorityFieldEvidence(
					field, members[index+8].LogicalSlug,
				)
				if err != nil {
					return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
				}
			} else {
				for _, selection := range field.SourceSelections {
					if selection.FieldID != field.FieldID || selection.SelectionID == "" ||
						selection.SourceRole == "" || !validServiceSHA256(selection.SourceRevisionID) ||
						!validServiceSHA256(selection.OriginalFileSHA256) ||
						!validServiceSHA256(selection.ParseManifestSHA256) ||
						selection.PageNumber == 0 || selection.CoordinateSpace != "PDF_POINTS_TOP_LEFT_V1" ||
						len(selection.BBox) != 4 || selection.Quote == "" ||
						selection.QuoteSHA256 != digestWikiReleaseBytes([]byte(selection.Quote)) {
						return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
					}
					coordinates := [4]int{}
					validCoordinates := true
					for coordinateIndex := range coordinates {
						dimension := selection.PageWidthPoints
						if coordinateIndex%2 == 1 {
							dimension = selection.PageHeightPoints
						}
						coordinates[coordinateIndex], validCoordinates = normalizedCoordinate(
							selection.BBox[coordinateIndex], dimension,
						)
						if !validCoordinates {
							break
						}
					}
					if !validCoordinates {
						return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
					}
					quoteHash, quoteErr := hash(
						"schema-wiki-text.v1", map[string]any{"text": selection.Quote}, "",
					)
					citation := types.CitationTargetV1{
						Contract: "citation-target.v1", CitationID: selection.SelectionID,
						SourceRole: selection.SourceRole, SpaceID: scope.SpaceID,
						EntityVersionID: release.EntityVersion.VersionID,
						KnowledgeID:     selection.OriginalFileSHA256, ChunkID: selection.SelectionID,
						SourceRevisionID:     selection.SourceRevisionID,
						ParseAttemptID:       selection.ParseManifestSHA256,
						ParsedDocumentSHA256: selection.SourceRevisionID,
						ParseManifestSHA256:  selection.ParseManifestSHA256,
						PageNumber:           int(selection.PageNumber), LocatorRef: selection.SelectionID,
						BBox: types.CitationBBoxV1{
							CoordinateSystem: "normalized_0_1e6", PageWidth: 1_000_000,
							PageHeight: 1_000_000, X0: coordinates[0], Y0: coordinates[1],
							X1: coordinates[2], Y1: coordinates[3],
						},
						QuoteSnapshot: selection.Quote, QuoteSHA256: quoteHash,
						ContentSnapshotSHA256: selection.QuoteSHA256,
						LogicalMemberRef:      members[index+8].LogicalSlug,
					}
					citation.CitationSHA256, err = hash(
						citation.Contract, citation, "citation_sha256",
					)
					if quoteErr != nil || err != nil || types.ValidateCitationTarget(citation) != nil {
						return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
					}
					page.Citations = append(page.Citations, citation)
					page.EvidenceReceiptSHA256s = append(
						page.EvidenceReceiptSHA256s, citation.CitationSHA256,
					)
				}
			}
		case "unknown":
			if field.ValueSnapshot != nil || field.TypedReason == nil || *field.TypedReason == "" ||
				len(field.SourceSelections) != 0 {
				return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
			}
			page.State = "unknown"
			reviewReason := "FIELD_UNKNOWN"
			unknownReason := types.SchemaFieldUnknownReasonFieldUnknown
			if *field.TypedReason == "SOURCE_GUIDANCE_ROLE_INTERSECTION_EMPTY" {
				unknownReason = types.SchemaFieldUnknownReasonNotCoveredByCurrentSourceMaterials
			}
			page.ReviewItemReason = &reviewReason
			page.UnknownReason = &unknownReason
		default:
			return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
		}
		page.FieldPageSHA256, err = hash(page.Contract, page, "field_page_sha256")
		sectionID, fieldID := field.SectionID, field.FieldID
		if err != nil || projectMember(
			index+8, "field", &sectionID, &fieldID, page, page.FieldPageSHA256,
		) != nil {
			return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
		}
	}
	for _, member := range release.Members {
		if member.MemberKind != "field" {
			continue
		}
		var page types.SchemaFieldPageV1
		if json.Unmarshal(member.Payload, &page) != nil {
			return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
		}
		for _, citation := range page.Citations {
			binding := types.CitationMemberBindingV1{
				Contract: "citation-member-binding.v1", CitationSHA256: citation.CitationSHA256,
				LogicalMemberRef: member.MemberRef, MemberDigest: member.MemberDigest,
			}
			binding.BindingSHA256, err = hash(binding.Contract, binding, "binding_sha256")
			if err != nil {
				return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
			}
			release.CitationBindings = append(release.CitationBindings, binding)
		}
	}
	sort.Slice(release.CitationBindings, func(left, right int) bool {
		if release.CitationBindings[left].LogicalMemberRef != release.CitationBindings[right].LogicalMemberRef {
			return release.CitationBindings[left].LogicalMemberRef < release.CitationBindings[right].LogicalMemberRef
		}
		return release.CitationBindings[left].CitationSHA256 < release.CitationBindings[right].CitationSHA256
	})
	release.ManifestDigest, err = hash(
		"schema-wiki-manifest.v1",
		map[string]any{"members": release.Members, "citation_bindings": release.CitationBindings}, "",
	)
	if err != nil {
		return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
	}
	release.ReleaseSHA256, err = hash(release.Contract, release, "release_sha256")
	if err != nil {
		return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
	}
	if custody.CandidateEvidenceAuthority != nil &&
		types.ValidateSchema67CandidateEvidenceAuthorityV1(
			*custody.CandidateEvidenceAuthority, release,
		) != nil {
		return types.KnowledgeWikiReleaseV1{}, ErrSchemaWikiPreparationInvalid
	}
	return release, nil
}

func canonicalSchemaWikiC6StoredManifest(
	raw json.RawMessage,
) (schemaWikiC6IsolatedCustodyV1, json.RawMessage, error) {
	var custody schemaWikiC6IsolatedCustodyV1
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&custody); err != nil {
		return custody, nil, ErrSchemaWikiPreparationInvalid
	}
	var trailing any
	if !errors.Is(decoder.Decode(&trailing), io.EOF) ||
		custody.Contract != "schema-wiki-isolated-r1-custody.815.v1" {
		return custody, nil, ErrSchemaWikiPreparationInvalid
	}
	var ok bool
	custody.OrderedMembers, ok = restoreSchemaWikiC6JSONBMemberPayloads(custody.OrderedMembers)
	if !ok {
		return custody, nil, ErrSchemaWikiPreparationInvalid
	}
	canonical, err := json.Marshal(custody)
	if err != nil {
		return custody, nil, ErrSchemaWikiPreparationInvalid
	}
	return custody, canonical, nil
}

func restoreSchemaWikiC6JSONBMemberPayloads(
	members []types.WikiReleaseMemberSnapshot,
) ([]types.WikiReleaseMemberSnapshot, bool) {
	restored := append([]types.WikiReleaseMemberSnapshot(nil), members...)
	for index := range restored {
		member := &restored[index]
		var storedValue any
		var frozenValue any
		if json.Unmarshal(member.Payload, &storedValue) != nil ||
			json.Unmarshal([]byte(member.Content), &frozenValue) != nil ||
			!reflect.DeepEqual(storedValue, frozenValue) {
			return nil, false
		}
		member.Payload = json.RawMessage(append([]byte(nil), member.Content...))
	}
	return restored, true
}

func schemaWikiC6StoredManifestDigest(raw json.RawMessage) (string, bool) {
	_, canonical, err := canonicalSchemaWikiC6StoredManifest(raw)
	if err != nil {
		return "", false
	}
	return digestWikiReleaseBytes(canonical), true
}

func isSchemaWikiC6StoredManifest(raw json.RawMessage) bool {
	var header struct {
		Contract string `json:"contract"`
	}
	return json.Unmarshal(raw, &header) == nil &&
		header.Contract == "schema-wiki-isolated-r1-custody.815.v1"
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
	for _, member := range validated.snapshots {
		if member.LogicalSlug == logicalSlug {
			return true
		}
	}
	if validated.isolatedC6 {
		return false
	}
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
	request, err = s.bindSchemaWikiC6FrozenNativeSource(validated, request)
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
		goldenAuthority, goldenErr := s.citationContent.ResolvePreparationOpaqueToken(
			ctx, scope, token,
		)
		if goldenErr != nil || goldenAuthority == nil {
			return nil, ErrSchemaWikiCitationUnavailable
		}
		if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
			return nil, err
		}
		_, validated, loadErr := s.loadSchemaPreparationGoldenEvaluation(
			ctx,
			principal,
			scope,
			goldenAuthority.PreparationID,
			goldenAuthority.EvaluationID,
			"read-golden-evidence-content",
		)
		if loadErr != nil {
			return nil, loadErr
		}
		request, requestErr := schemaWikiPreparationCitationRequest(
			validated,
			scope,
			goldenAuthority.PreparationID,
			goldenAuthority.EvaluationID,
			goldenAuthority.EvidenceID,
			"field:"+goldenAuthority.FieldID,
			"citation-"+goldenAuthority.EvidenceID[:24],
		)
		if requestErr != nil {
			return nil, requestErr
		}
		opened, readErr := s.citationContent.ReadPreparationByOpaqueToken(
			ctx,
			scope,
			token,
			goldenAuthority.PreparationID,
			goldenAuthority.EvaluationID,
			goldenAuthority.EvidenceID,
			request,
		)
		if readErr != nil {
			return nil, readErr
		}
		return opened, nil
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
	request, err = s.bindSchemaWikiC6FrozenNativeSource(validated, request)
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
	request, err = s.bindSchemaWikiC6FrozenNativeSource(validated, request)
	if err != nil {
		return nil, err
	}
	opened, err := s.citationPort.ReadExactRevision(ctx, request)
	if err != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	return opened, nil
}

func (s *SchemaWikiService) bindSchemaWikiC6FrozenNativeSource(
	validated validatedSchemaWikiCustody,
	request CitationRevisionReadRequestV1,
) (CitationRevisionReadRequestV1, error) {
	if !validated.isolatedC6 {
		return request, nil
	}
	reader, ok := s.formalCandidatePreview.(schemaWikiFormalCandidateNativeSourceReader)
	if !ok || validated.experimentID == "" ||
		!validServiceSHA256(validated.versionIdentity) ||
		!validServiceSHA256(validated.revisionSetSHA256) ||
		request.Scope.TenantID == 0 || request.Scope.RawKBID == "" ||
		request.Citation.SourceRole == "" || request.CoordinateAuthorityReceipt == nil ||
		request.CoordinateAuthorityReceipt.SourceRole != request.Citation.SourceRole {
		return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
	}
	key := wikirepository.SchemaWikiFormalCandidatePreviewKey{
		KBID: request.Scope.RawKBID, ExperimentID: validated.experimentID,
		VersionIdentity: validated.versionIdentity,
	}
	record, err := s.formalCandidatePreview.ReadExact(request.Scope.TenantID, key)
	if err != nil || record.ExperimentID != validated.experimentID ||
		record.ManifestSHA256 != validated.versionIdentity ||
		record.RevisionSetSHA256 != validated.revisionSetSHA256 ||
		record.CandidateSHA256 != request.CandidateSHA256 {
		return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
	}
	manifest, source, err := reader.ReadNativeSourceExact(
		request.Scope.TenantID, key, request.Citation.SourceRole,
	)
	if err != nil || len(manifest) == 0 || len(source) == 0 {
		return CitationRevisionReadRequestV1{}, ErrSchemaWikiCitationUnavailable
	}
	request.frozenNativeSource = &schemaWikiC5FrozenNativeSource{
		experimentID: validated.experimentID, versionIdentity: validated.versionIdentity,
		revisionSetSHA256: validated.revisionSetSHA256,
		sourceRole:        request.Citation.SourceRole,
		manifest:          append([]byte(nil), manifest...), sourceBytes: append([]byte(nil), source...),
	}
	return request, nil
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

func schemaWikiPreparationCitationRequest(
	validated validatedSchemaWikiCustody,
	scope types.WikiReleaseScope,
	preparationID string,
	evaluationID string,
	evidenceID string,
	logicalSlug string,
	citationID string,
) (CitationRevisionReadRequestV1, error) {
	if preparationID == "" || !validServiceSHA256(evaluationID) ||
		!validServiceSHA256(evidenceID) || logicalSlug == "" || citationID == "" {
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
		if binding.LogicalMemberRef != logicalSlug ||
			binding.CitationSHA256 != selected.CitationSHA256 {
			continue
		}
		for index := range validated.candidateEvidenceAuthority.JoinReceipts {
			join := &validated.candidateEvidenceAuthority.JoinReceipts[index]
			if join.ReceiptSHA256 == evidenceID && join.FieldID == fieldID &&
				selected.CitationID == "citation-"+join.ReceiptSHA256[:24] {
				copy := *join
				return CitationRevisionReadRequestV1{
					PreparationID:              preparationID,
					EvaluationID:               evaluationID,
					EvidenceID:                 evidenceID,
					CandidateSHA256:            validated.release.CandidateSHA256,
					FieldID:                    fieldID,
					Scope:                      scope,
					Citation:                   *selected,
					Binding:                    binding,
					EvidenceReceiptSHA256s:     evidenceReceipts,
					CoordinateAuthorityReceipt: &copy,
				}, nil
			}
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
