package releasestore

import (
	"context"
	"fmt"
	"math"
	"runtime"
	"sort"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm/logger"
)

type storageQueryCounter struct {
	logger.Interface
	queries atomic.Int64
}

func (l *storageQueryCounter) Trace(context.Context, time.Time, func() (string, int64), error) {
	l.queries.Add(1)
}

type storageTiming struct {
	duration  time.Duration
	queries   int64
	wireBytes int64
}

func TestPostgresMemberStorageReadBudget(t *testing.T) {
	for _, n := range []int{3600, 37500} {
		t.Run(fmt.Sprint(n), func(t *testing.T) {
			db := memberStorageDB(t)
			referenceFixtureScope(t, db)
			store := New(db, testSpaces(t))
			members := make([]release.Member, n)
			for i := range members {
				members[i] = paddedStorageMember(t, i, 0)
			}
			r := storagePublish(t, store, "read-budget", members)
			storageRoot(t, db, r.ID)
			// Store one legacy version in the very same database for the frozen old reader.
			// The600-history fixture does not duplicate legacy history.
			snapshots, _, err := snapshotsOf(release.ActivationWrite{Members: members})
			require.NoError(t, err)
			rows := make([]types.WikiReleaseMember, len(snapshots))
			for i, s := range snapshots {
				rows[i] = types.WikiReleaseMember{ID: r.ID + ":" + s.LogicalSlug, ReleaseID: r.ID, Kind: s.Kind,
					LogicalSlug: s.LogicalSlug, RevisionID: s.RevisionID, MemberDigest: s.MemberDigest, Title: s.Title, Content: s.Content, Payload: s.Payload}
			}
			require.NoError(t, db.CreateInBatches(rows, 500).Error)
			counter := &storageQueryCounter{Interface: logger.Default.LogMode(logger.Silent)}
			measured, wireBytes := storageMeasuredConnection(t, db, counter)
			read := func(modern bool) storageTiming {
				reader := New(measured, testSpaces(t))
				counter.queries.Store(0)
				wireBytes.Store(0)
				start := time.Now()
				var got release.Release
				var err error
				if modern {
					got, err = reader.ReleaseByID(context.Background(), 7, "space-1", r.ID)
				} else {
					got, err = frozenLegacyStorageRead(context.Background(), reader, r.ID)
				}
				elapsed := time.Since(start)
				queries := counter.queries.Load()
				require.NoError(t, err)
				require.Equal(t, members, got.Members)
				return storageTiming{elapsed, queries, wireBytes.Load()}
			}
			// Matched database warm-up, but each timed read creates a cold application/object cache.
			read(false)
			read(true)
			var oldSamples, newSamples []storageTiming
			for repeat := 0; repeat < 15; repeat++ {
				oldSamples = append(oldSamples, read(false))
				newSamples = append(newSamples, read(true))
				newSamples = append(newSamples, read(true))
				oldSamples = append(oldSamples, read(false))
				checkStorageResourceBudget(t, db)
			}
			summarize := func(samples []storageTiming) (time.Duration, time.Duration, int64) {
				durations := make([]time.Duration, len(samples))
				var q int64
				for i, s := range samples {
					durations[i] = s.duration
					q = max(q, s.queries)
				}
				sort.Slice(durations, func(i, j int) bool { return durations[i] < durations[j] })
				return durations[(len(durations)-1)*50/100], durations[int(math.Ceil(float64(len(durations))*0.95))-1], q
			}
			old50, old95, oldQ := summarize(oldSamples)
			new50, new95, newQ := summarize(newSamples)
			t.Logf("N=%d PG15/local or CI target, %s/%s cpus=%d GOMAXPROCS=%d samples=30each ABBA15; old p50=%s p95=%s queries=%d; new p50=%s p95=%s queries=%d; wire bytes included (per sample); all samples old=%v new=%v", n, runtime.GOOS, runtime.GOARCH, runtime.NumCPU(), runtime.GOMAXPROCS(0), old50, old95, oldQ, new50, new95, newQ, oldSamples, newSamples)
			require.LessOrEqual(t, newQ, 2*oldQ)
			require.LessOrEqual(t, new50, 2*old50)
			require.LessOrEqual(t, new95, 2*old95)
		})
	}
}

// Frozen old cold path (682b10667): it never invokes the upgraded storage port.
// Kept in the test so new production's correct ref-only/legacy-binary guard cannot change baseline.
func frozenLegacyStorageRead(ctx context.Context, s *Store, id string) (release.Release, error) {
	scope, err := s.spaces.Scope(7, "space-1")
	if err != nil {
		return release.Release{}, err
	}
	header, err := s.releaseHeader(ctx, scope, id)
	if err != nil {
		return release.Release{}, err
	}
	header.Members, err = s.members.load(ctx, memberKey{Tenant: 7, Space: "space-1", Release: id}, func(ctx context.Context) ([]release.Member, error) {
		var r types.WikiRelease
		if err := s.db.WithContext(ctx).Where("tenant_id = ? AND space_id = ? AND raw_kb_id = ? AND wiki_kb_id = ?", scope.TenantID, scope.SpaceID, scope.RawKBID, scope.WikiKBID).Where("release_id = ?", id).Take(&r).Error; err != nil {
			return nil, err
		}
		var rows []types.WikiReleaseMember
		if err := s.db.WithContext(ctx).Where("release_id = ?", id).Order("logical_slug ASC").Find(&rows).Error; err != nil {
			return nil, err
		}
		snapshots := make([]types.WikiReleaseMemberSnapshot, 0, len(rows))
		for _, row := range rows {
			snapshots = append(snapshots, row.Snapshot())
		}
		members := make([]release.Member, 0, len(snapshots))
		for _, snapshot := range snapshots {
			m, err := decodeMember(snapshot)
			if err != nil {
				return nil, err
			}
			members = append(members, m)
		}
		return members, nil
	})
	return header, err
}
