package releasestore

// S5b-3d-2 acceptance (protected, written by Claude): confirmation items keep their optional
// source reference through every store read, and migration 000012 rolls back (Spec
// docs/design/slices/S5b-3d-2-待确认材料打开原文件.md §2.1). Requires WEKNORA_TEST_POSTGRES_URL.

import (
	"context"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/confirm"
)

var confirmationSourceRef = "source:v1:k-raw-1:2:" + strings.Repeat("ab", 32)

func TestPostgresConfirmationSourceRefRoundTrips(t *testing.T) {
	_, store := confirmationSchema(t)
	ctx := context.Background()
	sourced := confirmationItem("s", "k-s")
	sourced.SourceRef = confirmationSourceRef
	plain := confirmationItem("p", "k-p")
	stored, err := store.InsertItems(ctx, 7, []confirm.Item{sourced, plain})
	require.NoError(t, err)
	require.Equal(t, confirmationSourceRef, stored[0].SourceRef)
	require.Empty(t, stored[1].SourceRef)

	listed, err := store.ListItems(ctx, 7, "space-1", confirm.Filter{Status: "open"})
	require.NoError(t, err)
	refs := map[string]string{}
	for _, item := range listed {
		refs[item.ID] = item.SourceRef
	}
	require.Equal(t, map[string]string{"s": confirmationSourceRef, "p": ""}, refs)
	one, found, err := store.ItemByID(ctx, 7, "space-1", "s")
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, confirmationSourceRef, one.SourceRef)
}

func TestPostgresConfirmationItemsWrittenBefore000012ReadWithoutASource(t *testing.T) {
	db, store := confirmationSchema(t)
	require.NoError(t, db.Exec(`INSERT INTO enterprise_confirmations
(id, tenant_id, space_id, subject, revision, content_digest, title, detail, options, created_by, created_at)
VALUES ('old', 7, 'space-1', 'k-old', '1:rev', 'digest', '标题', '',
        '[{"key":"ignore","label":"忽略"}]', 'svc', now())`).Error)
	item, found, err := store.ItemByID(context.Background(), 7, "space-1", "old")
	require.NoError(t, err)
	require.True(t, found)
	require.Empty(t, item.SourceRef)
}

func TestPostgresConfirmationSourceMigrationRollsBack(t *testing.T) {
	db, _ := confirmationSchema(t)
	require.True(t, db.Migrator().HasColumn("enterprise_confirmations", "source_ref"))
	require.NoError(t, db.Exec(migrationSQL(t, "000012_enterprise_confirmation_sources.down.sql")).Error)
	require.False(t, db.Migrator().HasColumn("enterprise_confirmations", "source_ref"))
	require.True(t, db.Migrator().HasTable("enterprise_confirmations"), "rolling back keeps the items")
	require.NoError(t, db.Exec(migrationSQL(t, "000012_enterprise_confirmation_sources.up.sql")).Error)
	require.True(t, db.Migrator().HasColumn("enterprise_confirmations", "source_ref"))
}
