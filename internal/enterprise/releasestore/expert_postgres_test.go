package releasestore

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/expert"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// expertRevision's before value mixes JSON types and HTML-escaped characters: the record must
// still hash to its digest after a PostgreSQL round trip, since citations recompute it.
func expertRevision(id string) expert.Revision {
	r := expert.Revision{
		ID: id, TenantID: 7, SpaceID: "space-1", BaseReleaseID: "rel-1", MemberSlug: "claim",
		BaseMemberDigest: "digest-claim", Actor: "web_user:expert", Role: "admin",
		RecordedAt: time.Date(2026, 10, 22, 9, 30, 0, 123456000, time.UTC),
		Before: expert.Value{State: "present", Value: map[string]any{
			"days": 90.0, "note": "<a & b>", "list": []any{"x", 1.5, nil, true},
		}},
		After:  expert.Value{State: "present", Value: "new value"},
		Reason: "checked against the filed terms",
	}
	r.RecordSHA256 = r.ContentDigest()
	return r
}

func requireExpertCode(t *testing.T, err error, code string) {
	t.Helper()
	var typed *release.Error
	require.True(t, errors.As(err, &typed), "%v", err)
	require.Equal(t, code, typed.Code)
}

func TestPostgresExpertRevisionRoundTripAndIsolation(t *testing.T) {
	db := openSchema(t)
	require.NoError(t, db.Exec(migrationSQL(t, "000009_enterprise_expert_revisions.up.sql")).Error)
	store := New(db, testSpaces(t))
	ctx := context.Background()
	record := expertRevision("rev-1")
	require.NoError(t, store.CreateRevision(ctx, record))

	got, err := store.RevisionByID(ctx, 7, "space-1", "rev-1")
	require.NoError(t, err)
	require.Equal(t, record, got)
	require.Equal(t, got.RecordSHA256, got.ContentDigest(), "the stored record still hashes to its digest")

	_, err = store.RevisionByID(ctx, 7, "space-2", "rev-1")
	requireExpertCode(t, err, release.ErrorEvidenceNotFound)
	_, err = store.RevisionByID(ctx, 8, "space-1", "rev-1")
	requireExpertCode(t, err, release.ErrorEvidenceNotFound)
	_, err = store.RevisionByID(ctx, 7, "space-1", "missing")
	requireExpertCode(t, err, release.ErrorEvidenceNotFound)

	again := expertRevision("rev-1")
	again.Reason = "an overwrite attempt"
	require.Error(t, store.CreateRevision(ctx, again), "records are immutable")
	unchanged, err := store.RevisionByID(ctx, 7, "space-1", "rev-1")
	require.NoError(t, err)
	require.Equal(t, record, unchanged)

	foreign := expertRevision("rev-2")
	foreign.TenantID = 9
	requireExpertCode(t, store.CreateRevision(ctx, foreign), release.ErrorReleaseAccessDenied)
	var count int64
	require.NoError(t, db.Table("enterprise_expert_revisions").Count(&count).Error)
	require.EqualValues(t, 1, count)
}

func TestPostgresExpertRevisionMigrationRoundTripPreservesReleaseAndHead(t *testing.T) {
	db := openSchema(t)
	store := New(db, testSpaces(t))
	ctx := context.Background()
	released, err := store.Activate(ctx, activation(t, store, "before-expert-revisions", postgresSourceRef))
	require.NoError(t, err)
	head, err := store.Head(ctx, 7, "space-1")
	require.NoError(t, err)
	before := rowCounts(t, db)

	require.NoError(t, db.Exec(migrationSQL(t, "000009_enterprise_expert_revisions.up.sql")).Error)
	require.NoError(t, store.CreateRevision(ctx, expertRevision("rev-1")))
	require.Equal(t, before, rowCounts(t, db))
	require.NoError(t, db.Exec(migrationSQL(t, "000009_enterprise_expert_revisions.down.sql")).Error)
	require.False(t, db.Migrator().HasTable("enterprise_expert_revisions"))
	require.Equal(t, before, rowCounts(t, db))

	after, err := store.ReleaseByID(ctx, 7, "space-1", released.ID)
	require.NoError(t, err)
	require.Equal(t, released, after)
	afterHead, err := store.Head(ctx, 7, "space-1")
	require.NoError(t, err)
	require.Equal(t, head, afterHead)

	require.NoError(t, db.Exec(migrationSQL(t, "000009_enterprise_expert_revisions.up.sql")).Error)
	_, err = store.RevisionByID(ctx, 7, "space-1", "rev-1")
	requireExpertCode(t, err, release.ErrorEvidenceNotFound)
	require.NoError(t, store.CreateRevision(ctx, expertRevision("rev-1")))
}
