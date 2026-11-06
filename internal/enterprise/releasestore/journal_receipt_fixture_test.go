package releasestore

import (
	"context"
	"database/sql"
	"errors"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

const journalTimeoutEnv = "ENTERPRISE_MEMBER_JOURNAL_TIMEOUT_SECONDS"

type receiptFault struct {
	stage          string
	beforeCommit   bool
	readbackFails  bool
	response       error
	mutate         func(*sql.Conn, string)
	afterCommit    func()
	attempt        string
	writes         atomic.Int64
	readbacks      atomic.Int64
	injected       atomic.Bool
	commitObserved atomic.Bool
}

func receiptStage(query string) string {
	switch {
	case strings.HasPrefix(query, "WITH admission AS MATERIALIZED"):
		return "admission"
	case strings.HasPrefix(query, "WITH recorded AS"):
		return "terminal"
	case strings.HasPrefix(query, "DELETE FROM enterprise_member_validation_pending"):
		return "cleanup"
	default:
		return ""
	}
}

// A separately pinned physical connection proves the real autocommit before a test
// adapter hides its response. No production hook or replacement storage port is used.
func installReceiptFault(t *testing.T, db *gorm.DB, fault *receiptFault) {
	t.Helper()
	pool, err := db.DB()
	require.NoError(t, err)
	proof, err := pool.Conn(context.Background())
	require.NoError(t, err)
	name := "receipt-" + t.Name()
	t.Cleanup(func() {
		_ = db.Callback().Raw().Remove(name + "-before")
		_ = db.Callback().Raw().Remove(name + "-after")
		_ = db.Callback().Row().Remove(name + "-read")
		_ = proof.Close()
	})
	if fault.response == nil {
		fault.response = context.DeadlineExceeded
	}
	require.NoError(t, db.Callback().Raw().Before("gorm:raw").Register(name+"-before", func(tx *gorm.DB) {
		if receiptStage(tx.Statement.SQL.String()) != fault.stage {
			return
		}
		fault.writes.Add(1)
		if fault.beforeCommit && fault.injected.CompareAndSwap(false, true) {
			fault.attempt = tx.Statement.Vars[len(tx.Statement.Vars)-1].(string)
			tx.RowsAffected = 0
			tx.AddError(fault.response)
		}
	}))
	require.NoError(t, db.Callback().Raw().After("gorm:raw").Register(name+"-after", func(tx *gorm.DB) {
		if receiptStage(tx.Statement.SQL.String()) != fault.stage || tx.Error != nil ||
			fault.beforeCommit || !fault.injected.CompareAndSwap(false, true) {
			return
		}
		fault.attempt = tx.Statement.Vars[len(tx.Statement.Vars)-1].(string)
		if fault.stage != "cleanup" {
			table := "enterprise_member_validation_pending"
			if fault.stage == "terminal" {
				table = "enterprise_member_validation_failures"
			}
			var committed int
			require.NoError(t, proof.QueryRowContext(context.Background(), "SELECT count(*) FROM "+table+
				" WHERE tenant_id=7 AND space_id='space-1' AND raw_kb_id='raw-1' AND wiki_kb_id='wiki-1' AND attempt_id=$1",
				fault.attempt).Scan(&committed))
			require.Equal(t, 1, committed, "must prove actual committed data before returning a lost response")
		} else {
			var remaining int
			require.NoError(t, proof.QueryRowContext(context.Background(),
				"SELECT count(*) FROM enterprise_member_validation_pending WHERE attempt_id=$1", fault.attempt).Scan(&remaining))
			require.Zero(t, remaining)
		}
		fault.commitObserved.Store(true)
		if fault.mutate != nil {
			fault.mutate(proof, fault.attempt)
		}
		if fault.afterCommit != nil {
			fault.afterCommit()
		}
		tx.RowsAffected = 0 // exactly the unknown-response shape observed during rehearsal
		tx.AddError(fault.response)
	}))
	require.NoError(t, db.Callback().Row().Before("gorm:row").Register(name+"-read", func(tx *gorm.DB) {
		query := tx.Statement.SQL.String()
		if !fault.injected.Load() || receiptStage(query) != "" ||
			!strings.Contains(query, "enterprise_member_validation_pending") ||
			!strings.Contains(query, "enterprise_member_validation_failures") {
			return
		}
		fault.readbacks.Add(1)
		require.Contains(t, tx.Statement.Vars, fault.attempt, "reconcile the original attempt, never another ticket")
		for _, identity := range []any{uint64(7), "space-1", "raw-1", "wiki-1"} {
			require.Contains(t, tx.Statement.Vars, identity, "readback must bind the complete scope")
		}
		if fault.readbackFails {
			tx.AddError(errors.New("synthetic private readback unavailable"))
		}
	}))
}

func receiptScope(t *testing.T) types.WikiReleaseScope {
	t.Helper()
	scope, err := testSpaces(t).Scope(7, "space-1")
	require.NoError(t, err)
	return scope
}

func receiptMode(t *testing.T, db *gorm.DB) string {
	t.Helper()
	var mode string
	require.NoError(t, db.Table("enterprise_member_scopes").Select("mode").Scan(&mode).Error)
	return mode
}

func mutateReceipt(t *testing.T, conn *sql.Conn, statement, attempt string) {
	t.Helper()
	_, err := conn.ExecContext(context.Background(), statement, attempt)
	require.NoError(t, err)
}
