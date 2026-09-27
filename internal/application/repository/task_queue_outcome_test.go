package repository

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"gorm.io/driver/postgres"
	"net/url"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

// Local structural contract lets the pre-implementation test fail at runtime.
type pendingOutcomeStore interface {
	BeginOperation(context.Context, *types.TaskPendingOp, string) (bool, error)
	CompleteOperation(context.Context, *types.TaskPendingOp, string) (bool, error)
	ArchiveOperation(context.Context, *types.TaskPendingOp, string, *types.TaskDeadLetter) (bool, error)
	FailedOperationCount(context.Context, uint64, string, string, string) (int64, error)
}

func TestPendingOperationGuardAndAtomicArchive(t *testing.T) {
	runOutcomeDatabases(t, testPendingOperationGuardAndAtomicArchive)
}
func testPendingOperationGuardAndAtomicArchive(t *testing.T, db *gorm.DB) {
	repo := NewTaskPendingOpsRepository(db)
	guard, ok := repo.(pendingOutcomeStore)
	require.True(t, ok, "pending queue must guard native dispatch before sending")
	ctx := context.Background()
	op := makePendingOp("wiki:ingest", "knowledge_base", "kb", "ingest", "source", []byte(`{"op":"ingest"}`))
	require.NoError(t, repo.Enqueue(ctx, op))
	payload := []byte(`{"op":"ingest","execution_id":"first"}`)
	begun, err := guard.BeginOperation(ctx, op, "first")
	require.NoError(t, err)
	require.True(t, begun)
	// Old payload, wrong claim generation, and wrong scope may never acquire it.
	begun, err = guard.BeginOperation(ctx, op, "first")
	require.NoError(t, err)
	require.False(t, begun)
	current := *op
	current.Payload = payload
	wrong := current
	now := time.Now()
	wrong.ClaimedAt = &now
	begun, err = guard.BeginOperation(ctx, &wrong, "other")
	require.NoError(t, err)
	require.False(t, begun)
	wrong = current
	wrong.TenantID++
	begun, err = guard.BeginOperation(ctx, &wrong, "other")
	require.NoError(t, err)
	require.False(t, begun)
	dl := &types.TaskDeadLetter{TenantID: 1, TaskType: op.TaskType, Scope: op.Scope, ScopeID: op.ScopeID, RelatedID: op.DedupKey, Payload: payload, LastError: "OUTCOME_UNKNOWN"}
	// Insert failure must leave the marked pending row.
	require.NoError(t, db.Callback().Create().Before("gorm:create").Register("fail_archive", func(tx *gorm.DB) {
		if tx.Statement.Table == "task_dead_letters" {
			tx.AddError(errors.New("archive unavailable"))
		}
	}))
	settled, err := guard.ArchiveOperation(ctx, &current, "first", dl)
	require.Error(t, err)
	require.False(t, settled)
	require.NoError(t, db.Callback().Create().Remove("fail_archive"))
	var remaining types.TaskPendingOp
	require.NoError(t, db.First(&remaining, op.ID).Error)
	require.JSONEq(t, string(payload), string(remaining.Payload))
	// Delete failure must roll back the inserted archive too.
	require.NoError(t, db.Callback().Delete().Before("gorm:delete").Register("fail_delete", func(tx *gorm.DB) {
		if tx.Statement.Table == "task_pending_ops" {
			tx.AddError(errors.New("delete unavailable"))
		}
	}))
	settled, err = guard.ArchiveOperation(ctx, &current, "first", dl)
	require.Error(t, err)
	require.False(t, settled)
	require.NoError(t, db.Callback().Delete().Remove("fail_delete"))
	count, err := guard.FailedOperationCount(ctx, 1, op.TaskType, op.Scope, op.ScopeID)
	require.NoError(t, err)
	require.Zero(t, count)
	// A mismatching archive must not change any scope.
	foreign := *dl
	foreign.TenantID = 2
	settled, err = guard.ArchiveOperation(ctx, &current, "first", &foreign)
	require.Error(t, err)
	require.False(t, settled)
	settled, err = guard.ArchiveOperation(ctx, &current, "first", dl)
	require.NoError(t, err)
	require.True(t, settled)
	settled, err = guard.ArchiveOperation(ctx, &current, "first", dl)
	require.NoError(t, err)
	require.False(t, settled, "missing row does not prove which owner settled it")
	count, err = guard.FailedOperationCount(ctx, 1, op.TaskType, op.Scope, op.ScopeID)
	require.NoError(t, err)
	require.EqualValues(t, 1, count)
	count, err = guard.FailedOperationCount(ctx, 2, op.TaskType, op.Scope, op.ScopeID)
	require.NoError(t, err)
	require.Zero(t, count)
}

func TestPendingCompleteRejectsStaleClaimAndPreservesPayload(t *testing.T) {
	runOutcomeDatabases(t, testPendingCompleteRejectsStaleClaimAndPreservesPayload)
}
func testPendingCompleteRejectsStaleClaimAndPreservesPayload(t *testing.T, db *gorm.DB) {
	repo := NewTaskPendingOpsRepository(db)
	guard := repo.(pendingOutcomeStore)
	ctx := context.Background()
	op := makePendingOp("wiki:ingest", "knowledge_base", "kb", "ingest", "source", []byte(`{"future":{"value":42}}`))
	require.NoError(t, repo.Enqueue(ctx, op))
	begun, err := guard.BeginOperation(ctx, op, "first")
	require.NoError(t, err)
	require.True(t, begun)
	var row types.TaskPendingOp
	require.NoError(t, db.First(&row, op.ID).Error)
	require.JSONEq(t, `{"future":{"value":42},"execution_id":"first"}`, string(row.Payload))
	now := time.Now()
	require.NoError(t, db.Model(&types.TaskPendingOp{}).Where("id = ?", op.ID).Update("claimed_at", now).Error)
	done, err := guard.CompleteOperation(ctx, op, "first")
	require.NoError(t, err)
	require.False(t, done)
	require.NoError(t, db.First(&row, op.ID).Error)
	done, err = guard.CompleteOperation(ctx, &row, "first")
	require.NoError(t, err)
	require.True(t, done)
}

// PostgreSQL tests use a unique schema and clean up only that schema. Normal
// offline runs retain SQLite coverage and explicitly skip the integration arm.
func runOutcomeDatabases(t *testing.T, test func(*testing.T, *gorm.DB)) {
	t.Run("sqlite", func(t *testing.T) { test(t, setupTaskQueueTestDB(t)) })
	t.Run("postgres", func(t *testing.T) {
		dsn := os.Getenv("G35_TEST_PG_DSN")
		if dsn == "" {
			t.Skip("G35_TEST_PG_DSN not configured")
		}
		admin, err := gorm.Open(postgres.Open(dsn), &gorm.Config{})
		require.NoError(t, err)
		schema := fmt.Sprintf("g35_queue_%d", time.Now().UnixNano())
		require.NoError(t, admin.Exec("CREATE SCHEMA "+schema).Error)
		t.Cleanup(func() {
			require.NoError(t, admin.Exec("DROP SCHEMA "+schema+" CASCADE").Error)
			sqlDB, _ := admin.DB()
			_ = sqlDB.Close()
		})
		parsed, err := url.Parse(dsn)
		require.NoError(t, err)
		query := parsed.Query()
		query.Set("search_path", schema)
		parsed.RawQuery = query.Encode()
		db, err := gorm.Open(postgres.Open(parsed.String()), &gorm.Config{})
		require.NoError(t, err)
		t.Cleanup(func() { sqlDB, _ := db.DB(); _ = sqlDB.Close() })
		ddl := strings.NewReplacer("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY", "DATETIME", "TIMESTAMPTZ", "payload     TEXT", "payload     JSONB").Replace(taskPendingOpsTestDDL + taskDeadLettersTestDDL)
		require.NoError(t, db.Exec(ddl).Error)
		test(t, db)
	})
}

func TestPendingOperationConcurrentSettlement(t *testing.T) {
	runOutcomeDatabases(t, func(t *testing.T, db *gorm.DB) {
		if db.Dialector.Name() != "postgres" {
			t.Skip("row-lock concurrency requires PostgreSQL")
		}
		repo := NewTaskPendingOpsRepository(db)
		guard := repo.(pendingOutcomeStore)
		ctx := context.Background()
		op := makePendingOp("wiki:ingest", "knowledge_base", "kb", "ingest", "source", []byte(`{}`))
		require.NoError(t, repo.Enqueue(ctx, op))
		var wg sync.WaitGroup
		accepted := make([]bool, 2)
		errs := make([]error, 2)
		for i := range 2 {
			wg.Add(1)
			go func(i int) {
				defer wg.Done()
				accepted[i], errs[i] = guard.BeginOperation(ctx, op, fmt.Sprintf("execution-%d", i))
			}(i)
		}
		wg.Wait()
		require.NoError(t, errs[0])
		require.NoError(t, errs[1])
		require.NotEqual(t, accepted[0], accepted[1])
		winner := 0
		if accepted[1] {
			winner = 1
		}
		execution := fmt.Sprintf("execution-%d", winner)
		dl := &types.TaskDeadLetter{TenantID: op.TenantID, TaskType: op.TaskType, Scope: op.Scope, ScopeID: op.ScopeID, RelatedID: op.DedupKey, LastError: "OUTCOME_UNKNOWN"}
		for i := range 2 {
			wg.Add(1)
			go func(i int) { defer wg.Done(); accepted[i], errs[i] = guard.ArchiveOperation(ctx, op, execution, dl) }(i)
		}
		wg.Wait()
		require.NoError(t, errs[0])
		require.NoError(t, errs[1])
		require.NotEqual(t, accepted[0], accepted[1])
		count, err := guard.FailedOperationCount(ctx, op.TenantID, op.TaskType, op.Scope, op.ScopeID)
		require.NoError(t, err)
		require.EqualValues(t, 1, count)
	})
}

type failedOperationLookup interface {
	HasFailedOperation(context.Context, *types.TaskPendingOp) (bool, error)
}

func TestPendingLateRevisionFailureGate(t *testing.T) {
	runOutcomeDatabases(t, func(t *testing.T, db *gorm.DB) {
		repo := NewTaskPendingOpsRepository(db)
		lookup, ok := repo.(failedOperationLookup)
		require.True(t, ok, "final dispatch gate must remember same revision archived failure")
		guard := repo.(pendingOutcomeStore)
		ctx := context.Background()
		raw := []byte(`{"op":"ingest","knowledge_id":"source","revision":{"parse_attempt":1,"file_sha256":"source","parser_identity":{"parser_engine":"engine-a"}}}`)
		first := makePendingOp("wiki:ingest", "knowledge_base", "kb", "ingest", "source", raw)
		require.NoError(t, repo.Enqueue(ctx, first))
		begun, err := guard.BeginOperation(ctx, first, "sent")
		require.NoError(t, err)
		require.True(t, begun)
		late := makePendingOp(first.TaskType, first.Scope, first.ScopeID, first.Op, first.DedupKey, raw)
		require.NoError(t, repo.Enqueue(ctx, late))
		archived, err := guard.ArchiveOperation(ctx, first, "sent", &types.TaskDeadLetter{TenantID: first.TenantID, TaskType: first.TaskType, Scope: first.Scope, ScopeID: first.ScopeID, RelatedID: first.DedupKey, LastError: "OUTCOME_UNKNOWN"})
		require.NoError(t, err)
		require.True(t, archived)
		blocked, err := lookup.HasFailedOperation(ctx, late)
		require.NoError(t, err)
		require.True(t, blocked)
		var next map[string]interface{}
		require.NoError(t, json.Unmarshal(raw, &next))
		next["revision"].(map[string]interface{})["parse_attempt"] = 2
		late.Payload, _ = json.Marshal(next)
		blocked, err = lookup.HasFailedOperation(ctx, late)
		require.NoError(t, err)
		require.False(t, blocked)
		next["revision"].(map[string]interface{})["parse_attempt"] = 1
		next["revision"].(map[string]interface{})["parser_identity"].(map[string]interface{})["parser_engine"] = "engine-b"
		late.Payload, _ = json.Marshal(next)
		blocked, err = lookup.HasFailedOperation(ctx, late)
		require.NoError(t, err)
		require.False(t, blocked, "parser identity participates")
		late.Payload = raw
		late.TenantID++
		blocked, err = lookup.HasFailedOperation(ctx, late)
		require.NoError(t, err)
		require.False(t, blocked)
		late.TenantID--
		late.Op = "retract"
		blocked, err = lookup.HasFailedOperation(ctx, late)
		require.NoError(t, err)
		require.False(t, blocked)
	})
}
func TestPendingWikiScrubPreservesStartedClaims(t *testing.T) {
	runOutcomeDatabases(t, func(t *testing.T, db *gorm.DB) {
		repo := NewTaskPendingOpsRepository(db)
		ctx := context.Background()
		for _, payload := range []string{`{}`, `{"execution_id":"sent"}`, `{}`} {
			row := makePendingOp("wiki:ingest", "knowledge_base", "kb", "ingest", "source", []byte(payload))
			if payload == `{}` {
				var count int64
				db.Model(&types.TaskPendingOp{}).Count(&count)
				if count > 0 {
					now := time.Now()
					row.ClaimedAt = &now
				}
			}
			require.NoError(t, repo.Enqueue(ctx, row))
		}
		require.NoError(t, repo.DeleteByDedupKey(ctx, "wiki:ingest", "knowledge_base", "kb", "source", "ingest"))
		var count int64
		require.NoError(t, db.Model(&types.TaskPendingOp{}).Count(&count).Error)
		require.EqualValues(t, 2, count, "scrub must preserve both marked and claimed rows")
	})
}
