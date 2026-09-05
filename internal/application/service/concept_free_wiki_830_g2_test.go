package service

import (
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"strings"
	"testing"
	"time"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func conceptG1MigrationFixture830G2(
	t *testing.T,
) (types.EntityPageManifest830G1, validatedSchemaWikiCustody, []types.ConceptSourceBlock830G2) {
	t.Helper()
	manifest, err := types.ParseEntityPageManifest830G1(loadEntityPageGraph830G1ServiceVector(t))
	require.NoError(t, err)
	custody := entityPageGraphSourceCustody830G1(t, manifest)
	quotes := make(map[string]string)
	for _, member := range manifest.Members {
		if member.PageKind != "field" {
			continue
		}
		payload, payloadErr := member.FieldAssertionPayload()
		require.NoError(t, payloadErr)
		for _, citation := range payload.Citations {
			quotes[citation.JoinReceiptSHA256] = citation.QuoteSnapshot
		}
	}
	contentByChunk := make(map[string][]rune)
	for index := range custody.candidateEvidenceAuthority.JoinReceipts {
		join := &custody.candidateEvidenceAuthority.JoinReceipts[index]
		quote := []rune(quotes[join.ReceiptSHA256])
		require.NotEmpty(t, quote)
		content := contentByChunk[join.ChunkID]
		if len(content) > 0 {
			content = append(content, '\n')
		}
		join.QuoteOccurrenceStart = len(content)
		content = append(content, quote...)
		join.QuoteOccurrenceEnd = len(content)
		join.QuoteOccurrenceCount = 1
		contentByChunk[join.ChunkID] = content
		join.ParserIdentitySHA256 = "3454fd9710a63239b956908260913a25bfde1001ab9e1ac1b3cef2742946abf3"
		join.TenantID = 10003
		join.SpaceID = manifest.SpaceID
		join.RawKBID = "raw-g1"
		for _, source := range manifest.InputAuthority.SourceAuthorities {
			if source.SourceRole != join.SourceRole {
				continue
			}
			join.WeKnoraParseAttempt = int64(source.WeKnoraParseAttempt)
			join.LiveRevisionSourceReceipt.TenantID = join.TenantID
			join.LiveRevisionSourceReceipt.SpaceID = join.SpaceID
			join.LiveRevisionSourceReceipt.RawKBID = join.RawKBID
			join.LiveRevisionSourceReceipt.WikiKBID = manifest.WikiKBID
			join.LiveRevisionSourceReceipt.KnowledgeID = source.KnowledgeID
			join.LiveRevisionSourceReceipt.WeKnoraParseAttempt = int64(source.WeKnoraParseAttempt)
			join.LiveRevisionSourceReceipt.FileSHA256 = source.SourceSHA256
			join.LiveRevisionSourceReceipt.ParseManifestSHA256 = source.ParseManifestSHA256
		}
	}
	for chunkID := range contentByChunk {
		text := string(contentByChunk[chunkID])
		digest := sha256.Sum256([]byte(text))
		for index := range custody.candidateEvidenceAuthority.JoinReceipts {
			join := &custody.candidateEvidenceAuthority.JoinReceipts[index]
			if join.ChunkID != chunkID {
				continue
			}
			join.ChunkContentSHA256 = hex.EncodeToString(digest[:])
		}
	}
	sources := make([]types.ConceptSourceBlock830G2, 0, len(custody.candidateEvidenceAuthority.JoinReceipts))
	for _, join := range custody.candidateEvidenceAuthority.JoinReceipts {
		sources = append(sources, types.ConceptSourceBlock830G2{
			ConceptSourceIdentity830G2: types.ConceptSourceIdentity830G2{
				TenantID: join.TenantID, SpaceID: join.SpaceID, RawKBID: join.RawKBID,
				KnowledgeID: join.KnowledgeID, ParseAttempt: join.WeKnoraParseAttempt,
				RevisionID: join.LiveRevisionSourceReceipt.RevisionSourceID,
				SourceHash: join.SourceSHA256, ParseHash: join.ParseManifestSHA256,
				ParserIdentity: join.ParserIdentitySHA256,
			},
			BlockID: join.LocatorRef, PageNumber: join.PageNumber,
			Text: string(contentByChunk[join.ChunkID]), SourceType: "DOCUMENT",
		})
	}
	return manifest, custody, sources
}

type conceptG1NilAuthorityContent830G2 struct {
	schemaWikiGoldenEvidenceContentSpy
}

func (*conceptG1NilAuthorityContent830G2) IssueExactRevision(
	context.Context,
	CitationRevisionReadRequestV1,
) (*types.SchemaWikiCitationContentAuthorityV1, error) {
	return nil, nil
}

type conceptG1DriftAuthorityContent830G2 struct {
	schemaWikiC6CitationContentSpy
}

func (stub *conceptG1DriftAuthorityContent830G2) IssueExactRevision(
	ctx context.Context,
	request CitationRevisionReadRequestV1,
) (*types.SchemaWikiCitationContentAuthorityV1, error) {
	authority, err := stub.schemaWikiC6CitationContentSpy.IssueExactRevision(ctx, request)
	if err != nil || authority == nil {
		return authority, err
	}
	authority.ReleaseID += "-drift"
	authority.AuthoritySHA256, err = types.ComputeSchemaWikiCitationContentAuthoritySHA256(*authority)
	return authority, err
}

func TestConceptG1MigrationAdapterProjectsAllFieldsAndReplaysUsedCitations(t *testing.T) {
	manifest, custody, sources := conceptG1MigrationFixture830G2(t)
	custody.isolatedC6 = true
	custody.experimentID = "g1-c5-migration"
	custody.versionIdentity = strings.Repeat("a", 64)
	custody.revisionSetSHA256 = strings.Repeat("b", 64)
	reader := &schemaWikiFormalCandidatePreviewReaderStub{
		record: wikirepository.SchemaWikiFormalCandidatePreviewRecord{
			TenantID: 10003, KBID: "raw-g1", ExperimentID: custody.experimentID,
			ManifestSHA256: custody.versionIdentity, RevisionSetSHA256: custody.revisionSetSHA256,
			CandidateSHA256: custody.release.CandidateSHA256,
		},
		nativeSourceManifest: []byte(`{"contract":"schema-wiki-c5-manifest.test"}`),
		nativeSourcePDF:      []byte("%PDF-1.7 frozen C5 source"),
	}
	content := &schemaWikiC6CitationContentSpy{}
	migration := &SchemaWikiService{formalCandidatePreview: reader, citationContent: content}
	fields, versions, err := conceptG1ExistingSnapshot830G2(
		context.Background(), types.WikiReleaseScope{
			TenantID: 10003, SpaceID: manifest.SpaceID, RawKBID: "raw-g1", WikiKBID: manifest.WikiKBID,
		}, manifest, custody, sources, migration.verifyConceptG1Citation830G2,
	)
	require.NoError(t, err)
	require.Len(t, fields, manifest.FieldAssertionCount)
	require.Equal(t, map[string]string{manifest.EntityID: manifest.EntityVersionID}, versions)
	require.Equal(t, 17, reader.nativeSourceCalls)
	require.Equal(t, 17, content.issueCurrentCalls)
	require.NotNil(t, content.request.frozenNativeSource)
	require.Equal(t, reader.nativeSourceManifest, content.request.frozenNativeSource.manifest)
	require.Equal(t, reader.nativeSourcePDF, content.request.frozenNativeSource.sourceBytes)
	nilAuthority := &SchemaWikiService{
		formalCandidatePreview: reader,
		citationContent:        &conceptG1NilAuthorityContent830G2{},
	}
	require.ErrorIs(t,
		nilAuthority.verifyConceptG1Citation830G2(context.Background(), custody, content.request),
		ErrSchemaWikiPreparationInvalid,
	)
	driftAuthority := &SchemaWikiService{
		formalCandidatePreview: reader,
		citationContent:        &conceptG1DriftAuthorityContent830G2{},
	}
	require.ErrorIs(t,
		driftAuthority.verifyConceptG1Citation830G2(context.Background(), custody, content.request),
		ErrSchemaWikiPreparationInvalid,
	)

	byKey := make(map[string]types.ConceptFieldAssertion830G2, len(fields))
	for _, field := range fields {
		byKey[field.FieldKey] = field
	}
	known := byKey["insured_eligibility"]
	require.Equal(t, "present", known.State)
	require.Len(t, known.Evidence, 3)
	require.Equal(t, "UNICODE_CODE_POINT", known.Evidence[0].OffsetUnit)
	require.Equal(t, sources[0].ParserIdentity, known.Evidence[0].ParserIdentity)
	member, found := manifest.Member("field", "insured_eligibility")
	require.True(t, found)
	payload, err := member.FieldAssertionPayload()
	require.NoError(t, err)
	require.Len(t, payload.Citations, len(known.Evidence))
	for index, evidence := range known.Evidence {
		// Parsing the frozen G1 manifest above has already validated its
		// schema-wiki-text.v1 domain hash. G2 deliberately uses the raw UTF-8
		// quote hash, so migration must translate instead of copying it.
		rawQuote := sha256.Sum256([]byte(payload.Citations[index].QuoteSnapshot))
		rawQuoteSHA256 := hex.EncodeToString(rawQuote[:])
		require.NotEqual(t, payload.Citations[index].QuoteSHA256, rawQuoteSHA256)
		require.Equal(t, rawQuoteSHA256, evidence.QuoteHash)
	}
	unknown := byKey["product_code"]
	require.Equal(t, "unknown", unknown.State)
	require.Equal(t, "FORMATION_MODE_DEFERRED", *unknown.UnknownReason)
	require.Empty(t, unknown.Evidence)

	tampered := append([]types.ConceptSourceBlock830G2(nil), sources...)
	tampered[0].Text += "漂移"
	_, _, err = conceptG1ExistingSnapshot830G2(
		context.Background(), types.WikiReleaseScope{
			TenantID: 10003, SpaceID: manifest.SpaceID, RawKBID: "raw-g1", WikiKBID: manifest.WikiKBID,
		}, manifest, custody, tampered, migration.verifyConceptG1Citation830G2,
	)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
	_, _, err = conceptG1ExistingSnapshot830G2(
		context.Background(), types.WikiReleaseScope{
			TenantID: 10003, SpaceID: manifest.SpaceID, RawKBID: "raw-g1", WikiKBID: manifest.WikiKBID,
		}, manifest, custody, sources, nil,
	)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
}

func conceptBundleVector830G2(t *testing.T) json.RawMessage {
	t.Helper()
	raw, err := os.ReadFile("../../../harness/tests/fixtures/concept_free_wiki_830_g2_contract_vector.json")
	require.NoError(t, err)
	return raw
}

func conceptReleaseFixture830G2(t *testing.T) (*wikiReleaseFixture, *SchemaWikiService) {
	t.Helper()
	fixture := newWikiReleaseFixture(t, WikiReleaseFaults{})
	fixture.scope = types.WikiReleaseScope{
		TenantID: 1, SpaceID: "space-a", RawKBID: "raw-a", WikiKBID: "wiki-a",
	}
	fixture.principal1.TenantID = 1
	fixture.principal1.SpaceID = "space-a"
	fixture.access.allowed[fixture.principal1.ID] = fixture.scope
	fixture.ctx = schemaWikiHumanContext(fixture.principal1, fixture.scope, types.TenantRoleAdmin)
	// Fixture-only authority: production must inject a verifier backed by
	// server-owned source revisions, coordinates, and current ACLs.
	fixture.service.conceptSourceAuthorityVerifier830G2 = &conceptSourceAuthorityVerifierFake830G2{}
	return fixture, NewSchemaWikiService(fixture.service, nil)
}

type conceptSourceAuthorityVerifierFake830G2 struct {
	err      error
	requests []ConceptSourceAuthorityVerificationRequest830G2
}

func (fake *conceptSourceAuthorityVerifierFake830G2) VerifyConceptSources830G2(
	_ context.Context,
	request ConceptSourceAuthorityVerificationRequest830G2,
) error {
	fake.requests = append(fake.requests, request)
	return fake.err
}

func conceptDecision830G2(
	t *testing.T,
	fixture *wikiReleaseFixture,
	draft *types.WikiReleasePreparation,
	nonce string,
) ([]byte, *types.HumanBatchDecisionReceiptV1) {
	t.Helper()
	fixture.service.humanDecisionVerifier = NewEd25519HumanBatchDecisionVerifier(
		map[string]ed25519.PublicKey{"human-1": fixture.privateKey.Public().(ed25519.PublicKey)},
	)
	decision := &types.HumanBatchDecisionReceiptV1{
		Version: "1", Decision: "approve", PrincipalID: fixture.principal1.ID,
		WikiReleaseScope: fixture.scope, CandidateHash: draft.CandidateDigest,
		HumanBatchHash: draft.ReadyReceiptDigest, ReviewPolicyHash: draft.ReviewPolicyID,
		IssuedAt: 1_000, ExpiresAt: 2_000, Nonce: nonce, SignerKeyID: "human-1",
	}
	unsigned, err := CanonicalHumanBatchDecisionReceiptV1(decision, false)
	require.NoError(t, err)
	decision.Signature = EncodeWikiReleaseSignature(ed25519.Sign(fixture.privateKey, unsigned))
	raw, err := CanonicalHumanBatchDecisionReceiptV1(decision, true)
	require.NoError(t, err)
	return raw, decision
}

func conceptAuthorization830G2(
	t *testing.T,
	fixture *wikiReleaseFixture,
	ready *types.WikiReleasePreparation,
	decision *types.HumanBatchDecisionReceiptV1,
) []byte {
	t.Helper()
	authorization := &types.PublishAuthorizationV0{
		Version: "0", Action: "activate", PreparationID: ready.ID,
		CandidateDigest: ready.CandidateDigest, ManifestDigest: ready.ManifestDigest,
		ReadyReceiptDigest: ready.ReadyReceiptDigest, ReviewDecisionDigest: ready.ReviewDecisionDigest,
		ReviewPolicyID: ready.ReviewPolicyID, TenantID: fixture.scope.TenantID,
		SpaceID: fixture.scope.SpaceID, RawKBID: fixture.scope.RawKBID, WikiKBID: fixture.scope.WikiKBID,
		ExpectedReleaseID:       ready.ExpectedReleaseID,
		ExpectedActivationEpoch: ready.ExpectedActivationEpoch,
		ExpiresAt:               2_000, Nonce: decision.Nonce, SignerKeyID: "signer-1",
	}
	unsigned, err := CanonicalPublishAuthorizationV0(authorization, false)
	require.NoError(t, err)
	authorization.Signature = EncodeWikiReleaseSignature(ed25519.Sign(fixture.privateKey, unsigned))
	raw, err := CanonicalPublishAuthorizationV0(authorization, true)
	require.NoError(t, err)
	return raw
}

func TestConceptSourceAuthorityGate830G2FailsClosed(t *testing.T) {
	t.Run("missing verifier rejects review and preserves draft", func(t *testing.T) {
		fixture, schema := conceptReleaseFixture830G2(t)
		draft, err := schema.CreateConceptFreeWikiDraft830G2(
			fixture.ctx, fixture.principal1, fixture.scope, "g2-source-gate-review", conceptBundleVector830G2(t),
		)
		require.NoError(t, err)
		rawDecision, _ := conceptDecision830G2(t, fixture, draft, "g2-source-gate-review")
		fixture.service.conceptSourceAuthorityVerifier830G2 = nil

		_, err = schema.ReviewSchemaDraft(
			fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision,
		)
		require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
		persisted, readErr := fixture.repo.GetDraftPreparation(fixture.ctx, fixture.scope, draft.ID)
		require.NoError(t, readErr)
		require.Equal(t, types.WikiReleasePreparationDraft, persisted.Status)
		_, readyErr := fixture.repo.GetReadyPreparation(fixture.ctx, fixture.scope, draft.ID)
		require.ErrorIs(t, readyErr, wikirepository.ErrWikiReleaseNotFound)
	})

	t.Run("withdrawn verifier rejects activation and preserves head", func(t *testing.T) {
		fixture, schema := conceptReleaseFixture830G2(t)
		draft, err := schema.CreateConceptFreeWikiDraft830G2(
			fixture.ctx, fixture.principal1, fixture.scope, "g2-source-gate-activate", conceptBundleVector830G2(t),
		)
		require.NoError(t, err)
		rawDecision, decision := conceptDecision830G2(t, fixture, draft, "g2-source-gate-activate")
		ready, err := schema.ReviewSchemaDraft(
			fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision,
		)
		require.NoError(t, err)
		fixture.service.conceptSourceAuthorityVerifier830G2 = nil

		_, err = fixture.service.ActivateReviewed(
			fixture.ctx, fixture.principal1, rawDecision,
			conceptAuthorization830G2(t, fixture, ready, decision),
		)
		require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
		_, headErr := fixture.repo.GetHead(fixture.ctx, fixture.scope)
		require.ErrorIs(t, headErr, wikirepository.ErrWikiReleaseNotFound)
	})

	t.Run("authority drift rejects without promotion", func(t *testing.T) {
		fixture, schema := conceptReleaseFixture830G2(t)
		draft, err := schema.CreateConceptFreeWikiDraft830G2(
			fixture.ctx, fixture.principal1, fixture.scope, "g2-source-gate-drift", conceptBundleVector830G2(t),
		)
		require.NoError(t, err)
		rawDecision, _ := conceptDecision830G2(t, fixture, draft, "g2-source-gate-drift")
		fixture.service.conceptSourceAuthorityVerifier830G2 = &conceptSourceAuthorityVerifierFake830G2{
			err: errors.New("source ACL or revision drift"),
		}

		_, err = schema.ReviewSchemaDraft(
			fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision,
		)
		require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
		_, readErr := fixture.repo.GetDraftPreparation(fixture.ctx, fixture.scope, draft.ID)
		require.NoError(t, readErr)
	})
}

func TestCreateConceptFreeWikiDraft830G2AndReadOnePinnedRelease(t *testing.T) {
	fixture, schema := conceptReleaseFixture830G2(t)
	draft, err := schema.CreateConceptFreeWikiDraft830G2(
		fixture.ctx, fixture.principal1, fixture.scope, "g2-preparation", conceptBundleVector830G2(t),
	)
	require.NoError(t, err)
	require.Equal(t, "57ef3c1044874555a85330fbf7cc8505611c3211a5284ff17f0edf97f945dee5", draft.CandidateDigest)
	require.Len(t, draft.Members, 6)
	require.Equal(t, types.WikiReleasePreparationDraft, draft.Status)

	fixture.service.humanDecisionVerifier = NewEd25519HumanBatchDecisionVerifier(
		map[string]ed25519.PublicKey{"human-1": fixture.privateKey.Public().(ed25519.PublicKey)},
	)
	decision := &types.HumanBatchDecisionReceiptV1{
		Version: "1", Decision: "approve", PrincipalID: fixture.principal1.ID,
		WikiReleaseScope: fixture.scope, CandidateHash: draft.CandidateDigest,
		HumanBatchHash: draft.ReadyReceiptDigest, ReviewPolicyHash: draft.ReviewPolicyID,
		IssuedAt: 1_000, ExpiresAt: 2_000, Nonce: "review-g2", SignerKeyID: "human-1",
	}
	unsigned, err := CanonicalHumanBatchDecisionReceiptV1(decision, false)
	require.NoError(t, err)
	decision.Signature = EncodeWikiReleaseSignature(ed25519.Sign(fixture.privateKey, unsigned))
	rawDecision, err := CanonicalHumanBatchDecisionReceiptV1(decision, true)
	require.NoError(t, err)
	ready, err := schema.ReviewSchemaDraft(
		fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision,
	)
	require.NoError(t, err)
	require.Equal(t, ready.ManifestDigest, digestWikiReleaseBytes(ready.Manifest))
	require.Equal(t, ready.PreparationDigest, digestWikiReleasePreparation(ready))
	authorization := &types.PublishAuthorizationV0{
		Version: "0", Action: "activate", PreparationID: ready.ID,
		CandidateDigest: ready.CandidateDigest, ManifestDigest: ready.ManifestDigest,
		ReadyReceiptDigest:   ready.ReadyReceiptDigest,
		ReviewDecisionDigest: ready.ReviewDecisionDigest, ReviewPolicyID: ready.ReviewPolicyID,
		TenantID: fixture.scope.TenantID, SpaceID: fixture.scope.SpaceID,
		RawKBID: fixture.scope.RawKBID, WikiKBID: fixture.scope.WikiKBID,
		ExpiresAt: 2_000, Nonce: "review-g2", SignerKeyID: "signer-1",
	}
	unsignedAuthorization, err := CanonicalPublishAuthorizationV0(authorization, false)
	require.NoError(t, err)
	authorization.Signature = EncodeWikiReleaseSignature(
		ed25519.Sign(fixture.privateKey, unsignedAuthorization),
	)
	rawAuthorization, err := CanonicalPublishAuthorizationV0(authorization, true)
	require.NoError(t, err)
	activation, err := fixture.service.ActivateReviewed(
		fixture.ctx, fixture.principal1, rawDecision, rawAuthorization,
	)
	require.NoError(t, err)
	authority := fixture.service.conceptSourceAuthorityVerifier830G2.(*conceptSourceAuthorityVerifierFake830G2)
	require.Len(t, authority.requests, 2)
	require.Equal(t, "review", authority.requests[0].Operation)
	require.Equal(t, "activate", authority.requests[1].Operation)
	require.Equal(t, fixture.principal1, authority.requests[1].Principal)
	require.Equal(t, fixture.scope, authority.requests[1].Scope)
	require.Equal(t, ready.ID, authority.requests[1].PreparationID)
	require.Equal(t, ready.CandidateDigest, authority.requests[1].CandidateHash)
	require.Equal(t, ready.ManifestDigest, authority.requests[1].ManifestDigest)
	require.Equal(t, ready.PreparationDigest, authority.requests[1].PreparationDigest)
	require.JSONEq(t, string(ready.Manifest), string(authority.requests[1].Manifest))

	memberID := "concept_c730e23edec4bc4fa3035b05ad32ddffb0a0e38a841fff3c58a0eef88cdcc4b3"
	current, err := schema.ReadConceptPage830G2(
		fixture.ctx, fixture.principal1, fixture.scope, memberID, "",
	)
	require.NoError(t, err)
	require.Equal(t, "concept-page-read.830.g2.v1", current.Contract)
	require.Equal(t, "current", current.ReadMode)
	require.Equal(t, activation.ReleaseID, current.ReleaseID)
	require.Equal(t, uint64(1), current.ActivationEpoch)
	require.Equal(t, memberID, current.Member.MemberID)
	require.Len(t, current.RelatedMembers, 1)
	require.Len(t, current.Citations, 1)
	require.NotEmpty(t, current.DefinitionHash)
	require.NotEmpty(t, current.AggregateHash)
	fieldID := "assertion_b1157f22ec5827b7873eee56aed736cb9e99e9a2779e3b9a389089b17d8ffb62"
	field, err := schema.ReadConceptPage830G2(
		fixture.ctx, fixture.principal1, fixture.scope, fieldID, "",
	)
	require.NoError(t, err)
	require.Len(t, field.RelatedMembers, 1)
	require.Equal(t, memberID, field.RelatedMembers[0].MemberID)
	overviewID := "entity_overview_ec948fb3c2c13bf92f987a22d3750417a1942bee4821ff39fbb8acf35c588815"
	overview, err := schema.ReadConceptPage830G2(
		fixture.ctx, fixture.principal1, fixture.scope, overviewID, "",
	)
	require.NoError(t, err)
	require.Len(t, overview.RelatedMembers, 3)

	pinned, err := schema.ReadConceptPage830G2(
		fixture.ctx, fixture.principal1, fixture.scope, memberID, activation.ReleaseID,
	)
	require.NoError(t, err)
	require.Equal(t, "pinned", pinned.ReadMode)
	_, err = schema.ReadConceptPage830G2(
		fixture.ctx, fixture.principal1, fixture.scope, memberID, "other-release",
	)
	require.ErrorIs(t, err, ErrWikiReleaseNotFound)
}

func TestCreateConceptFreeWikiDraft830G2RejectsCallerScopeDrift(t *testing.T) {
	fixture, schema := conceptReleaseFixture830G2(t)
	drifted := fixture.scope
	drifted.RawKBID = "raw-b"
	_, err := schema.CreateConceptFreeWikiDraft830G2(
		fixture.ctx, fixture.principal1, drifted, "g2-preparation", conceptBundleVector830G2(t),
	)
	require.Error(t, err)
}

func activateConceptBundle830G2(
	t *testing.T,
	fixture *wikiReleaseFixture,
	schema *SchemaWikiService,
	identity string,
) (*types.WikiReleaseReceipt, types.ConceptCandidateBundle830G2) {
	t.Helper()
	bundle, err := types.ParseConceptCandidateBundle830G2(conceptBundleVector830G2(t))
	require.NoError(t, err)
	draft, err := schema.CreateConceptFreeWikiDraft830G2(
		fixture.ctx, fixture.principal1, fixture.scope, identity+"-preparation", conceptBundleVector830G2(t),
	)
	require.NoError(t, err)
	fixture.service.humanDecisionVerifier = NewEd25519HumanBatchDecisionVerifier(
		map[string]ed25519.PublicKey{"human-1": fixture.privateKey.Public().(ed25519.PublicKey)},
	)
	decision := &types.HumanBatchDecisionReceiptV1{
		Version: "1", Decision: "approve", PrincipalID: fixture.principal1.ID,
		WikiReleaseScope: fixture.scope, CandidateHash: draft.CandidateDigest,
		HumanBatchHash: draft.ReadyReceiptDigest, ReviewPolicyHash: draft.ReviewPolicyID,
		IssuedAt: 1_000, ExpiresAt: 2_000, Nonce: identity + "-nonce", SignerKeyID: "human-1",
	}
	unsigned, err := CanonicalHumanBatchDecisionReceiptV1(decision, false)
	require.NoError(t, err)
	decision.Signature = EncodeWikiReleaseSignature(ed25519.Sign(fixture.privateKey, unsigned))
	rawDecision, err := CanonicalHumanBatchDecisionReceiptV1(decision, true)
	require.NoError(t, err)
	ready, err := schema.ReviewSchemaDraft(
		fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision,
	)
	require.NoError(t, err)
	authorization := &types.PublishAuthorizationV0{
		Version: "0", Action: "activate", PreparationID: ready.ID,
		CandidateDigest: ready.CandidateDigest, ManifestDigest: ready.ManifestDigest,
		ReadyReceiptDigest: ready.ReadyReceiptDigest, ReviewDecisionDigest: ready.ReviewDecisionDigest,
		ReviewPolicyID: ready.ReviewPolicyID, TenantID: fixture.scope.TenantID,
		SpaceID: fixture.scope.SpaceID, RawKBID: fixture.scope.RawKBID, WikiKBID: fixture.scope.WikiKBID,
		ExpiresAt: 2_000, Nonce: decision.Nonce, SignerKeyID: "signer-1",
	}
	unsignedAuthorization, err := CanonicalPublishAuthorizationV0(authorization, false)
	require.NoError(t, err)
	authorization.Signature = EncodeWikiReleaseSignature(ed25519.Sign(fixture.privateKey, unsignedAuthorization))
	rawAuthorization, err := CanonicalPublishAuthorizationV0(authorization, true)
	require.NoError(t, err)
	activation, err := fixture.service.ActivateReviewed(
		fixture.ctx, fixture.principal1, rawDecision, rawAuthorization,
	)
	require.NoError(t, err)
	return activation, bundle
}

func TestReadConceptPage830G2ReadsHistoricalExactReleaseAfterHeadAdvances(t *testing.T) {
	fixture, schema := conceptReleaseFixture830G2(t)
	activation, bundle := activateConceptBundle830G2(t, fixture, schema, "g2-history")
	now := time.Now().UTC()
	_, err := fixture.repo.Activate(fixture.ctx, wikirepository.WikiReleaseActivationWrite{
		Release: &types.WikiRelease{
			ID: "release-r2", WikiReleaseScope: fixture.scope,
			CandidateDigest: bundle.CandidateHash, ManifestDigest: bundle.CandidateHash,
			BaseReleaseID: activation.ReleaseID, BaseActivationEpoch: activation.ActivationEpoch,
			PreparationID: "preparation-r2", CreatedAt: now, ActivatedAt: now,
		},
		ExpectedReleaseID: activation.ReleaseID, ExpectedActivationEpoch: activation.ActivationEpoch,
		Nonce: "r2", AuthorizationDigest: bundle.CandidateHash,
		ActivatedBy: fixture.principal1.ID, ActivatedAt: now, ActivationReceiptID: "receipt-r2",
	})
	require.NoError(t, err)

	memberID := "concept_c730e23edec4bc4fa3035b05ad32ddffb0a0e38a841fff3c58a0eef88cdcc4b3"
	read, err := schema.ReadConceptPage830G2(
		fixture.ctx, fixture.principal1, fixture.scope, memberID, activation.ReleaseID,
	)
	require.NoError(t, err)
	require.Equal(t, "pinned", read.ReadMode)
	require.Equal(t, activation.ReleaseID, read.ReleaseID)
	require.Equal(t, activation.ActivationEpoch, read.ActivationEpoch)
}

func TestReadConceptPage830G2RejectsReleaseBaseDrift(t *testing.T) {
	for name, drift := range map[string]struct {
		baseReleaseID       string
		baseActivationEpoch uint64
	}{
		"base release": {baseReleaseID: "forged-base"},
		"base epoch":   {baseActivationEpoch: 7},
	} {
		t.Run(name, func(t *testing.T) {
			fixture, schema := conceptReleaseFixture830G2(t)
			draft, err := schema.CreateConceptFreeWikiDraft830G2(
				fixture.ctx, fixture.principal1, fixture.scope, "g2-read-base-drift", conceptBundleVector830G2(t),
			)
			require.NoError(t, err)
			rawDecision, _ := conceptDecision830G2(t, fixture, draft, "g2-read-base-drift")
			ready, err := schema.ReviewSchemaDraft(
				fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision,
			)
			require.NoError(t, err)
			now := time.Now().UTC()
			_, err = fixture.repo.Activate(fixture.ctx, wikirepository.WikiReleaseActivationWrite{
				Release: &types.WikiRelease{
					ID: "release-with-drift", WikiReleaseScope: fixture.scope,
					CandidateDigest: ready.CandidateDigest, ManifestDigest: ready.ManifestDigest,
					BaseReleaseID: drift.baseReleaseID, BaseActivationEpoch: drift.baseActivationEpoch,
					PreparationID: ready.ID, CreatedAt: now, ActivatedAt: now,
				},
				Members: ready.Members, Nonce: "drift", AuthorizationDigest: ready.CandidateDigest,
				ActivatedBy: fixture.principal1.ID, ActivatedAt: now, ActivationReceiptID: "drift-receipt",
			})
			require.NoError(t, err)

			_, err = schema.ReadConceptPage830G2(
				fixture.ctx, fixture.principal1, fixture.scope,
				"concept_c730e23edec4bc4fa3035b05ad32ddffb0a0e38a841fff3c58a0eef88cdcc4b3", "",
			)
			require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
		})
	}
}

func TestValidateConceptBase830G2RejectsHeaderOnlyG1Release(t *testing.T) {
	fixture, schema := conceptReleaseFixture830G2(t)
	now := time.Now().UTC()
	preparation := &types.WikiReleasePreparation{
		ID: "fake-g1-preparation", WikiReleaseScope: fixture.scope,
		Status:   types.WikiReleasePreparationReady,
		Manifest: json.RawMessage(`{"contract":"entity-page-manifest.830.g1.v1"}`), CreatedAt: now,
	}
	require.NoError(t, fixture.repo.CreateReadyPreparation(fixture.ctx, preparation))
	_, err := fixture.repo.Activate(fixture.ctx, wikirepository.WikiReleaseActivationWrite{
		Release: &types.WikiRelease{
			ID: "fake-g1-release", WikiReleaseScope: fixture.scope,
			PreparationID: preparation.ID, CreatedAt: now, ActivatedAt: now,
		},
		Nonce: "fake-g1", AuthorizationDigest: "fake-g1", ActivatedBy: fixture.principal1.ID,
		ActivatedAt: now, ActivationReceiptID: "fake-g1-receipt",
	})
	require.NoError(t, err)
	bundle, err := types.ParseConceptCandidateBundle830G2(conceptBundleVector830G2(t))
	require.NoError(t, err)
	bundle.Request.BaseReleaseID = "fake-g1-release"
	bundle.Request.BaseActivationEpoch = 1

	err = schema.validateConceptBase830G2(fixture.ctx, fixture.scope, bundle)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
}

func TestValidateConceptBase830G2RejectsTamperedG2ReleaseMembers(t *testing.T) {
	fixture, schema := conceptReleaseFixture830G2(t)
	base, err := types.ParseConceptCandidateBundle830G2(conceptBundleVector830G2(t))
	require.NoError(t, err)
	draft, err := schema.CreateConceptFreeWikiDraft830G2(
		fixture.ctx, fixture.principal1, fixture.scope, "g2-base-tamper-preparation", conceptBundleVector830G2(t),
	)
	require.NoError(t, err)
	fixture.service.humanDecisionVerifier = NewEd25519HumanBatchDecisionVerifier(
		map[string]ed25519.PublicKey{"human-1": fixture.privateKey.Public().(ed25519.PublicKey)},
	)
	decision := &types.HumanBatchDecisionReceiptV1{
		Version: "1", Decision: "approve", PrincipalID: fixture.principal1.ID,
		WikiReleaseScope: fixture.scope, CandidateHash: draft.CandidateDigest,
		HumanBatchHash: draft.ReadyReceiptDigest, ReviewPolicyHash: draft.ReviewPolicyID,
		IssuedAt: 1_000, ExpiresAt: 2_000, Nonce: "g2-tampered-member-review", SignerKeyID: "human-1",
	}
	unsigned, err := CanonicalHumanBatchDecisionReceiptV1(decision, false)
	require.NoError(t, err)
	decision.Signature = EncodeWikiReleaseSignature(ed25519.Sign(fixture.privateKey, unsigned))
	rawDecision, err := CanonicalHumanBatchDecisionReceiptV1(decision, true)
	require.NoError(t, err)
	ready, err := schema.ReviewSchemaDraft(
		fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision,
	)
	require.NoError(t, err)
	tamperedMembers := append([]types.WikiReleaseMemberSnapshot(nil), ready.Members...)
	tamperedMembers[0].Content = "tampered persisted member"
	now := time.Now().UTC()
	activation, err := fixture.repo.Activate(fixture.ctx, wikirepository.WikiReleaseActivationWrite{
		Release: &types.WikiRelease{
			ID: "release-tampered-g2", WikiReleaseScope: fixture.scope,
			CandidateDigest: ready.CandidateDigest, ManifestDigest: ready.ManifestDigest,
			PreparationID: ready.ID, CreatedAt: now, ActivatedAt: now,
		},
		Members: tamperedMembers, Nonce: "tampered-g2", AuthorizationDigest: base.CandidateHash,
		ActivatedBy: fixture.principal1.ID, ActivatedAt: now, ActivationReceiptID: "receipt-tampered-g2",
	})
	require.NoError(t, err)
	next := base
	next.Request.BaseReleaseID = activation.ReleaseID
	next.Request.BaseActivationEpoch = activation.ActivationEpoch
	next.Request.ExistingDefinitions = append([]types.ConceptDefinition830G2(nil), base.CompileResult.Output.Definitions...)
	next.Request.ExistingFields = append([]types.ConceptFieldAssertion830G2(nil), base.CompileResult.Output.Fields...)
	next.Request.ExistingPages = append([]types.ConceptFreeWikiPage830G2(nil), base.CompileResult.Output.Pages...)
	next.Request.ExistingEntityVersions = make(map[string]string, len(base.Request.EntityVersions))
	for key, value := range base.Request.EntityVersions {
		next.Request.ExistingEntityVersions[key] = value
	}

	err = schema.validateConceptBase830G2(fixture.ctx, fixture.scope, next)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
}

func TestValidateConceptBase830G2RejectsSynchronizedPreparationDigestDrift(t *testing.T) {
	fixture, schema := conceptReleaseFixture830G2(t)
	base, err := types.ParseConceptCandidateBundle830G2(conceptBundleVector830G2(t))
	require.NoError(t, err)
	draft, err := schema.CreateConceptFreeWikiDraft830G2(
		fixture.ctx, fixture.principal1, fixture.scope, "g2-digest-drift-source", conceptBundleVector830G2(t),
	)
	require.NoError(t, err)
	fixture.service.humanDecisionVerifier = NewEd25519HumanBatchDecisionVerifier(
		map[string]ed25519.PublicKey{"human-1": fixture.privateKey.Public().(ed25519.PublicKey)},
	)
	decision := &types.HumanBatchDecisionReceiptV1{
		Version: "1", Decision: "approve", PrincipalID: fixture.principal1.ID,
		WikiReleaseScope: fixture.scope, CandidateHash: draft.CandidateDigest,
		HumanBatchHash: draft.ReadyReceiptDigest, ReviewPolicyHash: draft.ReviewPolicyID,
		IssuedAt: 1_000, ExpiresAt: 2_000, Nonce: "g2-digest-drift", SignerKeyID: "human-1",
	}
	unsigned, err := CanonicalHumanBatchDecisionReceiptV1(decision, false)
	require.NoError(t, err)
	decision.Signature = EncodeWikiReleaseSignature(ed25519.Sign(fixture.privateKey, unsigned))
	rawDecision, err := CanonicalHumanBatchDecisionReceiptV1(decision, true)
	require.NoError(t, err)
	ready, err := schema.ReviewSchemaDraft(
		fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision,
	)
	require.NoError(t, err)
	tampered := *ready
	tampered.ID = "g2-synchronized-digest-drift"
	tampered.ManifestDigest = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	tampered.PreparationDigest = digestWikiReleasePreparation(&tampered)
	require.NoError(t, fixture.repo.CreateReadyPreparation(fixture.ctx, &tampered))
	now := time.Now().UTC()
	activation, err := fixture.repo.Activate(fixture.ctx, wikirepository.WikiReleaseActivationWrite{
		Release: &types.WikiRelease{
			ID: "release-synchronized-digest-drift", WikiReleaseScope: fixture.scope,
			CandidateDigest: tampered.CandidateDigest, ManifestDigest: tampered.ManifestDigest,
			PreparationID: tampered.ID, CreatedAt: now, ActivatedAt: now,
		},
		Members: tampered.Members, Nonce: "g2-synchronized-digest-drift",
		AuthorizationDigest: base.CandidateHash, ActivatedBy: fixture.principal1.ID,
		ActivatedAt: now, ActivationReceiptID: "receipt-synchronized-digest-drift",
	})
	require.NoError(t, err)
	next := base
	next.Request.BaseReleaseID = activation.ReleaseID
	next.Request.BaseActivationEpoch = activation.ActivationEpoch
	next.Request.ExistingDefinitions = append([]types.ConceptDefinition830G2(nil), base.CompileResult.Output.Definitions...)
	next.Request.ExistingFields = append([]types.ConceptFieldAssertion830G2(nil), base.CompileResult.Output.Fields...)
	next.Request.ExistingPages = append([]types.ConceptFreeWikiPage830G2(nil), base.CompileResult.Output.Pages...)
	next.Request.ExistingEntityVersions = make(map[string]string, len(base.Request.EntityVersions))
	for key, value := range base.Request.EntityVersions {
		next.Request.ExistingEntityVersions[key] = value
	}

	err = schema.validateConceptBase830G2(fixture.ctx, fixture.scope, next)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
}
