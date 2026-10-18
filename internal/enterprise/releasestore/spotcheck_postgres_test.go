package releasestore

// These tests require WEKNORA_TEST_POSTGRES_URL and use openSchema's fresh,
// disposable schema. A skip provides no PostgreSQL execution evidence.
import (
	"context"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/spotcheck"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

func spotCheckSchema(t *testing.T) (*gorm.DB, *Store) {
	t.Helper()
	db := openSchema(t)
	require.NoError(t, db.Exec(migrationSQL(t, "000008_enterprise_spot_checks.up.sql")).Error)
	spaces, err := ParseSpaces(`[
 {"tenant_id":7,"space_id":"space-1","raw_kb_id":"raw-1","wiki_kb_id":"wiki-1"},
 {"tenant_id":7,"space_id":"space-2","raw_kb_id":"raw-2","wiki_kb_id":"wiki-2"},
 {"tenant_id":8,"space_id":"space-1","raw_kb_id":"raw-3","wiki_kb_id":"wiki-3"},
 {"tenant_id":8,"space_id":"space-2","raw_kb_id":"raw-4","wiki_kb_id":"wiki-4"}]`)
	require.NoError(t, err)
	return db, New(db, spaces)
}

func spotSample(id, slug string) spotcheck.Sample {
	return spotcheck.Sample{
		ID: id, SpaceID: "space-1", ReleaseID: "rel-1", LogicalSlug: slug,
		MemberDigest: "digest-" + slug, Stratum: "opaque/stratum", CreatedBy: "svc-test",
		CreatedAt: time.Date(2026, 10, 18, 12, 0, 0, 0, time.UTC),
	}
}

func spotVerdict(id, sampleID string) spotcheck.Verdict {
	return spotcheck.Verdict{ID: id, SampleID: sampleID, Outcome: "correct", Note: "checked",
		Reviewer: "user:reviewer", DecidedAt: spotSample("", "").CreatedAt}
}

func spotIDs(samples []spotcheck.Sample) []string {
	out := make([]string, 0, len(samples))
	for _, sample := range samples {
		out = append(out, sample.ID)
	}
	return out
}

func TestPostgresSpotCheckPreservesFirstSampleAndReturnsInputOrder(t *testing.T) {
	_, store := spotCheckSchema(t)
	ctx := context.Background()
	input := []spotcheck.Sample{spotSample("b", "b"), spotSample("a", "a")}
	got, err := store.InsertSamples(ctx, 7, input)
	require.NoError(t, err)
	require.Equal(t, input, got)
	v := spotVerdict("verdict", "a")
	require.NoError(t, store.AppendVerdict(ctx, 7, "space-1", v))
	changed := input[1]
	changed.ID, changed.MemberDigest, changed.Stratum = "replacement", "changed-digest", "other"
	changed.CreatedBy, changed.CreatedAt = "another", changed.CreatedAt.Add(time.Hour)
	again, err := store.InsertSamples(ctx, 7, []spotcheck.Sample{changed, input[0]})
	require.NoError(t, err)
	want := input[1]
	want.Verdict = &v
	require.Equal(t, []spotcheck.Sample{want, input[0]}, again)
	listed, err := store.ListSamples(ctx, 7, "space-1", spotcheck.Filter{})
	require.NoError(t, err)
	require.Equal(t, []string{"a", "b"}, spotIDs(listed))
	otherRelease := spotSample("a-next-release", "a")
	otherRelease.ReleaseID = "rel-2"
	next, err := store.InsertSamples(ctx, 7, []spotcheck.Sample{otherRelease})
	require.NoError(t, err)
	require.Equal(t, []spotcheck.Sample{otherRelease}, next, "a new Release has its own sample identity")
	first, second := spotSample("first", "duplicate"), spotSample("second", "duplicate")
	duplicates, err := store.InsertSamples(ctx, 7, []spotcheck.Sample{first, second})
	require.NoError(t, err)
	require.Equal(t, []spotcheck.Sample{first, first}, duplicates)
}

func TestPostgresSpotCheckConcurrentOverlappingBatchesHaveOneWinner(t *testing.T) {
	db, store := spotCheckSchema(t)
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	type result struct {
		inputs, samples []spotcheck.Sample
		err             error
	}
	results := make(chan result, 8)
	start := make(chan struct{})
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			input := []spotcheck.Sample{
				spotSample(fmt.Sprintf("a-%d", i), "a"),
				spotSample(fmt.Sprintf("b-%d", i), "b"),
			}
			if i%2 == 1 {
				input[0], input[1] = input[1], input[0]
			}
			<-start
			got, err := store.InsertSamples(ctx, 7, input)
			results <- result{input, got, err}
		}(i)
	}
	close(start)
	wg.Wait()
	close(results)
	winners := map[string]string{}
	for r := range results {
		require.NoError(t, r.err)
		require.Len(t, r.samples, len(r.inputs))
		for i, sample := range r.samples {
			require.Equal(t, r.inputs[i].LogicalSlug, sample.LogicalSlug)
			if winner, ok := winners[sample.LogicalSlug]; ok {
				require.Equal(t, winner, sample.ID)
			} else {
				winners[sample.LogicalSlug] = sample.ID
			}
		}
	}
	var count int64
	require.NoError(t, db.Table("enterprise_samples").Count(&count).Error)
	require.EqualValues(t, 2, count)
}

func TestPostgresSpotCheckBatchRollsBackOnNonIdempotencyConflict(t *testing.T) {
	db, store := spotCheckSchema(t)
	ctx := context.Background()
	_, err := store.InsertSamples(ctx, 7, []spotcheck.Sample{spotSample("collision", "z")})
	require.NoError(t, err)
	// The first insert must roll back when the later, different logical sample
	// collides on the primary key. Only the four-column identity is idempotent.
	_, err = store.InsertSamples(ctx, 7, []spotcheck.Sample{spotSample("new", "a"), spotSample("collision", "b")})
	require.Error(t, err)
	listed, err := store.ListSamples(ctx, 7, "space-1", spotcheck.Filter{})
	require.NoError(t, err)
	require.Equal(t, []string{"collision"}, spotIDs(listed))
	// A database failure that is not a uniqueness conflict must also abort
	// every preceding row in the batch.
	require.NoError(t, db.Exec(`CREATE FUNCTION reject_spot_sample() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN IF NEW.logical_slug = 'b' THEN RAISE EXCEPTION 'sample rejected'; END IF; RETURN NEW; END $$;
CREATE TRIGGER reject_spot_sample BEFORE INSERT ON enterprise_samples
FOR EACH ROW EXECUTE FUNCTION reject_spot_sample();`).Error)
	_, err = store.InsertSamples(ctx, 7, []spotcheck.Sample{spotSample("new-a", "a"), spotSample("new-b", "b")})
	require.Error(t, err)
	listed, err = store.ListSamples(ctx, 7, "space-1", spotcheck.Filter{})
	require.NoError(t, err)
	require.Equal(t, []string{"collision"}, spotIDs(listed))
}

func TestPostgresSpotCheckIsolatesTwoTenantsAndTwoSpaces(t *testing.T) {
	_, store := spotCheckSchema(t)
	ctx := context.Background()
	for _, tenant := range []uint64{7, 8} {
		for _, space := range []string{"space-1", "space-2"} {
			sample := spotSample(fmt.Sprintf("%d-%s", tenant, space), "same-slug")
			sample.SpaceID = space
			got, err := store.InsertSamples(ctx, tenant, []spotcheck.Sample{sample})
			require.NoError(t, err)
			require.Equal(t, []spotcheck.Sample{sample}, got)
		}
	}
	for _, tenant := range []uint64{7, 8} {
		for _, space := range []string{"space-1", "space-2"} {
			id := fmt.Sprintf("%d-%s", tenant, space)
			listed, err := store.ListSamples(ctx, tenant, space, spotcheck.Filter{})
			require.NoError(t, err)
			require.Equal(t, []string{id}, spotIDs(listed))
			for _, other := range []string{"7-space-1", "7-space-2", "8-space-1", "8-space-2", "missing"} {
				if other == id {
					continue
				}
				_, found, err := store.SampleByID(ctx, tenant, space, other)
				require.NoError(t, err)
				require.False(t, found)
				err = store.AppendVerdict(ctx, tenant, space, spotVerdict(id+"-"+other, other))
				requireCode(t, err, spotcheck.ErrorSampleNotFound)
			}
			require.NoError(t, store.AppendVerdict(ctx, tenant, space, spotVerdict("v-"+id, id)))
			listed, err = store.ListSamples(ctx, tenant, space, spotcheck.Filter{Status: "decided"})
			require.NoError(t, err)
			require.Len(t, listed, 1)
			require.Equal(t, "v-"+id, listed[0].Verdict.ID)
		}
	}
}

func TestPostgresSpotCheckReadsLatestBySequenceAndFiltersStably(t *testing.T) {
	db, store := spotCheckSchema(t)
	ctx := context.Background()
	a, b, c := spotSample("a", "a"), spotSample("b", "b"), spotSample("c", "c")
	c.ReleaseID, c.CreatedAt = "rel-2", c.CreatedAt.Add(-time.Hour)
	_, err := store.InsertSamples(ctx, 7, []spotcheck.Sample{b, c, a})
	require.NoError(t, err)
	latest := spotVerdict("z-verdict", "a")
	for i, id := range []string{"z-verdict", "y-verdict", "a-verdict"} {
		latest.ID = id
		if i == 2 {
			latest.Outcome, latest.DecidedAt = "wrong", latest.DecidedAt.Add(-time.Hour)
		}
		require.NoError(t, store.AppendVerdict(ctx, 7, "space-1", latest))
	}
	got, found, err := store.SampleByID(ctx, 7, "space-1", "a")
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, &latest, got.Verdict)
	var count int64
	require.NoError(t, db.Table("enterprise_sample_verdicts").Count(&count).Error)
	require.EqualValues(t, 3, count)
	for _, tc := range []struct {
		filter spotcheck.Filter
		ids    []string
	}{
		{spotcheck.Filter{}, []string{"c", "a", "b"}},
		{spotcheck.Filter{Status: "pending"}, []string{"c", "b"}},
		{spotcheck.Filter{Status: "decided"}, []string{"a"}},
		{spotcheck.Filter{ReleaseID: "rel-1"}, []string{"a", "b"}},
		{spotcheck.Filter{Status: "pending", ReleaseID: "rel-1"}, []string{"b"}},
		{spotcheck.Filter{Status: "decided", ReleaseID: "rel-2"}, []string{}},
		{spotcheck.Filter{ReleaseID: "absent"}, []string{}},
	} {
		listed, err := store.ListSamples(ctx, 7, "space-1", tc.filter)
		require.NoError(t, err)
		require.NotNil(t, listed)
		require.Equal(t, tc.ids, spotIDs(listed))
		for _, sample := range listed {
			if sample.ID == "a" {
				require.Equal(t, &latest, sample.Verdict)
			} else {
				require.Nil(t, sample.Verdict)
			}
		}
	}
	latest.Outcome = "incomplete"
	require.Error(t, store.AppendVerdict(ctx, 7, "space-1", latest), "duplicate verdict ID must not overwrite")
	latest.ID, latest.Outcome = "invalid-outcome", "invalid"
	require.Error(t, store.AppendVerdict(ctx, 7, "space-1", latest))
	got, found, err = store.SampleByID(ctx, 7, "space-1", "a")
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, "wrong", got.Verdict.Outcome)
	empty, err := store.InsertSamples(ctx, 7, nil)
	require.NoError(t, err)
	require.NotNil(t, empty)
	require.Empty(t, empty)
}
