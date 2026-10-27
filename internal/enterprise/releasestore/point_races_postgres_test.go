package releasestore

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

// Hold the first candidate mode lock until the contender reaches that same lock.
// Each contender already passed any optimistic service reads at this point.
func racePointMode(t *testing.T, db *gorm.DB, first, second func(context.Context) error) (error, error) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	held, attempted, proceed := make(chan struct{}), make(chan struct{}), make(chan struct{})
	var one, two, three sync.Once
	unblock := func() { three.Do(func() { close(proceed) }) }
	defer unblock()
	isMode := func(tx *gorm.DB) bool {
		return strings.Contains(tx.Statement.SQL.String(), "pg_advisory_xact_lock") && len(tx.Statement.Vars) == 1 &&
			strings.HasPrefix(tx.Statement.Vars[0].(string), `["review",`)
	}
	require.NoError(t, db.Callback().Raw().After("gorm:raw").Register("point_hold", func(tx *gorm.DB) {
		if isMode(tx) && tx.Error == nil && tx.Statement.Context.Value(raceActorKey{}) == "first" {
			one.Do(func() {
				close(held)
				select {
				case <-proceed:
				case <-ctx.Done():
				}
			})
		}
	}))
	require.NoError(t, db.Callback().Raw().Before("gorm:raw").Register("point_contend", func(tx *gorm.DB) {
		if isMode(tx) && tx.Statement.Context.Value(raceActorKey{}) == "second" {
			two.Do(func() { close(attempted) })
		}
	}))
	t.Cleanup(func() {
		require.NoError(t, db.Callback().Raw().Remove("point_hold"))
		require.NoError(t, db.Callback().Raw().Remove("point_contend"))
	})
	a, b := make(chan error, 1), make(chan error, 1)
	go func() { a <- first(context.WithValue(ctx, raceActorKey{}, "first")) }()
	select {
	case <-held:
	case err := <-a:
		t.Fatalf("first skipped lock: %v", err)
	case <-ctx.Done():
		t.Fatal(ctx.Err())
	}
	go func() { b <- second(context.WithValue(ctx, raceActorKey{}, "second")) }()
	select {
	case <-attempted:
	case err := <-b:
		t.Fatalf("second skipped lock: %v", err)
	case <-ctx.Done():
		t.Fatal(ctx.Err())
	}
	unblock()
	var x, y error
	select {
	case x = <-a:
	case <-ctx.Done():
		t.Fatal(ctx.Err())
	}
	select {
	case y = <-b:
	case <-ctx.Done():
		t.Fatal(ctx.Err())
	}
	return x, y
}

func TestPostgresPointAndWholeWritesExcludeEachOtherUnderContention(t *testing.T) {
	for _, pointOutcome := range []string{"approve", "reject"} {
		for _, wholeAction := range []string{"decide", "activate"} {
			for _, pointFirst := range []bool{false, true} {
				name := pointOutcome + "/" + wholeAction + "/whole-first"
				if pointFirst {
					name = pointOutcome + "/" + wholeAction + "/point-first"
				}
				t.Run(name, func(t *testing.T) {
					db, store, base, c := pointWorld(t)
					write := pointActivation(t, store, base, c, "point", point(c, "b", "approve"))
					pointWrite := func(ctx context.Context) error {
						if pointOutcome == "reject" {
							return store.RejectPoints(ctx, []release.PointDecision{point(c, "b", "reject")})
						}
						_, err := store.Activate(ctx, write)
						return err
					}
					wholeWrite := func(ctx context.Context) error {
						if wholeAction == "decide" {
							_, err := service(store).Decide(ctx, principal, "space-1", c.ID, approve)
							return err
						}
						whole := write
						whole.Points = nil
						whole.BundleDigest = c.BundleDigest
						whole.Nonce = "whole-activation"
						_, err := store.Activate(ctx, whole)
						return err
					}
					first, second := wholeWrite, pointWrite
					if pointFirst {
						first, second = pointWrite, wholeWrite
					}
					winner, loser := racePointMode(t, db, first, second)
					require.NoError(t, winner)
					var failure *release.Error
					require.ErrorAs(t, loser, &failure)
					require.Equal(t, release.ErrorCandidateDecided, failure.Code)
					decisions, err := store.PointDecisions(context.Background(), 7, "space-1", c.ID)
					require.NoError(t, err)
					if pointFirst {
						require.Len(t, decisions, 1)
					} else {
						require.Empty(t, decisions)
					}
				})
			}
		}
	}
}

func TestPostgresPointBatchesRaceReplayOrRollBackWithoutPendingApproval(t *testing.T) {
	for _, kind := range []string{"same-batch", "same-slug", "different-slug"} {
		t.Run(kind, func(t *testing.T) {
			db, store, base, c := pointWorld(t)
			first := pointActivation(t, store, base, c, "one", point(c, "b", "approve"))
			second := first
			if kind != "same-batch" {
				second = pointActivation(t, store, base, c, "two", point(c, "b", "approve"))
				if kind == "different-slug" {
					second.Points[0].Slug = "c"
				}
			}
			var a, b release.Release
			x, y := racePointMode(t, db,
				func(ctx context.Context) error { var err error; a, err = store.Activate(ctx, first); return err },
				func(ctx context.Context) error { var err error; b, err = store.Activate(ctx, second); return err })
			require.NoError(t, x)
			if kind == "same-batch" {
				require.NoError(t, y)
				require.Equal(t, a, b)
			} else {
				var failure *release.Error
				require.ErrorAs(t, y, &failure)
				expected := release.ErrorMemberDecided
				if kind == "different-slug" {
					expected = release.ErrorReleaseConflict
				}
				require.Equal(t, expected, failure.Code)
			}
			decisions, err := store.PointDecisions(context.Background(), 7, "space-1", c.ID)
			require.NoError(t, err)
			require.Len(t, decisions, 1)
			require.Equal(t, a.ID, decisions[0].ReleaseID)
			require.EqualValues(t, 2, countReleases(t, db))
			head, err := store.Head(context.Background(), 7, "space-1")
			require.NoError(t, err)
			require.Equal(t, a.ID, head.ReleaseID)
		})
	}
}

func TestPostgresPointInsertFailureRollsBackReleaseHeadAndPins(t *testing.T) {
	db, store, base, c := pointWorld(t)
	ref := seedSource(t, db, "new-source", 7, "raw-1", 1)
	write := pointActivation(t, store, base, c, "fault", point(c, "b", "approve"))
	write.Members[0].EvidenceRefs = []string{ref}
	before := rowCounts(t, db)
	require.NoError(t, db.Exec(`CREATE FUNCTION reject_point_insert() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN RAISE EXCEPTION 'point write failed'; END $$;
 CREATE TRIGGER reject_point_insert BEFORE INSERT ON enterprise_point_decisions
 FOR EACH ROW EXECUTE FUNCTION reject_point_insert();`).Error)
	_, err := store.Activate(context.Background(), write)
	require.Error(t, err)
	var failure *release.Error
	require.False(t, errors.As(err, &failure), "storage failure remains an internal failure")
	require.Equal(t, before, rowCounts(t, db))
	require.Equal(t, "released", retention(t, db, "new-source"))
	decisions, err := store.PointDecisions(context.Background(), 7, "space-1", c.ID)
	require.NoError(t, err)
	require.Empty(t, decisions)
	head, err := store.Head(context.Background(), 7, "space-1")
	require.NoError(t, err)
	require.Equal(t, base.ID, head.ReleaseID)
}
