package releasestore

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

// Supplemental controls for the R3 draft: routing cannot lose an observed gap or
// let two independently selected formats split snapshot validation from decoding.
func TestPostgresObservedPublisherRoutingFailureRemainsVisible(t *testing.T) {
	for _, canceled := range []bool{false, true} {
		t.Run(map[bool]string{false: "header-failure", true: "canceled"}[canceled], func(t *testing.T) {
			db, s, id := observationFixture(t)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			if canceled {
				cancel()
			} else {
				var once atomic.Bool
				require.NoError(t, db.Callback().Query().Before("gorm:query").Register(
					"routing-failure", func(q *gorm.DB) {
						if q.Statement.Table == "wiki_releases" && once.CompareAndSwap(false, true) {
							_ = q.AddError(errors.New("synthetic header unavailable"))
						}
					}))
			}
			_, err := New(db, testSpaces(t)).ReleaseByID(ctx, 7, "space-1", id)
			require.Error(t, err)
			var failures int64
			require.NoError(t, db.Table("enterprise_member_validation_failures").
				Where("kind='gap'").Count(&failures).Error)
			assert.Positive(t, failures, "known observed routing failure cannot disappear")
			sc, err := s.spaces.Scope(7, "space-1")
			require.NoError(t, err)
			assert.Error(t, NewMemberStorage().ReferenceOnly(context.Background(), db, sc))
		})
	}
}

func TestPostgresObservationTransitionCannotSplitReadAndDecode(t *testing.T) {
	db := memberStorageDB(t)
	s := New(db, testSpaces(t))
	r := storagePublish(t, s, "transition-during-read", storageMembers(t, 3, 0))
	original := storedSnapshots(t, db, r.ID)
	entered, resume := make(chan struct{}), make(chan struct{})
	var once, finish sync.Once
	releaseRead := func() { finish.Do(func() { close(resume) }) }
	defer releaseRead()
	require.NoError(t, db.Callback().Query().After("gorm:query").Register("pause-routing", func(q *gorm.DB) {
		if q.Statement.Table == "wiki_releases" {
			wait := false
			once.Do(func() { close(entered); wait = true })
			if wait {
				<-resume
			}
		}
	}))
	done := make(chan error, 1)
	go func() {
		_, err := New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", r.ID)
		done <- err
	}()
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("reader did not reach format routing")
	}
	sc, err := s.spaces.Scope(7, "space-1")
	require.NoError(t, err)
	require.NoError(t, s.storage.StartObservation(context.Background(), db, sc))
	broken := append([]types.WikiReleaseMemberSnapshot(nil), original...)
	broken[0].Content = `{"v":99,"payload":"{}"}`
	replaceObservedSnapshots(t, db, s, r.ID, broken)
	releaseRead()
	require.Error(t, <-done)
	require.NoError(t, db.Callback().Query().Remove("pause-routing"))
	replaceObservedSnapshots(t, db, s, r.ID, original)
	var failures int64
	require.NoError(t, db.Table("enterprise_member_validation_failures").
		Where("kind='integrity'").Count(&failures).Error)
	assert.Positive(t, failures, "producer decode must share the chosen new-format observation")
	ageObservation(t, db)
	assert.Error(t, NewMemberStorage().ReferenceOnly(context.Background(), db, sc))
}

func TestPostgresUnknownReadFormatCannotReuseWarmMembers(t *testing.T) {
	db, _, id := observationFixture(t)
	reader := New(db, testSpaces(t))
	_, err := reader.ReleaseByID(context.Background(), 7, "space-1", id)
	require.NoError(t, err)
	require.NoError(t, db.Exec("UPDATE wiki_releases SET member_storage='chunks.v99'").Error)
	_, err = reader.ReleaseByID(context.Background(), 7, "space-1", id)
	assert.Error(t, err, "a cache hit cannot bypass unknown storage format rejection")
	var failures int64
	require.NoError(t, db.Table("enterprise_member_validation_failures").
		Where("kind='integrity'").Count(&failures).Error)
	assert.Positive(t, failures)
}

func TestPostgresPublisherNotFoundDoesNotBecomeAnObservationGap(t *testing.T) {
	db, s, id := observationFixture(t)
	var once atomic.Bool
	require.NoError(t, db.Callback().Query().Before("gorm:query").Register("one-notfound", func(q *gorm.DB) {
		if q.Statement.Table == "wiki_releases" && once.CompareAndSwap(false, true) {
			// Real SQL sees no row once, while the subsequent fixed-id lookup can see it.
			q.Statement.AddClause(clause.Where{Exprs: []clause.Expression{clause.Expr{SQL: "FALSE"}}})
		}
	}))
	_, err := New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", id)
	var missing *release.Error
	require.ErrorAs(t, err, &missing)
	require.Equal(t, release.ErrorReleaseNotFound, missing.Code)
	var failures int64
	require.NoError(t, db.Table("enterprise_member_validation_failures").
		Where("kind='gap'").Count(&failures).Error)
	assert.Zero(t, failures, "the original normal 404 exemption must survive concurrent publication")
	sc, err := s.spaces.Scope(7, "space-1")
	require.NoError(t, err)
	assert.NoError(t, NewMemberStorage().ReferenceOnly(context.Background(), db, sc))
}
