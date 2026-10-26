package releasestore

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

func activation(t *testing.T, store *Store, nonce string, refs ...string) release.ActivationWrite {
	t.Helper()
	head, err := store.Head(context.Background(), 7, "space-1")
	require.NoError(t, err)
	payload := json.RawMessage(`{"value":1}`)
	write := release.ActivationWrite{
		TenantID: 7, SpaceID: "space-1", Subject: "svc-test", CandidateID: "candidate-" + nonce,
		DecisionID: "decision-" + nonce, DecisionDigest: fileSHA, Nonce: nonce,
		Expected: head, Members: []release.Member{{
			Kind: "claim", LogicalSlug: "claim", Payload: payload, MemberDigest: memberDigest(t, string(payload)),
			EvidenceRefs: refs, AccessScope: "space",
		}},
	}
	// Distinct fixture candidates have distinct compiler identities, like real bundles.
	// Retry tests copy this write, keeping the digest while varying nonce/decision.
	bundle, err := json.Marshal(struct {
		Base     release.Head
		Compiler string
		Members  []release.Member
	}{head, "fixture/" + nonce, write.Members})
	require.NoError(t, err)
	write.BundleDigest = digestOf(bundle)
	return write
}

func retention(t *testing.T, db *gorm.DB, id string) string {
	t.Helper()
	var source types.KnowledgeRevisionSource
	require.NoError(t, db.Where("knowledge_id = ?", id).Take(&source).Error)
	return source.RetentionState
}

func rowCounts(t *testing.T, db *gorm.DB) map[string]int64 {
	t.Helper()
	out := map[string]int64{}
	for _, table := range []string{
		"wiki_release_preparations", "wiki_releases", "wiki_release_members", "wiki_release_heads",
		"wiki_release_receipts", "enterprise_release_sources", "enterprise_release_retirements",
	} {
		var count int64
		require.NoError(t, db.Table(table).Count(&count).Error)
		out[table] = count
	}
	return out
}

func TestPostgresActivationPinsInheritedMembersAndReplayWritesOnce(t *testing.T) {
	db := openSchema(t)
	ref2 := seedSource(t, db, "k-2", 7, "raw-1", 1)
	store := New(db, testSpaces(t))
	s, ctx := service(store), context.Background()
	publish := func(base, slug, ref string) release.Release {
		var bundle map[string]any
		require.NoError(t, json.Unmarshal(rawBundle(t, base, slug, `{"v":1}`), &bundle))
		bundle["members"].([]any)[0].(map[string]any)["evidence_refs"] = []string{ref, ref}
		raw, err := json.Marshal(bundle)
		require.NoError(t, err)
		candidate, err := s.Receive(ctx, principal, "space-1", raw)
		require.NoError(t, err)
		decision, err := s.Decide(ctx, principal, "space-1", candidate.ID, approve)
		require.NoError(t, err)
		rel, err := s.Activate(ctx, principal, "space-1", candidate.ID, decision.ID)
		require.NoError(t, err)
		return rel
	}
	first := publish("", "inherited", postgresSourceRef)
	second := publish(first.ID, "added", ref2)
	require.Len(t, second.Members, 2)
	var count int64
	require.NoError(t, db.Table("enterprise_release_sources").Where("release_id = ?", second.ID).Count(&count).Error)
	require.EqualValues(t, 2, count)
	require.Equal(t, "pinned", retention(t, db, "k-1"))
	require.Equal(t, "pinned", retention(t, db, "k-2"))
	pins, err := store.SourcePins(ctx, 7, "space-1", "k-1")
	require.NoError(t, err)
	require.Len(t, pins, 2)
	require.Less(t, pins[0].ReleaseID, pins[1].ReleaseID)
	for _, pin := range pins {
		require.Equal(t, pin.ReleaseID == second.ID, pin.Active)
	}
}

func TestPostgresUnavailableSourceLeavesAllActivationRowsAndHeadUnchanged(t *testing.T) {
	for _, broken := range []string{"missing", "deleting", "deleted", "tenant", "attempt", "resource", "binding"} {
		t.Run(broken, func(t *testing.T) {
			db := openSchema(t)
			ref := seedSource(t, db, "k-2", 7, "raw-1", 1)
			store := New(db, testSpaces(t))
			_, err := store.Activate(context.Background(), activation(t, store, "base"))
			require.NoError(t, err)
			switch broken {
			case "missing":
				ref = "source:v1:missing:1:" + fileSHA
			case "deleting":
				require.NoError(t, db.Exec("UPDATE knowledges SET parse_status = 'deleting' WHERE id = 'k-2'").Error)
			case "deleted":
				require.NoError(t, db.Exec("UPDATE knowledges SET deleted_at = now() WHERE id = 'k-2'").Error)
			case "tenant":
				require.NoError(t, db.Exec("UPDATE knowledges SET tenant_id = 8 WHERE id = 'k-2'").Error)
			case "attempt":
				ref = "source:v1:k-2:2:" + fileSHA
			case "resource":
				require.NoError(t, db.Exec(`UPDATE resources SET state = 'deleted'
WHERE id IN (SELECT resource_id FROM resource_bindings WHERE owner_id = 'k-2')`).Error)
			case "binding":
				require.NoError(t, db.Exec("DELETE FROM resource_bindings WHERE owner_id = 'k-2'").Error)
			}
			before := rowCounts(t, db)
			head, err := store.Head(context.Background(), 7, "space-1")
			require.NoError(t, err)
			_, err = store.Activate(context.Background(), activation(t, store, broken, postgresSourceRef, ref))
			var failure *release.Error
			require.ErrorAs(t, err, &failure)
			require.Equal(t, release.ErrorSourceUnavailable, failure.Code)
			require.Equal(t, before, rowCounts(t, db))
			after, err := store.Head(context.Background(), 7, "space-1")
			require.NoError(t, err)
			require.Equal(t, head, after)
			require.Equal(t, "released", retention(t, db, "k-1"))
		})
	}
}

func TestPostgresAssociationFailureRollsBackPinsReleaseAndHead(t *testing.T) {
	for _, existingHead := range []bool{false, true} {
		t.Run(fmt.Sprint(existingHead), func(t *testing.T) {
			db := openSchema(t)
			store := New(db, testSpaces(t))
			if existingHead {
				_, err := store.Activate(context.Background(), activation(t, store, "base"))
				require.NoError(t, err)
			}
			require.NoError(t, db.Exec(`CREATE FUNCTION reject_source_pin() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'association rejected'; END $$;
CREATE TRIGGER reject_source_pin BEFORE INSERT ON enterprise_release_sources
FOR EACH ROW EXECUTE FUNCTION reject_source_pin();`).Error)
			before := rowCounts(t, db)
			head, err := store.Head(context.Background(), 7, "space-1")
			require.NoError(t, err)
			_, err = store.Activate(context.Background(), activation(t, store, "fault", postgresSourceRef))
			require.Error(t, err)
			require.Equal(t, before, rowCounts(t, db))
			after, err := store.Head(context.Background(), 7, "space-1")
			require.NoError(t, err)
			require.Equal(t, head, after)
			require.Equal(t, "released", retention(t, db, "k-1"))
		})
	}
}

func TestPostgresRetirementReleasesOnlyLastUnsealedReferenceAndPreservesHistory(t *testing.T) {
	db := openSchema(t)
	sealedRef := seedSource(t, db, "k-sealed", 7, "raw-1", 1)
	var sealed types.KnowledgeRevisionSource
	require.NoError(t, db.Where("knowledge_id = 'k-sealed'").Take(&sealed).Error)
	pageCount := 1
	sealed.PageCount, sealed.RetentionState, sealed.ReleasedAt = &pageCount, "pinned", nil
	var err error
	sealed.BindingDigest, err = types.ComputeKnowledgeRevisionSourceBindingDigest(sealed)
	require.NoError(t, err)
	require.NoError(t, db.Model(&sealed).Where("knowledge_id = 'k-sealed'").Updates(map[string]any{
		"page_count": 1, "retention_state": "pinned", "released_at": nil, "binding_digest": sealed.BindingDigest,
	}).Error)
	store := New(db, testSpaces(t))
	ctx := context.Background()
	first, err := store.Activate(ctx, activation(t, store, "first", postgresSourceRef, sealedRef))
	require.NoError(t, err)
	second, err := store.Activate(ctx, activation(t, store, "second", postgresSourceRef))
	require.NoError(t, err)
	write := release.RetirementWrite{
		TenantID: 7, SpaceID: "space-1", ReleaseID: first.ID, Reason: "superseded", Subject: "admin",
	}
	record, err := store.Retire(ctx, write)
	require.NoError(t, err)
	require.Equal(t, "pinned", retention(t, db, "k-1"))
	require.Equal(t, "pinned", retention(t, db, "k-sealed"))
	write.Reason = "retry reason"
	again, err := store.Retire(ctx, write)
	require.NoError(t, err)
	require.Equal(t, record, again)
	history, err := store.ReleaseByID(ctx, 7, "space-1", first.ID)
	require.NoError(t, err)
	require.Equal(t, record.RetiredAt, *history.RetiredAt)
	require.Len(t, history.Members, 1)
	write.ReleaseID = second.ID
	_, err = store.Retire(ctx, write)
	var failure *release.Error
	require.ErrorAs(t, err, &failure)
	require.Equal(t, release.ErrorReleaseActive, failure.Code)
	_, err = store.Activate(ctx, activation(t, store, "empty"))
	require.NoError(t, err)
	_, err = store.Retire(ctx, write)
	require.NoError(t, err)
	require.Equal(t, "released", retention(t, db, "k-1"))
	require.Equal(t, "pinned", retention(t, db, "k-sealed"))
	pins, err := store.SourcePins(ctx, 7, "space-1", "k-1")
	require.NoError(t, err)
	require.Empty(t, pins)
	write.SpaceID = "space-2"
	_, err = store.Retire(ctx, write)
	require.ErrorAs(t, err, &failure)
	require.Equal(t, release.ErrorReleaseNotFound, failure.Code)
}

func TestPostgresNonceReplayAfterRetirementDoesNotRepinDeletedSource(t *testing.T) {
	db := openSchema(t)
	store := New(db, testSpaces(t))
	ctx := context.Background()
	write := activation(t, store, "original", postgresSourceRef)
	first, err := store.Activate(ctx, write)
	require.NoError(t, err)
	_, err = store.Activate(ctx, activation(t, store, "next"))
	require.NoError(t, err)
	_, err = store.Retire(ctx, release.RetirementWrite{
		TenantID: 7, SpaceID: "space-1", ReleaseID: first.ID, Reason: "done", Subject: "admin",
	})
	require.NoError(t, err)
	require.NoError(t, repository.NewKnowledgeRepository(db).DeleteKnowledge(ctx, 7, "k-1"))
	before := rowCounts(t, db)
	again, err := store.Activate(ctx, write)
	require.NoError(t, err)
	require.Equal(t, first.ID, again.ID)
	require.Equal(t, before, rowCounts(t, db))
	require.Equal(t, "released", retention(t, db, "k-1"))
	// A new decision/nonce still replays the retired release without repinning.
	write.Nonce, write.DecisionID, write.DecisionDigest = "historical-new-nonce", "new-decision", "new-digest"
	replay, err := store.Activate(ctx, write)
	require.NoError(t, err)
	require.Equal(t, again, replay)
	require.Equal(t, before, rowCounts(t, db))
}

func TestPostgresSourcePinMigrationRoundTrip(t *testing.T) {
	db := openSchema(t)
	seedSource(t, db, "k-sealed", 7, "raw-1", 1)
	var sealed types.KnowledgeRevisionSource
	require.NoError(t, db.Where("knowledge_id = 'k-sealed'").Take(&sealed).Error)
	pageCount := 1
	sealed.PageCount, sealed.RetentionState, sealed.ReleasedAt = &pageCount, "pinned", nil
	digest, err := types.ComputeKnowledgeRevisionSourceBindingDigest(sealed)
	require.NoError(t, err)
	require.NoError(t, db.Model(&sealed).Where("knowledge_id = 'k-sealed'").Updates(map[string]any{
		"page_count": 1, "binding_digest": digest, "retention_state": "pinned", "released_at": nil,
	}).Error)
	require.NoError(t, db.Exec(migrationSQL(t, "000007_release_source_pins.down.sql")).Error)
	require.False(t, db.Migrator().HasTable("enterprise_release_sources"))
	require.Equal(t, "pinned", retention(t, db, "k-1"))
	require.Equal(t, "pinned", retention(t, db, "k-sealed"))
	require.NoError(t, db.Exec(migrationSQL(t, "000007_release_source_pins.up.sql")).Error)
	require.True(t, db.Migrator().HasTable("enterprise_release_retirements"))
	require.Equal(t, "released", retention(t, db, "k-1"))
	require.Equal(t, "pinned", retention(t, db, "k-sealed"))
	var indexes int64
	require.NoError(t, db.Raw(`SELECT count(*) FROM pg_indexes WHERE schemaname = current_schema()
AND tablename = 'enterprise_release_sources' AND indexdef LIKE '%tenant_id, knowledge_id%'`).Scan(&indexes).Error)
	require.EqualValues(t, 1, indexes)
}

func TestPostgresRetirementRespectsReferencesInOtherSpaces(t *testing.T) {
	db := openSchema(t)
	store := New(db, testSpaces(t))
	ctx := context.Background()
	first, err := store.Activate(ctx, activation(t, store, "first", postgresSourceRef))
	require.NoError(t, err)
	other := activation(t, store, "other", postgresSourceRef)
	other.SpaceID, other.Expected = "space-2", release.Head{}
	_, err = store.Activate(ctx, other)
	require.NoError(t, err)
	_, err = store.Activate(ctx, activation(t, store, "next"))
	require.NoError(t, err)
	_, err = store.Retire(ctx, release.RetirementWrite{
		TenantID: 7, SpaceID: "space-1", ReleaseID: first.ID, Reason: "done", Subject: "admin",
	})
	require.NoError(t, err)
	require.Equal(t, "pinned", retention(t, db, "k-1"))
	pins, err := store.SourcePins(ctx, 7, "space-2", "k-1")
	require.NoError(t, err)
	expected := []release.SourcePin{{ReleaseID: "rel_" + shortDigest("other"), ParseAttempt: 1, Active: true}}
	require.Equal(t, expected, pins)
	pins, err = store.SourcePins(ctx, 8, "space-2", "k-1")
	require.Error(t, err, fmt.Sprint(pins))
}
