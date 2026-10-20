package releasestore

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

func cacheFixture(t *testing.T) (*Store, []release.Release) {
	t.Helper()
	db, spaces := openSchema(t), testSpaces(t)
	writer := New(db, spaces)
	versions := make([]release.Release, 5)
	for i := range versions {
		w := activation(t, writer, fmt.Sprintf("cache-%d", i))
		w.Members[0].Payload = []byte(fmt.Sprintf(`{"value":%d}`, i))
		w.Members[0].MemberDigest = memberDigest(t, string(w.Members[0].Payload))
		var err error
		versions[i], err = writer.Activate(context.Background(), w)
		require.NoError(t, err)
	}
	return New(db, spaces), versions
}

func countMemberQueries(t *testing.T, db *gorm.DB) *atomic.Int32 {
	t.Helper()
	count := &atomic.Int32{}
	require.NoError(t, db.Callback().Query().Before("gorm:query").Register("test:count_members", func(tx *gorm.DB) {
		if tx.Statement.Table == "wiki_release_members" {
			count.Add(1)
		}
	}))
	t.Cleanup(func() { _ = db.Callback().Query().Remove("test:count_members") })
	return count
}

func TestPostgresMemberCacheKeepsMembersButRefreshesHeaderAndPreparation(t *testing.T) {
	store, versions := cacheFixture(t)
	ctx, id := context.Background(), versions[0].ID
	first, err := store.ReleaseByID(ctx, 7, "space-1", id)
	require.NoError(t, err)
	count := countMemberQueries(t, store.db)
	require.NoError(t, store.db.Where("release_id = ?", id).Delete(&types.WikiReleaseMember{}).Error)
	retired, err := store.Retire(ctx, release.RetirementWrite{
		TenantID: 7, SpaceID: "space-1", ReleaseID: id, Subject: "admin", Reason: "superseded",
	})
	require.NoError(t, err)
	second, err := store.ReleaseByID(ctx, 7, "space-1", id)
	require.NoError(t, err)
	require.Equal(t, first.Members, second.Members)
	require.Equal(t, retired.RetiredAt, *second.RetiredAt)
	ref, err := store.ReleaseReference(ctx, 7, "space-1", id)
	require.NoError(t, err)
	require.Equal(t, release.Reference{ID: id, Retired: true}, ref)
	require.Zero(t, count.Load(), "neither member cache hit nor reference query reads member rows")
	// A fresh malformed preparation must not be hidden by either cache path.
	require.NoError(t, store.db.Exec(`UPDATE wiki_release_preparations SET manifest = '"broken"' WHERE preparation_id =
		(SELECT preparation_id FROM wiki_releases WHERE release_id = ?)`, id).Error)
	_, err = store.ReleaseByID(ctx, 7, "space-1", id)
	require.Error(t, err)
	_, err = store.ReleaseReference(ctx, 7, "space-1", id)
	require.Error(t, err)
}

func TestPostgresMemberCacheLoadsOnceConcurrentlyAndEvictsLRU(t *testing.T) {
	store, versions := cacheFixture(t)
	ctx := context.Background()
	count := countMemberQueries(t, store.db)
	start := make(chan struct{})
	var wg sync.WaitGroup
	for i := 0; i < 24; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			got, err := store.ReleaseByID(ctx, 7, "space-1", versions[0].ID)
			if err != nil || len(got.Members) != 1 {
				t.Errorf("concurrent read: %v, %v", got, err)
			}
		}()
	}
	close(start)
	wg.Wait()
	require.EqualValues(t, 1, count.Load())
	for _, i := range []int{1, 2, 3, 0, 4, 0, 1} {
		_, err := store.ReleaseByID(ctx, 7, "space-1", versions[i].ID)
		require.NoError(t, err)
	}
	require.EqualValues(t, 6, count.Load(), "four-version LRU reloads only the evicted version")
}

func TestPostgresMemberCacheFailuresRetryAndReferencesStayLight(t *testing.T) {
	store, versions := cacheFixture(t)
	count := countMemberQueries(t, store.db)
	fail := true
	injectFailure := func(tx *gorm.DB) {
		if tx.Statement.Table == "wiki_release_members" && fail {
			_ = tx.AddError(errors.New("injected member read failure"))
		}
	}
	require.NoError(t, store.db.Callback().Query().Before("gorm:query").Register("test:member_failure", injectFailure))
	t.Cleanup(func() { _ = store.db.Callback().Query().Remove("test:member_failure") })
	ctx := context.Background()
	// A malformed unused snapshot proves that the lightweight path does not
	// secretly deserialize the second copy stored on the preparation.
	require.NoError(t, store.db.Exec(`UPDATE wiki_release_preparations SET members = '"unused"'`).Error)
	ref, err := store.ReleaseReference(ctx, 7, "space-1", "")
	require.NoError(t, err)
	require.Equal(t, versions[4].ID, ref.ID)
	require.Zero(t, count.Load())
	_, err = store.ReleaseByID(ctx, 7, "space-1", ref.ID)
	require.Error(t, err)
	fail = false
	got, err := store.ReleaseByID(ctx, 7, "space-1", ref.ID)
	require.NoError(t, err)
	require.Equal(t, versions[4].Members, got.Members)
	require.EqualValues(t, 2, count.Load())
}

func TestPostgresMemberCacheSeparatesIdenticalIDsByTenantAndSpace(t *testing.T) {
	for _, target := range []struct {
		tenant uint64
		space  string
	}{{8, "space-1"}, {7, "space-2"}} {
		t.Run(fmt.Sprintf("%d-%s", target.tenant, target.space), func(t *testing.T) {
			store, versions := cacheFixture(t)
			spaces, err := ParseSpaces(`[
				{"tenant_id":7,"space_id":"space-1","raw_kb_id":"raw-1","wiki_kb_id":"wiki-1"},
				{"tenant_id":7,"space_id":"space-2","raw_kb_id":"raw-2","wiki_kb_id":"wiki-2"},
				{"tenant_id":8,"space_id":"space-1","raw_kb_id":"raw-8","wiki_kb_id":"wiki-8"}]`)
			require.NoError(t, err)
			store.spaces = spaces
			ctx, id := context.Background(), versions[0].ID
			_, err = store.ReleaseByID(ctx, 7, "space-1", id)
			require.NoError(t, err)
			_, err = store.ReleaseByID(ctx, target.tenant, target.space, id)
			require.Error(t, err, "a cache hit cannot bypass the current scoped header lookup")
			scope, err := spaces.Scope(target.tenant, target.space)
			require.NoError(t, err)
			updates := map[string]any{
				"tenant_id": scope.TenantID, "space_id": scope.SpaceID,
				"raw_kb_id": scope.RawKBID, "wiki_kb_id": scope.WikiKBID,
			}
			// Release IDs are globally unique in PostgreSQL. Relocate the fixture's
			// header and preparation, then remove its rows to distinguish the two
			// identical-ID cache entries without weakening the real DB constraints.
			var row types.WikiRelease
			require.NoError(t, store.db.Where("release_id = ?", id).Take(&row).Error)
			require.NoError(t, store.db.Model(&types.WikiRelease{}).Where("release_id = ?", id).Updates(updates).Error)
			require.NoError(t, store.db.Model(&types.WikiReleasePreparation{}).
				Where("preparation_id = ?", row.PreparationID).Updates(updates).Error)
			require.NoError(t, store.db.Where("release_id = ?", id).Delete(&types.WikiReleaseMember{}).Error)
			got, err := store.ReleaseByID(ctx, target.tenant, target.space, id)
			require.NoError(t, err)
			require.Empty(t, got.Members, "must not reuse the original tenant/Space's cached members")
			_, err = store.ReleaseReference(ctx, 7, "space-1", id)
			require.Error(t, err)
		})
	}
}

func TestPostgresMemberCacheCanceledReadDoesNotServeCachedBody(t *testing.T) {
	store, versions := cacheFixture(t)
	_, err := store.ReleaseByID(context.Background(), 7, "space-1", versions[0].ID)
	require.NoError(t, err)
	ctx, cancel := context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
	defer cancel()
	_, err = store.ReleaseByID(ctx, 7, "space-1", versions[0].ID)
	require.ErrorIs(t, err, context.DeadlineExceeded)
}
