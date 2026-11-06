package memberstore_test

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/releasestore"
	"github.com/stretchr/testify/require"
)

func TestPostgresRestoreRejectsPreparationRootAsRelease(t *testing.T) {
	db := migrationDB(t)
	ctx := context.Background()
	historical(t, db, "restore-wrong-root", "")
	s := releasestore.NewMemberStorage()
	require.NoError(t, s.Backfill(ctx, db, scope(), "restore-wrong-root", 1<<20))
	require.NoError(t, db.Exec("UPDATE enterprise_member_releases SET root_digest=(SELECT root_di"+
		"gest FROM enterprise_member_preparations)").Error)
	require.Error(t, s.RestoreLegacy(ctx, db, scope(), 1<<20))
	require.Equal(t, "page", legacyRows(t, db, "restore-wrong-root")[1].Kind)
	var marker string
	require.NoError(t, db.Table("wiki_releases").Select("member_storage").Scan(&marker).Error)
	require.NotEmpty(t, marker)
}

func TestPostgresReferenceFailureCanRestartFullObservation(t *testing.T) {
	db := migrationDB(t)
	ctx := context.Background()
	historical(t, db, "restart-reference", "page")
	s := releasestore.NewMemberStorage()
	require.NoError(t, s.Backfill(ctx, db, scope(), "restart-reference", 1<<20))
	require.NoError(t, s.StartObservation(ctx, db, scope()))
	require.NoError(t, db.Exec("UPDATE enterprise_member_scopes SET observation_started_at=CURREN"+
		"T_TIMESTAMP-INTERVAL '8 days'").Error)
	require.NoError(t, s.ReferenceOnly(ctx, db, scope()))
	require.NoError(t, db.Exec(`UPDATE enterprise_member_scopes SET read_failures=1`).Error)
	require.NoError(t, s.StartObservation(ctx, db, scope()))
	require.Error(t, s.ReferenceOnly(ctx, db, scope()))
	require.Error(t, s.CompactLegacy(ctx, db, scope()),
		"restarting cannot immediately compact before a full new window")
	require.NoError(t, db.Exec("UPDATE enterprise_member_scopes SET observation_started_at=CURREN"+
		"T_TIMESTAMP-INTERVAL '8 days'").Error)
	require.NoError(t, s.ReferenceOnly(ctx, db, scope()))
	require.NoError(t, s.CompactLegacy(ctx, db, scope()))
}
