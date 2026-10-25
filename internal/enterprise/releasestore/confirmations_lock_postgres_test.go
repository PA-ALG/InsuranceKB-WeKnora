package releasestore

// Controlled interleavings of answers and closures on one item (S5b-3a review R3). Another
// transaction holds the item row lock, as an answer or a closure in progress does; the operation
// under test is released only once PostgreSQL reports it blocked by that very holder
// (pg_blocking_pids), so the order is fixed rather than left to scheduling. Every wait is bounded,
// and a failing test rolls the holder back. Requires WEKNORA_TEST_POSTGRES_URL.
import (
	"context"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/confirm"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

const lockStepTimeout = 15 * time.Second

type heldLock struct {
	tx  *gorm.DB
	pid int64
}

// holdItemLock begins another transaction holding the item's row lock and returns its backend id.
func holdItemLock(ctx context.Context, t *testing.T, db *gorm.DB, itemID string) heldLock {
	t.Helper()
	tx := db.WithContext(ctx).Begin()
	require.NoError(t, tx.Error)
	// A failing test must not leave the lock held, or dropping the schema would wait for it.
	t.Cleanup(func() { _ = tx.Rollback().Error })
	require.NoError(t, tx.Exec(`SELECT id FROM enterprise_confirmations WHERE id = ? FOR UPDATE`, itemID).Error)
	var pid int64
	require.NoError(t, tx.Raw(`SELECT pg_backend_pid()`).Scan(&pid).Error)
	return heldLock{tx: tx, pid: pid}
}

// blockedBy reports whether some backend is blocked by the holder's transaction before ctx ends.
// Waiters blocked by anything else, in this schema or another, do not count.
func blockedBy(ctx context.Context, db *gorm.DB, holder heldLock) bool {
	for {
		var blocked int64
		err := db.WithContext(ctx).Raw(`SELECT count(*) FROM pg_stat_activity
WHERE ? = ANY(pg_blocking_pids(pid))`, holder.pid).Scan(&blocked).Error
		if err == nil && blocked > 0 {
			return true
		}
		select {
		case <-ctx.Done():
			return false
		case <-time.After(10 * time.Millisecond):
		}
	}
}

// finished receives the operation's result, or fails the test once ctx ends.
func finished(ctx context.Context, t *testing.T, done <-chan error) error {
	t.Helper()
	select {
	case err := <-done:
		return err
	case <-ctx.Done():
		t.Fatal("the operation under test did not finish")
		return nil
	}
}

func TestPostgresConfirmationLockProbeIgnoresUnrelatedWaiters(t *testing.T) {
	db, store := confirmationSchema(t)
	ctx, cancel := context.WithTimeout(context.Background(), lockStepTimeout)
	defer cancel()
	_, err := store.InsertItems(ctx, 7, []confirm.Item{confirmationItem("i-1", "k-1"), confirmationItem("i-2", "k-2")})
	require.NoError(t, err)
	mine, other := holdItemLock(ctx, t, db, "i-1"), holdItemLock(ctx, t, db, "i-2")
	waiter := db.WithContext(ctx).Begin()
	require.NoError(t, waiter.Error)
	t.Cleanup(func() { _ = waiter.Rollback().Error })
	waiting := make(chan error, 1)
	go func() {
		waiting <- waiter.Exec(`SELECT id FROM enterprise_confirmations WHERE id = 'i-2' FOR UPDATE`).Error
	}()
	require.True(t, blockedBy(ctx, db, other), "the unrelated waiter is blocked by the other holder")
	short, stop := context.WithTimeout(ctx, 300*time.Millisecond)
	defer stop()
	require.False(t, blockedBy(short, db, mine), "a waiter blocked by another holder does not release mine")
	require.NoError(t, other.tx.Commit().Error)
	require.NoError(t, finished(ctx, t, waiting))
}

func TestPostgresConfirmationAppliedClosureLosesToANewerAnswerCommittedFirst(t *testing.T) {
	db, store := confirmationSchema(t)
	ctx, cancel := context.WithTimeout(context.Background(), lockStepTimeout)
	defer cancel()
	_, err := store.InsertItems(ctx, 7, []confirm.Item{confirmationItem("i-1", "k-1")})
	require.NoError(t, err)
	require.NoError(t, store.AppendAnswer(ctx, 7, "space-1", confirmationAnswer("a-old", "i-1", "assign:p-1")))
	hold := holdItemLock(ctx, t, db, "i-1")
	require.NoError(t, hold.tx.Exec(`INSERT INTO enterprise_confirmation_answers
(id, tenant_id, space_id, confirmation_id, option_key, note, answerer, answered_at)
VALUES ('a-new', 7, 'space-1', 'i-1', 'ignore', '', 'user:b', now())`).Error)
	done := make(chan error, 1)
	go func() {
		done <- store.CloseItem(ctx, 7, "space-1", "i-1",
			confirm.Closure{Reason: "applied", AnswerID: "a-old", ClosedBy: "svc", ClosedAt: confirmationTime})
	}()
	require.True(t, blockedBy(ctx, db, hold), "the closure must wait for the answer in progress")
	require.NoError(t, hold.tx.Commit().Error)
	err = finished(ctx, t, done)
	require.Equal(t, "ANSWER_STALE", confirmationCode(t, err), "the closure re-reads the latest answer under the lock")
	item, _, err := store.ItemByID(ctx, 7, "space-1", "i-1")
	require.NoError(t, err)
	require.Nil(t, item.Closure)
	require.Equal(t, "a-new", item.Answer.ID)
}

func TestPostgresConfirmationAnAnswerLosesToAClosureCommittedFirst(t *testing.T) {
	for _, reason := range []string{"applied", "obsolete"} {
		t.Run(reason, func(t *testing.T) {
			db, store := confirmationSchema(t)
			ctx, cancel := context.WithTimeout(context.Background(), lockStepTimeout)
			defer cancel()
			_, err := store.InsertItems(ctx, 7, []confirm.Item{confirmationItem("i-1", "k-1")})
			require.NoError(t, err)
			require.NoError(t, store.AppendAnswer(ctx, 7, "space-1", confirmationAnswer("a-1", "i-1", "ignore")))
			answerID := "NULL"
			if reason == "applied" {
				answerID = "'a-1'"
			}
			hold := holdItemLock(ctx, t, db, "i-1")
			require.NoError(t, hold.tx.Exec(`INSERT INTO enterprise_confirmation_closures
(confirmation_id, tenant_id, space_id, reason, answer_id, closed_by, closed_at)
VALUES ('i-1', 7, 'space-1', ?, `+answerID+`, 'svc', now())`, reason).Error)
			done := make(chan error, 1)
			go func() {
				done <- store.AppendAnswer(ctx, 7, "space-1", confirmationAnswer("a-late", "i-1", "assign:p-1"))
			}()
			require.True(t, blockedBy(ctx, db, hold), "the answer must wait for the closure in progress")
			require.NoError(t, hold.tx.Commit().Error)
			err = finished(ctx, t, done)
			require.Equal(t, "CONFIRMATION_CLOSED", confirmationCode(t, err), "re-read closure under the lock")
			item, _, err := store.ItemByID(ctx, 7, "space-1", "i-1")
			require.NoError(t, err)
			require.Equal(t, reason, item.Closure.Reason)
			require.Equal(t, "a-1", item.Answer.ID, "the late answer was not appended")
		})
	}
}
