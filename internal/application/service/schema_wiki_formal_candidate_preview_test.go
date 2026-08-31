package service

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"sort"
	"strings"
	"testing"
	"time"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

type schemaWikiFormalCandidatePreviewReaderStub struct {
	record                 wikirepository.SchemaWikiFormalCandidatePreviewRecord
	content                wikirepository.SchemaWikiFormalCandidatePreviewContent
	releaseMembers         []types.WikiReleaseMemberSnapshot
	evidenceAuthority      types.Schema67CandidateEvidenceAuthorityV1
	readErr                error
	contentErr             error
	releaseMembersErr      error
	evidenceAuthorityErr   error
	readCalls              int
	contentCalls           int
	releaseMemberCalls     int
	evidenceAuthorityCalls int
	nativeSourceCalls      int
	nativeSourceManifest   []byte
	nativeSourcePDF        []byte
}

func (s *schemaWikiFormalCandidatePreviewReaderStub) ReadNativeSourceExact(
	_ uint64,
	_ wikirepository.SchemaWikiFormalCandidatePreviewKey,
	_ string,
) ([]byte, []byte, error) {
	s.nativeSourceCalls++
	return append([]byte(nil), s.nativeSourceManifest...),
		append([]byte(nil), s.nativeSourcePDF...), nil
}

func (s *schemaWikiFormalCandidatePreviewReaderStub) ReadCandidateEvidenceAuthorityExact(
	_ uint64,
	_ wikirepository.SchemaWikiFormalCandidatePreviewKey,
) (types.Schema67CandidateEvidenceAuthorityV1, error) {
	s.evidenceAuthorityCalls++
	return s.evidenceAuthority, s.evidenceAuthorityErr
}

func (s *schemaWikiFormalCandidatePreviewReaderStub) ReadReleaseMembersExact(
	_ uint64,
	_ wikirepository.SchemaWikiFormalCandidatePreviewKey,
) ([]types.WikiReleaseMemberSnapshot, error) {
	s.releaseMemberCalls++
	return append([]types.WikiReleaseMemberSnapshot(nil), s.releaseMembers...), s.releaseMembersErr
}

func (s *schemaWikiFormalCandidatePreviewReaderStub) ReadExact(
	_ uint64,
	_ wikirepository.SchemaWikiFormalCandidatePreviewKey,
) (wikirepository.SchemaWikiFormalCandidatePreviewRecord, error) {
	s.readCalls++
	return s.record, s.readErr
}

func (s *schemaWikiFormalCandidatePreviewReaderStub) ReadContentExact(
	_ uint64,
	_ wikirepository.SchemaWikiFormalCandidatePreviewKey,
	_ wikirepository.SchemaWikiFormalCandidatePreviewContentRequest,
) (wikirepository.SchemaWikiFormalCandidatePreviewContent, error) {
	s.contentCalls++
	return s.content, s.contentErr
}

func schemaWikiFormalCandidatePreviewServiceFixture() (*schemaWikiFormalCandidatePreviewReaderStub, wikirepository.SchemaWikiFormalCandidatePreviewKey) {
	key := wikirepository.SchemaWikiFormalCandidatePreviewKey{
		KBID:            "b1f1764c-443d-46b8-98e3-d5aa5e55eb42",
		ExperimentID:    "2a92f197-4b33-41de-a6af-c60252d6347d",
		VersionIdentity: strings.Repeat("a", 64),
	}
	preview := json.RawMessage(`{"contract":"schema-wiki-formal-candidate-preview.815.v1","preview_sha256":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"}`)
	contentBytes := []byte("%PDF-1.7 exact")
	contentSum := sha256.Sum256(contentBytes)
	return &schemaWikiFormalCandidatePreviewReaderStub{
		record: wikirepository.SchemaWikiFormalCandidatePreviewRecord{
			TenantID: 10003, KBID: key.KBID, ExperimentID: key.ExperimentID,
			ManifestSHA256: key.VersionIdentity, CandidateSHA256: strings.Repeat("b", 64),
			CompanionSHA256: strings.Repeat("c", 64), TerminalSHA256: strings.Repeat("d", 64),
			RevisionSetSHA256: strings.Repeat("e", 64), PreviewSHA256: strings.Repeat("f", 64),
			Preview: preview,
		},
		content: wikirepository.SchemaWikiFormalCandidatePreviewContent{
			Bytes: contentBytes, OriginalFileSHA256: hex.EncodeToString(contentSum[:]),
		},
	}, key
}

func TestSchemaWikiFormalCandidatePreviewServiceReturnsClosedResponseHash(t *testing.T) {
	reader, key := schemaWikiFormalCandidatePreviewServiceFixture()
	service := NewSchemaWikiServiceWithFormalCandidatePreview(reader)
	response, err := service.ReadSchemaWikiFormalCandidatePreview(context.Background(), 10003, key)
	require.NoError(t, err)
	require.Equal(t, "schema-wiki-formal-candidate-preview-response.815.v1", response.Contract)
	require.Equal(t, response.VersionIdentity, response.ManifestSHA256)
	require.Equal(t, reader.record.PreviewSHA256, response.PreviewSHA256)
	require.Equal(t, reader.record.Preview, response.Preview)
	require.Equal(t, 1, reader.readCalls)

	raw, err := json.Marshal(response)
	require.NoError(t, err)
	var decoded map[string]any
	require.NoError(t, json.Unmarshal(raw, &decoded))
	require.Len(t, decoded, 13)
	got := decoded["response_sha256"]
	delete(decoded, "response_sha256")
	canonical, err := json.Marshal(decoded)
	require.NoError(t, err)
	preimage := append([]byte("weknora.schema-wiki-c5.815.v1\x00schema-wiki-formal-candidate-preview-response.815.v1\x00"), canonical...)
	sum := sha256.Sum256(preimage)
	require.Equal(t, hex.EncodeToString(sum[:]), got)
}

func TestSchemaWikiFormalCandidatePreviewServiceRejectsTupleDriftBeforeOutput(t *testing.T) {
	reader, key := schemaWikiFormalCandidatePreviewServiceFixture()
	reader.record.CandidateSHA256 = "not-a-sha"
	service := NewSchemaWikiServiceWithFormalCandidatePreview(reader)
	response, err := service.ReadSchemaWikiFormalCandidatePreview(context.Background(), 10003, key)
	require.ErrorIs(t, err, ErrSchemaWikiFormalCandidatePreviewBindingMismatch)
	require.Nil(t, response)
}

func TestSchemaWikiFormalCandidatePreviewServiceReadsOnlyExactSelectionBytes(t *testing.T) {
	reader, key := schemaWikiFormalCandidatePreviewServiceFixture()
	service := NewSchemaWikiServiceWithFormalCandidatePreview(reader)
	request := wikirepository.SchemaWikiFormalCandidatePreviewContentRequest{
		FieldID: "field-01", SelectionID: "selection-01",
	}
	content, err := service.ReadSchemaWikiFormalCandidatePreviewContent(
		context.Background(), 10003, key, request,
	)
	require.NoError(t, err)
	require.Equal(t, reader.content.Bytes, content)
	require.Equal(t, 1, reader.contentCalls)
	content[0] = 'X'
	require.Equal(t, byte('%'), reader.content.Bytes[0])
}

var schemaWikiC6DecisionSeed = sha256.Sum256([]byte("schema-wiki-c6-decision-test-key.v1"))
var schemaWikiC6AuthorizationSeed = sha256.Sum256([]byte("schema-wiki-c6-authorization-test-key.v1"))

type schemaWikiC6DecisionFixture struct {
	service                 *SchemaWikiService
	authority               *WikiReleaseService
	repository              *wikirepository.WikiReleaseRepository
	db                      *gorm.DB
	reader                  *schemaWikiFormalCandidatePreviewReaderStub
	key                     wikirepository.SchemaWikiFormalCandidatePreviewKey
	principal               types.WikiReleasePrincipal
	scope                   types.WikiReleaseScope
	ctx                     context.Context
	now                     time.Time
	privateKey              ed25519.PrivateKey
	authorizationPrivateKey ed25519.PrivateKey
}

type schemaWikiC6CitationContentSpy struct {
	schemaWikiGoldenEvidenceContentSpy
	issueCurrentCalls int
	request           CitationRevisionReadRequestV1
}

func (s *schemaWikiC6CitationContentSpy) IssueExactRevision(
	_ context.Context,
	request CitationRevisionReadRequestV1,
) (*types.SchemaWikiCitationContentAuthorityV1, error) {
	s.issueCurrentCalls++
	s.request = request
	receipt := request.CoordinateAuthorityReceipt
	if receipt == nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	authority := &types.SchemaWikiCitationContentAuthorityV1{
		Contract: "schema-wiki-citation-content-authority.v1", TokenKeyID: "c6-citation-test-key",
		ReleaseID: request.ReleaseID, ActivationEpoch: request.ActivationEpoch,
		CandidateSHA256: request.CandidateSHA256, FieldID: request.FieldID,
		CitationID: request.Citation.CitationID, RevisionSource: receipt.LiveRevisionSourceReceipt,
		CitationSHA256: request.Citation.CitationSHA256,
		BindingSHA256:  request.Binding.BindingSHA256, PageNumber: request.Citation.PageNumber,
		BBox: request.Citation.BBox, QuoteSHA256: request.Citation.QuoteSHA256,
		ContentSnapshotSHA256:  request.Citation.ContentSnapshotSHA256,
		CoordinateSpaceVersion: receipt.TargetCoordinateSpace,
		PageWidth:              receipt.PageWidth, PageHeight: receipt.PageHeight,
		RotationDegrees: receipt.RotationDegrees, RetentionState: types.KnowledgeRevisionSourcePinned,
		ExpiresAtUnix: time.Date(2026, 8, 27, 13, 0, 0, 0, time.UTC).Unix(),
	}
	digest, err := types.ComputeSchemaWikiCitationContentAuthoritySHA256(*authority)
	if err != nil {
		return nil, err
	}
	authority.AuthoritySHA256 = digest
	authority.OpaqueToken = "c6-citation-test-token"
	return authority, nil
}

func schemaWikiC6TestMembers(t *testing.T, record wikirepository.SchemaWikiFormalCandidatePreviewRecord) []types.WikiReleaseMemberSnapshot {
	t.Helper()
	vector := loadSchemaWikiReleaseVector(t)
	release := vector.Release
	joinsByField := make(map[string][]types.Schema67CitationAuthorityJoinReceiptV1)
	for _, receipt := range vector.CandidateEvidenceAuthority.JoinReceipts {
		joinsByField[receipt.FieldID] = append(joinsByField[receipt.FieldID], receipt)
	}
	members := make([]types.WikiReleaseMemberSnapshot, 0, 75)
	appendMember := func(kind, slug, title string, body any) {
		payload, err := json.Marshal(map[string]any{
			"contract":           "schema-wiki-isolated-r1-member.815.v1",
			"candidate_sha256":   record.CandidateSHA256,
			"c5_manifest_sha256": record.ManifestSHA256,
			"c5_preview_sha256":  record.PreviewSHA256,
			"quality_status":     "NOT_EVALUATED",
			"mvp_status":         "NOT_ACCEPTED",
			"production_status":  "NOT_FOR_PRODUCTION",
			"publishing":         false,
			"member_kind":        kind,
			"body":               body,
		})
		require.NoError(t, err)
		sum := sha256.Sum256(payload)
		members = append(members, types.WikiReleaseMemberSnapshot{
			Kind: kind, LogicalSlug: slug, RevisionID: record.ManifestSHA256,
			MemberDigest: hex.EncodeToString(sum[:]), Title: title,
			Content: string(payload), Payload: payload,
		})
	}
	var root types.SchemaRootPageV1
	require.NoError(t, json.Unmarshal(release.Members[0].Payload, &root))
	appendMember("root", "root:"+root.EntityVersionID, root.ProductDisplayName, map[string]any{
		"entity_id": root.EntityID, "entity_version_id": root.EntityVersionID,
		"product_version_id": root.ProductVersionID, "display_name": root.ProductDisplayName,
	})
	fieldSection := make(map[string]string, 67)
	for _, section := range release.SchemaPack.Sections {
		appendMember("section", "section:"+section.SectionID, section.DisplayName, section)
		for _, fieldID := range section.OrderedFieldIDs {
			fieldSection[fieldID] = section.SectionID
		}
	}
	for index, fieldID := range release.SchemaPack.OrderedFieldIDs {
		var page types.SchemaFieldPageV1
		require.NoError(t, json.Unmarshal(release.Members[index+8].Payload, &page))
		body := map[string]any{
			"schema_order": index + 1, "section_id": fieldSection[fieldID], "field_id": fieldID,
			"display_name": fieldID, "state": page.State, "value_snapshot": page.ValueSnapshot,
			"typed_reason": nil, "source_selections": []any{},
		}
		if page.State == "unknown" {
			body["typed_reason"] = "SOURCE_GUIDANCE_ROLE_INTERSECTION_EMPTY"
		}
		if page.State == "present" || page.State == "absent_explicitly" {
			if page.State == "absent_explicitly" {
				body["state"] = "absent"
			}
			receipts := joinsByField[fieldID]
			require.Len(t, receipts, len(page.Citations))
			selections := make([]any, 0, len(receipts))
			for citationIndex, citation := range page.Citations {
				receipt := receipts[citationIndex]
				require.Equal(t, "citation-"+receipt.ReceiptSHA256[:24], citation.CitationID)
				bbox := []any{
					receipt.SourceBBoxPreimage[0], receipt.SourceBBoxPreimage[1],
					receipt.SourceBBoxPreimage[2], receipt.SourceBBoxPreimage[3],
				}
				selection := map[string]any{
					"selection_id": receipt.LocatorRef, "field_id": fieldID,
					"source_role":           receipt.SourceRole,
					"source_revision_id":    receipt.LiveRevisionSourceReceipt.RevisionSourceID,
					"original_file_sha256":  receipt.FileSHA256,
					"parse_manifest_sha256": receipt.RawStructureSHA256,
					"page_number":           receipt.PageNumber,
					"coordinate_space":      "PDF_POINTS_TOP_LEFT_V1",
					"page_width_points":     "1000", "page_height_points": "1000",
					"bbox": bbox, "rects": []any{bbox}, "block_id": receipt.LocatorRef,
					"span_id": receipt.LocatorRef + "-span", "table_id": nil,
					"table_slice_id": nil, "cell_ids": []any{},
					"quote":                citation.QuoteSnapshot,
					"quote_sha256":         digestWikiReleaseBytes([]byte(citation.QuoteSnapshot)),
					"page_text_char_start": 0,
					"page_text_char_end":   len([]rune(citation.QuoteSnapshot)),
				}
				selections = append(selections, selection)
			}
			body["source_selections"] = selections
		}
		appendMember("field", "field:"+fieldID, fieldID, body)
	}
	return members
}

func twoDigitServiceTest(value int) string {
	if value < 10 {
		return "0" + string(rune('0'+value))
	}
	return string(rune('0'+value/10)) + string(rune('0'+value%10))
}

func newSchemaWikiC6DecisionFixture(t *testing.T, faults WikiReleaseFaults) *schemaWikiC6DecisionFixture {
	t.Helper()
	vector := loadSchemaWikiReleaseVector(t)
	live := vector.CandidateEvidenceAuthority.SourceAuthorities[0].LiveRevisionSourceReceipt
	now := time.Date(2026, 8, 27, 12, 0, 0, 0, time.UTC)
	key := wikirepository.SchemaWikiFormalCandidatePreviewKey{
		KBID:            live.RawKBID,
		ExperimentID:    "5655e43c-1adb-4282-95f7-305e58441512",
		VersionIdentity: strings.Repeat("a", 64),
	}
	record := wikirepository.SchemaWikiFormalCandidatePreviewRecord{
		TenantID: 10003, KBID: key.KBID, ExperimentID: key.ExperimentID,
		ManifestSHA256: key.VersionIdentity, CandidateSHA256: vector.Release.CandidateSHA256,
		CompanionSHA256: strings.Repeat("c", 64), TerminalSHA256: strings.Repeat("d", 64),
		RevisionSetSHA256: strings.Repeat("e", 64), PreviewSHA256: strings.Repeat("f", 64),
		Preview: json.RawMessage(`{"contract":"schema-wiki-formal-candidate-preview.815.v1","quality_status":"NOT_EVALUATED","mvp_status":"NOT_ACCEPTED","publishing":false,"preview_sha256":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"}`),
	}
	reader := &schemaWikiFormalCandidatePreviewReaderStub{
		record: record, evidenceAuthority: vector.CandidateEvidenceAuthority,
		nativeSourceManifest: []byte(`{"contract":"weknora.ec.revision-item.v1"}`),
		nativeSourcePDF:      []byte("%PDF-1.7\nC6 fixture source\n%%EOF"),
	}
	reader.releaseMembers = schemaWikiC6TestMembers(t, record)
	db, err := gorm.Open(sqlite.Open("file:"+t.Name()+"?mode=memory&cache=shared"), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(
		&types.WikiReleasePreparation{}, &types.WikiRelease{}, &types.WikiReleaseMember{},
		&types.WikiReleaseHead{}, &types.WikiReleaseReceipt{},
	))
	repository := wikirepository.NewWikiReleaseRepository(db)
	privateKey := ed25519.NewKeyFromSeed(schemaWikiC6DecisionSeed[:])
	authorizationPrivateKey := ed25519.NewKeyFromSeed(schemaWikiC6AuthorizationSeed[:])
	idCounts := map[string]int{}
	authority := NewWikiReleaseService(
		repository, NewContextWikiReleaseAccessVerifier(),
		NewEd25519WikiReleaseAuthorizationVerifier(map[string]ed25519.PublicKey{
			"c6-authorization-key": authorizationPrivateKey.Public().(ed25519.PublicKey),
		}),
		WikiReleaseServiceOptions{
			Now: func() time.Time { return now }, Faults: faults,
			HumanDecisionVerifier: NewEd25519HumanBatchDecisionVerifier(map[string]ed25519.PublicKey{
				"c6-reviewer-key": privateKey.Public().(ed25519.PublicKey),
			}),
			NewID: func(kind string) string { idCounts[kind]++; return kind + "-c6-" + twoDigitServiceTest(idCounts[kind]) },
		},
	)
	principal := types.WikiReleasePrincipal{ID: "reviewer-c6", TenantID: live.TenantID, SpaceID: live.SpaceID}
	scope := types.WikiReleaseScope{
		TenantID: live.TenantID, SpaceID: principal.SpaceID, RawKBID: key.KBID,
		WikiKBID: live.WikiKBID,
	}
	ctx := schemaWikiHumanContext(principal, scope, types.TenantRoleAdmin)
	return &schemaWikiC6DecisionFixture{
		service:   NewSchemaWikiServiceWithFormalCandidatePreviewDecision(authority, reader, scope),
		authority: authority, repository: repository, db: db, reader: reader, key: key,
		principal: principal, scope: scope, ctx: ctx, now: now, privateKey: privateKey,
		authorizationPrivateKey: authorizationPrivateKey,
	}
}

func (f *schemaWikiC6DecisionFixture) decisionBytes(t *testing.T, decision string, mutate func(*types.HumanBatchDecisionReceiptV1)) []byte {
	t.Helper()
	_, _, policy, batch := schemaWikiC6FrozenHashesTest(t, f.reader.record)
	receipt := &types.HumanBatchDecisionReceiptV1{
		Version: "1", Decision: decision, PrincipalID: f.principal.ID,
		WikiReleaseScope: f.scope, CandidateHash: f.reader.record.CandidateSHA256,
		HumanBatchHash:   batch,
		ReviewPolicyHash: policy,
		IssuedAt:         f.now.Add(-time.Minute).Unix(), ExpiresAt: f.now.Add(time.Hour).Unix(),
		Nonce: "c6-decision-01", SignerKeyID: "c6-reviewer-key",
	}
	if mutate != nil {
		mutate(receipt)
	}
	unsigned, err := CanonicalHumanBatchDecisionReceiptV1(receipt, false)
	require.NoError(t, err)
	receipt.Signature = base64.RawURLEncoding.EncodeToString(ed25519.Sign(f.privateKey, unsigned))
	raw, err := CanonicalHumanBatchDecisionReceiptV1(receipt, true)
	require.NoError(t, err)
	return raw
}

func (f *schemaWikiC6DecisionFixture) authorizationBytes(
	t *testing.T,
	rawDecision []byte,
	mutate func(*types.PublishAuthorizationV0),
) []byte {
	return f.authorizationBytesForExpectedHead(t, rawDecision, "", 0, mutate)
}

func (f *schemaWikiC6DecisionFixture) authorizationBytesForExpectedHead(
	t *testing.T,
	rawDecision []byte,
	expectedReleaseID string,
	expectedActivationEpoch uint64,
	mutate func(*types.PublishAuthorizationV0),
) []byte {
	t.Helper()
	decision, err := ParseHumanBatchDecisionReceiptV1(rawDecision)
	require.NoError(t, err)
	decisionDigest := sha256.Sum256(rawDecision)
	preview := &SchemaWikiFormalCandidatePreviewResponseV1{
		ExperimentID:      f.reader.record.ExperimentID,
		VersionIdentity:   f.reader.record.ManifestSHA256,
		ManifestSHA256:    f.reader.record.ManifestSHA256,
		CandidateSHA256:   f.reader.record.CandidateSHA256,
		CompanionSHA256:   f.reader.record.CompanionSHA256,
		TerminalSHA256:    f.reader.record.TerminalSHA256,
		RevisionSetSHA256: f.reader.record.RevisionSetSHA256,
		PreviewSHA256:     f.reader.record.PreviewSHA256,
	}
	preparation, err := schemaWikiC6ReadyPreparation(
		f.scope, preview, hex.EncodeToString(decisionDigest[:]), f.reader.releaseMembers,
		f.reader.evidenceAuthority, expectedReleaseID, expectedActivationEpoch, f.now,
	)
	require.NoError(t, err)
	authorization := &types.PublishAuthorizationV0{
		Version: "0", Action: "activate", PreparationID: preparation.ID,
		CandidateDigest: preparation.CandidateDigest, ManifestDigest: preparation.ManifestDigest,
		ReadyReceiptDigest:   preparation.ReadyReceiptDigest,
		ReviewDecisionDigest: preparation.ReviewDecisionDigest,
		ReviewPolicyID:       preparation.ReviewPolicyID,
		TenantID:             f.scope.TenantID, SpaceID: f.scope.SpaceID,
		RawKBID: f.scope.RawKBID, WikiKBID: f.scope.WikiKBID,
		ExpectedReleaseID: expectedReleaseID, ExpectedActivationEpoch: expectedActivationEpoch,
		ExpiresAt: f.now.Add(time.Hour).Unix(), Nonce: decision.Nonce,
		SignerKeyID: "c6-authorization-key",
	}
	if mutate != nil {
		mutate(authorization)
	}
	unsigned, err := CanonicalPublishAuthorizationV0(authorization, false)
	require.NoError(t, err)
	authorization.Signature = base64.RawURLEncoding.EncodeToString(
		ed25519.Sign(f.authorizationPrivateKey, unsigned),
	)
	raw, err := CanonicalPublishAuthorizationV0(authorization, true)
	require.NoError(t, err)
	return raw
}

func (f *schemaWikiC6DecisionFixture) approveBytes(
	t *testing.T,
	mutateDecision func(*types.HumanBatchDecisionReceiptV1),
	mutateAuthorization func(*types.PublishAuthorizationV0),
) ([]byte, []byte) {
	t.Helper()
	decision := f.decisionBytes(t, "approve", mutateDecision)
	return decision, f.authorizationBytes(t, decision, mutateAuthorization)
}

func schemaWikiC6FrozenHashesTest(
	t *testing.T,
	record wikirepository.SchemaWikiFormalCandidatePreviewRecord,
) (string, string, string, string) {
	t.Helper()
	digest := func(domain string, value any) string {
		raw, err := json.Marshal(value)
		require.NoError(t, err)
		sum := sha256.Sum256(append([]byte(domain), raw...))
		return hex.EncodeToString(sum[:])
	}
	emptyPatchSum := sha256.Sum256([]byte(
		"insurancekb.c6-review-patch.815.v1\x00schema-wiki-canonical.v1\x00[]",
	))
	emptyPatch := hex.EncodeToString(emptyPatchSum[:])
	c4Gate := digest(
		"insurancekb.c4-status-sidecar.815.v1\x00schema-wiki-canonical.v1\x00c4-status-sidecar.815.v1\x00",
		map[string]any{
			"candidate_sha256": record.CandidateSHA256,
			"experiment_id":    record.ExperimentID,
			"quality_status":   "NOT_EVALUATED",
			"version_identity": record.ManifestSHA256,
		},
	)
	policy := digest(
		"insurancekb.c6-whole-candidate-review-policy.815.v1\x00schema-wiki-canonical.v1\x00",
		map[string]any{
			"c4_gate_hash":        c4Gate,
			"decision_scope":      "WHOLE_CANDIDATE",
			"publish_scope":       "ISOLATED_R1_ONLY",
			"review_patch_sha256": emptyPatch,
			"unknown_edit":        "FORBIDDEN",
		},
	)
	batch := digest(
		"insurancekb.c6-whole-candidate-review-subject.815.v1\x00schema-wiki-canonical.v1\x00",
		map[string]any{
			"c4_gate_hash":        c4Gate,
			"candidate_sha256":    record.CandidateSHA256,
			"experiment_id":       record.ExperimentID,
			"preview_sha256":      record.PreviewSHA256,
			"review_patch_sha256": emptyPatch,
			"version_identity":    record.ManifestSHA256,
		},
	)
	return emptyPatch, c4Gate, policy, batch
}

func (f *schemaWikiC6DecisionFixture) frozenDecisionBytes(
	t *testing.T,
	decision string,
	mutate func(*types.HumanBatchDecisionReceiptV1),
) []byte {
	t.Helper()
	_, _, policy, batch := schemaWikiC6FrozenHashesTest(t, f.reader.record)
	return f.decisionBytes(t, decision, func(value *types.HumanBatchDecisionReceiptV1) {
		value.HumanBatchHash = batch
		value.ReviewPolicyHash = policy
		if mutate != nil {
			mutate(value)
		}
	})
}

func TestSchemaWikiC6DecisionUsesFrozenBatchAndPolicyPreimages(t *testing.T) {
	fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
	decision, activation, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		fixture.frozenDecisionBytes(t, "reject", nil), nil,
	)
	require.NoError(t, err)
	require.Equal(t, "reject", decision.Decision)
	require.Nil(t, activation)
}

func TestSchemaWikiC6ApproveRequiresPublishAuthorization(t *testing.T) {
	fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
	_, _, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		fixture.decisionBytes(t, "approve", nil), nil,
	)
	require.ErrorIs(t, err, ErrWikiReleaseInvalidAuthorization)
	state, countErr := fixture.repository.CountState(fixture.ctx)
	require.NoError(t, countErr)
	require.Equal(t, types.WikiReleaseStateCount{}, state)
}

func TestSchemaWikiC6RejectsUnfrozenScopeBeforeBundleOpen(t *testing.T) {
	fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
	driftedScope := fixture.scope
	driftedScope.WikiKBID = "wiki-isolated-c6-drift"
	driftedCtx := schemaWikiHumanContext(fixture.principal, driftedScope, types.TenantRoleAdmin)
	_, _, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		driftedCtx, fixture.principal, driftedScope, fixture.key,
		fixture.decisionBytes(t, "reject", func(value *types.HumanBatchDecisionReceiptV1) {
			value.WikiReleaseScope = driftedScope
		}), nil,
	)
	require.ErrorIs(t, err, ErrSchemaWikiFormalCandidatePreviewRequestInvalid)
	require.Zero(t, fixture.reader.readCalls)
}

func TestSchemaWikiC6HumanAdminUsesCanonicalWebPrincipalIdentity(t *testing.T) {
	newRuntimeFixture := func(
		t *testing.T,
		contextPrincipal types.Principal,
		contextUserID string,
		contextTenantID uint64,
		role types.TenantRole,
		servicePrincipalID func(string) string,
	) *schemaWikiC6DecisionFixture {
		t.Helper()
		fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
		bareUserID := fixture.principal.ID
		fixture.principal.ID = servicePrincipalID(bareUserID)
		ctx := context.WithValue(context.Background(), types.UserIDContextKey, contextUserID)
		ctx = context.WithValue(ctx, types.TenantIDContextKey, contextTenantID)
		ctx = context.WithValue(ctx, types.TenantRoleContextKey, role)
		ctx = types.WithPrincipal(ctx, contextPrincipal)
		fixture.ctx = SealWikiReleaseAccess(ctx, fixture.principal, fixture.scope)
		return fixture
	}
	webStorageID := func(userID string) string {
		return (types.Principal{Type: types.PrincipalWebUser, ID: userID}).StorageID()
	}

	t.Run("same web user and tenant owner", func(t *testing.T) {
		fixture := newRuntimeFixture(
			t,
			types.Principal{Type: types.PrincipalWebUser, ID: "reviewer-c6"},
			"reviewer-c6", 10003, types.TenantRoleOwner, webStorageID,
		)
		decision, activation, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key,
			fixture.frozenDecisionBytes(t, "reject", nil), nil,
		)
		require.NoError(t, err)
		require.Equal(t, "reject", decision.Decision)
		require.Nil(t, activation)
	})

	negativeCases := map[string]struct {
		contextPrincipal types.Principal
		contextUserID    string
		contextTenantID  uint64
		role             types.TenantRole
		serviceID        func(string) string
	}{
		"different user": {
			contextPrincipal: types.Principal{Type: types.PrincipalWebUser, ID: "other-user"},
			contextUserID:    "other-user", contextTenantID: 10003,
			role: types.TenantRoleOwner, serviceID: webStorageID,
		},
		"different tenant": {
			contextPrincipal: types.Principal{Type: types.PrincipalWebUser, ID: "reviewer-c6"},
			contextUserID:    "reviewer-c6", contextTenantID: 10004,
			role: types.TenantRoleOwner, serviceID: webStorageID,
		},
		"non web principal": {
			contextPrincipal: types.Principal{Type: types.PrincipalIMUser, ID: "reviewer-c6"},
			contextUserID:    "reviewer-c6", contextTenantID: 10003,
			role: types.TenantRoleOwner, serviceID: webStorageID,
		},
		"malformed prefix": {
			contextPrincipal: types.Principal{Type: types.PrincipalWebUser, ID: "reviewer-c6"},
			contextUserID:    "reviewer-c6", contextTenantID: 10003,
			role:      types.TenantRoleOwner,
			serviceID: func(userID string) string { return "web-user:" + userID },
		},
		"non owner": {
			contextPrincipal: types.Principal{Type: types.PrincipalWebUser, ID: "reviewer-c6"},
			contextUserID:    "reviewer-c6", contextTenantID: 10003,
			role: types.TenantRoleViewer, serviceID: webStorageID,
		},
	}
	for name, testCase := range negativeCases {
		t.Run(name, func(t *testing.T) {
			fixture := newRuntimeFixture(
				t, testCase.contextPrincipal, testCase.contextUserID,
				testCase.contextTenantID, testCase.role, testCase.serviceID,
			)
			_, _, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
				fixture.ctx, fixture.principal, fixture.scope, fixture.key,
				fixture.frozenDecisionBytes(t, "reject", nil), nil,
			)
			require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
			require.Zero(t, fixture.reader.readCalls)
		})
	}
}

func TestSchemaWikiC6CurrentAndPinnedSchemaReadsReopenIsolatedCustody(t *testing.T) {
	fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
	rawDecision, rawAuthorization := fixture.approveBytes(t, nil, nil)
	_, activation, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		rawDecision, rawAuthorization,
	)
	require.NoError(t, err)
	require.NotNil(t, activation)
	current, err := fixture.service.ReadCurrentSchemaMember(
		fixture.ctx, fixture.principal, fixture.scope, "root:ping-an-e-sheng-bao@596-1",
	)
	require.NoError(t, err)
	require.Equal(t, activation.ReleaseID, current.ReleaseID)
	pin, err := fixture.authority.BeginPinnedRead(fixture.ctx, fixture.principal, fixture.scope)
	require.NoError(t, err)
	pinned, err := fixture.service.ReadPinnedSchemaMember(
		fixture.ctx, fixture.principal, pin, "field:product_code",
	)
	require.NoError(t, err)
	require.Equal(t, "field", pinned.Kind)
	authority, err := fixture.service.ReadCurrentSchemaAuthority(
		fixture.ctx, fixture.principal, fixture.scope,
	)
	require.NoError(t, err)
	require.Equal(t, activation.ReleaseID, authority.ReleaseID)
	require.Equal(t, "ping-an-e-sheng-bao@596-1", authority.Root.EntityVersionID)
	expected := loadSchemaWikiReleaseVector(t).Release
	require.Equal(t, expected.Domain, authority.Domain)
	require.Equal(t, expected.Taxonomy, authority.Taxonomy)
	require.Equal(t, expected.SchemaPack, authority.SchemaPack)

	validated, projected, err := fixture.service.loadPinnedSchemaRelease(
		fixture.ctx, fixture.principal, pin,
	)
	require.NoError(t, err)
	require.Len(t, projected, 75)
	require.Len(t, validated.release.Members, 75)
	require.Equal(t, projected[0].Payload, current.Payload)
	require.Equal(t, projected[8].Payload, pinned.Payload)
	for index, member := range projected {
		canonical, canonicalErr := types.CanonicalSchemaWikiMemberPayload(member.Kind, member.Payload)
		require.NoErrorf(t, canonicalErr, "projected member %d (%s)", index, member.LogicalSlug)
		require.JSONEq(t, string(canonical), string(member.Payload))
		switch member.Kind {
		case "section":
			var page types.SchemaSectionPageV1
			require.NoError(t, json.Unmarshal(member.Payload, &page))
			require.Equal(t, expected.SchemaPack.Sections[index-1].SectionID, page.SectionID)
			require.Equal(t, expected.SchemaPack.Sections[index-1].OrderedFieldIDs, page.OrderedFieldIDs)
		case "field":
			var page types.SchemaFieldPageV1
			require.NoError(t, json.Unmarshal(member.Payload, &page))
			require.Equal(t, expected.SchemaPack.OrderedFieldIDs[index-8], page.FieldID)
		}
	}
	var root types.SchemaRootPageV1
	require.NoError(t, json.Unmarshal(projected[0].Payload, &root))
	require.Equal(t, expected.Domain.DomainID, root.DomainID)
	require.Equal(t, expected.Domain.DomainSHA256, root.DomainSHA256)
	require.Equal(t, expected.SchemaPack.SchemaPackID, root.SchemaPackID)
	require.Equal(t, expected.SchemaPack.SchemaPackSHA256, root.SchemaPackSHA256)
	require.Equal(t, []string{
		"product-overview", "application-and-contract", "renewal-and-pricing",
		"coverage-and-exclusions", "claims-and-reimbursement",
		"services-and-benefits", "sales-support",
	}, root.OrderedSectionIDs)
	var productCode types.SchemaFieldPageV1
	require.NoError(t, json.Unmarshal(projected[8].Payload, &productCode))
	require.Equal(t, "product_code", productCode.FieldID)
	require.Equal(t, "present", productCode.State)
	require.Equal(t, "approved-value:product_code", *productCode.ValueSnapshot)
	require.Len(t, productCode.Citations, 3)
	require.Equal(t, fixture.scope.SpaceID, productCode.Citations[0].SpaceID)
	require.Equal(t,
		fixture.reader.evidenceAuthority.JoinReceipts[0].LiveRevisionSourceReceipt.RevisionSourceID,
		productCode.Citations[0].SourceRevisionID,
	)
	require.Equal(t, "field:product_code", productCode.Citations[0].LogicalMemberRef)
	require.Len(t, productCode.EvidenceReceiptSHA256s, 1)
	require.Equal(t,
		fixture.reader.evidenceAuthority.JoinReceipts[0].EvidenceReceiptSHA256,
		productCode.EvidenceReceiptSHA256s[0],
	)
	var unknown types.SchemaFieldPageV1
	for _, member := range projected[8:] {
		var page types.SchemaFieldPageV1
		require.NoError(t, json.Unmarshal(member.Payload, &page))
		if page.State == "unknown" {
			unknown = page
			break
		}
	}
	require.Equal(t, "unknown", unknown.State)
	require.Nil(t, unknown.ValueSnapshot)
	require.Empty(t, unknown.Citations)
	require.Empty(t, unknown.EvidenceReceiptSHA256s)
	encodedUnknown, err := json.Marshal(unknown)
	require.NoError(t, err)
	require.Contains(t, string(encodedUnknown), `"citations":[]`)
	require.Contains(t, string(encodedUnknown), `"evidence_receipt_sha256s":[]`)
}

func requireSchemaWikiC6CitationRequestExact(
	t *testing.T,
	request CitationRevisionReadRequestV1,
	pin WikiReleasePinnedRead,
	citation types.CitationTargetV1,
) {
	t.Helper()
	require.Equal(t, pin.ReleaseID(), request.ReleaseID)
	require.Equal(t, pin.ActivationEpoch(), request.ActivationEpoch)
	require.Equal(t, "product_code", request.FieldID)
	require.Equal(t, pin.scope, request.Scope)
	require.Equal(t, citation, request.Citation)
	require.Equal(t, citation.CitationSHA256, request.Binding.CitationSHA256)
	require.Equal(t, citation.LogicalMemberRef, request.Binding.LogicalMemberRef)
	require.NotNil(t, request.frozenNativeSource)
	require.NotNil(t, request.CoordinateAuthorityReceipt)
	receipt := request.CoordinateAuthorityReceipt
	require.NoError(t, types.ValidateSchema67CitationAuthorityJoinReceiptV1(*receipt))
	require.Len(t, receipt.ReceiptSHA256, 64)
	require.Equal(t, request.CandidateSHA256, receipt.CandidateSHA256)
	require.Equal(t, request.FieldID, receipt.FieldID)
	require.Equal(t, citation.SourceRole, receipt.SourceRole)
	require.Equal(t, citation.SourceRevisionID, receipt.LiveRevisionSourceReceipt.RevisionSourceID)
	require.Equal(t, citation.PageNumber, receipt.PageNumber)
	require.Equal(t, citation.BBox, receipt.NormalizedBBox)
	require.Equal(t, citation.QuoteSHA256, receipt.QuoteSHA256)
	require.Equal(t, citation.ContentSnapshotSHA256, receipt.LocatorContentSHA256)
	require.Equal(t, citation.ParseManifestSHA256, receipt.ParseManifestSHA256)
	require.Equal(t, citation.CitationID, "citation-"+receipt.ReceiptSHA256[:24])
}

func requireSchemaWikiC6CitationRequestUsesVerifiedNativeAttempt(
	t *testing.T,
	request CitationRevisionReadRequestV1,
) {
	t.Helper()
	receipt := request.CoordinateAuthorityReceipt
	require.NotNil(t, receipt)
	revisions := &schemaWikiCitationRevisionRepositoryStub{knowledge: &types.Knowledge{
		ID: request.Citation.KnowledgeID, TenantID: request.Scope.TenantID,
		KnowledgeBaseID: request.Scope.RawKBID, ParseStatus: types.ParseStatusCompleted,
		FileType: "pdf",
	}}
	adapter := newSchemaWikiCitationRevisionReadAdapter(
		revisions, &schemaWikiCitationChunkRepositoryStub{},
	)
	_, err := adapter.resolveExactRevisionAuthority(
		context.WithValue(context.Background(), types.TenantIDContextKey, request.Scope.TenantID),
		request,
	)
	require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
	require.Equal(t, 1, revisions.knowledgeCalls)
	require.Equal(t, 1, revisions.revisionCalls)
	require.Equal(t, receipt.LiveRevisionSourceReceipt.WeKnoraParseAttempt, revisions.lastAttempt)
	require.Equal(t, receipt.EvidenceParseAttemptID, request.Citation.ParseAttemptID)
	require.Equal(t,
		receipt.LiveRevisionSourceReceipt.RevisionSourceID,
		request.Citation.SourceRevisionID,
	)
}

func TestSchemaWikiC6CurrentAndExplicitPinnedCitationAuthorityReopenProjectedEvidence(t *testing.T) {
	fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
	rawDecision, rawAuthorization := fixture.approveBytes(t, nil, nil)
	_, activation, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		rawDecision, rawAuthorization,
	)
	require.NoError(t, err)
	require.NotNil(t, activation)
	pin, err := fixture.authority.BeginPinnedRead(fixture.ctx, fixture.principal, fixture.scope)
	require.NoError(t, err)
	releaseRow, err := fixture.repository.GetRelease(fixture.ctx, fixture.scope, pin.ReleaseID())
	require.NoError(t, err)
	preparation, err := fixture.repository.GetReadyPreparation(
		fixture.ctx, fixture.scope, releaseRow.PreparationID,
	)
	require.NoError(t, err)
	custody, _, err := canonicalSchemaWikiC6StoredManifest(preparation.Manifest)
	require.NoError(t, err)
	require.NotNil(t, custody.CandidateEvidenceAuthority)
	require.Equal(t, fixture.reader.evidenceAuthority, *custody.CandidateEvidenceAuthority)
	projectedRelease, err := schemaWikiC6ReleaseProjection(
		fixture.scope, custody, custody.OrderedMembers,
	)
	require.NoError(t, err)
	require.NoError(t, types.ValidateSchema67CandidateEvidenceAuthorityV1(
		*custody.CandidateEvidenceAuthority, projectedRelease,
	))
	validated, _, err := fixture.service.loadPinnedSchemaRelease(
		fixture.ctx, fixture.principal, pin,
	)
	require.NoError(t, err)
	var citation types.CitationTargetV1
	for _, member := range validated.release.Members {
		if member.MemberRef != "field:product_code" {
			continue
		}
		var page types.SchemaFieldPageV1
		require.NoError(t, json.Unmarshal(member.Payload, &page))
		require.NotEmpty(t, page.Citations)
		citation = page.Citations[0]
	}
	require.NotEmpty(t, citation.CitationID)

	t.Run("current authority", func(t *testing.T) {
		content := &schemaWikiC6CitationContentSpy{}
		fixture.service.citationContent = content
		authority, issueErr := fixture.service.IssueCurrentSchemaCitationAuthority(
			fixture.ctx, fixture.principal, fixture.scope, activation.ReleaseID,
			citation.LogicalMemberRef, citation.CitationID,
		)
		require.NoError(t, issueErr)
		require.NotNil(t, authority)
		require.Equal(t, 1, content.issueCurrentCalls)
		requireSchemaWikiC6CitationRequestExact(t, content.request, pin, citation)
		require.Equal(t, content.request.ReleaseID, authority.ReleaseID)
		require.Equal(t, content.request.ActivationEpoch, authority.ActivationEpoch)
		require.Equal(t, content.request.FieldID, authority.FieldID)
		require.Equal(t, content.request.Citation.CitationID, authority.CitationID)
		require.Equal(t, content.request.CoordinateAuthorityReceipt.LiveRevisionSourceReceipt,
			authority.RevisionSource)
		requireSchemaWikiC6CitationRequestUsesVerifiedNativeAttempt(t, content.request)
	})

	t.Run("explicit pinned authority does not consult current", func(t *testing.T) {
		require.NoError(t, fixture.db.Delete(
			&types.WikiReleaseHead{}, "active_release_id = ?", pin.ReleaseID(),
		).Error)
		pinned, _, pinnedErr := fixture.service.loadPinnedSchemaRelease(
			fixture.ctx, fixture.principal, pin,
		)
		require.NoError(t, pinnedErr)
		request, requestErr := schemaWikiCitationRequest(
			pinned, pin.scope, pin.ReleaseID(), pin.ActivationEpoch(),
			citation.LogicalMemberRef, citation.CitationID,
		)
		require.NoError(t, requestErr)
		request, requestErr = fixture.service.bindSchemaWikiC6FrozenNativeSource(pinned, request)
		require.NoError(t, requestErr)
		require.NotNil(t, request.frozenNativeSource)
		requireSchemaWikiC6CitationRequestExact(t, request, pin, citation)
		require.NoError(t, types.ValidateSchema67CandidateEvidenceAuthorityV1(
			pinned.candidateEvidenceAuthority, pinned.release,
		))
		requireSchemaWikiC6CitationRequestUsesVerifiedNativeAttempt(t, request)
	})
}

func TestSchemaWikiC6CurrentCitationLoadsFrozenNativeSourceCustody(t *testing.T) {
	fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
	fixture.reader.nativeSourceManifest = []byte(`{"contract":"weknora.ec.revision-item.v1"}`)
	fixture.reader.nativeSourcePDF = []byte("%PDF-1.7\nexact frozen source\n%%EOF")
	rawDecision, rawAuthorization := fixture.approveBytes(t, nil, nil)
	_, activation, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		rawDecision, rawAuthorization,
	)
	require.NoError(t, err)
	require.NotNil(t, activation)
	pin, err := fixture.authority.BeginPinnedRead(fixture.ctx, fixture.principal, fixture.scope)
	require.NoError(t, err)
	validated, _, err := fixture.service.loadPinnedSchemaRelease(
		fixture.ctx, fixture.principal, pin,
	)
	require.NoError(t, err)
	var citation types.CitationTargetV1
	for _, member := range validated.release.Members {
		if member.MemberKind != "field" {
			continue
		}
		var page types.SchemaFieldPageV1
		require.NoError(t, json.Unmarshal(member.Payload, &page))
		if len(page.Citations) > 0 {
			citation = page.Citations[0]
			break
		}
	}
	require.NotEmpty(t, citation.CitationID)
	content := &schemaWikiC6CitationContentSpy{}
	fixture.service.citationContent = content
	_, err = fixture.service.IssueCurrentSchemaCitationAuthority(
		fixture.ctx, fixture.principal, fixture.scope, activation.ReleaseID,
		citation.LogicalMemberRef, citation.CitationID,
	)
	require.NoError(t, err)
	require.Equal(t, 1, fixture.reader.nativeSourceCalls,
		"isolated current citation must fresh-read its exact C5 native source custody")
	request, err := schemaWikiCitationRequest(
		validated, pin.scope, pin.ReleaseID(), pin.ActivationEpoch(),
		citation.LogicalMemberRef, citation.CitationID,
	)
	require.NoError(t, err)
	foreign := validated
	foreign.revisionSetSHA256 = strings.Repeat("9", 64)
	_, err = fixture.service.bindSchemaWikiC6FrozenNativeSource(foreign, request)
	require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
}

func TestSchemaWikiC6CurrentAndExplicitPinnedRejectSelectionParseManifestIdentityMismatch(t *testing.T) {
	fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
	changed := false
	for index := range fixture.reader.releaseMembers {
		var envelope map[string]any
		require.NoError(t, json.Unmarshal(fixture.reader.releaseMembers[index].Payload, &envelope))
		body, ok := envelope["body"].(map[string]any)
		if !ok {
			continue
		}
		selections, ok := body["source_selections"].([]any)
		if !ok || len(selections) == 0 {
			continue
		}
		selection, ok := selections[0].(map[string]any)
		require.True(t, ok)
		selection["parse_manifest_sha256"] = strings.Repeat("9", 64)
		payload, err := json.Marshal(envelope)
		require.NoError(t, err)
		fixture.reader.releaseMembers[index].Payload = payload
		fixture.reader.releaseMembers[index].Content = string(payload)
		fixture.reader.releaseMembers[index].MemberDigest = digestWikiReleaseBytes(payload)
		changed = true
		break
	}
	require.True(t, changed)

	rawDecision, rawAuthorization := fixture.approveBytes(t, nil, nil)
	_, activation, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		rawDecision, rawAuthorization,
	)
	require.NoError(t, err)
	require.NotNil(t, activation)
	_, err = fixture.service.ReadCurrentSchemaMember(
		fixture.ctx, fixture.principal, fixture.scope, "field:product_code",
	)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
	pinned := WikiReleasePinnedRead{
		scope: fixture.scope, releaseID: activation.ReleaseID,
		activationEpoch: activation.ActivationEpoch,
	}
	_, _, err = fixture.service.loadPinnedSchemaRelease(
		fixture.ctx, fixture.principal, pinned,
	)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
}

func TestSchemaWikiC6RejectReturnsVerifiedWholeBatchDecisionWithZeroWrites(t *testing.T) {
	fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
	before, err := fixture.repository.CountState(fixture.ctx)
	require.NoError(t, err)

	decision, releaseReceipt, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		fixture.decisionBytes(t, "reject", nil), []byte("null"),
	)
	require.NoError(t, err)
	require.Equal(t, "reject", decision.Decision)
	require.Nil(t, releaseReceipt)
	require.Equal(t, 1, fixture.reader.readCalls)
	require.Equal(t, 0, fixture.reader.releaseMemberCalls)
	after, err := fixture.repository.CountState(fixture.ctx)
	require.NoError(t, err)
	require.Equal(t, before, after)

	_, _, err = fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		fixture.decisionBytes(t, "reject", nil), []byte(`{}`),
	)
	require.ErrorIs(t, err, ErrWikiReleaseInvalidAuthorization)
	afterInvalidAuthorization, countErr := fixture.repository.CountState(fixture.ctx)
	require.NoError(t, countErr)
	require.Equal(t, before, afterInvalidAuthorization)
}

func TestSchemaWikiC6ApproveAtomicallyCreatesOneR1With75MembersAndEpochOne(t *testing.T) {
	fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
	rawDecision, rawAuthorization := fixture.approveBytes(t, nil, nil)
	decision, activation, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		rawDecision, rawAuthorization,
	)
	require.NoError(t, err)
	require.Equal(t, "approve", decision.Decision)
	require.Equal(t, uint64(1), activation.ActivationEpoch)
	state, err := fixture.repository.CountState(fixture.ctx)
	require.NoError(t, err)
	require.Equal(t, types.WikiReleaseStateCount{Preparations: 1, Releases: 1, Members: 75, Heads: 1, Receipts: 1}, state)
	release, err := fixture.repository.GetRelease(fixture.ctx, fixture.scope, activation.ReleaseID)
	require.NoError(t, err)
	require.Equal(t, fixture.reader.record.CandidateSHA256, release.CandidateDigest)
	require.Empty(t, release.BaseReleaseID)
	require.Zero(t, release.BaseActivationEpoch)
	preparation, err := fixture.repository.GetReadyPreparation(fixture.ctx, fixture.scope, release.PreparationID)
	require.NoError(t, err)
	emptyPatch, c4Gate, policy, batch := schemaWikiC6FrozenHashesTest(t, fixture.reader.record)
	require.Equal(t, release.CandidateDigest, preparation.CandidateDigest)
	require.Equal(t, release.ManifestDigest, preparation.ManifestDigest)
	require.Equal(t, batch, preparation.ReadyReceiptDigest)
	require.Equal(t, policy, preparation.ReviewPolicyID)
	require.Equal(t, types.WikiReleasePreparationReady, preparation.Status)
	require.Len(t, preparation.Members, 75)
	var custody schemaWikiC6IsolatedCustodyV1
	require.NoError(t, json.Unmarshal(preparation.Manifest, &custody))
	require.Equal(t, fixture.reader.record.ExperimentID, custody.ExperimentID)
	require.Equal(t, fixture.reader.record.ManifestSHA256, custody.VersionIdentity)
	require.Equal(t, emptyPatch, custody.ReviewPatchSHA256)
	require.Equal(t, c4Gate, custody.C4GateHash)
	require.Equal(t, policy, custody.ReviewPolicySHA256)
	require.Equal(t, batch, custody.HumanBatchSHA256)
	require.Len(t, custody.OrderedMembers, 75)
	require.Len(t, custody.OrderedMemberSHA256s, 75)
	members, err := fixture.repository.GetReleaseMembers(fixture.ctx, fixture.scope, release.ID)
	require.NoError(t, err)
	require.Len(t, members, 75)
	current, err := fixture.authority.Current(fixture.ctx, fixture.principal, fixture.scope)
	require.NoError(t, err)
	require.Equal(t, types.WikiReleaseCurrent{ReleaseID: release.ID, ActivationEpoch: 1}, current)
	pin, err := fixture.authority.BeginPinnedRead(fixture.ctx, fixture.principal, fixture.scope)
	require.NoError(t, err)
	root, err := fixture.authority.ReadPinnedPage(fixture.ctx, fixture.principal, pin, "root:ping-an-e-sheng-bao@596-1")
	require.NoError(t, err)
	require.Contains(t, string(root.Payload), `"quality_status":"NOT_EVALUATED"`)
	require.Contains(t, string(root.Payload), `"production_status":"NOT_FOR_PRODUCTION"`)
	require.Contains(t, string(root.Payload), `"mvp_status":"NOT_ACCEPTED"`)
}

func TestSchemaWikiC6ApproveCreatesImmutableSuccessorAndAdvancesHeadByCAS(t *testing.T) {
	fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
	firstDecision, firstAuthorization := fixture.approveBytes(t, nil, nil)
	_, firstReceipt, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		firstDecision, firstAuthorization,
	)
	require.NoError(t, err)
	require.NotNil(t, firstReceipt)
	require.Equal(t, uint64(1), firstReceipt.ActivationEpoch)

	firstRelease, err := fixture.repository.GetRelease(
		fixture.ctx, fixture.scope, firstReceipt.ReleaseID,
	)
	require.NoError(t, err)
	firstMembers, err := fixture.repository.GetReleaseMembers(
		fixture.ctx, fixture.scope, firstReceipt.ReleaseID,
	)
	require.NoError(t, err)
	firstReleaseBytes, err := json.Marshal(firstRelease)
	require.NoError(t, err)
	firstMembersBytes, err := json.Marshal(firstMembers)
	require.NoError(t, err)
	firstReceiptBytes, err := json.Marshal(firstReceipt)
	require.NoError(t, err)
	fixture.key.ExperimentID = "6655e43c-1adb-4282-95f7-305e58441512"
	fixture.key.VersionIdentity = strings.Repeat("1", 64)
	fixture.reader.record.ExperimentID = fixture.key.ExperimentID
	fixture.reader.record.ManifestSHA256 = fixture.key.VersionIdentity
	fixture.reader.record.CompanionSHA256 = strings.Repeat("2", 64)
	fixture.reader.record.TerminalSHA256 = strings.Repeat("3", 64)
	fixture.reader.record.RevisionSetSHA256 = strings.Repeat("4", 64)
	fixture.reader.record.PreviewSHA256 = strings.Repeat("5", 64)
	fixture.reader.record.Preview = json.RawMessage(
		`{"contract":"schema-wiki-formal-candidate-preview.815.v1","quality_status":"NOT_EVALUATED","mvp_status":"NOT_ACCEPTED","publishing":false,"preview_sha256":"5555555555555555555555555555555555555555555555555555555555555555"}`,
	)
	fixture.reader.releaseMembers = schemaWikiC6TestMembers(t, fixture.reader.record)

	secondDecision := fixture.decisionBytes(
		t, "approve", func(value *types.HumanBatchDecisionReceiptV1) {
			value.Nonce = "c6-decision-02"
		},
	)
	secondAuthorization := fixture.authorizationBytesForExpectedHead(
		t, secondDecision, firstReceipt.ReleaseID, firstReceipt.ActivationEpoch, nil,
	)
	_, secondReceipt, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		secondDecision, secondAuthorization,
	)
	require.NoError(t, err)
	require.NotNil(t, secondReceipt)
	require.Equal(t, firstReceipt.ReleaseID, secondReceipt.PreviousReleaseID)
	require.NotEqual(t, firstReceipt.ReleaseID, secondReceipt.ReleaseID)
	require.Equal(t, uint64(2), secondReceipt.ActivationEpoch)

	head, err := fixture.repository.GetHead(fixture.ctx, fixture.scope)
	require.NoError(t, err)
	require.Equal(t, secondReceipt.ReleaseID, head.ActiveReleaseID)
	require.Equal(t, uint64(2), head.ActivationEpoch)
	secondRelease, err := fixture.repository.GetRelease(
		fixture.ctx, fixture.scope, secondReceipt.ReleaseID,
	)
	require.NoError(t, err)
	require.Equal(t, firstReceipt.ReleaseID, secondRelease.BaseReleaseID)
	require.Equal(t, uint64(1), secondRelease.BaseActivationEpoch)
	secondMembers, err := fixture.repository.GetReleaseMembers(
		fixture.ctx, fixture.scope, secondReceipt.ReleaseID,
	)
	require.NoError(t, err)
	require.Len(t, secondMembers, 75)
	require.NotEqual(t, firstMembersBytes, mustMarshalSchemaWikiC6Test(t, secondMembers))
	current, err := fixture.authority.Current(fixture.ctx, fixture.principal, fixture.scope)
	require.NoError(t, err)
	require.Equal(t, types.WikiReleaseCurrent{
		ReleaseID: secondReceipt.ReleaseID, ActivationEpoch: 2,
	}, current)
	pin, err := fixture.authority.BeginPinnedRead(fixture.ctx, fixture.principal, fixture.scope)
	require.NoError(t, err)
	root, err := fixture.authority.ReadPinnedPage(
		fixture.ctx, fixture.principal, pin, "root:ping-an-e-sheng-bao@596-1",
	)
	require.NoError(t, err)
	require.Equal(t, fixture.reader.record.ManifestSHA256, root.RevisionID)
	currentSchema, err := fixture.service.ReadCurrentSchemaMember(
		fixture.ctx, fixture.principal, fixture.scope, "root:ping-an-e-sheng-bao@596-1",
	)
	require.NoError(t, err)
	require.Equal(t, secondReceipt.ReleaseID, currentSchema.ReleaseID)
	pinnedSchema, err := fixture.service.ReadPinnedSchemaMember(
		fixture.ctx, fixture.principal, pin, "field:product_code",
	)
	require.NoError(t, err)
	require.Equal(t, "field:product_code", pinnedSchema.LogicalSlug)

	unchangedFirstRelease, err := fixture.repository.GetRelease(
		fixture.ctx, fixture.scope, firstReceipt.ReleaseID,
	)
	require.NoError(t, err)
	unchangedFirstMembers, err := fixture.repository.GetReleaseMembers(
		fixture.ctx, fixture.scope, firstReceipt.ReleaseID,
	)
	require.NoError(t, err)
	unchangedFirstReceipt, err := fixture.repository.GetReceipt(
		fixture.ctx, fixture.scope, "c6-decision-01",
	)
	require.NoError(t, err)
	actualFirstReleaseBytes, err := json.Marshal(unchangedFirstRelease)
	require.NoError(t, err)
	actualFirstMembersBytes, err := json.Marshal(unchangedFirstMembers)
	require.NoError(t, err)
	actualFirstReceiptBytes, err := json.Marshal(unchangedFirstReceipt)
	require.NoError(t, err)
	require.Equal(t, firstReleaseBytes, actualFirstReleaseBytes)
	require.Equal(t, firstMembersBytes, actualFirstMembersBytes)
	require.Equal(t, firstReceiptBytes, actualFirstReceiptBytes)

	state, err := fixture.repository.CountState(fixture.ctx)
	require.NoError(t, err)
	require.Equal(t, types.WikiReleaseStateCount{
		Preparations: 2, Releases: 2, Members: 150, Heads: 1, Receipts: 2,
	}, state)

	beforeRetry := state
	_, repeatedReceipt, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		secondDecision, secondAuthorization,
	)
	require.NoError(t, err)
	require.Equal(t, secondReceipt, repeatedReceipt)
	afterRetry, err := fixture.repository.CountState(fixture.ctx)
	require.NoError(t, err)
	require.Equal(t, beforeRetry, afterRetry)

	driftDecision := fixture.decisionBytes(
		t, "approve", func(value *types.HumanBatchDecisionReceiptV1) {
			value.Nonce = "c6-decision-03"
		},
	)
	driftAuthorization := fixture.authorizationBytesForExpectedHead(
		t, driftDecision, firstReceipt.ReleaseID, firstReceipt.ActivationEpoch, nil,
	)
	_, _, err = fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		driftDecision, driftAuthorization,
	)
	require.ErrorIs(t, err, ErrWikiReleaseConflict)
	afterDrift, err := fixture.repository.CountState(fixture.ctx)
	require.NoError(t, err)
	require.Equal(t, beforeRetry, afterDrift)

	rejectDecision := fixture.decisionBytes(
		t, "reject", func(value *types.HumanBatchDecisionReceiptV1) {
			value.Nonce = "c6-decision-04"
		},
	)
	decision, releaseReceipt, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		rejectDecision, []byte("null"),
	)
	require.NoError(t, err)
	require.Equal(t, "reject", decision.Decision)
	require.Nil(t, releaseReceipt)
	afterReject, err := fixture.repository.CountState(fixture.ctx)
	require.NoError(t, err)
	require.Equal(t, beforeRetry, afterReject)
}

func approveSchemaWikiC6SuccessorForReadTest(
	t *testing.T,
	fixture *schemaWikiC6DecisionFixture,
) *types.WikiReleaseReceipt {
	t.Helper()
	firstDecision, firstAuthorization := fixture.approveBytes(t, nil, nil)
	_, firstReceipt, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		firstDecision, firstAuthorization,
	)
	require.NoError(t, err)
	require.NotNil(t, firstReceipt)
	fixture.key.ExperimentID = "6655e43c-1adb-4282-95f7-305e58441512"
	fixture.key.VersionIdentity = strings.Repeat("1", 64)
	fixture.reader.record.ExperimentID = fixture.key.ExperimentID
	fixture.reader.record.ManifestSHA256 = fixture.key.VersionIdentity
	fixture.reader.record.CompanionSHA256 = strings.Repeat("2", 64)
	fixture.reader.record.TerminalSHA256 = strings.Repeat("3", 64)
	fixture.reader.record.RevisionSetSHA256 = strings.Repeat("4", 64)
	fixture.reader.record.PreviewSHA256 = strings.Repeat("5", 64)
	fixture.reader.record.Preview = json.RawMessage(
		`{"contract":"schema-wiki-formal-candidate-preview.815.v1","quality_status":"NOT_EVALUATED","mvp_status":"NOT_ACCEPTED","publishing":false,"preview_sha256":"5555555555555555555555555555555555555555555555555555555555555555"}`,
	)
	fixture.reader.releaseMembers = schemaWikiC6TestMembers(t, fixture.reader.record)
	secondDecision := fixture.decisionBytes(
		t, "approve", func(value *types.HumanBatchDecisionReceiptV1) {
			value.Nonce = "c6-decision-02"
		},
	)
	secondAuthorization := fixture.authorizationBytesForExpectedHead(
		t, secondDecision, firstReceipt.ReleaseID, firstReceipt.ActivationEpoch, nil,
	)
	_, secondReceipt, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		secondDecision, secondAuthorization,
	)
	require.NoError(t, err)
	require.NotNil(t, secondReceipt)
	return secondReceipt
}

func TestSchemaWikiC6CurrentAndPinnedReopenRejectPersistedBaseIdentityDrift(t *testing.T) {
	tests := []struct {
		name   string
		mutate func(*types.WikiReleasePreparation, *types.WikiReleaseReceipt)
	}{
		{
			name: "empty release with nonzero epoch",
			mutate: func(preparation *types.WikiReleasePreparation, _ *types.WikiReleaseReceipt) {
				preparation.ExpectedReleaseID = ""
				preparation.ExpectedActivationEpoch = 1
				preparation.PreparationDigest = digestWikiReleasePreparation(preparation)
			},
		},
		{
			name: "nonempty release with zero epoch",
			mutate: func(preparation *types.WikiReleasePreparation, receipt *types.WikiReleaseReceipt) {
				preparation.ExpectedReleaseID = receipt.PreviousReleaseID
				preparation.ExpectedActivationEpoch = 0
				preparation.PreparationDigest = digestWikiReleasePreparation(preparation)
			},
		},
		{
			name: "complete foreign base release",
			mutate: func(preparation *types.WikiReleasePreparation, _ *types.WikiReleaseReceipt) {
				preparation.ExpectedReleaseID = "release-foreign"
				preparation.ExpectedActivationEpoch = 1
				preparation.PreparationDigest = digestWikiReleasePreparation(preparation)
			},
		},
		{
			name: "complete base epoch drift",
			mutate: func(preparation *types.WikiReleasePreparation, receipt *types.WikiReleaseReceipt) {
				preparation.ExpectedReleaseID = receipt.PreviousReleaseID
				preparation.ExpectedActivationEpoch = 2
				preparation.PreparationDigest = digestWikiReleasePreparation(preparation)
			},
		},
		{
			name: "preparation digest drift",
			mutate: func(preparation *types.WikiReleasePreparation, _ *types.WikiReleaseReceipt) {
				preparation.ExpectedReleaseID = "release-foreign"
			},
		},
		{
			name: "signed decision binding drift",
			mutate: func(preparation *types.WikiReleasePreparation, _ *types.WikiReleaseReceipt) {
				preparation.ReviewDecisionDigest = strings.Repeat("8", 64)
				preparation.PreparationDigest = digestWikiReleasePreparation(preparation)
			},
		},
	}
	for _, testCase := range tests {
		t.Run(testCase.name, func(t *testing.T) {
			fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
			receipt := approveSchemaWikiC6SuccessorForReadTest(t, fixture)
			release, err := fixture.repository.GetRelease(
				fixture.ctx, fixture.scope, receipt.ReleaseID,
			)
			require.NoError(t, err)
			preparation, err := fixture.repository.GetReadyPreparation(
				fixture.ctx, fixture.scope, release.PreparationID,
			)
			require.NoError(t, err)
			testCase.mutate(preparation, receipt)
			require.NoError(t, fixture.db.Save(preparation).Error)

			_, err = fixture.service.ReadCurrentSchemaMember(
				fixture.ctx, fixture.principal, fixture.scope, "field:product_code",
			)
			require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
			pin := WikiReleasePinnedRead{
				scope: fixture.scope, releaseID: receipt.ReleaseID,
				activationEpoch: receipt.ActivationEpoch,
			}
			_, err = fixture.service.ReadPinnedSchemaMember(
				fixture.ctx, fixture.principal, pin, "field:product_code",
			)
			require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
		})
	}
}

func mustMarshalSchemaWikiC6Test(t *testing.T, value any) []byte {
	t.Helper()
	raw, err := json.Marshal(value)
	require.NoError(t, err)
	return raw
}

func TestSchemaWikiC6SuccessorFaultsRollBackPreparationReleaseMembersHeadAndReceipt(t *testing.T) {
	tests := []struct {
		name  string
		fault func(*WikiReleaseFaults)
	}{
		{
			name: "preparation fault",
			fault: func(faults *WikiReleaseFaults) {
				faults.Preparation = func() error { return errors.New("successor preparation fault") }
			},
		},
		{
			name: "CAS fault",
			fault: func(faults *WikiReleaseFaults) {
				faults.CAS = func() error { return errors.New("successor CAS fault") }
			},
		},
		{
			name: "receipt fault",
			fault: func(faults *WikiReleaseFaults) {
				faults.Receipt = func() error { return errors.New("successor receipt fault") }
			},
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
			firstDecision, firstAuthorization := fixture.approveBytes(t, nil, nil)
			_, firstReceipt, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
				fixture.ctx, fixture.principal, fixture.scope, fixture.key,
				firstDecision, firstAuthorization,
			)
			require.NoError(t, err)
			before, err := fixture.repository.CountState(fixture.ctx)
			require.NoError(t, err)
			test.fault(&fixture.authority.faults)

			secondDecision := fixture.decisionBytes(
				t, "approve", func(value *types.HumanBatchDecisionReceiptV1) {
					value.Nonce = "c6-decision-02"
				},
			)
			secondAuthorization := fixture.authorizationBytesForExpectedHead(
				t, secondDecision, firstReceipt.ReleaseID, firstReceipt.ActivationEpoch, nil,
			)
			_, _, err = fixture.service.DecideSchemaWikiFormalCandidatePreview(
				fixture.ctx, fixture.principal, fixture.scope, fixture.key,
				secondDecision, secondAuthorization,
			)
			require.Error(t, err)

			after, err := fixture.repository.CountState(fixture.ctx)
			require.NoError(t, err)
			require.Equal(t, before, after)
			head, err := fixture.repository.GetHead(fixture.ctx, fixture.scope)
			require.NoError(t, err)
			require.Equal(t, firstReceipt.ReleaseID, head.ActiveReleaseID)
			require.Equal(t, uint64(1), head.ActivationEpoch)
			_, err = fixture.repository.GetReceipt(fixture.ctx, fixture.scope, "c6-decision-02")
			require.ErrorIs(t, err, wikirepository.ErrWikiReleaseNotFound)
		})
	}
}

func schemaWikiC6PostgresJSONBObjectTextTest(t *testing.T, raw json.RawMessage) json.RawMessage {
	t.Helper()
	var fields map[string]json.RawMessage
	require.NoError(t, json.Unmarshal(raw, &fields))
	keys := make([]string, 0, len(fields))
	for key := range fields {
		keys = append(keys, key)
	}
	sort.Sort(sort.Reverse(sort.StringSlice(keys)))
	var encoded bytes.Buffer
	encoded.WriteByte('{')
	for index, key := range keys {
		if index > 0 {
			encoded.WriteByte(',')
		}
		keyRaw, err := json.Marshal(key)
		require.NoError(t, err)
		encoded.Write(keyRaw)
		encoded.WriteByte(':')
		encoded.Write(fields[key])
	}
	encoded.WriteByte('}')
	reordered := json.RawMessage(encoded.Bytes())
	require.JSONEq(t, string(raw), string(reordered))
	require.NotEqual(t, string(raw), string(reordered))
	return reordered
}

func TestSchemaWikiC6CurrentAndPinnedReopenPostgresJSONBManifest(t *testing.T) {
	fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
	rawDecision, rawAuthorization := fixture.approveBytes(t, nil, nil)
	_, activation, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		rawDecision, rawAuthorization,
	)
	require.NoError(t, err)
	before, err := fixture.repository.CountState(fixture.ctx)
	require.NoError(t, err)

	release, err := fixture.repository.GetRelease(fixture.ctx, fixture.scope, activation.ReleaseID)
	require.NoError(t, err)
	preparation, err := fixture.repository.GetReadyPreparation(
		fixture.ctx, fixture.scope, release.PreparationID,
	)
	require.NoError(t, err)
	var custody schemaWikiC6IsolatedCustodyV1
	require.NoError(t, json.Unmarshal(preparation.Manifest, &custody))
	for index := range custody.OrderedMembers {
		custody.OrderedMembers[index].Payload = schemaWikiC6PostgresJSONBObjectTextTest(
			t, custody.OrderedMembers[index].Payload,
		)
		preparation.Members[index].Payload = schemaWikiC6PostgresJSONBObjectTextTest(
			t, preparation.Members[index].Payload,
		)
	}
	preparation.Manifest, err = json.Marshal(custody)
	require.NoError(t, err)
	require.NoError(t, fixture.db.Model(&types.WikiReleasePreparation{}).
		Where("preparation_id = ?", preparation.ID).
		Select("manifest", "members").Updates(preparation).Error)
	var materialized []types.WikiReleaseMember
	require.NoError(t, fixture.db.Where("release_id = ?", release.ID).
		Order("id ASC").Find(&materialized).Error)
	for index := range materialized {
		materialized[index].Payload = schemaWikiC6PostgresJSONBObjectTextTest(
			t, materialized[index].Payload,
		)
		require.NoError(t, fixture.db.Model(&materialized[index]).
			Select("payload").Updates(&materialized[index]).Error)
	}
	roundTripped, err := fixture.repository.GetReadyPreparation(
		fixture.ctx, fixture.scope, release.PreparationID,
	)
	require.NoError(t, err)
	require.Equal(t, release.ManifestDigest, roundTripped.ManifestDigest)
	require.Equal(t, roundTripped.PreparationDigest, digestWikiReleasePreparation(roundTripped))
	require.NotEqual(t, roundTripped.ManifestDigest, digestWikiReleaseBytes(roundTripped.Manifest))

	currentMember, err := fixture.service.ReadCurrentSchemaMember(
		fixture.ctx, fixture.principal, fixture.scope, "field:product_code",
	)
	require.NoError(t, err)
	require.Equal(t, "field:product_code", currentMember.Member.LogicalSlug)
	pin, err := fixture.authority.BeginPinnedRead(fixture.ctx, fixture.principal, fixture.scope)
	require.NoError(t, err)
	pinnedMember, err := fixture.service.ReadPinnedSchemaMember(
		fixture.ctx, fixture.principal, pin, "field:product_code",
	)
	require.NoError(t, err)
	require.Equal(t, currentMember.Payload, pinnedMember.Payload)
	authorityPinnedMember, err := fixture.authority.ReadPinnedPage(
		fixture.ctx, fixture.principal, pin, "field:product_code",
	)
	require.NoError(t, err)
	require.NotEqual(t, pinnedMember.Payload, authorityPinnedMember.Payload)
	require.JSONEq(t, custody.OrderedMembers[8].Content, string(authorityPinnedMember.Payload))
	canonicalPage, err := types.CanonicalSchemaWikiMemberPayload("field", pinnedMember.Payload)
	require.NoError(t, err)
	require.Equal(t, canonicalPage, pinnedMember.Payload)
	var changedPayload map[string]any
	require.NoError(t, json.Unmarshal(custody.OrderedMembers[0].Payload, &changedPayload))
	changedPayload["quality_status"] = "CHANGED"
	custody.OrderedMembers[0].Payload, err = json.Marshal(changedPayload)
	require.NoError(t, err)
	changedManifest, err := json.Marshal(custody)
	require.NoError(t, err)
	require.NoError(t, fixture.db.Model(&types.WikiReleasePreparation{}).
		Where("preparation_id = ?", preparation.ID).
		Update("manifest", changedManifest).Error)
	_, err = fixture.service.ReadCurrentSchemaMember(
		fixture.ctx, fixture.principal, fixture.scope, "field:product_code",
	)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
	after, err := fixture.repository.CountState(fixture.ctx)
	require.NoError(t, err)
	require.Equal(t, before, after)
}

func TestSchemaWikiC6DecisionIdentityRepeatAndCASFailuresLeaveNoPartialR1(t *testing.T) {
	t.Run("identity drift", func(t *testing.T) {
		fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
		rawDecision, rawAuthorization := fixture.approveBytes(
			t, func(value *types.HumanBatchDecisionReceiptV1) {
				value.CandidateHash = strings.Repeat("9", 64)
			}, nil,
		)
		_, _, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key,
			rawDecision, rawAuthorization,
		)
		require.ErrorIs(t, err, ErrWikiReleaseInvalidAuthorization)
		state, countErr := fixture.repository.CountState(fixture.ctx)
		require.NoError(t, countErr)
		require.Equal(t, types.WikiReleaseStateCount{}, state)
	})

	t.Run("repeated approve", func(t *testing.T) {
		fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
		rawDecision, rawAuthorization := fixture.approveBytes(t, nil, nil)
		_, first, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key, rawDecision, rawAuthorization,
		)
		require.NoError(t, err)
		before, countErr := fixture.repository.CountState(fixture.ctx)
		require.NoError(t, countErr)
		_, repeated, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key, rawDecision, rawAuthorization,
		)
		require.NoError(t, err)
		require.Equal(t, first, repeated)
		after, countErr := fixture.repository.CountState(fixture.ctx)
		require.NoError(t, countErr)
		require.Equal(t, before, after)

		changedAuthorization := fixture.authorizationBytes(
			t, rawDecision, func(value *types.PublishAuthorizationV0) { value.ExpiresAt++ },
		)
		_, _, err = fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key,
			rawDecision, changedAuthorization,
		)
		require.ErrorIs(t, err, ErrWikiReleaseConflict)

		changedDecision := fixture.decisionBytes(
			t, "approve", func(value *types.HumanBatchDecisionReceiptV1) { value.ExpiresAt++ },
		)
		_, _, err = fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key,
			changedDecision, rawAuthorization,
		)
		require.ErrorIs(t, err, ErrWikiReleaseConflict)
		changedCandidateDecision := fixture.decisionBytes(
			t, "approve", func(value *types.HumanBatchDecisionReceiptV1) {
				value.CandidateHash = strings.Repeat("9", 64)
			},
		)
		_, _, err = fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key,
			changedCandidateDecision, rawAuthorization,
		)
		require.ErrorIs(t, err, ErrWikiReleaseConflict)
		_, _, err = fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key,
			fixture.decisionBytes(t, "reject", nil), nil,
		)
		require.ErrorIs(t, err, ErrWikiReleaseConflict)
		final, countErr := fixture.repository.CountState(fixture.ctx)
		require.NoError(t, countErr)
		require.Equal(t, before, final)
	})

	t.Run("existing target Wiki head", func(t *testing.T) {
		fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
		otherScope := fixture.scope
		otherScope.SpaceID = "space-c6-existing"
		require.NoError(t, fixture.db.Create(&types.WikiReleaseHead{
			ID: "10003:space-c6-existing:wiki-isolated-c6", WikiReleaseScope: otherScope,
			ActiveReleaseID: "release-existing", ActivationEpoch: 7, UpdatedAt: fixture.now,
		}).Error)
		rawDecision, rawAuthorization := fixture.approveBytes(t, nil, nil)
		_, _, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key,
			rawDecision, rawAuthorization,
		)
		require.ErrorIs(t, err, ErrWikiReleaseConflict)
		state, countErr := fixture.repository.CountState(fixture.ctx)
		require.NoError(t, countErr)
		require.Equal(t, types.WikiReleaseStateCount{Heads: 1}, state)
	})

	t.Run("activation preparation fault", func(t *testing.T) {
		fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{Preparation: func() error { return errors.New("c6 activation fault") }})
		rawDecision, rawAuthorization := fixture.approveBytes(t, nil, nil)
		_, _, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key,
			rawDecision, rawAuthorization,
		)
		require.Error(t, err)
		state, countErr := fixture.repository.CountState(fixture.ctx)
		require.NoError(t, countErr)
		require.Equal(t, types.WikiReleaseStateCount{}, state)
	})

	t.Run("CAS transaction fault", func(t *testing.T) {
		fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{CAS: func() error { return errors.New("c6 CAS fault") }})
		rawDecision, rawAuthorization := fixture.approveBytes(t, nil, nil)
		_, _, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key,
			rawDecision, rawAuthorization,
		)
		require.Error(t, err)
		state, countErr := fixture.repository.CountState(fixture.ctx)
		require.NoError(t, countErr)
		require.Equal(t, types.WikiReleaseStateCount{}, state)
	})

	t.Run("receipt transaction fault", func(t *testing.T) {
		fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{Receipt: func() error { return errors.New("c6 receipt fault") }})
		rawDecision, rawAuthorization := fixture.approveBytes(t, nil, nil)
		_, _, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key,
			rawDecision, rawAuthorization,
		)
		require.Error(t, err)
		state, countErr := fixture.repository.CountState(fixture.ctx)
		require.NoError(t, countErr)
		require.Equal(t, types.WikiReleaseStateCount{}, state)

		authorizationExpired := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
		validDecision := authorizationExpired.decisionBytes(
			t, "approve", func(value *types.HumanBatchDecisionReceiptV1) {
				value.ExpiresAt = authorizationExpired.now.Add(3 * time.Hour).Unix()
			},
		)
		expiredAuthorization := authorizationExpired.authorizationBytes(t, validDecision, nil)
		authorizationExpired.authority.now = func() time.Time {
			return authorizationExpired.now.Add(2 * time.Hour)
		}
		_, _, err = authorizationExpired.service.DecideSchemaWikiFormalCandidatePreview(
			authorizationExpired.ctx, authorizationExpired.principal, authorizationExpired.scope,
			authorizationExpired.key, validDecision, expiredAuthorization,
		)
		require.ErrorIs(t, err, ErrWikiReleaseInvalidAuthorization)
		state, countErr = authorizationExpired.repository.CountState(authorizationExpired.ctx)
		require.NoError(t, countErr)
		require.Equal(t, types.WikiReleaseStateCount{}, state)
	})
}

func TestSchemaWikiC6ExactRetryRemainsIdempotentAfterDecisionAndAuthorizationExpiry(t *testing.T) {
	t.Run("exact canonical retry", func(t *testing.T) {
		fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
		rawDecision, rawAuthorization := fixture.approveBytes(t, nil, nil)
		_, first, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key,
			rawDecision, rawAuthorization,
		)
		require.NoError(t, err)
		before, err := fixture.repository.CountState(fixture.ctx)
		require.NoError(t, err)
		fixture.authority.now = func() time.Time { return fixture.now.Add(2 * time.Hour) }

		_, repeated, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key,
			rawDecision, rawAuthorization,
		)
		require.NoError(t, err)
		require.Equal(t, first, repeated)
		after, err := fixture.repository.CountState(fixture.ctx)
		require.NoError(t, err)
		require.Equal(t, before, after)
	})

	t.Run("same nonce changed canonical bytes", func(t *testing.T) {
		fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
		rawDecision, rawAuthorization := fixture.approveBytes(t, nil, nil)
		_, _, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key,
			rawDecision, rawAuthorization,
		)
		require.NoError(t, err)
		before, err := fixture.repository.CountState(fixture.ctx)
		require.NoError(t, err)
		fixture.authority.now = func() time.Time { return fixture.now.Add(2 * time.Hour) }

		changedDecision := fixture.decisionBytes(
			t, "approve", func(value *types.HumanBatchDecisionReceiptV1) { value.ExpiresAt++ },
		)
		_, _, err = fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key,
			changedDecision, rawAuthorization,
		)
		require.ErrorIs(t, err, ErrWikiReleaseConflict)
		changedAuthorization := fixture.authorizationBytes(
			t, rawDecision, func(value *types.PublishAuthorizationV0) { value.ExpiresAt++ },
		)
		_, _, err = fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key,
			rawDecision, changedAuthorization,
		)
		require.ErrorIs(t, err, ErrWikiReleaseConflict)
		after, err := fixture.repository.CountState(fixture.ctx)
		require.NoError(t, err)
		require.Equal(t, before, after)
	})

	t.Run("new expired request", func(t *testing.T) {
		fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
		rawDecision, rawAuthorization := fixture.approveBytes(t, nil, nil)
		fixture.authority.now = func() time.Time { return fixture.now.Add(2 * time.Hour) }
		_, _, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
			fixture.ctx, fixture.principal, fixture.scope, fixture.key,
			rawDecision, rawAuthorization,
		)
		require.ErrorIs(t, err, ErrWikiReleaseInvalidAuthorization)
		state, countErr := fixture.repository.CountState(fixture.ctx)
		require.NoError(t, countErr)
		require.Equal(t, types.WikiReleaseStateCount{}, state)
	})
}

func TestSchemaWikiC6PinnedReadRequiresItsReadyPreparation(t *testing.T) {
	fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
	rawDecision, rawAuthorization := fixture.approveBytes(t, nil, nil)
	_, activation, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key,
		rawDecision, rawAuthorization,
	)
	require.NoError(t, err)
	require.NotNil(t, activation)
	pin, err := fixture.authority.BeginPinnedRead(fixture.ctx, fixture.principal, fixture.scope)
	require.NoError(t, err)
	release, err := fixture.repository.GetRelease(fixture.ctx, fixture.scope, activation.ReleaseID)
	require.NoError(t, err)
	require.NoError(t, fixture.db.Where("preparation_id = ?", release.PreparationID).Delete(&types.WikiReleasePreparation{}).Error)
	_, err = fixture.authority.ReadPinnedPage(
		fixture.ctx, fixture.principal, pin, "root:ping-an-e-sheng-bao@596-1",
	)
	require.ErrorIs(t, err, ErrWikiReleaseNotFound)
}

func TestSchemaWikiC6SchemaReadRejectsChangedIsolatedCustody(t *testing.T) {
	fixture := newSchemaWikiC6DecisionFixture(t, WikiReleaseFaults{})
	rawDecision, rawAuthorization := fixture.approveBytes(t, nil, nil)
	_, activation, err := fixture.service.DecideSchemaWikiFormalCandidatePreview(
		fixture.ctx, fixture.principal, fixture.scope, fixture.key, rawDecision, rawAuthorization,
	)
	require.NoError(t, err)
	release, err := fixture.repository.GetRelease(fixture.ctx, fixture.scope, activation.ReleaseID)
	require.NoError(t, err)
	preparation, err := fixture.repository.GetReadyPreparation(
		fixture.ctx, fixture.scope, release.PreparationID,
	)
	require.NoError(t, err)
	var custody schemaWikiC6IsolatedCustodyV1
	require.NoError(t, json.Unmarshal(preparation.Manifest, &custody))
	custody.ExperimentID = "changed-experiment"
	changedManifest, err := json.Marshal(custody)
	require.NoError(t, err)
	preparation.Manifest = changedManifest
	preparation.ManifestDigest = digestWikiReleaseBytes(changedManifest)
	preparation.PreparationDigest = digestWikiReleasePreparation(preparation)
	require.NoError(t, fixture.db.Save(preparation).Error)
	require.NoError(t, fixture.db.Model(&types.WikiRelease{}).
		Where("release_id = ?", release.ID).
		Update("manifest_digest", preparation.ManifestDigest).Error)
	_, err = fixture.service.ReadCurrentSchemaMember(
		fixture.ctx, fixture.principal, fixture.scope, "field:product_code",
	)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
}
