package service

import (
	"context"
	"crypto/ed25519"
	"encoding/json"
	"errors"
	"strconv"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func automatedFixture(t *testing.T) (*wikiReleaseFixture, *SchemaWikiService, *SystemAutomationPolicy) {
	t.Helper()
	f, s, _ := batchConceptReleaseFixture830G3(t)
	f.ctx = systemTestContext(f.scope)
	f.principal1.ID = "api_tenant:" + strconv.FormatUint(f.scope.TenantID, 10)
	f.principal1.APIKeyKnowledgeBaseIDs = []string{f.scope.RawKBID, f.scope.WikiKBID}
	f.access.allowed[f.principal1.ID] = f.scope
	p := systemTestPolicy(f.scope, f.principal1.ID)
	f.service.systemPolicyProvider = SystemAutomationPolicyProviderFunc(func(context.Context, types.WikiReleasePrincipal, types.WikiReleaseScope) (*SystemAutomationPolicy, error) {
		return p, nil
	})
	f.service.systemDecisionVerifier = NewEd25519SystemPolicyDecisionVerifier(map[string]ed25519.PublicKey{"system-1": f.privateKey.Public().(ed25519.PublicKey)})
	return f, s, p
}

func automaticDecision(t *testing.T, f *wikiReleaseFixture, p *SystemAutomationPolicy, draft *types.WikiReleasePreparation) ([]byte, *SystemPolicyDecisionReceiptV1) {
	t.Helper()
	d := systemTestDecision(p)
	d.PreparationID = draft.ID
	d.DraftPreparationDigest = draft.PreparationDigest
	d.CandidateDigest = draft.CandidateDigest
	d.ManifestDigest = draft.ManifestDigest
	d.ReadyReceiptDigest = draft.ReadyReceiptDigest
	d.InnerReviewPolicyID = draft.ReviewPolicyID
	d.ExpectedReleaseID = draft.ExpectedReleaseID
	d.ExpectedActivationEpoch = draft.ExpectedActivationEpoch
	return signSystemTestDecision(t, d, f.privateKey), d
}

func automaticAuthorization(t *testing.T, f *wikiReleaseFixture, ready *types.WikiReleasePreparation, nonce string) []byte {
	t.Helper()
	a := &types.PublishAuthorizationV0{Version: "0", Action: "activate", PreparationID: ready.ID, CandidateDigest: ready.CandidateDigest, ManifestDigest: ready.ManifestDigest, ReadyReceiptDigest: ready.ReadyReceiptDigest, ReviewDecisionDigest: ready.ReviewDecisionDigest, ReviewPolicyID: ready.ReviewPolicyID, TenantID: f.scope.TenantID, SpaceID: f.scope.SpaceID, RawKBID: f.scope.RawKBID, WikiKBID: f.scope.WikiKBID, ExpectedReleaseID: ready.ExpectedReleaseID, ExpectedActivationEpoch: ready.ExpectedActivationEpoch, ExpiresAt: 2000, Nonce: nonce, SignerKeyID: "signer-1"}
	raw, err := CanonicalPublishAuthorizationV0(a, false)
	require.NoError(t, err)
	a.Signature = EncodeWikiReleaseSignature(ed25519.Sign(f.privateKey, raw))
	raw, err = CanonicalPublishAuthorizationV0(a, true)
	require.NoError(t, err)
	return raw
}

func TestAutomatedWikiReleaseDraftReadyActivationAndReplay(t *testing.T) {
	f, s, p := automatedFixture(t)
	draft, err := s.CreateBatchConceptDraftAutomated830G3(f.ctx, f.principal1, f.scope, "auto-draft", batchConceptCandidateVector830G3(t))
	require.NoError(t, err)
	raw, d := automaticDecision(t, f, p, draft)
	ready, err := f.service.ReviewDraftAutomated(f.ctx, f.principal1, f.scope, draft.ID, raw)
	require.NoError(t, err)
	require.Equal(t, draft.ReviewPolicyID, ready.ReviewPolicyID, "outer policy cannot replace inner compiler policy")
	require.NotEqual(t, p.Digest, ready.ReviewPolicyID)
	require.Equal(t, digestWikiReleaseBytes(raw), ready.ReviewDecisionDigest)
	repeated, err := f.service.ReviewDraftAutomated(f.ctx, f.principal1, f.scope, draft.ID, raw)
	require.NoError(t, err)
	require.Equal(t, ready, repeated)
	d.Nonce = "other-decision"
	changed := signSystemTestDecision(t, d, f.privateKey)
	_, err = f.service.ReviewDraftAutomated(f.ctx, f.principal1, f.scope, draft.ID, changed)
	require.Error(t, err)
	a := automaticAuthorization(t, f, ready, "system-nonce")
	receipt, err := f.service.ActivateAutomated(f.ctx, f.principal1, raw, a)
	require.NoError(t, err)
	require.Equal(t, uint64(6), receipt.ActivationEpoch)
	before, err := f.repo.CountState(f.ctx)
	require.NoError(t, err)
	*f.nowUnix = 2100
	replay, err := f.service.ActivateAutomated(f.ctx, f.principal1, raw, a)
	require.NoError(t, err)
	require.Equal(t, receipt, replay)
	after, err := f.repo.CountState(f.ctx)
	require.NoError(t, err)
	require.Equal(t, before, after)
	p.Enabled = false
	p.Digest, _ = SystemAutomationPolicyDigest(p)
	_, err = f.service.ActivateAutomated(f.ctx, f.principal1, raw, a)
	require.Error(t, err, "revocation blocks even exact committed replay")
}

func TestAutomatedWikiReleaseCreateDraftExactReplay(t *testing.T) {
	f, s, p := automatedFixture(t)
	raw := batchConceptCandidateVector830G3(t)
	draft, err := s.CreateBatchConceptDraftAutomated830G3(f.ctx, f.principal1, f.scope, "crash-replay", raw)
	require.NoError(t, err)
	before, err := f.repo.CountState(f.ctx)
	require.NoError(t, err)
	*f.nowUnix += 10
	stored, err := f.repo.GetDraftPreparation(f.ctx, f.scope, draft.ID)
	require.NoError(t, err)
	require.True(t, stored.PreparationDigest == digestWikiReleasePreparation(stored), "stored digest")
	bundle, canonical, err := types.CanonicalBatchConceptCandidateBundle830G3(raw)
	require.NoError(t, err)
	members, err := bundle.SnapshotMembers()
	require.NoError(t, err)
	storedCanonical, err := types.CanonicalConceptMemberPayload830G2(stored.Manifest)
	require.NoError(t, err)
	require.True(t, string(storedCanonical) == string(canonical), "stored canonical manifest")
	for index := range members {
		require.True(t, conceptMemberSnapshotEqual830G2(stored.Members[index], members[index]), "member index %d kind %s", index, members[index].Kind)
	}
	replayed, err := s.CreateBatchConceptDraftAutomated830G3(f.ctx, f.principal1, f.scope, draft.ID, raw)
	require.NoError(t, err, "remote success before local checkpoint must replay the exact persisted Draft")
	// The HTTP metadata excludes the JSONB bodies, whose storage representation
	// can change escaping. Their canonical contents are checked above and in replay.
	wantMetadata, gotMetadata := *draft, *replayed
	wantMetadata.Manifest, gotMetadata.Manifest = nil, nil
	wantMetadata.Members, gotMetadata.Members = nil, nil
	require.Equal(t, wantMetadata, gotMetadata, "including original CreatedAt used by deterministic signing")
	after, err := f.repo.CountState(f.ctx)
	require.NoError(t, err)
	require.Equal(t, before, after)

	source := f.service.conceptSourceAuthorityVerifier830G2
	f.service.conceptSourceAuthorityVerifier830G2 = nil
	_, err = s.CreateBatchConceptDraftAutomated830G3(f.ctx, f.principal1, f.scope, draft.ID, raw)
	require.Error(t, err, "replay cannot bypass immutable source verification")
	f.service.conceptSourceAuthorityVerifier830G2 = source
	delete(f.access.allowed, f.principal1.ID)
	_, err = s.CreateBatchConceptDraftAutomated830G3(f.ctx, f.principal1, f.scope, draft.ID, raw)
	require.Error(t, err, "replay cannot bypass current ACL")
	f.access.allowed[f.principal1.ID] = f.scope
	wrongScope := f.scope
	wrongScope.WikiKBID = "wrong-wiki"
	_, err = s.CreateBatchConceptDraftAutomated830G3(f.ctx, f.principal1, wrongScope, draft.ID, raw)
	require.Error(t, err)
	p.Enabled = false
	p.Digest, _ = SystemAutomationPolicyDigest(p)
	_, err = s.CreateBatchConceptDraftAutomated830G3(f.ctx, f.principal1, f.scope, draft.ID, raw)
	require.Error(t, err, "current policy revocation blocks exact replay")
}

func TestAutomatedWikiReleaseCreateDraftReplayRejectsStoredConflicts(t *testing.T) {
	f, s, p := automatedFixture(t)
	raw := batchConceptCandidateVector830G3(t)
	draft, err := s.CreateBatchConceptDraftAutomated830G3(f.ctx, f.principal1, f.scope, "original-draft", raw)
	require.NoError(t, err)
	for name, mutate := range map[string]func(*types.WikiReleasePreparation){
		"candidate": func(d *types.WikiReleasePreparation) { d.CandidateDigest = d.ManifestDigest },
		"parent":    func(d *types.WikiReleasePreparation) { d.ExpectedActivationEpoch++ },
		"scope":     func(d *types.WikiReleasePreparation) { d.WikiKBID = "other-wiki" },
		"manifest":  func(d *types.WikiReleasePreparation) { d.Manifest = json.RawMessage(`{}`) },
		"members":   func(d *types.WikiReleasePreparation) { d.Members = nil },
	} {
		t.Run(name, func(t *testing.T) {
			collision := *draft
			collision.ID = "collision-" + name
			mutate(&collision)
			collision.PreparationDigest = digestWikiReleasePreparation(&collision)
			require.NoError(t, f.repo.CreateReadyPreparation(f.ctx, &collision))
			_, err := s.CreateBatchConceptDraftAutomated830G3(f.ctx, f.principal1, f.scope, collision.ID, raw)
			require.Error(t, err, "an occupied ID must never adopt a different request")
		})
	}
	decision, _ := automaticDecision(t, f, p, draft)
	ready, err := f.service.ReviewDraftAutomated(f.ctx, f.principal1, f.scope, draft.ID, decision)
	require.NoError(t, err)
	_, err = f.service.ActivateAutomated(f.ctx, f.principal1, decision, automaticAuthorization(t, f, ready, "system-nonce"))
	require.NoError(t, err)
	_, err = s.CreateBatchConceptDraftAutomated830G3(f.ctx, f.principal1, f.scope, draft.ID, raw)
	require.Error(t, err, "the original parent must still be current")
}

func TestAutomatedWikiReleasePolicyIdentityAndReceiptFailuresWriteNothing(t *testing.T) {
	f, s, p := automatedFixture(t)
	before, err := f.repo.CountState(f.ctx)
	require.NoError(t, err)
	p.Enabled = false
	p.Digest, _ = SystemAutomationPolicyDigest(p)
	_, err = s.CreateBatchConceptDraftAutomated830G3(f.ctx, f.principal1, f.scope, "invalid-policy", batchConceptCandidateVector830G3(t))
	require.Error(t, err)
	after, err := f.repo.CountState(f.ctx)
	require.NoError(t, err)
	require.Equal(t, before, after)
	p.Enabled = true
	p.Digest, _ = SystemAutomationPolicyDigest(p)
	draft, err := s.CreateBatchConceptDraftAutomated830G3(f.ctx, f.principal1, f.scope, "invalid-decisions", batchConceptCandidateVector830G3(t))
	require.NoError(t, err)
	_, valid := automaticDecision(t, f, p, draft)
	cases := map[string]func(*SystemPolicyDecisionReceiptV1){
		"scope":           func(d *SystemPolicyDecisionReceiptV1) { d.WikiKBID = "other" },
		"key":             func(d *SystemPolicyDecisionReceiptV1) { d.APIKeyID++ },
		"policy":          func(d *SystemPolicyDecisionReceiptV1) { d.PolicyVersion = "2" },
		"candidate":       func(d *SystemPolicyDecisionReceiptV1) { d.CandidateDigest = d.ManifestDigest },
		"draft digest":    func(d *SystemPolicyDecisionReceiptV1) { d.DraftPreparationDigest = d.ManifestDigest },
		"inner policy":    func(d *SystemPolicyDecisionReceiptV1) { d.InnerReviewPolicyID = p.Digest },
		"parent":          func(d *SystemPolicyDecisionReceiptV1) { d.ExpectedActivationEpoch++ },
		"expired":         func(d *SystemPolicyDecisionReceiptV1) { d.ExpiresAt = 1000 },
		"future":          func(d *SystemPolicyDecisionReceiptV1) { d.IssuedAt = 1001 },
		"policy lifetime": func(d *SystemPolicyDecisionReceiptV1) { d.ExpiresAt = 3001 },
		"capabilities":    func(d *SystemPolicyDecisionReceiptV1) { d.Capabilities = []string{"activate"} },
		"reject":          func(d *SystemPolicyDecisionReceiptV1) { d.Decision = "reject" },
	}
	for name, change := range cases {
		t.Run(name, func(t *testing.T) {
			d := *valid
			change(&d)
			raw := signSystemTestDecision(t, &d, f.privateKey)
			_, err := f.service.ReviewDraftAutomated(f.ctx, f.principal1, f.scope, draft.ID, raw)
			require.Error(t, err)
			stored, err := f.repo.GetDraftPreparation(f.ctx, f.scope, draft.ID)
			require.NoError(t, err)
			require.Equal(t, draft.PreparationDigest, stored.PreparationDigest)
		})
	}
	raw, _ := automaticDecision(t, f, p, draft)
	_, err = f.service.ReviewDraftAutomated(f.ctx, f.principal1, f.scope, draft.ID, append([]byte(" "), raw...))
	require.Error(t, err)
	human, _ := conceptDecision830G2(t, f, draft, "human-receipt")
	_, err = f.service.ReviewDraftAutomated(f.ctx, f.principal1, f.scope, draft.ID, human)
	require.Error(t, err)
	_, err = s.CreateBatchConceptDraft830G3(f.ctx, f.principal1, f.scope, "human-guard", batchConceptCandidateVector830G3(t))
	require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
}

func TestAutomatedWikiReleasePreservesACLSourceAndCAS(t *testing.T) {
	f, s, p := automatedFixture(t)
	draft, err := s.CreateBatchConceptDraftAutomated830G3(f.ctx, f.principal1, f.scope, "gated-auto", batchConceptCandidateVector830G3(t))
	require.NoError(t, err)
	raw, _ := automaticDecision(t, f, p, draft)
	source := f.service.conceptSourceAuthorityVerifier830G2
	f.service.conceptSourceAuthorityVerifier830G2 = nil
	_, err = f.service.ReviewDraftAutomated(f.ctx, f.principal1, f.scope, draft.ID, raw)
	require.Error(t, err)
	f.service.conceptSourceAuthorityVerifier830G2 = source
	delete(f.access.allowed, f.principal1.ID)
	_, err = f.service.ReviewDraftAutomated(f.ctx, f.principal1, f.scope, draft.ID, raw)
	require.Error(t, err)
	f.access.allowed[f.principal1.ID] = f.scope
	ready, err := f.service.ReviewDraftAutomated(f.ctx, f.principal1, f.scope, draft.ID, raw)
	require.NoError(t, err)
	auth := automaticAuthorization(t, f, ready, "system-nonce")
	before, err := f.repo.CountState(f.ctx)
	require.NoError(t, err)
	f.service.conceptSourceAuthorityVerifier830G2 = nil
	_, err = f.service.ActivateAutomated(f.ctx, f.principal1, raw, auth)
	require.Error(t, err)
	f.service.conceptSourceAuthorityVerifier830G2 = source
	delete(f.access.allowed, f.principal1.ID)
	_, err = f.service.ActivateAutomated(f.ctx, f.principal1, raw, auth)
	require.Error(t, err)
	f.access.allowed[f.principal1.ID] = f.scope
	f.service.faults.CAS = func() error { return errors.New("fixture CAS failure") }
	_, err = f.service.ActivateAutomated(f.ctx, f.principal1, raw, auth)
	require.Error(t, err)
	after, err := f.repo.CountState(f.ctx)
	require.NoError(t, err)
	require.Equal(t, before, after)
	f.service.faults.CAS = nil
	badAuth, err := ParsePublishAuthorizationV0(auth)
	require.NoError(t, err)
	badAuth.ReviewDecisionDigest = draft.ManifestDigest
	unsigned, err := CanonicalPublishAuthorizationV0(badAuth, false)
	require.NoError(t, err)
	badAuth.Signature = EncodeWikiReleaseSignature(ed25519.Sign(f.privateKey, unsigned))
	badRaw, err := CanonicalPublishAuthorizationV0(badAuth, true)
	require.NoError(t, err)
	_, err = f.service.ActivateAutomated(f.ctx, f.principal1, raw, badRaw)
	require.Error(t, err)
	// No envelope field may smuggle unsigned caller data into the system receipt.
	var extra map[string]any
	require.NoError(t, json.Unmarshal(raw, &extra))
	extra["value"] = "unverified"
	badRaw, _ = json.Marshal(extra)
	_, err = f.service.ActivateAutomated(f.ctx, f.principal1, badRaw, auth)
	require.Error(t, err)
}

// This source port simulates elapsed time or a current-policy revocation during
// a strict source read; it does not replace the candidate/evidence validators.
type automaticSourceHook func()

func (h automaticSourceHook) VerifyConceptSources830G2(context.Context, ConceptSourceAuthorityVerificationRequest830G2) error {
	h()
	return nil
}

func TestAutomatedWikiReleaseDecisionExpiryAtWriteEdge(t *testing.T) {
	f, s, p := automatedFixture(t)
	draft, err := s.CreateBatchConceptDraftAutomated830G3(f.ctx, f.principal1, f.scope, "expiry-edge", batchConceptCandidateVector830G3(t))
	require.NoError(t, err)
	raw, _ := automaticDecision(t, f, p, draft)
	f.service.conceptSourceAuthorityVerifier830G2 = automaticSourceHook(func() { *f.nowUnix = 2000 })
	_, err = f.service.ReviewDraftAutomated(f.ctx, f.principal1, f.scope, draft.ID, raw)
	require.Error(t, err, "decision expires during source IO; must remain Draft")
	_, err = f.repo.GetDraftPreparation(f.ctx, f.scope, draft.ID)
	require.NoError(t, err)
}
