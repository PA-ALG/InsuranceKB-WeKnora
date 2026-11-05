package memberstore_test

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/releasestore"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

func TestPostgresMigrationPreservesOriginalDatabaseCollationOrder(t *testing.T) {
	db := migrationDB(t)
	ctx := context.Background()
	down, err := os.ReadFile("../../../migrations/enterprise/versioned/000013_enterprise_member" +
		"_chunks.down.sql")
	require.NoError(t, err)
	require.NoError(t, db.Exec(string(down)).Error)
	input := historical(t, db, "collation", "page")
	require.NoError(t, db.Exec("ALTER TABLE wiki_release_members ALTER COLUMN logical_slug TYPE T"+
		"EXT COLLATE \"en-US-x-icu\"").
		Error)
	require.NoError(t, db.Where("release_id = ?", "collation").Delete(&types.WikiReleaseMember{}).Error)
	input[0].LogicalSlug = "item/ä"
	input[1].LogicalSlug = "item/z"
	raw, err := json.Marshal(input)
	require.NoError(t, err)
	require.NoError(t, db.Table("wiki_release_preparations").Where("preparation_id = ?", "prep-collation").
		Update("members", gorm.Expr("?::jsonb", string(raw))).Error)
	for _, m := range input {
		r := types.WikiReleaseMember{
			ID:        "collation:" + m.LogicalSlug,
			ReleaseID: "collation", Kind: m.Kind, LogicalSlug: m.LogicalSlug,
			RevisionID: m.RevisionID, MemberDigest: m.MemberDigest,
			Title: m.Title, Content: m.Content, Payload: m.Payload,
		}
		require.NoError(t, db.Create(&r).Error)
	}
	up, err := os.ReadFile("../../../migrations/enterprise/versioned/000013_enterprise_member_chunks.up.sql")
	require.NoError(t, err)
	require.NoError(t, db.Exec(string(up)).Error)
	var preparation types.WikiReleasePreparation
	require.NoError(t, db.Where("preparation_id=?", "prep-collation").Take(&preparation).Error)
	var manifest struct {
		CandidateID    string      `json:"candidate_id"`
		DecisionID     string      `json:"decision_id"`
		DecisionDigest string      `json:"decision_digest"`
		BundleDigest   string      `json:"bundle_digest"`
		Members        [][2]string `json:"members"`
	}
	require.NoError(t, json.Unmarshal(preparation.Manifest, &manifest))
	for i, m := range input {
		manifest.Members[i] = [2]string{m.LogicalSlug, m.MemberDigest}
	}
	manifestBytes, err := json.Marshal(manifest)
	require.NoError(t, err)
	hash := func(b []byte) string { d := sha256.Sum256(b); return hex.EncodeToString(d[:]) }
	digest := hash(manifestBytes)
	require.NoError(t, db.Table("wiki_release_preparations").Where("preparation_id=?", preparation.ID).
		Updates(map[string]any{
			"manifest": gorm.Expr("?::jsonb",
				string(manifestBytes)),
			"manifest_digest": digest, "preparation_digest": hash([]byte(fmt.Sprintf("%s|%s|%s||0",
				preparation.ID, digest, preparation.ReviewDecisionDigest))),
		}).
		Error)
	require.NoError(t, db.Table("wiki_releases").Where("release_id=?", "collation").
		Update("manifest_digest", digest).Error)
	original := legacyRows(t, db, "collation")
	require.Equal(t, "item/ä", original[0].LogicalSlug)
	store := releasestore.NewMemberStorage()
	require.NoError(t, store.Backfill(ctx, db, scope(), "collation", 1<<20))
	require.NoError(t, store.StartObservation(ctx, db, scope()))
	got, err := store.Read(ctx, db, scope(), "collation")
	require.NoError(t, err)
	for i := range original {
		require.Equal(t, original[i].Snapshot(), got[i])
	}
	require.NoError(t, db.Exec("UPDATE enterprise_member_scopes SET observation_started_at=CURREN"+
		"T_TIMESTAMP-INTERVAL '8 days'").
		Error)
	require.NoError(t, store.ReferenceOnly(ctx, db, scope()))
	require.NoError(t, store.CompactLegacy(ctx, db, scope()))
	require.NoError(t, store.RestoreLegacy(ctx, db, scope(), 1<<20))
	require.Equal(t, original, legacyRows(t, db, "collation"))
}
