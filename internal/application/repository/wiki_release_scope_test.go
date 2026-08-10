package repository

import (
	"context"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func newSchemaWikiScopeRepository(t *testing.T) (*WikiReleaseRepository, *gorm.DB) {
	t.Helper()
	db, err := gorm.Open(
		sqlite.Open("file:"+t.Name()+"?mode=memory&cache=shared"),
		&gorm.Config{},
	)
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(&types.WikiReleaseHead{}))
	require.NoError(t, db.AutoMigrate(&types.WikiReleasePreparation{}))
	return NewWikiReleaseRepository(db), db
}

func TestGetPreparationScopeForWikiKBIsExactAndTenantScoped(t *testing.T) {
	t.Parallel()
	repo, db := newSchemaWikiScopeRepository(t)
	require.NoError(t, db.Create(&types.WikiReleasePreparation{
		ID: "preparation-596-1",
		WikiReleaseScope: types.WikiReleaseScope{
			TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-medical",
		},
		CandidateDigest: "candidate", ManifestDigest: "manifest",
		ReadyReceiptDigest: "bundle", ReviewDecisionDigest: "", ReviewPolicyID: "policy",
		ExpectedReleaseID: "", ExpectedActivationEpoch: 0, Status: types.WikiReleasePreparationDraft,
		Manifest: []byte(`{"contract":"test"}`), Members: []types.WikiReleaseMemberSnapshot{},
		PreparationDigest: "preparation",
	}).Error)

	scope, err := repo.GetPreparationScopeForWikiKB(
		context.Background(), 10003, "wiki-medical", "preparation-596-1",
	)
	require.NoError(t, err)
	require.Equal(t, types.WikiReleaseScope{
		TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-medical",
	}, *scope)

	_, err = repo.GetPreparationScopeForWikiKB(
		context.Background(), 99999, "wiki-medical", "preparation-596-1",
	)
	require.ErrorIs(t, err, ErrWikiReleaseNotFound)
	_, err = repo.GetPreparationScopeForWikiKB(
		context.Background(), 10003, "wiki-medical", "preparation-missing",
	)
	require.ErrorIs(t, err, ErrWikiReleaseNotFound)
}

func schemaWikiScopeHead(id string, tenantID uint64, wikiKBID string) *types.WikiReleaseHead {
	return &types.WikiReleaseHead{
		ID: id,
		WikiReleaseScope: types.WikiReleaseScope{
			TenantID: tenantID,
			SpaceID:  "space-596-1",
			RawKBID:  "raw-596-1",
			WikiKBID: wikiKBID,
		},
		ActiveReleaseID: "release-596-1",
		ActivationEpoch: 1,
	}
}

func TestGetHeadForWikiKBScopeRequiresExactlyOneTenantScopedHead(t *testing.T) {
	t.Parallel()

	t.Run("exact one", func(t *testing.T) {
		repo, db := newSchemaWikiScopeRepository(t)
		require.NoError(t, db.Create(schemaWikiScopeHead("head-one", 10003, "wiki-medical")).Error)

		head, err := repo.GetHeadForWikiKB(context.Background(), 10003, "wiki-medical")
		require.NoError(t, err)
		require.Equal(t, uint64(10003), head.TenantID)
		require.Equal(t, "space-596-1", head.SpaceID)
		require.Equal(t, "raw-596-1", head.RawKBID)
		require.Equal(t, "wiki-medical", head.WikiKBID)
	})

	t.Run("zero", func(t *testing.T) {
		repo, _ := newSchemaWikiScopeRepository(t)
		_, err := repo.GetHeadForWikiKB(context.Background(), 10003, "wiki-missing")
		require.ErrorIs(t, err, ErrWikiReleaseNotFound)
	})

	t.Run("multiple", func(t *testing.T) {
		repo, db := newSchemaWikiScopeRepository(t)
		require.NoError(t, db.Create(schemaWikiScopeHead("head-a", 10003, "wiki-medical")).Error)
		second := schemaWikiScopeHead("head-b", 10003, "wiki-medical")
		second.SpaceID = "space-foreign"
		second.RawKBID = "raw-foreign"
		require.NoError(t, db.Create(second).Error)

		_, err := repo.GetHeadForWikiKB(context.Background(), 10003, "wiki-medical")
		require.ErrorIs(t, err, ErrWikiReleaseConflict)
	})

	t.Run("cross tenant is absent", func(t *testing.T) {
		repo, db := newSchemaWikiScopeRepository(t)
		require.NoError(t, db.Create(schemaWikiScopeHead("head-victim", 99999, "wiki-medical")).Error)

		_, err := repo.GetHeadForWikiKB(context.Background(), 10003, "wiki-medical")
		require.True(t, errors.Is(err, ErrWikiReleaseNotFound), "err=%v", err)
	})
}
