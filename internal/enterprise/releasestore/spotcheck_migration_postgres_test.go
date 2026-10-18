package releasestore

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/spotcheck"
	"github.com/stretchr/testify/require"
)

func TestPostgresSpotCheckMigrationRoundTripPreservesReleaseAndHead(t *testing.T) {
	db := openSchema(t)
	store := New(db, testSpaces(t))
	ctx := context.Background()
	released, err := store.Activate(ctx, activation(t, store, "before-spot-checks", postgresSourceRef))
	require.NoError(t, err)
	head, err := store.Head(ctx, 7, "space-1")
	require.NoError(t, err)
	before := rowCounts(t, db)
	require.NoError(t, db.Exec(migrationSQL(t, "000008_enterprise_spot_checks.up.sql")).Error)
	sample := spotSample("sample", "claim")
	sample.ReleaseID = released.ID
	_, err = store.InsertSamples(ctx, 7, []spotcheck.Sample{sample})
	require.NoError(t, err)
	require.NoError(t, store.AppendVerdict(ctx, 7, "space-1", spotVerdict("verdict", sample.ID)))
	require.Equal(t, before, rowCounts(t, db))
	require.NoError(t, db.Exec(migrationSQL(t, "000008_enterprise_spot_checks.down.sql")).Error)
	require.False(t, db.Migrator().HasTable("enterprise_sample_verdicts"))
	require.False(t, db.Migrator().HasTable("enterprise_samples"))
	require.Equal(t, before, rowCounts(t, db))
	after, err := store.ReleaseByID(ctx, 7, "space-1", released.ID)
	require.NoError(t, err)
	require.Equal(t, released, after)
	afterHead, err := store.Head(ctx, 7, "space-1")
	require.NoError(t, err)
	require.Equal(t, head, afterHead)
	require.NoError(t, db.Exec(migrationSQL(t, "000008_enterprise_spot_checks.up.sql")).Error)
	empty, err := store.ListSamples(ctx, 7, "space-1", spotcheck.Filter{})
	require.NoError(t, err)
	require.NotNil(t, empty)
	require.Empty(t, empty)
	_, err = store.InsertSamples(ctx, 7, []spotcheck.Sample{sample})
	require.NoError(t, err)
	require.NoError(t, store.AppendVerdict(ctx, 7, "space-1", spotVerdict("after-up", sample.ID)))
	require.Equal(t, before, rowCounts(t, db))
}

func TestPostgresSpotCheckMigrationEnforcesIdentityAndVerdictConstraints(t *testing.T) {
	db, store := spotCheckSchema(t)
	ctx := context.Background()
	_, err := store.InsertSamples(ctx, 7, []spotcheck.Sample{spotSample("sample", "claim")})
	require.NoError(t, err)
	var seqColumn struct {
		DataType, IsNullable, IdentityGeneration string
	}
	require.NoError(t, db.Raw(`SELECT data_type, is_nullable, identity_generation
FROM information_schema.columns WHERE table_schema = current_schema()
AND table_name = 'enterprise_sample_verdicts' AND column_name = 'seq'`).Scan(&seqColumn).Error)
	require.Equal(t, "bigint", seqColumn.DataType)
	require.Equal(t, "NO", seqColumn.IsNullable)
	require.Equal(t, "ALWAYS", seqColumn.IdentityGeneration)
	var nullable int64
	require.NoError(t, db.Raw(`SELECT count(*) FROM information_schema.columns
WHERE table_schema = current_schema() AND table_name IN ('enterprise_samples', 'enterprise_sample_verdicts')
AND is_nullable = 'YES'`).Scan(&nullable).Error)
	require.Zero(t, nullable)
	var indexes int64
	require.NoError(t, db.Raw(`SELECT count(*) FROM pg_indexes WHERE schemaname = current_schema()
AND tablename = 'enterprise_sample_verdicts' AND indexdef LIKE '%(sample_id, seq)%'`).Scan(&indexes).Error)
	require.EqualValues(t, 1, indexes)
	// Database constraints reject rows even when bypassing the adapter.
	verdictSQL := `INSERT INTO enterprise_sample_verdicts
(id, tenant_id, space_id, sample_id, outcome, note, reviewer, decided_at)
VALUES (?, 7, 'space-1', ?, ?, '', 'reviewer', now())`
	require.Error(t, db.Exec(verdictSQL, "missing-parent", "absent", "correct").Error)
	require.Error(t, db.Exec(verdictSQL, "wrong-outcome", "sample", "unknown").Error)
	require.Error(t, db.Exec(`INSERT INTO enterprise_sample_verdicts
(id, seq, tenant_id, space_id, sample_id, outcome, note, reviewer, decided_at)
VALUES ('explicit-seq', 1, 7, 'space-1', 'sample', 'correct', '', 'reviewer', now())`).Error)
	require.NoError(t, store.AppendVerdict(ctx, 7, "space-1", spotVerdict("first", "sample")))
	require.NoError(t, store.AppendVerdict(ctx, 7, "space-1", spotVerdict("second", "sample")))
	var seqs []int64
	require.NoError(t, db.Table("enterprise_sample_verdicts").Order("seq").Pluck("seq", &seqs).Error)
	require.Len(t, seqs, 2)
	require.Less(t, seqs[0], seqs[1])
	// The sequence's uniqueness is enforced separately from the verdict PK.
	require.Error(t, db.Exec(`INSERT INTO enterprise_sample_verdicts
(id, seq, tenant_id, space_id, sample_id, outcome, note, reviewer, decided_at)
OVERRIDING SYSTEM VALUE
VALUES ('duplicate-seq', ?, 7, 'space-1', 'sample', 'correct', '', 'reviewer', now())`, seqs[0]).Error)
	var count int64
	require.NoError(t, db.Table("enterprise_sample_verdicts").Count(&count).Error)
	require.EqualValues(t, 2, count)
}
