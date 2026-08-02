package main

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
	"sync/atomic"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
)

func TestReleaseProofRejectsMissingOrMalformedExternalHashesBeforeOperations(t *testing.T) {
	valid := proofInputHashes{
		CandidateHash:    strings.Repeat("a", 64),
		HumanBatchHash:   strings.Repeat("b", 64),
		PolicyHash:       strings.Repeat("c", 64),
		ReleaseHash:      strings.Repeat("d", 64),
		ArtifactHash:     strings.Repeat("e", 64),
		HumanReceiptHash: strings.Repeat("f", 64),
	}

	tests := map[string]func(*proofInputHashes){
		"missing candidate": func(input *proofInputHashes) { input.CandidateHash = "" },
		"uppercase batch":   func(input *proofInputHashes) { input.HumanBatchHash = strings.Repeat("A", 64) },
		"short policy":      func(input *proofInputHashes) { input.PolicyHash = strings.Repeat("c", 63) },
		"non hex release":   func(input *proofInputHashes) { input.ReleaseHash = strings.Repeat("z", 64) },
		"missing artifact":  func(input *proofInputHashes) { input.ArtifactHash = "" },
		"missing receipt":   func(input *proofInputHashes) { input.HumanReceiptHash = "" },
	}

	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			input := valid
			mutate(&input)
			operations := 0
			_, err := runReleaseProof(
				context.Background(),
				proofRunInput{Hashes: input},
				proofHooks{BeforeReleaseOperation: func() { operations++ }},
			)
			if err == nil {
				t.Fatal("expected typed invalid-input failure")
			}
			if operations != 0 {
				t.Fatalf("release operations = %d, want 0", operations)
			}
		})
	}
}

func TestReleaseProofSequenceUsesReal059ServiceAndRepository(t *testing.T) {
	input := newProofRunInput(t)
	hooks := proofHooks{Now: func() time.Time { return time.Unix(1_000, 0).UTC() }}
	first, err := runReleaseProof(context.Background(), input, hooks)
	if err != nil {
		t.Fatalf("run release proof: %v", err)
	}
	second, err := runReleaseProof(context.Background(), input, hooks)
	if err != nil {
		t.Fatalf("repeat release proof: %v", err)
	}
	if first.ObjectType != "release-proof-596-1" || len(first.C0Digest) != 64 {
		t.Fatalf("unexpected receipt identity: %#v", first)
	}
	if !bytes.Equal(first.Canonical, second.Canonical) || first.C0Digest != second.C0Digest {
		t.Fatal("same exact proof input was not deterministic")
	}

	var payload struct {
		Status              string                      `json:"status"`
		HeadEpochs          []int                       `json:"head_epochs"`
		HeadManifestDigests []string                    `json:"head_manifest_digests"`
		CASWinners          int                         `json:"cas_winners"`
		CASConflicts        int                         `json:"cas_conflicts"`
		CASBarrierArrivals  int                         `json:"cas_barrier_arrivals"`
		CASProofMode        string                      `json:"cas_proof_mode"`
		PinnedStable        bool                        `json:"pinned_stable"`
		ACLShrinkDenied     bool                        `json:"acl_shrink_denied"`
		RollbackChecks      int                         `json:"rollback_checks"`
		StateCounts         map[string]map[string]int64 `json:"state_counts"`
	}
	if err := json.Unmarshal(first.Canonical, &payload); err != nil {
		t.Fatalf("decode canonical proof: %v", err)
	}
	if payload.Status != "RELEASE_PROOF_COMPLETE" ||
		!equalInts(payload.HeadEpochs, []int{0, 1, 2, 3}) ||
		payload.CASWinners != 1 || payload.CASConflicts != 1 ||
		payload.CASBarrierArrivals != 2 ||
		payload.CASProofMode != "DETERMINISTIC_CONCURRENCY_PROOF_NOT_PG" ||
		!payload.PinnedStable || !payload.ACLShrinkDenied || payload.RollbackChecks != 2 {
		t.Fatalf("incomplete proof payload: %#v", payload)
	}
	if len(payload.HeadManifestDigests) != 4 || payload.HeadManifestDigests[0] != "" ||
		payload.HeadManifestDigests[1] != payload.HeadManifestDigests[3] ||
		payload.HeadManifestDigests[2] != input.R1.Preparation.ManifestDigest {
		t.Fatalf("unexpected head sequence: %#v", payload.HeadManifestDigests)
	}
	wantCounts := map[string]int64{
		"preparations": 3, "releases": 2, "members": 2, "heads": 1, "receipts": 3,
	}
	for name, want := range wantCounts {
		if payload.StateCounts["after_rollbacks"][name] != want {
			t.Fatalf(
				"final state count %s = %d, want %d",
				name, payload.StateCounts["after_rollbacks"][name], want,
			)
		}
	}
	if payload.StateCounts["initial"]["heads"] != 0 ||
		payload.StateCounts["after_r1"]["releases"] != 2 ||
		payload.StateCounts["after_revert"]["receipts"] != 3 {
		t.Fatalf("incomplete before/after count custody: %#v", payload.StateCounts)
	}

	serialized := string(first.Canonical)
	for _, forbidden := range []string{
		input.Principal.ID, input.Scope.SpaceID, input.Scope.RawKBID, input.Scope.WikiKBID,
		"R0 body", "R1 body", "signature", "private_key",
	} {
		if strings.Contains(serialized, forbidden) {
			t.Fatalf("proof receipt leaked forbidden value %q", forbidden)
		}
	}
}

func TestReleaseProofRejectsResignedPreparationDriftBeforeOperations(t *testing.T) {
	input := newProofRunInput(t)
	input.R1.Preparation.ReviewDecisionDigest = hashText("drifted-review-decision")
	authorizationKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x66}, ed25519.SeedSize))
	input.R1.ActivationAuthorization = signedAuthorization(
		t,
		authorizationKey,
		"activate",
		input.R1.Preparation,
		input.ReleaseIDs.R0,
		1,
		"nonce-r1",
	)
	operations := 0
	_, err := runReleaseProof(
		context.Background(),
		input,
		proofHooks{BeforeReleaseOperation: func() { operations++ }},
	)
	if err == nil {
		t.Fatal("expected resigned preparation drift to fail")
	}
	if operations != 0 {
		t.Fatalf("release operations = %d, want 0", operations)
	}
}

func TestReleaseProofRejectsFaultManifestDriftBeforeFaultActivation(t *testing.T) {
	input := newProofRunInput(t)
	input.FaultActivation.Preparation.ManifestDigest = hashText("drifted-fault-manifest")
	authorizationKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x66}, ed25519.SeedSize))
	input.FaultActivation.ActivationAuthorization = signedAuthorization(
		t,
		authorizationKey,
		"activate",
		input.FaultActivation.Preparation,
		input.ReleaseIDs.R0,
		3,
		"nonce-fault-activate",
	)
	if err := validateCanonicalAuthorities(input); err != nil {
		t.Fatalf("re-signed fault authority is invalid: %v", err)
	}
	if err := validateProofPlanBindings(input, 1_000); err != nil {
		t.Fatalf("re-signed fault plan is invalid: %v", err)
	}
	var operations atomic.Int32

	_, err := runReleaseProof(
		context.Background(),
		input,
		proofHooks{
			BeforeReleaseOperation: func() { operations.Add(1) },
			Now:                    func() time.Time { return time.Unix(1_000, 0).UTC() },
		},
	)

	if !errors.Is(err, errProofInvariant) {
		t.Fatalf("fault manifest drift error = %v, want proof invariant", err)
	}
	if got := operations.Load(); got != 12 {
		t.Fatalf("release operations = %d, want 12 before fault ActivateReviewed", got)
	}
}

func TestReleaseProofRejectsResignedAuthorizationPlanDriftBeforeOperations(t *testing.T) {
	authorizationKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x66}, ed25519.SeedSize))
	tests := map[string]func(*proofRunInput){
		"activation action": func(input *proofRunInput) {
			authorization := parseAuthorization(t, input.R0.ActivationAuthorization)
			authorization.Action = "revert"
			input.R0.ActivationAuthorization = resignAuthorization(t, authorizationKey, authorization)
		},
		"activation nonce": func(input *proofRunInput) {
			authorization := parseAuthorization(t, input.R1.ActivationAuthorization)
			authorization.Nonce = "nonce-r1-drift"
			input.R1.ActivationAuthorization = resignAuthorization(t, authorizationKey, authorization)
		},
		"revert expected epoch": func(input *proofRunInput) {
			authorization := parseAuthorization(t, input.RevertAuthorizations[0])
			authorization.ExpectedActivationEpoch = 3
			input.RevertAuthorizations[0] = resignAuthorization(t, authorizationKey, authorization)
		},
		"fault revert scope": func(input *proofRunInput) {
			authorization := parseAuthorization(t, input.FaultRevertAuthorization)
			authorization.SpaceID = "other-space"
			input.FaultRevertAuthorization = resignAuthorization(t, authorizationKey, authorization)
		},
	}

	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			input := newProofRunInput(t)
			mutate(&input)
			operations := 0
			_, err := runReleaseProof(
				context.Background(),
				input,
				proofHooks{BeforeReleaseOperation: func() { operations++ }},
			)
			if err == nil {
				t.Fatal("expected resigned authorization plan drift to fail")
			}
			if operations != 0 {
				t.Fatalf("release operations = %d, want 0", operations)
			}
		})
	}
}

func TestReleaseProofRejectsHumanReceiptHashDriftBeforeOperations(t *testing.T) {
	input := newProofRunInput(t)
	input.Hashes.HumanReceiptHash = hashText("different-human-receipt")
	operations := 0
	_, err := runReleaseProof(
		context.Background(),
		input,
		proofHooks{BeforeReleaseOperation: func() { operations++ }},
	)
	if err == nil {
		t.Fatal("expected human receipt hash drift to fail")
	}
	if operations != 0 {
		t.Fatalf("release operations = %d, want 0", operations)
	}
}

func TestReleaseProofRejectsUntrustedHumanSignatureBeforeOperations(t *testing.T) {
	input := newProofRunInput(t)
	receipt, err := service.ParseHumanBatchDecisionReceiptV1(input.R1.HumanDecision)
	if err != nil {
		t.Fatalf("parse human decision: %v", err)
	}
	receipt.Signature = base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{0x00}, 64))
	input.R1.HumanDecision, err = service.CanonicalHumanBatchDecisionReceiptV1(receipt, true)
	if err != nil {
		t.Fatalf("canonical drifted decision: %v", err)
	}
	input.Hashes.HumanReceiptHash = hashBytes(input.R1.HumanDecision)
	operations := 0
	_, err = runReleaseProof(
		context.Background(),
		input,
		proofHooks{BeforeReleaseOperation: func() { operations++ }},
	)
	if err == nil {
		t.Fatal("expected untrusted human signature to fail")
	}
	if operations != 0 {
		t.Fatalf("release operations = %d, want 0", operations)
	}
}

func TestProofReceiptC0DomainVector(t *testing.T) {
	canonical := []byte(`{"head_epochs":[1,2,3],"status":"RELEASE_PROOF_COMPLETE","version":"1"}`)
	const expected = "029b195b619d4b648e534c8aff3e455f2cd1d3450f6a28e94c62f373e7df136a"
	if got := c0ProofDigest(canonical); got != expected {
		t.Fatalf("C0 digest = %s, want frozen independent vector %s", got, expected)
	}
}

func newProofRunInput(t *testing.T) proofRunInput {
	t.Helper()
	humanKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x65}, ed25519.SeedSize))
	authorizationKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x66}, ed25519.SeedSize))
	scope := types.WikiReleaseScope{
		TenantID: 65, SpaceID: "proof-space", RawKBID: "proof-raw", WikiKBID: "proof-wiki",
	}
	principal := types.WikiReleasePrincipal{
		ID: "proof-principal", TenantID: scope.TenantID, SpaceID: scope.SpaceID,
	}
	releaseIDs := proofReleaseIDs{
		R0: "proof-release-1", R1: "proof-release-2", Fault: "proof-release-3",
	}
	policyHash := hashText("policy-596-1")
	r0Members := []types.WikiReleaseMemberSnapshot{{
		Kind: "page", LogicalSlug: "596-1", RevisionID: "revision-r0",
		MemberDigest: hashText("artifact-r0"), Title: "596-1", Content: "R0 body",
		Payload: json.RawMessage(`{"version":0}`),
	}}
	r1Members := []types.WikiReleaseMemberSnapshot{{
		Kind: "page", LogicalSlug: "596-1", RevisionID: "revision-r1",
		MemberDigest: hashText("artifact-r1"), Title: "596-1", Content: "R1 body",
		Payload: json.RawMessage(`{"version":1}`),
	}}
	faultMembers := []types.WikiReleaseMemberSnapshot{{
		Kind: "page", LogicalSlug: "596-1", RevisionID: "revision-fault",
		MemberDigest: hashText("artifact-fault"), Title: "596-1", Content: "fault body",
		Payload: json.RawMessage(`{"version":2}`),
	}}

	r0DecisionRaw, r0Decision := signedHumanDecision(
		t, humanKey, scope, principal.ID, "nonce-r0", hashText("candidate-r0"),
		hashText("batch-r0"), policyHash,
	)
	r0 := proofReleaseInput{
		Preparation: proofPreparation(
			t, "preparation-r0", scope, r0Decision, r0DecisionRaw, "", 0, r0Members,
		),
		HumanDecision: r0DecisionRaw,
	}
	r0.ActivationAuthorization = signedAuthorization(
		t, authorizationKey, "activate", r0.Preparation, "", 0, "nonce-r0",
	)

	r1DecisionRaw, r1Decision := signedHumanDecision(
		t, humanKey, scope, principal.ID, "nonce-r1", hashText("candidate-r1"),
		hashText("batch-r1"), policyHash,
	)
	r1 := proofReleaseInput{
		Preparation: proofPreparation(
			t, "preparation-r1", scope, r1Decision, r1DecisionRaw,
			releaseIDs.R0, 1, r1Members,
		),
		HumanDecision: r1DecisionRaw,
	}
	r1.ActivationAuthorization = signedAuthorization(
		t, authorizationKey, "activate", r1.Preparation, releaseIDs.R0, 1, "nonce-r1",
	)

	faultDecisionRaw, faultDecision := signedHumanDecision(
		t, humanKey, scope, principal.ID, "nonce-fault-activate", hashText("candidate-fault"),
		hashText("batch-fault"), policyHash,
	)
	faultActivation := proofReleaseInput{
		Preparation: proofPreparation(
			t, "preparation-fault", scope, faultDecision, faultDecisionRaw,
			releaseIDs.R0, 3, faultMembers,
		),
		HumanDecision: faultDecisionRaw,
	}
	faultActivation.ActivationAuthorization = signedAuthorization(
		t, authorizationKey, "activate", faultActivation.Preparation,
		releaseIDs.R0, 3, "nonce-fault-activate",
	)

	return proofRunInput{
		Hashes: proofInputHashes{
			CandidateHash: r1Decision.CandidateHash, HumanBatchHash: r1Decision.HumanBatchHash,
			PolicyHash: r1Decision.ReviewPolicyHash, ReleaseHash: hashText("golden-release-596-1"),
			ArtifactHash:     hashText("golden-artifact-596-1"),
			HumanReceiptHash: hashBytes(r1DecisionRaw),
		},
		Scope: scope, Principal: principal,
		ReleaseIDs: releaseIDs,
		HumanPublicKeys: map[string]string{
			"human-proof": base64.RawURLEncoding.EncodeToString(
				humanKey.Public().(ed25519.PublicKey),
			),
		},
		AuthorizationPublicKeys: map[string]string{
			"authorization-proof": base64.RawURLEncoding.EncodeToString(
				authorizationKey.Public().(ed25519.PublicKey),
			),
		},
		R0: r0, R1: r1,
		RevertAuthorizations: []json.RawMessage{
			signedAuthorization(
				t, authorizationKey, "revert", r0.Preparation,
				releaseIDs.R1, 2, "nonce-revert-a",
			),
			signedAuthorization(
				t, authorizationKey, "revert", r0.Preparation,
				releaseIDs.R1, 2, "nonce-revert-b",
			),
		},
		FaultActivation: faultActivation,
		FaultRevertAuthorization: signedAuthorization(
			t, authorizationKey, "revert", r1.Preparation,
			releaseIDs.R0, 3, "nonce-fault-revert",
		),
		PinnedLogicalSlug: "596-1",
	}
}

func signedHumanDecision(
	t *testing.T,
	privateKey ed25519.PrivateKey,
	scope types.WikiReleaseScope,
	principalID string,
	nonce string,
	candidateHash string,
	batchHash string,
	policyHash string,
) (json.RawMessage, *types.HumanBatchDecisionReceiptV1) {
	t.Helper()
	receipt := &types.HumanBatchDecisionReceiptV1{
		Version: "1", Decision: "approve", PrincipalID: principalID, WikiReleaseScope: scope,
		CandidateHash: candidateHash, HumanBatchHash: batchHash, ReviewPolicyHash: policyHash,
		IssuedAt: 900, ExpiresAt: 1_100, Nonce: nonce, SignerKeyID: "human-proof",
	}
	unsigned, err := service.CanonicalHumanBatchDecisionReceiptV1(receipt, false)
	if err != nil {
		t.Fatalf("canonical human decision: %v", err)
	}
	receipt.Signature = service.EncodeWikiReleaseSignature(ed25519.Sign(privateKey, unsigned))
	raw, err := service.CanonicalHumanBatchDecisionReceiptV1(receipt, true)
	if err != nil {
		t.Fatalf("signed human decision: %v", err)
	}
	return raw, receipt
}

func proofPreparation(
	t *testing.T,
	id string,
	scope types.WikiReleaseScope,
	decision *types.HumanBatchDecisionReceiptV1,
	rawDecision []byte,
	expectedReleaseID string,
	expectedEpoch uint64,
	members []types.WikiReleaseMemberSnapshot,
) types.WikiReleasePreparation {
	t.Helper()
	return types.WikiReleasePreparation{
		ID: id, WikiReleaseScope: scope,
		CandidateDigest: decision.CandidateHash, ManifestDigest: proofManifestDigest(t, members),
		ReadyReceiptDigest: decision.HumanBatchHash, ReviewDecisionDigest: hashBytes(rawDecision),
		ReviewPolicyID: decision.ReviewPolicyHash, ExpectedReleaseID: expectedReleaseID,
		ExpectedActivationEpoch: expectedEpoch, Members: members,
	}
}

func proofManifestDigest(t *testing.T, members []types.WikiReleaseMemberSnapshot) string {
	t.Helper()
	ordered := append([]types.WikiReleaseMemberSnapshot(nil), members...)
	sort.Slice(ordered, func(i, j int) bool { return ordered[i].LogicalSlug < ordered[j].LogicalSlug })
	raw, err := json.Marshal(map[string]any{"members": ordered})
	if err != nil {
		t.Fatalf("manifest fixture: %v", err)
	}
	return hashBytes(raw)
}

func signedAuthorization(
	t *testing.T,
	privateKey ed25519.PrivateKey,
	action string,
	preparation types.WikiReleasePreparation,
	expectedReleaseID string,
	expectedEpoch uint64,
	nonce string,
) json.RawMessage {
	t.Helper()
	authorization := &types.PublishAuthorizationV0{
		Version: "0", Action: action, PreparationID: preparation.ID,
		CandidateDigest: preparation.CandidateDigest, ManifestDigest: preparation.ManifestDigest,
		ReadyReceiptDigest:   preparation.ReadyReceiptDigest,
		ReviewDecisionDigest: preparation.ReviewDecisionDigest,
		ReviewPolicyID:       preparation.ReviewPolicyID, TenantID: preparation.TenantID,
		SpaceID: preparation.SpaceID, RawKBID: preparation.RawKBID, WikiKBID: preparation.WikiKBID,
		ExpectedReleaseID: expectedReleaseID, ExpectedActivationEpoch: expectedEpoch,
		ExpiresAt: 1_100, Nonce: nonce, SignerKeyID: "authorization-proof",
	}
	return resignAuthorization(t, privateKey, authorization)
}

func parseAuthorization(t *testing.T, raw json.RawMessage) *types.PublishAuthorizationV0 {
	t.Helper()
	authorization, err := service.ParsePublishAuthorizationV0(raw)
	if err != nil {
		t.Fatalf("parse authorization: %v", err)
	}
	return authorization
}

func resignAuthorization(
	t *testing.T,
	privateKey ed25519.PrivateKey,
	authorization *types.PublishAuthorizationV0,
) json.RawMessage {
	t.Helper()
	unsigned, err := service.CanonicalPublishAuthorizationV0(authorization, false)
	if err != nil {
		t.Fatalf("canonical authorization: %v", err)
	}
	authorization.Signature = service.EncodeWikiReleaseSignature(ed25519.Sign(privateKey, unsigned))
	raw, err := service.CanonicalPublishAuthorizationV0(authorization, true)
	if err != nil {
		t.Fatalf("signed authorization: %v", err)
	}
	return raw
}

func hashText(value string) string { return hashBytes([]byte(value)) }

func hashBytes(value []byte) string {
	digest := sha256.Sum256(value)
	return hex.EncodeToString(digest[:])
}

func equalInts(left, right []int) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
}
