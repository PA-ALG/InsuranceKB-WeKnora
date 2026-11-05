package memberstore_test

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/releasestore"
	"github.com/stretchr/testify/require"
)

func TestPostgresDowngradeRejectsUnresolvedValidationReservation(t *testing.T) {
	db := migrationDB(t)
	ctx := context.Background()
	historical(t, db, "down-observation", "page")
	s := releasestore.NewMemberStorage()
	require.NoError(t, s.Backfill(ctx, db, scope(), "down-observation", 1<<20))
	require.NoError(t, s.RestoreLegacy(ctx, db, scope(), 1<<20))
	require.NoError(t, db.Exec(`INSERT INTO enterprise_member_validation_pending
 (tenant_id,space_id,raw_kb_id,wiki_kb_id,attempt_id) VALUES(1,'space','raw','wiki','abandoned')`).Error)
	down, err := os.ReadFile(filepath.Join("../../../migrations/enterprise/versioned", "000013_enterprise_member_chunks.down.sql"))
	require.NoError(t, err)
	require.Error(t, db.Exec(string(down)).Error, "offline downgrade must not drop unresolved integrity evidence")
	require.Len(t, legacyRows(t, db, "down-observation"), 2)
	require.NoError(t, db.Exec(`WITH recorded AS (INSERT INTO enterprise_member_validation_failures
 (tenant_id,space_id,raw_kb_id,wiki_kb_id,attempt_id,kind)
 SELECT tenant_id,space_id,raw_kb_id,wiki_kb_id,attempt_id,'gap'
 FROM enterprise_member_validation_pending RETURNING attempt_id)
 DELETE FROM enterprise_member_validation_pending WHERE attempt_id IN(SELECT attempt_id FROM recorded)`).Error)
	require.NoError(t, db.Exec(string(down)).Error)
	require.Len(t, legacyRows(t, db, "down-observation"), 2)
}
