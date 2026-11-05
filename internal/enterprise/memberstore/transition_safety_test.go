package memberstore_test

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/memberstore"
	"github.com/Tencent/WeKnora/internal/enterprise/releasestore"
	"github.com/stretchr/testify/require"
)

func TestPostgresFailedTransitionInvalidatesObservationAndCompaction(t *testing.T) {
	db := migrationDB(t)
	ctx := context.Background()
	historical(t, db, "transition", "page")
	s := releasestore.NewMemberStorage()
	require.NoError(t, s.Backfill(ctx, db, scope(), "transition", 1<<20))
	require.NoError(t, s.StartObservation(ctx, db, scope()))
	require.NoError(t, db.Exec("UPDATE enterprise_member_scopes SET observation_started_at=CURREN"+
		"T_TIMESTAMP-INTERVAL '8 days'").
		Error)
	require.NoError(t, db.Exec(`UPDATE enterprise_member_contents SET title='bad' WHERE logical_slug='a'`).Error)
	require.Error(t, s.ReferenceOnly(ctx, db, scope()))
	require.NoError(t, db.Exec(`UPDATE enterprise_member_contents SET title='' WHERE logical_slug='a'`).Error)
	require.Error(t, s.ReferenceOnly(ctx, db, scope()), "repair must not revive an expired observation window")
	require.NoError(t, s.StartObservation(ctx, db, scope()))
	require.NoError(t, db.Exec("UPDATE enterprise_member_scopes SET observation_started_at=CURREN"+
		"T_TIMESTAMP-INTERVAL '8 days'").
		Error)
	require.NoError(t, s.ReferenceOnly(ctx, db, scope()))
	require.NoError(t, db.Exec(`UPDATE enterprise_member_scopes SET read_failures=1`).Error)
	require.Error(t, s.CompactLegacy(ctx, db, scope()), "a failed observation must retain redundant copies")
	require.Len(t, legacyRows(t, db, "transition"), 2)
}

func TestPostgresBackfillRechecksSourceAfterObjectWrites(t *testing.T) {
	db := migrationDB(t)
	ctx := context.Background()
	historical(t, db, "during", "page")
	require.NoError(t, db.Exec("CREATE FUNCTION st1_source_drift() RETURNS trigger LANGUAGE plpgs"+
		"ql AS $$ BEGIN\n UPDATE wiki_release_members SET title='changed' W"+
		"HERE release_id='during' AND logical_slug='a'; RETURN NEW; END $$"+
		";\n CREATE TRIGGER st1_source_drift AFTER INSERT ON enterprise_mem"+
		"ber_sets FOR EACH ROW EXECUTE FUNCTION st1_source_drift()").Error)
	require.ErrorIs(t, releasestore.NewMemberStorage().Backfill(ctx,
		db, scope(), "during", 1<<20), memberstore.ErrIntegrity)
	var count int64
	require.NoError(t, db.Table("enterprise_member_releases").Count(&count).Error)
	require.Zero(t, count)
	require.Equal(t, "", legacyRows(t, db, "during")[0].Title, "source and partial new data roll back together")
}
