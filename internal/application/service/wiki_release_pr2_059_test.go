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
	"fmt"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

// These test-only adapters keep the pre-059 compatibility suite exercising
// the same private atomic/read helpers without exporting production bypasses.
func (s *WikiReleaseService) Activate(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	rawAuthorization []byte,
) (*types.WikiReleaseReceipt, error) {
	return s.activate(ctx, principal, rawAuthorization)
}

func (s *WikiReleaseService) PinnedPage(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	releaseID string,
	logicalSlug string,
) (*types.WikiReleaseMemberSnapshot, error) {
	return s.pinnedPage(ctx, principal, scope, releaseID, logicalSlug)
}

func (s *WikiReleaseService) PinnedPayload(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	releaseID string,
	logicalSlug string,
) (json.RawMessage, error) {
	return s.pinnedPayload(ctx, principal, scope, releaseID, logicalSlug)
}

func (s *WikiReleaseService) MinimalSearch(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	releaseID string,
	query string,
) ([]types.WikiReleaseMemberSnapshot, error) {
	return s.minimalSearch(ctx, principal, scope, releaseID, query)
}

type releasePR2Vector struct {
	CandidateHash           string          `json:"candidate_hash"`
	HumanBatchHash          string          `json:"human_batch_hash"`
	ReviewPolicyHash        string          `json:"review_policy_hash"`
	CanonicalUnsignedSHA256 string          `json:"canonical_unsigned_sha256"`
	CanonicalSignedSHA256   string          `json:"canonical_signed_sha256"`
	PublicKey               string          `json:"public_key"`
	Receipt                 json.RawMessage `json:"receipt"`
}

var serializedFixtureSequence059 atomic.Uint64

func TestWikiReleasePR2HumanBatchVectorAndWholeBatchGate(t *testing.T) {
	vectorRaw, err := os.ReadFile("testdata/059_candidate_human_batch_approval_vector.json")
	require.NoError(t, err)
	var vector releasePR2Vector
	require.NoError(t, json.Unmarshal(vectorRaw, &vector))
	receipt, err := ParseHumanBatchDecisionReceiptV1(vector.Receipt)
	require.NoError(t, err)
	require.Equal(t, vector.CandidateHash, receipt.CandidateHash)
	require.Equal(t, vector.HumanBatchHash, receipt.HumanBatchHash)
	require.Equal(t, vector.ReviewPolicyHash, receipt.ReviewPolicyHash)
	unsigned, err := CanonicalHumanBatchDecisionReceiptV1(receipt, false)
	require.NoError(t, err)
	signed, err := CanonicalHumanBatchDecisionReceiptV1(receipt, true)
	require.NoError(t, err)
	require.Equal(t, vector.CanonicalUnsignedSHA256, sha256Hex059(unsigned))
	require.Equal(t, vector.CanonicalSignedSHA256, sha256Hex059(signed))
	publicKey, err := base64.RawURLEncoding.DecodeString(vector.PublicKey)
	require.NoError(t, err)
	verifier := NewEd25519HumanBatchDecisionVerifier(map[string]ed25519.PublicKey{
		"human-key-1": publicKey,
	})
	require.NoError(t, verifier.Verify(receipt))

	fixture := newWikiReleaseFixture(t, WikiReleaseFaults{})
	humanKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x59}, ed25519.SeedSize))
	configureHumanDecisionVerifier059(fixture, humanKey)
	decisionRaw, decision := signHumanDecision059(
		t, humanKey, fixture, "approve", "nonce-reviewed", hash059("candidate"),
	)
	preparation := prepareReviewed059(t, fixture, decision, decisionRaw, "preparation-reviewed", "", 0)
	authorization := signWikiReleaseAuthorization(
		t, fixture.privateKey, preparation, decision.Nonce, decision.ExpiresAt,
	)
	activation, err := fixture.service.ActivateReviewed(
		fixture.ctx, fixture.principal1, decisionRaw, authorization,
	)
	require.NoError(t, err)
	*fixture.nowUnix = 3_000
	retry, err := fixture.service.ActivateReviewed(
		fixture.ctx, fixture.principal1, decisionRaw, authorization,
	)
	require.NoError(t, err)
	require.Equal(t, activation, retry)
	changedAuthorization := signWikiReleaseAuthorization(
		t, fixture.privateKey, preparation, decision.Nonce, 4_000,
	)
	_, err = fixture.service.ActivateReviewed(
		fixture.ctx, fixture.principal1, decisionRaw, changedAuthorization,
	)
	require.ErrorIs(t, err, ErrWikiReleaseConflict)
	*fixture.nowUnix = 1_000

	before, err := fixture.repo.CountState(fixture.ctx)
	require.NoError(t, err)
	rejectRaw, reject := signHumanDecision059(
		t, humanKey, fixture, "reject", "nonce-reject", hash059("rejected-candidate"),
	)
	rejectPreparation := prepareReviewed059(
		t, fixture, reject, rejectRaw, "preparation-reject", activation.ReleaseID, activation.ActivationEpoch,
	)
	_, err = fixture.service.ActivateReviewed(
		fixture.ctx,
		fixture.principal1,
		rejectRaw,
		signWikiReleaseAuthorization(t, fixture.privateKey, rejectPreparation, reject.Nonce, reject.ExpiresAt),
	)
	require.ErrorIs(t, err, ErrWikiReleaseInvalidAuthorization)
	after, err := fixture.repo.CountState(fixture.ctx)
	require.NoError(t, err)
	require.Equal(t, before.Releases, after.Releases)
	require.Equal(t, before.Heads, after.Heads)
	require.Equal(t, before.Receipts, after.Receipts)
}

func TestWikiReleasePR2HumanGateRejectsDriftBeforeActivation(t *testing.T) {
	for _, testCase := range []struct {
		name   string
		mutate func(*testing.T, *wikiReleaseFixture, ed25519.PrivateKey, []byte, []byte) ([]byte, []byte, types.WikiReleasePrincipal)
	}{
		{
			name: "principal mismatch",
			mutate: func(_ *testing.T, fixture *wikiReleaseFixture, _ ed25519.PrivateKey, decision, authorization []byte) ([]byte, []byte, types.WikiReleasePrincipal) {
				return decision, authorization, fixture.principal2
			},
		},
		{
			name: "current ACL removed",
			mutate: func(_ *testing.T, fixture *wikiReleaseFixture, _ ed25519.PrivateKey, decision, authorization []byte) ([]byte, []byte, types.WikiReleasePrincipal) {
				delete(fixture.access.allowed, fixture.principal1.ID)
				return decision, authorization, fixture.principal1
			},
		},
		{
			name: "expired decision",
			mutate: func(_ *testing.T, fixture *wikiReleaseFixture, _ ed25519.PrivateKey, decision, authorization []byte) ([]byte, []byte, types.WikiReleasePrincipal) {
				*fixture.nowUnix = 3_000
				return decision, authorization, fixture.principal1
			},
		},
		{
			name: "signature drift",
			mutate: func(t *testing.T, fixture *wikiReleaseFixture, _ ed25519.PrivateKey, decision, authorization []byte) ([]byte, []byte, types.WikiReleasePrincipal) {
				var fields map[string]any
				require.NoError(t, json.Unmarshal(decision, &fields))
				fields["signature"] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
				drifted, err := json.Marshal(fields)
				require.NoError(t, err)
				return drifted, authorization, fixture.principal1
			},
		},
		{
			name: "nonce drift",
			mutate: func(t *testing.T, fixture *wikiReleaseFixture, _ ed25519.PrivateKey, decision, authorization []byte) ([]byte, []byte, types.WikiReleasePrincipal) {
				parsed, err := ParsePublishAuthorizationV0(authorization)
				require.NoError(t, err)
				parsed.Nonce = "different-nonce"
				unsigned, err := CanonicalPublishAuthorizationV0(parsed, false)
				require.NoError(t, err)
				parsed.Signature = EncodeWikiReleaseSignature(ed25519.Sign(fixture.privateKey, unsigned))
				drifted, err := CanonicalPublishAuthorizationV0(parsed, true)
				require.NoError(t, err)
				return decision, drifted, fixture.principal1
			},
		},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			fixture := newWikiReleaseFixture(t, WikiReleaseFaults{})
			humanKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x60}, ed25519.SeedSize))
			configureHumanDecisionVerifier059(fixture, humanKey)
			decisionRaw, decision := signHumanDecision059(
				t, humanKey, fixture, "approve", "nonce-gate", hash059("candidate-gate"),
			)
			preparation := prepareReviewed059(t, fixture, decision, decisionRaw, "preparation-gate", "", 0)
			authorization := signWikiReleaseAuthorization(
				t, fixture.privateKey, preparation, decision.Nonce, decision.ExpiresAt,
			)
			decisionRaw, authorization, principal := testCase.mutate(
				t, fixture, humanKey, decisionRaw, authorization,
			)
			_, err := fixture.service.ActivateReviewed(
				fixture.ctx, principal, decisionRaw, authorization,
			)
			require.Error(t, err)
			state, countErr := fixture.repo.CountState(fixture.ctx)
			require.NoError(t, countErr)
			require.Equal(t, int64(0), state.Releases)
			require.Equal(t, int64(0), state.Heads)
			require.Equal(t, int64(0), state.Receipts)
		})
	}
}

func TestWikiReleasePR2PinnedReadPinsOnceAndRechecksACL(t *testing.T) {
	fixture := newWikiReleaseFixture(t, WikiReleaseFaults{})
	r0 := fixture.prepare(t, "preparation-r0", "candidate-r0", "", 0, r0WikiReleaseMembers())
	r0Receipt, err := fixture.activate(t, r0, "nonce-r0")
	require.NoError(t, err)
	pin, err := fixture.service.BeginPinnedRead(fixture.ctx, fixture.principal1, fixture.scope)
	require.NoError(t, err)
	require.Equal(t, r0Receipt.ReleaseID, pin.ReleaseID())

	r1 := fixture.prepare(
		t, "preparation-r1", "candidate-r1", r0Receipt.ReleaseID, r0Receipt.ActivationEpoch, r1WikiReleaseMembers(),
	)
	_, err = fixture.activate(t, r1, "nonce-r1")
	require.NoError(t, err)
	page, err := fixture.service.ReadPinnedPage(fixture.ctx, fixture.principal1, pin, "a")
	require.NoError(t, err)
	require.Equal(t, "A0", page.Content)
	payload, err := fixture.service.ReadPinnedPayload(fixture.ctx, fixture.principal1, pin, "a")
	require.NoError(t, err)
	require.JSONEq(t, `{"slug":"a","v":0}`, string(payload))
	search, err := fixture.service.SearchPinned(fixture.ctx, fixture.principal1, pin, "")
	require.NoError(t, err)
	require.Equal(t, []string{"a", "b", "c"}, releaseSlugs(search))

	delete(fixture.access.allowed, fixture.principal1.ID)
	_, pageErr := fixture.service.ReadPinnedPage(fixture.ctx, fixture.principal1, pin, "a")
	_, payloadErr := fixture.service.ReadPinnedPayload(fixture.ctx, fixture.principal1, pin, "a")
	_, searchErr := fixture.service.SearchPinned(fixture.ctx, fixture.principal1, pin, "")
	for _, readErr := range []error{pageErr, payloadErr, searchErr} {
		require.ErrorIs(t, readErr, ErrWikiReleaseAccessDenied)
	}
	_, err = fixture.service.ReadPinnedPage(
		fixture.ctx, fixture.principal1, WikiReleasePinnedRead{}, "a",
	)
	require.ErrorIs(t, err, ErrWikiReleaseNotFound)
}

func TestWikiReleasePR2RevertReusesHistoricalReleaseAndRollsBack(t *testing.T) {
	fixture := newWikiReleaseFixture(t, WikiReleaseFaults{})
	r0 := fixture.prepare(t, "preparation-r0", "candidate-r0", "", 0, r0WikiReleaseMembers())
	r0Receipt, err := fixture.activate(t, r0, "nonce-r0")
	require.NoError(t, err)
	r1 := fixture.prepare(
		t, "preparation-r1", "candidate-r1", r0Receipt.ReleaseID, r0Receipt.ActivationEpoch, r1WikiReleaseMembers(),
	)
	r1Receipt, err := fixture.activate(t, r1, "nonce-r1")
	require.NoError(t, err)
	before, err := fixture.repo.CountState(fixture.ctx)
	require.NoError(t, err)

	raw := signRevertAuthorization059(t, fixture.privateKey, r0, r1Receipt, "nonce-revert")
	reverted, err := fixture.service.Revert(fixture.ctx, fixture.principal1, raw)
	require.NoError(t, err)
	require.Equal(t, r0Receipt.ReleaseID, reverted.ReleaseID)
	require.Equal(t, uint64(3), reverted.ActivationEpoch)
	after, err := fixture.repo.CountState(fixture.ctx)
	require.NoError(t, err)
	require.Equal(t, before.Releases, after.Releases)
	require.Equal(t, before.Members, after.Members)
	require.Equal(t, before.Heads, after.Heads)
	require.Equal(t, before.Receipts+1, after.Receipts)
	retry, err := fixture.service.Revert(fixture.ctx, fixture.principal1, raw)
	require.NoError(t, err)
	require.Equal(t, reverted, retry)

	t.Run("receipt fault rolls back head", func(t *testing.T) {
		receiptFaultEnabled := false
		broken := newWikiReleaseFixture(t, WikiReleaseFaults{Receipt: func() error {
			if receiptFaultEnabled {
				return errors.New("receipt fault")
			}
			return nil
		}})
		brokenR0 := broken.prepare(t, "preparation-r0", "candidate-r0", "", 0, r0WikiReleaseMembers())
		brokenR0Receipt, err := broken.activate(t, brokenR0, "nonce-r0")
		require.NoError(t, err)
		brokenR1 := broken.prepare(
			t, "preparation-r1", "candidate-r1", brokenR0Receipt.ReleaseID, brokenR0Receipt.ActivationEpoch, r1WikiReleaseMembers(),
		)
		brokenR1Receipt, err := broken.activate(t, brokenR1, "nonce-r1")
		require.NoError(t, err)
		brokenBefore, err := broken.repo.CountState(broken.ctx)
		require.NoError(t, err)
		receiptFaultEnabled = true
		_, err = broken.service.Revert(
			broken.ctx,
			broken.principal1,
			signRevertAuthorization059(t, broken.privateKey, brokenR0, brokenR1Receipt, "nonce-revert"),
		)
		require.EqualError(t, err, "receipt fault")
		brokenAfter, err := broken.repo.CountState(broken.ctx)
		require.NoError(t, err)
		require.Equal(t, brokenBefore, brokenAfter)
		current, err := broken.service.Current(broken.ctx, broken.principal1, broken.scope)
		require.NoError(t, err)
		require.Equal(t, brokenR1Receipt.ReleaseID, current.ReleaseID)
	})
}

func TestWikiReleasePR2ActivateAndRevertCASContendersHaveOneWinner(t *testing.T) {
	fixture := newSerializedWikiReleaseFixture059(t)
	r0 := fixture.prepare(t, "preparation-r0", "candidate-r0", "", 0, r0WikiReleaseMembers())
	r0Receipt, err := fixture.activate(t, r0, "nonce-r0")
	require.NoError(t, err)
	r1 := fixture.prepare(
		t, "preparation-r1", "candidate-r1", r0Receipt.ReleaseID,
		r0Receipt.ActivationEpoch, r1WikiReleaseMembers(),
	)
	r1Receipt, err := fixture.activate(t, r1, "nonce-r1")
	require.NoError(t, err)
	humanKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x62}, ed25519.SeedSize))
	configureHumanDecisionVerifier059(fixture, humanKey)
	decisionRaw, decision := signHumanDecision059(
		t, humanKey, fixture, "approve", "nonce-r2", hash059("candidate-r2"),
	)
	r2 := prepareReviewed059(
		t, fixture, decision, decisionRaw, "preparation-r2",
		r1Receipt.ReleaseID, r1Receipt.ActivationEpoch,
	)
	activateRaw := signWikiReleaseAuthorization(
		t, fixture.privateKey, r2, decision.Nonce, decision.ExpiresAt,
	)
	revertRaw := signRevertAuthorization059(t, fixture.privateKey, r0, r1Receipt, "nonce-revert")

	start := make(chan struct{})
	results := make(chan error, 2)
	var ready sync.WaitGroup
	ready.Add(2)
	go func() {
		ready.Done()
		<-start
		_, activateErr := fixture.service.ActivateReviewed(
			fixture.ctx, fixture.principal1, decisionRaw, activateRaw,
		)
		results <- activateErr
	}()
	go func() {
		ready.Done()
		<-start
		_, revertErr := fixture.service.Revert(fixture.ctx, fixture.principal1, revertRaw)
		results <- revertErr
	}()
	ready.Wait()
	close(start)
	resultsByCall := []error{<-results, <-results}
	winners := 0
	conflicts := 0
	for _, result := range resultsByCall {
		if result == nil {
			winners++
		} else if errors.Is(result, ErrWikiReleaseConflict) {
			conflicts++
		} else {
			require.NoError(t, result)
		}
	}
	require.Equal(t, 1, winners)
	require.Equal(t, 1, conflicts)
	current, currentErr := fixture.service.Current(fixture.ctx, fixture.principal1, fixture.scope)
	require.NoError(t, currentErr)
	require.Equal(t, uint64(3), current.ActivationEpoch)
	state, countErr := fixture.repo.CountState(fixture.ctx)
	require.NoError(t, countErr)
	require.Equal(t, int64(3), state.Receipts)
}

func newSerializedWikiReleaseFixture059(t *testing.T) *wikiReleaseFixture {
	t.Helper()
	name := fmt.Sprintf(
		"%s-%d",
		strings.NewReplacer("/", "-", " ", "-").Replace(t.Name()),
		serializedFixtureSequence059.Add(1),
	)
	db, err := gorm.Open(sqlite.Open("file:"+name+"?mode=memory&cache=shared"), &gorm.Config{})
	require.NoError(t, err)
	sqlDB, err := db.DB()
	require.NoError(t, err)
	sqlDB.SetMaxOpenConns(1)
	require.NoError(t, db.AutoMigrate(
		&types.WikiReleasePreparation{}, &types.WikiRelease{}, &types.WikiReleaseMember{},
		&types.WikiReleaseHead{}, &types.WikiReleaseReceipt{},
	))
	repo := wikirepository.NewWikiReleaseRepository(db)
	scope := types.WikiReleaseScope{
		TenantID: 42, SpaceID: "space-1", RawKBID: "raw-1", WikiKBID: "wiki-1",
	}
	principal1 := types.WikiReleasePrincipal{
		ID: "principal-1", TenantID: 42, SpaceID: "space-1",
	}
	principal2 := types.WikiReleasePrincipal{
		ID: "principal-2", TenantID: 42, SpaceID: "space-1",
	}
	access := &mutableWikiReleaseAccessVerifier{allowed: map[string]types.WikiReleaseScope{
		principal1.ID: scope, principal2.ID: scope,
	}}
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x44}, ed25519.SeedSize))
	nowUnix := int64(1_000)
	var id atomic.Int64
	releaseService := NewWikiReleaseService(
		repo, access,
		NewEd25519WikiReleaseAuthorizationVerifier(map[string]ed25519.PublicKey{
			"signer-1": privateKey.Public().(ed25519.PublicKey),
		}),
		WikiReleaseServiceOptions{
			Now: func() time.Time { return time.Unix(nowUnix, 0).UTC() },
			NewID: func(kind string) string {
				return fmt.Sprintf("%s-%d", kind, id.Add(1))
			},
		},
	)
	return &wikiReleaseFixture{
		ctx: context.Background(), repo: repo, service: releaseService, scope: scope,
		principal1: principal1, principal2: principal2, access: access,
		privateKey: privateKey, nowUnix: &nowUnix,
	}
}

func hash059(value string) string {
	return sha256Hex059([]byte(value))
}

func configureHumanDecisionVerifier059(
	fixture *wikiReleaseFixture,
	humanKey ed25519.PrivateKey,
) {
	id := 0
	fixture.service = NewWikiReleaseService(
		fixture.repo,
		fixture.access,
		fixture.service.authorizationVerifier,
		WikiReleaseServiceOptions{
			Now: func() time.Time { return time.Unix(*fixture.nowUnix, 0).UTC() },
			NewID: func(kind string) string {
				id++
				return fmt.Sprintf("%s-pr2-%d", kind, id)
			},
			HumanDecisionVerifier: NewEd25519HumanBatchDecisionVerifier(
				map[string]ed25519.PublicKey{"human-1": humanKey.Public().(ed25519.PublicKey)},
			),
		},
	)
}

func sha256Hex059(value []byte) string {
	sum := sha256.Sum256(value)
	return hex.EncodeToString(sum[:])
}

func signHumanDecision059(
	t *testing.T,
	privateKey ed25519.PrivateKey,
	fixture *wikiReleaseFixture,
	decision string,
	nonce string,
	candidateHash string,
) ([]byte, *types.HumanBatchDecisionReceiptV1) {
	t.Helper()
	receipt := &types.HumanBatchDecisionReceiptV1{
		Version:          "1",
		Decision:         decision,
		PrincipalID:      fixture.principal1.ID,
		WikiReleaseScope: fixture.scope,
		CandidateHash:    candidateHash,
		HumanBatchHash:   hash059("batch-" + nonce),
		ReviewPolicyHash: hash059("policy-1"),
		IssuedAt:         1_000,
		ExpiresAt:        2_000,
		Nonce:            nonce,
		SignerKeyID:      "human-1",
	}
	unsigned, err := CanonicalHumanBatchDecisionReceiptV1(receipt, false)
	require.NoError(t, err)
	receipt.Signature = EncodeWikiReleaseSignature(ed25519.Sign(privateKey, unsigned))
	raw, err := CanonicalHumanBatchDecisionReceiptV1(receipt, true)
	require.NoError(t, err)
	return raw, receipt
}

func prepareReviewed059(
	t *testing.T,
	fixture *wikiReleaseFixture,
	decision *types.HumanBatchDecisionReceiptV1,
	rawDecision []byte,
	id string,
	expectedReleaseID string,
	expectedEpoch uint64,
) *types.WikiReleasePreparation {
	t.Helper()
	preparation, err := fixture.service.Prepare(
		fixture.ctx,
		fixture.principal1,
		&types.WikiReleasePreparation{
			ID:                      id,
			WikiReleaseScope:        fixture.scope,
			CandidateDigest:         decision.CandidateHash,
			ReadyReceiptDigest:      decision.HumanBatchHash,
			ReviewDecisionDigest:    sha256Hex059(rawDecision),
			ReviewPolicyID:          decision.ReviewPolicyHash,
			ExpectedReleaseID:       expectedReleaseID,
			ExpectedActivationEpoch: expectedEpoch,
			Members:                 r0WikiReleaseMembers(),
		},
	)
	require.NoError(t, err)
	return preparation
}

func signRevertAuthorization059(
	t *testing.T,
	privateKey ed25519.PrivateKey,
	target *types.WikiReleasePreparation,
	current *types.WikiReleaseReceipt,
	nonce string,
) []byte {
	t.Helper()
	authorization := &types.PublishAuthorizationV0{
		Version:                 "0",
		Action:                  "revert",
		PreparationID:           target.ID,
		CandidateDigest:         target.CandidateDigest,
		ManifestDigest:          target.ManifestDigest,
		ReadyReceiptDigest:      target.ReadyReceiptDigest,
		ReviewDecisionDigest:    target.ReviewDecisionDigest,
		ReviewPolicyID:          target.ReviewPolicyID,
		TenantID:                target.TenantID,
		SpaceID:                 target.SpaceID,
		RawKBID:                 target.RawKBID,
		WikiKBID:                target.WikiKBID,
		ExpectedReleaseID:       current.ReleaseID,
		ExpectedActivationEpoch: current.ActivationEpoch,
		ExpiresAt:               2_000,
		Nonce:                   nonce,
		SignerKeyID:             "signer-1",
	}
	unsigned, err := CanonicalPublishAuthorizationV0(authorization, false)
	require.NoError(t, err)
	authorization.Signature = EncodeWikiReleaseSignature(ed25519.Sign(privateKey, unsigned))
	raw, err := CanonicalPublishAuthorizationV0(authorization, true)
	require.NoError(t, err)
	return raw
}
