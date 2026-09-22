package service

import (
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func TestG3AutomatedActivationDoesNotRepeatReadySemanticValidation(t *testing.T) {
	f, s, policy := automatedFixture(t)
	draft, err := s.CreateBatchConceptDraftAutomated830G3(f.ctx, f.principal1, f.scope, "activation-reuse", batchConceptCandidateVector830G3(t))
	require.NoError(t, err)
	decision, signed := automaticDecision(t, f, policy, draft)
	ready, err := f.service.ReviewDraftAutomated(f.ctx, f.principal1, f.scope, draft.ID, decision)
	require.NoError(t, err)
	persisted, err := f.repo.GetReadyPreparation(f.ctx, f.scope, ready.ID)
	require.NoError(t, err)
	canonical, err := types.CanonicalBatchConceptWire830G3(persisted.Manifest)
	require.NoError(t, err)
	require.Equal(t, persisted.ManifestDigest, digestWikiReleaseBytes(canonical), "stored JSON must retain the canonical manifest identity")
	t.Logf("persisted raw manifest matches canonical digest: %t", persisted.ManifestDigest == digestWikiReleaseBytes(persisted.Manifest))
	verifier := f.service.conceptSourceAuthorityVerifier830G2.(*conceptSourceAuthorityVerifierFake830G2)
	sourceChecks := len(verifier.requests)
	before := batchPreparationValidations830G3.Load()
	receipt, err := f.service.ActivateAutomated(f.ctx, f.principal1, decision, automaticAuthorization(t, f, ready, signed.Nonce))
	require.NoError(t, err)
	require.Equal(t, uint64(6), receipt.ActivationEpoch)
	require.Len(t, verifier.requests, sourceChecks+1, "activation must retain current source authority")
	require.Equal(t, uint64(1), batchPreparationValidations830G3.Load()-before, "private CAS activation must reuse the already validated Ready projection")
}

func TestG3AutomatedActivationRejectsMembersOmittedAfterValidation(t *testing.T) {
	f, s, policy := automatedFixture(t)
	draft, err := s.CreateBatchConceptDraftAutomated830G3(f.ctx, f.principal1, f.scope, "activation-omitted-members", batchConceptCandidateVector830G3(t))
	require.NoError(t, err)
	decision, signed := automaticDecision(t, f, policy, draft)
	ready, err := f.service.ReviewDraftAutomated(f.ctx, f.principal1, f.scope, draft.ID, decision)
	require.NoError(t, err)
	name := strings.NewReplacer("/", "-", " ", "-").Replace(t.Name())
	db, err := gorm.Open(sqlite.Open("file:"+name+"?mode=memory&cache=shared"), &gorm.Config{})
	require.NoError(t, err)
	connection, err := db.DB()
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	before, err := f.repo.CountState(f.ctx)
	require.NoError(t, err)
	// Change only the in-memory fixture after the public caller's full check,
	// before private activation rereads the persisted Ready preparation.
	f.service.conceptSourceAuthorityVerifier830G2 = automaticSourceHook(func() {
		result := db.Model(&types.WikiReleasePreparation{}).Where("preparation_id = ? AND status = ?", ready.ID, types.WikiReleasePreparationReady).UpdateColumn("members", gorm.Expr("?", "null"))
		require.NoError(t, result.Error)
		require.EqualValues(t, 1, result.RowsAffected)
		changed, readErr := f.repo.GetReadyPreparation(f.ctx, f.scope, ready.ID)
		require.NoError(t, readErr)
		require.Nil(t, changed.Members)
	})
	_, err = f.service.ActivateAutomated(f.ctx, f.principal1, decision, automaticAuthorization(t, f, ready, signed.Nonce))
	require.ErrorIs(t, err, ErrWikiReleaseInvalidAuthorization)
	after, err := f.repo.CountState(f.ctx)
	require.NoError(t, err)
	require.Equal(t, before, after, "omitted members must not create an empty release or advance the head")
}
