package releasestore

// PostgreSQL evidence for the adapter: exact bytes, concurrent dedup, Head CAS, idempotent
// replay, isolation and the 000006 rollback. Each run uses a fresh schema holding only the
// 000002 release tables and the 000006 tables. Requires WEKNORA_TEST_POSTGRES_URL.

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

const testSchema = `{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["contract_version", "origin", "members", "compiler_identity"]
}`

type allowAll struct{}

func (allowAll) Resolve(context.Context, string) (bool, error) { return true, nil }

func migrationSQL(t *testing.T, name string) string {
	t.Helper()
	_, file, _, _ := runtime.Caller(0)
	raw, err := os.ReadFile(filepath.Join(filepath.Dir(file), "../../../migrations/enterprise/versioned", name))
	require.NoError(t, err)
	return string(raw)
}

func openSchema(t *testing.T) *gorm.DB {
	t.Helper()
	dsn := strings.TrimSpace(os.Getenv("WEKNORA_TEST_POSTGRES_URL"))
	if dsn == "" {
		t.Skip("WEKNORA_TEST_POSTGRES_URL is required for PostgreSQL adapter evidence")
	}
	admin, err := gorm.Open(postgres.Open(dsn), &gorm.Config{})
	require.NoError(t, err)
	schema := fmt.Sprintf("s4c2a_%d", time.Now().UnixNano())
	require.NoError(t, admin.Exec("CREATE SCHEMA "+schema).Error)
	adminSQL, err := admin.DB()
	require.NoError(t, err)
	t.Cleanup(func() {
		_ = admin.Exec("DROP SCHEMA " + schema + " CASCADE").Error
		_ = adminSQL.Close()
	})
	separator := "?"
	if strings.Contains(dsn, "?") {
		separator = "&"
	}
	db, err := gorm.Open(postgres.Open(dsn+separator+"search_path="+schema), &gorm.Config{})
	require.NoError(t, err)
	sqlDB, err := db.DB()
	require.NoError(t, err)
	sqlDB.SetMaxOpenConns(8)
	t.Cleanup(func() { _ = sqlDB.Close() })
	for _, name := range []string{
		"000002_release_falsification.up.sql", "000006_enterprise_candidates.up.sql",
		"000011_enterprise_point_decisions.up.sql", // RV6b: Decide reads point decisions
	} {
		require.NoError(t, db.Exec(migrationSQL(t, name)).Error, name)
	}
	setupRevisionSourceTables(t, db)
	return db
}

func testSpaces(t *testing.T) Spaces {
	t.Helper()
	spaces, err := ParseSpaces(`[
	  {"tenant_id":7,"space_id":"space-1","raw_kb_id":"raw-1","wiki_kb_id":"wiki-1"},
	  {"tenant_id":7,"space_id":"space-2","raw_kb_id":"raw-2","wiki_kb_id":"wiki-2"}]`)
	require.NoError(t, err)
	return spaces
}

func memberDigest(t *testing.T, payload string) string {
	t.Helper()
	var value any
	require.NoError(t, json.Unmarshal([]byte(payload), &value))
	raw, err := json.Marshal(value)
	require.NoError(t, err)
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

// rawBundle writes the payload text verbatim, so read-back can prove byte preservation.
func rawBundle(t *testing.T, base string, slug, payload string) []byte {
	t.Helper()
	baseField := ""
	if base != "" {
		baseField = fmt.Sprintf(`"base_release_id": %q, `, base)
	}
	raw := []byte(fmt.Sprintf(`{"contract_version": "1", %s"origin": "compile", "compiler_identity": "harness/test",
  "members": [{"kind": "claim", "logical_slug": %q, "payload": %s, "member_digest": %q,
               "evidence_refs": ["source:v1:k-1:1:abc"], "access_scope": "space"}]}`,
		baseField, slug, payload, memberDigest(t, payload)))
	return []byte(strings.ReplaceAll(string(raw), "source:v1:k-1:1:abc", postgresSourceRef))
}

var principal = release.Principal{TenantID: 7, Subject: "svc-harness"}

var approve = release.DecisionInput{Outcome: "approve", Mode: "machine", PolicyRef: "gate-2026-10-15"}

func service(store *Store) *release.Service {
	return release.NewService(store, allowAll{}, map[string][]byte{"candidate_bundle": []byte(testSchema)},
		release.WithPublisher(store))
}

func TestPostgresPublishesAndReadsBackExactBytes(t *testing.T) {
	store := New(openSchema(t), testSpaces(t))
	s, ctx := service(store), context.Background()
	payload := `{"value":  "90日",   "conditions": ["意外除外", "等待期"]}`
	c, err := s.Receive(ctx, principal, "space-1", rawBundle(t, "", "1814/waiting_period", payload))
	require.NoError(t, err)
	d, err := s.Decide(ctx, principal, "space-1", c.ID, approve)
	require.NoError(t, err)
	r, err := s.Activate(ctx, principal, "space-1", c.ID, d.ID)
	require.NoError(t, err)
	require.Equal(t, uint64(1), r.Epoch)
	require.Equal(t, c.ID, r.CandidateID)
	require.Equal(t, d.Digest, r.DecisionDigest)

	active, err := s.Release(ctx, principal, "space-1", "")
	require.NoError(t, err)
	require.Equal(t, r.ID, active.ID)
	require.Len(t, active.Members, 1)
	require.Equal(t, payload, string(active.Members[0].Payload), "payload bytes survive storage")
	require.Equal(t, []string{postgresSourceRef}, active.Members[0].EvidenceRefs)
	require.Equal(t, "space", active.Members[0].AccessScope)

	bundle, err := store.BundleOf(ctx, 7, "space-1", c.ID)
	require.NoError(t, err)
	require.Equal(t, string(rawBundle(t, "", "1814/waiting_period", payload)), string(bundle.RawJSON))
}

func TestPostgresDeduplicatesConcurrentSubmissions(t *testing.T) {
	store := New(openSchema(t), testSpaces(t))
	s, ctx := service(store), context.Background()
	raw := rawBundle(t, "", "a", `{"v":1}`)
	statuses, ids := make(chan string, 8), make(chan string, 8)
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			c, err := s.Receive(ctx, principal, "space-1", raw)
			require.NoError(t, err)
			statuses <- c.Status
			ids <- c.ID
		}()
	}
	wg.Wait()
	close(statuses)
	close(ids)
	created, seen := 0, map[string]bool{}
	for status := range statuses {
		if status == "created" {
			created++
		}
	}
	for id := range ids {
		seen[id] = true
	}
	require.Equal(t, 1, created)
	require.Len(t, seen, 1)

	other, err := s.Receive(ctx, principal, "space-2", raw)
	require.NoError(t, err)
	require.False(t, seen[other.ID], "never deduplicated across Spaces")
}

func TestPostgresConcurrentActivationsAdmitExactlyOne(t *testing.T) {
	store := New(openSchema(t), testSpaces(t))
	s, ctx := service(store), context.Background()
	type ready struct{ candidate, decision string }
	var plans []ready
	for i := 0; i < 4; i++ {
		c, err := s.Receive(ctx, principal, "space-1", rawBundle(t, "", fmt.Sprintf("slug-%d", i), `{"v":1}`))
		require.NoError(t, err)
		d, err := s.Decide(ctx, principal, "space-1", c.ID, approve)
		require.NoError(t, err)
		plans = append(plans, ready{c.ID, d.ID})
	}
	results := make(chan error, len(plans))
	var wg sync.WaitGroup
	for _, plan := range plans {
		wg.Add(1)
		go func(plan ready) {
			defer wg.Done()
			_, err := s.Activate(ctx, principal, "space-1", plan.candidate, plan.decision)
			results <- err
		}(plan)
	}
	wg.Wait()
	close(results)
	succeeded := 0
	for err := range results {
		if err == nil {
			succeeded++
			continue
		}
		var failure *release.Error
		require.ErrorAs(t, err, &failure)
		require.Contains(t, []string{release.ErrorReleaseConflict, release.ErrorNeedsRebase}, failure.Code)
	}
	require.Equal(t, 1, succeeded)
	head, err := store.Head(ctx, 7, "space-1")
	require.NoError(t, err)
	require.Equal(t, uint64(1), head.Epoch)
}

func TestPostgresReplayingAnActivationWritesOnce(t *testing.T) {
	db := openSchema(t)
	store := New(db, testSpaces(t))
	s, ctx := service(store), context.Background()
	c, err := s.Receive(ctx, principal, "space-1", rawBundle(t, "", "a", `{"v":1}`))
	require.NoError(t, err)
	d, err := s.Decide(ctx, principal, "space-1", c.ID, approve)
	require.NoError(t, err)
	first, err := s.Activate(ctx, principal, "space-1", c.ID, d.ID)
	require.NoError(t, err)

	// Replay below the service: the same write reaches the adapter twice.
	write := release.ActivationWrite{
		TenantID: 7, SpaceID: "space-1", Subject: "svc-harness", CandidateID: c.ID,
		BundleDigest: c.BundleDigest, DecisionID: d.ID, DecisionDigest: d.Digest,
		Nonce: hexSHA(c.ID + ":" + d.Digest), Expected: release.Head{},
	}
	again, err := store.Activate(ctx, write)
	require.NoError(t, err)
	require.Equal(t, first.ID, again.ID)
	var receipts int64
	require.NoError(t, db.Table("wiki_release_receipts").Count(&receipts).Error)
	require.Equal(t, int64(1), receipts)
}

func TestPostgresKeepsTenantsAndSpacesApart(t *testing.T) {
	store := New(openSchema(t), testSpaces(t))
	s, ctx := service(store), context.Background()
	c, err := s.Receive(ctx, principal, "space-1", rawBundle(t, "", "a", `{"v":1}`))
	require.NoError(t, err)

	_, err = store.CandidateByID(ctx, 7, "space-2", c.ID)
	requireCode(t, err, release.ErrorCandidateNotFound)
	_, err = store.CandidateByID(ctx, 8, "space-1", c.ID)
	requireCode(t, err, release.ErrorCandidateNotFound)
	_, err = s.Receive(ctx, principal, "space-unconfigured", rawBundle(t, "", "a", `{"v":1}`))
	require.Error(t, err)
	_, err = s.Release(ctx, principal, "space-2", "")
	requireCode(t, err, release.ErrorReleaseNotFound)
}

func TestPostgresMigrationRollsBackAndReapplies(t *testing.T) {
	db := openSchema(t)
	// RV6b: the point decisions reference candidates, so they roll back first.
	require.NoError(t, db.Exec(migrationSQL(t, "000011_enterprise_point_decisions.down.sql")).Error)
	require.NoError(t, db.Exec(migrationSQL(t, "000006_enterprise_candidates.down.sql")).Error)
	require.False(t, db.Migrator().HasTable("enterprise_candidates"))
	require.True(t, db.Migrator().HasTable("wiki_releases"), "rollback keeps release history")
	require.NoError(t, db.Exec(migrationSQL(t, "000006_enterprise_candidates.up.sql")).Error)
	require.True(t, db.Migrator().HasTable("enterprise_decisions"))
}

func requireCode(t *testing.T, err error, code string) {
	t.Helper()
	var failure *release.Error
	require.ErrorAs(t, err, &failure)
	require.Equal(t, code, failure.Code)
}

func hexSHA(text string) string {
	sum := sha256.Sum256([]byte(text))
	return hex.EncodeToString(sum[:])
}

func TestPostgresRefusesAHeadBoundToOtherKnowledgeBases(t *testing.T) {
	db := openSchema(t)
	s, ctx := service(New(db, testSpaces(t))), context.Background()
	c, err := s.Receive(ctx, principal, "space-1", rawBundle(t, "", "a", `{"v":1}`))
	require.NoError(t, err)
	d, err := s.Decide(ctx, principal, "space-1", c.ID, approve)
	require.NoError(t, err)
	_, err = s.Activate(ctx, principal, "space-1", c.ID, d.ID)
	require.NoError(t, err)

	for name, raw := range map[string]string{
		"other wiki KB": `[{"tenant_id":7,"space_id":"space-1","raw_kb_id":"raw-1","wiki_kb_id":"wiki-9"}]`,
		"other raw KB":  `[{"tenant_id":7,"space_id":"space-1","raw_kb_id":"raw-9","wiki_kb_id":"wiki-1"}]`,
	} {
		t.Run(name, func(t *testing.T) {
			spaces, err := ParseSpaces(raw)
			require.NoError(t, err)
			moved := New(db, spaces)
			_, err = moved.Head(ctx, 7, "space-1")
			requireCode(t, err, release.ErrorServiceUnavailable)
			_, err = moved.ReleaseByID(ctx, 7, "space-1", "")
			requireCode(t, err, release.ErrorServiceUnavailable)
		})
	}
}

func TestPostgresRetryAfterTheHeadMovedReturnsTheCommittedRelease(t *testing.T) {
	db := openSchema(t)
	s, ctx := service(New(db, testSpaces(t))), context.Background()
	a, err := s.Receive(ctx, principal, "space-1", rawBundle(t, "", "a", `{"v":1}`))
	require.NoError(t, err)
	da, err := s.Decide(ctx, principal, "space-1", a.ID, approve)
	require.NoError(t, err)
	// Since S8b an untouched Head advance is rebased; this stale candidate adds the slug B
	// commits below, a real conflict that still needs a rebase.
	stale, err := s.Receive(ctx, principal, "space-1", rawBundle(t, "", "b", `{"v":3}`))
	require.NoError(t, err)
	ds, err := s.Decide(ctx, principal, "space-1", stale.ID, approve)
	require.NoError(t, err)
	r1, err := s.Activate(ctx, principal, "space-1", a.ID, da.ID)
	require.NoError(t, err)
	b, err := s.Receive(ctx, principal, "space-1", rawBundle(t, r1.ID, "b", `{"v":2}`))
	require.NoError(t, err)
	db2, err := s.Decide(ctx, principal, "space-1", b.ID, approve)
	require.NoError(t, err)
	r2, err := s.Activate(ctx, principal, "space-1", b.ID, db2.ID)
	require.NoError(t, err)

	again, err := s.Activate(ctx, principal, "space-1", a.ID, da.ID)
	require.NoError(t, err)
	require.Equal(t, r1.ID, again.ID)
	_, err = s.Activate(ctx, principal, "space-1", stale.ID, ds.ID)
	requireCode(t, err, release.ErrorNeedsRebase)

	var releases, receipts int64
	require.NoError(t, db.Table("wiki_releases").Count(&releases).Error)
	require.NoError(t, db.Table("wiki_release_receipts").Count(&receipts).Error)
	require.Equal(t, int64(2), releases, "neither the replay nor the stale candidate wrote a release")
	require.Equal(t, int64(2), receipts)
	head, err := s.Release(ctx, principal, "space-1", "")
	require.NoError(t, err)
	require.Equal(t, r2.ID, head.ID)
}
