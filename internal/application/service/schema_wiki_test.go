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
	"io"
	"os"
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

const schemaWikiReleaseVectorPath = "testdata/schema_wiki_release_596_1_vector.json"
const schemaWikiReleaseVectorSHA256 = "6783e3312199378a51065872278961f10c0e0f6510648e2ff1ce18823f10e6be"

var schemaWikiReviewSeed = sha256.Sum256([]byte("schema-wiki-review-test-key.v1"))
var schemaWikiPublishSeed = sha256.Sum256([]byte("schema-wiki-publish-test-key.v1"))
var schemaWikiQualityGateSeed = sha256.Sum256([]byte("schema67-golden-quality-gate-test-key.v1"))

type schemaWikiHumanVerifierSpy struct {
	inner        HumanBatchDecisionVerifier
	calls        int
	beforeVerify func(*types.HumanBatchDecisionReceiptV1)
}

func (s *schemaWikiHumanVerifierSpy) Verify(receipt *types.HumanBatchDecisionReceiptV1) error {
	s.calls++
	if s.beforeVerify != nil {
		s.beforeVerify(receipt)
	}
	return s.inner.Verify(receipt)
}

type schemaWikiReleaseAuthorityVectorV1 struct {
	CandidateEvidenceAuthority types.Schema67CandidateEvidenceAuthorityV1 `json:"candidate_evidence_authority"`
	Release                    types.KnowledgeWikiReleaseV1               `json:"release"`
}

func loadSchemaWikiReleaseVector(t *testing.T) schemaWikiReleaseAuthorityVectorV1 {
	t.Helper()
	raw, err := os.ReadFile(schemaWikiReleaseVectorPath)
	require.NoError(t, err)
	sum := sha256.Sum256(raw)
	require.Equal(t, schemaWikiReleaseVectorSHA256, hex.EncodeToString(sum[:]))
	var vector schemaWikiReleaseAuthorityVectorV1
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	require.NoError(t, decoder.Decode(&vector))
	var trailing any
	require.ErrorIs(t, decoder.Decode(&trailing), io.EOF)
	var canonicalTree map[string]any
	require.NoError(t, json.Unmarshal(raw, &canonicalTree))
	canonical, err := json.Marshal(canonicalTree)
	require.NoError(t, err)
	require.Equal(t, bytes.TrimSuffix(raw, []byte("\n")), canonical,
		"frozen vector must be canonical JSON with only its frozen final newline")
	typed, err := json.Marshal(vector)
	require.NoError(t, err)
	var typedTree map[string]any
	require.NoError(t, json.Unmarshal(typed, &typedTree))
	require.Equal(t, canonicalTree, typedTree, "typed vector roundtrip must preserve every field")
	require.NoError(t, types.ValidateKnowledgeWikiRelease(vector.Release, vector.Release.SchemaPack))
	require.NoError(t, types.ValidateSchema67CandidateEvidenceAuthorityV1(
		vector.CandidateEvidenceAuthority, vector.Release,
	))
	require.Len(t, vector.Release.Members, 75)
	require.Len(t, vector.CandidateEvidenceAuthority.SourceAuthorities, 3)
	require.Len(t, vector.CandidateEvidenceAuthority.JoinReceipts, 111)
	return vector
}

func schemaWikiTestHash(t *testing.T, objectType string, payload any) string {
	t.Helper()
	canonical, err := json.Marshal(payload)
	require.NoError(t, err)
	preimage := append([]byte("schema-wiki-canonical.v1\x00"+objectType+"\x00"), canonical...)
	sum := sha256.Sum256(preimage)
	return hex.EncodeToString(sum[:])
}

func schemaWikiDifferentSHA(value string) string {
	if len(value) == 0 || value[0] != '0' {
		return "0" + value[1:]
	}
	return "1" + value[1:]
}

func schemaWikiTestHashWithout(t *testing.T, objectType string, value any, key string) string {
	t.Helper()
	raw := mustSchemaWikiJSON(t, value)
	var payload map[string]any
	require.NoError(t, json.Unmarshal(raw, &payload))
	delete(payload, key)
	return schemaWikiTestHash(t, objectType, payload)
}

func schemaWikiTestCanonicalJSON(t *testing.T, value any) json.RawMessage {
	t.Helper()
	raw := mustSchemaWikiJSON(t, value)
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var tree any
	require.NoError(t, decoder.Decode(&tree))
	var trailing any
	require.ErrorIs(t, decoder.Decode(&trailing), io.EOF)
	var out bytes.Buffer
	encoder := json.NewEncoder(&out)
	encoder.SetEscapeHTML(false)
	require.NoError(t, encoder.Encode(tree))
	return bytes.TrimSuffix(out.Bytes(), []byte("\n"))
}

func cloneSchemaWikiEvidenceAuthority(
	t *testing.T,
	authority types.Schema67CandidateEvidenceAuthorityV1,
) types.Schema67CandidateEvidenceAuthorityV1 {
	t.Helper()
	var clone types.Schema67CandidateEvidenceAuthorityV1
	require.NoError(t, json.Unmarshal(mustSchemaWikiJSON(t, authority), &clone))
	return clone
}

func resealSchemaWikiEvidenceAuthority(
	t *testing.T,
	authority *types.Schema67CandidateEvidenceAuthorityV1,
) {
	t.Helper()
	for index := range authority.JoinReceipts {
		receipt := &authority.JoinReceipts[index]
		receipt.ReceiptSHA256 = ""
		digest, err := types.ComputeSchema67CitationAuthorityJoinReceiptSHA256(*receipt)
		require.NoError(t, err)
		receipt.ReceiptSHA256 = digest
	}
	authority.AuthoritySHA256 = ""
	digest, err := types.ComputeSchema67CandidateEvidenceAuthoritySHA256(*authority)
	require.NoError(t, err)
	authority.AuthoritySHA256 = digest
}

func forgeSchemaWikiDuplicateCitationID(
	t *testing.T,
	release types.KnowledgeWikiReleaseV1,
) (types.KnowledgeWikiReleaseV1, types.SchemaWikiReviewBundleV1) {
	t.Helper()
	memberIndex := -1
	var page types.SchemaFieldPageV1
	for index, member := range release.Members {
		if member.MemberKind != "field" {
			continue
		}
		require.NoError(t, json.Unmarshal(member.Payload, &page))
		if len(page.Citations) > 0 {
			memberIndex = index
			break
		}
	}
	require.NotEqual(t, -1, memberIndex)
	duplicate := page.Citations[0]
	duplicate.LocatorRef += "-duplicate"
	duplicate.QuoteSnapshot = "Distinct exact quote for duplicate identifier"
	duplicate.QuoteSHA256 = schemaWikiTestHash(
		t, "schema-wiki-text.v1", map[string]any{"text": duplicate.QuoteSnapshot},
	)
	duplicate.ContentSnapshotSHA256 = strings.Repeat("b", 64)
	duplicate.CitationSHA256 = ""
	duplicate.CitationSHA256 = schemaWikiTestHashWithout(
		t, duplicate.Contract, duplicate, "citation_sha256",
	)
	require.Equal(t, page.Citations[0].CitationID, duplicate.CitationID)
	require.NotEqual(t, page.Citations[0].CitationSHA256, duplicate.CitationSHA256)
	page.Citations = append(page.Citations, duplicate)
	page.FieldPageSHA256 = ""
	page.FieldPageSHA256 = schemaWikiTestHashWithout(
		t, page.Contract, page, "field_page_sha256",
	)
	pageRaw := schemaWikiTestCanonicalJSON(t, page)
	release.Members[memberIndex].Payload = pageRaw
	release.Members[memberIndex].PayloadSHA256 = page.FieldPageSHA256
	release.Members[memberIndex].MemberDigest = ""
	release.Members[memberIndex].MemberDigest = schemaWikiTestHashWithout(
		t, release.Members[memberIndex].Contract,
		release.Members[memberIndex],
		"member_digest",
	)

	memberDigestByRef := make(map[string]string, len(release.Members))
	for _, member := range release.Members {
		memberDigestByRef[member.MemberRef] = member.MemberDigest
	}
	for index := range release.CitationBindings {
		binding := &release.CitationBindings[index]
		binding.MemberDigest = memberDigestByRef[binding.LogicalMemberRef]
		binding.BindingSHA256 = ""
		binding.BindingSHA256 = schemaWikiTestHashWithout(
			t, binding.Contract, *binding, "binding_sha256",
		)
	}
	duplicateBinding := types.CitationMemberBindingV1{
		Contract:         "citation-member-binding.v1",
		CitationSHA256:   duplicate.CitationSHA256,
		LogicalMemberRef: release.Members[memberIndex].MemberRef,
		MemberDigest:     release.Members[memberIndex].MemberDigest,
	}
	duplicateBinding.BindingSHA256 = schemaWikiTestHashWithout(
		t, duplicateBinding.Contract, duplicateBinding, "binding_sha256",
	)
	release.CitationBindings = append(release.CitationBindings, duplicateBinding)
	sort.Slice(release.CitationBindings, func(left, right int) bool {
		leftKey := release.CitationBindings[left].LogicalMemberRef + "\x00" +
			release.CitationBindings[left].CitationSHA256
		rightKey := release.CitationBindings[right].LogicalMemberRef + "\x00" +
			release.CitationBindings[right].CitationSHA256
		return leftKey < rightKey
	})
	release.ManifestDigest = schemaWikiTestHash(t, "schema-wiki-manifest.v1", map[string]any{
		"members": release.Members, "citation_bindings": release.CitationBindings,
	})
	release.ReleaseSHA256 = ""
	release.ReleaseSHA256 = schemaWikiTestHashWithout(
		t, release.Contract, release, "release_sha256",
	)

	memberDigests := make([]string, len(release.Members))
	for index, member := range release.Members {
		memberDigests[index] = member.MemberDigest
	}
	bindingDigests := make([]string, len(release.CitationBindings))
	for index, binding := range release.CitationBindings {
		bindingDigests[index] = binding.BindingSHA256
	}
	bundle := types.SchemaWikiReviewBundleV1{
		Contract:              "schema-wiki-review-bundle.v1",
		CandidateSHA256:       release.CandidateSHA256,
		ReleaseSHA256:         release.ReleaseSHA256,
		ManifestDigest:        release.ManifestDigest,
		OrderedMemberDigests:  memberDigests,
		OrderedBindingSHA256s: bindingDigests,
		ReviewPolicySHA256:    release.ReviewPolicySHA256,
		DomainSHA256:          release.Domain.DomainSHA256,
		TaxonomySHA256:        release.Taxonomy.TaxonomySHA256,
		SchemaPackSHA256:      release.SchemaPack.SchemaPackSHA256,
		EntityID:              release.Entity.EntityID,
		VersionID:             release.EntityVersion.VersionID,
	}
	bundle.ReviewBundleSHA256 = schemaWikiTestHashWithout(
		t, bundle.Contract, bundle, "review_bundle_sha256",
	)
	return release, bundle
}

func schemaWikiReviewBundle(
	t *testing.T,
	release types.KnowledgeWikiReleaseV1,
	evidenceAuthority types.Schema67CandidateEvidenceAuthorityV1,
) types.SchemaWikiReviewBundleV1 {
	t.Helper()
	memberDigests := make([]string, len(release.Members))
	for index, member := range release.Members {
		memberDigests[index] = member.MemberDigest
	}
	bindingDigests := make([]string, len(release.CitationBindings))
	for index, binding := range release.CitationBindings {
		bindingDigests[index] = binding.BindingSHA256
	}
	fieldDecisions := make([]string, 67)
	for index := range fieldDecisions {
		fieldDecisions[index] = strings.Repeat("d", 64)
	}
	metricReceipts := make([]string, 15)
	for index := range metricReceipts {
		metricReceipts[index] = strings.Repeat("e", 64)
	}
	qualityPayload := map[string]any{
		"contract": "schema67-golden-quality-gate-receipt.v1", "status": "PASS",
		"product_version_id": "596-1", "candidate_sha256": release.CandidateSHA256,
		"candidate_evidence_authority_sha256": evidenceAuthority.AuthoritySHA256,
		"golden_set_sha256":                   strings.Repeat("a", 64), "golden_version": "test.v1",
		"evaluator_identity_sha256":      "525f208a404d996caf5f806a9b065ea5af81f0b7d2996b9b50c25e4878400808",
		"metric_policy_sha256":           "5d2ffd2379f9f1902a0ab834de6e1e8e593d400115878b9c565331b121d6f0d7",
		"ordered_field_decision_sha256s": fieldDecisions,
		"metric_receipt_sha256s":         metricReceipts,
		"private_dossier_sha256":         strings.Repeat("b", 64),
		"public_aggregate_sha256":        strings.Repeat("c", 64),
		"golden_approval_sha256s":        []string{strings.Repeat("1", 64), strings.Repeat("2", 64)},
		"signer_key_id":                  "schema67-golden-evaluator-test-key",
	}
	quality := types.Schema67GoldenQualityGateReceiptV1{
		Contract: qualityPayload["contract"].(string), Status: "PASS", ProductVersionID: "596-1",
		CandidateSHA256:                  release.CandidateSHA256,
		CandidateEvidenceAuthoritySHA256: evidenceAuthority.AuthoritySHA256,
		GoldenSetSHA256:                  strings.Repeat("a", 64), GoldenVersion: "test.v1",
		EvaluatorIdentitySHA256:     qualityPayload["evaluator_identity_sha256"].(string),
		MetricPolicySHA256:          qualityPayload["metric_policy_sha256"].(string),
		OrderedFieldDecisionSHA256s: fieldDecisions, MetricReceiptSHA256s: metricReceipts,
		PrivateDossierSHA256:  strings.Repeat("b", 64),
		PublicAggregateSHA256: strings.Repeat("c", 64),
		GoldenApprovalSHA256s: []string{strings.Repeat("1", 64), strings.Repeat("2", 64)},
		SignerKeyID:           "schema67-golden-evaluator-test-key",
	}
	qualityPrivateKey := ed25519.NewKeyFromSeed(schemaWikiQualityGateSeed[:])
	unsigned, err := CanonicalSchema67GoldenQualityGateReceiptV1(&quality, false)
	require.NoError(t, err)
	quality.Signature = base64.RawURLEncoding.EncodeToString(ed25519.Sign(qualityPrivateKey, unsigned))
	require.Equal(t,
		"kBi7x4LeXeVWagrV18w2xkmKci-4Rq0yvC9C38_tpMLwsaMCTezugc0PGsYhd5f4KRrDfdAQqzUeKGtnTmFLDA",
		quality.Signature,
		"Go signing preimage must remain byte-identical to the frozen Python vector",
	)
	qualityPayload["signature"] = quality.Signature
	quality.ReceiptSHA256 = schemaWikiTestHash(t, "schema67-golden-quality-gate-receipt.v1", qualityPayload)
	require.NoError(t, types.ValidateSchema67GoldenQualityGateReceiptV1(quality))
	bundle := types.SchemaWikiReviewBundleV1{
		Contract:              "schema-wiki-review-bundle.v1",
		CandidateSHA256:       release.CandidateSHA256,
		ReleaseSHA256:         release.ReleaseSHA256,
		ManifestDigest:        release.ManifestDigest,
		OrderedMemberDigests:  memberDigests,
		OrderedBindingSHA256s: bindingDigests,
		ReviewPolicySHA256:    release.ReviewPolicySHA256,
		DomainSHA256:          release.Domain.DomainSHA256,
		TaxonomySHA256:        release.Taxonomy.TaxonomySHA256,
		SchemaPackSHA256:      release.SchemaPack.SchemaPackSHA256,
		EntityID:              release.Entity.EntityID,
		VersionID:             release.EntityVersion.VersionID,
		QualityGateReceipt:    quality,
	}
	bundle.ReviewBundleSHA256 = schemaWikiTestHashWithout(
		t, bundle.Contract, bundle, "review_bundle_sha256",
	)
	require.NoError(t, types.ValidateSchemaWikiReviewBundle(bundle, release))
	return bundle
}

func schemaWikiDecision(
	t *testing.T,
	scope types.WikiReleaseScope,
	release types.KnowledgeWikiReleaseV1,
	bundle types.SchemaWikiReviewBundleV1,
) (types.HumanBatchDecisionReceiptV1, string) {
	t.Helper()
	receipt := types.HumanBatchDecisionReceiptV1{
		Version:          "1",
		Decision:         "approve",
		PrincipalID:      "reviewer",
		WikiReleaseScope: scope,
		CandidateHash:    release.CandidateSHA256,
		HumanBatchHash:   bundle.ReviewBundleSHA256,
		ReviewPolicyHash: release.ReviewPolicySHA256,
		IssuedAt:         time.Now().Add(-time.Minute).Unix(),
		ExpiresAt:        time.Now().Add(time.Hour).Unix(),
		Nonce:            "schema-wiki-review-596-1",
		SignerKeyID:      "named-human-review-key",
	}
	privateKey := ed25519.NewKeyFromSeed(schemaWikiReviewSeed[:])
	unsigned, err := CanonicalHumanBatchDecisionReceiptV1(&receipt, false)
	require.NoError(t, err)
	receipt.Signature = base64.RawURLEncoding.EncodeToString(ed25519.Sign(privateKey, unsigned))
	raw, err := CanonicalHumanBatchDecisionReceiptV1(&receipt, true)
	require.NoError(t, err)
	sum := sha256.Sum256(raw)
	return receipt, hex.EncodeToString(sum[:])
}

func schemaWikiDecisionVerifier() *schemaWikiHumanVerifierSpy {
	privateKey := ed25519.NewKeyFromSeed(schemaWikiReviewSeed[:])
	return &schemaWikiHumanVerifierSpy{inner: NewEd25519HumanBatchDecisionVerifier(
		map[string]ed25519.PublicKey{
			"named-human-review-key": privateKey.Public().(ed25519.PublicKey),
		},
	)}
}

func schemaWikiDecisionAuthority(verifier HumanBatchDecisionVerifier) *WikiReleaseService {
	return NewWikiReleaseService(
		nil,
		nil,
		nil,
		WikiReleaseServiceOptions{
			Now:                   time.Now,
			HumanDecisionVerifier: verifier,
		},
	)
}

type schemaWikiDraftFixture struct {
	PreparationID        string
	Release              types.KnowledgeWikiReleaseV1
	EvidenceAuthority    types.Schema67CandidateEvidenceAuthorityV1
	ReviewBundle         types.SchemaWikiReviewBundleV1
	HumanDecision        types.HumanBatchDecisionReceiptV1
	ReviewDecisionDigest string
	Members              []types.WikiReleaseMemberSnapshot
}

func resignSchemaWikiDecision(t *testing.T, draft *schemaWikiDraftFixture) {
	t.Helper()
	privateKey := ed25519.NewKeyFromSeed(schemaWikiReviewSeed[:])
	draft.HumanDecision.Signature = ""
	unsigned, err := CanonicalHumanBatchDecisionReceiptV1(&draft.HumanDecision, false)
	require.NoError(t, err)
	draft.HumanDecision.Signature = base64.RawURLEncoding.EncodeToString(
		ed25519.Sign(privateKey, unsigned),
	)
	raw, err := CanonicalHumanBatchDecisionReceiptV1(&draft.HumanDecision, true)
	require.NoError(t, err)
	sum := sha256.Sum256(raw)
	draft.ReviewDecisionDigest = hex.EncodeToString(sum[:])
}

func schemaWikiPreparedMembers(
	t *testing.T,
	release types.KnowledgeWikiReleaseV1,
) []types.WikiReleaseMemberSnapshot {
	t.Helper()
	members := make([]types.WikiReleaseMemberSnapshot, len(release.Members))
	for index, member := range release.Members {
		members[index] = types.WikiReleaseMemberSnapshot{
			Kind:         member.MemberKind,
			LogicalSlug:  member.MemberRef,
			RevisionID:   release.ReleaseSHA256,
			MemberDigest: member.MemberDigest,
			Title:        member.MemberRef,
			Payload:      append(json.RawMessage(nil), member.Payload...),
		}
		require.Equal(t, []byte(member.Payload), []byte(members[index].Payload),
			"stored Draft member must carry the canonical typed page bytes, not its descriptor")
	}
	return members
}

func schemaWikiPostgresJSONBText(t *testing.T, raw []byte) []byte {
	t.Helper()
	var value any
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	require.NoError(t, decoder.Decode(&value))
	var trailing any
	require.ErrorIs(t, decoder.Decode(&trailing), io.EOF)
	var out bytes.Buffer
	writeSchemaWikiJSONBValue(t, &out, value)
	return out.Bytes()
}

func writeSchemaWikiJSONBValue(t *testing.T, out *bytes.Buffer, value any) {
	t.Helper()
	switch typed := value.(type) {
	case map[string]any:
		keys := make([]string, 0, len(typed))
		for key := range typed {
			keys = append(keys, key)
		}
		sort.Sort(sort.Reverse(sort.StringSlice(keys)))
		out.WriteString("{ ")
		for index, key := range keys {
			if index > 0 {
				out.WriteString(", ")
			}
			encodedKey, err := json.Marshal(key)
			require.NoError(t, err)
			out.Write(encodedKey)
			out.WriteString(" : ")
			writeSchemaWikiJSONBValue(t, out, typed[key])
		}
		out.WriteString(" }")
	case []any:
		out.WriteString("[ ")
		for index, item := range typed {
			if index > 0 {
				out.WriteString(", ")
			}
			writeSchemaWikiJSONBValue(t, out, item)
		}
		out.WriteString(" ]")
	default:
		encoded, err := json.Marshal(typed)
		require.NoError(t, err)
		out.Write(encoded)
	}
}

func normalizeSchemaWikiPreparationAsPostgresJSONB(
	t *testing.T,
	fixture *schemaWikiPrepareFixture,
	preparationID string,
) {
	t.Helper()
	stored := fixture.storedPreparation(t, preparationID)
	normalizedManifest := schemaWikiPostgresJSONBText(t, stored.Manifest)
	normalizedMembers := schemaWikiPostgresJSONBText(t, mustSchemaWikiJSON(t, stored.Members))
	require.NoError(t, fixture.db.Exec(
		"UPDATE wiki_release_preparations SET manifest = ?, members = ? WHERE preparation_id = ?",
		string(normalizedManifest), string(normalizedMembers), preparationID,
	).Error)
}

func normalizeSchemaWikiReleaseMembersAsPostgresJSONB(
	t *testing.T,
	fixture *schemaWikiPrepareFixture,
	releaseID string,
) {
	t.Helper()
	var members []types.WikiReleaseMember
	require.NoError(t, fixture.db.Where("release_id = ?", releaseID).Find(&members).Error)
	require.Len(t, members, 75)
	for _, member := range members {
		require.NoError(t, fixture.db.Exec(
			"UPDATE wiki_release_members SET payload = ? WHERE id = ?",
			string(schemaWikiPostgresJSONBText(t, member.Payload)), member.ID,
		).Error)
	}
}

func mustSchemaWikiJSON(t *testing.T, value any) []byte {
	t.Helper()
	raw, err := json.Marshal(value)
	require.NoError(t, err)
	return raw
}

func schemaWikiReviewedDraft(
	t *testing.T,
) (types.WikiReleasePrincipal, types.WikiReleaseScope, schemaWikiDraftFixture) {
	t.Helper()
	vector := loadSchemaWikiReleaseVector(t)
	release := vector.Release
	scope := types.WikiReleaseScope{
		TenantID: 10003,
		SpaceID:  "space-596-1",
		RawKBID:  "raw-kb-596-1",
		WikiKBID: "wiki-kb-596-1",
	}
	bundle := schemaWikiReviewBundle(t, release, vector.CandidateEvidenceAuthority)
	decision, decisionDigest := schemaWikiDecision(t, scope, release, bundle)
	return types.WikiReleasePrincipal{
			ID:       "reviewer",
			TenantID: 10003,
			SpaceID:  "space-596-1",
		}, scope, schemaWikiDraftFixture{
			PreparationID:        "schema-wiki-preparation-596-1",
			Release:              release,
			EvidenceAuthority:    vector.CandidateEvidenceAuthority,
			ReviewBundle:         bundle,
			HumanDecision:        decision,
			ReviewDecisionDigest: decisionDigest,
			Members:              schemaWikiPreparedMembers(t, release),
		}
}

func schemaWikiHumanContext(
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	role types.TenantRole,
) context.Context {
	ctx := context.WithValue(context.Background(), types.UserIDContextKey, principal.ID)
	ctx = context.WithValue(ctx, types.TenantIDContextKey, principal.TenantID)
	ctx = context.WithValue(ctx, types.TenantRoleContextKey, role)
	return SealWikiReleaseAccess(ctx, principal, scope)
}

type schemaWikiPrepareFixture struct {
	db                *gorm.DB
	authority         *WikiReleaseService
	verifier          *schemaWikiHumanVerifierSpy
	adapter           *SchemaWikiService
	ctx               context.Context
	publishPrivateKey ed25519.PrivateKey
}

func newSchemaWikiPrepareFixture(
	t *testing.T,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
) *schemaWikiPrepareFixture {
	t.Helper()
	db, err := gorm.Open(
		sqlite.Open("file:"+t.Name()+"?mode=memory&cache=shared"),
		&gorm.Config{},
	)
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(
		&types.WikiReleasePreparation{}, &types.WikiRelease{},
		&types.WikiReleaseMember{}, &types.WikiReleaseHead{},
		&types.WikiReleaseReceipt{},
	))
	verifier := schemaWikiDecisionVerifier()
	publishPrivateKey := ed25519.NewKeyFromSeed(schemaWikiPublishSeed[:])
	authority := NewWikiReleaseService(
		wikirepository.NewWikiReleaseRepository(db),
		NewContextWikiReleaseAccessVerifier(),
		NewEd25519WikiReleaseAuthorizationVerifier(map[string]ed25519.PublicKey{
			"signer-1": publishPrivateKey.Public().(ed25519.PublicKey),
		}),
		WikiReleaseServiceOptions{
			Now: time.Now, HumanDecisionVerifier: verifier,
			QualityGateReceiptVerifier: NewEd25519Schema67GoldenQualityGateReceiptVerifier(
				map[string]ed25519.PublicKey{
					"schema67-golden-evaluator-test-key": ed25519.NewKeyFromSeed(
						schemaWikiQualityGateSeed[:],
					).Public().(ed25519.PublicKey),
				},
			),
		},
	)
	return &schemaWikiPrepareFixture{
		db: db, authority: authority, verifier: verifier,
		adapter:           NewSchemaWikiService(authority, nil),
		ctx:               schemaWikiHumanContext(principal, scope, types.TenantRoleAdmin),
		publishPrivateKey: publishPrivateKey,
	}
}

func (fixture *schemaWikiPrepareFixture) storedCount(t *testing.T) int64 {
	t.Helper()
	var count int64
	require.NoError(t, fixture.db.Model(&types.WikiReleasePreparation{}).Count(&count).Error)
	return count
}

func (fixture *schemaWikiPrepareFixture) storedPreparation(
	t *testing.T,
	preparationID string,
) types.WikiReleasePreparation {
	t.Helper()
	var preparation types.WikiReleasePreparation
	require.NoError(t, fixture.db.First(
		&preparation, "preparation_id = ?", preparationID,
	).Error)
	return preparation
}

func (fixture *schemaWikiPrepareFixture) stateCounts(
	t *testing.T,
) (heads int64, releases int64, receipts int64) {
	t.Helper()
	require.NoError(t, fixture.db.Model(&types.WikiReleaseHead{}).Count(&heads).Error)
	require.NoError(t, fixture.db.Model(&types.WikiRelease{}).Count(&releases).Error)
	require.NoError(t, fixture.db.Model(&types.WikiReleaseReceipt{}).Count(&receipts).Error)
	return heads, releases, receipts
}

func createSchemaWikiDraft(
	t *testing.T,
	fixture *schemaWikiPrepareFixture,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	draft schemaWikiDraftFixture,
) *types.WikiReleasePreparation {
	t.Helper()
	created, err := fixture.adapter.CreateSchemaDraft(
		fixture.ctx,
		principal,
		scope,
		draft.PreparationID,
		draft.Release,
		draft.EvidenceAuthority,
		draft.ReviewBundle,
	)
	require.NoError(t, err)
	return created
}

func schemaWikiDecisionBytes(
	t *testing.T,
	decision types.HumanBatchDecisionReceiptV1,
) []byte {
	t.Helper()
	raw, err := CanonicalHumanBatchDecisionReceiptV1(&decision, true)
	require.NoError(t, err)
	return raw
}

func TestSchemaWikiDraftPersistsExactMembersWithoutServingOrActivationState(t *testing.T) {
	t.Parallel()
	principal, scope, reviewed := schemaWikiReviewedDraft(t)
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)

	draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
	require.Equal(t, types.WikiReleasePreparationDraft, draft.Status)
	require.Len(t, draft.Members, 75)
	require.Empty(t, draft.ReviewDecisionDigest)
	stored := fixture.storedPreparation(t, draft.ID)
	require.Equal(t, draft, &stored)
	var custody schemaWikiPreparationCustodyV1
	require.NoError(t, json.Unmarshal(stored.Manifest, &custody))
	require.Equal(t, reviewed.EvidenceAuthority, custody.CandidateEvidenceAuthority)
	require.Len(t, custody.CandidateEvidenceAuthority.SourceAuthorities, 3)
	require.Len(t, custody.CandidateEvidenceAuthority.JoinReceipts, 111)
	expectedPayloads := make(map[string]json.RawMessage, len(reviewed.Release.Members))
	for _, member := range reviewed.Release.Members {
		expectedPayloads[member.MemberRef] = member.Payload
	}
	for _, member := range stored.Members {
		expectedPayload, ok := expectedPayloads[member.LogicalSlug]
		require.True(t, ok)
		require.Equal(t, []byte(expectedPayload), []byte(member.Payload),
			"Draft must persist the actual typed page payload for every member")
	}
	heads, releases, receipts := fixture.stateCounts(t)
	require.Zero(t, heads)
	require.Zero(t, releases)
	require.Zero(t, receipts)

	_, err := fixture.authority.BeginPinnedRead(fixture.ctx, principal, scope)
	require.ErrorIs(t, err, ErrWikiReleaseNotFound)
	current, err := fixture.adapter.ReadCurrentSchemaMember(
		fixture.ctx, principal, scope, draft.Members[0].LogicalSlug,
	)
	require.ErrorIs(t, err, ErrNoSchemaWikiActiveRelease)
	require.Nil(t, current)
	search, err := fixture.adapter.SearchCurrentSchemaMembers(
		fixture.ctx, principal, scope, "",
	)
	require.ErrorIs(t, err, ErrNoSchemaWikiActiveRelease)
	require.Empty(t, search,
		"Draft must not enter Schema current/page/search/index/Agent release reads")
}

func TestCreateSchemaDraftRejectsCandidateEvidenceAuthorityDriftBeforePersistence(t *testing.T) {
	t.Parallel()

	cases := map[string]func(*testing.T, *types.Schema67CandidateEvidenceAuthorityV1){
		"missing live receipt preimage": func(_ *testing.T, authority *types.Schema67CandidateEvidenceAuthorityV1) {
			authority.SourceAuthorities[0].LiveRevisionSourceReceipt = types.LiveRevisionSourceReceiptV1{}
		},
		"missing join receipt": func(_ *testing.T, authority *types.Schema67CandidateEvidenceAuthorityV1) {
			authority.JoinReceipts = authority.JoinReceipts[1:]
		},
		"fully rehashed locator substitution": func(t *testing.T, authority *types.Schema67CandidateEvidenceAuthorityV1) {
			authority.JoinReceipts[0].LocatorRef += "-foreign"
			resealSchemaWikiEvidenceAuthority(t, authority)
		},
		"fully rehashed nested source substitution": func(t *testing.T, authority *types.Schema67CandidateEvidenceAuthorityV1) {
			source := &authority.SourceAuthorities[0]
			source.LiveRevisionSourceReceipt.WikiKBID = "wiki-kb-foreign"
			source.LiveRevisionSourceReceipt.SourceReceiptSHA256 = ""
			digest, err := types.ComputeLiveRevisionSourceReceiptSHA256(
				source.LiveRevisionSourceReceipt,
			)
			require.NoError(t, err)
			source.LiveRevisionSourceReceipt.SourceReceiptSHA256 = digest
			for index := range authority.JoinReceipts {
				join := &authority.JoinReceipts[index]
				if join.SourceSHA256 != source.SourceSHA256 {
					continue
				}
				join.LiveRevisionSourceReceipt = source.LiveRevisionSourceReceipt
				join.LiveRevisionSourceReceiptSHA256 = digest
			}
			resealSchemaWikiEvidenceAuthority(t, authority)
		},
	}

	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			principal, scope, reviewed := schemaWikiReviewedDraft(t)
			fixture := newSchemaWikiPrepareFixture(t, principal, scope)
			authority := cloneSchemaWikiEvidenceAuthority(t, reviewed.EvidenceAuthority)
			mutate(t, &authority)

			created, err := fixture.adapter.CreateSchemaDraft(
				fixture.ctx, principal, scope, reviewed.PreparationID,
				reviewed.Release, authority, reviewed.ReviewBundle,
			)
			require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
			require.Nil(t, created)
			require.Zero(t, fixture.storedCount(t))
			require.Zero(t, fixture.verifier.calls)
			heads, releases, receipts := fixture.stateCounts(t)
			require.Zero(t, heads)
			require.Zero(t, releases)
			require.Zero(t, receipts)
		})
	}
}

func TestCreateSchemaDraftRejectsQualityGateReceiptDriftBeforePersistence(t *testing.T) {
	t.Parallel()

	cases := map[string]func(*testing.T, *types.SchemaWikiReviewBundleV1){
		"missing receipt": func(_ *testing.T, bundle *types.SchemaWikiReviewBundleV1) {
			bundle.QualityGateReceipt = types.Schema67GoldenQualityGateReceiptV1{}
		},
		"non PASS status": func(t *testing.T, bundle *types.SchemaWikiReviewBundleV1) {
			bundle.QualityGateReceipt.Status = "FAIL"
			bundle.QualityGateReceipt.ReceiptSHA256 = schemaWikiTestHashWithout(
				t, bundle.QualityGateReceipt.Contract,
				bundle.QualityGateReceipt, "receipt_sha256",
			)
			bundle.ReviewBundleSHA256 = schemaWikiTestHashWithout(
				t, bundle.Contract, *bundle, "review_bundle_sha256",
			)
		},
		"missing evaluator signature": func(t *testing.T, bundle *types.SchemaWikiReviewBundleV1) {
			bundle.QualityGateReceipt.Signature = ""
			bundle.QualityGateReceipt.ReceiptSHA256 = schemaWikiTestHashWithout(
				t, bundle.QualityGateReceipt.Contract,
				bundle.QualityGateReceipt, "receipt_sha256",
			)
			bundle.ReviewBundleSHA256 = schemaWikiTestHashWithout(
				t, bundle.Contract, *bundle, "review_bundle_sha256",
			)
		},
		"signed content substitution": func(t *testing.T, bundle *types.SchemaWikiReviewBundleV1) {
			bundle.QualityGateReceipt.PrivateDossierSHA256 = strings.Repeat("f", 64)
			bundle.QualityGateReceipt.ReceiptSHA256 = schemaWikiTestHashWithout(
				t, bundle.QualityGateReceipt.Contract,
				bundle.QualityGateReceipt, "receipt_sha256",
			)
			require.NoError(t, types.ValidateSchema67GoldenQualityGateReceiptV1(
				bundle.QualityGateReceipt,
			), "the substituted receipt remains self-hash-valid but has a stale signature")
			bundle.ReviewBundleSHA256 = schemaWikiTestHashWithout(
				t, bundle.Contract, *bundle, "review_bundle_sha256",
			)
		},
		"fully rehashed foreign evidence authority": func(
			t *testing.T,
			bundle *types.SchemaWikiReviewBundleV1,
		) {
			bundle.QualityGateReceipt.CandidateEvidenceAuthoritySHA256 = strings.Repeat("d", 64)
			bundle.QualityGateReceipt.ReceiptSHA256 = schemaWikiTestHashWithout(
				t, bundle.QualityGateReceipt.Contract,
				bundle.QualityGateReceipt, "receipt_sha256",
			)
			require.NoError(t, types.ValidateSchema67GoldenQualityGateReceiptV1(
				bundle.QualityGateReceipt,
			), "the nested receipt is otherwise a valid self-consistent foreign authority")
			bundle.ReviewBundleSHA256 = schemaWikiTestHashWithout(
				t, bundle.Contract, *bundle, "review_bundle_sha256",
			)
		},
	}

	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			principal, scope, reviewed := schemaWikiReviewedDraft(t)
			fixture := newSchemaWikiPrepareFixture(t, principal, scope)
			mutate(t, &reviewed.ReviewBundle)

			created, err := fixture.adapter.CreateSchemaDraft(
				fixture.ctx, principal, scope, reviewed.PreparationID,
				reviewed.Release, reviewed.EvidenceAuthority, reviewed.ReviewBundle,
			)
			require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
			require.Nil(t, created)
			require.Zero(t, fixture.verifier.calls)
			require.Zero(t, fixture.storedCount(t))
			heads, releases, receipts := fixture.stateCounts(t)
			require.Zero(t, heads)
			require.Zero(t, releases)
			require.Zero(t, receipts)
		})
	}
}

func TestCreateSchemaDraftRejectsSelfSignedQualityGateReceiptBeforePersistence(t *testing.T) {
	t.Parallel()
	principal, scope, reviewed := schemaWikiReviewedDraft(t)
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	attacker := ed25519.NewKeyFromSeed(bytes.Repeat([]byte("x"), ed25519.SeedSize))
	receipt := &reviewed.ReviewBundle.QualityGateReceipt
	receipt.SignerKeyID = "caller-selected-key"
	receipt.Signature = "placeholder"
	unsigned, err := CanonicalSchema67GoldenQualityGateReceiptV1(receipt, false)
	require.NoError(t, err)
	receipt.Signature = base64.RawURLEncoding.EncodeToString(ed25519.Sign(attacker, unsigned))
	receipt.ReceiptSHA256 = schemaWikiTestHashWithout(
		t, receipt.Contract, *receipt, "receipt_sha256",
	)
	reviewed.ReviewBundle.ReviewBundleSHA256 = schemaWikiTestHashWithout(
		t, reviewed.ReviewBundle.Contract, reviewed.ReviewBundle, "review_bundle_sha256",
	)
	require.NoError(t, types.ValidateSchemaWikiReviewBundle(reviewed.ReviewBundle, reviewed.Release))

	created, err := fixture.adapter.CreateSchemaDraft(
		fixture.ctx, principal, scope, reviewed.PreparationID,
		reviewed.Release, reviewed.EvidenceAuthority, reviewed.ReviewBundle,
	)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
	require.Nil(t, created)
	require.Zero(t, fixture.storedCount(t))
}

func TestCreateSchemaDraftRejectsReleaseAndReviewBundleDriftBeforePersistence(t *testing.T) {
	t.Parallel()

	cases := map[string]func(*types.KnowledgeWikiReleaseV1, *types.SchemaWikiReviewBundleV1){
		"descriptor only": func(release *types.KnowledgeWikiReleaseV1, _ *types.SchemaWikiReviewBundleV1) {
			release.Members[0].Payload = nil
		},
		"generic payload": func(release *types.KnowledgeWikiReleaseV1, _ *types.SchemaWikiReviewBundleV1) {
			release.Members[0].Payload = json.RawMessage(`{"state":"present"}`)
		},
		"release identity": func(release *types.KnowledgeWikiReleaseV1, _ *types.SchemaWikiReviewBundleV1) {
			release.ReleaseSHA256 = "f" + release.ReleaseSHA256[1:]
		},
		"citation binding": func(release *types.KnowledgeWikiReleaseV1, _ *types.SchemaWikiReviewBundleV1) {
			release.CitationBindings[0].MemberDigest = "f" + release.CitationBindings[0].MemberDigest[1:]
		},
		"typed payload": func(release *types.KnowledgeWikiReleaseV1, _ *types.SchemaWikiReviewBundleV1) {
			release.Members[0].Payload[0] = '['
		},
		"review bundle": func(_ *types.KnowledgeWikiReleaseV1, bundle *types.SchemaWikiReviewBundleV1) {
			bundle.ManifestDigest = "f" + bundle.ManifestDigest[1:]
		},
	}

	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			principal, scope, reviewed := schemaWikiReviewedDraft(t)
			fixture := newSchemaWikiPrepareFixture(t, principal, scope)
			mutate(&reviewed.Release, &reviewed.ReviewBundle)

			created, err := fixture.adapter.CreateSchemaDraft(
				fixture.ctx,
				principal,
				scope,
				reviewed.PreparationID,
				reviewed.Release,
				reviewed.EvidenceAuthority,
				reviewed.ReviewBundle,
			)
			require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
			require.Nil(t, created)
			require.Zero(t, fixture.verifier.calls)
			require.Zero(t, fixture.storedCount(t))
			heads, releases, receipts := fixture.stateCounts(t)
			require.Zero(t, heads)
			require.Zero(t, releases)
			require.Zero(t, receipts)
		})
	}
}

func TestCreateSchemaDraftRejectsFullyRehashedDuplicateCitationIDBeforeAuthorities(t *testing.T) {
	t.Parallel()
	principal, scope, reviewed := schemaWikiReviewedDraft(t)
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	port := &schemaWikiCitationReadSpy{err: errors.New("must not run")}
	fixture.adapter = NewSchemaWikiService(fixture.authority, port)
	forgedRelease, forgedBundle := forgeSchemaWikiDuplicateCitationID(t, reviewed.Release)
	require.Error(t, types.ValidateKnowledgeWikiRelease(forgedRelease, forgedRelease.SchemaPack),
		"fixture must reach the public Create boundary as a fully rehashed semantic attack")
	require.Equal(t, schemaWikiTestHash(t, "schema-wiki-manifest.v1", map[string]any{
		"members": forgedRelease.Members, "citation_bindings": forgedRelease.CitationBindings,
	}), forgedRelease.ManifestDigest)
	require.Equal(t, schemaWikiTestHashWithout(
		t, forgedRelease.Contract, forgedRelease, "release_sha256",
	), forgedRelease.ReleaseSHA256)
	require.Equal(t, schemaWikiTestHashWithout(
		t, forgedBundle.Contract, forgedBundle, "review_bundle_sha256",
	), forgedBundle.ReviewBundleSHA256)

	created, err := fixture.adapter.CreateSchemaDraft(
		fixture.ctx,
		principal,
		scope,
		reviewed.PreparationID,
		forgedRelease,
		reviewed.EvidenceAuthority,
		forgedBundle,
	)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
	require.Nil(t, created)
	require.Zero(t, fixture.storedCount(t))
	require.Zero(t, fixture.verifier.calls)
	require.Zero(t, port.calls)
	heads, releases, receipts := fixture.stateCounts(t)
	require.Zero(t, heads)
	require.Zero(t, releases)
	require.Zero(t, receipts)
}

func TestSchemaWikiDraftPreviewRequiresPreparationAndExactMemberRevision(t *testing.T) {
	t.Parallel()
	principal, scope, reviewed := schemaWikiReviewedDraft(t)
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
	require.Empty(t, draft.ExpectedReleaseID)
	require.Zero(t, draft.ExpectedActivationEpoch)
	expected := draft.Members[0]

	preview, err := fixture.adapter.ReadSchemaDraftMember(
		fixture.ctx, principal, scope, draft.ID, expected.LogicalSlug, expected.RevisionID,
	)
	require.NoError(t, err)
	require.Equal(t, expected, *preview)
	viewer := types.WikiReleasePrincipal{
		ID: "viewer", TenantID: scope.TenantID, SpaceID: scope.SpaceID,
	}
	viewerRead, viewerErr := fixture.adapter.ReadSchemaDraftMember(
		schemaWikiHumanContext(viewer, scope, types.TenantRoleViewer),
		viewer,
		scope,
		draft.ID,
		expected.LogicalSlug,
		expected.RevisionID,
	)
	require.ErrorIs(t, viewerErr, ErrWikiReleaseAccessDenied)
	require.Nil(t, viewerRead)
	apiKey := principal
	apiKey.ID = "api-key-retrieve"
	apiKey.APIKeyKnowledgeBaseIDs = []string{scope.WikiKBID, scope.RawKBID}
	apiKeyContext := schemaWikiHumanContext(apiKey, scope, types.TenantRoleOwner)
	apiKeyContext = types.WithTenantAPIKeyScope(apiKeyContext, types.TenantAPIKeyScope{
		KeyID: 1, FullAccess: true,
	})
	apiKeyRead, apiKeyErr := fixture.adapter.ReadSchemaDraftMember(
		apiKeyContext,
		apiKey,
		scope,
		draft.ID,
		expected.LogicalSlug,
		expected.RevisionID,
	)
	require.ErrorIs(t, apiKeyErr, ErrWikiReleaseAccessDenied)
	require.Nil(t, apiKeyRead)

	for name, identities := range map[string][2]string{
		"foreign preparation":  {"preparation-foreign", expected.RevisionID},
		"current substitution": {draft.ID, "current"},
		"wrong revision":       {draft.ID, "revision-foreign"},
	} {
		t.Run(name, func(t *testing.T) {
			opened, readErr := fixture.adapter.ReadSchemaDraftMember(
				fixture.ctx,
				principal,
				scope,
				identities[0],
				expected.LogicalSlug,
				identities[1],
			)
			require.ErrorIs(t, readErr, ErrWikiReleaseNotFound)
			require.Nil(t, opened)
		})
	}
}

func TestSchemaWikiPreparationReadDerivesImmutableRevisionForDraftAndReady(t *testing.T) {
	t.Parallel()
	principal, scope, reviewed := schemaWikiReviewedDraft(t)
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
	expected := draft.Members[8]

	draftRead, err := fixture.adapter.ReadSchemaPreparationMember(
		fixture.ctx, principal, scope, draft.ID, expected.LogicalSlug,
	)
	require.NoError(t, err)
	require.Equal(t, "draft", draftRead.ReadMode)
	require.Equal(t, expected.RevisionID, draftRead.Member.RevisionID)
	require.Equal(t, []byte(expected.Payload), []byte(draftRead.Payload))

	ready, err := fixture.adapter.ReviewSchemaDraft(
		fixture.ctx,
		principal,
		scope,
		draft.ID,
		schemaWikiDecisionBytes(t, reviewed.HumanDecision),
	)
	require.NoError(t, err)
	readyRead, err := fixture.adapter.ReadSchemaPreparationMember(
		fixture.ctx, principal, scope, ready.ID, expected.LogicalSlug,
	)
	require.NoError(t, err)
	require.Equal(t, "reviewed_preparation", readyRead.ReadMode)
	require.Equal(t, expected.RevisionID, readyRead.Member.RevisionID)
	require.Equal(t, []byte(expected.Payload), []byte(readyRead.Payload))
}

func TestSchemaWikiDraftHumanActionsRequireTrustedJWTAdminContext(t *testing.T) {
	t.Parallel()

	for _, role := range []types.TenantRole{types.TenantRoleViewer, types.TenantRoleContributor} {
		t.Run(string(role), func(t *testing.T) {
			principal, scope, reviewed := schemaWikiReviewedDraft(t)
			fixture := newSchemaWikiPrepareFixture(t, principal, scope)
			fixture.ctx = schemaWikiHumanContext(principal, scope, role)
			created, err := fixture.adapter.CreateSchemaDraft(
				fixture.ctx, principal, scope, reviewed.PreparationID,
				reviewed.Release, reviewed.EvidenceAuthority, reviewed.ReviewBundle,
			)
			require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
			require.Nil(t, created)
			require.Zero(t, fixture.storedCount(t))
		})
	}

	t.Run("api key", func(t *testing.T) {
		principal, scope, reviewed := schemaWikiReviewedDraft(t)
		fixture := newSchemaWikiPrepareFixture(t, principal, scope)
		fixture.ctx = types.WithTenantAPIKeyScope(
			schemaWikiHumanContext(principal, scope, types.TenantRoleOwner),
			types.TenantAPIKeyScope{KeyID: 1, FullAccess: true},
		)
		created, err := fixture.adapter.CreateSchemaDraft(
			fixture.ctx, principal, scope, reviewed.PreparationID,
			reviewed.Release, reviewed.EvidenceAuthority, reviewed.ReviewBundle,
		)
		require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
		require.Nil(t, created)
		require.Zero(t, fixture.storedCount(t))
	})

	t.Run("owner", func(t *testing.T) {
		principal, scope, reviewed := schemaWikiReviewedDraft(t)
		fixture := newSchemaWikiPrepareFixture(t, principal, scope)
		fixture.ctx = schemaWikiHumanContext(principal, scope, types.TenantRoleOwner)
		created, err := fixture.adapter.CreateSchemaDraft(
			fixture.ctx, principal, scope, reviewed.PreparationID,
			reviewed.Release, reviewed.EvidenceAuthority, reviewed.ReviewBundle,
		)
		require.NoError(t, err)
		require.Equal(t, types.WikiReleasePreparationDraft, created.Status)
	})
}

func TestSchemaWikiReviewDraftRequiresTrustedHumanAdminBeforeVerifier(t *testing.T) {
	t.Parallel()

	cases := map[string]func(context.Context, types.WikiReleasePrincipal, types.WikiReleaseScope) context.Context{
		"missing trusted role": func(_ context.Context, principal types.WikiReleasePrincipal, scope types.WikiReleaseScope) context.Context {
			ctx := context.WithValue(context.Background(), types.UserIDContextKey, principal.ID)
			ctx = context.WithValue(ctx, types.TenantIDContextKey, principal.TenantID)
			return SealWikiReleaseAccess(ctx, principal, scope)
		},
		"viewer": func(_ context.Context, principal types.WikiReleasePrincipal, scope types.WikiReleaseScope) context.Context {
			return schemaWikiHumanContext(principal, scope, types.TenantRoleViewer)
		},
		"contributor": func(_ context.Context, principal types.WikiReleasePrincipal, scope types.WikiReleaseScope) context.Context {
			return schemaWikiHumanContext(principal, scope, types.TenantRoleContributor)
		},
		"api key with owner role": func(_ context.Context, principal types.WikiReleasePrincipal, scope types.WikiReleaseScope) context.Context {
			return types.WithTenantAPIKeyScope(
				schemaWikiHumanContext(principal, scope, types.TenantRoleOwner),
				types.TenantAPIKeyScope{KeyID: 1, FullAccess: true},
			)
		},
	}

	for name, badContext := range cases {
		t.Run(name, func(t *testing.T) {
			principal, scope, reviewed := schemaWikiReviewedDraft(t)
			fixture := newSchemaWikiPrepareFixture(t, principal, scope)
			draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
			before := fixture.storedPreparation(t, draft.ID)

			ready, err := fixture.adapter.ReviewSchemaDraft(
				badContext(fixture.ctx, principal, scope),
				principal,
				scope,
				draft.ID,
				schemaWikiDecisionBytes(t, reviewed.HumanDecision),
			)
			require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
			require.Nil(t, ready)
			require.Zero(t, fixture.verifier.calls)
			require.Equal(t, before, fixture.storedPreparation(t, draft.ID))
			heads, releases, receipts := fixture.stateCounts(t)
			require.Zero(t, heads)
			require.Zero(t, releases)
			require.Zero(t, receipts)
		})
	}

	t.Run("owner", func(t *testing.T) {
		principal, scope, reviewed := schemaWikiReviewedDraft(t)
		fixture := newSchemaWikiPrepareFixture(t, principal, scope)
		draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
		ready, err := fixture.adapter.ReviewSchemaDraft(
			schemaWikiHumanContext(principal, scope, types.TenantRoleOwner),
			principal,
			scope,
			draft.ID,
			schemaWikiDecisionBytes(t, reviewed.HumanDecision),
		)
		require.NoError(t, err)
		require.Equal(t, types.WikiReleasePreparationReady, ready.Status)
		require.Equal(t, 1, fixture.verifier.calls)
	})
}

func TestSchemaWikiReviewDraftVerifiesBeforeAtomicDraftToReady(t *testing.T) {
	t.Parallel()
	principal, scope, reviewed := schemaWikiReviewedDraft(t)
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
	fixture.verifier.beforeVerify = func(receipt *types.HumanBatchDecisionReceiptV1) {
		require.Equal(t, reviewed.HumanDecision, *receipt)
		stored := fixture.storedPreparation(t, draft.ID)
		require.Equal(t, types.WikiReleasePreparationDraft, stored.Status)
		require.Empty(t, stored.ReviewDecisionDigest)
		var ready int64
		require.NoError(t, fixture.db.Model(&types.WikiReleasePreparation{}).
			Where("status = ?", types.WikiReleasePreparationReady).Count(&ready).Error)
		require.Zero(t, ready, "verification must happen before the draft becomes ready")
		heads, releases, receipts := fixture.stateCounts(t)
		require.Zero(t, heads)
		require.Zero(t, releases)
		require.Zero(t, receipts)
	}

	ready, err := fixture.adapter.ReviewSchemaDraft(
		fixture.ctx,
		principal,
		scope,
		draft.ID,
		schemaWikiDecisionBytes(t, reviewed.HumanDecision),
	)
	require.NoError(t, err)
	require.Equal(t, 1, fixture.verifier.calls)
	require.Equal(t, types.WikiReleasePreparationReady, ready.Status)
	require.Equal(t, reviewed.ReviewDecisionDigest, ready.ReviewDecisionDigest)
	require.Equal(t, reviewed.ReviewBundle.ReviewBundleSHA256, ready.ReadyReceiptDigest)
	stored := fixture.storedPreparation(t, draft.ID)
	require.Equal(t, ready, &stored)
	require.Len(t, stored.Members, 75)
	heads, releases, receipts := fixture.stateCounts(t)
	require.Zero(t, heads)
	require.Zero(t, releases)
	require.Zero(t, receipts)
}

func TestSchemaWikiReviewDraftFailuresLeaveExactDraftUnchanged(t *testing.T) {
	t.Parallel()

	cases := map[string]func(*schemaWikiDraftFixture){
		"reject": func(draft *schemaWikiDraftFixture) {
			draft.HumanDecision.Decision = "reject"
			resignSchemaWikiDecision(t, draft)
		},
		"partial": func(draft *schemaWikiDraftFixture) {
			draft.HumanDecision.Decision = "partial"
			resignSchemaWikiDecision(t, draft)
		},
		"expired": func(draft *schemaWikiDraftFixture) {
			draft.HumanDecision.IssuedAt = time.Now().Add(-2 * time.Hour).Unix()
			draft.HumanDecision.ExpiresAt = time.Now().Add(-time.Hour).Unix()
			resignSchemaWikiDecision(t, draft)
		},
		"scope drift": func(draft *schemaWikiDraftFixture) {
			draft.HumanDecision.RawKBID = "raw-foreign"
			resignSchemaWikiDecision(t, draft)
		},
		"candidate drift": func(draft *schemaWikiDraftFixture) {
			draft.HumanDecision.CandidateHash = schemaWikiDifferentSHA(draft.HumanDecision.CandidateHash)
			resignSchemaWikiDecision(t, draft)
		},
		"manifest review-bundle drift": func(draft *schemaWikiDraftFixture) {
			draft.HumanDecision.HumanBatchHash = schemaWikiDifferentSHA(draft.HumanDecision.HumanBatchHash)
			resignSchemaWikiDecision(t, draft)
		},
		"principal drift": func(draft *schemaWikiDraftFixture) {
			draft.HumanDecision.PrincipalID = "foreign-named-human"
			resignSchemaWikiDecision(t, draft)
		},
	}

	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			principal, scope, reviewed := schemaWikiReviewedDraft(t)
			fixture := newSchemaWikiPrepareFixture(t, principal, scope)
			draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
			before := fixture.storedPreparation(t, draft.ID)
			mutate(&reviewed)
			fixture.verifier.beforeVerify = func(_ *types.HumanBatchDecisionReceiptV1) {
				current := fixture.storedPreparation(t, draft.ID)
				require.Equal(t, types.WikiReleasePreparationDraft, current.Status)
				require.Empty(t, current.ReviewDecisionDigest)
				var readyCount int64
				require.NoError(t, fixture.db.Model(&types.WikiReleasePreparation{}).
					Where("status = ?", types.WikiReleasePreparationReady).Count(&readyCount).Error)
				require.Zero(t, readyCount)
				heads, releases, receipts := fixture.stateCounts(t)
				require.Zero(t, heads)
				require.Zero(t, releases)
				require.Zero(t, receipts)
			}

			ready, reviewErr := fixture.adapter.ReviewSchemaDraft(
				fixture.ctx,
				principal,
				scope,
				draft.ID,
				schemaWikiDecisionBytes(t, reviewed.HumanDecision),
			)
			require.ErrorIs(t, reviewErr, ErrWikiReleaseInvalidAuthorization)
			require.Nil(t, ready)
			require.Equal(t, 1, fixture.verifier.calls)
			after := fixture.storedPreparation(t, draft.ID)
			require.Equal(t, before, after)
			require.Equal(t, types.WikiReleasePreparationDraft, after.Status)
			heads, releases, receipts := fixture.stateCounts(t)
			require.Zero(t, heads)
			require.Zero(t, releases)
			require.Zero(t, receipts)
		})
	}
}

func TestSchemaWikiReviewDraftCASRejectsConcurrentDraftDigestDrift(t *testing.T) {
	t.Parallel()

	cases := map[string]struct {
		mutate func(*testing.T, *schemaWikiPrepareFixture, *types.WikiReleasePreparation)
		assert func(*testing.T, types.WikiReleasePreparation, *types.WikiReleasePreparation)
	}{
		"candidate digest": {
			mutate: func(t *testing.T, fixture *schemaWikiPrepareFixture, draft *types.WikiReleasePreparation) {
				require.NoError(t, fixture.db.Model(&types.WikiReleasePreparation{}).
					Where("preparation_id = ?", draft.ID).
					Update("candidate_digest", schemaWikiDifferentSHA(draft.CandidateDigest)).Error)
			},
			assert: func(t *testing.T, stored types.WikiReleasePreparation, draft *types.WikiReleasePreparation) {
				require.Equal(t, schemaWikiDifferentSHA(draft.CandidateDigest), stored.CandidateDigest)
			},
		},
		"review bundle digest": {
			mutate: func(t *testing.T, fixture *schemaWikiPrepareFixture, draft *types.WikiReleasePreparation) {
				require.NoError(t, fixture.db.Model(&types.WikiReleasePreparation{}).
					Where("preparation_id = ?", draft.ID).
					Update("ready_receipt_digest", schemaWikiDifferentSHA(draft.ReadyReceiptDigest)).Error)
			},
			assert: func(t *testing.T, stored types.WikiReleasePreparation, draft *types.WikiReleasePreparation) {
				require.Equal(t, schemaWikiDifferentSHA(draft.ReadyReceiptDigest), stored.ReadyReceiptDigest)
			},
		},
		"review policy": {
			mutate: func(t *testing.T, fixture *schemaWikiPrepareFixture, draft *types.WikiReleasePreparation) {
				require.NoError(t, fixture.db.Model(&types.WikiReleasePreparation{}).
					Where("preparation_id = ?", draft.ID).
					Update("review_policy_id", schemaWikiDifferentSHA(draft.ReviewPolicyID)).Error)
			},
			assert: func(t *testing.T, stored types.WikiReleasePreparation, draft *types.WikiReleasePreparation) {
				require.Equal(t, schemaWikiDifferentSHA(draft.ReviewPolicyID), stored.ReviewPolicyID)
			},
		},
		"storage manifest digest": {
			mutate: func(t *testing.T, fixture *schemaWikiPrepareFixture, draft *types.WikiReleasePreparation) {
				require.NoError(t, fixture.db.Model(&types.WikiReleasePreparation{}).
					Where("preparation_id = ?", draft.ID).
					Update("manifest_digest", schemaWikiDifferentSHA(draft.ManifestDigest)).Error)
			},
			assert: func(t *testing.T, stored types.WikiReleasePreparation, draft *types.WikiReleasePreparation) {
				require.Equal(t, schemaWikiDifferentSHA(draft.ManifestDigest), stored.ManifestDigest)
			},
		},
		"raw manifest": {
			mutate: func(t *testing.T, fixture *schemaWikiPrepareFixture, draft *types.WikiReleasePreparation) {
				require.NoError(t, fixture.db.Model(&types.WikiReleasePreparation{}).
					Where("preparation_id = ?", draft.ID).
					Update("manifest", json.RawMessage(`{"tampered":true}`)).Error)
			},
			assert: func(t *testing.T, stored types.WikiReleasePreparation, _ *types.WikiReleasePreparation) {
				require.JSONEq(t, `{"tampered":true}`, string(stored.Manifest))
			},
		},
		"members": {
			mutate: func(t *testing.T, fixture *schemaWikiPrepareFixture, draft *types.WikiReleasePreparation) {
				require.NoError(t, fixture.db.Exec(
					"UPDATE wiki_release_preparations SET members = ? WHERE preparation_id = ?",
					"[]", draft.ID,
				).Error)
			},
			assert: func(t *testing.T, stored types.WikiReleasePreparation, _ *types.WikiReleasePreparation) {
				require.Empty(t, stored.Members)
			},
		},
		"expected release": {
			mutate: func(t *testing.T, fixture *schemaWikiPrepareFixture, draft *types.WikiReleasePreparation) {
				require.NoError(t, fixture.db.Model(&types.WikiReleasePreparation{}).
					Where("preparation_id = ?", draft.ID).
					Update("expected_release_id", "release-foreign").Error)
			},
			assert: func(t *testing.T, stored types.WikiReleasePreparation, _ *types.WikiReleasePreparation) {
				require.Equal(t, "release-foreign", stored.ExpectedReleaseID)
			},
		},
		"expected activation epoch": {
			mutate: func(t *testing.T, fixture *schemaWikiPrepareFixture, draft *types.WikiReleasePreparation) {
				require.NoError(t, fixture.db.Model(&types.WikiReleasePreparation{}).
					Where("preparation_id = ?", draft.ID).
					Update("expected_activation_epoch", uint64(9)).Error)
			},
			assert: func(t *testing.T, stored types.WikiReleasePreparation, _ *types.WikiReleasePreparation) {
				require.Equal(t, uint64(9), stored.ExpectedActivationEpoch)
			},
		},
		"preexisting review decision": {
			mutate: func(t *testing.T, fixture *schemaWikiPrepareFixture, draft *types.WikiReleasePreparation) {
				require.NoError(t, fixture.db.Model(&types.WikiReleasePreparation{}).
					Where("preparation_id = ?", draft.ID).
					Update("review_decision_digest", strings.Repeat("a", 64)).Error)
			},
			assert: func(t *testing.T, stored types.WikiReleasePreparation, _ *types.WikiReleasePreparation) {
				require.Equal(t, strings.Repeat("a", 64), stored.ReviewDecisionDigest)
			},
		},
		"preparation digest": {
			mutate: func(t *testing.T, fixture *schemaWikiPrepareFixture, draft *types.WikiReleasePreparation) {
				require.NoError(t, fixture.db.Model(&types.WikiReleasePreparation{}).
					Where("preparation_id = ?", draft.ID).
					Update("preparation_digest", schemaWikiDifferentSHA(draft.PreparationDigest)).Error)
			},
			assert: func(t *testing.T, stored types.WikiReleasePreparation, draft *types.WikiReleasePreparation) {
				require.Equal(t, schemaWikiDifferentSHA(draft.PreparationDigest), stored.PreparationDigest)
			},
		},
	}

	for name, testCase := range cases {
		t.Run(name, func(t *testing.T) {
			principal, scope, reviewed := schemaWikiReviewedDraft(t)
			fixture := newSchemaWikiPrepareFixture(t, principal, scope)
			draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
			fixture.verifier.beforeVerify = func(_ *types.HumanBatchDecisionReceiptV1) {
				testCase.mutate(t, fixture, draft)
			}

			ready, err := fixture.adapter.ReviewSchemaDraft(
				fixture.ctx,
				principal,
				scope,
				draft.ID,
				schemaWikiDecisionBytes(t, reviewed.HumanDecision),
			)
			require.ErrorIs(t, err, wikirepository.ErrWikiReleaseConflict)
			require.Nil(t, ready)
			require.Equal(t, 1, fixture.verifier.calls)
			stored := fixture.storedPreparation(t, draft.ID)
			require.Equal(t, types.WikiReleasePreparationDraft, stored.Status)
			if name != "preexisting review decision" {
				require.Empty(t, stored.ReviewDecisionDigest)
			}
			testCase.assert(t, stored, draft)
			heads, releases, receipts := fixture.stateCounts(t)
			require.Zero(t, heads)
			require.Zero(t, releases)
			require.Zero(t, receipts)
		})
	}
}

func TestSchemaWikiReviewDraftRejectsInvalidStoredCustodyBeforeHumanVerifier(t *testing.T) {
	t.Parallel()
	principal, scope, reviewed := schemaWikiReviewedDraft(t)
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
	require.NoError(t, fixture.db.Model(&types.WikiReleasePreparation{}).
		Where("preparation_id = ?", draft.ID).
		Update("manifest", json.RawMessage(`{"tampered":true}`)).Error)

	ready, err := fixture.adapter.ReviewSchemaDraft(
		fixture.ctx,
		principal,
		scope,
		draft.ID,
		schemaWikiDecisionBytes(t, reviewed.HumanDecision),
	)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
	require.Nil(t, ready)
	require.Zero(t, fixture.verifier.calls)
	stored := fixture.storedPreparation(t, draft.ID)
	require.Equal(t, types.WikiReleasePreparationDraft, stored.Status)
	require.Empty(t, stored.ReviewDecisionDigest)
	heads, releases, receipts := fixture.stateCounts(t)
	require.Zero(t, heads)
	require.Zero(t, releases)
	require.Zero(t, receipts)
}

func TestCreateSchemaDraftRejectsCitationSpaceOutsideExactRouteScope(t *testing.T) {
	t.Parallel()
	principal, scope, reviewed := schemaWikiReviewedDraft(t)
	scope.SpaceID = "space-foreign"
	principal.SpaceID = scope.SpaceID
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)

	created, err := fixture.adapter.CreateSchemaDraft(
		fixture.ctx,
		principal,
		scope,
		reviewed.PreparationID,
		reviewed.Release,
		reviewed.EvidenceAuthority,
		reviewed.ReviewBundle,
	)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
	require.Nil(t, created)
	require.Zero(t, fixture.storedCount(t))
}

func TestSchemaWikiDraftCannotActivateAndReadyNeedsSeparatePublishAuthorization(t *testing.T) {
	t.Parallel()
	principal, scope, reviewed := schemaWikiReviewedDraft(t)
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	require.NoError(t, fixture.db.Create(&types.WikiReleaseHead{
		ID: "head-old", WikiReleaseScope: scope,
		ActiveReleaseID: "release-old", ActivationEpoch: 4,
	}).Error)
	draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
	rawDecision := schemaWikiDecisionBytes(t, reviewed.HumanDecision)
	authorization := signWikiReleaseAuthorization(
		t,
		fixture.publishPrivateKey,
		draft,
		reviewed.HumanDecision.Nonce,
		reviewed.HumanDecision.ExpiresAt,
	)

	activation, err := fixture.authority.ActivateReviewed(
		fixture.ctx, principal, rawDecision, authorization,
	)
	require.Error(t, err, "an unreviewed Draft must never activate")
	require.Nil(t, activation)
	head, err := fixture.authority.repository.GetHeadForWikiKB(
		fixture.ctx, scope.TenantID, scope.WikiKBID,
	)
	require.NoError(t, err)
	require.Equal(t, "release-old", head.ActiveReleaseID)
	require.Equal(t, uint64(4), head.ActivationEpoch)

	ready, err := fixture.adapter.ReviewSchemaDraft(
		fixture.ctx, principal, scope, draft.ID, rawDecision,
	)
	require.NoError(t, err)
	_, err = fixture.authority.ActivateReviewed(fixture.ctx, principal, rawDecision, nil)
	require.Error(t, err, "review is not publish authorization")

	staleAuthorization := signWikiReleaseAuthorization(
		t,
		fixture.publishPrivateKey,
		ready,
		reviewed.HumanDecision.Nonce,
		reviewed.HumanDecision.ExpiresAt,
	)
	var stale types.PublishAuthorizationV0
	require.NoError(t, json.Unmarshal(staleAuthorization, &stale))
	stale.ExpectedReleaseID = "release-stale"
	unsigned, err := CanonicalPublishAuthorizationV0(&stale, false)
	require.NoError(t, err)
	stale.Signature = EncodeWikiReleaseSignature(ed25519.Sign(fixture.publishPrivateKey, unsigned))
	staleAuthorization, err = CanonicalPublishAuthorizationV0(&stale, true)
	require.NoError(t, err)
	_, err = fixture.authority.ActivateReviewed(
		fixture.ctx, principal, rawDecision, staleAuthorization,
	)
	require.Error(t, err)
	head, err = fixture.authority.repository.GetHeadForWikiKB(
		fixture.ctx, scope.TenantID, scope.WikiKBID,
	)
	require.NoError(t, err)
	require.Equal(t, "release-old", head.ActiveReleaseID)
	require.Equal(t, uint64(4), head.ActivationEpoch)
	require.NoError(t, fixture.db.Model(&types.WikiReleaseHead{}).
		Where("tenant_id = ? AND space_id = ? AND raw_kb_id = ? AND wiki_kb_id = ?",
			scope.TenantID, scope.SpaceID, scope.RawKBID, scope.WikiKBID).
		Updates(map[string]any{
			"active_release_id": "release-winner",
			"activation_epoch":  uint64(5),
		}).Error)
	exactAuthorization := signWikiReleaseAuthorization(
		t,
		fixture.publishPrivateKey,
		ready,
		reviewed.HumanDecision.Nonce,
		reviewed.HumanDecision.ExpiresAt,
	)
	_, err = fixture.authority.ActivateReviewed(
		fixture.ctx, principal, rawDecision, exactAuthorization,
	)
	require.ErrorIs(t, err, ErrWikiReleaseConflict)
	head, err = fixture.authority.repository.GetHeadForWikiKB(
		fixture.ctx, scope.TenantID, scope.WikiKBID,
	)
	require.NoError(t, err)
	require.Equal(t, "release-winner", head.ActiveReleaseID)
	require.Equal(t, uint64(5), head.ActivationEpoch)
	_, releases, receipts := fixture.stateCounts(t)
	require.Zero(t, releases)
	require.Zero(t, receipts)
}

func TestSchemaWikiReadyActivatesOnlyWithSeparatePublishAuthorization(t *testing.T) {
	t.Parallel()
	principal, scope, reviewed := schemaWikiReviewedDraft(t)
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
	rawDecision := schemaWikiDecisionBytes(t, reviewed.HumanDecision)
	ready, err := fixture.adapter.ReviewSchemaDraft(
		fixture.ctx, principal, scope, draft.ID, rawDecision,
	)
	require.NoError(t, err)
	authorization := signWikiReleaseAuthorization(
		t,
		fixture.publishPrivateKey,
		ready,
		reviewed.HumanDecision.Nonce,
		reviewed.HumanDecision.ExpiresAt,
	)

	receipt, err := fixture.authority.ActivateReviewed(
		fixture.ctx, principal, rawDecision, authorization,
	)
	require.NoError(t, err)
	require.NotNil(t, receipt)
	require.Equal(t, uint64(1), receipt.ActivationEpoch)
	head, err := fixture.authority.repository.GetHeadForWikiKB(
		fixture.ctx, scope.TenantID, scope.WikiKBID,
	)
	require.NoError(t, err)
	require.Equal(t, receipt.ReleaseID, head.ActiveReleaseID)
	require.Equal(t, receipt.ActivationEpoch, head.ActivationEpoch)
}

type schemaWikiCitationReadSpy struct {
	calls   int
	err     error
	request CitationRevisionReadRequestV1
}

func (s *schemaWikiCitationReadSpy) ReadExactRevision(
	_ context.Context,
	request CitationRevisionReadRequestV1,
) ([]byte, error) {
	s.calls++
	s.request = request
	return nil, s.err
}

func TestCitationRevisionReadPortUsesExactVectorIdentityAndFailsUnavailable(t *testing.T) {
	t.Parallel()
	principal, scope, reviewed := schemaWikiReviewedDraft(t)
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	port := &schemaWikiCitationReadSpy{err: ErrSchemaWikiCitationUnavailable}
	fixture.adapter = NewSchemaWikiService(fixture.authority, port)
	draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
	rawDecision := schemaWikiDecisionBytes(t, reviewed.HumanDecision)
	ready, err := fixture.adapter.ReviewSchemaDraft(
		fixture.ctx, principal, scope, draft.ID, rawDecision,
	)
	require.NoError(t, err)
	authorization := signWikiReleaseAuthorization(
		t, fixture.publishPrivateKey, ready, reviewed.HumanDecision.Nonce,
		reviewed.HumanDecision.ExpiresAt,
	)
	_, err = fixture.authority.ActivateReviewed(
		fixture.ctx, principal, rawDecision, authorization,
	)
	require.NoError(t, err)
	pin, err := fixture.authority.BeginPinnedRead(fixture.ctx, principal, scope)
	require.NoError(t, err)
	citation := firstSchemaWikiCitation(t, reviewed.Release)

	opened, err := fixture.adapter.ReadPinnedSchemaCitation(
		fixture.ctx, principal, pin, citation.LogicalMemberRef, citation.CitationID,
	)
	require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
	require.Empty(t, opened)
	require.Equal(t, 1, port.calls)
	require.Equal(t, scope, port.request.Scope,
		"the exact-revision port must receive the server-derived sealed scope")
	require.Equal(t, citation, port.request.Citation)
	require.Equal(t, citation.CitationSHA256, port.request.Binding.CitationSHA256)
	require.NotNil(t, port.request.CoordinateAuthorityReceipt)
	require.Equal(
		t, reviewed.EvidenceAuthority.JoinReceipts[0],
		*port.request.CoordinateAuthorityReceipt,
		"the server must derive the complete join receipt from stored release custody",
	)
}

func firstSchemaWikiCitation(
	t *testing.T,
	release types.KnowledgeWikiReleaseV1,
) types.CitationTargetV1 {
	t.Helper()
	for _, member := range release.Members {
		if member.MemberKind != "field" {
			continue
		}
		var page types.SchemaFieldPageV1
		require.NoError(t, json.Unmarshal(member.Payload, &page))
		if len(page.Citations) > 0 {
			return page.Citations[0]
		}
	}
	t.Fatal("frozen release has no citation")
	return types.CitationTargetV1{}
}

func TestCitationRevisionRejectsCallerSubstitutionAndUnauthorizedBeforePort(t *testing.T) {
	t.Parallel()
	principal, scope, reviewed := schemaWikiReviewedDraft(t)
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	port := &schemaWikiCitationReadSpy{err: errors.New("must not run")}
	fixture.adapter = NewSchemaWikiService(fixture.authority, port)
	draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
	rawDecision := schemaWikiDecisionBytes(t, reviewed.HumanDecision)
	ready, err := fixture.adapter.ReviewSchemaDraft(
		fixture.ctx, principal, scope, draft.ID, rawDecision,
	)
	require.NoError(t, err)
	authorization := signWikiReleaseAuthorization(
		t, fixture.publishPrivateKey, ready, reviewed.HumanDecision.Nonce,
		reviewed.HumanDecision.ExpiresAt,
	)
	_, err = fixture.authority.ActivateReviewed(
		fixture.ctx, principal, rawDecision, authorization,
	)
	require.NoError(t, err)
	pin, err := fixture.authority.BeginPinnedRead(fixture.ctx, principal, scope)
	require.NoError(t, err)
	citation := firstSchemaWikiCitation(t, reviewed.Release)

	opened, err := fixture.adapter.ReadPinnedSchemaCitation(
		fixture.ctx, principal, pin, citation.LogicalMemberRef, "citation-foreign",
	)
	require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
	require.Empty(t, opened)
	require.Zero(t, port.calls, "caller-selected foreign citation must not reach exact-revision port")

	unsealed := context.WithValue(context.Background(), types.UserIDContextKey, principal.ID)
	unsealed = context.WithValue(unsealed, types.TenantIDContextKey, principal.TenantID)
	opened, err = fixture.adapter.ReadPinnedSchemaCitation(
		unsealed, principal, pin, citation.LogicalMemberRef, citation.CitationID,
	)
	require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
	require.Empty(t, opened)
	require.Zero(t, port.calls, "unsealed caller must fail before the exact-revision port")
}

type schemaWikiAccessSpy struct {
	calls   []string
	allowed bool
}

func (s *schemaWikiAccessSpy) VerifyWikiReleaseAccess(
	_ context.Context,
	request WikiReleaseAccessRequest,
) error {
	s.calls = append(s.calls, request.Operation)
	if !s.allowed {
		return ErrWikiReleaseAccessDenied
	}
	return nil
}

func newGenericSchemaWikiReadFixture(
	t *testing.T,
) (*SchemaWikiService, *WikiReleaseService, *schemaWikiAccessSpy, types.WikiReleasePrincipal, types.WikiReleaseScope) {
	t.Helper()
	db, err := gorm.Open(
		sqlite.Open("file:"+t.Name()+"?mode=memory&cache=shared"),
		&gorm.Config{},
	)
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(
		&types.WikiReleasePreparation{},
		&types.WikiRelease{},
		&types.WikiReleaseMember{},
		&types.WikiReleaseHead{},
		&types.WikiReleaseReceipt{},
	))
	scope := types.WikiReleaseScope{
		TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-596-1",
	}
	principal := types.WikiReleasePrincipal{ID: "viewer", TenantID: 10003, SpaceID: "space-596-1"}
	repo := wikirepository.NewWikiReleaseRepository(db)
	access := &schemaWikiAccessSpy{allowed: true}
	authority := NewWikiReleaseService(repo, access, nil, WikiReleaseServiceOptions{})
	preparation, err := authority.Prepare(context.Background(), principal, &types.WikiReleasePreparation{
		ID:                   "preparation-reviewed",
		WikiReleaseScope:     scope,
		CandidateDigest:      strings.Repeat("1", 64),
		ReadyReceiptDigest:   strings.Repeat("2", 64),
		ReviewDecisionDigest: strings.Repeat("3", 64),
		ReviewPolicyID:       strings.Repeat("4", 64),
		Members: []types.WikiReleaseMemberSnapshot{{
			Kind: "field", LogicalSlug: "field:product_code", RevisionID: strings.Repeat("5", 64),
			MemberDigest: strings.Repeat("6", 64), Title: "field:product_code",
			Payload: json.RawMessage(`{"state":"present"}`),
		}},
	})
	require.NoError(t, err)
	_, err = repo.Activate(context.Background(), wikirepository.WikiReleaseActivationWrite{
		Release: &types.WikiRelease{
			ID: "release-r1", WikiReleaseScope: scope,
			CandidateDigest: preparation.CandidateDigest, ManifestDigest: preparation.ManifestDigest,
			PreparationID: preparation.ID,
		},
		Members: preparation.Members, ExpectedReleaseID: "", ExpectedActivationEpoch: 0,
		Nonce: "generic-r1", AuthorizationDigest: strings.Repeat("7", 64),
		ActivatedBy: "viewer", ActivatedAt: time.Now().UTC(), ActivationReceiptID: "receipt-r1",
		ExpectedPreparationID: preparation.ID, ExpectedPreparationDigest: preparation.PreparationDigest,
	})
	require.NoError(t, err)
	return NewSchemaWikiService(authority, nil), authority, access, principal, scope
}

func TestSchemaWikiCurrentPinnedAndReviewedPreparationReadsStayDistinct(t *testing.T) {
	t.Parallel()
	principal, scope, reviewed := schemaWikiReviewedDraft(t)
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
	rawDecision := schemaWikiDecisionBytes(t, reviewed.HumanDecision)
	ready, err := fixture.adapter.ReviewSchemaDraft(
		fixture.ctx, principal, scope, draft.ID, rawDecision,
	)
	require.NoError(t, err)
	authorization := signWikiReleaseAuthorization(
		t, fixture.publishPrivateKey, ready, reviewed.HumanDecision.Nonce,
		reviewed.HumanDecision.ExpiresAt,
	)
	receipt, err := fixture.authority.ActivateReviewed(
		fixture.ctx, principal, rawDecision, authorization,
	)
	require.NoError(t, err)
	expected := schemaWikiReleaseMemberByRef(t, reviewed.Release, "field:product_code")

	current, err := fixture.adapter.ReadCurrentSchemaMember(
		fixture.ctx, principal, scope, "field:product_code",
	)
	require.NoError(t, err)
	require.Equal(t, "active", current.ReadMode)
	require.Equal(t, receipt.ReleaseID, current.ReleaseID)
	require.Empty(t, current.PreparationID)
	require.Equal(t, []byte(expected.Payload), []byte(current.Payload))
	authority, err := fixture.adapter.ReadCurrentSchemaAuthority(fixture.ctx, principal, scope)
	require.NoError(t, err)
	require.Equal(t, receipt.ReleaseID, authority.ReleaseID)
	require.Equal(t, receipt.ActivationEpoch, authority.ActivationEpoch)
	require.Equal(t, reviewed.Release.Entity.EntityID, authority.Entity.EntityID)
	require.Equal(t, reviewed.Release.EntityVersion.VersionID, authority.EntityVersion.VersionID)
	require.Equal(t, reviewed.Release.EntityVersion.VersionID, authority.Root.EntityVersionID)

	prepared, err := fixture.adapter.ReadReviewedPreparationMember(
		fixture.ctx, principal, scope, ready.ID, "field:product_code",
	)
	require.NoError(t, err)
	require.Equal(t, "reviewed_preparation", prepared.ReadMode)
	require.Equal(t, ready.ID, prepared.PreparationID)
	require.Empty(t, prepared.ReleaseID)
	require.Equal(t, []byte(expected.Payload), []byte(prepared.Payload))

	pin, err := fixture.authority.BeginPinnedRead(fixture.ctx, principal, scope)
	require.NoError(t, err)
	require.Equal(t, receipt.ReleaseID, pin.ReleaseID())
	// A Head change after the opaque pin cannot redirect the old request.
	require.NoError(t, fixture.db.Model(&types.WikiReleaseHead{}).
		Where("tenant_id = ? AND wiki_kb_id = ?", scope.TenantID, scope.WikiKBID).
		Updates(map[string]any{"active_release_id": "release-r2", "activation_epoch": uint64(2)}).Error)
	pinned, err := fixture.adapter.ReadPinnedSchemaMember(
		fixture.ctx, principal, pin, "field:product_code",
	)
	require.NoError(t, err)
	require.Equal(t, []byte(expected.Payload), []byte(pinned.Payload))
}

func TestSchemaWikiPostgresJSONBNormalizationReturnsCanonicalPayloadAcrossReads(t *testing.T) {
	t.Parallel()

	t.Run("draft", func(t *testing.T) {
		principal, scope, reviewed := schemaWikiReviewedDraft(t)
		fixture := newSchemaWikiPrepareFixture(t, principal, scope)
		draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
		normalizeSchemaWikiPreparationAsPostgresJSONB(t, fixture, draft.ID)
		expected := schemaWikiReleaseMemberByRef(t, reviewed.Release, "field:product_code")

		opened, err := fixture.adapter.ReadSchemaDraftMember(
			fixture.ctx, principal, scope, draft.ID, expected.MemberRef, reviewed.Release.ReleaseSHA256,
		)
		require.NoError(t, err)
		require.Equal(t, []byte(expected.Payload), []byte(opened.Payload))
	})

	t.Run("ready", func(t *testing.T) {
		principal, scope, reviewed := schemaWikiReviewedDraft(t)
		fixture := newSchemaWikiPrepareFixture(t, principal, scope)
		draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
		ready, err := fixture.adapter.ReviewSchemaDraft(
			fixture.ctx, principal, scope, draft.ID,
			schemaWikiDecisionBytes(t, reviewed.HumanDecision),
		)
		require.NoError(t, err)
		normalizeSchemaWikiPreparationAsPostgresJSONB(t, fixture, ready.ID)
		expected := schemaWikiReleaseMemberByRef(t, reviewed.Release, "field:product_code")

		opened, err := fixture.adapter.ReadReviewedPreparationMember(
			fixture.ctx, principal, scope, ready.ID, expected.MemberRef,
		)
		require.NoError(t, err)
		require.Equal(t, []byte(expected.Payload), []byte(opened.Payload))
	})

	t.Run("normalized draft reviews to ready", func(t *testing.T) {
		principal, scope, reviewed := schemaWikiReviewedDraft(t)
		fixture := newSchemaWikiPrepareFixture(t, principal, scope)
		draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
		normalizeSchemaWikiPreparationAsPostgresJSONB(t, fixture, draft.ID)

		ready, err := fixture.adapter.ReviewSchemaDraft(
			fixture.ctx, principal, scope, draft.ID,
			schemaWikiDecisionBytes(t, reviewed.HumanDecision),
		)
		require.NoError(t, err)
		require.Equal(t, types.WikiReleasePreparationReady, ready.Status)
		require.Equal(t, 1, fixture.verifier.calls)
		expected := schemaWikiReleaseMemberByRef(t, reviewed.Release, "field:product_code")
		opened, err := fixture.adapter.ReadReviewedPreparationMember(
			fixture.ctx, principal, scope, ready.ID, expected.MemberRef,
		)
		require.NoError(t, err)
		require.Equal(t, []byte(expected.Payload), []byte(opened.Payload))
	})

	t.Run("active pinned and search", func(t *testing.T) {
		principal, scope, reviewed := schemaWikiReviewedDraft(t)
		fixture := newSchemaWikiPrepareFixture(t, principal, scope)
		draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
		rawDecision := schemaWikiDecisionBytes(t, reviewed.HumanDecision)
		ready, err := fixture.adapter.ReviewSchemaDraft(
			fixture.ctx, principal, scope, draft.ID, rawDecision,
		)
		require.NoError(t, err)
		authorization := signWikiReleaseAuthorization(
			t, fixture.publishPrivateKey, ready, reviewed.HumanDecision.Nonce,
			reviewed.HumanDecision.ExpiresAt,
		)
		receipt, err := fixture.authority.ActivateReviewed(
			fixture.ctx, principal, rawDecision, authorization,
		)
		require.NoError(t, err)
		normalizeSchemaWikiPreparationAsPostgresJSONB(t, fixture, ready.ID)
		normalizeSchemaWikiReleaseMembersAsPostgresJSONB(t, fixture, receipt.ReleaseID)
		expected := schemaWikiReleaseMemberByRef(t, reviewed.Release, "field:product_code")

		current, err := fixture.adapter.ReadCurrentSchemaMember(
			fixture.ctx, principal, scope, expected.MemberRef,
		)
		require.NoError(t, err)
		require.Equal(t, []byte(expected.Payload), []byte(current.Payload))

		pin, err := fixture.authority.BeginPinnedRead(fixture.ctx, principal, scope)
		require.NoError(t, err)
		pinned, err := fixture.adapter.ReadPinnedSchemaMember(
			fixture.ctx, principal, pin, expected.MemberRef,
		)
		require.NoError(t, err)
		require.Equal(t, []byte(expected.Payload), []byte(pinned.Payload))

		results, err := fixture.adapter.SearchCurrentSchemaMembers(
			fixture.ctx, principal, scope, "product_code",
		)
		require.NoError(t, err)
		require.Len(t, results, 1)
		require.Equal(t, []byte(expected.Payload), []byte(results[0].Payload))
	})
}

func TestSchemaWikiPreparationCustodyStrictlyCanonicalizesJSONBAndRejectsDrift(t *testing.T) {
	t.Parallel()
	principal, scope, reviewed := schemaWikiReviewedDraft(t)
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	draft := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
	canonical := append(json.RawMessage(nil), draft.Manifest...)
	normalized := schemaWikiPostgresJSONBText(t, canonical)
	require.NotEqual(t, []byte(canonical), normalized)
	var normalizedCustody schemaWikiPreparationCustodyV1
	decoder := json.NewDecoder(bytes.NewReader(normalized))
	decoder.DisallowUnknownFields()
	require.NoError(t, decoder.Decode(&normalizedCustody))
	var normalizedTrailing any
	require.ErrorIs(t, decoder.Decode(&normalizedTrailing), io.EOF)
	require.NoError(t, canonicalizeSchemaWikiReleasePayloads(&normalizedCustody.Release))
	var originalCustody schemaWikiPreparationCustodyV1
	require.NoError(t, json.Unmarshal(canonical, &originalCustody))
	originalRelease := mustSchemaWikiJSON(t, originalCustody.Release)
	normalizedRelease := mustSchemaWikiJSON(t, normalizedCustody.Release)
	if !bytes.Equal(originalRelease, normalizedRelease) {
		difference := 0
		for difference < len(originalRelease) && difference < len(normalizedRelease) &&
			originalRelease[difference] == normalizedRelease[difference] {
			difference++
		}
		leftEnd, rightEnd := difference+80, difference+80
		if leftEnd > len(originalRelease) {
			leftEnd = len(originalRelease)
		}
		if rightEnd > len(normalizedRelease) {
			rightEnd = len(normalizedRelease)
		}
		t.Fatalf("normalized release differs at byte %d: original=%q normalized=%q",
			difference, originalRelease[difference:leftEnd], normalizedRelease[difference:rightEnd])
	}
	require.NoError(t, types.ValidateKnowledgeWikiRelease(
		normalizedCustody.Release, normalizedCustody.Release.SchemaPack,
	))
	require.NoError(t, types.ValidateSchemaWikiReviewBundle(
		normalizedCustody.ReviewBundle, normalizedCustody.Release,
	))
	require.NoError(t, types.ValidateSchema67CandidateEvidenceAuthorityV1(
		normalizedCustody.CandidateEvidenceAuthority, normalizedCustody.Release,
	))

	_, replayed, err := parseSchemaWikiPreparationCustody(normalized)
	require.NoError(t, err)
	require.Equal(t, []byte(canonical), []byte(replayed))

	withUnknown := map[string]any{}
	require.NoError(t, json.Unmarshal(canonical, &withUnknown))
	withUnknown["foreign_authority"] = true
	_, _, err = parseSchemaWikiPreparationCustody(mustSchemaWikiJSON(t, withUnknown))
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
	var nestedUnknown map[string]any
	require.NoError(t, json.Unmarshal(
		mustSchemaWikiJSON(t, originalCustody.CandidateEvidenceAuthority), &nestedUnknown,
	))
	nestedUnknown["foreign_authority"] = true
	withUnknown = map[string]any{}
	require.NoError(t, json.Unmarshal(canonical, &withUnknown))
	withUnknown["candidate_evidence_authority"] = nestedUnknown
	_, _, err = parseSchemaWikiPreparationCustody(mustSchemaWikiJSON(t, withUnknown))
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
	_, _, err = parseSchemaWikiPreparationCustody(append(append([]byte(nil), canonical...), []byte(" {}")...))
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)

	reordered := originalCustody
	reordered.CandidateEvidenceAuthority = cloneSchemaWikiEvidenceAuthority(
		t, originalCustody.CandidateEvidenceAuthority,
	)
	reordered.CandidateEvidenceAuthority.JoinReceipts[0], reordered.CandidateEvidenceAuthority.JoinReceipts[1] =
		reordered.CandidateEvidenceAuthority.JoinReceipts[1], reordered.CandidateEvidenceAuthority.JoinReceipts[0]
	resealSchemaWikiEvidenceAuthority(t, &reordered.CandidateEvidenceAuthority)
	_, _, err = parseSchemaWikiPreparationCustody(mustSchemaWikiJSON(t, reordered))
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid,
		"outer-rehashed join order drift must not replace the frozen Candidate evidence order")

	missingPreimage := originalCustody
	missingPreimage.CandidateEvidenceAuthority = cloneSchemaWikiEvidenceAuthority(
		t, originalCustody.CandidateEvidenceAuthority,
	)
	missingPreimage.CandidateEvidenceAuthority.SourceAuthorities[0].LiveRevisionSourceReceipt =
		types.LiveRevisionSourceReceiptV1{}
	_, _, err = parseSchemaWikiPreparationCustody(mustSchemaWikiJSON(t, missingPreimage))
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)

	foreignScope := originalCustody
	foreignScope.CandidateEvidenceAuthority = cloneSchemaWikiEvidenceAuthority(
		t, originalCustody.CandidateEvidenceAuthority,
	)
	source := &foreignScope.CandidateEvidenceAuthority.SourceAuthorities[0]
	source.LiveRevisionSourceReceipt.WikiKBID = "wiki-kb-foreign"
	source.LiveRevisionSourceReceipt.SourceReceiptSHA256 = ""
	sourceDigest, sourceErr := types.ComputeLiveRevisionSourceReceiptSHA256(
		source.LiveRevisionSourceReceipt,
	)
	require.NoError(t, sourceErr)
	source.LiveRevisionSourceReceipt.SourceReceiptSHA256 = sourceDigest
	for index := range foreignScope.CandidateEvidenceAuthority.JoinReceipts {
		join := &foreignScope.CandidateEvidenceAuthority.JoinReceipts[index]
		if join.SourceSHA256 != source.SourceSHA256 {
			continue
		}
		join.LiveRevisionSourceReceipt = source.LiveRevisionSourceReceipt
		join.LiveRevisionSourceReceiptSHA256 = sourceDigest
	}
	resealSchemaWikiEvidenceAuthority(t, &foreignScope.CandidateEvidenceAuthority)
	foreignRaw := mustSchemaWikiJSON(t, foreignScope)
	_, _, err = parseSchemaWikiPreparationCustody(foreignRaw)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid,
		"scope drift changes the join receipt hash and cannot replace the release-bound citation ID")

	drifted := *draft
	drifted.Manifest = normalized
	drifted.ManifestDigest = schemaWikiDifferentSHA(draft.ManifestDigest)
	_, err = validateSchemaWikiPreparation(&drifted, types.WikiReleasePreparationDraft, scope)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)

	unknownSnapshot := draft.Members[0]
	var payload map[string]any
	require.NoError(t, json.Unmarshal(unknownSnapshot.Payload, &payload))
	payload["foreign_authority"] = true
	unknownSnapshot.Payload = mustSchemaWikiJSON(t, payload)
	_, ok := schemaWikiNormalizeStoredSnapshot(unknownSnapshot, draft.Members[0])
	require.False(t, ok)
	trailingSnapshot := draft.Members[0]
	trailingSnapshot.Payload = append(
		append(json.RawMessage(nil), trailingSnapshot.Payload...), []byte(" {}")...,
	)
	_, ok = schemaWikiNormalizeStoredSnapshot(trailingSnapshot, draft.Members[0])
	require.False(t, ok)
}

func schemaWikiReleaseMemberByRef(
	t *testing.T,
	release types.KnowledgeWikiReleaseV1,
	memberRef string,
) types.SchemaWikiMemberV1 {
	t.Helper()
	for _, member := range release.Members {
		if member.MemberRef == memberRef {
			return member
		}
	}
	t.Fatalf("member %s not found", memberRef)
	return types.SchemaWikiMemberV1{}
}

func TestSchemaWikiGenericSameSlugActiveAndReadyFailClosed(t *testing.T) {
	t.Parallel()
	adapter, _, _, principal, scope := newGenericSchemaWikiReadFixture(t)
	ctx := schemaWikiHumanContext(principal, scope, types.TenantRoleAdmin)

	active, err := adapter.ReadCurrentSchemaMember(ctx, principal, scope, "field:product_code")
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
	require.Nil(t, active)
	prepared, err := adapter.ReadReviewedPreparationMember(
		ctx, principal, scope, "preparation-reviewed", "field:product_code",
	)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
	require.Nil(t, prepared)
}

func TestSchemaWikiNoActiveFailsTypedWithoutGenericFallback(t *testing.T) {
	t.Parallel()
	adapter, _, _, principal, scope := newGenericSchemaWikiReadFixture(t)
	scope.WikiKBID = "wiki-without-head"
	scope.SpaceID = "space-without-head"
	principal.SpaceID = scope.SpaceID

	read, err := adapter.ReadCurrentSchemaMember(
		context.Background(), principal, scope, "field:product_code",
	)
	require.ErrorIs(t, err, ErrNoSchemaWikiActiveRelease)
	require.Nil(t, read)
}
