package repository

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

func TestTaskPendingOps_ReleaseOperationRoundTrip(t *testing.T) {
	testPendingRetryPayloadAndOwnership(t, setupTaskQueueTestDB(t))
}

func TestPostgresTaskPendingOpsReleaseOperationPreservesPayloadAndOwnership(t *testing.T) {
	dsn := strings.TrimSpace(os.Getenv("WEKNORA_TEST_POSTGRES_URL"))
	if dsn == "" {
		t.Skip("WEKNORA_TEST_POSTGRES_URL is required for PostgreSQL adapter evidence")
	}
	// Enterprise PostgreSQL CI selects TestPostgres* and rejects every skip.
	// Bridge its disposable database URL to the queue fixture's existing
	// unique-schema setup and cleanup, retaining its SQLite comparison arm.
	t.Setenv("G35_TEST_PG_DSN", dsn)
	runOutcomeDatabases(t, testPendingRetryPayloadAndOwnership)
}

func testPendingRetryPayloadAndOwnership(t *testing.T, db *gorm.DB) {
	t.Helper()
	ctx := context.Background()
	repo := NewTaskPendingOpsRepository(db)
	execution := repo.(interfaces.TaskPendingOpsExecutionStore)
	retry := repo.(interfaces.TaskPendingOpsRetryStore)
	payload := `{"op":"ingest","knowledge_id":"source",` +
		`"revision":{"parse_attempt":7,"file_sha256":"source"},` +
		`"future":{"execution_id":"nested","values":[1,null,true]}}`
	op := makePendingOp("wiki:ingest", "knowledge_base", "kb", "ingest", "source", []byte(payload))
	op.FailCount = 2
	require.NoError(t, repo.Enqueue(ctx, op))

	staleBefore := time.Now().Add(-time.Hour)
	claims, err := repo.ClaimBatch(ctx, op.TaskType, op.Scope, op.ScopeID, 1, staleBefore)
	require.NoError(t, err)
	require.Len(t, claims, 1)
	firstClaim := claims[0]
	require.NotNil(t, firstClaim.ClaimedAt)
	begun, err := execution.BeginOperation(ctx, firstClaim, "first")
	require.NoError(t, err)
	require.True(t, begun)

	released, err := retry.ReleaseOperation(ctx, firstClaim, "first")
	require.NoError(t, err)
	require.True(t, released)
	var releasedRow types.TaskPendingOp
	require.NoError(t, db.First(&releasedRow, op.ID).Error)
	require.Nil(t, releasedRow.ClaimedAt)
	require.JSONEq(t, payload, string(releasedRow.Payload),
		"only the top-level execution_id may be removed; nested keys and other fields must survive")
	require.Equal(t, 2, releasedRow.FailCount)

	claims, err = repo.ClaimBatch(ctx, op.TaskType, op.Scope, op.ScopeID, 1, staleBefore)
	require.NoError(t, err)
	require.Len(t, claims, 1, "a released operation must be eligible for immediate reclaim")
	secondClaim := claims[0]
	require.Equal(t, op.ID, secondClaim.ID)
	require.NotNil(t, secondClaim.ClaimedAt)
	begun, err = execution.BeginOperation(ctx, secondClaim, "second")
	require.NoError(t, err)
	require.True(t, begun, "the removed marker must permit a new execution")
	var before types.TaskPendingOp
	require.NoError(t, db.First(&before, op.ID).Error)
	require.JSONEq(t, payload[:len(payload)-1]+`,"execution_id":"second"}`, string(before.Payload))

	// Use the CURRENT claim with the OLD execution ID so rejection proves
	// the execution CAS predicate, independently of the timestamp predicate.
	released, err = retry.ReleaseOperation(ctx, secondClaim, "first")
	require.NoError(t, err)
	require.False(t, released, "an old execution must not release the new owner")
	var after types.TaskPendingOp
	require.NoError(t, db.First(&after, op.ID).Error)
	require.Equal(t, before, after, "a rejected release must not mutate the new claim or payload")

	released, err = retry.ReleaseOperation(ctx, secondClaim, "second")
	require.NoError(t, err)
	require.True(t, released, "the current owner must still be able to release")
	// Read into a fresh row: GORM does not clear a populated *time.Time on NULL.
	var finalRow types.TaskPendingOp
	require.NoError(t, db.First(&finalRow, op.ID).Error)
	require.Nil(t, finalRow.ClaimedAt)
	require.JSONEq(t, payload, string(finalRow.Payload))
	require.Equal(t, 2, finalRow.FailCount)
}
