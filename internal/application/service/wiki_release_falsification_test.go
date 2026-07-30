package service

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/postgres"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func TestWikiReleaseFalsificationStrictAuthorizationRejectsEmptyJSON(t *testing.T) {
	_, err := ParsePublishAuthorizationV0([]byte(`{}`))
	require.Error(t, err)
}

func TestWikiReleaseFalsificationDefaultAccessVerifierFailsClosed(t *testing.T) {
	scope := types.WikiReleaseScope{
		TenantID: 42,
		SpaceID:  "space-1",
		RawKBID:  "raw-1",
		WikiKBID: "wiki-1",
	}
	err := NewDefaultWikiReleaseAccessVerifier().VerifyWikiReleaseAccess(
		context.Background(),
		WikiReleaseAccessRequest{
			Principal: types.WikiReleasePrincipal{
				ID:                     "self-asserted-principal",
				TenantID:               scope.TenantID,
				SpaceID:                scope.SpaceID,
				APIKeyKnowledgeBaseIDs: []string{scope.RawKBID, scope.WikiKBID},
			},
			Scope:     scope,
			Operation: "current",
		},
	)
	require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
}

func TestWikiReleaseFalsificationStrictCanonicalAuthorization(t *testing.T) {
	authorization := &types.PublishAuthorizationV0{
		Version:                 "0",
		Action:                  "activate",
		PreparationID:           "preparation-1",
		CandidateDigest:         "candidate-cafe\u0301",
		ManifestDigest:          "manifest-1",
		ReadyReceiptDigest:      "ready-1",
		ReviewDecisionDigest:    "review-1",
		ReviewPolicyID:          "policy-1",
		TenantID:                42,
		SpaceID:                 "space-1",
		RawKBID:                 "raw-1",
		WikiKBID:                "wiki-1",
		ExpectedReleaseID:       "release-0",
		ExpectedActivationEpoch: 7,
		ExpiresAt:               2_000_000_000,
		Nonce:                   "nonce-1",
		SignerKeyID:             "signer-1",
	}

	signingBytes, err := CanonicalPublishAuthorizationV0(authorization, false)
	require.NoError(t, err)
	require.Equal(t,
		`{"action":"activate","candidate_digest":"candidate-café","expected_activation_epoch":7,"expected_release_id":"release-0","expires_at":2000000000,"manifest_digest":"manifest-1","nonce":"nonce-1","preparation_id":"preparation-1","raw_kb_id":"raw-1","ready_receipt_digest":"ready-1","review_decision_digest":"review-1","review_policy_id":"policy-1","signer_key_id":"signer-1","space_id":"space-1","tenant_id":42,"version":"0","wiki_kb_id":"wiki-1"}`,
		string(signingBytes),
	)

	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x2a}, ed25519.SeedSize))
	authorization.Signature = EncodeWikiReleaseSignature(ed25519.Sign(privateKey, signingBytes))
	raw, err := CanonicalPublishAuthorizationV0(authorization, true)
	require.NoError(t, err)

	parsed, err := ParsePublishAuthorizationV0(raw)
	require.NoError(t, err)
	require.Equal(t, "candidate-café", parsed.CandidateDigest)

	verifier := NewEd25519WikiReleaseAuthorizationVerifier(map[string]ed25519.PublicKey{
		"signer-1": privateKey.Public().(ed25519.PublicKey),
	})
	require.NoError(t, verifier.Verify(parsed))

	t.Run("unknown key", func(t *testing.T) {
		withUnknown := append([]byte(nil), raw[:len(raw)-1]...)
		withUnknown = append(withUnknown, []byte(`,"unexpected":"x"}`)...)
		_, err := ParsePublishAuthorizationV0(withUnknown)
		require.ErrorIs(t, err, ErrWikiReleaseInvalidAuthorization)
	})

	t.Run("duplicate key", func(t *testing.T) {
		withDuplicate := append([]byte(nil), raw[:len(raw)-1]...)
		withDuplicate = append(withDuplicate, []byte(`,"nonce":"nonce-2"}`)...)
		_, err := ParsePublishAuthorizationV0(withDuplicate)
		require.ErrorIs(t, err, ErrWikiReleaseInvalidAuthorization)
	})

	t.Run("floating integer", func(t *testing.T) {
		withFloat := strings.Replace(string(raw), `"tenant_id":42`, `"tenant_id":42.5`, 1)
		_, err := ParsePublishAuthorizationV0([]byte(withFloat))
		require.ErrorIs(t, err, ErrWikiReleaseInvalidAuthorization)
	})

	t.Run("unknown signer", func(t *testing.T) {
		require.ErrorIs(t,
			NewEd25519WikiReleaseAuthorizationVerifier(nil).Verify(parsed),
			ErrWikiReleaseInvalidAuthorization,
		)
	})

	t.Run("malformed signature", func(t *testing.T) {
		parsed.Signature = "not+raw-url"
		require.ErrorIs(t, verifier.Verify(parsed), ErrWikiReleaseInvalidAuthorization)
	})
}

func TestWikiReleaseFalsificationRepositoryCASRollsBackLoser(t *testing.T) {
	ctx := context.Background()
	db, err := gorm.Open(sqlite.Open("file:wiki-release-repository?mode=memory&cache=shared"), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(
		&types.WikiReleasePreparation{},
		&types.WikiRelease{},
		&types.WikiReleaseMember{},
		&types.WikiReleaseHead{},
		&types.WikiReleaseReceipt{},
	))
	repo := wikirepository.NewWikiReleaseRepository(db)
	scope := types.WikiReleaseScope{
		TenantID: 42,
		SpaceID:  "space-1",
		RawKBID:  "raw-1",
		WikiKBID: "wiki-1",
	}
	members := []types.WikiReleaseMemberSnapshot{
		{LogicalSlug: "a", RevisionID: "a0", MemberDigest: "digest-a0", Title: "A", Content: "A0", Payload: json.RawMessage(`{"slug":"a","v":0}`)},
		{LogicalSlug: "b", RevisionID: "b0", MemberDigest: "digest-b0", Title: "B", Content: "B0", Payload: json.RawMessage(`{"slug":"b","v":0}`)},
		{LogicalSlug: "c", RevisionID: "c0", MemberDigest: "digest-c0", Title: "C", Content: "C0", Payload: json.RawMessage(`{"slug":"c","v":0}`)},
	}
	preparation := &types.WikiReleasePreparation{
		ID:                      "preparation-r0",
		WikiReleaseScope:        scope,
		CandidateDigest:         "candidate-r0",
		ManifestDigest:          "manifest-r0",
		ReadyReceiptDigest:      "ready-r0",
		ReviewDecisionDigest:    "review-r0",
		ReviewPolicyID:          "policy-1",
		ExpectedReleaseID:       "",
		ExpectedActivationEpoch: 0,
		Status:                  types.WikiReleasePreparationReady,
		Manifest:                json.RawMessage(`{"members":["a","b","c"]}`),
		Members:                 members,
		CreatedAt:               time.Unix(100, 0).UTC(),
	}
	require.NoError(t, repo.CreateReadyPreparation(ctx, preparation))

	stored, err := repo.GetReadyPreparation(ctx, scope, preparation.ID)
	require.NoError(t, err)
	require.Equal(t, preparation.Manifest, stored.Manifest)
	require.Equal(t, members, stored.Members)

	receipt, err := repo.Activate(ctx, wikirepository.WikiReleaseActivationWrite{
		Release: &types.WikiRelease{
			ID:                  "release-r0",
			WikiReleaseScope:    scope,
			CandidateDigest:     preparation.CandidateDigest,
			ManifestDigest:      preparation.ManifestDigest,
			BaseReleaseID:       "",
			BaseActivationEpoch: 0,
			CreatedAt:           time.Unix(101, 0).UTC(),
			ActivatedAt:         time.Unix(101, 0).UTC(),
		},
		Members:                   members,
		ExpectedReleaseID:         "",
		ExpectedActivationEpoch:   0,
		Nonce:                     "nonce-r0",
		AuthorizationDigest:       "authorization-r0",
		ActivatedBy:               "principal-1",
		ActivatedAt:               time.Unix(101, 0).UTC(),
		ActivationReceiptID:       "receipt-r0",
		ExpectedPreparationID:     preparation.ID,
		ExpectedPreparationDigest: preparation.ManifestDigest,
	})
	require.NoError(t, err)
	require.Equal(t, "release-r0", receipt.ReleaseID)
	require.Equal(t, uint64(1), receipt.ActivationEpoch)

	_, err = repo.Activate(ctx, wikirepository.WikiReleaseActivationWrite{
		Release: &types.WikiRelease{
			ID:                  "release-loser",
			WikiReleaseScope:    scope,
			CandidateDigest:     "candidate-loser",
			ManifestDigest:      "manifest-loser",
			BaseReleaseID:       "",
			BaseActivationEpoch: 0,
			CreatedAt:           time.Unix(102, 0).UTC(),
			ActivatedAt:         time.Unix(102, 0).UTC(),
		},
		Members:                   members,
		ExpectedReleaseID:         "",
		ExpectedActivationEpoch:   0,
		Nonce:                     "nonce-loser",
		AuthorizationDigest:       "authorization-loser",
		ActivatedBy:               "principal-1",
		ActivatedAt:               time.Unix(102, 0).UTC(),
		ActivationReceiptID:       "receipt-loser",
		ExpectedPreparationID:     "preparation-loser",
		ExpectedPreparationDigest: "manifest-loser",
	})
	require.ErrorIs(t, err, wikirepository.ErrWikiReleaseConflict)

	state, err := repo.CountState(ctx)
	require.NoError(t, err)
	require.Equal(t, types.WikiReleaseStateCount{
		Preparations: 1,
		Releases:     1,
		Members:      3,
		Heads:        1,
		Receipts:     1,
	}, state)
}

type mutableWikiReleaseAccessVerifier struct {
	allowed map[string]types.WikiReleaseScope
}

func (v *mutableWikiReleaseAccessVerifier) VerifyWikiReleaseAccess(
	_ context.Context,
	request WikiReleaseAccessRequest,
) error {
	scope, ok := v.allowed[request.Principal.ID]
	if !ok || scope != request.Scope ||
		request.Principal.ID == "" ||
		request.Principal.TenantID != request.Scope.TenantID ||
		request.Principal.SpaceID != request.Scope.SpaceID {
		return ErrWikiReleaseAccessDenied
	}
	return nil
}

type wikiReleaseFixture struct {
	ctx        context.Context
	repo       *wikirepository.WikiReleaseRepository
	service    *WikiReleaseService
	scope      types.WikiReleaseScope
	principal1 types.WikiReleasePrincipal
	principal2 types.WikiReleasePrincipal
	access     *mutableWikiReleaseAccessVerifier
	privateKey ed25519.PrivateKey
	nowUnix    *int64
}

func newWikiReleaseFixture(t *testing.T, faults WikiReleaseFaults) *wikiReleaseFixture {
	t.Helper()
	name := strings.NewReplacer("/", "-", " ", "-").Replace(t.Name())
	db, err := gorm.Open(sqlite.Open("file:"+name+"?mode=memory&cache=shared"), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(
		&types.WikiReleasePreparation{},
		&types.WikiRelease{},
		&types.WikiReleaseMember{},
		&types.WikiReleaseHead{},
		&types.WikiReleaseReceipt{},
	))
	repo := wikirepository.NewWikiReleaseRepository(db)
	scope := types.WikiReleaseScope{
		TenantID: 42,
		SpaceID:  "space-1",
		RawKBID:  "raw-1",
		WikiKBID: "wiki-1",
	}
	principal1 := types.WikiReleasePrincipal{ID: "principal-1", TenantID: 42, SpaceID: "space-1"}
	principal2 := types.WikiReleasePrincipal{ID: "principal-2", TenantID: 42, SpaceID: "space-1"}
	access := &mutableWikiReleaseAccessVerifier{
		allowed: map[string]types.WikiReleaseScope{
			principal1.ID: scope,
			principal2.ID: scope,
		},
	}
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x44}, ed25519.SeedSize))
	nowUnix := int64(1_000)
	id := 0
	releaseService := NewWikiReleaseService(
		repo,
		access,
		NewEd25519WikiReleaseAuthorizationVerifier(map[string]ed25519.PublicKey{
			"signer-1": privateKey.Public().(ed25519.PublicKey),
		}),
		WikiReleaseServiceOptions{
			Now: func() time.Time { return time.Unix(nowUnix, 0).UTC() },
			NewID: func(kind string) string {
				id++
				return fmt.Sprintf("%s-%d", kind, id)
			},
			Faults: faults,
		},
	)
	return &wikiReleaseFixture{
		ctx:        context.Background(),
		repo:       repo,
		service:    releaseService,
		scope:      scope,
		principal1: principal1,
		principal2: principal2,
		access:     access,
		privateKey: privateKey,
		nowUnix:    &nowUnix,
	}
}

func (fixture *wikiReleaseFixture) prepare(
	t *testing.T,
	id string,
	candidate string,
	expectedReleaseID string,
	expectedEpoch uint64,
	members []types.WikiReleaseMemberSnapshot,
) *types.WikiReleasePreparation {
	t.Helper()
	preparation, err := fixture.service.Prepare(
		fixture.ctx,
		fixture.principal1,
		&types.WikiReleasePreparation{
			ID:                      id,
			WikiReleaseScope:        fixture.scope,
			CandidateDigest:         candidate,
			ReadyReceiptDigest:      "ready-" + id,
			ReviewDecisionDigest:    "review-" + id,
			ReviewPolicyID:          "policy-1",
			ExpectedReleaseID:       expectedReleaseID,
			ExpectedActivationEpoch: expectedEpoch,
			Members:                 members,
		},
	)
	require.NoError(t, err)
	return preparation
}

func (fixture *wikiReleaseFixture) activate(
	t *testing.T,
	preparation *types.WikiReleasePreparation,
	nonce string,
) (*types.WikiReleaseReceipt, error) {
	t.Helper()
	return fixture.service.Activate(
		fixture.ctx,
		fixture.principal1,
		signWikiReleaseAuthorization(t, fixture.privateKey, preparation, nonce, 2_000),
	)
}

func r0WikiReleaseMembers() []types.WikiReleaseMemberSnapshot {
	return []types.WikiReleaseMemberSnapshot{
		{LogicalSlug: "a", RevisionID: "a0", MemberDigest: "digest-a0", Title: "A", Content: "A0", Payload: json.RawMessage(`{"slug":"a","v":0}`)},
		{LogicalSlug: "b", RevisionID: "b0", MemberDigest: "digest-b0", Title: "B", Content: "B0", Payload: json.RawMessage(`{"slug":"b","v":0}`)},
		{LogicalSlug: "c", RevisionID: "c0", MemberDigest: "digest-c0", Title: "C", Content: "C0", Payload: json.RawMessage(`{"slug":"c","v":0}`)},
	}
}

func r1WikiReleaseMembers() []types.WikiReleaseMemberSnapshot {
	return []types.WikiReleaseMemberSnapshot{
		{LogicalSlug: "a", RevisionID: "a1", MemberDigest: "digest-a1", Title: "A", Content: "A1", Payload: json.RawMessage(`{"slug":"a","v":1}`)},
		{LogicalSlug: "c", RevisionID: "c0", MemberDigest: "digest-c0", Title: "C", Content: "C0", Payload: json.RawMessage(`{"slug":"c","v":0}`)},
		{LogicalSlug: "d", RevisionID: "d0", MemberDigest: "digest-d0", Title: "D", Content: "D0", Payload: json.RawMessage(`{"slug":"d","v":0}`)},
	}
}

func TestWikiReleaseFalsificationR0ToR1UsesOneImmutableRelease(t *testing.T) {
	ctx := context.Background()
	db, err := gorm.Open(sqlite.Open("file:wiki-release-service?mode=memory&cache=shared"), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(
		&types.WikiReleasePreparation{},
		&types.WikiRelease{},
		&types.WikiReleaseMember{},
		&types.WikiReleaseHead{},
		&types.WikiReleaseReceipt{},
	))
	repo := wikirepository.NewWikiReleaseRepository(db)
	scope := types.WikiReleaseScope{
		TenantID: 42,
		SpaceID:  "space-1",
		RawKBID:  "raw-1",
		WikiKBID: "wiki-1",
	}
	principal := types.WikiReleasePrincipal{
		ID:       "principal-1",
		TenantID: 42,
		SpaceID:  "space-1",
	}
	access := &mutableWikiReleaseAccessVerifier{
		allowed: map[string]types.WikiReleaseScope{principal.ID: scope},
	}
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x33}, ed25519.SeedSize))
	id := 0
	releaseService := NewWikiReleaseService(
		repo,
		access,
		NewEd25519WikiReleaseAuthorizationVerifier(map[string]ed25519.PublicKey{
			"signer-1": privateKey.Public().(ed25519.PublicKey),
		}),
		WikiReleaseServiceOptions{
			Now: func() time.Time { return time.Unix(1_000, 0).UTC() },
			NewID: func(kind string) string {
				id++
				return fmt.Sprintf("%s-%d", kind, id)
			},
		},
	)

	r0Members := []types.WikiReleaseMemberSnapshot{
		{LogicalSlug: "a", RevisionID: "a0", MemberDigest: "digest-a0", Title: "A", Content: "A0", Payload: json.RawMessage(`{"slug":"a","v":0}`)},
		{LogicalSlug: "b", RevisionID: "b0", MemberDigest: "digest-b0", Title: "B", Content: "B0", Payload: json.RawMessage(`{"slug":"b","v":0}`)},
		{LogicalSlug: "c", RevisionID: "c0", MemberDigest: "digest-c0", Title: "C", Content: "C0", Payload: json.RawMessage(`{"slug":"c","v":0}`)},
	}
	r0Preparation, err := releaseService.Prepare(ctx, principal, &types.WikiReleasePreparation{
		ID:                   "preparation-r0",
		WikiReleaseScope:     scope,
		CandidateDigest:      "candidate-r0",
		ReadyReceiptDigest:   "ready-r0",
		ReviewDecisionDigest: "review-r0",
		ReviewPolicyID:       "policy-1",
		Members:              r0Members,
	})
	require.NoError(t, err)
	r0Receipt, err := releaseService.Activate(
		ctx,
		principal,
		signWikiReleaseAuthorization(t, privateKey, r0Preparation, "nonce-r0", 2_000),
	)
	require.NoError(t, err)
	require.Equal(t, uint64(1), r0Receipt.ActivationEpoch)

	r1Members := []types.WikiReleaseMemberSnapshot{
		{LogicalSlug: "a", RevisionID: "a1", MemberDigest: "digest-a1", Title: "A", Content: "A1", Payload: json.RawMessage(`{"slug":"a","v":1}`)},
		{LogicalSlug: "c", RevisionID: "c0", MemberDigest: "digest-c0", Title: "C", Content: "C0", Payload: json.RawMessage(`{"slug":"c","v":0}`)},
		{LogicalSlug: "d", RevisionID: "d0", MemberDigest: "digest-d0", Title: "D", Content: "D0", Payload: json.RawMessage(`{"slug":"d","v":0}`)},
	}
	r1Preparation, err := releaseService.Prepare(ctx, principal, &types.WikiReleasePreparation{
		ID:                      "preparation-r1",
		WikiReleaseScope:        scope,
		CandidateDigest:         "candidate-r1",
		ReadyReceiptDigest:      "ready-r1",
		ReviewDecisionDigest:    "review-r1",
		ReviewPolicyID:          "policy-1",
		ExpectedReleaseID:       r0Receipt.ReleaseID,
		ExpectedActivationEpoch: r0Receipt.ActivationEpoch,
		Members:                 r1Members,
	})
	require.NoError(t, err)
	loserPreparation, err := releaseService.Prepare(ctx, principal, &types.WikiReleasePreparation{
		ID:                      "preparation-loser",
		WikiReleaseScope:        scope,
		CandidateDigest:         "candidate-loser",
		ReadyReceiptDigest:      "ready-loser",
		ReviewDecisionDigest:    "review-loser",
		ReviewPolicyID:          "policy-1",
		ExpectedReleaseID:       r0Receipt.ReleaseID,
		ExpectedActivationEpoch: r0Receipt.ActivationEpoch,
		Members: append([]types.WikiReleaseMemberSnapshot(nil),
			r1Members...),
	})
	require.NoError(t, err)

	r1Receipt, err := releaseService.Activate(
		ctx,
		principal,
		signWikiReleaseAuthorization(t, privateKey, r1Preparation, "nonce-r1", 2_000),
	)
	require.NoError(t, err)
	_, err = releaseService.Activate(
		ctx,
		principal,
		signWikiReleaseAuthorization(t, privateKey, loserPreparation, "nonce-loser", 2_000),
	)
	require.ErrorIs(t, err, ErrWikiReleaseConflict)

	current, err := releaseService.Current(ctx, principal, scope)
	require.NoError(t, err)
	require.Equal(t, types.WikiReleaseCurrent{
		ReleaseID:       r1Receipt.ReleaseID,
		ActivationEpoch: 2,
	}, current)

	pageA, err := releaseService.PinnedPage(ctx, principal, scope, current.ReleaseID, "a")
	require.NoError(t, err)
	require.Equal(t, "A1", pageA.Content)
	payloadA, err := releaseService.PinnedPayload(ctx, principal, scope, current.ReleaseID, "a")
	require.NoError(t, err)
	require.JSONEq(t, `{"slug":"a","v":1}`, string(payloadA))
	_, err = releaseService.PinnedPage(ctx, principal, scope, current.ReleaseID, "b")
	require.ErrorIs(t, err, ErrWikiReleaseNotFound)
	pageC, err := releaseService.PinnedPage(ctx, principal, scope, current.ReleaseID, "c")
	require.NoError(t, err)
	require.Equal(t, "c0", pageC.RevisionID)
	pageD, err := releaseService.PinnedPage(ctx, principal, scope, current.ReleaseID, "d")
	require.NoError(t, err)
	require.Equal(t, "D0", pageD.Content)

	search, err := releaseService.MinimalSearch(ctx, principal, scope, current.ReleaseID, "")
	require.NoError(t, err)
	require.Equal(t, []string{"a", "c", "d"}, releaseSlugs(search))

	pinnedR0, err := releaseService.MinimalSearch(ctx, principal, scope, r0Receipt.ReleaseID, "")
	require.NoError(t, err)
	require.Equal(t, []string{"a", "b", "c"}, releaseSlugs(pinnedR0))

	state, err := repo.CountState(ctx)
	require.NoError(t, err)
	require.Equal(t, types.WikiReleaseStateCount{
		Preparations: 3,
		Releases:     2,
		Members:      6,
		Heads:        1,
		Receipts:     2,
	}, state)
}

func TestWikiReleaseFalsificationRejectsSecondWikiBindingInTenantSpace(t *testing.T) {
	fixture := newWikiReleaseFixture(t, WikiReleaseFaults{})
	r0 := fixture.prepare(t, "preparation-r0", "candidate-r0", "", 0, r0WikiReleaseMembers())
	_, err := fixture.activate(t, r0, "nonce-r0")
	require.NoError(t, err)

	before, err := fixture.repo.CountState(fixture.ctx)
	require.NoError(t, err)

	secondScope := fixture.scope
	secondScope.RawKBID = "raw-2"
	secondScope.WikiKBID = "wiki-2"
	fixture.access.allowed[fixture.principal1.ID] = secondScope
	_, err = fixture.service.Prepare(
		fixture.ctx,
		fixture.principal1,
		&types.WikiReleasePreparation{
			ID:                   "preparation-second-wiki",
			WikiReleaseScope:     secondScope,
			CandidateDigest:      "candidate-second-wiki",
			ReadyReceiptDigest:   "ready-second-wiki",
			ReviewDecisionDigest: "review-second-wiki",
			ReviewPolicyID:       "policy-1",
			Members:              r0WikiReleaseMembers(),
		},
	)
	var conflict *WikiReleaseConflictError
	require.ErrorAs(t, err, &conflict)

	after, err := fixture.repo.CountState(fixture.ctx)
	require.NoError(t, err)
	require.Equal(t, before, after)
}

func TestWikiReleaseFalsificationRejectsPreparedSecondWikiActivation(t *testing.T) {
	fixture := newWikiReleaseFixture(t, WikiReleaseFaults{})
	secondScope := fixture.scope
	secondScope.RawKBID = "raw-2"
	secondScope.WikiKBID = "wiki-2"

	fixture.access.allowed[fixture.principal1.ID] = secondScope
	secondPreparation, err := fixture.service.Prepare(
		fixture.ctx,
		fixture.principal1,
		&types.WikiReleasePreparation{
			ID:                   "preparation-second-wiki",
			WikiReleaseScope:     secondScope,
			CandidateDigest:      "candidate-second-wiki",
			ReadyReceiptDigest:   "ready-second-wiki",
			ReviewDecisionDigest: "review-second-wiki",
			ReviewPolicyID:       "policy-1",
			Members:              r0WikiReleaseMembers(),
		},
	)
	require.NoError(t, err)

	fixture.access.allowed[fixture.principal1.ID] = fixture.scope
	r0 := fixture.prepare(t, "preparation-r0", "candidate-r0", "", 0, r0WikiReleaseMembers())
	_, err = fixture.activate(t, r0, "nonce-r0")
	require.NoError(t, err)

	before, err := fixture.repo.CountState(fixture.ctx)
	require.NoError(t, err)

	fixture.access.allowed[fixture.principal1.ID] = secondScope
	_, err = fixture.service.Activate(
		fixture.ctx,
		fixture.principal1,
		signWikiReleaseAuthorization(t, fixture.privateKey, secondPreparation, "nonce-second-wiki", 2_000),
	)
	var conflict *WikiReleaseConflictError
	require.ErrorAs(t, err, &conflict)

	after, err := fixture.repo.CountState(fixture.ctx)
	require.NoError(t, err)
	require.Equal(t, before, after)
}

func TestWikiReleaseFalsificationFaultsLeaveNoHalfWrite(t *testing.T) {
	for _, faultPoint := range []string{"preparation", "index"} {
		t.Run(faultPoint, func(t *testing.T) {
			injected := errors.New("injected " + faultPoint + " fault")
			faults := WikiReleaseFaults{}
			if faultPoint == "preparation" {
				faults.Preparation = func() error { return injected }
			} else {
				faults.Index = func() error { return injected }
			}
			fixture := newWikiReleaseFixture(t, faults)
			before, err := fixture.repo.CountState(fixture.ctx)
			require.NoError(t, err)
			_, err = fixture.service.Prepare(
				fixture.ctx,
				fixture.principal1,
				&types.WikiReleasePreparation{
					ID:                   "preparation-r0",
					WikiReleaseScope:     fixture.scope,
					CandidateDigest:      "candidate-r0",
					ReadyReceiptDigest:   "ready-r0",
					ReviewDecisionDigest: "review-r0",
					ReviewPolicyID:       "policy-1",
					Members:              r0WikiReleaseMembers(),
				},
			)
			require.ErrorIs(t, err, injected)
			after, err := fixture.repo.CountState(fixture.ctx)
			require.NoError(t, err)
			require.Equal(t, before, after)
		})
	}

	for _, faultPoint := range []string{"cas", "receipt"} {
		t.Run(faultPoint, func(t *testing.T) {
			injected := errors.New("injected " + faultPoint + " fault")
			enabled := false
			fault := func() error {
				if enabled {
					return injected
				}
				return nil
			}
			faults := WikiReleaseFaults{}
			if faultPoint == "cas" {
				faults.CAS = fault
			} else {
				faults.Receipt = fault
			}
			fixture := newWikiReleaseFixture(t, faults)
			r0Preparation := fixture.prepare(t, "preparation-r0", "candidate-r0", "", 0, r0WikiReleaseMembers())
			r0Receipt, err := fixture.activate(t, r0Preparation, "nonce-r0")
			require.NoError(t, err)
			r1Preparation := fixture.prepare(
				t,
				"preparation-r1",
				"candidate-r1",
				r0Receipt.ReleaseID,
				r0Receipt.ActivationEpoch,
				r1WikiReleaseMembers(),
			)
			before, err := fixture.repo.CountState(fixture.ctx)
			require.NoError(t, err)
			enabled = true
			_, err = fixture.activate(t, r1Preparation, "nonce-r1")
			require.ErrorIs(t, err, injected)
			after, err := fixture.repo.CountState(fixture.ctx)
			require.NoError(t, err)
			require.Equal(t, before, after)
			current, err := fixture.service.Current(fixture.ctx, fixture.principal1, fixture.scope)
			require.NoError(t, err)
			require.Equal(t, r0Receipt.ReleaseID, current.ReleaseID)
			require.Equal(t, r0Receipt.ActivationEpoch, current.ActivationEpoch)
		})
	}
}

func TestWikiReleaseFalsificationExactRetrySurvivesExpiry(t *testing.T) {
	fixture := newWikiReleaseFixture(t, WikiReleaseFaults{})
	preparation := fixture.prepare(
		t,
		"preparation-r0",
		"candidate-r0",
		"",
		0,
		r0WikiReleaseMembers(),
	)
	raw := signWikiReleaseAuthorization(t, fixture.privateKey, preparation, "nonce-r0", 2_000)
	receipt, err := fixture.service.Activate(
		fixture.ctx,
		fixture.principal1,
		raw,
	)
	require.NoError(t, err)

	*fixture.nowUnix = 3_000
	retry, err := fixture.service.Activate(
		fixture.ctx,
		fixture.principal1,
		raw,
	)
	require.NoError(t, err)
	require.Equal(t, receipt, retry)

	differentDigest := signWikiReleaseAuthorization(
		t,
		fixture.privateKey,
		preparation,
		"nonce-r0",
		4_000,
	)
	_, err = fixture.service.Activate(
		fixture.ctx,
		fixture.principal1,
		differentDigest,
	)
	require.ErrorIs(t, err, ErrWikiReleaseConflict)

	state, err := fixture.repo.CountState(fixture.ctx)
	require.NoError(t, err)
	require.Equal(t, types.WikiReleaseStateCount{
		Preparations: 1,
		Releases:     1,
		Members:      3,
		Heads:        1,
		Receipts:     1,
	}, state)
}

func TestWikiReleaseFalsificationActivationConflictResolvesCommittedReceipt(t *testing.T) {
	fixture := newWikiReleaseFixture(t, WikiReleaseFaults{})
	preparation := fixture.prepare(
		t,
		"preparation-r0",
		"candidate-r0",
		"",
		0,
		r0WikiReleaseMembers(),
	)
	raw := signWikiReleaseAuthorization(t, fixture.privateKey, preparation, "nonce-r0", 2_000)
	receipt, err := fixture.service.Activate(
		fixture.ctx,
		fixture.principal1,
		raw,
	)
	require.NoError(t, err)
	authorization, err := ParsePublishAuthorizationV0(raw)
	require.NoError(t, err)
	canonical, err := CanonicalPublishAuthorizationV0(authorization, true)
	require.NoError(t, err)

	resolved, err := fixture.service.resolveActivationError(
		fixture.ctx,
		fixture.principal1,
		fixture.scope,
		"nonce-r0",
		digestWikiReleaseBytes(canonical),
		wikirepository.ErrWikiReleaseConflict,
	)
	require.NoError(t, err)
	require.Equal(t, receipt, resolved)

	_, err = fixture.service.resolveActivationError(
		fixture.ctx,
		fixture.principal1,
		fixture.scope,
		"nonce-r0",
		"different-authorization-digest",
		wikirepository.ErrWikiReleaseConflict,
	)
	require.ErrorIs(t, err, ErrWikiReleaseConflict)
}

func TestWikiReleaseFalsificationReceiptIdentityIgnoresTenantRawDrift(t *testing.T) {
	fixture := newWikiReleaseFixture(t, WikiReleaseFaults{})
	preparation := fixture.prepare(
		t,
		"preparation-r0",
		"candidate-r0",
		"",
		0,
		r0WikiReleaseMembers(),
	)
	raw := signWikiReleaseAuthorization(t, fixture.privateKey, preparation, "nonce-r0", 2_000)
	receipt, err := fixture.service.Activate(
		fixture.ctx,
		fixture.principal1,
		raw,
	)
	require.NoError(t, err)

	driftedScope := fixture.scope
	driftedScope.TenantID = 999
	driftedScope.RawKBID = "raw-drifted"
	found, err := fixture.repo.GetReceipt(fixture.ctx, driftedScope, "nonce-r0")
	require.NoError(t, err)
	require.Equal(t, receipt, found)

	driftedAuthorization, err := ParsePublishAuthorizationV0(raw)
	require.NoError(t, err)
	driftedAuthorization.TenantID = driftedScope.TenantID
	driftedAuthorization.RawKBID = driftedScope.RawKBID
	signingBytes, err := CanonicalPublishAuthorizationV0(driftedAuthorization, false)
	require.NoError(t, err)
	driftedAuthorization.Signature = EncodeWikiReleaseSignature(
		ed25519.Sign(fixture.privateKey, signingBytes),
	)
	driftedRaw, err := CanonicalPublishAuthorizationV0(driftedAuthorization, true)
	require.NoError(t, err)
	_, err = fixture.service.Activate(
		fixture.ctx,
		fixture.principal1,
		driftedRaw,
	)
	var conflict *WikiReleaseConflictError
	require.ErrorAs(t, err, &conflict)

	state, err := fixture.repo.CountState(fixture.ctx)
	require.NoError(t, err)
	require.Equal(t, types.WikiReleaseStateCount{
		Preparations: 1,
		Releases:     1,
		Members:      3,
		Heads:        1,
		Receipts:     1,
	}, state)
}

func TestWikiReleaseFalsificationACLShrinkFailsClosed(t *testing.T) {
	fixture := newWikiReleaseFixture(t, WikiReleaseFaults{})
	preparation := fixture.prepare(
		t,
		"preparation-r0",
		"candidate-r0",
		"",
		0,
		r0WikiReleaseMembers(),
	)
	receipt, err := fixture.activate(t, preparation, "nonce-r0")
	require.NoError(t, err)

	for _, principal := range []types.WikiReleasePrincipal{
		fixture.principal1,
		fixture.principal2,
	} {
		current, err := fixture.service.Current(fixture.ctx, principal, fixture.scope)
		require.NoError(t, err)
		require.Equal(t, receipt.ReleaseID, current.ReleaseID)
		page, err := fixture.service.PinnedPage(
			fixture.ctx,
			principal,
			fixture.scope,
			receipt.ReleaseID,
			"a",
		)
		require.NoError(t, err)
		require.Equal(t, "A0", page.Content)
		payload, err := fixture.service.PinnedPayload(
			fixture.ctx,
			principal,
			fixture.scope,
			receipt.ReleaseID,
			"a",
		)
		require.NoError(t, err)
		require.JSONEq(t, `{"slug":"a","v":0}`, string(payload))
		search, err := fixture.service.MinimalSearch(
			fixture.ctx,
			principal,
			fixture.scope,
			receipt.ReleaseID,
			"",
		)
		require.NoError(t, err)
		require.Equal(t, []string{"a", "b", "c"}, releaseSlugs(search))
	}

	delete(fixture.access.allowed, fixture.principal1.ID)
	_, err = fixture.service.Current(fixture.ctx, fixture.principal1, fixture.scope)
	require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
	_, err = fixture.service.PinnedPage(
		fixture.ctx,
		fixture.principal1,
		fixture.scope,
		receipt.ReleaseID,
		"a",
	)
	require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
	_, err = fixture.service.PinnedPayload(
		fixture.ctx,
		fixture.principal1,
		fixture.scope,
		receipt.ReleaseID,
		"a",
	)
	require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
	_, err = fixture.service.MinimalSearch(
		fixture.ctx,
		fixture.principal1,
		fixture.scope,
		receipt.ReleaseID,
		"",
	)
	require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)

	current, err := fixture.service.Current(fixture.ctx, fixture.principal2, fixture.scope)
	require.NoError(t, err)
	require.Equal(t, receipt.ReleaseID, current.ReleaseID)
	search, err := fixture.service.MinimalSearch(
		fixture.ctx,
		fixture.principal2,
		fixture.scope,
		receipt.ReleaseID,
		"",
	)
	require.NoError(t, err)
	require.Equal(t, []string{"a", "b", "c"}, releaseSlugs(search))

	_, err = fixture.service.Current(
		fixture.ctx,
		types.WikiReleasePrincipal{},
		fixture.scope,
	)
	require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
	driftedScope := fixture.scope
	driftedScope.SpaceID = "space-2"
	_, err = fixture.service.Current(
		fixture.ctx,
		fixture.principal2,
		driftedScope,
	)
	require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
}

func TestWikiReleaseFalsificationPostgresConcurrency(t *testing.T) {
	dsn := strings.TrimSpace(os.Getenv("WEKNORA_TEST_POSTGRES_URL"))
	if dsn == "" {
		t.Skip("WEKNORA_TEST_POSTGRES_URL is required for PostgreSQL concurrency evidence")
	}

	db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{})
	require.NoError(t, err)
	sqlDB, err := db.DB()
	require.NoError(t, err)
	sqlDB.SetMaxOpenConns(8)
	sqlDB.SetMaxIdleConns(8)
	require.GreaterOrEqual(t, sqlDB.Stats().MaxOpenConnections, 4)
	require.NoError(t, sqlDB.PingContext(context.Background()))
	t.Cleanup(func() {
		require.NoError(t, sqlDB.Close())
	})

	for _, model := range []any{
		&types.WikiReleasePreparation{},
		&types.WikiRelease{},
		&types.WikiReleaseMember{},
		&types.WikiReleaseHead{},
		&types.WikiReleaseReceipt{},
	} {
		require.True(t, db.Migrator().HasTable(model), "000002 release table is not migrated: %T", model)
	}

	t.Run("same R0 base admits exactly one candidate", func(t *testing.T) {
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		scope := types.WikiReleaseScope{
			TenantID: 9_460_001,
			SpaceID:  "s0r-pg-concurrent",
			RawKBID:  "s0r-pg-concurrent-raw",
			WikiKBID: "s0r-pg-concurrent-wiki",
		}
		require.NoError(t, cleanupPostgresWikiReleaseScope(ctx, db, scope))
		t.Cleanup(func() {
			require.NoError(t, cleanupPostgresWikiReleaseScope(context.Background(), db, scope))
		})
		fixture := newPostgresWikiReleaseFixture(db, ctx, scope)

		r0Preparation := fixture.prepare(
			t,
			"preparation-r0",
			"candidate-r0",
			"",
			0,
			r0WikiReleaseMembers(),
		)
		r0Receipt, err := fixture.activate(t, fixture.service, r0Preparation, "nonce-r0")
		require.NoError(t, err)

		candidateA := fixture.prepare(
			t,
			"preparation-candidate-a",
			"candidate-a",
			r0Receipt.ReleaseID,
			r0Receipt.ActivationEpoch,
			r1WikiReleaseMembers(),
		)
		candidateBMembers := []types.WikiReleaseMemberSnapshot{
			{LogicalSlug: "a", RevisionID: "a2", MemberDigest: "digest-a2", Title: "A", Content: "A2", Payload: json.RawMessage(`{"slug":"a","v":2}`)},
			{LogicalSlug: "c", RevisionID: "c0", MemberDigest: "digest-c0", Title: "C", Content: "C0", Payload: json.RawMessage(`{"slug":"c","v":0}`)},
			{LogicalSlug: "e", RevisionID: "e0", MemberDigest: "digest-e0", Title: "E", Content: "E0", Payload: json.RawMessage(`{"slug":"e","v":0}`)},
		}
		candidateB := fixture.prepare(
			t,
			"preparation-candidate-b",
			"candidate-b",
			r0Receipt.ReleaseID,
			r0Receipt.ActivationEpoch,
			candidateBMembers,
		)

		candidates := []struct {
			preparation   *types.WikiReleasePreparation
			nonce         string
			authorization []byte
		}{
			{
				preparation: candidateA,
				nonce:       "nonce-candidate-a",
				authorization: signWikiReleaseAuthorization(
					t,
					fixture.privateKey,
					candidateA,
					"nonce-candidate-a",
					2_000,
				),
			},
			{
				preparation: candidateB,
				nonce:       "nonce-candidate-b",
				authorization: signWikiReleaseAuthorization(
					t,
					fixture.privateKey,
					candidateB,
					"nonce-candidate-b",
					2_000,
				),
			},
		}
		var casArrivals atomic.Uint32
		bothAtCAS := make(chan struct{})
		releaseCandidates := make(chan struct{})
		candidatesReleased := false
		defer func() {
			if !candidatesReleased {
				close(releaseCandidates)
			}
		}()
		concurrentService := fixture.serviceWithFaults(WikiReleaseFaults{
			CAS: func() error {
				if casArrivals.Add(1) == uint32(len(candidates)) {
					close(bothAtCAS)
				}
				select {
				case <-releaseCandidates:
					return nil
				case <-ctx.Done():
					return ctx.Err()
				}
			},
		})
		start := make(chan struct{})
		results := make(chan postgresWikiReleaseActivationResult, len(candidates))
		for _, candidate := range candidates {
			candidate := candidate
			go func() {
				<-start
				receipt, activateErr := concurrentService.Activate(
					ctx,
					fixture.principal,
					candidate.authorization,
				)
				results <- postgresWikiReleaseActivationResult{
					preparation: candidate.preparation,
					nonce:       candidate.nonce,
					receipt:     receipt,
					err:         activateErr,
				}
			}()
		}
		close(start)
		select {
		case <-bothAtCAS:
		case <-ctx.Done():
			require.FailNow(t, "both activations did not reach the CAS barrier", ctx.Err().Error())
		}
		close(releaseCandidates)
		candidatesReleased = true

		var winner postgresWikiReleaseActivationResult
		var loser postgresWikiReleaseActivationResult
		successes := 0
		conflicts := 0
		for range candidates {
			result := <-results
			if result.err == nil {
				successes++
				winner = result
				continue
			}
			var conflict *WikiReleaseConflictError
			if errors.As(result.err, &conflict) {
				conflicts++
				loser = result
			}
		}
		require.Equal(t, 1, successes)
		require.Equal(t, 1, conflicts)
		require.NotNil(t, winner.receipt)
		require.Nil(t, loser.receipt)

		current, err := fixture.service.Current(ctx, fixture.principal, scope)
		require.NoError(t, err)
		require.Equal(t, winner.receipt.ReleaseID, current.ReleaseID)
		require.Equal(t, uint64(2), current.ActivationEpoch)

		state, err := countPostgresWikiReleaseScope(ctx, db, scope)
		require.NoError(t, err)
		require.Equal(t, types.WikiReleaseStateCount{
			Preparations: 3,
			Releases:     2,
			Members:      6,
			Heads:        1,
			Receipts:     2,
		}, state)

		var loserReleases int64
		require.NoError(t, postgresWikiReleaseScopeQuery(
			db.WithContext(ctx).Model(&types.WikiRelease{}),
			scope,
		).Where("preparation_id = ?", loser.preparation.ID).Count(&loserReleases).Error)
		require.Zero(t, loserReleases)

		var loserMembers int64
		require.NoError(t, db.WithContext(ctx).
			Table("wiki_release_members AS member").
			Joins("JOIN wiki_releases AS release ON release.release_id = member.release_id").
			Where(
				"release.tenant_id = ? AND release.space_id = ? AND release.raw_kb_id = ? AND release.wiki_kb_id = ? AND release.preparation_id = ?",
				scope.TenantID,
				scope.SpaceID,
				scope.RawKBID,
				scope.WikiKBID,
				loser.preparation.ID,
			).
			Count(&loserMembers).Error)
		require.Zero(t, loserMembers)

		var loserReceipts int64
		require.NoError(t, postgresWikiReleaseScopeQuery(
			db.WithContext(ctx).Model(&types.WikiReleaseReceipt{}),
			scope,
		).Where("nonce = ?", loser.nonce).Count(&loserReceipts).Error)
		require.Zero(t, loserReceipts)
	})

	t.Run("blocked CAS serves complete R0 then complete R1", func(t *testing.T) {
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		scope := types.WikiReleaseScope{
			TenantID: 9_460_002,
			SpaceID:  "s0r-pg-pinned",
			RawKBID:  "s0r-pg-pinned-raw",
			WikiKBID: "s0r-pg-pinned-wiki",
		}
		require.NoError(t, cleanupPostgresWikiReleaseScope(ctx, db, scope))
		t.Cleanup(func() {
			require.NoError(t, cleanupPostgresWikiReleaseScope(context.Background(), db, scope))
		})
		fixture := newPostgresWikiReleaseFixture(db, ctx, scope)

		r0Preparation := fixture.prepare(
			t,
			"preparation-r0",
			"candidate-r0",
			"",
			0,
			r0WikiReleaseMembers(),
		)
		r0Receipt, err := fixture.activate(t, fixture.service, r0Preparation, "nonce-r0")
		require.NoError(t, err)
		r1Preparation := fixture.prepare(
			t,
			"preparation-r1",
			"candidate-r1",
			r0Receipt.ReleaseID,
			r0Receipt.ActivationEpoch,
			r1WikiReleaseMembers(),
		)

		casEntered := make(chan struct{})
		releaseCAS := make(chan struct{})
		casReleased := false
		defer func() {
			if !casReleased {
				close(releaseCAS)
			}
		}()
		blockedService := fixture.serviceWithFaults(WikiReleaseFaults{
			CAS: func() error {
				close(casEntered)
				select {
				case <-releaseCAS:
					return nil
				case <-ctx.Done():
					return ctx.Err()
				}
			},
		})
		r1Authorization := signWikiReleaseAuthorization(
			t,
			fixture.privateKey,
			r1Preparation,
			"nonce-r1",
			2_000,
		)
		activationDone := make(chan postgresWikiReleaseActivationResult, 1)
		go func() {
			receipt, activateErr := blockedService.Activate(
				ctx,
				fixture.principal,
				r1Authorization,
			)
			activationDone <- postgresWikiReleaseActivationResult{receipt: receipt, err: activateErr}
		}()

		select {
		case <-casEntered:
		case <-ctx.Done():
			require.FailNow(t, "activation did not reach the CAS barrier", ctx.Err().Error())
		}

		current, err := fixture.service.Current(ctx, fixture.principal, scope)
		require.NoError(t, err)
		require.Equal(t, r0Receipt.ReleaseID, current.ReleaseID)
		require.Equal(t, uint64(1), current.ActivationEpoch)
		page, err := fixture.service.PinnedPage(ctx, fixture.principal, scope, current.ReleaseID, "a")
		require.NoError(t, err)
		require.Equal(t, "A0", page.Content)
		payload, err := fixture.service.PinnedPayload(ctx, fixture.principal, scope, current.ReleaseID, "a")
		require.NoError(t, err)
		require.JSONEq(t, `{"slug":"a","v":0}`, string(payload))
		search, err := fixture.service.MinimalSearch(ctx, fixture.principal, scope, current.ReleaseID, "")
		require.NoError(t, err)
		require.Equal(t, []string{"a", "b", "c"}, releaseSlugs(search))

		close(releaseCAS)
		casReleased = true
		var activation postgresWikiReleaseActivationResult
		select {
		case activation = <-activationDone:
		case <-ctx.Done():
			require.FailNow(t, "activation did not leave the CAS barrier", ctx.Err().Error())
		}
		require.NoError(t, activation.err)
		require.NotNil(t, activation.receipt)

		current, err = fixture.service.Current(ctx, fixture.principal, scope)
		require.NoError(t, err)
		require.Equal(t, activation.receipt.ReleaseID, current.ReleaseID)
		require.Equal(t, uint64(2), current.ActivationEpoch)
		page, err = fixture.service.PinnedPage(ctx, fixture.principal, scope, current.ReleaseID, "a")
		require.NoError(t, err)
		require.Equal(t, "A1", page.Content)
		_, err = fixture.service.PinnedPage(ctx, fixture.principal, scope, current.ReleaseID, "b")
		require.ErrorIs(t, err, ErrWikiReleaseNotFound)
		payload, err = fixture.service.PinnedPayload(ctx, fixture.principal, scope, current.ReleaseID, "a")
		require.NoError(t, err)
		require.JSONEq(t, `{"slug":"a","v":1}`, string(payload))
		search, err = fixture.service.MinimalSearch(ctx, fixture.principal, scope, current.ReleaseID, "")
		require.NoError(t, err)
		require.Equal(t, []string{"a", "c", "d"}, releaseSlugs(search))
	})
}

type postgresWikiReleaseActivationResult struct {
	preparation *types.WikiReleasePreparation
	nonce       string
	receipt     *types.WikiReleaseReceipt
	err         error
}

type postgresWikiReleaseFixture struct {
	ctx        context.Context
	repo       *wikirepository.WikiReleaseRepository
	service    *WikiReleaseService
	scope      types.WikiReleaseScope
	principal  types.WikiReleasePrincipal
	access     *mutableWikiReleaseAccessVerifier
	privateKey ed25519.PrivateKey
	ids        atomic.Uint64
}

func newPostgresWikiReleaseFixture(
	db *gorm.DB,
	ctx context.Context,
	scope types.WikiReleaseScope,
) *postgresWikiReleaseFixture {
	principal := types.WikiReleasePrincipal{
		ID:       "postgres-principal",
		TenantID: scope.TenantID,
		SpaceID:  scope.SpaceID,
	}
	fixture := &postgresWikiReleaseFixture{
		ctx:       ctx,
		repo:      wikirepository.NewWikiReleaseRepository(db),
		scope:     scope,
		principal: principal,
		access: &mutableWikiReleaseAccessVerifier{
			allowed: map[string]types.WikiReleaseScope{principal.ID: scope},
		},
		privateKey: ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x46}, ed25519.SeedSize)),
	}
	fixture.service = fixture.serviceWithFaults(WikiReleaseFaults{})
	return fixture
}

func (fixture *postgresWikiReleaseFixture) serviceWithFaults(
	faults WikiReleaseFaults,
) *WikiReleaseService {
	return NewWikiReleaseService(
		fixture.repo,
		fixture.access,
		NewEd25519WikiReleaseAuthorizationVerifier(map[string]ed25519.PublicKey{
			"signer-1": fixture.privateKey.Public().(ed25519.PublicKey),
		}),
		WikiReleaseServiceOptions{
			Now: func() time.Time { return time.Unix(1_000, 0).UTC() },
			NewID: func(kind string) string {
				id := fixture.ids.Add(1)
				return fmt.Sprintf("%s-%s-%d", kind, fixture.scope.SpaceID, id)
			},
			Faults: faults,
		},
	)
}

func (fixture *postgresWikiReleaseFixture) prepare(
	t *testing.T,
	id string,
	candidate string,
	expectedReleaseID string,
	expectedEpoch uint64,
	members []types.WikiReleaseMemberSnapshot,
) *types.WikiReleasePreparation {
	t.Helper()
	preparation, err := fixture.service.Prepare(
		fixture.ctx,
		fixture.principal,
		&types.WikiReleasePreparation{
			ID:                      fixture.scope.SpaceID + "-" + id,
			WikiReleaseScope:        fixture.scope,
			CandidateDigest:         candidate,
			ReadyReceiptDigest:      "ready-" + id,
			ReviewDecisionDigest:    "review-" + id,
			ReviewPolicyID:          "policy-1",
			ExpectedReleaseID:       expectedReleaseID,
			ExpectedActivationEpoch: expectedEpoch,
			Members:                 members,
		},
	)
	require.NoError(t, err)
	return preparation
}

func (fixture *postgresWikiReleaseFixture) activate(
	t *testing.T,
	service *WikiReleaseService,
	preparation *types.WikiReleasePreparation,
	nonce string,
) (*types.WikiReleaseReceipt, error) {
	t.Helper()
	return service.Activate(
		fixture.ctx,
		fixture.principal,
		signWikiReleaseAuthorization(t, fixture.privateKey, preparation, nonce, 2_000),
	)
}

func cleanupPostgresWikiReleaseScope(
	ctx context.Context,
	db *gorm.DB,
	scope types.WikiReleaseScope,
) error {
	return db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		for _, statement := range []string{
			"DELETE FROM wiki_release_receipts WHERE tenant_id = ? AND space_id = ? AND raw_kb_id = ? AND wiki_kb_id = ?",
			"DELETE FROM wiki_release_heads WHERE tenant_id = ? AND space_id = ? AND raw_kb_id = ? AND wiki_kb_id = ?",
			`DELETE FROM wiki_release_members WHERE release_id IN (
				SELECT release_id FROM wiki_releases
				WHERE tenant_id = ? AND space_id = ? AND raw_kb_id = ? AND wiki_kb_id = ?
			)`,
			"DELETE FROM wiki_releases WHERE tenant_id = ? AND space_id = ? AND raw_kb_id = ? AND wiki_kb_id = ?",
			"DELETE FROM wiki_release_preparations WHERE tenant_id = ? AND space_id = ? AND raw_kb_id = ? AND wiki_kb_id = ?",
		} {
			if err := tx.Exec(
				statement,
				scope.TenantID,
				scope.SpaceID,
				scope.RawKBID,
				scope.WikiKBID,
			).Error; err != nil {
				return err
			}
		}
		return nil
	})
}

func postgresWikiReleaseScopeQuery(
	db *gorm.DB,
	scope types.WikiReleaseScope,
) *gorm.DB {
	return db.Where(
		"tenant_id = ? AND space_id = ? AND raw_kb_id = ? AND wiki_kb_id = ?",
		scope.TenantID,
		scope.SpaceID,
		scope.RawKBID,
		scope.WikiKBID,
	)
}

func countPostgresWikiReleaseScope(
	ctx context.Context,
	db *gorm.DB,
	scope types.WikiReleaseScope,
) (types.WikiReleaseStateCount, error) {
	var state types.WikiReleaseStateCount
	counts := []struct {
		model any
		out   *int64
	}{
		{model: &types.WikiReleasePreparation{}, out: &state.Preparations},
		{model: &types.WikiRelease{}, out: &state.Releases},
		{model: &types.WikiReleaseHead{}, out: &state.Heads},
		{model: &types.WikiReleaseReceipt{}, out: &state.Receipts},
	}
	for _, count := range counts {
		if err := postgresWikiReleaseScopeQuery(
			db.WithContext(ctx).Model(count.model),
			scope,
		).Count(count.out).Error; err != nil {
			return types.WikiReleaseStateCount{}, err
		}
	}
	if err := db.WithContext(ctx).
		Table("wiki_release_members AS member").
		Joins("JOIN wiki_releases AS release ON release.release_id = member.release_id").
		Where(
			"release.tenant_id = ? AND release.space_id = ? AND release.raw_kb_id = ? AND release.wiki_kb_id = ?",
			scope.TenantID,
			scope.SpaceID,
			scope.RawKBID,
			scope.WikiKBID,
		).
		Count(&state.Members).Error; err != nil {
		return types.WikiReleaseStateCount{}, err
	}
	return state, nil
}

func signWikiReleaseAuthorization(
	t *testing.T,
	privateKey ed25519.PrivateKey,
	preparation *types.WikiReleasePreparation,
	nonce string,
	expiresAt int64,
) []byte {
	t.Helper()
	authorization := &types.PublishAuthorizationV0{
		Version:                 "0",
		Action:                  "activate",
		PreparationID:           preparation.ID,
		CandidateDigest:         preparation.CandidateDigest,
		ManifestDigest:          preparation.ManifestDigest,
		ReadyReceiptDigest:      preparation.ReadyReceiptDigest,
		ReviewDecisionDigest:    preparation.ReviewDecisionDigest,
		ReviewPolicyID:          preparation.ReviewPolicyID,
		TenantID:                preparation.TenantID,
		SpaceID:                 preparation.SpaceID,
		RawKBID:                 preparation.RawKBID,
		WikiKBID:                preparation.WikiKBID,
		ExpectedReleaseID:       preparation.ExpectedReleaseID,
		ExpectedActivationEpoch: preparation.ExpectedActivationEpoch,
		ExpiresAt:               expiresAt,
		Nonce:                   nonce,
		SignerKeyID:             "signer-1",
	}
	signingBytes, err := CanonicalPublishAuthorizationV0(authorization, false)
	require.NoError(t, err)
	authorization.Signature = EncodeWikiReleaseSignature(ed25519.Sign(privateKey, signingBytes))
	raw, err := CanonicalPublishAuthorizationV0(authorization, true)
	require.NoError(t, err)
	return raw
}

func releaseSlugs(members []types.WikiReleaseMemberSnapshot) []string {
	slugs := make([]string, 0, len(members))
	for _, member := range members {
		slugs = append(slugs, member.LogicalSlug)
	}
	return slugs
}
