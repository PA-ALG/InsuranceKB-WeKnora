package repository

import (
	"context"
	"os"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

// #460 R1: the final dispatch gate must fail closed when the dead-letter read
// fails; only a catalog-confirmed missing table means "no archived failure".
func TestFailedOperationLookupFailsClosed(t *testing.T) {
	runOutcomeDatabases(t, testFailedOperationLookupFailsClosed)
}

func TestFailedOperationLookupWithoutDeadLetterTable(t *testing.T) {
	runOutcomeDatabases(t, testFailedOperationLookupWithoutDeadLetterTable)
}

func TestBudgetReleaseRecordsRetries(t *testing.T) {
	runOutcomeDatabases(t, testBudgetReleaseRecordsRetries)
}

func TestPostgresFailedOperationLookupAndBudgetRelease(t *testing.T) {
	dsn := strings.TrimSpace(os.Getenv("WEKNORA_TEST_POSTGRES_URL"))
	if dsn == "" {
		t.Skip("WEKNORA_TEST_POSTGRES_URL is required for PostgreSQL adapter evidence")
	}
	t.Setenv("G35_TEST_PG_DSN", dsn)
	runOutcomeDatabases(t, testFailedOperationLookupFailsClosed)
	runOutcomeDatabases(t, testFailedOperationLookupWithoutDeadLetterTable)
	runOutcomeDatabases(t, testBudgetReleaseRecordsRetries)
}

func archivedFailure(t *testing.T, db *gorm.DB) (failedOperationLookup, *types.TaskPendingOp) {
	t.Helper()
	ctx := context.Background()
	repo := NewTaskPendingOpsRepository(db)
	guard := repo.(pendingOutcomeStore)
	raw := []byte(`{"op":"ingest","knowledge_id":"source"}`)
	first := makePendingOp("wiki:ingest", "knowledge_base", "kb", "ingest", "source", raw)
	require.NoError(t, repo.Enqueue(ctx, first))
	begun, err := guard.BeginOperation(ctx, first, "sent")
	require.NoError(t, err)
	require.True(t, begun)
	late := makePendingOp(first.TaskType, first.Scope, first.ScopeID, first.Op, first.DedupKey, raw)
	require.NoError(t, repo.Enqueue(ctx, late))
	archived, err := guard.ArchiveOperation(ctx, first, "sent", &types.TaskDeadLetter{
		TenantID: first.TenantID, TaskType: first.TaskType, Scope: first.Scope, ScopeID: first.ScopeID,
		RelatedID: first.DedupKey, LastError: "OUTCOME_UNKNOWN",
	})
	require.NoError(t, err)
	require.True(t, archived)
	return repo.(failedOperationLookup), late
}

func testFailedOperationLookupFailsClosed(t *testing.T, db *gorm.DB) {
	lookup, late := archivedFailure(t, db)
	blocked, err := lookup.HasFailedOperation(context.Background(), late)
	require.NoError(t, err)
	require.True(t, blocked)
	sqlDB, err := db.DB()
	require.NoError(t, err)
	require.NoError(t, sqlDB.Close())
	blocked, err = lookup.HasFailedOperation(context.Background(), late)
	require.Error(t, err, "a failed read must not look like an unarchived input")
	require.False(t, blocked)
}

func testFailedOperationLookupWithoutDeadLetterTable(t *testing.T, db *gorm.DB) {
	require.NoError(t, db.Exec("DROP TABLE task_dead_letters").Error)
	ctx := context.Background()
	repo := NewTaskPendingOpsRepository(db)
	op := makePendingOp("wiki:ingest", "knowledge_base", "kb", "ingest", "source", []byte(`{"op":"ingest"}`))
	require.NoError(t, repo.Enqueue(ctx, op))
	blocked, err := repo.(failedOperationLookup).HasFailedOperation(ctx, op)
	require.NoError(t, err)
	require.False(t, blocked)
}

func testBudgetReleaseRecordsRetries(t *testing.T, db *gorm.DB) {
	ctx := context.Background()
	repo := NewTaskPendingOpsRepository(db)
	execution := repo.(interfaces.TaskPendingOpsExecutionStore)
	budget := repo.(interfaces.TaskPendingOpsBudgetStore)
	payload := `{"op":"ingest","knowledge_id":"source","future":{"execution_id":"nested"}}`
	op := makePendingOp("wiki:ingest", "knowledge_base", "kb", "ingest", "source", []byte(payload))
	op.FailCount = 2
	require.NoError(t, repo.Enqueue(ctx, op))
	begun, err := execution.BeginOperation(ctx, op, "first")
	require.NoError(t, err)
	require.True(t, begun)
	released, err := budget.ReleaseOperationAfterAttempt(ctx, op, "first")
	require.NoError(t, err)
	require.True(t, released)
	var row types.TaskPendingOp
	require.NoError(t, db.First(&row, op.ID).Error)
	require.Nil(t, row.ClaimedAt)
	require.Equal(t, 3, row.FailCount)
	require.JSONEq(t, `{"op":"ingest","knowledge_id":"source","future":{"execution_id":"nested"},"budget_retries":3}`,
		string(row.Payload), "execution marker removed, budget recorded with fail_count")
	released, err = budget.ReleaseOperationAfterAttempt(ctx, op, "first")
	require.NoError(t, err)
	require.False(t, released, "the owner changed; a second release must not apply")
}
