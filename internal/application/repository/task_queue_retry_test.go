package repository

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
)

// A structural contract lets the new capability fail at runtime before its
// production interface and implementation exist.
type pendingRetryStore interface {
	ReleaseOperation(context.Context, *types.TaskPendingOp, string) (bool, error)
}

func TestTaskPendingOps_ReleaseOperationPreservesPayloadAndAllowsRetry(t *testing.T) {
	for _, mode := range []string{"claimed", "lite"} {
		t.Run(mode, func(t *testing.T) {
			db := setupTaskQueueTestDB(t)
			repo := NewTaskPendingOpsRepository(db)
			retry, ok := repo.(pendingRetryStore)
			require.True(t, ok, "pending queue must safely release an operation that never ran")
			execution := repo.(interfaces.TaskPendingOpsExecutionStore)
			ctx := context.Background()
			payload := `{"op":"ingest","knowledge_id":"source",` +
				`"revision":{"parse_attempt":7,"file_sha256":"source",` +
				`"parser_identity":{"parser_engine":"engine-a"}},` +
				`"future":{"execution_id":"nested","values":[1,null,true]}}`
			op := makePendingOp("wiki:ingest", "knowledge_base", "kb", "ingest", "source", []byte(payload))
			require.NoError(t, repo.Enqueue(ctx, op))
			for range 2 {
				_, err := repo.IncrFailCount(ctx, op.ID)
				require.NoError(t, err)
			}
			claim := op
			staleBefore := time.Now().Add(-time.Hour)
			if mode == "claimed" {
				rows, err := repo.ClaimBatch(ctx, op.TaskType, op.Scope, op.ScopeID, 1, staleBefore)
				require.NoError(t, err)
				require.Len(t, rows, 1)
				claim = rows[0]
				require.NotNil(t, claim.ClaimedAt)
			}
			begun, err := execution.BeginOperation(ctx, claim, "first")
			require.NoError(t, err)
			require.True(t, begun)
			// Persist a field absent from the claim snapshot. Release must edit
			// the current JSON value, not rebuild it from known payload fields.
			expected := payload[:len(payload)-1] + `,"late_field":{"kept":"yes"}}`
			marked := expected[:len(expected)-1] + `,"execution_id":"first"}`
			require.NoError(t, db.Model(&types.TaskPendingOp{}).Where("id = ?", op.ID).
				Update("payload", json.RawMessage(marked)).Error)

			released, err := retry.ReleaseOperation(ctx, claim, "first")
			require.NoError(t, err)
			require.True(t, released)
			var remaining types.TaskPendingOp
			require.NoError(t, db.First(&remaining, op.ID).Error)
			require.Nil(t, remaining.ClaimedAt)
			require.JSONEq(t, expected, string(remaining.Payload))
			require.Equal(t, 2, remaining.FailCount)

			rows, err := repo.ClaimBatch(ctx, op.TaskType, op.Scope, op.ScopeID, 1, staleBefore)
			require.NoError(t, err)
			require.Len(t, rows, 1)
			require.Equal(t, op.ID, rows[0].ID)
			begun, err = execution.BeginOperation(ctx, rows[0], "second")
			require.NoError(t, err)
			require.True(t, begun, "the cleared marker must permit a new execution")
			require.NoError(t, db.First(&remaining, op.ID).Error)
			require.JSONEq(t, expected[:len(expected)-1]+`,"execution_id":"second"}`, string(remaining.Payload))
			require.Equal(t, 2, remaining.FailCount)
		})
	}
}

func TestTaskPendingOps_ReleaseOperationRejectsMismatchedOwner(t *testing.T) {
	db := setupTaskQueueTestDB(t)
	repo := NewTaskPendingOpsRepository(db)
	retry, ok := repo.(pendingRetryStore)
	require.True(t, ok, "pending queue must safely release an operation that never ran")
	execution := repo.(interfaces.TaskPendingOpsExecutionStore)
	ctx := context.Background()
	op := makePendingOp("wiki:ingest", "knowledge_base", "kb", "ingest", "source", []byte(`{"keep":true}`))
	require.NoError(t, repo.Enqueue(ctx, op))
	rows, err := repo.ClaimBatch(ctx, op.TaskType, op.Scope, op.ScopeID, 1, time.Now().Add(-time.Hour))
	require.NoError(t, err)
	require.Len(t, rows, 1)
	claim := rows[0]
	begun, err := execution.BeginOperation(ctx, claim, "first")
	require.NoError(t, err)
	require.True(t, begun)
	var before types.TaskPendingOp
	require.NoError(t, db.First(&before, op.ID).Error)

	cases := []struct {
		name   string
		mutate func(*types.TaskPendingOp, *string)
	}{
		{"missing row", func(c *types.TaskPendingOp, _ *string) { c.ID++ }},
		{"tenant", func(c *types.TaskPendingOp, _ *string) { c.TenantID++ }},
		{"task type", func(c *types.TaskPendingOp, _ *string) { c.TaskType = "other" }},
		{"scope", func(c *types.TaskPendingOp, _ *string) { c.Scope = "other" }},
		{"scope id", func(c *types.TaskPendingOp, _ *string) { c.ScopeID = "other" }},
		{"operation", func(c *types.TaskPendingOp, _ *string) { c.Op = "retract" }},
		{"dedup key", func(c *types.TaskPendingOp, _ *string) { c.DedupKey = "other" }},
		{"claim generation", func(c *types.TaskPendingOp, _ *string) {
			older := c.ClaimedAt.Add(-time.Minute)
			c.ClaimedAt = &older
		}},
		{"unclaimed generation", func(c *types.TaskPendingOp, _ *string) { c.ClaimedAt = nil }},
		{"execution", func(_ *types.TaskPendingOp, executionID *string) { *executionID = "other" }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			wrong := *claim
			executionID := "first"
			tc.mutate(&wrong, &executionID)
			released, err := retry.ReleaseOperation(ctx, &wrong, executionID)
			require.NoError(t, err)
			require.False(t, released)
			var remaining types.TaskPendingOp
			require.NoError(t, db.First(&remaining, op.ID).Error)
			require.Equal(t, before, remaining, "a rejected release must leave the owner and payload intact")
		})
	}
}

func TestTaskPendingOps_ReleaseOperationOldOwnerCannotClearNewExecution(t *testing.T) {
	db := setupTaskQueueTestDB(t)
	repo := NewTaskPendingOpsRepository(db)
	retry, ok := repo.(pendingRetryStore)
	require.True(t, ok, "pending queue must safely release an operation that never ran")
	execution := repo.(interfaces.TaskPendingOpsExecutionStore)
	ctx := context.Background()
	op := makePendingOp("wiki:ingest", "knowledge_base", "kb", "ingest", "source", []byte(`{"keep":"value"}`))
	require.NoError(t, repo.Enqueue(ctx, op))
	// A fixed older generation avoids relying on wall-clock precision to
	// distinguish the original claim from the reclaim below.
	originalGeneration := time.Now().Add(-time.Minute)
	require.NoError(t, db.Model(&types.TaskPendingOp{}).Where("id = ?", op.ID).
		Update("claimed_at", originalGeneration).Error)
	var oldClaim types.TaskPendingOp
	require.NoError(t, db.First(&oldClaim, op.ID).Error)
	begun, err := execution.BeginOperation(ctx, &oldClaim, "first")
	require.NoError(t, err)
	require.True(t, begun)
	released, err := retry.ReleaseOperation(ctx, &oldClaim, "first")
	require.NoError(t, err)
	require.True(t, released)
	rows, err := repo.ClaimBatch(ctx, op.TaskType, op.Scope, op.ScopeID, 1, time.Now().Add(-time.Hour))
	require.NoError(t, err)
	require.Len(t, rows, 1)
	newClaim := rows[0]
	begun, err = execution.BeginOperation(ctx, newClaim, "second")
	require.NoError(t, err)
	require.True(t, begun)

	for _, attempt := range []struct {
		claim       *types.TaskPendingOp
		executionID string
	}{
		{&oldClaim, "first"},
		{&oldClaim, "second"},
		{newClaim, "first"},
	} {
		released, err = retry.ReleaseOperation(ctx, attempt.claim, attempt.executionID)
		require.NoError(t, err)
		require.False(t, released)
	}
	var remaining types.TaskPendingOp
	require.NoError(t, db.First(&remaining, op.ID).Error)
	require.Equal(t, newClaim.ClaimedAt, remaining.ClaimedAt)
	require.JSONEq(t, `{"keep":"value","execution_id":"second"}`, string(remaining.Payload))
}

func TestTaskPendingOps_ReleaseOperationRejectsInvalidInput(t *testing.T) {
	db := setupTaskQueueTestDB(t)
	repo := NewTaskPendingOpsRepository(db)
	retry, ok := repo.(pendingRetryStore)
	require.True(t, ok, "pending queue must safely release an operation that never ran")
	execution := repo.(interfaces.TaskPendingOpsExecutionStore)
	ctx := context.Background()
	op := makePendingOp("wiki:ingest", "knowledge_base", "kb", "ingest", "source", nil)
	require.NoError(t, repo.Enqueue(ctx, op))
	begun, err := execution.BeginOperation(ctx, op, "first")
	require.NoError(t, err)
	require.True(t, begun)
	zeroID := *op
	zeroID.ID = 0
	for _, input := range []struct {
		name        string
		claim       *types.TaskPendingOp
		executionID string
	}{
		{"nil claim", nil, "first"},
		{"zero id", &zeroID, "first"},
		{"empty execution", op, ""},
	} {
		t.Run(input.name, func(t *testing.T) {
			released, err := retry.ReleaseOperation(ctx, input.claim, input.executionID)
			require.Error(t, err)
			require.False(t, released)
		})
	}
	canceled, cancel := context.WithCancel(ctx)
	cancel()
	released, err := retry.ReleaseOperation(canceled, op, "first")
	require.ErrorIs(t, err, context.Canceled)
	require.False(t, released)
	var remaining types.TaskPendingOp
	require.NoError(t, db.First(&remaining, op.ID).Error)
	require.JSONEq(t, `{"execution_id":"first"}`, string(remaining.Payload))
}
