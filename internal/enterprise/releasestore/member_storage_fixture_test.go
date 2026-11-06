package releasestore

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/repository"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

func memberStorageDB(t *testing.T) *gorm.DB {
	t.Helper()
	db := openSchema(t).Session(&gorm.Session{Logger: logger.Default.LogMode(logger.Silent)})
	if db.Migrator().HasTable("enterprise_member_scopes") {
		return db
	}
	_, file, _, _ := runtime.Caller(0)
	raw, err := os.ReadFile(filepath.Join(filepath.Dir(file),
		"../../../migrations/enterprise/versioned/000013_enterprise_member_chunks.up.sql"))
	if os.IsNotExist(err) {
		raw, err = os.ReadFile("testdata/member_chunks.sql")
	}
	require.NoError(t, err)
	require.NoError(t, db.Exec(string(raw)).Error)
	return db
}

func storageCount(t *testing.T, db *gorm.DB, table string) int64 {
	t.Helper()
	var n int64
	require.NoError(t, db.Table(table).Count(&n).Error)
	return n
}

func storageRoot(t *testing.T, db *gorm.DB, id string) []byte {
	t.Helper()
	var row struct{ RootDigest []byte }
	require.NoError(t, db.Table("enterprise_member_releases").Where("release_id = ?", id).Take(&row).Error)
	require.Len(t, row.RootDigest, 32)
	return row.RootDigest
}

func storagePublish(t *testing.T, store *Store, nonce string, members []release.Member) release.Release {
	t.Helper()
	w := activation(t, store, nonce)
	w.Members = members
	w.BundleDigest = digestOf([]byte(nonce))
	got, err := store.Activate(context.Background(), w)
	require.NoError(t, err)
	return got
}

func storageMembers(t *testing.T, n, revision int) []release.Member {
	t.Helper()
	members := make([]release.Member, n)
	for i := range members {
		p := fmt.Sprintf(`{"value":"項%d/%d","number":9007199254740993}`, i, revision)
		members[i] = release.Member{
			Kind: "claim", LogicalSlug: fmt.Sprintf("group/%06d", i),
			Payload: json.RawMessage(p), MemberDigest: memberDigest(t, p), AccessScope: "space",
		}
	}
	return members
}

func storedSnapshots(t *testing.T, db *gorm.DB, id string) []types.WikiReleaseMemberSnapshot {
	t.Helper()
	var rows []types.WikiReleaseMember
	require.NoError(t, db.Where("release_id = ?", id).Order("logical_slug ASC").Find(&rows).Error)
	out := make([]types.WikiReleaseMemberSnapshot, len(rows))
	for i := range rows {
		out[i] = rows[i].Snapshot()
	}
	return out
}

// Fixture-only transition: migration/operator guard tests separately exercise the actual transition.
// Never used by runtime. It lets old runtime reach fail-closed and cold-read assertions.
func fixtureReferenceReads(t *testing.T, db *gorm.DB) {
	t.Helper()
	require.NoError(t, db.Exec(`UPDATE enterprise_member_scopes SET mode='reference'`).Error)
	require.NoError(t, db.Exec(`UPDATE wiki_releases SET member_storage='chunks.v1'`).Error)
	require.NoError(t, db.Exec(`UPDATE wiki_release_preparations SET member_storage='chunks.v1'`).Error)
}

func repositoryStorageWrite(t *testing.T, repo *repository.WikiReleaseRepository,
	scope types.WikiReleaseScope, id string, m []types.WikiReleaseMemberSnapshot,
) {
	t.Helper()
	ctx := context.Background()
	head, err := repo.GetHeadForSpace(ctx, scope.TenantID, scope.SpaceID)
	expected := ""
	var epoch uint64
	if err == nil {
		expected = head.ActiveReleaseID
		epoch = head.ActivationEpoch
	} else {
		require.ErrorIs(t, err, repository.ErrWikiReleaseNotFound)
	}
	p := types.WikiReleasePreparation{
		ID: "prep-" + id, WikiReleaseScope: scope,
		CandidateDigest: id, ManifestDigest: id, ExpectedReleaseID: expected,
		ExpectedActivationEpoch: epoch, Status: "ready", Manifest: json.RawMessage(`{}`),
		Members: m, PreparationDigest: id,
	}
	r := types.WikiRelease{
		ID: "rel-" + id, WikiReleaseScope: scope,
		CandidateDigest: id, ManifestDigest: id, PreparationID: p.ID,
	}
	_, err = repo.Activate(ctx, repository.WikiReleaseActivationWrite{
		Preparation: &p,
		Release:     &r, Members: m, ExpectedReleaseID: expected, ExpectedActivationEpoch: epoch,
		Nonce: id, ActivationReceiptID: "receipt-" + id, ExpectedPreparationID: p.ID,
		ExpectedPreparationDigest: p.PreparationDigest,
	})
	require.NoError(t, err)
}

func fullStorageCounts(t *testing.T, db *gorm.DB) map[string]int64 {
	t.Helper()
	out := rowCounts(t, db)
	for _, table := range []string{
		"enterprise_member_scopes",
		"enterprise_member_contents", "enterprise_member_chunks",
		"enterprise_member_sets", "enterprise_member_releases",
		"enterprise_member_preparations", "enterprise_member_progress",
	} {
		out[table] = storageCount(t, db, table)
	}
	return out
}
