package service

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type conceptKnowledgeStub830G2 struct {
	knowledge *types.Knowledge
	revision  *types.KnowledgeRevision
	source    *types.KnowledgeRevisionSource
	resource  *types.StoredResource
}

func (s *conceptKnowledgeStub830G2) GetKnowledgeByID(context.Context, uint64, string) (*types.Knowledge, error) {
	return s.knowledge, nil
}
func (s *conceptKnowledgeStub830G2) GetRevision(context.Context, string, int64) (*types.KnowledgeRevision, error) {
	return s.revision, nil
}
func (s *conceptKnowledgeStub830G2) GetRevisionSource(context.Context, uint64, string, int64) (*types.KnowledgeRevisionSource, *types.StoredResource, error) {
	return s.source, s.resource, nil
}

type conceptChunksStub830G2 struct{ chunks []*types.Chunk }

func (s conceptChunksStub830G2) ListChunksByKnowledgeID(context.Context, uint64, string) ([]*types.Chunk, error) {
	return s.chunks, nil
}

type conceptFixedStub830G2 struct{ pdf []byte }

func (s conceptFixedStub830G2) ReadFixedRevision(context.Context, string, int64, string, string, int) ([]byte, error) {
	return append([]byte(nil), s.pdf...), nil
}

type conceptDocReaderStub830G2 struct {
	result  *types.ReadResult
	request *types.ReadRequest
}

func (s *conceptDocReaderStub830G2) Read(_ context.Context, request *types.ReadRequest) (*types.ReadResult, error) {
	s.request = request
	return s.result, nil
}

func testSHA830G2(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])
}

func testNativeResult830G2(t *testing.T) (*types.ReadResult, string) {
	t.Helper()
	markdown := "A😀\n\n中"
	identity := conceptNativeParserIdentity830G2{
		ProducerContract: "weknora.docreader.builtin-pdfium-charbox.v1",
		CaptureMode:      "builtin-pdfium-charbox-v1", Pypdfium2Version: "5.8.0", PDFiumVersion: "7543",
	}
	identityRaw, err := canonicalJSON830G2(identity)
	require.NoError(t, err)
	identitySHA := testSHA830G2(string(identityRaw))
	projection := conceptNativeProjection830G2{
		Contract:     "builtin-pdfium-native-locators.v1",
		SourceSHA256: testSHA830G2("pdf"), MarkdownSHA256: testSHA830G2(markdown),
		CoordinateSpace: "normalized_0_1e6_top_left",
		ParserIdentity:  identity, ParserIdentitySHA256: identitySHA,
		Pages: []conceptNativePage830G2{
			{PageNumber: 1, GlobalCodepointStart: 0, GlobalCodepointEnd: 2,
				PageTextSHA256: testSHA830G2("A😀"), WidthPoints: "100", HeightPoints: "200",
				BBoxes: []conceptNativeBBox830G2{
					{GlobalCodepointStart: 0, GlobalCodepointEnd: 1, BBox: [4]int{100000, 800000, 200000, 900000}},
					{GlobalCodepointStart: 1, GlobalCodepointEnd: 2, BBox: [4]int{200000, 800000, 400000, 900000}},
				}},
			{PageNumber: 2, GlobalCodepointStart: 4, GlobalCodepointEnd: 5,
				PageTextSHA256: testSHA830G2("中"), WidthPoints: "100", HeightPoints: "200",
				BBoxes: []conceptNativeBBox830G2{{GlobalCodepointStart: 4, GlobalCodepointEnd: 5, BBox: [4]int{250000, 500000, 500000, 750000}}}},
		},
	}
	sanitized, err := canonicalJSON830G2(projection)
	require.NoError(t, err)
	digest := testSHA830G2(string(sanitized))
	return &types.ReadResult{
		MarkdownContent: markdown,
		NativeStructure: &types.NativeStructureArtifact{
			SchemaVersion: projection.Contract, SourceSHA256: projection.SourceSHA256,
			RawSHA256: digest, SanitizedSHA256: digest, SanitizedJSON: sanitized,
		},
	}, identitySHA
}

func TestConceptNativeQuote830G2RequiresExactUniquePageTextAndCompleteBoxes(t *testing.T) {
	result, identitySHA := testNativeResult830G2(t)
	bbox, err := resolveConceptNativeQuote830G2(result, testSHA830G2("pdf"), identitySHA, 1, "A😀")
	require.NoError(t, err)
	require.Equal(t, ConceptCitationBBox830G2{
		CoordinateSpace: "normalized_0_1e6_top_left",
		X0:              100000, Y0: 800000, X1: 400000, Y1: 900000,
	}, bbox)

	duplicate := *result
	duplicate.MarkdownContent = "A😀A😀\n\n中"
	projection := conceptNativeProjection830G2{}
	require.NoError(t, json.Unmarshal(result.NativeStructure.SanitizedJSON, &projection))
	projection.MarkdownSHA256 = testSHA830G2(duplicate.MarkdownContent)
	projection.Pages[0].GlobalCodepointEnd = 4
	projection.Pages[0].PageTextSHA256 = testSHA830G2("A😀A😀")
	projection.Pages[1].GlobalCodepointStart = 6
	projection.Pages[1].GlobalCodepointEnd = 7
	projection.Pages[1].BBoxes[0].GlobalCodepointStart = 6
	projection.Pages[1].BBoxes[0].GlobalCodepointEnd = 7
	projection.Pages[0].BBoxes = append(projection.Pages[0].BBoxes,
		conceptNativeBBox830G2{GlobalCodepointStart: 2, GlobalCodepointEnd: 3, BBox: [4]int{100000, 700000, 200000, 800000}},
		conceptNativeBBox830G2{GlobalCodepointStart: 3, GlobalCodepointEnd: 4, BBox: [4]int{200000, 700000, 400000, 800000}},
	)
	raw, err := canonicalJSON830G2(projection)
	require.NoError(t, err)
	digest := testSHA830G2(string(raw))
	duplicate.NativeStructure = &types.NativeStructureArtifact{SchemaVersion: projection.Contract,
		SourceSHA256: projection.SourceSHA256, RawSHA256: digest, SanitizedSHA256: digest, SanitizedJSON: raw}
	_, err = resolveConceptNativeQuote830G2(&duplicate, testSHA830G2("pdf"), identitySHA, 1, "A😀")
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)

	missingBox := *result
	projection = conceptNativeProjection830G2{}
	require.NoError(t, json.Unmarshal(result.NativeStructure.SanitizedJSON, &projection))
	projection.Pages[0].BBoxes = projection.Pages[0].BBoxes[:1]
	raw, err = canonicalJSON830G2(projection)
	require.NoError(t, err)
	digest = testSHA830G2(string(raw))
	missingBox.NativeStructure = &types.NativeStructureArtifact{SchemaVersion: projection.Contract,
		SourceSHA256: projection.SourceSHA256, RawSHA256: digest, SanitizedSHA256: digest, SanitizedJSON: raw}
	_, err = resolveConceptNativeQuote830G2(&missingBox, testSHA830G2("pdf"), identitySHA, 1, "A😀")
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
}

func TestConceptSourceAuthority830G2ReplaysDurableManifestChunkAndFixedPDF(t *testing.T) {
	result, parserIdentity := testNativeResult830G2(t)
	pdf := []byte("pdf")
	chunk := &types.Chunk{ID: "chunk-1", TenantID: 1, KnowledgeID: "knowledge-1", KnowledgeBaseID: "raw-1", Content: "prefix A😀 suffix", ChunkIndex: 0, ParseAttempt: 1}
	manifest, err := types.ComputeRevisionManifestDigest("knowledge-1", 1, []types.RevisionManifestChunk{{ID: chunk.ID, Index: 0, Content: chunk.Content}})
	require.NoError(t, err)
	pageCount := 2
	source := &types.KnowledgeRevisionSource{TenantID: 1, KnowledgeID: "knowledge-1", ParseAttempt: 1, ResourceID: "resource-1", ResourceHandle: "resourcehandle12345678", FileSHA256: testSHA830G2("pdf"), ObjectSHA256: testSHA830G2("pdf"), Size: int64(len(pdf)), MimeType: "application/pdf", PageCount: &pageCount, ManifestAlgorithm: types.RevisionManifestAlgorithm, ManifestDigest: manifest, ChunkCount: 1, ImmutableLocator: types.BuildResourcePath("resourcehandle12345678"), RetentionState: types.KnowledgeRevisionSourcePinned}
	source.RevisionSourceID, err = types.ComputeKnowledgeRevisionSourceID(*source)
	require.NoError(t, err)
	source.BindingDigest, err = types.ComputeKnowledgeRevisionSourceBindingDigest(*source)
	require.NoError(t, err)
	repo := &conceptKnowledgeStub830G2{knowledge: &types.Knowledge{ID: "knowledge-1", TenantID: 1, KnowledgeBaseID: "raw-1", FileType: "pdf", FileName: "source.pdf"}, revision: &types.KnowledgeRevision{KnowledgeID: "knowledge-1", ParseAttempt: 1, FileSHA256: source.FileSHA256, ManifestAlgorithm: types.RevisionManifestAlgorithm, ManifestDigest: manifest, ChunkCount: 1}, source: source, resource: &types.StoredResource{ID: "resource-1", TenantID: 1}}
	doc := &conceptDocReaderStub830G2{result: result}
	now := time.Unix(1_800_000_000, 0).UTC()
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x72}, ed25519.SeedSize))
	codec, err := NewSchemaWikiCitationTokenCodec("citation-key", map[string]ed25519.PrivateKey{"citation-key": privateKey}, func() time.Time { return now })
	require.NoError(t, err)
	bridge := &ConceptSourceAuthorityService830G2{fixed: conceptFixedStub830G2{pdf: pdf}, knowledge: repo, revisions: repo, chunks: conceptChunksStub830G2{chunks: []*types.Chunk{chunk}}, docreader: doc, codec: codec}
	quoteStart := 7
	evidence := types.ConceptEvidence830G2{ConceptSourceIdentity830G2: types.ConceptSourceIdentity830G2{TenantID: 1, SpaceID: "space-1", RawKBID: "raw-1", KnowledgeID: "knowledge-1", ParseAttempt: 1, RevisionID: source.RevisionSourceID, SourceHash: source.FileSHA256, ParseHash: manifest, ParserIdentity: parserIdentity}, SourceType: "DOCUMENT", BlockID: chunk.ID, PageNumber: 1, OffsetUnit: "UNICODE_CODE_POINT", Start: quoteStart, End: quoteStart + 2, Quote: "A😀", QuoteHash: testSHA830G2("A😀")}
	scope := types.WikiReleaseScope{TenantID: 1, SpaceID: "space-1", RawKBID: "raw-1", WikiKBID: "wiki-1"}
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(1))
	sourceBlock := types.ConceptSourceBlock830G2{ConceptSourceIdentity830G2: evidence.ConceptSourceIdentity830G2, BlockID: chunk.ID, PageNumber: 1, Text: chunk.Content, SourceType: "DOCUMENT"}
	_, bbox, err := bridge.verifyEvidence(ctx, scope, evidence, &sourceBlock)
	require.NoError(t, err)
	require.Equal(t, 100000, bbox.X0)
	require.Equal(t, map[string]string{"pdf_native_structure_capture": "builtin-pdfium-charbox-v1"}, doc.request.ParserEngineOverrides)
	require.Equal(t, "builtin", doc.request.ParserEngine)
	authorityRequest := ConceptCitationAuthorityRequest830G2{Scope: scope, ReleaseID: "release-1", ActivationEpoch: 1, CandidateHash: testSHA830G2("candidate"), MemberID: "member-1", CitationID: "citation-123456789012345678901234", Evidence: evidence, SourceBlock: sourceBlock}
	authority, err := bridge.IssueConceptCitationAuthority830G2(ctx, authorityRequest)
	require.NoError(t, err)
	now = now.Add(2 * time.Second)
	opened, err := bridge.ReadConceptCitationByOpaqueToken830G2(ctx, scope, authority.OpaqueToken, authorityRequest)
	require.NoError(t, err)
	require.Equal(t, pdf, opened)

	evidence.Start++
	_, _, err = bridge.verifyEvidence(context.Background(), scope, evidence, &sourceBlock)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
}

func TestConceptCitationToken830G2UsesIndependentSigningDomain(t *testing.T) {
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x61}, ed25519.SeedSize))
	now := time.Unix(1_800_000_000, 0).UTC()
	codec, err := NewSchemaWikiCitationTokenCodec("citation-key", map[string]ed25519.PrivateKey{"citation-key": privateKey}, func() time.Time { return now })
	require.NoError(t, err)
	authority := ConceptCitationContentAuthority830G2{
		Contract: "concept-citation-content-authority.830.g2.v1", TokenKeyID: "citation-key",
		ReleaseID: "release-1", ActivationEpoch: 2, CandidateHash: testSHA830G2("candidate"),
		MemberID: "member-1", CitationID: "citation-5e3d5cbaee7b3c4f8a638b35",
		Scope: types.WikiReleaseScope{TenantID: 1, SpaceID: "space", RawKBID: "raw", WikiKBID: "wiki"},
		Source: types.ConceptSourceIdentity830G2{TenantID: 1, SpaceID: "space", RawKBID: "raw", KnowledgeID: "knowledge", ParseAttempt: 1,
			RevisionID: testSHA830G2("revision"), SourceHash: testSHA830G2("pdf"), ParseHash: testSHA830G2("manifest"), ParserIdentity: testSHA830G2("parser")},
		RevisionSource: ConceptRevisionSourceAuthority830G2{BindingDigest: testSHA830G2("binding"), FileSHA256: testSHA830G2("pdf"), PageCount: 2},
		BlockID:        "chunk-1", PageNumber: 1, QuoteHash: testSHA830G2("A😀"),
		BBox:          ConceptCitationBBox830G2{CoordinateSpace: "normalized_0_1e6_top_left", X0: 1, Y0: 2, X1: 3, Y1: 4},
		ExpiresAtUnix: now.Add(schemaWikiCitationTokenTTL).Unix(),
	}
	digest, err := computeConceptCitationAuthorityDigest830G2(authority)
	require.NoError(t, err)
	require.Equal(t, "a9a00635b599b8fd5a9f5f30c3a5fe8a104d9c805ec9b5d3191a2589021fb6e7", digest)
	authority.AuthorityDigest = digest
	token, err := codec.issueConcept830G2(authority.Scope, authority, now)
	require.NoError(t, err)
	authority.OpaqueToken = token

	claims, err := codec.verifyConcept830G2(token)
	require.NoError(t, err)
	require.Equal(t, authority.AuthorityDigest, claims.Authority.AuthorityDigest)
	_, err = codec.verify(token)
	require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
	_, err = codec.verifyGoldenEvidence(token)
	require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
	bridge := &ConceptSourceAuthorityService830G2{codec: codec}
	release := &WikiReleaseService{conceptSourceAuthorityVerifier830G2: bridge}
	schema := NewSchemaWikiService(release, nil)
	route, err := schema.ResolveSchemaCitationContentRouteAuthority(context.Background(), token)
	require.NoError(t, err)
	require.Equal(t, "release", route.Kind)
	require.Equal(t, authority.Scope, route.Scope)
	require.Equal(t, authority.ReleaseID, route.ReleaseID)
}

func TestConceptCitationAuthority830G2FrozenCrossLanguageVector(t *testing.T) {
	raw, err := os.ReadFile("testdata/concept_source_authority_830_g2_vector.json")
	require.NoError(t, err)
	var vector struct {
		ClockUnix                    int64                                `json:"clock_unix"`
		CitationIdentityPreimageJSON string                               `json:"citation_identity_preimage_json"`
		AuthorityCanonicalJSON       string                               `json:"authority_canonical_json"`
		AuthorityHashDomain          string                               `json:"authority_hash_domain"`
		AuthorityDigest              string                               `json:"authority_digest"`
		Authority                    ConceptCitationContentAuthority830G2 `json:"authority"`
	}
	require.NoError(t, json.Unmarshal(raw, &vector))
	canonical, err := canonicalJSON830G2(mapWithoutConceptAuthorityDigests830G2(vector.Authority))
	require.NoError(t, err)
	require.Equal(t, vector.AuthorityCanonicalJSON, string(canonical))
	require.Equal(t, "concept-citation-content-authority.830.g2.v1\n", vector.AuthorityHashDomain)
	digest, err := computeConceptCitationAuthorityDigest830G2(vector.Authority)
	require.NoError(t, err)
	require.Equal(t, vector.AuthorityDigest, digest)
	identityDigest := testSHA830G2(vector.CitationIdentityPreimageJSON)
	require.Equal(t, "citation-"+identityDigest[:24], vector.Authority.CitationID)
	require.Equal(t, vector.ClockUnix+int64(schemaWikiCitationTokenTTL/time.Second), vector.Authority.ExpiresAtUnix)
}

func TestConceptLegacyProof830G2CannotAuthorizeSameEvidenceOnNewPage(t *testing.T) {
	evidence := types.ConceptEvidence830G2{Quote: "legacy"}
	canonical, err := canonicalJSON830G2(evidence)
	require.NoError(t, err)
	proofs := map[string]conceptLegacyProof830G2{"field-old\x00" + testSHA256Bytes830G2(canonical): {}}
	_, ok := conceptLegacyProofForOccurrence830G2("field_assertion", "field-old", evidence, proofs)
	require.True(t, ok)
	_, ok = conceptLegacyProofForOccurrence830G2("free_wiki_item", "free-new", evidence, proofs)
	require.False(t, ok)
}

func TestConceptLegacyCarryover830G2AllowsOnlyAddedConceptNavigation(t *testing.T) {
	value := "covered"
	migrated := types.ConceptFieldAssertion830G2{
		SpaceID: "space-1", EntityID: "entity-1", FieldKey: "eligibility",
		State: "present", Value: &value, Attempted: true,
		Evidence:   []types.ConceptEvidence830G2{{Quote: "legacy", QuoteHash: testSHA830G2("legacy")}},
		ConceptIDs: []string{}, Conditions: []string{"adult"}, Exceptions: []string{"excluded"},
		EntityVersion: "v1", ValidTime: "2026",
	}
	linked := migrated
	linked.ConceptIDs = []string{"concept-linked"}
	target, ok := conceptLegacyCarryoverTargetField830G2(migrated, []types.ConceptFieldAssertion830G2{migrated}, []types.ConceptFieldAssertion830G2{linked})
	require.True(t, ok)
	require.Equal(t, linked, target)
	linkedAgain := linked
	linkedAgain.ConceptIDs = []string{"concept-linked", "concept-added-later"}
	target, ok = conceptLegacyCarryoverTargetField830G2(migrated, []types.ConceptFieldAssertion830G2{linked}, []types.ConceptFieldAssertion830G2{linkedAgain})
	require.True(t, ok)
	require.Equal(t, linkedAgain, target)
	_, ok = conceptLegacyCarryoverTargetField830G2(migrated, []types.ConceptFieldAssertion830G2{linkedAgain}, []types.ConceptFieldAssertion830G2{linked})
	require.False(t, ok, "a later G2 release cannot remove an existing concept link")

	changedValue := linked
	changed := "changed"
	changedValue.Value = &changed
	_, ok = conceptLegacyCarryoverTargetField830G2(migrated, []types.ConceptFieldAssertion830G2{migrated}, []types.ConceptFieldAssertion830G2{changedValue})
	require.False(t, ok, "a changed value must use current native evidence")

	changedEvidence := linked
	changedEvidence.Evidence = append([]types.ConceptEvidence830G2(nil), linked.Evidence...)
	changedEvidence.Evidence[0].Quote = "changed"
	_, ok = conceptLegacyCarryoverTargetField830G2(migrated, []types.ConceptFieldAssertion830G2{migrated}, []types.ConceptFieldAssertion830G2{changedEvidence})
	require.False(t, ok, "changed evidence cannot consume the old C5 proof")
}

func TestConceptExistingSources830G2CloseOverBaseEvidenceOnly(t *testing.T) {
	evidence := types.ConceptEvidence830G2{
		ConceptSourceIdentity830G2: types.ConceptSourceIdentity830G2{
			TenantID: 1, SpaceID: "space-1", RawKBID: "raw-1", KnowledgeID: "knowledge-1", ParseAttempt: 1,
			RevisionID: "revision-1", SourceHash: testSHA830G2("pdf"), ParseHash: testSHA830G2("parse"), ParserIdentity: testSHA830G2("parser"),
		},
		SourceType: "DOCUMENT", BlockID: "chunk-1", PageNumber: 1,
		OffsetUnit: "UNICODE_CODE_POINT", Start: 0, End: 1, Quote: "A", QuoteHash: testSHA830G2("A"),
	}
	source := types.ConceptSourceBlock830G2{
		ConceptSourceIdentity830G2: evidence.ConceptSourceIdentity830G2,
		BlockID:                    evidence.BlockID, PageNumber: evidence.PageNumber, SourceType: evidence.SourceType, Text: "A",
	}
	padding := source
	padding.BlockID = "unreferenced-padding"
	bundle := types.ConceptCandidateBundle830G2{Request: types.ConceptCompileRequest830G2{
		Sources:        []types.ConceptSourceBlock830G2{source, padding},
		ExistingFields: []types.ConceptFieldAssertion830G2{{Evidence: []types.ConceptEvidence830G2{evidence}}},
	}}
	keys, err := conceptReferencedExistingSourceKeys830G2(bundle)
	require.NoError(t, err)
	require.Equal(t, map[string]struct{}{evidence.RevisionID + "\x00" + evidence.BlockID: {}}, keys)
	require.NotContains(t, keys, padding.RevisionID+"\x00"+padding.BlockID)

	drifted := bundle
	drifted.Request.Sources = append([]types.ConceptSourceBlock830G2(nil), bundle.Request.Sources...)
	drifted.Request.Sources[0].ParserIdentity = testSHA830G2("other-parser")
	_, err = conceptReferencedExistingSourceKeys830G2(drifted)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)

	drifted = bundle
	drifted.Request.Sources = append([]types.ConceptSourceBlock830G2(nil), bundle.Request.Sources...)
	drifted.Request.Sources[0].Text = "B"
	_, err = conceptReferencedExistingSourceKeys830G2(drifted)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)

	drifted = bundle
	drifted.Request.ExistingFields = append([]types.ConceptFieldAssertion830G2(nil), bundle.Request.ExistingFields...)
	drifted.Request.ExistingFields[0].Evidence = append([]types.ConceptEvidence830G2(nil), evidence)
	drifted.Request.ExistingFields[0].Evidence[0].End = 2
	_, err = conceptReferencedExistingSourceKeys830G2(drifted)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
}

func TestConceptLegacyEvidenceReuse830G2ReviewFailsWithoutNativeAuthority(t *testing.T) {
	fixture, schema := conceptReleaseFixture830G2(t)
	bundle, err := types.ParseConceptCandidateBundle830G2(conceptBundleVector830G2(t))
	require.NoError(t, err)
	require.NotEmpty(t, bundle.CompileResult.Output.Fields)
	require.NotEmpty(t, bundle.CompileResult.Output.Pages)
	field := bundle.CompileResult.Output.Fields[0]
	require.NotEmpty(t, field.Evidence)
	legacyEvidence := field.Evidence[0]
	require.Contains(t, bundle.CompileResult.Output.Pages[0].Evidence, legacyEvidence,
		"the frozen bundle must reuse the legacy evidence on a new page")
	fieldID, err := field.FieldAssertionID()
	require.NoError(t, err)
	canonical, err := canonicalJSON830G2(legacyEvidence)
	require.NoError(t, err)

	bridge := &ConceptSourceAuthorityService830G2{
		legacyProofResolver: func(context.Context, types.WikiReleaseScope, types.ConceptCandidateBundle830G2) (map[string]conceptLegacyProof830G2, error) {
			return map[string]conceptLegacyProof830G2{
				fieldID + "\x00" + testSHA256Bytes830G2(canonical): {},
			}, nil
		},
		// Native dependencies are deliberately absent. The legacy proof belongs
		// only to the unchanged field occurrence and cannot authorize the page.
	}
	fixture.service.conceptSourceAuthorityVerifier830G2 = bridge
	draft, err := schema.CreateConceptFreeWikiDraft830G2(
		fixture.ctx, fixture.principal1, fixture.scope,
		"g2-legacy-reuse-native-required", conceptBundleVector830G2(t),
	)
	require.NoError(t, err)
	rawDecision, _ := conceptDecision830G2(t, fixture, draft, "g2-legacy-reuse-native-required")

	_, err = schema.ReviewSchemaDraft(fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
	persisted, readErr := fixture.repo.GetDraftPreparation(fixture.ctx, fixture.scope, draft.ID)
	require.NoError(t, readErr)
	require.Equal(t, types.WikiReleasePreparationDraft, persisted.Status)
}

func TestConceptCitationAuthority830G2HalfConstructedServicesFailClosed(t *testing.T) {
	var nilBridge *ConceptSourceAuthorityService830G2
	_, err := nilBridge.ResolveConceptCitationRouteAuthority830G2("token")
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
	_, err = nilBridge.ReadConceptCitationByOpaqueToken830G2(context.Background(), types.WikiReleaseScope{}, "token", ConceptCitationAuthorityRequest830G2{})
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)

	bridge := &ConceptSourceAuthorityService830G2{}
	_, err = bridge.ResolveConceptCitationRouteAuthority830G2("token")
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
	_, err = bridge.ReadConceptCitationByOpaqueToken830G2(context.Background(), types.WikiReleaseScope{}, "token", ConceptCitationAuthorityRequest830G2{})
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)

	schema := &SchemaWikiService{conceptSourceAuthority: bridge}
	_, err = schema.IssueConceptCitationAuthority830G2(
		context.Background(), types.WikiReleasePrincipal{}, types.WikiReleaseScope{},
		"release-1", "member-1", "citation-123456789012345678901234",
	)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
}

func TestConceptLegacyCitation830G2MissingRevisionOrFixedReaderFailsClosed(t *testing.T) {
	now := time.Unix(1_800_000_000, 0).UTC()
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x49}, ed25519.SeedSize))
	codec, err := NewSchemaWikiCitationTokenCodec("citation-key", map[string]ed25519.PrivateKey{"citation-key": privateKey}, func() time.Time { return now })
	require.NoError(t, err)
	pageCount := 1
	source := &types.KnowledgeRevisionSource{
		TenantID: 1, KnowledgeID: "knowledge-1", ParseAttempt: 1,
		ResourceID: "resource-1", ResourceHandle: "resourcehandle12345678",
		FileSHA256: testSHA830G2("pdf"), ObjectSHA256: testSHA830G2("pdf"), Size: 3,
		MimeType: "application/pdf", PageCount: &pageCount,
		ManifestAlgorithm: types.RevisionManifestAlgorithm, ManifestDigest: testSHA830G2("manifest"), ChunkCount: 1,
		ImmutableLocator: types.BuildResourcePath("resourcehandle12345678"), RetentionState: types.KnowledgeRevisionSourcePinned,
	}
	source.RevisionSourceID, err = types.ComputeKnowledgeRevisionSourceID(*source)
	require.NoError(t, err)
	source.BindingDigest, err = types.ComputeKnowledgeRevisionSourceBindingDigest(*source)
	require.NoError(t, err)
	evidence := types.ConceptEvidence830G2{
		ConceptSourceIdentity830G2: types.ConceptSourceIdentity830G2{
			TenantID: 1, SpaceID: "space-1", RawKBID: "raw-1", KnowledgeID: "knowledge-1", ParseAttempt: 1,
			RevisionID: source.RevisionSourceID, SourceHash: source.FileSHA256, ParseHash: source.ManifestDigest, ParserIdentity: testSHA830G2("legacy-parser"),
		},
		SourceType: "DOCUMENT", BlockID: "chunk-1", PageNumber: 1, OffsetUnit: "UNICODE_CODE_POINT",
		Start: 0, End: 1, Quote: "A", QuoteHash: testSHA830G2("A"),
	}
	scope := types.WikiReleaseScope{TenantID: 1, SpaceID: "space-1", RawKBID: "raw-1", WikiKBID: "wiki-1"}
	request := ConceptCitationAuthorityRequest830G2{
		Scope: scope, ReleaseID: "release-1", ActivationEpoch: 1, CandidateHash: testSHA830G2("candidate"),
		MemberID: "field-1", CitationID: "citation-123456789012345678901234", Evidence: evidence,
		Bundle: &types.ConceptCandidateBundle830G2{},
	}
	legacyAuthority := &types.SchemaWikiCitationContentAuthorityV1{
		RevisionSource: types.LiveRevisionSourceReceiptV1{RevisionSourceID: source.RevisionSourceID},
		PageNumber:     1, BBox: types.CitationBBoxV1{X0: 1, Y0: 2, X1: 3, Y1: 4},
	}
	canonical, err := canonicalJSON830G2(evidence)
	require.NoError(t, err)
	resolver := func(context.Context, types.WikiReleaseScope, types.ConceptCandidateBundle830G2) (map[string]conceptLegacyProof830G2, error) {
		return map[string]conceptLegacyProof830G2{
			request.MemberID + "\x00" + testSHA256Bytes830G2(canonical): {authority: legacyAuthority},
		}, nil
	}

	withoutRevision := &ConceptSourceAuthorityService830G2{codec: codec, legacyProofResolver: resolver}
	_, _, err = withoutRevision.resolveCitationEvidence830G2(context.Background(), request)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)

	repo := &conceptKnowledgeStub830G2{source: source, resource: &types.StoredResource{ID: source.ResourceID, TenantID: 1}}
	withoutFixed := &ConceptSourceAuthorityService830G2{codec: codec, revisions: repo, legacyProofResolver: resolver}
	_, _, err = withoutFixed.resolveCitationEvidence830G2(context.Background(), request)
	require.NoError(t, err, "the fixture must reach the final fixed-reader boundary")
	trusted := conceptCitationAuthorityFromResolved830G2(request, source, ConceptCitationBBox830G2{CoordinateSpace: "normalized_0_1e6_top_left", X0: 1, Y0: 2, X1: 3, Y1: 4}, codec.activeKeyID, now.Add(schemaWikiCitationTokenTTL).Unix())
	trusted.AuthorityDigest, err = computeConceptCitationAuthorityDigest830G2(trusted)
	require.NoError(t, err)
	token, err := codec.issueConcept830G2(scope, trusted, now)
	require.NoError(t, err)
	_, err = withoutFixed.ReadConceptCitationByOpaqueToken830G2(context.Background(), scope, token, request)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
}

func mapWithoutConceptAuthorityDigests830G2(authority ConceptCitationContentAuthority830G2) map[string]any {
	raw, _ := json.Marshal(authority)
	var value map[string]any
	_ = json.Unmarshal(raw, &value)
	delete(value, "authority_digest")
	delete(value, "opaque_token")
	return value
}
