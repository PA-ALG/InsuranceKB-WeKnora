package service

import (
	"context"
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

type batchConceptQueryAccessVerifier830G3 struct {
	delegate   WikiReleaseAccessVerifier
	operations []string
	onSearch   func()
}

func (v *batchConceptQueryAccessVerifier830G3) VerifyWikiReleaseAccess(
	ctx context.Context,
	request WikiReleaseAccessRequest,
) error {
	if err := v.delegate.VerifyWikiReleaseAccess(ctx, request); err != nil {
		return err
	}
	v.operations = append(v.operations, request.Operation)
	if request.Operation == "minimal-search" && v.onSearch != nil {
		callback := v.onSearch
		v.onSearch = nil
		callback()
	}
	return nil
}

func batchConceptCandidateVector830G3(t *testing.T) json.RawMessage {
	t.Helper()
	raw, err := os.ReadFile("../../../harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json")
	require.NoError(t, err)
	return raw
}

func actualConceptBaseVector830G3(t *testing.T) json.RawMessage {
	t.Helper()
	raw, err := os.ReadFile("../../../docs/insurance-kb/evidence/830-g2/b-source-complete-candidate-bundle.json")
	require.NoError(t, err)
	return raw
}

func expectedBatchConceptPreparationReadHash830G3(
	t *testing.T,
	value BatchConceptPreparationRead830G3,
) (string, []byte) {
	t.Helper()
	raw, err := json.Marshal(value)
	require.NoError(t, err)
	var payload map[string]json.RawMessage
	require.NoError(t, json.Unmarshal(raw, &payload))
	delete(payload, "read_sha256")
	raw, err = json.Marshal(payload)
	require.NoError(t, err)
	canonical, err := types.CanonicalConceptMemberPayload830G2(raw)
	require.NoError(t, err)
	preimage := append(
		[]byte("schema-wiki-canonical.v1\x00"+value.Contract+"\x00"), canonical...,
	)
	digest := sha256.Sum256(preimage)
	return hex.EncodeToString(digest[:]), canonical
}

func batchConceptReleaseFixture830G3(
	t *testing.T,
) (*wikiReleaseFixture, *SchemaWikiService, types.BatchConceptCandidateBundle830G3) {
	t.Helper()
	bundle, _, err := types.CanonicalBatchConceptCandidateBundle830G3(batchConceptCandidateVector830G3(t))
	require.NoError(t, err)
	base, canonicalBase, err := types.CanonicalConceptCandidateBundle830G2(actualConceptBaseVector830G3(t))
	require.NoError(t, err)
	request := bundle.Request.BaseRequest
	scope := types.WikiReleaseScope{
		TenantID: request.TenantID, SpaceID: request.SpaceID,
		RawKBID: request.RawKBID, WikiKBID: request.WikiKBID,
	}
	fixture := newWikiReleaseFixture(t, WikiReleaseFaults{})
	fixture.scope = scope
	fixture.principal1.TenantID = scope.TenantID
	fixture.principal1.SpaceID = scope.SpaceID
	fixture.access.allowed[fixture.principal1.ID] = scope
	fixture.ctx = schemaWikiHumanContext(fixture.principal1, scope, types.TenantRoleAdmin)
	verifier := &conceptSourceAuthorityVerifierFake830G2{}
	fixture.service.conceptSourceAuthorityVerifier830G2 = verifier
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	fixture.service.publishedReadReuse = newPublishedBatchReadReuse830G3(sourceReuseTestCodec830G3(t))

	now := time.Unix(900, 0).UTC()
	previous := ""
	for epoch, releaseID := range []string{"base-r1", "base-r2", "base-r3", base.Request.BaseReleaseID} {
		_, err = fixture.repo.Activate(fixture.ctx, wikirepository.WikiReleaseActivationWrite{
			Release: &types.WikiRelease{
				ID: releaseID, WikiReleaseScope: scope,
				CandidateDigest: "base-candidate", ManifestDigest: "base-manifest",
				BaseReleaseID: previous, BaseActivationEpoch: uint64(epoch),
				PreparationID: "base-placeholder", CreatedAt: now, ActivatedAt: now,
			},
			ExpectedReleaseID: previous, ExpectedActivationEpoch: uint64(epoch),
			Nonce: "base-nonce-" + releaseID, AuthorizationDigest: "base-authorization-" + releaseID,
			ActivatedBy: fixture.principal1.ID, ActivatedAt: now,
			ActivationReceiptID: "base-receipt-" + releaseID,
		})
		require.NoError(t, err)
		previous = releaseID
	}
	baseMembers, err := base.SnapshotMembers()
	require.NoError(t, err)
	basePreparation := &types.WikiReleasePreparation{
		ID: "actual-g2-base-preparation", WikiReleaseScope: scope,
		CandidateDigest: base.CandidateHash, ManifestDigest: digestWikiReleaseBytes(canonicalBase),
		ReadyReceiptDigest:   base.ReviewResult.Execution.RawOutputHash,
		ReviewDecisionDigest: "actual-g2-review", ReviewPolicyID: conceptReviewPolicyHash830G2(base.Request.PolicyIdentity),
		ExpectedReleaseID: base.Request.BaseReleaseID, ExpectedActivationEpoch: base.Request.BaseActivationEpoch,
		Status: types.WikiReleasePreparationReady, Manifest: canonicalBase, Members: baseMembers, CreatedAt: now,
	}
	basePreparation.PreparationDigest = digestWikiReleasePreparation(basePreparation)
	require.NoError(t, fixture.repo.CreateReadyPreparation(fixture.ctx, basePreparation))
	_, err = fixture.repo.Activate(fixture.ctx, wikirepository.WikiReleaseActivationWrite{
		Release: &types.WikiRelease{
			ID: request.BaseReleaseID, WikiReleaseScope: scope,
			CandidateDigest: base.CandidateHash, ManifestDigest: basePreparation.ManifestDigest,
			BaseReleaseID: base.Request.BaseReleaseID, BaseActivationEpoch: base.Request.BaseActivationEpoch,
			PreparationID: basePreparation.ID, CreatedAt: now, ActivatedAt: now,
		},
		Members: baseMembers, ExpectedReleaseID: base.Request.BaseReleaseID,
		ExpectedActivationEpoch: base.Request.BaseActivationEpoch,
		Nonce:                   "actual-g2-base", AuthorizationDigest: base.CandidateHash,
		ActivatedBy: fixture.principal1.ID, ActivatedAt: now,
		ActivationReceiptID: "actual-g2-base-receipt",
	})
	require.NoError(t, err)
	return fixture, NewSchemaWikiService(fixture.service, nil), bundle
}

func TestCreateBatchConceptDraft830G3StoresExactImmutableCandidate(t *testing.T) {
	fixture, schema, bundle := batchConceptReleaseFixture830G3(t)
	headBefore, err := fixture.repo.GetHead(fixture.ctx, fixture.scope)
	require.NoError(t, err)
	draft, err := schema.CreateBatchConceptDraft830G3(
		fixture.ctx, fixture.principal1, fixture.scope,
		"batch-g3-preparation", batchConceptCandidateVector830G3(t),
	)
	require.NoError(t, err)
	require.Equal(t, types.WikiReleasePreparationDraft, draft.Status)
	require.Equal(t, bundle.CandidateHash, draft.CandidateDigest)
	require.Equal(t, bundle.Request.BaseRequest.BaseReleaseID, draft.ExpectedReleaseID)
	require.Equal(t, bundle.Request.BaseRequest.BaseActivationEpoch, draft.ExpectedActivationEpoch)
	require.Len(t, draft.Members, 354)
	headAfter, err := fixture.repo.GetHead(fixture.ctx, fixture.scope)
	require.NoError(t, err)
	require.Equal(t, headBefore, headAfter)
	verifier := fixture.service.conceptSourceAuthorityVerifier830G2.(*conceptSourceAuthorityVerifierFake830G2)
	require.Len(t, verifier.requests, 1)
	require.Equal(t, "create-draft", verifier.requests[0].Operation)
	require.Empty(t, verifier.requests[0].PreparationDigest)
}

func TestLoadBatchConceptPreparation830G3ReopensDraftAndReadyWithoutCurrentHead(t *testing.T) {
	fixture, schema, bundle := batchConceptReleaseFixture830G3(t)
	draft, err := schema.CreateBatchConceptDraft830G3(
		fixture.ctx, fixture.principal1, fixture.scope,
		"batch-g3-reopen-draft", batchConceptCandidateVector830G3(t),
	)
	require.NoError(t, err)

	draftRead, err := schema.LoadBatchConceptPreparation830G3(
		fixture.ctx, fixture.principal1, fixture.scope, draft.ID,
	)
	require.NoError(t, err)
	require.Equal(t, batchConceptPreparationReadContract830G3, draftRead.Contract)
	require.Equal(t, "preparation", draftRead.ReadMode)
	require.Equal(t, "DRAFT", draftRead.Status)
	require.Equal(t, bundle.CandidateHash, draftRead.CandidateSHA256)
	wantManifest, err := json.Marshal(bundle.PageManifest)
	require.NoError(t, err)
	gotManifest, err := json.Marshal(draftRead.PageManifest)
	require.NoError(t, err)
	require.JSONEq(t, string(wantManifest), string(gotManifest))
	require.NotEmpty(t, draftRead.ReadSHA256)

	ready := *draft
	ready.ID = "batch-g3-reopen-ready"
	ready.Status = types.WikiReleasePreparationReady
	ready.ReviewDecisionDigest = digestWikiReleaseBytes([]byte("batch-g3-reviewed"))
	ready.PreparationDigest = digestWikiReleasePreparation(&ready)
	require.NoError(t, fixture.repo.CreateReadyPreparation(fixture.ctx, &ready))

	// Preparation refresh remains pinned to the stored base even when the
	// serving Head advances independently.
	now := time.Unix(950, 0).UTC()
	_, err = fixture.repo.Activate(fixture.ctx, wikirepository.WikiReleaseActivationWrite{
		Release: &types.WikiRelease{
			ID: "later-release", WikiReleaseScope: fixture.scope,
			CandidateDigest: "later-candidate", ManifestDigest: "later-manifest",
			BaseReleaseID: draft.ExpectedReleaseID, BaseActivationEpoch: draft.ExpectedActivationEpoch,
			PreparationID: "later-preparation", CreatedAt: now, ActivatedAt: now,
		},
		ExpectedReleaseID: draft.ExpectedReleaseID, ExpectedActivationEpoch: draft.ExpectedActivationEpoch,
		Nonce: "later-release", AuthorizationDigest: "later-authorization",
		ActivatedBy: fixture.principal1.ID, ActivatedAt: now, ActivationReceiptID: "later-receipt",
	})
	require.NoError(t, err)
	readyRead, err := schema.LoadBatchConceptPreparation830G3(
		fixture.ctx, fixture.principal1, fixture.scope, ready.ID,
	)
	require.NoError(t, err)
	require.Equal(t, "READY", readyRead.Status)
	require.Equal(t, draftRead.CandidateSHA256, readyRead.CandidateSHA256)
	require.Equal(t, draftRead.ExpectedBaseReleaseID, readyRead.ExpectedBaseReleaseID)
	require.Equal(t, draftRead.ExpectedBaseActivationEpoch, readyRead.ExpectedBaseActivationEpoch)
	require.Equal(t, draftRead.PageManifest, readyRead.PageManifest)
}

func TestBatchConceptPreparationReadHash830G3UsesLogicalUnicodeCanonicalBytes(t *testing.T) {
	for _, test := range []struct {
		name    string
		content string
	}{
		{name: "real U+2028", content: "before\u2028after"},
		{name: "real U+2029", content: "before\u2029after"},
		{name: "literal backslash-u2028", content: `before\u2028after`},
		{name: "literal backslash-u2029", content: `before\u2029after`},
		{name: "body TAB LF CR", content: "before\tline\nreturn\rafter"},
	} {
		t.Run(test.name, func(t *testing.T) {
			value := BatchConceptPreparationRead830G3{
				Contract: batchConceptPreparationReadContract830G3, ReadMode: "preparation",
				TenantID: 10003, SpaceID: "space-g3", RawKBID: "raw-g3", WikiKBID: "wiki-g3",
				PreparationID: "preparation-g3", Status: "DRAFT",
				CandidateSHA256: strings.Repeat("a", 64), ExpectedBaseReleaseID: "base-release",
				ExpectedBaseActivationEpoch: 5,
				PageManifest: types.BatchConceptPageManifest830G3{
					Contract: "batch-concept-page-manifest.830.g3.v1",
					Members: []types.ConceptPageMember830G2{{
						Kind: "field_assertion", MemberID: "field-1", OwnerID: "entity-1",
						Title: "标题", Content: test.content, Payload: json.RawMessage(`{}`),
					}},
					MembersSHA256: strings.Repeat("b", 64),
					Audit:         []types.ConceptAuditDisposition830G2{},
				},
			}
			want, canonical := expectedBatchConceptPreparationReadHash830G3(t, value)
			got, err := batchConceptPreparationReadHash830G3(value)
			require.NoError(t, err)
			require.Equal(t, want, got)
			if strings.Contains(test.name, "real U+") {
				require.Contains(t, string(canonical), test.content)
			} else if strings.Contains(test.name, "literal") {
				require.Contains(t, string(canonical), strings.ReplaceAll(test.content, `\`, `\\`))
			} else {
				require.Contains(t, string(canonical), `before\tline\nreturn\rafter`)
			}
		})
	}
}

func TestBatchConceptPreparationReadHash830G3MatchesFrozenActual342Consumer(t *testing.T) {
	fixture, schema, _ := batchConceptReleaseFixture830G3(t)
	const preparationID = "fixture-g3-actual342"
	_, err := schema.CreateBatchConceptDraft830G3(
		fixture.ctx, fixture.principal1, fixture.scope,
		preparationID, batchConceptCandidateVector830G3(t),
	)
	require.NoError(t, err)
	read, err := schema.LoadBatchConceptPreparation830G3(
		fixture.ctx, fixture.principal1, fixture.scope, preparationID,
	)
	require.NoError(t, err)
	want, canonical := expectedBatchConceptPreparationReadHash830G3(t, *read)
	require.Equal(t, want, read.ReadSHA256)
	require.Equal(t, 28, strings.Count(string(canonical), "\u2028"))
}

func TestBatchConceptPreparationID830G3RejectsStructuredControlBeforeWrite(t *testing.T) {
	fixture, schema, _ := batchConceptReleaseFixture830G3(t)
	verifier := fixture.service.conceptSourceAuthorityVerifier830G2.(*conceptSourceAuthorityVerifierFake830G2)
	stateBefore, err := fixture.repo.CountState(fixture.ctx)
	require.NoError(t, err)

	_, err = schema.CreateBatchConceptDraft830G3(
		fixture.ctx, fixture.principal1, fixture.scope,
		"invalid\npreparation", batchConceptCandidateVector830G3(t),
	)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
	require.Empty(t, verifier.requests, "invalid identity must fail before source verification")
	stateAfter, err := fixture.repo.CountState(fixture.ctx)
	require.NoError(t, err)
	require.Equal(t, stateBefore, stateAfter, "invalid identity must not create a Draft")

	_, err = schema.LoadBatchConceptPreparation830G3(
		fixture.ctx, fixture.principal1, fixture.scope, "invalid\npreparation",
	)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
}

func TestValidBatchConceptPreparationID830G3UsesExactDTextRules(t *testing.T) {
	for _, value := range []string{
		"preparation-g3",
		"批次 准备",
		"batch\u2028preparation",
		"batch\u2029preparation",
		`batch\u2028preparation`,
		strings.Repeat("x", 513),
	} {
		require.True(t, validBatchConceptPreparationID830G3(value), "%q", value)
	}
	for _, value := range []string{
		"",
		" ",
		" leading",
		"trailing ",
		"batch\tpreparation",
		"batch\npreparation",
		"batch\rpreparation",
		"batch\x00preparation",
		"batch\x7fpreparation",
		"\u2028edge",
		"edge\u2029",
		"\u00a0edge",
		"edge\u00a0",
		"Cafe\u0301",
		string([]byte{'b', 'a', 'd', 0xff}),
	} {
		require.False(t, validBatchConceptPreparationID830G3(value), "%q", value)
	}
}

func TestCreateBatchConceptDraft830G3FailsClosedBeforeStorage(t *testing.T) {
	t.Run("source verifier denial", func(t *testing.T) {
		fixture, schema, _ := batchConceptReleaseFixture830G3(t)
		verifier := fixture.service.conceptSourceAuthorityVerifier830G2.(*conceptSourceAuthorityVerifierFake830G2)
		verifier.err = errors.New("source drift")
		_, err := schema.CreateBatchConceptDraft830G3(
			fixture.ctx, fixture.principal1, fixture.scope,
			"batch-g3-denied", batchConceptCandidateVector830G3(t),
		)
		require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
		_, readErr := fixture.repo.GetDraftPreparation(fixture.ctx, fixture.scope, "batch-g3-denied")
		require.ErrorIs(t, readErr, wikirepository.ErrWikiReleaseNotFound)
		require.Len(t, verifier.requests, 1)
	})

	t.Run("wrong scope", func(t *testing.T) {
		fixture, schema, _ := batchConceptReleaseFixture830G3(t)
		drifted := fixture.scope
		drifted.RawKBID = "different-raw"
		_, err := schema.CreateBatchConceptDraft830G3(
			fixture.ctx, fixture.principal1, drifted,
			"batch-g3-wrong-scope", batchConceptCandidateVector830G3(t),
		)
		require.Error(t, err)
		_, readErr := fixture.repo.GetDraftPreparation(fixture.ctx, fixture.scope, "batch-g3-wrong-scope")
		require.ErrorIs(t, readErr, wikirepository.ErrWikiReleaseNotFound)
	})

	t.Run("noncanonical changed manifest", func(t *testing.T) {
		fixture, schema, _ := batchConceptReleaseFixture830G3(t)
		var changed map[string]any
		require.NoError(t, json.Unmarshal(batchConceptCandidateVector830G3(t), &changed))
		changed["candidate_hash"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
		raw, marshalErr := json.Marshal(changed)
		require.NoError(t, marshalErr)
		_, err := schema.CreateBatchConceptDraft830G3(
			fixture.ctx, fixture.principal1, fixture.scope,
			"batch-g3-noncanonical", raw,
		)
		require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
		verifier := fixture.service.conceptSourceAuthorityVerifier830G2.(*conceptSourceAuthorityVerifierFake830G2)
		require.Empty(t, verifier.requests)
	})
}

func TestValidateBatchConceptBase830G3ReopensActualFinalOutput(t *testing.T) {
	fixture, schema, bundle := batchConceptReleaseFixture830G3(t)
	require.NoError(t, schema.validateBatchConceptBase830G3(fixture.ctx, fixture.scope, bundle))

	missing := bundle
	missing.Request.BaseRequest.ExistingFields = missing.Request.BaseRequest.ExistingFields[1:]
	require.ErrorIs(t, schema.validateBatchConceptBase830G3(fixture.ctx, fixture.scope, missing), ErrSchemaWikiPreparationInvalid)

	stale := bundle
	stale.Request.BaseRequest.BaseActivationEpoch--
	require.ErrorIs(t, schema.validateBatchConceptBase830G3(fixture.ctx, fixture.scope, stale), ErrSchemaWikiPreparationInvalid)
}

func TestLoadBatchConceptPreparation830G3RejectsMissingAccessAndStoredDrift(t *testing.T) {
	t.Run("missing", func(t *testing.T) {
		fixture, schema, _ := batchConceptReleaseFixture830G3(t)
		_, err := schema.LoadBatchConceptPreparation830G3(
			fixture.ctx, fixture.principal1, fixture.scope, "missing",
		)
		require.ErrorIs(t, err, ErrWikiReleaseNotFound)
	})

	t.Run("wrong principal", func(t *testing.T) {
		fixture, schema, _ := batchConceptReleaseFixture830G3(t)
		draft, err := schema.CreateBatchConceptDraft830G3(
			fixture.ctx, fixture.principal1, fixture.scope,
			"batch-g3-access", batchConceptCandidateVector830G3(t),
		)
		require.NoError(t, err)
		_, err = schema.LoadBatchConceptPreparation830G3(
			fixture.ctx, fixture.principal2, fixture.scope, draft.ID,
		)
		require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
	})

	for name, mutate := range map[string]func(*types.WikiReleasePreparation){
		"member": func(preparation *types.WikiReleasePreparation) {
			preparation.Members = append([]types.WikiReleaseMemberSnapshot(nil), preparation.Members...)
			preparation.Members[0].Content += " tampered"
		},
		"manifest": func(preparation *types.WikiReleasePreparation) {
			preparation.Manifest = append(json.RawMessage(nil), preparation.Manifest...)
			preparation.Manifest[10] ^= 1
		},
	} {
		t.Run("stored "+name+" drift", func(t *testing.T) {
			fixture, schema, _ := batchConceptReleaseFixture830G3(t)
			draft, err := schema.CreateBatchConceptDraft830G3(
				fixture.ctx, fixture.principal1, fixture.scope,
				"batch-g3-drift-source", batchConceptCandidateVector830G3(t),
			)
			require.NoError(t, err)
			stored := *draft
			stored.ID = "batch-g3-stored-" + name
			stored.Status = types.WikiReleasePreparationReady
			stored.ReviewDecisionDigest = digestWikiReleaseBytes([]byte("reviewed-" + name))
			mutate(&stored)
			stored.PreparationDigest = digestWikiReleasePreparation(&stored)
			require.NoError(t, fixture.repo.CreateReadyPreparation(fixture.ctx, &stored))
			_, err = schema.LoadBatchConceptPreparation830G3(
				fixture.ctx, fixture.principal1, fixture.scope, stored.ID,
			)
			require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
		})
	}
}

func TestBatchConceptDraftReviewActivate830G3ReverifiesSourcesAndCASesHead(t *testing.T) {
	fixture, schema, _ := batchConceptReleaseFixture830G3(t)
	draft, err := schema.CreateBatchConceptDraft830G3(
		fixture.ctx, fixture.principal1, fixture.scope,
		"batch-g3-full-flow", batchConceptCandidateVector830G3(t),
	)
	require.NoError(t, err)
	rawDecision, decision := conceptDecision830G2(t, fixture, draft, "batch-g3-flow")
	ready, err := schema.ReviewSchemaDraft(
		fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision,
	)
	require.NoError(t, err)
	require.Equal(t, types.WikiReleasePreparationReady, ready.Status)
	rawAuthorization := conceptAuthorization830G2(t, fixture, ready, decision)
	receipt, err := fixture.service.ActivateReviewed(
		fixture.ctx, fixture.principal1, rawDecision,
		rawAuthorization,
	)
	require.NoError(t, err)
	headAfterFirst, err := fixture.repo.GetHead(fixture.ctx, fixture.scope)
	require.NoError(t, err)
	stateAfterFirst, err := fixture.repo.CountState(fixture.ctx)
	require.NoError(t, err)
	retry, err := fixture.service.ActivateReviewed(
		fixture.ctx, fixture.principal1, rawDecision, rawAuthorization,
	)
	require.NoError(t, err)
	require.Equal(t, receipt, retry, "the exact nonce retry must return the frozen activation receipt")
	require.Equal(t, uint64(6), receipt.ActivationEpoch)
	headAfterRetry, err := fixture.repo.GetHead(fixture.ctx, fixture.scope)
	require.NoError(t, err)
	stateAfterRetry, err := fixture.repo.CountState(fixture.ctx)
	require.NoError(t, err)
	require.Equal(t, headAfterFirst, headAfterRetry, "retry must not advance Head or activation epoch")
	require.Equal(t, stateAfterFirst, stateAfterRetry, "retry must not add a release or activation receipt")
	verifier := fixture.service.conceptSourceAuthorityVerifier830G2.(*conceptSourceAuthorityVerifierFake830G2)
	require.Len(t, verifier.requests, 4)
	require.Equal(t, []string{"create-draft", "review", "activate", "activate"}, []string{
		verifier.requests[0].Operation, verifier.requests[1].Operation,
		verifier.requests[2].Operation, verifier.requests[3].Operation,
	})
	require.Empty(t, verifier.requests[0].PreparationDigest)
	require.Equal(t, draft.PreparationDigest, verifier.requests[1].PreparationDigest)
	require.Equal(t, ready.PreparationDigest, verifier.requests[2].PreparationDigest)
	require.Equal(t, ready.PreparationDigest, verifier.requests[3].PreparationDigest)
}

func TestBatchConceptBase830G3ReopensPublishedG3Head(t *testing.T) {
	fixture, schema, bundle := batchConceptReleaseFixture830G3(t)
	draft, err := schema.CreateBatchConceptDraft830G3(
		fixture.ctx, fixture.principal1, fixture.scope,
		"batch-g3-base-reopen", batchConceptCandidateVector830G3(t),
	)
	require.NoError(t, err)
	rawDecision, decision := conceptDecision830G2(t, fixture, draft, "batch-g3-base-reopen")
	ready, err := schema.ReviewSchemaDraft(
		fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision,
	)
	require.NoError(t, err)
	receipt, err := fixture.service.ActivateReviewed(
		fixture.ctx, fixture.principal1, rawDecision,
		conceptAuthorization830G2(t, fixture, ready, decision),
	)
	require.NoError(t, err)

	next := bundle
	next.Request.BaseRequest.BaseReleaseID = receipt.ReleaseID
	next.Request.BaseRequest.BaseActivationEpoch = receipt.ActivationEpoch
	next.Request.BaseRequest.ExistingDefinitions = bundle.CompileResult.Output.Definitions
	next.Request.BaseRequest.ExistingFields = bundle.CompileResult.Output.Fields
	next.Request.BaseRequest.ExistingPages = bundle.CompileResult.Output.Pages
	next.Request.BaseRequest.ExistingEntityVersions = bundle.Request.BaseRequest.EntityVersions
	require.NoError(t, schema.validateBatchConceptBase830G3(fixture.ctx, fixture.scope, next))

	// A self-hashed display override still needs the actual published parent's history anchor.
	navigation := next
	navigation.ModelCompileResult.Execution.Implementation = "published-content-identity-reuse.830.g3.v1"
	navigation.ModelCompileResult.Output.Definitions = []types.ConceptDefinition830G2{}
	navigation.ModelCompileResult.Output.Fields = []types.ConceptFieldAssertion830G2{}
	navigation.ModelCompileResult.Output.Pages = []types.ConceptFreeWikiPage830G2{}
	navigation.ModelCompileResult.Output.Audit = []types.ConceptAuditDisposition830G2{}
	binding := navigation.Request.EntityBindings[0]
	previous, err := types.DefaultNavigationAssignmentHash830G3(binding)
	require.NoError(t, err)
	row := types.NavigationAssignment830G3{Contract: "g3-navigation-assignment.830.v1", EntityID: binding.EntityID,
		EntityVersion: binding.EntityVersion, AssignmentVersion: 1, Labels: []string{binding.PrimaryClassification, "健康保障"},
		PrimaryLabel: "健康保障", PreviousAssignmentSHA256: previous}
	rehash := func() {
		raw, err := json.Marshal(row)
		require.NoError(t, err)
		var payload map[string]json.RawMessage
		require.NoError(t, json.Unmarshal(raw, &payload))
		delete(payload, "assignment_sha256")
		raw, err = json.Marshal(payload)
		require.NoError(t, err)
		canonical, err := types.CanonicalConceptMemberPayload830G2(raw)
		require.NoError(t, err)
		digest := sha256.Sum256(append([]byte("schema-wiki-canonical.v1\x00"+row.Contract+"\x00"), canonical...))
		row.AssignmentSHA256 = hex.EncodeToString(digest[:])
		navigation.NavigationAssignments = []types.NavigationAssignment830G3{row}
	}
	rehash()
	require.NoError(t, schema.validateBatchConceptBase830G3(fixture.ctx, fixture.scope, navigation))
	row.PreviousAssignmentSHA256 = strings.Repeat("a", 64)
	rehash()
	require.ErrorIs(t, schema.validateBatchConceptBase830G3(fixture.ctx, fixture.scope, navigation), ErrSchemaWikiPreparationInvalid)

	next.Request.BaseRequest.ExistingFields = next.Request.BaseRequest.ExistingFields[:len(next.Request.BaseRequest.ExistingFields)-1]
	require.ErrorIs(
		t, schema.validateBatchConceptBase830G3(fixture.ctx, fixture.scope, next),
		ErrSchemaWikiPreparationInvalid,
	)
}

func TestBatchConceptActivePage830G3ReopensWholePinnedBundle(t *testing.T) {
	fixture, schema, bundle := batchConceptReleaseFixture830G3(t)
	draft, err := schema.CreateBatchConceptDraft830G3(
		fixture.ctx, fixture.principal1, fixture.scope,
		"batch-g3-active-page", batchConceptCandidateVector830G3(t),
	)
	require.NoError(t, err)
	rawDecision, decision := conceptDecision830G2(t, fixture, draft, "batch-g3-active-page")
	ready, err := schema.ReviewSchemaDraft(fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision)
	require.NoError(t, err)
	receipt, err := fixture.service.ActivateReviewed(
		fixture.ctx, fixture.principal1, rawDecision,
		conceptAuthorization830G2(t, fixture, ready, decision),
	)
	require.NoError(t, err)
	overview := nextBatchConceptMember830G3(t, bundle.PageManifest.Members, "entity_overview")

	current, err := schema.ReadConceptPage830G2(
		fixture.ctx, fixture.principal1, fixture.scope, overview.MemberID, "",
	)
	require.NoError(t, err)
	require.Equal(t, "current", current.ReadMode)
	require.Equal(t, receipt.ReleaseID, current.ReleaseID)
	require.Equal(t, bundle.CandidateHash, current.CandidateHash)
	require.Equal(t, overview.Kind, current.Member.Kind)
	require.Equal(t, overview.MemberID, current.Member.MemberID)
	require.Equal(t, overview.OwnerID, current.Member.OwnerID)
	require.Equal(t, overview.Title, current.Member.Title)
	require.Equal(t, overview.Content, current.Member.Content)
	require.JSONEq(t, string(overview.Payload), string(current.Member.Payload))
	require.Empty(t, current.Citations)
	var directory types.EntityDirectoryEntry830G3
	require.NoError(t, json.Unmarshal(overview.Payload, &directory))
	wantedRelated := map[string]struct{}{}
	for _, section := range directory.Sections {
		for _, field := range section.Fields {
			wantedRelated[field.MemberID] = struct{}{}
		}
	}
	expectedOrder := make([]string, 0, len(wantedRelated))
	for _, member := range bundle.PageManifest.Members {
		if _, ok := wantedRelated[member.MemberID]; ok {
			expectedOrder = append(expectedOrder, member.MemberID)
		}
	}
	require.Len(t, current.RelatedMembers, len(wantedRelated))
	actualOrder := make([]string, 0, len(current.RelatedMembers))
	for _, member := range current.RelatedMembers {
		require.Equal(t, overview.OwnerID, member.OwnerID)
		require.Equal(t, "field_assertion", member.Kind)
		actualOrder = append(actualOrder, member.MemberID)
	}
	require.Equal(t, expectedOrder, actualOrder)

	pinned, err := schema.ReadConceptPage830G2(
		fixture.ctx, fixture.principal1, fixture.scope, overview.MemberID, receipt.ReleaseID,
	)
	require.NoError(t, err)
	require.Equal(t, "pinned", pinned.ReadMode)
	require.Equal(t, current.Member, pinned.Member)
	require.Equal(t, current.RelatedMembers, pinned.RelatedMembers)

	pin, view, err := schema.loadExactConceptBundle830G2(
		fixture.ctx, fixture.principal1, fixture.scope, receipt.ReleaseID,
	)
	require.NoError(t, err)
	require.Equal(t, receipt.ReleaseID, pin.ReleaseID())
	require.Equal(t, bundle.CandidateHash, view.CandidateHash)
	require.Len(t, view.PageManifest.Members, 354)
	for _, member := range view.PageManifest.Members {
		citations := conceptMemberCitations830G2(view, member)
		if len(citations) == 0 {
			continue
		}
		_, found := conceptEvidenceByCitationID830G2(view, member.MemberID, citations[0].CitationID)
		require.True(t, found, "the pinned G3 view must resolve its own citation before token issuance")
		return
	}
	t.Fatal("fixture contains no cited member")
}

func TestBatchConceptQuery830G3UsesOnePinAndKeepsG2Selection(t *testing.T) {
	fixture, schema, bundle := batchConceptReleaseFixture830G3(t)
	base, err := types.ParseConceptCandidateBundle830G2(actualConceptBaseVector830G3(t))
	require.NoError(t, err)
	require.NotEmpty(t, base.PageManifest.Members)

	// Repeated/mixed query state remains legacy-compatible when the first
	// selected immutable release is G2.
	g2Page, err := schema.ReadConceptPageQuery830G3(
		fixture.ctx, fixture.principal1, fixture.scope,
		base.PageManifest.Members[0].MemberID,
		[]string{"  " + bundle.Request.BaseRequest.BaseReleaseID + "  ", "future-g3"}, true,
	)
	require.NoError(t, err)
	require.Equal(t, bundle.Request.BaseRequest.BaseReleaseID, g2Page.ReleaseID)
	require.Equal(t, "pinned", g2Page.ReadMode)
	g2Current, err := schema.ReadConceptPageQuery830G3(
		fixture.ctx, fixture.principal1, fixture.scope,
		base.PageManifest.Members[0].MemberID,
		[]string{"   ", "future-g3"}, true,
	)
	require.NoError(t, err)
	require.Equal(t, bundle.Request.BaseRequest.BaseReleaseID, g2Current.ReleaseID)
	require.Equal(t, "current", g2Current.ReadMode)

	draft, err := schema.CreateBatchConceptDraft830G3(
		fixture.ctx, fixture.principal1, fixture.scope,
		"batch-g3-query-pin", batchConceptCandidateVector830G3(t),
	)
	require.NoError(t, err)
	rawDecision, decision := conceptDecision830G2(t, fixture, draft, "batch-g3-query-pin")
	ready, err := schema.ReviewSchemaDraft(
		fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision,
	)
	require.NoError(t, err)
	receipt, err := fixture.service.ActivateReviewed(
		fixture.ctx, fixture.principal1, rawDecision,
		conceptAuthorization830G2(t, fixture, ready, decision),
	)
	require.NoError(t, err)
	overview := nextBatchConceptMember830G3(t, bundle.PageManifest.Members, "entity_overview")

	current, err := schema.ReadConceptPageQuery830G3(
		fixture.ctx, fixture.principal1, fixture.scope, overview.MemberID, nil, false,
	)
	require.NoError(t, err)
	require.Equal(t, receipt.ReleaseID, current.ReleaseID)
	pinned, err := schema.ReadConceptPageQuery830G3(
		fixture.ctx, fixture.principal1, fixture.scope, overview.MemberID,
		[]string{"  " + receipt.ReleaseID + "  "}, false,
	)
	require.NoError(t, err)
	require.Equal(t, receipt.ReleaseID, pinned.ReleaseID)
	for _, test := range []struct {
		name     string
		releases []string
		prep     bool
	}{
		{name: "explicit empty", releases: []string{""}},
		{name: "repeated", releases: []string{receipt.ReleaseID, "other"}},
		{name: "mixed preparation", releases: []string{receipt.ReleaseID}, prep: true},
	} {
		t.Run(test.name, func(t *testing.T) {
			_, readErr := schema.ReadConceptPageQuery830G3(
				fixture.ctx, fixture.principal1, fixture.scope, overview.MemberID,
				test.releases, test.prep,
			)
			require.ErrorIs(t, readErr, ErrSchemaWikiPreparationInvalid)
		})
	}

	// Advance Head from the access callback that follows BeginPinnedRead. The
	// returned page must still come from the sole pin observed before it.
	verifier := &batchConceptQueryAccessVerifier830G3{delegate: fixture.access}
	verifier.onSearch = func() {
		now := time.Unix(990, 0).UTC()
		_, activateErr := fixture.repo.Activate(fixture.ctx, wikirepository.WikiReleaseActivationWrite{
			Release: &types.WikiRelease{
				ID: "after-query-pin", WikiReleaseScope: fixture.scope,
				CandidateDigest: "after-query-candidate", ManifestDigest: "after-query-manifest",
				BaseReleaseID: receipt.ReleaseID, BaseActivationEpoch: receipt.ActivationEpoch,
				PreparationID: "after-query-preparation", CreatedAt: now, ActivatedAt: now,
			},
			ExpectedReleaseID: receipt.ReleaseID, ExpectedActivationEpoch: receipt.ActivationEpoch,
			Nonce: "after-query-pin", AuthorizationDigest: "after-query-authorization",
			ActivatedBy: fixture.principal1.ID, ActivatedAt: now,
			ActivationReceiptID: "after-query-receipt",
		})
		require.NoError(t, activateErr)
	}
	fixture.service.accessVerifier = verifier
	stable, err := schema.ReadConceptPageQuery830G3(
		fixture.ctx, fixture.principal1, fixture.scope, overview.MemberID, nil, false,
	)
	require.NoError(t, err)
	require.Equal(t, receipt.ReleaseID, stable.ReleaseID)
	require.Equal(t, uint64(1), uint64(strings.Count(strings.Join(verifier.operations, ","), "current")))
	head, err := fixture.repo.GetHead(fixture.ctx, fixture.scope)
	require.NoError(t, err)
	require.Equal(t, "after-query-pin", head.ActiveReleaseID)

	// A malformed pinned G3 citation is rejected after the same immutable
	// bundle classification and before the empty source bridge can be called.
	schema.conceptSourceAuthority = &ConceptSourceAuthorityService830G2{}
	_, err = schema.IssueConceptCitationQuery830G3(
		fixture.ctx, fixture.principal1, fixture.scope, overview.MemberID, "citation-unused",
		[]string{receipt.ReleaseID, "other"}, true,
	)
	require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
}

func TestBatchConceptActivation830G3RejectsStaleHeadWithoutReceipt(t *testing.T) {
	fixture, schema, _ := batchConceptReleaseFixture830G3(t)
	draft, err := schema.CreateBatchConceptDraft830G3(
		fixture.ctx, fixture.principal1, fixture.scope,
		"batch-g3-stale-head", batchConceptCandidateVector830G3(t),
	)
	require.NoError(t, err)
	rawDecision, decision := conceptDecision830G2(t, fixture, draft, "batch-g3-stale-head")
	ready, err := schema.ReviewSchemaDraft(fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision)
	require.NoError(t, err)
	now := time.Unix(975, 0).UTC()
	_, err = fixture.repo.Activate(fixture.ctx, wikirepository.WikiReleaseActivationWrite{
		Release: &types.WikiRelease{
			ID: "intervening-release", WikiReleaseScope: fixture.scope,
			CandidateDigest: "intervening-candidate", ManifestDigest: "intervening-manifest",
			BaseReleaseID: ready.ExpectedReleaseID, BaseActivationEpoch: ready.ExpectedActivationEpoch,
			PreparationID: "intervening-preparation", CreatedAt: now, ActivatedAt: now,
		},
		ExpectedReleaseID: ready.ExpectedReleaseID, ExpectedActivationEpoch: ready.ExpectedActivationEpoch,
		Nonce: "intervening-nonce", AuthorizationDigest: "intervening-authorization",
		ActivatedBy: fixture.principal1.ID, ActivatedAt: now, ActivationReceiptID: "intervening-receipt",
	})
	require.NoError(t, err)

	_, err = fixture.service.ActivateReviewed(
		fixture.ctx, fixture.principal1, rawDecision,
		conceptAuthorization830G2(t, fixture, ready, decision),
	)
	require.ErrorIs(t, err, ErrWikiReleaseConflict)
	persisted, readErr := fixture.repo.GetReadyPreparation(fixture.ctx, fixture.scope, ready.ID)
	require.NoError(t, readErr)
	require.Equal(t, ready.PreparationDigest, persisted.PreparationDigest)
	_, receiptErr := fixture.repo.GetReceipt(fixture.ctx, fixture.scope, decision.Nonce)
	require.ErrorIs(t, receiptErr, wikirepository.ErrWikiReleaseNotFound)
	head, headErr := fixture.repo.GetHead(fixture.ctx, fixture.scope)
	require.NoError(t, headErr)
	require.Equal(t, "intervening-release", head.ActiveReleaseID)
}

func nextBatchConceptMember830G3(
	t *testing.T, members []types.ConceptPageMember830G2, kind string,
) types.ConceptPageMember830G2 {
	t.Helper()
	for _, member := range members {
		if member.Kind == kind {
			return member
		}
	}
	t.Fatalf("missing %s member", kind)
	return types.ConceptPageMember830G2{}
}

func TestBatchConceptSourceDrift830G3PreservesPreparationAndHead(t *testing.T) {
	t.Run("before review", func(t *testing.T) {
		fixture, schema, _ := batchConceptReleaseFixture830G3(t)
		draft, err := schema.CreateBatchConceptDraft830G3(
			fixture.ctx, fixture.principal1, fixture.scope,
			"batch-g3-review-drift", batchConceptCandidateVector830G3(t),
		)
		require.NoError(t, err)
		verifier := fixture.service.conceptSourceAuthorityVerifier830G2.(*conceptSourceAuthorityVerifierFake830G2)
		verifier.err = errors.New("source drift")
		rawDecision, _ := conceptDecision830G2(t, fixture, draft, "batch-g3-review-drift")
		_, err = schema.ReviewSchemaDraft(fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision)
		require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
		stored, readErr := fixture.repo.GetDraftPreparation(fixture.ctx, fixture.scope, draft.ID)
		require.NoError(t, readErr)
		require.Equal(t, types.WikiReleasePreparationDraft, stored.Status)
		head, headErr := fixture.repo.GetHead(fixture.ctx, fixture.scope)
		require.NoError(t, headErr)
		require.Equal(t, bundleBaseReleaseID830G3(t), head.ActiveReleaseID)
	})

	t.Run("after ready", func(t *testing.T) {
		fixture, schema, _ := batchConceptReleaseFixture830G3(t)
		draft, err := schema.CreateBatchConceptDraft830G3(
			fixture.ctx, fixture.principal1, fixture.scope,
			"batch-g3-activate-drift", batchConceptCandidateVector830G3(t),
		)
		require.NoError(t, err)
		rawDecision, decision := conceptDecision830G2(t, fixture, draft, "batch-g3-activate-drift")
		ready, err := schema.ReviewSchemaDraft(fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision)
		require.NoError(t, err)
		verifier := fixture.service.conceptSourceAuthorityVerifier830G2.(*conceptSourceAuthorityVerifierFake830G2)
		verifier.err = errors.New("source drift")
		_, err = fixture.service.ActivateReviewed(
			fixture.ctx, fixture.principal1, rawDecision,
			conceptAuthorization830G2(t, fixture, ready, decision),
		)
		require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
		stored, readErr := fixture.repo.GetReadyPreparation(fixture.ctx, fixture.scope, ready.ID)
		require.NoError(t, readErr)
		require.Equal(t, types.WikiReleasePreparationReady, stored.Status)
		head, headErr := fixture.repo.GetHead(fixture.ctx, fixture.scope)
		require.NoError(t, headErr)
		require.Equal(t, bundleBaseReleaseID830G3(t), head.ActiveReleaseID)
	})
}

func TestBatchConceptRealCreateSourceGate830G3FailsBeforeDraftWrite(t *testing.T) {
	fixture, schema, _ := batchConceptReleaseFixture830G3(t)
	fixture.service.conceptSourceAuthorityVerifier830G2 = &ConceptSourceAuthorityService830G2{
		releases: fixture.repo,
	}
	_, err := schema.CreateBatchConceptDraft830G3(
		fixture.ctx, fixture.principal1, fixture.scope,
		"batch-g3-real-source-denied", batchConceptCandidateVector830G3(t),
	)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
	_, readErr := fixture.repo.GetDraftPreparation(fixture.ctx, fixture.scope, "batch-g3-real-source-denied")
	require.ErrorIs(t, readErr, wikirepository.ErrWikiReleaseNotFound)
}

type batchConceptReceiptGateVerifier830G3 struct {
	source          types.KnowledgeRevisionSource
	receiptContract string
	calls           int
}

func (verifier *batchConceptReceiptGateVerifier830G3) VerifyConceptSources830G2(
	_ context.Context,
	request ConceptSourceAuthorityVerificationRequest830G2,
) error {
	verifier.calls++
	bundle, err := types.ParseBatchConceptCandidateBundle830G3(request.Manifest)
	if err != nil || len(bundle.Request.ResolutionInputs.Corpus.Entries) == 0 {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	receipt := bundle.Request.ResolutionInputs.Corpus.Entries[0].Receipt.Registered
	if receipt == nil {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	checked := *receipt
	if verifier.receiptContract != "" {
		checked.Contract = verifier.receiptContract
	}
	if !registeredReceiptMatchesSource830G3(checked, &verifier.source) {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	return nil
}

func batchConceptFirstRegisteredSource830G3(t *testing.T) types.KnowledgeRevisionSource {
	t.Helper()
	bundle, err := types.ParseBatchConceptCandidateBundle830G3(batchConceptCandidateVector830G3(t))
	require.NoError(t, err)
	receipt := bundle.Request.ResolutionInputs.Corpus.Entries[0].Receipt.Registered
	require.NotNil(t, receipt)
	pageCount := int(receipt.PageCount)
	return types.KnowledgeRevisionSource{
		KnowledgeID: receipt.KnowledgeID, ParseAttempt: receipt.ParseAttempt,
		RevisionSourceID: receipt.RevisionSourceID, FileSHA256: receipt.FileSHA256,
		ObjectSHA256: receipt.ObjectSHA256, Size: receipt.Size, MimeType: receipt.MIMEType,
		PageCount: &pageCount, ManifestAlgorithm: receipt.ManifestAlgorithm,
		ManifestDigest: receipt.ManifestDigest, ChunkCount: int(receipt.ChunkCount),
		BindingDigest: receipt.BindingDigest, RetentionState: receipt.RetentionState,
	}
}

func TestBatchConceptCreate830G3RejectsEveryRegisteredReceiptFieldBeforeDraftWrite(t *testing.T) {
	tests := map[string]func(*batchConceptReceiptGateVerifier830G3){
		"contract": func(gate *batchConceptReceiptGateVerifier830G3) {
			gate.receiptContract = "other"
		},
		"knowledge": func(gate *batchConceptReceiptGateVerifier830G3) { gate.source.KnowledgeID = "other" },
		"attempt":   func(gate *batchConceptReceiptGateVerifier830G3) { gate.source.ParseAttempt++ },
		"revision source": func(gate *batchConceptReceiptGateVerifier830G3) {
			gate.source.RevisionSourceID = testSHA830G2("other")
		},
		"file": func(gate *batchConceptReceiptGateVerifier830G3) {
			gate.source.FileSHA256 = testSHA830G2("other")
		},
		"object": func(gate *batchConceptReceiptGateVerifier830G3) {
			gate.source.ObjectSHA256 = testSHA830G2("other")
		},
		"size": func(gate *batchConceptReceiptGateVerifier830G3) { gate.source.Size++ },
		"mime": func(gate *batchConceptReceiptGateVerifier830G3) { gate.source.MimeType = "text/plain" },
		"page count": func(gate *batchConceptReceiptGateVerifier830G3) {
			(*gate.source.PageCount)++
		},
		"manifest algorithm": func(gate *batchConceptReceiptGateVerifier830G3) {
			gate.source.ManifestAlgorithm = "other"
		},
		"manifest digest": func(gate *batchConceptReceiptGateVerifier830G3) {
			gate.source.ManifestDigest = testSHA830G2("other")
		},
		"chunk count": func(gate *batchConceptReceiptGateVerifier830G3) { gate.source.ChunkCount++ },
		"binding": func(gate *batchConceptReceiptGateVerifier830G3) {
			gate.source.BindingDigest = testSHA830G2("other")
		},
		"retention": func(gate *batchConceptReceiptGateVerifier830G3) {
			gate.source.RetentionState = "released"
		},
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			fixture, schema, _ := batchConceptReleaseFixture830G3(t)
			gate := &batchConceptReceiptGateVerifier830G3{source: batchConceptFirstRegisteredSource830G3(t)}
			mutate(gate)
			fixture.service.conceptSourceAuthorityVerifier830G2 = gate
			preparationID := "batch-g3-receipt-drift-" + strings.ReplaceAll(name, " ", "-")
			_, err := schema.CreateBatchConceptDraft830G3(
				fixture.ctx, fixture.principal1, fixture.scope,
				preparationID, batchConceptCandidateVector830G3(t),
			)
			require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
			require.Equal(t, 1, gate.calls)
			_, readErr := fixture.repo.GetDraftPreparation(fixture.ctx, fixture.scope, preparationID)
			require.ErrorIs(t, readErr, wikirepository.ErrWikiReleaseNotFound,
				"source drift must fail before the repository creates a Draft")
		})
	}
}

func bundleBaseReleaseID830G3(t *testing.T) string {
	t.Helper()
	bundle, err := types.ParseBatchConceptCandidateBundle830G3(batchConceptCandidateVector830G3(t))
	require.NoError(t, err)
	return bundle.Request.BaseRequest.BaseReleaseID
}
