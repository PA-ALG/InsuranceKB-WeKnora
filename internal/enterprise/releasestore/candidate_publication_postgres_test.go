package releasestore

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"gorm.io/gorm"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// Force both optimistic lookups to miss, then hold the first transaction's
// candidate lock until the second is about to acquire it. No source or Head row
// is needed for serialization, including the very first release of a Space.
func TestPostgresReviewConcurrentCandidatePublication(t *testing.T) {
	for _, existingHead := range []bool{false, true} {
		for _, failFirst := range []bool{false, true} {
			t.Run(fmt.Sprintf("head=%t/rollback=%t", existingHead, failFirst), func(t *testing.T) {
				db := openSchema(t)
				store := New(db, testSpaces(t))
				ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
				defer cancel()
				if existingHead {
					_, err := store.Activate(ctx, activation(t, store, "seed"))
					require.NoError(t, err)
				}
				first := activation(t, store, "candidate")
				second := first
				second.Nonce, second.DecisionID, second.DecisionDigest = "other-nonce", "other-decision", "other-digest"
				held, attempted, proceed := make(chan struct{}), make(chan struct{}), make(chan struct{})
				var holdOnce, attemptOnce, proceedOnce sync.Once
				unblock := func() { proceedOnce.Do(func() { close(proceed) }) }
				defer unblock()
				isLock := func(tx *gorm.DB) bool {
					return strings.Contains(tx.Statement.SQL.String(), "pg_advisory_xact_lock")
				}
				require.NoError(t, db.Callback().Raw().After("gorm:raw").
					Register("test_candidate_held", func(tx *gorm.DB) {
						if isLock(tx) && tx.Error == nil && tx.Statement.Context.Value(raceActorKey{}) == "first" {
							holdOnce.Do(func() {
								close(held)
								select {
								case <-proceed:
								case <-ctx.Done():
								}
								if failFirst {
									_ = tx.AddError(errors.New("injected transaction failure"))
								}
							})
						}
					}))
				require.NoError(t, db.Callback().Raw().Before("gorm:raw").
					Register("test_candidate_attempt", func(tx *gorm.DB) {
						if isLock(tx) && tx.Statement.Context.Value(raceActorKey{}) == "second" {
							attemptOnce.Do(func() { close(attempted) })
						}
					}))
				t.Cleanup(func() {
					require.NoError(t, db.Callback().Raw().Remove("test_candidate_held"))
					require.NoError(t, db.Callback().Raw().Remove("test_candidate_attempt"))
				})
				type result struct {
					value release.Release
					err   error
				}
				a, b := make(chan result, 1), make(chan result, 1)
				go func() {
					r, e := store.Activate(context.WithValue(ctx, raceActorKey{}, "first"), first)
					a <- result{r, e}
				}()
				select {
				case <-held:
				case r := <-a:
					t.Fatalf("first did not acquire lock: %v", r.err)
				case <-ctx.Done():
					t.Fatal(ctx.Err())
				}
				go func() {
					r, e := store.Activate(context.WithValue(ctx, raceActorKey{}, "second"), second)
					b <- result{r, e}
				}()
				select {
				case <-attempted:
				case r := <-b:
					t.Fatalf("second did not attempt lock: %v", r.err)
				case <-ctx.Done():
					t.Fatal(ctx.Err())
				}
				unblock()
				var left, right result
				select {
				case left = <-a:
				case <-ctx.Done():
					t.Fatal(ctx.Err())
				}
				select {
				case right = <-b:
				case <-ctx.Done():
					t.Fatal(ctx.Err())
				}
				require.NoError(t, right.err)
				if failFirst {
					// Recovery lookup may observe the second publisher after rollback.
					if left.err == nil {
						require.Equal(t, right.value, left.value)
					} else {
						require.ErrorContains(t, left.err, "injected transaction failure")
					}
					var receipts, preparations int64
					require.NoError(t, db.Table("wiki_release_receipts").
						Where("nonce = ?", first.Nonce).Count(&receipts).Error)
					require.NoError(t, db.Table("wiki_release_preparations").
						Where("ready_receipt_digest = ?", first.Nonce).Count(&preparations).Error)
					require.Zero(t, receipts)
					require.Zero(t, preparations)
				} else {
					require.NoError(t, left.err)
					require.Equal(t, left.value, right.value)
				}
				var count int64
				require.NoError(t, db.Table("wiki_releases").Where(
					"tenant_id = ? AND space_id = ? AND candidate_digest = ?", 7, "space-1", first.BundleDigest,
				).Count(&count).Error)
				require.EqualValues(t, 1, count)
				head, err := store.Head(ctx, 7, "space-1")
				require.NoError(t, err)
				require.Equal(t, right.value.ID, head.ReleaseID)
				require.Equal(t, first.Expected.Epoch+1, head.Epoch)
			})
		}
	}
}
