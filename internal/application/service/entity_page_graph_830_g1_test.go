package service

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

type entityPageGraphReleaseSource830G1Spy struct {
	current          EntityPageGraphReleaseSnapshot830G1
	pinned           EntityPageGraphReleaseSnapshot830G1
	currentErr       error
	pinnedErr        error
	currentCalls     int
	pinnedCalls      int
	pinnedRelease    []string
	preparation      EntityPageGraphReleaseSnapshot830G1
	preparationErr   error
	preparationCalls int
	preparationIDs   []string
}

func (s *entityPageGraphReleaseSource830G1Spy) LoadPreparationEntityPageGraph830G1(
	_ context.Context,
	_ types.WikiReleasePrincipal,
	_ types.WikiReleaseScope,
	preparationID string,
) (EntityPageGraphReleaseSnapshot830G1, error) {
	s.preparationCalls++
	s.preparationIDs = append(s.preparationIDs, preparationID)
	return s.preparation, s.preparationErr
}

func (s *entityPageGraphReleaseSource830G1Spy) LoadCurrentEntityPageGraphRelease830G1(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
) (EntityPageGraphReleaseSnapshot830G1, error) {
	s.currentCalls++
	return s.current, s.currentErr
}

func (s *entityPageGraphReleaseSource830G1Spy) LoadPinnedEntityPageGraphRelease830G1(
	_ context.Context,
	_ types.WikiReleasePrincipal,
	_ types.WikiReleaseScope,
	releaseID string,
) (EntityPageGraphReleaseSnapshot830G1, error) {
	s.pinnedCalls++
	s.pinnedRelease = append(s.pinnedRelease, releaseID)
	return s.pinned, s.pinnedErr
}

func entityPageGraphReleaseFixture830G1(t *testing.T) EntityPageGraphReleaseSnapshot830G1 {
	t.Helper()
	raw := loadEntityPageGraph830G1ServiceVector(t)
	manifest, err := types.ParseEntityPageManifest830G1(raw)
	require.NoError(t, err)
	members := make([]types.WikiReleaseMemberSnapshot, 0, len(manifest.Members))
	for _, member := range manifest.Members {
		members = append(members, types.WikiReleaseMemberSnapshot{
			Kind: member.PageKind, LogicalSlug: member.PageID,
			RevisionID: member.PayloadSHA256, MemberDigest: member.MemberDigest,
			Title: member.ShortTitle, Content: "", Payload: append(json.RawMessage(nil), member.Payload...),
		})
	}
	return EntityPageGraphReleaseSnapshot830G1{
		ReleaseID: manifest.ReleaseID, ActivationEpoch: manifest.ActivationEpoch,
		Manifest: append(json.RawMessage(nil), raw...), Members: members,
	}
}

func loadEntityPageGraph830G1ServiceVector(t *testing.T) []byte {
	t.Helper()
	return readServiceTestFile(t, "../../../harness/tests/fixtures/entity_page_graph_830_g1_contract_vector.json")
}

func TestEntityPageGraphService830G1CurrentPinsOnceAndPinnedNeverFallsBack(t *testing.T) {
	t.Parallel()
	snapshot := entityPageGraphReleaseFixture830G1(t)
	selector := EntityPageGraphSelector830G1{
		EntityID: "ping-an-e-sheng-bao", PageKind: "field", StableKey: "cooling_off_period",
	}
	principal := types.WikiReleasePrincipal{ID: "viewer", TenantID: 7, SpaceID: snapshotManifestSpace(t, snapshot)}
	scope := types.WikiReleaseScope{
		TenantID: 7, SpaceID: principal.SpaceID, RawKBID: "raw-596-1", WikiKBID: "8d5695de-f255-42d5-9a41-042ba86e97b9",
	}

	t.Run("current observes the head-backed source once", func(t *testing.T) {
		spy := &entityPageGraphReleaseSource830G1Spy{current: snapshot}
		result, err := NewEntityPageGraphService830G1(spy).ReadCurrentEntityPage830G1(
			context.Background(), principal, scope, selector,
		)
		require.NoError(t, err)
		require.Equal(t, "current", result.ReadMode)
		require.Equal(t, snapshot.ReleaseID, result.ReleaseID)
		require.Equal(t, 1, spy.currentCalls)
		require.Zero(t, spy.pinnedCalls)
	})

	t.Run("explicit pinned reads only the requested release", func(t *testing.T) {
		spy := &entityPageGraphReleaseSource830G1Spy{pinned: snapshot}
		result, err := NewEntityPageGraphService830G1(spy).ReadPinnedEntityPage830G1(
			context.Background(), principal, scope, snapshot.ReleaseID, selector,
		)
		require.NoError(t, err)
		require.Equal(t, "pinned", result.ReadMode)
		require.Equal(t, []string{snapshot.ReleaseID}, spy.pinnedRelease)
		require.Zero(t, spy.currentCalls)
		require.Equal(t, 1, spy.pinnedCalls)
	})
}

func TestWikiReleaseCreateDraftUsesEmbeddedEntityPageManifestDigest830G1(t *testing.T) {
	t.Parallel()
	snapshot := entityPageGraphReleaseFixture830G1(t)
	manifest, err := types.ParseEntityPageManifest830G1(snapshot.Manifest)
	require.NoError(t, err)
	scope := types.WikiReleaseScope{
		TenantID: 7, SpaceID: manifest.SpaceID, RawKBID: "raw-596-1", WikiKBID: manifest.WikiKBID,
	}
	principal := types.WikiReleasePrincipal{ID: "reviewer", TenantID: scope.TenantID, SpaceID: scope.SpaceID}
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)

	draft, err := fixture.authority.createDraft(
		fixture.ctx,
		principal,
		&types.WikiReleasePreparation{
			ID: "preparation-g1-manifest-digest", WikiReleaseScope: scope,
			CandidateDigest:    manifest.InputAuthority.CandidateSHA256,
			ReadyReceiptDigest: strings.Repeat("a", 64), ReviewPolicyID: strings.Repeat("b", 64),
			Manifest: append(json.RawMessage(nil), snapshot.Manifest...), Members: snapshot.Members,
		},
	)
	require.NoError(t, err)
	require.Equal(t, manifest.ManifestSHA256, draft.ManifestDigest)
	require.NotEqual(t, digestWikiReleaseBytes(snapshot.Manifest), draft.ManifestDigest,
		"the frozen embedded manifest hash, not the transport bytes hash, is G1 custody authority")
}

func TestEntityPageGraphPreparation830G1ReadsDraftAndReadyPageKindsWithExactHeadBindingAndEmptyContent(t *testing.T) {
	t.Parallel()
	snapshot := entityPageGraphReleaseFixture830G1(t)
	manifest, err := types.ParseEntityPageManifest830G1(snapshot.Manifest)
	require.NoError(t, err)
	scope := types.WikiReleaseScope{
		TenantID: 7, SpaceID: manifest.SpaceID, RawKBID: "raw-596-1", WikiKBID: manifest.WikiKBID,
	}
	principal := types.WikiReleasePrincipal{ID: "reviewer", TenantID: scope.TenantID, SpaceID: scope.SpaceID}
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	require.NoError(t, fixture.db.Create(&types.WikiReleaseHead{
		ID: "head-g1", WikiReleaseScope: scope, ActiveReleaseID: manifest.ReleaseID,
		ActivationEpoch: manifest.ActivationEpoch, UpdatedAt: time.Now().UTC(),
	}).Error)
	draft, err := fixture.authority.createDraft(fixture.ctx, principal, &types.WikiReleasePreparation{
		ID: "preparation-g1-preview", WikiReleaseScope: scope,
		CandidateDigest:    manifest.InputAuthority.CandidateSHA256,
		ReadyReceiptDigest: strings.Repeat("a", 64), ReviewPolicyID: strings.Repeat("b", 64),
		Manifest: append(json.RawMessage(nil), snapshot.Manifest...), Members: snapshot.Members,
	})
	require.NoError(t, err)
	require.Equal(t, manifest.ReleaseID, draft.ExpectedReleaseID)
	require.Equal(t, manifest.ActivationEpoch, draft.ExpectedActivationEpoch)

	selectors := []EntityPageGraphSelector830G1{
		{EntityID: manifest.EntityID, PageKind: "overview", StableKey: "overview"},
		{EntityID: manifest.EntityID, PageKind: "section", StableKey: "application-and-contract"},
		{EntityID: manifest.EntityID, PageKind: "field", StableKey: "insured_eligibility"},
		{EntityID: manifest.EntityID, PageKind: "free_wiki", StableKey: "free-wiki"},
	}
	assertReads := func(status string) {
		t.Helper()
		for _, selector := range selectors {
			t.Run(status+"/"+selector.PageKind, func(t *testing.T) {
				read, readErr := NewEntityPageGraphService830G1(fixture.adapter).
					ReadPreparationEntityPage830G1(
						fixture.ctx, principal, scope, draft.ID, selector,
					)
				require.NoError(t, readErr)
				require.Equal(t, "preparation", read.ReadMode)
				require.Equal(t, draft.ID, read.PreparationID)
				require.Equal(t, manifest.ReleaseID, read.ReleaseID)
				require.Equal(t, manifest.ActivationEpoch, read.ActivationEpoch)
				require.Equal(t, selector.PageKind, read.Member.PageKind)
				require.Equal(t, selector.StableKey, read.Member.StableKey)
			})
		}
	}
	assertReads(types.WikiReleasePreparationDraft)
	for _, member := range draft.Members {
		require.Empty(t, member.Content)
	}
	ready := reviewEntityPageGraphPreparation830G1(t, fixture, principal, scope, draft)
	validatedManifest, validatedMembers, err := validateEntityPageGraphPreparation830G1(
		ready, types.WikiReleasePreparationReady, scope,
	)
	require.NoError(t, err)
	require.Equal(t, manifest.ManifestSHA256, validatedManifest.ManifestSHA256)
	require.Len(t, validatedMembers, 76)
	assertReads(types.WikiReleasePreparationReady)
}

func TestReviewSchemaDraftPromotesEntityPageGraphPreparation830G1(t *testing.T) {
	t.Parallel()
	snapshot := entityPageGraphReleaseFixture830G1(t)
	manifest, err := types.ParseEntityPageManifest830G1(snapshot.Manifest)
	require.NoError(t, err)
	scope := types.WikiReleaseScope{
		TenantID: 7, SpaceID: manifest.SpaceID, RawKBID: "raw-596-1", WikiKBID: manifest.WikiKBID,
	}
	principal := types.WikiReleasePrincipal{ID: "reviewer", TenantID: scope.TenantID, SpaceID: scope.SpaceID}
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	require.NoError(t, fixture.db.Create(&types.WikiReleaseHead{
		ID: "head-g1-review", WikiReleaseScope: scope, ActiveReleaseID: manifest.ReleaseID,
		ActivationEpoch: manifest.ActivationEpoch, UpdatedAt: time.Now().UTC(),
	}).Error)
	draft, err := fixture.authority.createDraft(fixture.ctx, principal, &types.WikiReleasePreparation{
		ID: "preparation-g1-review", WikiReleaseScope: scope,
		CandidateDigest:    manifest.InputAuthority.CandidateSHA256,
		ReadyReceiptDigest: strings.Repeat("a", 64), ReviewPolicyID: strings.Repeat("b", 64),
		Manifest: append(json.RawMessage(nil), snapshot.Manifest...), Members: snapshot.Members,
	})
	require.NoError(t, err)
	ready := reviewEntityPageGraphPreparation830G1(t, fixture, principal, scope, draft)
	require.Equal(t, draft.ID, ready.ID)
	require.Equal(t, types.WikiReleasePreparationReady, ready.Status)
	_, _, err = validateEntityPageGraphPreparation830G1(
		ready, types.WikiReleasePreparationReady, scope,
	)
	require.NoError(t, err)
}

func reviewEntityPageGraphPreparation830G1(
	t *testing.T,
	fixture *schemaWikiPrepareFixture,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	draft *types.WikiReleasePreparation,
) *types.WikiReleasePreparation {
	t.Helper()
	decision := types.HumanBatchDecisionReceiptV1{
		Version: "1", Decision: "approve", PrincipalID: principal.ID, WikiReleaseScope: scope,
		CandidateHash: draft.CandidateDigest, HumanBatchHash: draft.ReadyReceiptDigest,
		ReviewPolicyHash: draft.ReviewPolicyID,
		IssuedAt:         time.Now().Add(-time.Minute).Unix(), ExpiresAt: time.Now().Add(time.Hour).Unix(),
		Nonce: "entity-page-graph-review-830-g1", SignerKeyID: "named-human-review-key",
	}
	privateKey := ed25519.NewKeyFromSeed(schemaWikiReviewSeed[:])
	unsigned, err := CanonicalHumanBatchDecisionReceiptV1(&decision, false)
	require.NoError(t, err)
	decision.Signature = base64.RawURLEncoding.EncodeToString(ed25519.Sign(privateKey, unsigned))
	rawDecision, err := CanonicalHumanBatchDecisionReceiptV1(&decision, true)
	require.NoError(t, err)

	ready, err := fixture.adapter.ReviewSchemaDraft(
		fixture.ctx, principal, scope, draft.ID, rawDecision,
	)
	require.NoError(t, err)
	return ready
}

func TestCreateEntityPageGraphDraft830G1RequiresCurrentSourceReleaseCustodyBeforePersistence(t *testing.T) {
	t.Parallel()
	raw := loadEntityPageGraph830G1ServiceVector(t)
	manifest, err := types.ParseEntityPageManifest830G1(raw)
	require.NoError(t, err)
	scope := types.WikiReleaseScope{
		TenantID: 7, SpaceID: manifest.SpaceID, RawKBID: "raw-596-1", WikiKBID: manifest.WikiKBID,
	}
	principal := types.WikiReleasePrincipal{ID: "reviewer", TenantID: scope.TenantID, SpaceID: scope.SpaceID}
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	require.NoError(t, fixture.db.Create(&types.WikiReleaseHead{
		ID: "head-g1-without-source", WikiReleaseScope: scope,
		ActiveReleaseID: manifest.ReleaseID, ActivationEpoch: manifest.ActivationEpoch,
		UpdatedAt: time.Now().UTC(),
	}).Error)

	draft, err := fixture.adapter.CreateEntityPageGraphDraft830G1(
		fixture.ctx, principal, scope, "preparation-g1-no-source", raw,
	)
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
	require.Nil(t, draft)
	require.Zero(t, fixture.storedCount(t))
}

func TestCreateEntityPageGraphDraft830G1RejectsHeadDriftBeforePersistenceAndKeepsIDRetryable(t *testing.T) {
	snapshot := entityPageGraphReleaseFixture830G1(t)
	manifest, err := types.ParseEntityPageManifest830G1(snapshot.Manifest)
	require.NoError(t, err)
	scope := types.WikiReleaseScope{
		TenantID: 7, SpaceID: manifest.SpaceID, RawKBID: "raw-596-1", WikiKBID: manifest.WikiKBID,
	}
	principal := types.WikiReleasePrincipal{ID: "reviewer", TenantID: scope.TenantID, SpaceID: scope.SpaceID}
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	require.NoError(t, fixture.db.Create(&types.WikiReleaseHead{
		ID: "head-after-815-replay", WikiReleaseScope: scope,
		ActiveReleaseID: "release-after-815", ActivationEpoch: manifest.ActivationEpoch + 1,
		UpdatedAt: time.Now().UTC(),
	}).Error)
	input := &types.WikiReleasePreparation{
		ID: "preparation-g1-head-drift", WikiReleaseScope: scope,
		CandidateDigest:    manifest.InputAuthority.CandidateSHA256,
		ReadyReceiptDigest: strings.Repeat("a", 64), ReviewPolicyID: strings.Repeat("b", 64),
		ExpectedReleaseID: manifest.ReleaseID, ExpectedActivationEpoch: manifest.ActivationEpoch,
		Manifest: append(json.RawMessage(nil), snapshot.Manifest...), Members: snapshot.Members,
	}

	// The expected tuple above is the exact result frozen by the successful
	// current-815 replay. Head has moved before the G1 Draft persistence edge.
	draft, err := fixture.authority.createDraftWithExpectedHead(
		fixture.ctx, principal, input, manifest.ReleaseID, manifest.ActivationEpoch,
	)

	require.ErrorIs(t, err, wikirepository.ErrWikiReleaseConflict)
	require.Nil(t, draft)
	require.Zero(t, fixture.storedCount(t))

	require.NoError(t, fixture.db.Model(&types.WikiReleaseHead{}).
		Where("id = ?", "head-after-815-replay").
		Updates(map[string]any{
			"active_release_id": manifest.ReleaseID, "activation_epoch": manifest.ActivationEpoch,
		}).Error)
	retry, err := fixture.authority.createDraftWithExpectedHead(
		fixture.ctx, principal, input, manifest.ReleaseID, manifest.ActivationEpoch,
	)
	require.NoError(t, err)
	require.NotNil(t, retry)
	require.Equal(t, input.ID, retry.ID)
}

func TestCreateEntityPageGraphDraft830G1RejectsUnreadablePreparationIDsBeforeRepositoryAccess(t *testing.T) {
	t.Parallel()
	raw := loadEntityPageGraph830G1ServiceVector(t)
	manifest, err := types.ParseEntityPageManifest830G1(raw)
	require.NoError(t, err)
	scope := types.WikiReleaseScope{
		TenantID: 7, SpaceID: manifest.SpaceID, RawKBID: "raw-596-1", WikiKBID: manifest.WikiKBID,
	}
	principal := types.WikiReleasePrincipal{ID: "reviewer", TenantID: scope.TenantID, SpaceID: scope.SpaceID}
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	queryCount := 0
	require.NoError(t, fixture.db.Callback().Query().Before("gorm:query").Register(
		"test:count-invalid-g1-preparation-id-queries",
		func(*gorm.DB) { queryCount++ },
	))

	for _, preparationID := range []string{"", " ", "current", "CURRENT", "latest", "LaTeSt"} {
		t.Run(preparationID, func(t *testing.T) {
			before := queryCount
			draft, err := fixture.adapter.CreateEntityPageGraphDraft830G1(
				fixture.ctx, principal, scope, preparationID, raw,
			)
			require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
			require.Nil(t, draft)
			require.Equal(t, before, queryCount,
				"an unreadable preparation ID must fail closed before repository access")
		})
	}
	require.Zero(t, fixture.storedCount(t))
}

func TestEntityPageGraphService830G1PinnedFailuresAreTypedAndNeverFallback(t *testing.T) {
	t.Parallel()
	snapshot := entityPageGraphReleaseFixture830G1(t)
	selector := EntityPageGraphSelector830G1{
		EntityID: "ping-an-e-sheng-bao", PageKind: "overview", StableKey: "overview",
	}
	principal := types.WikiReleasePrincipal{ID: "viewer", TenantID: 7, SpaceID: snapshotManifestSpace(t, snapshot)}
	scope := types.WikiReleaseScope{
		TenantID: 7, SpaceID: principal.SpaceID, RawKBID: "raw-596-1", WikiKBID: "8d5695de-f255-42d5-9a41-042ba86e97b9",
	}

	for _, test := range []struct {
		name string
		err  error
		want error
	}{
		{name: "nonexistent", err: ErrEntityPageGraphNotFound830G1, want: ErrEntityPageGraphNotFound830G1},
		{name: "foreign", err: ErrEntityPageGraphForbidden830G1, want: ErrEntityPageGraphForbidden830G1},
	} {
		t.Run(test.name, func(t *testing.T) {
			spy := &entityPageGraphReleaseSource830G1Spy{pinnedErr: test.err}
			_, err := NewEntityPageGraphService830G1(spy).ReadPinnedEntityPage830G1(
				context.Background(), principal, scope, "release-missing", selector,
			)
			require.ErrorIs(t, err, test.want)
			require.Zero(t, spy.currentCalls)
			require.Equal(t, 1, spy.pinnedCalls)
		})
	}

	for _, alias := range []string{"current", "latest"} {
		t.Run("reserved alias "+alias, func(t *testing.T) {
			spy := &entityPageGraphReleaseSource830G1Spy{}
			_, err := NewEntityPageGraphService830G1(spy).ReadPinnedEntityPage830G1(
				context.Background(), principal, scope, alias, selector,
			)
			require.ErrorIs(t, err, ErrEntityPageGraphNotFound830G1)
			require.Zero(t, spy.currentCalls)
			require.Zero(t, spy.pinnedCalls)
		})
	}

	t.Run("incomplete graph", func(t *testing.T) {
		incomplete := snapshot
		incomplete.Members = append([]types.WikiReleaseMemberSnapshot(nil), snapshot.Members[:len(snapshot.Members)-1]...)
		spy := &entityPageGraphReleaseSource830G1Spy{pinned: incomplete}
		_, err := NewEntityPageGraphService830G1(spy).ReadPinnedEntityPage830G1(
			context.Background(), principal, scope, snapshot.ReleaseID, selector,
		)
		require.ErrorIs(t, err, ErrEntityPageGraphIntegrity830G1)
		require.Zero(t, spy.currentCalls)
		require.Equal(t, 1, spy.pinnedCalls)
	})
}

func TestSchemaWikiServiceLoadEntityPageGraphRelease830G1RejectsManifestCustodyDrift(t *testing.T) {
	rawManifest := bytes.TrimSpace(loadEntityPageGraph830G1ServiceVector(t))
	manifest, err := types.ParseEntityPageManifest830G1(rawManifest)
	require.NoError(t, err)
	snapshot := entityPageGraphReleaseFixture830G1(t)

	db, err := gorm.Open(sqlite.Open(
		"file:entity-page-graph-830-g1-manifest-drift?mode=memory&cache=shared",
	), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(
		&types.WikiReleasePreparation{}, &types.WikiRelease{}, &types.WikiReleaseMember{},
		&types.WikiReleaseHead{}, &types.WikiReleaseReceipt{},
	))
	repository := wikirepository.NewWikiReleaseRepository(db)
	scope := types.WikiReleaseScope{
		TenantID: 7, SpaceID: manifest.SpaceID, RawKBID: "raw-596-1", WikiKBID: manifest.WikiKBID,
	}
	principal := types.WikiReleasePrincipal{ID: "viewer", TenantID: 7, SpaceID: manifest.SpaceID}
	ctx := SealWikiReleaseAccess(context.Background(), principal, scope)
	releaseAuthority := NewWikiReleaseService(
		repository, NewContextWikiReleaseAccessVerifier(), nil, WikiReleaseServiceOptions{},
	)
	now := time.Unix(1_000, 0).UTC()
	manifestDigest := manifest.ManifestSHA256
	preparation := &types.WikiReleasePreparation{
		ID: "preparation-g1", WikiReleaseScope: scope,
		CandidateDigest: manifest.InputAuthority.CandidateSHA256, ManifestDigest: manifestDigest,
		ReadyReceiptDigest: "ready-g1", ReviewDecisionDigest: "review-g1", ReviewPolicyID: "policy-g1",
		Status:   types.WikiReleasePreparationReady,
		Manifest: append(json.RawMessage(nil), rawManifest...), Members: snapshot.Members, CreatedAt: now,
	}
	preparation.PreparationDigest = digestWikiReleasePreparation(preparation)
	release := &types.WikiRelease{
		ID: manifest.ReleaseID, WikiReleaseScope: scope,
		CandidateDigest: preparation.CandidateDigest, ManifestDigest: manifestDigest,
		PreparationID: preparation.ID, CreatedAt: now, ActivatedAt: now,
	}
	_, err = repository.Activate(ctx, wikirepository.WikiReleaseActivationWrite{
		Preparation: preparation, Release: release, Members: snapshot.Members,
		Nonce: "nonce-g1", AuthorizationDigest: "authorization-g1", ActivatedBy: principal.ID,
		ActivatedAt: now, ActivationReceiptID: "receipt-g1",
		ExpectedPreparationID: preparation.ID, ExpectedPreparationDigest: preparation.PreparationDigest,
	})
	require.NoError(t, err)

	tampered := manifest
	tampered.DisplayName += "（篡改）"
	tampered.ManifestSHA256 = entityPageGraphManifestDigest830G1ForTest(t, tampered)
	tamperedManifest, err := json.Marshal(tampered)
	require.NoError(t, err)
	result := db.Exec(
		"UPDATE wiki_release_preparations SET manifest = ? WHERE preparation_id = ?",
		string(tamperedManifest), preparation.ID,
	)
	require.NoError(t, result.Error)
	require.Equal(t, int64(1), result.RowsAffected)
	stored, err := repository.GetReadyPreparation(ctx, scope, preparation.ID)
	require.NoError(t, err)
	storedManifest, err := types.ParseEntityPageManifest830G1(stored.Manifest)
	require.NoError(t, err)
	require.Equal(t, tampered.DisplayName, storedManifest.DisplayName)
	require.Equal(t, tampered.ManifestSHA256, storedManifest.ManifestSHA256)
	require.Equal(t, manifestDigest, stored.ManifestDigest)
	require.NotEqual(t, stored.ManifestDigest, storedManifest.ManifestSHA256)

	_, err = NewSchemaWikiService(releaseAuthority, nil).LoadPinnedEntityPageGraphRelease830G1(
		ctx, principal, scope, manifest.ReleaseID,
	)
	require.ErrorIs(t, err, ErrEntityPageGraphIntegrity830G1)
}

func TestEntityPageGraphMemberSetsEqual830G1RequiresEmptyContentInBothCopies(t *testing.T) {
	base := types.WikiReleaseMemberSnapshot{
		Kind: "field", LogicalSlug: "page-1", RevisionID: "revision-1",
		MemberDigest: "digest-1", Title: "字段一", Payload: json.RawMessage(`{"contract":"field"}`),
	}
	for _, test := range []struct {
		name               string
		preparationContent string
		releaseContent     string
		want               bool
	}{
		{name: "both empty", want: true},
		{name: "preparation only", preparationContent: "second body"},
		{name: "release only", releaseContent: "second body"},
		{name: "both nonempty", preparationContent: "second body", releaseContent: "second body"},
	} {
		t.Run(test.name, func(t *testing.T) {
			preparationMember := base
			preparationMember.Content = test.preparationContent
			releaseMember := base
			releaseMember.Content = test.releaseContent
			require.Equal(t, test.want, entityPageGraphMemberSetsEqual830G1(
				[]types.WikiReleaseMemberSnapshot{preparationMember},
				[]types.WikiReleaseMemberSnapshot{releaseMember},
			))
		})
	}
}

func TestEntityPageGraphPreparationCitation830G1RejectsForeignEntityBeforePinnedSourceOrContent(t *testing.T) {
	t.Parallel()
	snapshot := entityPageGraphReleaseFixture830G1(t)
	manifest, err := types.ParseEntityPageManifest830G1(snapshot.Manifest)
	require.NoError(t, err)
	scope := types.WikiReleaseScope{
		TenantID: 7, SpaceID: manifest.SpaceID, RawKBID: "raw-596-1", WikiKBID: manifest.WikiKBID,
	}
	principal := types.WikiReleasePrincipal{ID: "reviewer", TenantID: scope.TenantID, SpaceID: scope.SpaceID}
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	require.NoError(t, fixture.db.Create(&types.WikiReleaseHead{
		ID: "head-g1-foreign-entity", WikiReleaseScope: scope, ActiveReleaseID: manifest.ReleaseID,
		ActivationEpoch: manifest.ActivationEpoch, UpdatedAt: time.Now().UTC(),
	}).Error)
	draft, err := fixture.authority.createDraft(fixture.ctx, principal, &types.WikiReleasePreparation{
		ID: "preparation-g1-foreign-entity", WikiReleaseScope: scope,
		CandidateDigest:    manifest.InputAuthority.CandidateSHA256,
		ReadyReceiptDigest: strings.Repeat("a", 64), ReviewPolicyID: strings.Repeat("b", 64),
		Manifest: append(json.RawMessage(nil), snapshot.Manifest...), Members: snapshot.Members,
	})
	require.NoError(t, err)

	var member types.EntityPageMember830G1
	var citationID string
	for _, candidate := range manifest.Members {
		if candidate.PageKind != "field" {
			continue
		}
		payload, payloadErr := candidate.FieldAssertionPayload()
		require.NoError(t, payloadErr)
		if len(payload.Citations) > 0 {
			member = candidate
			citationID = payload.Citations[0].CitationID
			break
		}
	}
	require.NotEmpty(t, citationID)
	content := &schemaWikiC6CitationContentSpy{}
	fixture.adapter = NewSchemaWikiService(fixture.authority, nil, content)
	headQueries := 0
	require.NoError(t, fixture.db.Callback().Query().Before("gorm:query").Register(
		"test:count-g1-foreign-entity-head-queries",
		func(tx *gorm.DB) {
			if tx.Statement != nil && tx.Statement.Table == "wiki_release_heads" {
				headQueries++
			}
		},
	))

	authority, err := fixture.adapter.IssueEntityPageGraphPreparationCitationAuthority830G1(
		fixture.ctx, principal, scope, draft.ID, "foreign-product",
		member.StableKey, citationID,
	)

	require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
	require.Nil(t, authority)
	require.Zero(t, headQueries, "foreign entity must fail before pinned source custody")
	require.Zero(t, content.issueCurrentCalls, "foreign entity must never reach citation content")
}

func TestEntityPageGraphPreparationCitation830G1UsesFullUniqueJoinIdentityAndExactSourceTuple(t *testing.T) {
	t.Parallel()
	manifest, err := types.ParseEntityPageManifest830G1(loadEntityPageGraph830G1ServiceVector(t))
	require.NoError(t, err)
	seen := map[string]struct{}{}
	var candidate types.EntityPageExactCitation830G1
	candidateFieldKey := ""
	for _, member := range manifest.Members {
		if member.PageKind != "field" {
			continue
		}
		payload, payloadErr := member.FieldAssertionPayload()
		require.NoError(t, payloadErr)
		for _, citation := range payload.Citations {
			require.Equal(t, "citation_"+citation.JoinReceiptSHA256, citation.CitationID)
			require.Len(t, citation.CitationID, len("citation_")+64)
			_, duplicate := seen[citation.JoinReceiptSHA256]
			require.False(t, duplicate)
			seen[citation.JoinReceiptSHA256] = struct{}{}
			if candidate.CitationID == "" {
				candidate = citation
				candidateFieldKey = member.StableKey
			}
		}
	}
	require.Len(t, seen, 17)
	require.NotEmpty(t, candidate.CitationID)
	join := types.Schema67CitationAuthorityJoinReceiptV1{
		FieldID:               candidateFieldKey,
		ReceiptSHA256:         candidate.JoinReceiptSHA256,
		EvidenceReceiptSHA256: candidate.EvidenceReceiptSHA256,
		SourceRole:            candidate.SourceRole, SourceSHA256: candidate.SourceSHA256,
		ParsedDocumentSHA256:   candidate.ParsedDocumentSHA256,
		ParseManifestSHA256:    candidate.ParseManifestSHA256,
		EvidenceParseAttemptID: candidate.ParseAttemptID,
		LocatorKind:            candidate.LocatorKind, LocatorRef: candidate.LocatorRef,
		PageNumber: candidate.PageNumber, LocatorContentSHA256: candidate.LocatorContentSHA256,
		NormalizedBBox: candidate.BBox, KnowledgeID: candidate.KnowledgeID,
		ChunkID: candidate.ChunkID, QuoteSHA256: candidate.QuoteSHA256,
		LiveRevisionSourceReceipt: types.LiveRevisionSourceReceiptV1{
			RevisionSourceID: candidate.SourceRevisionID,
		},
	}
	logicalMemberRef := "field:" + candidateFieldKey
	source := types.CitationTargetV1{
		Contract: "citation-target.v1", CitationID: "citation-" + candidate.JoinReceiptSHA256[:24],
		SpaceID: manifest.SpaceID, EntityVersionID: manifest.EntityVersionID,
		SourceRole: candidate.SourceRole, KnowledgeID: candidate.KnowledgeID,
		ChunkID: candidate.ChunkID, SourceRevisionID: candidate.SourceRevisionID,
		ParseAttemptID:       candidate.ParseAttemptID,
		ParsedDocumentSHA256: candidate.ParsedDocumentSHA256,
		ParseManifestSHA256:  candidate.ParseManifestSHA256,
		PageNumber:           candidate.PageNumber, LocatorRef: candidate.LocatorRef,
		BBox: candidate.BBox, QuoteSnapshot: candidate.QuoteSnapshot,
		QuoteSHA256:           candidate.QuoteSHA256,
		ContentSnapshotSHA256: candidate.LocatorContentSHA256,
		LogicalMemberRef:      logicalMemberRef,
	}
	source.CitationSHA256 = schemaWikiTestHashWithout(
		t, source.Contract, source, "citation_sha256",
	)
	require.True(t, entityPageGraphCitationMatchesSchemaSource830G1(candidate, join, source))
	tampered := candidate
	tampered.PageNumber++
	require.False(t, entityPageGraphCitationMatchesSchemaSource830G1(tampered, join, source))

	memberDigest := strings.Repeat("d", 64)
	binding := types.CitationMemberBindingV1{
		Contract: "citation-member-binding.v1", CitationSHA256: source.CitationSHA256,
		LogicalMemberRef: logicalMemberRef, MemberDigest: memberDigest,
	}
	binding.BindingSHA256 = schemaWikiTestHashWithout(
		t, binding.Contract, binding, "binding_sha256",
	)
	pagePayload, err := json.Marshal(types.SchemaFieldPageV1{
		Contract: "schema-field-page.v1", FieldID: candidateFieldKey, State: "present",
		ValueSnapshot:          &candidate.QuoteSnapshot,
		Citations:              []types.CitationTargetV1{source},
		EvidenceReceiptSHA256s: []string{candidate.EvidenceReceiptSHA256},
	})
	require.NoError(t, err)
	validated := validatedSchemaWikiCustody{
		release: types.KnowledgeWikiReleaseV1{
			CandidateSHA256: manifest.InputAuthority.CandidateSHA256,
			EntityVersion:   types.EntityVersionV1{VersionID: manifest.EntityVersionID},
			Members: []types.SchemaWikiMemberV1{{
				MemberKind: "field", MemberRef: logicalMemberRef,
				Payload: pagePayload, MemberDigest: memberDigest,
			}},
			CitationBindings: []types.CitationMemberBindingV1{binding},
		},
		candidateEvidenceAuthority: types.Schema67CandidateEvidenceAuthorityV1{
			CandidateSHA256: manifest.InputAuthority.CandidateSHA256,
			JoinReceipts:    []types.Schema67CitationAuthorityJoinReceiptV1{join},
		},
	}
	scope := types.WikiReleaseScope{
		TenantID: 7, SpaceID: manifest.SpaceID, RawKBID: "raw-596-1", WikiKBID: manifest.WikiKBID,
	}
	request, err := schemaWikiCitationRequest(
		validated, scope, manifest.ReleaseID, manifest.ActivationEpoch,
		logicalMemberRef, source.CitationID,
	)
	require.NoError(t, err)
	require.Equal(t, candidate.JoinReceiptSHA256, request.CoordinateAuthorityReceipt.ReceiptSHA256)
	require.Equal(t, candidate.SourceRevisionID, request.Citation.SourceRevisionID)
	require.Equal(t, candidate.PageNumber, request.Citation.PageNumber)
	require.Equal(t, candidate.BBox, request.Citation.BBox)
	require.Equal(t, candidate.QuoteSHA256, request.Citation.QuoteSHA256)

	content := &schemaWikiC6CitationContentSpy{}
	authority, err := content.IssueExactRevision(context.Background(), request)
	require.NoError(t, err)
	require.Equal(t, 1, content.issueCurrentCalls)
	require.Equal(t, request, content.request)
	require.Equal(t, "c6-citation-test-token", authority.OpaqueToken)
}

func TestEntityPageGraphManifest830G1ReplaysExactSchemaSourceCustody(t *testing.T) {
	t.Parallel()
	manifest, err := types.ParseEntityPageManifest830G1(loadEntityPageGraph830G1ServiceVector(t))
	require.NoError(t, err)
	release := types.KnowledgeWikiReleaseV1{
		CandidateSHA256: manifest.InputAuthority.CandidateSHA256,
		Entity:          types.EntityIdentityV1{EntityID: manifest.EntityID},
		EntityVersion: types.EntityVersionV1{
			EntityID: manifest.EntityID, VersionID: manifest.EntityVersionID,
			ProductVersionID: manifest.InputAuthority.ProductVersionID,
		},
		SchemaPack: types.SchemaPackV1{
			SchemaPackID:     manifest.Profile.SchemaPackID,
			SchemaVersion:    manifest.Profile.SchemaVersion,
			SchemaPackSHA256: manifest.Profile.SchemaPackSHA256,
		},
	}
	evidence := types.Schema67CandidateEvidenceAuthorityV1{
		Contract:        manifest.InputAuthority.EvidenceAuthorityContract,
		CandidateSHA256: manifest.InputAuthority.CandidateSHA256,
		AuthoritySHA256: manifest.InputAuthority.EvidenceAuthoritySHA256,
	}
	for _, source := range manifest.InputAuthority.SourceAuthorities {
		evidence.SourceAuthorities = append(evidence.SourceAuthorities, types.Schema67LiveSourceAuthorityV1{
			SourceRole: source.SourceRole, SourceSHA256: source.SourceSHA256,
			LiveRevisionSourceReceipt: types.LiveRevisionSourceReceiptV1{
				RevisionSourceID: source.RevisionSourceID, KnowledgeID: source.KnowledgeID,
				ResourceID: source.ResourceID, EvidenceParseAttemptID: source.EvidenceParseAttemptID,
				WeKnoraParseAttempt:  int64(source.WeKnoraParseAttempt),
				ParsedDocumentSHA256: source.ParsedDocumentSHA256,
				ParseManifestSHA256:  source.ParseManifestSHA256,
				SourceReceiptSHA256:  source.SourceReceiptSHA256,
			},
		})
	}
	for _, member := range manifest.Members {
		if member.PageKind != "field" {
			continue
		}
		candidate, payloadErr := member.FieldAssertionPayload()
		require.NoError(t, payloadErr)
		page := types.SchemaFieldPageV1{
			FieldID: candidate.FieldKey, State: candidate.State,
			ValueSnapshot:          candidate.ValueSnapshot,
			Citations:              []types.CitationTargetV1{},
			EvidenceReceiptSHA256s: append([]string{}, candidate.Reference.EvidenceReceiptSHA256s...),
		}
		for _, citation := range candidate.Citations {
			page.Citations = append(page.Citations, types.CitationTargetV1{
				CitationID: "citation-" + citation.JoinReceiptSHA256[:24],
				SourceRole: citation.SourceRole, KnowledgeID: citation.KnowledgeID,
				ChunkID: citation.ChunkID, SourceRevisionID: citation.SourceRevisionID,
				ParseAttemptID:       citation.ParseAttemptID,
				ParsedDocumentSHA256: citation.ParsedDocumentSHA256,
				ParseManifestSHA256:  citation.ParseManifestSHA256,
				PageNumber:           citation.PageNumber, LocatorRef: citation.LocatorRef,
				BBox: citation.BBox, QuoteSnapshot: citation.QuoteSnapshot,
				QuoteSHA256:           citation.QuoteSHA256,
				ContentSnapshotSHA256: citation.LocatorContentSHA256,
			})
			evidence.JoinReceipts = append(evidence.JoinReceipts, types.Schema67CitationAuthorityJoinReceiptV1{
				ReceiptSHA256: citation.JoinReceiptSHA256, FieldID: candidate.FieldKey,
				EvidenceReceiptSHA256: citation.EvidenceReceiptSHA256,
				SourceRole:            citation.SourceRole, SourceSHA256: citation.SourceSHA256,
				ParsedDocumentSHA256:   citation.ParsedDocumentSHA256,
				ParseManifestSHA256:    citation.ParseManifestSHA256,
				EvidenceParseAttemptID: citation.ParseAttemptID,
				LocatorKind:            citation.LocatorKind, LocatorRef: citation.LocatorRef,
				PageNumber: citation.PageNumber, LocatorContentSHA256: citation.LocatorContentSHA256,
				NormalizedBBox: citation.BBox, KnowledgeID: citation.KnowledgeID,
				ChunkID: citation.ChunkID, QuoteSHA256: citation.QuoteSHA256,
				LiveRevisionSourceReceipt: types.LiveRevisionSourceReceiptV1{
					RevisionSourceID: citation.SourceRevisionID,
				},
			})
		}
		payload, marshalErr := json.Marshal(page)
		require.NoError(t, marshalErr)
		release.Members = append(release.Members, types.SchemaWikiMemberV1{
			MemberKind: "field", Payload: payload,
		})
	}
	validated := validatedSchemaWikiCustody{release: release, candidateEvidenceAuthority: evidence}
	require.Equal(t, manifest.FieldAssertionCount, len(release.Members))
	require.Len(t, evidence.JoinReceipts, 17)
	require.Equal(t, manifest.InputAuthority.EvidenceAuthoritySHA256, evidence.AuthoritySHA256)
	for _, member := range manifest.Members {
		if member.PageKind != "field" {
			continue
		}
		candidate, payloadErr := member.FieldAssertionPayload()
		require.NoError(t, payloadErr)
		var old types.SchemaFieldPageV1
		for _, sourceMember := range release.Members {
			var page types.SchemaFieldPageV1
			require.NoError(t, json.Unmarshal(sourceMember.Payload, &page))
			if page.FieldID == member.StableKey {
				old = page
				break
			}
		}
		require.Equal(t, candidate.State, old.State, member.StableKey)
		require.Equal(t, candidate.Reference.EvidenceReceiptSHA256s, old.EvidenceReceiptSHA256s, member.StableKey)
		for index, citation := range candidate.Citations {
			require.True(t, entityPageGraphCitationMatchesSchemaSource830G1(
				citation, evidence.JoinReceipts[indexOfEntityPageJoin830G1(t, evidence.JoinReceipts, citation.JoinReceiptSHA256)],
				old.Citations[index],
			), member.StableKey)
		}
	}
	require.True(t, entityPageGraphManifestMatchesSchemaSource830G1(manifest, validated))
	validated.release.CandidateSHA256 = strings.Repeat("f", 64)
	require.False(t, entityPageGraphManifestMatchesSchemaSource830G1(manifest, validated))
}

func indexOfEntityPageJoin830G1(
	t *testing.T,
	joins []types.Schema67CitationAuthorityJoinReceiptV1,
	digest string,
) int {
	t.Helper()
	for index := range joins {
		if joins[index].ReceiptSHA256 == digest {
			return index
		}
	}
	require.FailNow(t, "missing join", digest)
	return -1
}

func entityPageGraphManifestDigest830G1ForTest(t *testing.T, manifest types.EntityPageManifest830G1) string {
	t.Helper()
	raw, err := json.Marshal(manifest)
	require.NoError(t, err)
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var payload map[string]any
	require.NoError(t, decoder.Decode(&payload))
	delete(payload, "manifest_sha256")
	canonical := schemaWikiTestCanonicalJSON(t, payload)
	canonical = entityPageGraphUnescapeLineSeparators830G1ForTest(canonical)
	preimage := append([]byte("schema-wiki-canonical.v1\x00"+manifest.Contract+"\x00"), canonical...)
	sum := sha256.Sum256(preimage)
	return hex.EncodeToString(sum[:])
}

func entityPageGraphUnescapeLineSeparators830G1ForTest(encoded []byte) []byte {
	result := make([]byte, 0, len(encoded))
	for index := 0; index < len(encoded); index++ {
		if encoded[index] != '\\' || index+5 >= len(encoded) || encoded[index+1] != 'u' ||
			(string(encoded[index+2:index+6]) != "2028" && string(encoded[index+2:index+6]) != "2029") {
			result = append(result, encoded[index])
			continue
		}
		slashes := 1
		for previous := index - 1; previous >= 0 && encoded[previous] == '\\'; previous-- {
			slashes++
		}
		if slashes%2 == 0 {
			result = append(result, encoded[index])
			continue
		}
		if encoded[index+5] == '8' {
			result = append(result, []byte("\u2028")...)
		} else {
			result = append(result, []byte("\u2029")...)
		}
		index += 5
	}
	return result
}

func snapshotManifestSpace(t *testing.T, snapshot EntityPageGraphReleaseSnapshot830G1) string {
	t.Helper()
	manifest, err := types.ParseEntityPageManifest830G1(snapshot.Manifest)
	require.NoError(t, err)
	return manifest.SpaceID
}

func readServiceTestFile(t *testing.T, path string) []byte {
	t.Helper()
	raw, err := os.ReadFile(path)
	require.NoError(t, err)
	return raw
}
