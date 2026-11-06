package memberstore

import (
	"context"
	"os"
	"sync/atomic"
	"testing"
	"time"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

const journalBudgetEnv = "ENTERPRISE_MEMBER_JOURNAL_TIMEOUT_SECONDS"

func budgetScope() types.WikiReleaseScope {
	return types.WikiReleaseScope{TenantID: 7, SpaceID: "journal-space", RawKBID: "journal-raw", WikiKBID: "journal-wiki"}
}

func budgetDB(t *testing.T) (*gorm.DB, sqlmock.Sqlmock, *[]time.Duration, *atomic.Int64) {
	t.Helper()
	pool, mock, err := sqlmock.New()
	require.NoError(t, err)
	t.Cleanup(func() { _ = pool.Close() })
	db, err := gorm.Open(postgres.New(postgres.Config{Conn: pool}), &gorm.Config{
		DisableAutomaticPing: true, Logger: logger.Default.LogMode(logger.Silent),
	})
	require.NoError(t, err)
	var deadlines []time.Duration
	var writes atomic.Int64
	require.NoError(t, db.Callback().Raw().Before("gorm:raw").Register("budget-context", func(tx *gorm.DB) {
		writes.Add(1)
		deadline, ok := tx.Statement.Context.Deadline()
		require.True(t, ok, "every journal write must have a bounded context")
		deadlines = append(deadlines, time.Until(deadline))
	}))
	return db, mock, &deadlines, &writes
}

func budgetSuccess(mock sqlmock.Sqlmock) {
	mock.ExpectExec(`WITH admission AS MATERIALIZED`).WillReturnResult(sqlmock.NewResult(0, 1))
	mock.ExpectExec(`DELETE FROM enterprise_member_validation_pending`).WillReturnResult(sqlmock.NewResult(0, 1))
}

func TestJournalWriteBudgetDefaultAndConfiguredContexts(t *testing.T) {
	for _, value := range []string{"unset", "1", "3", "15", "60"} {
		t.Run(value, func(t *testing.T) {
			want := 15 * time.Second
			t.Setenv(journalBudgetEnv, value)
			if value == "unset" {
				require.NoError(t, os.Unsetenv(journalBudgetEnv))
			} else {
				parsed, err := time.ParseDuration(value + "s")
				require.NoError(t, err)
				want = parsed
			}
			db, mock, deadlines, _ := budgetDB(t)
			budgetSuccess(mock)
			err := New().Validate(context.Background(), db, budgetScope(), func(context.Context) error { return nil })
			require.NoError(t, err)
			require.Len(t, *deadlines, 2)
			for _, got := range *deadlines {
				require.InDelta(t, want.Seconds(), got.Seconds(), 0.25)
			}
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestJournalInvalidBudgetRejectsBeforeSQLOrBusiness(t *testing.T) {
	for _, value := range []string{
		"", "0", "61", "-1", "+15", "01", "15s", "1.5", " 15", "15\n", "99999999999999999999999",
	} {
		t.Run(value, func(t *testing.T) {
			t.Setenv(journalBudgetEnv, value)
			db, mock, _, writes := budgetDB(t)
			called := false
			err := New().Validate(context.Background(), db, budgetScope(), func(context.Context) error {
				called = true
				return nil
			})
			require.ErrorIs(t, err, ErrState)
			require.False(t, called)
			require.Zero(t, writes.Load(), "invalid configuration must fail before a reservation attempt")
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestJournalAttemptRetainsItsPolicyAcrossNestedAndDeferredCompletion(t *testing.T) {
	t.Setenv(journalBudgetEnv, "3")
	s := New()
	db, mock, deadlines, _ := budgetDB(t)
	budgetSuccess(mock)
	var release func(error)
	err := s.Validate(context.Background(), db, budgetScope(), func(ctx context.Context) error {
		release = RetainValidation(ctx)
		t.Setenv(journalBudgetEnv, "5")
		return New().Validate(ctx, db, budgetScope(), func(context.Context) error { return nil })
	})
	require.NoError(t, err)
	require.Len(t, *deadlines, 1, "deferred work still owns the original reservation")
	require.NotNil(t, release)
	release(nil)
	require.Len(t, *deadlines, 2)
	for _, got := range *deadlines {
		require.InDelta(t, 3, got.Seconds(), 0.25)
	}
	require.NoError(t, mock.ExpectationsWereMet())
}
