package releasestore

// RV6b acceptance (protected, written by Claude): an approval's point decisions are written in the
// activation transaction, each point is decided once, rejections are all or none (Spec
// docs/design/slices/RV6b-逐字段审核平台.md §3, §5.3). Requires WEKNORA_TEST_POSTGRES_URL.

import (
	"context"
	"errors"
	"sync"
	"testing"

	"github.com/stretchr/testify/require"
	"gorm.io/gorm"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

func memberDecided(t *testing.T, err error) {
	t.Helper()
	var failure *release.Error
	require.True(t, errors.As(err, &failure), "%v", err)
	require.Equal(t, release.ErrorMemberDecided, failure.Code)
}

func point(c release.Candidate, slug, outcome string) release.PointDecision {
	return release.PointDecision{
		TenantID: 7, SpaceID: c.SpaceID, CandidateID: c.ID, Slug: slug,
		Outcome: outcome, Reason: "checked", Subject: "user-1",
	}
}

func countReleases(t *testing.T, db *gorm.DB) int64 {
	t.Helper()
	var n int64
	require.NoError(t, db.Table("wiki_releases").Count(&n).Error)
	return n
}

// pointWorld publishes a seed, then stores a candidate on it whose single member b is one point.
func pointWorld(t *testing.T) (*gorm.DB, *Store, release.Release, release.Candidate) {
	t.Helper()
	db := openSchema(t)
	store := New(db, testSpaces(t))
	s, ctx := service(store), context.Background()
	seed, err := s.Receive(ctx, principal, "space-1", rawBundle(t, "", "a", `{"v":1}`))
	require.NoError(t, err)
	d, err := s.Decide(ctx, principal, "space-1", seed.ID, approve)
	require.NoError(t, err)
	first, err := s.Activate(ctx, principal, "space-1", seed.ID, d.ID)
	require.NoError(t, err)
	c, err := s.Receive(ctx, principal, "space-1", rawBundle(t, first.ID, "b", `{"v":2}`))
	require.NoError(t, err)
	return db, store, first, c
}

func pointActivation(t *testing.T, store *Store, base release.Release, c release.Candidate, batch string,
	points ...release.PointDecision,
) release.ActivationWrite {
	t.Helper()
	b, err := store.BundleOf(context.Background(), 7, "space-1", c.ID)
	require.NoError(t, err)
	head, err := store.Head(context.Background(), 7, "space-1")
	require.NoError(t, err)
	members := append([]release.Member{}, b.Members...)
	for _, m := range base.Members {
		if m.LogicalSlug != b.Members[0].LogicalSlug {
			members = append(members, m)
		}
	}
	return release.ActivationWrite{
		TenantID: 7, SpaceID: "space-1", Subject: "user-1", CandidateID: c.ID,
		BundleDigest: digestOf([]byte(c.BundleDigest + "|" + batch)), DecisionID: "points-" + batch,
		DecisionDigest: digestOf([]byte("decision|" + batch)), Nonce: digestOf([]byte(c.ID + ":" + batch)),
		Expected: head, Members: members,
		Points: points,
	}
}

func TestPostgresActivationWritesItsPointDecisionsInTheSameTransaction(t *testing.T) {
	db, store, first, c := pointWorld(t)
	ctx := context.Background()
	write := pointActivation(t, store, first, c, "batch-1", point(c, "b", "approve"))
	r, err := store.Activate(ctx, write)
	require.NoError(t, err)

	decisions, err := store.PointDecisions(ctx, 7, "space-1", c.ID)
	require.NoError(t, err)
	require.Len(t, decisions, 1)
	require.Equal(t, "b", decisions[0].Slug)
	require.Equal(t, "approve", decisions[0].Outcome)
	require.Equal(t, r.ID, decisions[0].ReleaseID)
	require.Equal(t, "user-1", decisions[0].Subject)
	require.NotEmpty(t, decisions[0].ID)
	require.False(t, decisions[0].CreatedAt.IsZero())
	other, err := store.PointDecisions(ctx, 7, "space-2", c.ID)
	require.NoError(t, err)
	require.Empty(t, other, "point decisions are isolated by Space")

	// The same batch again is the same release, with no second decision.
	again, err := store.Activate(ctx, write)
	require.NoError(t, err)
	require.Equal(t, r.ID, again.ID)
	releases := countReleases(t, db)

	// Another batch naming a decided point publishes nothing and writes nothing.
	second := pointActivation(t, store, r, c, "batch-2", point(c, "b", "approve"))
	_, err = store.Activate(ctx, second)
	memberDecided(t, err)
	head, err := store.Head(ctx, 7, "space-1")
	require.NoError(t, err)
	require.Equal(t, r.ID, head.ReleaseID)
	require.Equal(t, releases, countReleases(t, db))
	decisions, err = store.PointDecisions(ctx, 7, "space-1", c.ID)
	require.NoError(t, err)
	require.Len(t, decisions, 1)
}

func TestPostgresRejectingPointsIsAllOrNoneAndOncePerPoint(t *testing.T) {
	db, store, _, c := pointWorld(t)
	ctx := context.Background()
	releases := countReleases(t, db)
	require.NoError(t, store.RejectPoints(ctx, []release.PointDecision{
		point(c, "b", "reject"), point(c, "c", "reject"),
	}))
	decisions, err := store.PointDecisions(ctx, 7, "space-1", c.ID)
	require.NoError(t, err)
	require.Len(t, decisions, 2)
	for _, d := range decisions {
		require.Equal(t, "reject", d.Outcome)
		require.Empty(t, d.ReleaseID, "a rejection has no release")
	}

	memberDecided(t, store.RejectPoints(ctx, []release.PointDecision{point(c, "e", "reject"), point(c, "b", "reject")}))
	decisions, err = store.PointDecisions(ctx, 7, "space-1", c.ID)
	require.NoError(t, err)
	require.Len(t, decisions, 2, "the undecided point of a refused batch is not written")

	var wg sync.WaitGroup
	results := make(chan error, 8)
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			results <- store.RejectPoints(ctx, []release.PointDecision{point(c, "f", "reject")})
		}()
	}
	wg.Wait()
	close(results)
	succeeded := 0
	for err := range results {
		if err == nil {
			succeeded++
			continue
		}
		memberDecided(t, err)
	}
	require.Equal(t, 1, succeeded, "concurrent decisions on one point: the first wins")
	decisions, err = store.PointDecisions(ctx, 7, "space-1", c.ID)
	require.NoError(t, err)
	require.Len(t, decisions, 3)
	require.Equal(t, releases, countReleases(t, db), "rejections publish nothing")
}

func TestPostgresPointDecisionMigrationRollsBack(t *testing.T) {
	db := openSchema(t)
	require.NoError(t, db.Exec(migrationSQL(t, "000011_enterprise_point_decisions.down.sql")).Error)
	var exists bool
	require.NoError(t, db.Raw(
		"SELECT to_regclass('enterprise_point_decisions') IS NOT NULL").Scan(&exists).Error)
	require.False(t, exists)
	require.NoError(t, db.Exec(migrationSQL(t, "000011_enterprise_point_decisions.up.sql")).Error)
}
