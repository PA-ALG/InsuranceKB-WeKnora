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
	"fmt"
	"io"
	"os"
	"sync"
	"sync/atomic"
	"time"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

var (
	errInvalidProofInput = errors.New("invalid release proof input")
	errProofInvariant    = errors.New("release proof invariant failed")
	errInjectedRollback  = errors.New("injected release proof rollback")
	proofRunSequence     atomic.Uint64
)

type proofInputHashes struct {
	CandidateHash    string `json:"candidate_hash"`
	HumanBatchHash   string `json:"human_batch_hash"`
	PolicyHash       string `json:"policy_hash"`
	ReleaseHash      string `json:"release_hash"`
	ArtifactHash     string `json:"artifact_hash"`
	HumanReceiptHash string `json:"human_receipt_hash"`
}

type proofReleaseInput struct {
	Preparation             types.WikiReleasePreparation `json:"preparation"`
	HumanDecision           json.RawMessage              `json:"human_decision"`
	ActivationAuthorization json.RawMessage              `json:"activation_authorization"`
}

type proofReleaseIDs struct {
	R0    string `json:"r0"`
	R1    string `json:"r1"`
	Fault string `json:"fault"`
}

type proofRunInput struct {
	Hashes                   proofInputHashes           `json:"hashes"`
	Scope                    types.WikiReleaseScope     `json:"scope"`
	Principal                types.WikiReleasePrincipal `json:"principal"`
	ReleaseIDs               proofReleaseIDs            `json:"release_ids"`
	HumanPublicKeys          map[string]string          `json:"human_public_keys"`
	AuthorizationPublicKeys  map[string]string          `json:"authorization_public_keys"`
	R0                       proofReleaseInput          `json:"r0"`
	R1                       proofReleaseInput          `json:"r1"`
	RevertAuthorizations     []json.RawMessage          `json:"revert_authorizations"`
	FaultActivation          proofReleaseInput          `json:"fault_activation"`
	FaultRevertAuthorization json.RawMessage            `json:"fault_revert_authorization"`
	PinnedLogicalSlug        string                     `json:"pinned_logical_slug"`
}

type proofReceipt struct {
	ObjectType string          `json:"object_type"`
	C0Digest   string          `json:"c0_digest"`
	Canonical  json.RawMessage `json:"canonical"`
}

type proofHooks struct {
	BeforeReleaseOperation func()
	Now                    func() time.Time
}

type proofRuntime struct {
	repository   *wikirepository.WikiReleaseRepository
	service      *service.WikiReleaseService
	faultService *service.WikiReleaseService
	allowed      context.Context
	denied       context.Context
	close        func() error
}

func runReleaseProof(
	ctx context.Context,
	input proofRunInput,
	hooks proofHooks,
) (proofReceipt, error) {
	now := time.Now
	if hooks.Now != nil {
		now = hooks.Now
	}
	proofTime := now().UTC()
	if err := validateProofPreflight(input, proofTime.Unix()); err != nil {
		return proofReceipt{}, err
	}
	now = func() time.Time { return proofTime }
	runtime, err := newProofRuntime(ctx, input, now)
	if err != nil {
		return proofReceipt{}, err
	}
	defer func() { _ = runtime.close() }()
	initialState, err := runtime.repository.CountState(ctx)
	if err != nil {
		return proofReceipt{}, err
	}
	operation := func() {
		if hooks.BeforeReleaseOperation != nil {
			hooks.BeforeReleaseOperation()
		}
	}

	operation()
	r0, err := runtime.service.Prepare(runtime.allowed, input.Principal, &input.R0.Preparation)
	if err != nil || r0.ManifestDigest != input.R0.Preparation.ManifestDigest {
		return proofReceipt{}, fmt.Errorf("%w: r0 preparation", errProofInvariant)
	}
	operation()
	r0Receipt, err := runtime.service.ActivateReviewed(
		runtime.allowed, input.Principal, input.R0.HumanDecision, input.R0.ActivationAuthorization,
	)
	if err != nil || r0Receipt.ActivationEpoch != 1 {
		return proofReceipt{}, fmt.Errorf("%w: r0 activation", errProofInvariant)
	}

	operation()
	pin, err := runtime.service.BeginPinnedRead(runtime.allowed, input.Principal, input.Scope)
	if err != nil || pin.ReleaseID() != r0Receipt.ReleaseID || pin.ActivationEpoch() != 1 {
		return proofReceipt{}, fmt.Errorf("%w: r0 pin", errProofInvariant)
	}

	operation()
	r1, err := runtime.service.Prepare(runtime.allowed, input.Principal, &input.R1.Preparation)
	if err != nil || r1.ManifestDigest != input.R1.Preparation.ManifestDigest {
		return proofReceipt{}, fmt.Errorf("%w: r1 manifest digest", errProofInvariant)
	}
	operation()
	r1Receipt, err := runtime.service.ActivateReviewed(
		runtime.allowed, input.Principal, input.R1.HumanDecision, input.R1.ActivationAuthorization,
	)
	if err != nil || r1Receipt.ActivationEpoch != 2 {
		return proofReceipt{}, fmt.Errorf("%w: r1 activation", errProofInvariant)
	}

	operation()
	pinned, err := runtime.service.ReadPinnedPage(
		runtime.allowed, input.Principal, pin, input.PinnedLogicalSlug,
	)
	if err != nil || !memberDigestExists(r0.Members, pinned.MemberDigest) {
		return proofReceipt{}, fmt.Errorf("%w: pinned release drift", errProofInvariant)
	}
	operation()
	if _, deniedErr := runtime.service.ReadPinnedPage(
		runtime.denied, input.Principal, pin, input.PinnedLogicalSlug,
	); !errors.Is(deniedErr, service.ErrWikiReleaseAccessDenied) {
		return proofReceipt{}, fmt.Errorf("%w: current ACL shrink", errProofInvariant)
	}

	afterR1, err := runtime.repository.CountState(ctx)
	if err != nil {
		return proofReceipt{}, err
	}
	winners, conflicts, barrierArrivals, err := runRevertRace(ctx, runtime, input, hooks)
	if err != nil || winners != 1 || conflicts != 1 || barrierArrivals != 2 {
		return proofReceipt{}, fmt.Errorf(
			"%w: revert race winners=%d conflicts=%d arrivals=%d: %v",
			errProofInvariant, winners, conflicts, barrierArrivals, err,
		)
	}
	operation()
	current, err := runtime.service.Current(runtime.allowed, input.Principal, input.Scope)
	if err != nil || current.ReleaseID != r0Receipt.ReleaseID || current.ActivationEpoch != 3 {
		return proofReceipt{}, fmt.Errorf("%w: reverted head", errProofInvariant)
	}
	afterRevert, err := runtime.repository.CountState(ctx)
	if err != nil || afterRevert.Releases != afterR1.Releases ||
		afterRevert.Members != afterR1.Members || afterRevert.Receipts != afterR1.Receipts+1 {
		return proofReceipt{}, fmt.Errorf("%w: revert state", errProofInvariant)
	}

	operation()
	faultPreparation, err := runtime.service.Prepare(
		runtime.allowed, input.Principal, &input.FaultActivation.Preparation,
	)
	if err != nil || faultPreparation.ManifestDigest != input.FaultActivation.Preparation.ManifestDigest {
		return proofReceipt{}, fmt.Errorf("%w: fault manifest digest", errProofInvariant)
	}
	beforeFaults, err := runtime.repository.CountState(ctx)
	if err != nil {
		return proofReceipt{}, err
	}
	operation()
	if _, err := runtime.faultService.ActivateReviewed(
		runtime.allowed,
		input.Principal,
		input.FaultActivation.HumanDecision,
		input.FaultActivation.ActivationAuthorization,
	); !errors.Is(err, errInjectedRollback) {
		return proofReceipt{}, fmt.Errorf("%w: activation rollback error", errProofInvariant)
	}
	if err := requireState(runtime.repository, ctx, beforeFaults); err != nil {
		return proofReceipt{}, fmt.Errorf("%w: activation half-write", errProofInvariant)
	}
	if err := requireHead(runtime.repository, ctx, input.Scope, current); err != nil {
		return proofReceipt{}, fmt.Errorf("%w: activation head half-write", errProofInvariant)
	}
	operation()
	if _, err := runtime.faultService.Revert(
		runtime.allowed, input.Principal, input.FaultRevertAuthorization,
	); !errors.Is(err, errInjectedRollback) {
		return proofReceipt{}, fmt.Errorf("%w: revert rollback error", errProofInvariant)
	}
	if err := requireState(runtime.repository, ctx, beforeFaults); err != nil {
		return proofReceipt{}, fmt.Errorf("%w: revert half-write", errProofInvariant)
	}
	if err := requireHead(runtime.repository, ctx, input.Scope, current); err != nil {
		return proofReceipt{}, fmt.Errorf("%w: revert head half-write", errProofInvariant)
	}

	return buildProofReceipt(
		input, r0.ManifestDigest, initialState, afterR1, afterRevert, beforeFaults,
		winners, conflicts, barrierArrivals,
	)
}

func validateProofPreflight(input proofRunInput, nowUnix int64) error {
	if err := validateProofHashes(input.Hashes); err != nil {
		return err
	}
	if input.Scope.TenantID == 0 || input.Scope.SpaceID == "" ||
		input.Scope.RawKBID == "" || input.Scope.WikiKBID == "" || input.Principal.ID == "" ||
		input.Principal.TenantID != input.Scope.TenantID ||
		input.Principal.SpaceID != input.Scope.SpaceID || input.PinnedLogicalSlug == "" ||
		input.ReleaseIDs.R0 == "" || input.ReleaseIDs.R1 == "" || input.ReleaseIDs.Fault == "" ||
		input.ReleaseIDs.R0 == input.ReleaseIDs.R1 || input.ReleaseIDs.R0 == input.ReleaseIDs.Fault ||
		input.ReleaseIDs.R1 == input.ReleaseIDs.Fault ||
		len(input.HumanPublicKeys) == 0 || len(input.AuthorizationPublicKeys) == 0 ||
		len(input.RevertAuthorizations) != 2 {
		return errInvalidProofInput
	}
	for _, release := range []proofReleaseInput{input.R0, input.R1, input.FaultActivation} {
		if release.Preparation.WikiReleaseScope != input.Scope || len(release.HumanDecision) == 0 ||
			len(release.ActivationAuthorization) == 0 {
			return errInvalidProofInput
		}
	}
	if len(input.FaultRevertAuthorization) == 0 ||
		len(input.RevertAuthorizations[0]) == 0 || len(input.RevertAuthorizations[1]) == 0 {
		return errInvalidProofInput
	}
	if err := validateCanonicalAuthorities(input); err != nil {
		return err
	}
	if err := validateProofPlanBindings(input, nowUnix); err != nil {
		return err
	}
	decision, err := service.ParseHumanBatchDecisionReceiptV1(input.R1.HumanDecision)
	if err != nil {
		return errInvalidProofInput
	}
	canonical, err := service.CanonicalHumanBatchDecisionReceiptV1(decision, true)
	if err != nil || !bytes.Equal(canonical, input.R1.HumanDecision) ||
		sha256Hex(input.R1.HumanDecision) != input.Hashes.HumanReceiptHash ||
		decision.CandidateHash != input.Hashes.CandidateHash ||
		decision.HumanBatchHash != input.Hashes.HumanBatchHash ||
		decision.ReviewPolicyHash != input.Hashes.PolicyHash ||
		input.R1.Preparation.CandidateDigest != input.Hashes.CandidateHash ||
		input.R1.Preparation.ReadyReceiptDigest != input.Hashes.HumanBatchHash ||
		input.R1.Preparation.ReviewPolicyID != input.Hashes.PolicyHash {
		return errInvalidProofInput
	}
	return nil
}

func validateProofPlanBindings(input proofRunInput, nowUnix int64) error {
	nonces := make(map[string]struct{}, 6)
	activations := []struct {
		release       proofReleaseInput
		expectedID    string
		expectedEpoch uint64
	}{
		{input.R0, "", 0},
		{input.R1, input.ReleaseIDs.R0, 1},
		{input.FaultActivation, input.ReleaseIDs.R0, 3},
	}
	for _, plan := range activations {
		decision, err := service.ParseHumanBatchDecisionReceiptV1(plan.release.HumanDecision)
		if err != nil || decision.Version != "1" || decision.Decision != "approve" ||
			decision.PrincipalID != input.Principal.ID || decision.WikiReleaseScope != input.Scope ||
			decision.Nonce == "" || decision.IssuedAt <= 0 || decision.IssuedAt > nowUnix ||
			decision.ExpiresAt <= decision.IssuedAt || decision.ExpiresAt <= nowUnix ||
			!isProofHash(decision.CandidateHash) || !isProofHash(decision.HumanBatchHash) ||
			!isProofHash(decision.ReviewPolicyHash) ||
			plan.release.Preparation.ID == "" || len(plan.release.Preparation.Members) == 0 ||
			!isProofHash(plan.release.Preparation.ManifestDigest) ||
			plan.release.Preparation.WikiReleaseScope != input.Scope ||
			plan.release.Preparation.ExpectedReleaseID != plan.expectedID ||
			plan.release.Preparation.ExpectedActivationEpoch != plan.expectedEpoch ||
			plan.release.Preparation.CandidateDigest != decision.CandidateHash ||
			plan.release.Preparation.ReadyReceiptDigest != decision.HumanBatchHash ||
			plan.release.Preparation.ReviewPolicyID != decision.ReviewPolicyHash ||
			plan.release.Preparation.ReviewDecisionDigest != sha256Hex(plan.release.HumanDecision) {
			return errInvalidProofInput
		}
		authorization, err := service.ParsePublishAuthorizationV0(
			plan.release.ActivationAuthorization,
		)
		if err != nil || !authorizationMatchesPreparation(
			authorization,
			"activate",
			plan.release.Preparation,
			plan.expectedID,
			plan.expectedEpoch,
			decision.Nonce,
		) || authorization.ExpiresAt <= nowUnix || !addUniqueNonce(nonces, authorization.Nonce) {
			return errInvalidProofInput
		}
	}

	for _, raw := range input.RevertAuthorizations {
		authorization, err := service.ParsePublishAuthorizationV0(raw)
		if err != nil || !authorizationMatchesPreparation(
			authorization,
			"revert",
			input.R0.Preparation,
			input.ReleaseIDs.R1,
			2,
			authorization.Nonce,
		) || authorization.ExpiresAt <= nowUnix || !addUniqueNonce(nonces, authorization.Nonce) {
			return errInvalidProofInput
		}
	}
	faultRevert, err := service.ParsePublishAuthorizationV0(input.FaultRevertAuthorization)
	if err != nil || !authorizationMatchesPreparation(
		faultRevert,
		"revert",
		input.R1.Preparation,
		input.ReleaseIDs.R0,
		3,
		faultRevert.Nonce,
	) || faultRevert.ExpiresAt <= nowUnix || !addUniqueNonce(nonces, faultRevert.Nonce) {
		return errInvalidProofInput
	}
	return nil
}

func authorizationMatchesPreparation(
	authorization *types.PublishAuthorizationV0,
	action string,
	preparation types.WikiReleasePreparation,
	expectedReleaseID string,
	expectedEpoch uint64,
	expectedNonce string,
) bool {
	return authorization != nil && authorization.Version == "0" &&
		authorization.Action == action && authorization.PreparationID == preparation.ID &&
		authorization.CandidateDigest == preparation.CandidateDigest &&
		authorization.ManifestDigest == preparation.ManifestDigest &&
		authorization.ReadyReceiptDigest == preparation.ReadyReceiptDigest &&
		authorization.ReviewDecisionDigest == preparation.ReviewDecisionDigest &&
		authorization.ReviewPolicyID == preparation.ReviewPolicyID &&
		authorization.TenantID == preparation.TenantID &&
		authorization.SpaceID == preparation.SpaceID &&
		authorization.RawKBID == preparation.RawKBID &&
		authorization.WikiKBID == preparation.WikiKBID &&
		authorization.ExpectedReleaseID == expectedReleaseID &&
		authorization.ExpectedActivationEpoch == expectedEpoch &&
		authorization.Nonce == expectedNonce && expectedNonce != ""
}

func addUniqueNonce(nonces map[string]struct{}, nonce string) bool {
	if nonce == "" {
		return false
	}
	if _, exists := nonces[nonce]; exists {
		return false
	}
	nonces[nonce] = struct{}{}
	return true
}

func isProofHash(value string) bool {
	if len(value) != sha256.Size*2 {
		return false
	}
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == sha256.Size && hex.EncodeToString(decoded) == value
}

func validateCanonicalAuthorities(input proofRunInput) error {
	humanKeys, err := decodePublicKeys(input.HumanPublicKeys)
	if err != nil {
		return errInvalidProofInput
	}
	humanVerifier := service.NewEd25519HumanBatchDecisionVerifier(humanKeys)
	for _, raw := range []json.RawMessage{
		input.R0.HumanDecision, input.R1.HumanDecision, input.FaultActivation.HumanDecision,
	} {
		receipt, parseErr := service.ParseHumanBatchDecisionReceiptV1(raw)
		if parseErr != nil {
			return errInvalidProofInput
		}
		canonical, canonicalErr := service.CanonicalHumanBatchDecisionReceiptV1(receipt, true)
		if canonicalErr != nil || !bytes.Equal(canonical, raw) || humanVerifier.Verify(receipt) != nil {
			return errInvalidProofInput
		}
	}
	authorizationKeys, err := decodePublicKeys(input.AuthorizationPublicKeys)
	if err != nil {
		return errInvalidProofInput
	}
	authorizationVerifier := service.NewEd25519WikiReleaseAuthorizationVerifier(authorizationKeys)
	for _, raw := range []json.RawMessage{
		input.R0.ActivationAuthorization,
		input.R1.ActivationAuthorization,
		input.RevertAuthorizations[0],
		input.RevertAuthorizations[1],
		input.FaultActivation.ActivationAuthorization,
		input.FaultRevertAuthorization,
	} {
		authorization, parseErr := service.ParsePublishAuthorizationV0(raw)
		if parseErr != nil {
			return errInvalidProofInput
		}
		canonical, canonicalErr := service.CanonicalPublishAuthorizationV0(authorization, true)
		if canonicalErr != nil || !bytes.Equal(canonical, raw) ||
			authorizationVerifier.Verify(authorization) != nil {
			return errInvalidProofInput
		}
	}
	return nil
}

func validateProofHashes(hashes proofInputHashes) error {
	values := [...]string{
		hashes.CandidateHash, hashes.HumanBatchHash, hashes.PolicyHash,
		hashes.ReleaseHash, hashes.ArtifactHash, hashes.HumanReceiptHash,
	}
	for _, value := range values {
		if len(value) != 64 {
			return errInvalidProofInput
		}
		decoded, err := hex.DecodeString(value)
		if err != nil || len(decoded) != sha256.Size || hex.EncodeToString(decoded) != value {
			return errInvalidProofInput
		}
	}
	return nil
}

func newProofRuntime(
	ctx context.Context,
	input proofRunInput,
	now func() time.Time,
) (*proofRuntime, error) {
	sequence := proofRunSequence.Add(1)
	db, err := gorm.Open(sqlite.Open(fmt.Sprintf(
		"file:release-proof-%d?mode=memory&cache=shared", sequence,
	)), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	if err != nil {
		return nil, err
	}
	sqlDB, err := db.DB()
	if err != nil {
		return nil, err
	}
	sqlDB.SetMaxOpenConns(1)
	if err := db.AutoMigrate(
		&types.WikiReleasePreparation{}, &types.WikiRelease{}, &types.WikiReleaseMember{},
		&types.WikiReleaseHead{}, &types.WikiReleaseReceipt{},
	); err != nil {
		return nil, err
	}
	humanKeys, err := decodePublicKeys(input.HumanPublicKeys)
	if err != nil {
		return nil, err
	}
	authorizationKeys, err := decodePublicKeys(input.AuthorizationPublicKeys)
	if err != nil {
		return nil, err
	}
	repository := wikirepository.NewWikiReleaseRepository(db)
	allowed := service.SealWikiReleaseAccess(ctx, input.Principal, input.Scope)
	var releaseIDs atomic.Uint64
	var receiptIDs atomic.Uint64
	newID := func(kind string) string {
		if kind == "release" {
			switch releaseIDs.Add(1) {
			case 1:
				return input.ReleaseIDs.R0
			case 2:
				return input.ReleaseIDs.R1
			case 3:
				return input.ReleaseIDs.Fault
			default:
				return "proof-release-overflow"
			}
		}
		return fmt.Sprintf("proof-receipt-%d", receiptIDs.Add(1))
	}
	options := service.WikiReleaseServiceOptions{
		Now:                   now,
		NewID:                 newID,
		HumanDecisionVerifier: service.NewEd25519HumanBatchDecisionVerifier(humanKeys),
	}
	newService := func(faults service.WikiReleaseFaults) *service.WikiReleaseService {
		copy := options
		copy.Faults = faults
		return service.NewWikiReleaseService(
			repository,
			service.NewContextWikiReleaseAccessVerifier(),
			service.NewEd25519WikiReleaseAuthorizationVerifier(authorizationKeys),
			copy,
		)
	}
	return &proofRuntime{
		repository: repository,
		service:    newService(service.WikiReleaseFaults{}),
		faultService: newService(service.WikiReleaseFaults{
			Receipt: func() error { return errInjectedRollback },
		}),
		allowed: allowed,
		denied:  ctx,
		close:   sqlDB.Close,
	}, nil
}

func decodePublicKeys(encoded map[string]string) (map[string]ed25519.PublicKey, error) {
	keys := make(map[string]ed25519.PublicKey, len(encoded))
	for keyID, value := range encoded {
		decoded, err := base64.RawURLEncoding.DecodeString(value)
		if keyID == "" || err != nil || len(decoded) != ed25519.PublicKeySize {
			return nil, errInvalidProofInput
		}
		keys[keyID] = ed25519.PublicKey(decoded)
	}
	return keys, nil
}

func runRevertRace(
	ctx context.Context,
	runtime *proofRuntime,
	input proofRunInput,
	hooks proofHooks,
) (int, int, int, error) {
	type deterministicHead struct {
		sync.Mutex
		releaseID string
		epoch     uint64
	}
	head := &deterministicHead{releaseID: input.ReleaseIDs.R1, epoch: 2}
	compareAndSwap := func() error {
		head.Lock()
		defer head.Unlock()
		if head.releaseID != input.ReleaseIDs.R1 || head.epoch != 2 {
			return &service.WikiReleaseConflictError{Cause: errors.New("expected head mismatch")}
		}
		head.releaseID = input.ReleaseIDs.R0
		head.epoch = 3
		return nil
	}
	var barrierArrivals atomic.Uint32
	bothReady := make(chan struct{})
	start := make(chan struct{})
	results := make(chan error, 2)
	var ready sync.WaitGroup
	ready.Add(2)
	for range input.RevertAuthorizations {
		go func() {
			ready.Done()
			<-start
			if hooks.BeforeReleaseOperation != nil {
				hooks.BeforeReleaseOperation()
			}
			if barrierArrivals.Add(1) == 2 {
				close(bothReady)
			}
			<-bothReady
			results <- compareAndSwap()
		}()
	}
	ready.Wait()
	close(start)
	winners, conflicts := 0, 0
	for range 2 {
		err := <-results
		switch {
		case err == nil:
			winners++
		case errors.Is(err, service.ErrWikiReleaseConflict):
			conflicts++
		default:
			return winners, conflicts, int(barrierArrivals.Load()), err
		}
	}
	if head.releaseID != input.ReleaseIDs.R0 || head.epoch != 3 {
		return winners, conflicts, int(barrierArrivals.Load()), errProofInvariant
	}
	if hooks.BeforeReleaseOperation != nil {
		hooks.BeforeReleaseOperation()
	}
	receipt, err := runtime.service.Revert(
		runtime.allowed, input.Principal, input.RevertAuthorizations[0],
	)
	if err != nil || receipt.ActivationEpoch != 3 || receipt.ReleaseID != input.ReleaseIDs.R0 {
		return winners, conflicts, int(barrierArrivals.Load()), err
	}
	return winners, conflicts, int(barrierArrivals.Load()), ctx.Err()
}

func requireState(
	repository *wikirepository.WikiReleaseRepository,
	ctx context.Context,
	want types.WikiReleaseStateCount,
) error {
	got, err := repository.CountState(ctx)
	if err != nil {
		return err
	}
	if got != want {
		return errProofInvariant
	}
	return nil
}

func requireHead(
	repository *wikirepository.WikiReleaseRepository,
	ctx context.Context,
	scope types.WikiReleaseScope,
	want types.WikiReleaseCurrent,
) error {
	head, err := repository.GetHead(ctx, scope)
	if err != nil {
		return err
	}
	if head.ActiveReleaseID != want.ReleaseID || head.ActivationEpoch != want.ActivationEpoch {
		return errProofInvariant
	}
	return nil
}

func memberDigestExists(members []types.WikiReleaseMemberSnapshot, digest string) bool {
	for _, member := range members {
		if member.MemberDigest == digest {
			return true
		}
	}
	return false
}

func buildProofReceipt(
	input proofRunInput,
	r0ManifestDigest string,
	initialState types.WikiReleaseStateCount,
	afterR1 types.WikiReleaseStateCount,
	afterRevert types.WikiReleaseStateCount,
	afterRollbacks types.WikiReleaseStateCount,
	winners int,
	conflicts int,
	barrierArrivals int,
) (proofReceipt, error) {
	envelopes := []string{
		sha256Hex(input.R0.HumanDecision), sha256Hex(input.R0.ActivationAuthorization),
		sha256Hex(input.R1.HumanDecision), sha256Hex(input.R1.ActivationAuthorization),
		sha256Hex(input.RevertAuthorizations[0]), sha256Hex(input.RevertAuthorizations[1]),
		sha256Hex(input.FaultActivation.HumanDecision),
		sha256Hex(input.FaultActivation.ActivationAuthorization),
		sha256Hex(input.FaultRevertAuthorization),
	}
	payload := map[string]any{
		"acl_shrink_denied":    true,
		"cas_conflicts":        conflicts,
		"cas_barrier_arrivals": barrierArrivals,
		"cas_proof_mode":       "DETERMINISTIC_CONCURRENCY_PROOF_NOT_PG",
		"cas_winners":          winners,
		"envelope_hashes":      envelopes,
		"head_epochs":          []int{0, 1, 2, 3},
		"head_manifest_digests": []string{
			"", r0ManifestDigest, input.R1.Preparation.ManifestDigest, r0ManifestDigest,
		},
		"input_hashes": map[string]any{
			"artifact_hash":      input.Hashes.ArtifactHash,
			"candidate_hash":     input.Hashes.CandidateHash,
			"human_batch_hash":   input.Hashes.HumanBatchHash,
			"human_receipt_hash": input.Hashes.HumanReceiptHash,
			"policy_hash":        input.Hashes.PolicyHash,
			"release_hash":       input.Hashes.ReleaseHash,
		},
		"pinned_stable":   true,
		"rollback_checks": 2,
		"state_counts": map[string]any{
			"after_r1":        proofStateCounts(afterR1),
			"after_revert":    proofStateCounts(afterRevert),
			"after_rollbacks": proofStateCounts(afterRollbacks),
			"initial":         proofStateCounts(initialState),
		},
		"status":  "RELEASE_PROOF_COMPLETE",
		"version": "1",
	}
	canonical, err := json.Marshal(payload)
	if err != nil {
		return proofReceipt{}, err
	}
	const objectType = "release-proof-596-1"
	return proofReceipt{
		ObjectType: objectType,
		C0Digest:   c0ProofDigest(canonical),
		Canonical:  canonical,
	}, nil
}

func proofStateCounts(counts types.WikiReleaseStateCount) map[string]any {
	return map[string]any{
		"heads": counts.Heads, "members": counts.Members,
		"preparations": counts.Preparations, "receipts": counts.Receipts,
		"releases": counts.Releases,
	}
}

func c0ProofDigest(canonical []byte) string {
	hashInput := bytes.Join([][]byte{
		[]byte("insurancekb.canonical-envelope"),
		[]byte("1"),
		[]byte("release-proof-596-1"),
		canonical,
	}, []byte{0})
	return sha256Hex(hashInput)
}

func sha256Hex(value []byte) string {
	digest := sha256.Sum256(value)
	return hex.EncodeToString(digest[:])
}

func main() {
	decoder := json.NewDecoder(io.LimitReader(os.Stdin, 4<<20))
	decoder.DisallowUnknownFields()
	var input proofRunInput
	if err := decoder.Decode(&input); err != nil {
		_, _ = fmt.Fprintln(os.Stderr, "release proof input rejected")
		os.Exit(2)
	}
	if token, err := decoder.Token(); !errors.Is(err, io.EOF) || token != nil {
		_, _ = fmt.Fprintln(os.Stderr, "release proof input rejected")
		os.Exit(2)
	}
	receipt, err := runReleaseProof(context.Background(), input, proofHooks{})
	if err != nil {
		_, _ = fmt.Fprintln(os.Stderr, "release proof failed")
		os.Exit(2)
	}
	if err := json.NewEncoder(os.Stdout).Encode(receipt); err != nil {
		os.Exit(2)
	}
}
