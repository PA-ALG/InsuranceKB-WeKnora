package releasestore

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
)

func TestMemberCacheBoundedIsolatedAndOwned(t *testing.T) {
	var cache memberCache
	ctx := context.Background()
	calls := 0
	read := func(context.Context) ([]release.Member, error) {
		calls++
		return []release.Member{{Payload: []byte(`{"v":1}`), EvidenceRefs: []string{"source"}}}, nil
	}
	load := func(key memberKey) []release.Member {
		m, err := cache.load(ctx, key, read)
		require.NoError(t, err)
		return m
	}
	a := memberKey{7, "one", "same"}
	b := memberKey{8, "one", "same"}
	c := memberKey{7, "two", "same"}
	d := memberKey{7, "two", "fourth"}
	for _, key := range []memberKey{a, b, c, d} {
		load(key)
	}
	mutated := load(a)
	mutated[0].Payload[0] = 'x'
	mutated[0].EvidenceRefs[0] = "changed"
	load(memberKey{7, "two", "fifth"})
	cached := load(a)
	require.Equal(t, `{"v":1}`, string(cached[0].Payload))
	require.Equal(t, []string{"source"}, cached[0].EvidenceRefs)
	require.Equal(t, 5, calls)
	load(b)
	require.Equal(t, 6, calls, "least recently used tenant was evicted")
	require.Equal(t, 4, cache.recent.Len())
}

func TestMemberCacheSharesLoadsRetriesErrorsAndHonorsCancellation(t *testing.T) {
	var cache memberCache
	key := memberKey{7, "one", "r"}
	var calls atomic.Int32
	read := func(context.Context) ([]release.Member, error) {
		calls.Add(1)
		return []release.Member{{LogicalSlug: "loaded"}}, nil
	}
	var wg sync.WaitGroup
	for i := 0; i < 24; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			m, err := cache.load(context.Background(), key, read)
			if err != nil || len(m) != 1 {
				t.Errorf("read: %v, %v", m, err)
			}
		}()
	}
	wg.Wait()
	require.EqualValues(t, 1, calls.Load())
	canceled, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := cache.load(canceled, key, read)
	require.ErrorIs(t, err, context.Canceled, "even a cache hit honors cancellation")
	failedKey := memberKey{7, "one", "failed"}
	for i := 0; i < 2; i++ {
		_, err = cache.load(context.Background(), failedKey, func(context.Context) ([]release.Member, error) {
			calls.Add(1)
			return nil, errors.New("read failed")
		})
		require.EqualError(t, err, "read failed")
	}
	require.EqualValues(t, 3, calls.Load())
}

func TestMemberCacheCanceledLoaderDoesNotPoisonLiveReader(t *testing.T) {
	var cache memberCache
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	key := memberKey{7, "one", "r"}
	started := make(chan struct{})
	firstDone := make(chan error, 1)
	go func() {
		_, err := cache.load(ctx, key, func(ctx context.Context) ([]release.Member, error) {
			close(started)
			<-ctx.Done()
			return nil, ctx.Err()
		})
		firstDone <- err
	}()
	<-started
	live, stop := context.WithTimeout(context.Background(), 5*time.Second)
	defer stop()
	liveDone := make(chan error, 1)
	go func() {
		m, err := cache.load(live, key, func(context.Context) ([]release.Member, error) {
			return []release.Member{{LogicalSlug: "live"}}, nil
		})
		if err == nil && (len(m) != 1 || m[0].LogicalSlug != "live") {
			err = errors.New("wrong shared result")
		}
		liveDone <- err
	}()
	cancel()
	require.ErrorIs(t, <-firstDone, context.Canceled)
	require.NoError(t, <-liveDone)
}

func TestMemberCacheCanceledWaiterDoesNotCancelLoader(t *testing.T) {
	var cache memberCache
	key := memberKey{7, "one", "r"}
	started, unblock := make(chan struct{}), make(chan struct{})
	done := make(chan error, 1)
	go func() {
		_, err := cache.load(context.Background(), key, func(context.Context) ([]release.Member, error) {
			close(started)
			<-unblock
			return []release.Member{{LogicalSlug: "live"}}, nil
		})
		done <- err
	}()
	<-started
	ctx, cancel := context.WithCancel(context.Background())
	waiterDone := make(chan error, 1)
	go func() {
		_, err := cache.load(ctx, key, func(context.Context) ([]release.Member, error) {
			return nil, errors.New("waiter must share the loader")
		})
		waiterDone <- err
	}()
	cancel()
	require.ErrorIs(t, <-waiterDone, context.Canceled)
	close(unblock)
	require.NoError(t, <-done)
}
