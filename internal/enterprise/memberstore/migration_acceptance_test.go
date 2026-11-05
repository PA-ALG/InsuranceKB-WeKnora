package memberstore_test

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/releasestore"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

func migrationDB(t *testing.T) *gorm.DB {
	t.Helper()
	dsn := os.Getenv("WEKNORA_TEST_POSTGRES_URL")
	if dsn == "" {
		t.Skip("WEKNORA_TEST_POSTGRES_URL is required for PostgreSQL evidence")
	}
	admin, err := gorm.Open(postgres.Open(dsn), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	require.NoError(t, err)
	schema := fmt.Sprintf("st1_%d", time.Now().UnixNano())
	require.NoError(t, admin.Exec("CREATE SCHEMA "+schema).Error)
	separator := "?"
	if strings.Contains(dsn, "?") {
		separator = "&"
	}
	db, err := gorm.Open(postgres.Open(dsn+separator+"search_path="+schema), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	require.NoError(t, err)
	sqlDB, err := db.DB()
	require.NoError(t, err)
	sqlDB.SetMaxOpenConns(3)
	t.Cleanup(func() {
		_ = sqlDB.Close()
		_ = admin.Exec("DROP SCHEMA " + schema + " CASCADE").Error
		a, _ := admin.DB()
		_ = a.Close()
	})
	for _, name := range []string{"000002_release_falsification.up.sql", "000013_enterprise_member_chunks.up.sql"} {
		raw, err := os.ReadFile(filepath.Join("../../../migrations/enterprise/versioned", name))
		require.NoError(t, err)
		require.NoError(t, db.Exec(string(raw)).Error)
	}
	return db
}

func scope() types.WikiReleaseScope {
	return types.WikiReleaseScope{TenantID: 1, SpaceID: "space", RawKBID: "raw", WikiKBID: "wiki"}
}

func historical(t *testing.T, db *gorm.DB, id string, kind string) []types.WikiReleaseMemberSnapshot {
	t.Helper()
	m := []types.WikiReleaseMemberSnapshot{{Kind: kind, LogicalSlug: "b", RevisionID: "rev", MemberDigest: strings.Repeat("b", 64), Title: "標題", Content: "原文\n𐐀", Payload: json.RawMessage(`{"n":9007199254740993}`)},
		{Kind: "claim", LogicalSlug: "a", MemberDigest: strings.Repeat("a", 64), Content: "content", Payload: json.RawMessage(`{"n":2}`)}}
	// Real enterprise v1 envelopes, digests and manifest; retain original order/empty kind.
	pairs := make([][2]string, len(m))
	for i := range m {
		digest, err := release.MemberDigest(m[i].Payload)
		require.NoError(t, err)
		m[i].MemberDigest = digest
		envelope, err := json.Marshal(struct {
			Version int    `json:"v"`
			Payload string `json:"payload"`
		}{1, string(m[i].Payload)})
		require.NoError(t, err)
		m[i].Content = string(envelope)
		pairs[i] = [2]string{m[i].LogicalSlug, digest}
	}
	manifest, err := json.Marshal(struct {
		CandidateID    string      `json:"candidate_id"`
		DecisionID     string      `json:"decision_id"`
		DecisionDigest string      `json:"decision_digest"`
		BundleDigest   string      `json:"bundle_digest"`
		Members        [][2]string `json:"members"`
	}{"candidate", "decision", "decision-digest", "bundle-digest", pairs})
	require.NoError(t, err)
	hash := func(raw []byte) string { d := sha256.Sum256(raw); return hex.EncodeToString(d[:]) }
	p := types.WikiReleasePreparation{ID: "prep-" + id, WikiReleaseScope: scope(), Status: "ready", Manifest: manifest, Members: m, CandidateDigest: "bundle-digest", ManifestDigest: hash(manifest), ReviewDecisionDigest: "decision-digest", ReviewPolicyID: "decision"}
	p.PreparationDigest = hash([]byte(fmt.Sprintf("%s|%s|%s||0", p.ID, p.ManifestDigest, p.ReviewDecisionDigest)))
	r := types.WikiRelease{ID: id, WikiReleaseScope: scope(), PreparationID: p.ID, CandidateDigest: p.CandidateDigest, ManifestDigest: p.ManifestDigest}
	require.NoError(t, db.Create(&p).Error)
	require.NoError(t, db.Create(&r).Error)
	for _, s := range m {
		k := s.Kind
		if k == "" {
			k = "page"
		}
		row := types.WikiReleaseMember{ID: id + ":" + s.LogicalSlug, ReleaseID: id, Kind: k, LogicalSlug: s.LogicalSlug, RevisionID: s.RevisionID, MemberDigest: s.MemberDigest, Title: s.Title, Content: s.Content, Payload: s.Payload}
		require.NoError(t, db.Create(&row).Error)
	}
	return m
}

func legacyRows(t *testing.T, db *gorm.DB, id string) []types.WikiReleaseMember {
	t.Helper()
	var rows []types.WikiReleaseMember
	require.NoError(t, db.Where("release_id = ?", id).Order("logical_slug ASC").Find(&rows).Error)
	return rows
}

func TestPostgresMemberMigrationPreservesHistoricalOrderAndRestoresBeforeDown(t *testing.T) {
	db := migrationDB(t)
	ctx := context.Background()
	historical(t, db, "historical", "")
	var originalPrep types.WikiReleasePreparation
	require.NoError(t, db.Take(&originalPrep).Error)
	originalRows := legacyRows(t, db, "historical")
	store := releasestore.NewMemberStorage()
	require.NoError(t, store.Backfill(ctx, db, scope(), "historical", 1<<20))
	require.NoError(t, store.Backfill(ctx, db, scope(), "historical", 1<<20), "reentrant full snapshot equality")
	var roots [][]byte
	var rows []struct{ Root []byte }
	require.NoError(t, db.Raw(`SELECT root_digest AS root FROM enterprise_member_releases UNION ALL SELECT root_digest FROM enterprise_member_preparations`).Scan(&rows).Error)
	for _, r := range rows {
		roots = append(roots, r.Root)
	}
	require.Len(t, roots, 2)
	require.NotEqual(t, roots[0], roots[1])
	require.NoError(t, store.StartObservation(ctx, db, scope()))
	require.Error(t, store.ReferenceOnly(ctx, db, scope()), "seven days cannot be bypassed")
	require.NoError(t, db.Exec(`UPDATE enterprise_member_scopes SET observation_started_at=CURRENT_TIMESTAMP-INTERVAL '8 days',read_failures=1`).Error)
	require.Error(t, store.ReferenceOnly(ctx, db, scope()), "a validation error rejects transition")
	require.NoError(t, db.Exec(`UPDATE enterprise_member_scopes SET read_failures=0`).Error)
	require.NoError(t, store.ReferenceOnly(ctx, db, scope()))
	require.NoError(t, store.CompactLegacy(ctx, db, scope()))
	require.Empty(t, legacyRows(t, db, "historical"))
	raw, err := os.ReadFile("../../../migrations/enterprise/versioned/000013_enterprise_member_chunks.down.sql")
	require.NoError(t, err)
	require.Error(t, db.Exec(string(raw)).Error, "down before restoring old format is forbidden")
	require.Error(t, store.RestoreLegacy(ctx, db, scope(), 1), "capacity budget rejects before restoring any bytes")
	require.Empty(t, legacyRows(t, db, "historical"))
	require.NoError(t, store.RestoreLegacy(ctx, db, scope(), 1<<20))
	require.Equal(t, originalRows, legacyRows(t, db, "historical"))
	var restored types.WikiReleasePreparation
	require.NoError(t, db.Take(&restored).Error)
	require.Equal(t, originalPrep, restored)
	require.NoError(t, db.Exec(string(raw)).Error)
	require.True(t, db.Migrator().HasTable("wiki_release_receipts"))
	require.False(t, db.Migrator().HasTable("enterprise_member_sets"))
}

func TestPostgresMemberMigrationSourceDriftAndFaultResume(t *testing.T) {
	db := migrationDB(t)
	ctx := context.Background()
	historical(t, db, "drift", "")
	store := releasestore.NewMemberStorage()
	require.NoError(t, db.Exec(`CREATE FUNCTION st1_fail_root() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic'; END $$;
 CREATE TRIGGER st1_fail_root BEFORE INSERT ON enterprise_member_sets FOR EACH ROW EXECUTE FUNCTION st1_fail_root()`).Error)
	require.Error(t, store.Backfill(ctx, db, scope(), "drift", 1<<20))
	var count int64
	require.NoError(t, db.Table("enterprise_member_releases").Count(&count).Error)
	require.Zero(t, count)
	require.NoError(t, db.Exec(`DROP TRIGGER st1_fail_root ON enterprise_member_sets`).Error)
	require.NoError(t, db.Exec(`UPDATE wiki_release_members SET title='changed' WHERE logical_slug='a'`).Error)
	require.Error(t, store.Backfill(ctx, db, scope(), "drift", 1<<20), "saved progress fingerprint cannot silently accept changed source")
	require.NoError(t, db.Exec(`UPDATE wiki_release_members SET title='' WHERE logical_slug='a'`).Error)
	require.NoError(t, store.Backfill(ctx, db, scope(), "drift", 1<<20))
	require.NoError(t, store.Backfill(ctx, db, scope(), "drift", 1<<20))
	require.NoError(t, db.Table("enterprise_member_releases").Count(&count).Error)
	require.EqualValues(t, 1, count)
}

func TestPostgresMemberMigrationSkipsUnassociatedAndRejectsBrokenObject(t *testing.T) {
	db := migrationDB(t)
	ctx := context.Background()
	historical(t, db, "valid", "page")
	store := releasestore.NewMemberStorage()
	p := types.WikiReleasePreparation{ID: "unassociated", WikiReleaseScope: scope(), Status: "ready", PreparationDigest: "unassociated", Manifest: json.RawMessage(`{}`), Members: []types.WikiReleaseMemberSnapshot{}}
	require.NoError(t, db.Create(&p).Error)
	require.NoError(t, store.Backfill(ctx, db, scope(), "valid", 1<<20))
	require.NoError(t, store.StartObservation(ctx, db, scope()))
	require.NoError(t, db.Exec(`UPDATE enterprise_member_scopes SET observation_started_at=CURRENT_TIMESTAMP-INTERVAL '8 days'`).Error)
	require.NoError(t, store.ReferenceOnly(ctx, db, scope()))
	require.NoError(t, store.CompactLegacy(ctx, db, scope()))
	require.NoError(t, db.Exec(`UPDATE enterprise_member_contents SET payload_json='{}'`).Error)
	require.Error(t, store.RestoreLegacy(ctx, db, scope(), 1<<20))
	var count int64
	require.NoError(t, db.Table("wiki_release_members").Count(&count).Error)
	require.Zero(t, count)
	var unchanged types.WikiReleasePreparation
	require.NoError(t, db.Where("preparation_id=?", p.ID).Take(&unchanged).Error)
	require.Equal(t, p.Members, unchanged.Members)
}

func TestPostgresMemberStorageInjectedPortUsesOriginalTransaction(t *testing.T) {
	db := migrationDB(t)
	ctx := context.Background()
	repo := repository.NewWikiReleaseRepository(db).WithMemberStorage(releasestore.NewMemberStorage())
	input := []types.WikiReleaseMemberSnapshot{{Kind: "page", LogicalSlug: "value", Content: "content", MemberDigest: strings.Repeat("a", 64), Payload: json.RawMessage(`{}`)}}
	p := types.WikiReleasePreparation{ID: "preparation", WikiReleaseScope: scope(), Status: "ready", PreparationDigest: "digest", Manifest: json.RawMessage(`{}`), Members: input}
	r := types.WikiRelease{ID: "release", WikiReleaseScope: scope(), PreparationID: p.ID}
	w := repository.WikiReleaseActivationWrite{Preparation: &p, Release: &r, Members: input, ExpectedPreparationID: p.ID, ExpectedPreparationDigest: p.PreparationDigest, Nonce: "nonce", ActivationReceiptID: "receipt", CASFault: func() error { return fmt.Errorf("synthetic CAS failure") }}
	_, err := repo.Activate(ctx, w)
	require.Error(t, err)
	for _, table := range []string{"wiki_release_preparations", "wiki_releases", "wiki_release_receipts", "wiki_release_heads", "enterprise_member_contents", "enterprise_member_chunks", "enterprise_member_sets", "enterprise_member_scopes", "enterprise_member_releases", "enterprise_member_preparations", "enterprise_member_progress"} {
		var n int64
		require.NoError(t, db.Table(table).Count(&n).Error)
		require.Zero(t, n, table)
	}
	w.CASFault = nil
	_, err = repo.Activate(ctx, w)
	require.NoError(t, err)
	got, err := repo.GetReleaseMembers(ctx, scope(), r.ID)
	require.NoError(t, err)
	require.Equal(t, input, got)
}
