package memberstore_test

import (
	"context"
	"os"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/releasestore"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

func restoredDownFixture(t *testing.T) (*gorm.DB, string) {
	t.Helper()
	db := migrationDB(t)
	historical(t, db, "down-check", "")
	store := releasestore.NewMemberStorage()
	require.NoError(t, store.Backfill(context.Background(), db, scope(), "down-check", 1<<20))
	require.NoError(t, store.RestoreLegacy(context.Background(), db, scope(), 1<<20))
	raw, err := os.ReadFile("../../../migrations/enterprise/versioned/000013_enterprise_member" +
		"_chunks.down.sql")
	require.NoError(t, err)
	var markers int64
	require.NoError(t, db.Raw(`SELECT count(*) FROM wiki_releases WHERE member_storage <> ''`).Scan(&markers).Error)
	require.Zero(t, markers, "the final gate must verify restored data after markers were cleared")
	return db, string(raw)
}

func TestPostgresDownRejectsRestoredCopyDriftAndBrokenNewStorage(t *testing.T) {
	mutations := map[string]string{
		"missing release mapping": `DELETE FROM enterprise_member_releases`,
		"missing release mapping with missing member": "DELETE FROM enterprise_member_releases; " +
			"DELETE FROM wiki_release_members WHERE logical_slug='a'",
		"missing preparation mapping": `DELETE FROM enterprise_member_preparations`,
		"missing legacy member":       `DELETE FROM wiki_release_members WHERE logical_slug='a'`,
		"extra legacy member": "INSERT INTO wiki_release_members SELECT id||':extra',release_id,k" +
			"ind,\n logical_slug||':extra',revision_id,member_digest,title,cont" +
			"ent,payload FROM wiki_release_members WHERE logical_slug='a'",
		"preparation order": "UPDATE wiki_release_preparations SET members=jsonb_build_array(me" +
			"mbers->1,members->0)",
		"preparation member count": `UPDATE wiki_release_preparations SET members=members-0`,
		"preparation string bytes": "UPDATE wiki_release_preparations SET members=jsonb_set(members,'{" +
			"0,title}','\"changed\"')",
		"preparation payload precision": "UPDATE wiki_release_preparations SET members=jsonb_set(members,'{" +
			"0,payload,n}','9007199254740992')",
		"content hash":    `UPDATE enterprise_member_contents SET title='changed' WHERE logical_slug='a'`,
		"missing content": `DELETE FROM enterprise_member_contents WHERE kind=''`,
		"chunk hash": "UPDATE enterprise_member_chunks SET refs=substring(refs FROM 33 F" +
			"OR 32)||substring(refs FROM 1 FOR 32)",
		"missing chunk": `DELETE FROM enterprise_member_chunks`,
		"root hash":     `UPDATE enterprise_member_sets SET blocks=set_byte(blocks,4,get_byte(blocks,4)#1)`,

		"root total": `UPDATE enterprise_member_sets SET member_count=member_count+1`,
		"release root order": "UPDATE enterprise_member_sets SET order_mode='legacy_sequence' WH" +
			"ERE order_mode='slug_asc'",
		"unverified owner": `UPDATE enterprise_member_releases SET verified=false`,
	}
	for _, field := range []string{"kind", "logical_slug", "revision_id", "member_digest", "title", "content"} {
		mutations["legacy "+field] = "UPDATE wiki_release_members SET " +
			field + "=" + field + "||'changed' WHERE logical_slug='a'"
	}
	mutations["legacy payload precision"] = "UPDATE wiki_release_members SET payload='{\"n\":9007199254740993}' " +
		"WHERE logical_slug='a'"
	for name, mutation := range mutations {
		t.Run(name, func(t *testing.T) {
			db, down := restoredDownFixture(t)
			require.NoError(t, db.Exec(mutation).Error)
			err := db.Exec(down).Error
			require.Error(t, err, "down must retain the new readable history when restored data drifts")
			require.True(t, db.Migrator().HasTable("enterprise_member_contents"), "a failed down must be atomic")
			require.True(t, db.Migrator().HasColumn("wiki_releases", "member_storage"))
		})
	}
}

func TestPostgresDownAcceptsCompleteRestorationAndHoldsMemberLock(t *testing.T) {
	db, down := restoredDownFixture(t)
	original := legacyRows(t, db, "down-check")
	var preparationBefore string
	require.NoError(t, db.Raw(`SELECT members::text FROM wiki_release_preparations`).Scan(&preparationBefore).Error)
	tx := db.Begin()
	require.NoError(t, tx.Error)
	t.Cleanup(func() { _ = tx.Rollback().Error })
	require.NoError(t, tx.Exec(down).Error, "complete restoration must allow down")
	writerErr := db.Transaction(func(writer *gorm.DB) error {
		if err := writer.Exec(`SET LOCAL lock_timeout='100ms'`).Error; err != nil {
			return err
		}
		return writer.Exec(`UPDATE wiki_release_members SET title='racing' WHERE logical_slug='a'`).Error
	})
	require.Error(t, writerErr, "member writes must remain blocked between final validation and commit")
	require.Contains(t, strings.ToLower(writerErr.Error()), "lock timeout")
	require.NoError(t, tx.Commit().Error)
	require.Equal(t, original, legacyRows(t, db, "down-check"))
	var preparationAfter string
	require.NoError(t, db.Raw(`SELECT members::text FROM wiki_release_preparations`).Scan(&preparationAfter).Error)
	require.Equal(t, preparationBefore, preparationAfter)
	require.False(t, db.Migrator().HasTable("enterprise_member_sets"))
}
