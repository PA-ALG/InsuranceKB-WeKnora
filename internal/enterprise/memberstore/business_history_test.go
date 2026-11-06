package memberstore_test

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/memberstore"
	"github.com/Tencent/WeKnora/internal/enterprise/releasestore"
	"github.com/stretchr/testify/require"
)

func TestPostgresBackfillRejectsUnreadableBusinessHistory(t *testing.T) {
	for _, sql := range []string{
		"UPDATE wiki_release_members SET member_digest=repeat('0',64) WHER" +
			"E logical_slug='a'",
		`UPDATE wiki_release_members SET content='{}' WHERE logical_slug='a'`,
		`UPDATE wiki_release_members SET payload='{"n":3}'::jsonb WHERE logical_slug='a'`,
		`UPDATE wiki_release_preparations SET manifest='{}'::jsonb`,
		`UPDATE wiki_releases SET candidate_digest='wrong'`,
		`UPDATE wiki_release_preparations SET preparation_digest='wrong'`,
		`UPDATE wiki_release_preparations SET members='[]'::jsonb`,
	} {
		t.Run(sql, func(t *testing.T) {
			db := migrationDB(t)
			historical(t, db, "invalid", "page")
			require.NoError(t, db.Exec(sql).Error)
			require.ErrorIs(t, releasestore.NewMemberStorage().Backfill(context.Background(),
				db, scope(), "invalid", 1<<20), memberstore.ErrIntegrity)
			var count int64
			require.NoError(t, db.Table("enterprise_member_releases").Count(&count).Error)
			require.Zero(t, count)
			require.Len(t, legacyRows(t, db, "invalid"), 2)
		})
	}
}

func TestPostgresOpaqueStorageCannotCertifyUnknownProtocol(t *testing.T) {
	db := migrationDB(t)
	historical(t, db, "unknown", "page")
	require.ErrorIs(t, memberstore.New().Backfill(context.Background(),
		db, scope(), "unknown", 1<<20), memberstore.ErrState)
}
