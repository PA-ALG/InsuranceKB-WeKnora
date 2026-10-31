package database

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/Tencent/WeKnora/deploy/upstream"
	"github.com/stretchr/testify/require"
)

func TestLegacyW1FixtureExactBytes(t *testing.T) {
	_, file, _, ok := runtime.Caller(0)
	require.True(t, ok)
	fixtureDir := filepath.Join(filepath.Dir(file), "testdata")

	tests := []struct {
		name string
		file string
		want string
	}{
		{
			name: "up",
			file: "000066_knowledge_revision_manifest.up.sql",
			want: "7fd004f131840b938e599d6ac65f20024dcbc7e6b2d7c274e456e32290a8817f",
		},
		{
			name: "down",
			file: "000066_knowledge_revision_manifest.down.sql",
			want: "19f60a922f682deb818897a05b84e7fe70d9cedf82eba942dc40b1c9ec60dc58",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			content, err := os.ReadFile(filepath.Join(fixtureDir, tt.file))
			require.NoError(t, err)
			require.Equal(t, tt.want, fmt.Sprintf("%x", sha256.Sum256(content)))
		})
	}
}

func TestRuntimeOfficialMigrationHeadMatchesAdoptionManifest(t *testing.T) {
	_, file, _, ok := runtime.Caller(0)
	require.True(t, ok)
	manifestBytes, err := os.ReadFile(filepath.Join(
		filepath.Dir(file),
		"..",
		"..",
		"deploy",
		"upstream",
		"weknora-adoption-target.json",
	))
	require.NoError(t, err)
	var manifest struct {
		SchemaVersion         int    `json:"schema_version"`
		Commit                string `json:"commit"`
		Tree                  string `json:"tree"`
		OfficialMigrationHead int64  `json:"official_migration_head"`
	}
	require.NoError(t, json.Unmarshal(manifestBytes, &manifest))

	target := upstream.Must()
	require.Equal(t, 1, target.SchemaVersion)
	require.Equal(t, manifest.SchemaVersion, target.SchemaVersion)
	require.Equal(t, manifest.OfficialMigrationHead, target.OfficialMigrationHead)
	require.Equal(t, manifest.OfficialMigrationHead, upstream.OfficialMigrationHead())
	require.Positive(t, upstream.OfficialMigrationHead())
	require.Equal(t, "f17ee8a8da901bd658a4cb25f40b5fd41adbfdd7", manifest.Commit)
	require.Equal(t, "de9e8951de64824a2f654d8ff5ace37fe5672b23", manifest.Tree)
	require.EqualValues(t, 134, manifest.OfficialMigrationHead)
}

type bridgeStateSequence struct {
	states []legacyW1BridgeState
	seen   []string
}

func (s *bridgeStateSequence) inspect(
	_ context.Context,
	queryer legacyW1StateQueryer,
) (legacyW1BridgeState, error) {
	switch queryer.(type) {
	case *sql.DB:
		s.seen = append(s.seen, "preflight")
	case *sql.Tx:
		s.seen = append(s.seen, "locked")
	default:
		s.seen = append(s.seen, "unknown")
	}
	if len(s.states) == 0 {
		return legacyW1BridgeState{}, errors.New("unexpected inspection")
	}
	state := s.states[0]
	s.states = s.states[1:]
	return state, nil
}

func newBridgeSQLMock(t *testing.T) (*sql.DB, sqlmock.Sqlmock) {
	t.Helper()
	db, mock, err := sqlmock.New(sqlmock.QueryMatcherOption(sqlmock.QueryMatcherEqual))
	require.NoError(t, err)
	t.Cleanup(func() {
		mock.ExpectClose()
		require.NoError(t, db.Close())
	})
	return db, mock
}

func exactLegacy66State() legacyW1BridgeState {
	return legacyW1BridgeState{
		fixtureChecksumValid: true,
		officialLedgerExists: true,
		officialVersion:      66,
		w1State:              legacyW1Exact,
		spanState:            spanNameLegacy64,
	}
}

func fullCurrentState() legacyW1BridgeState {
	return legacyW1BridgeState{
		fixtureChecksumValid:   true,
		officialLedgerExists:   true,
		officialVersion:        upstream.OfficialMigrationHead(),
		w1State:                legacyW1Exact,
		spanState:              spanNameExpanded255,
		enterpriseLedgerExists: true,
		enterpriseVersion:      1,
	}
}

func TestAcquireLegacyW1MigrationGuardRejectsDirtyBeforeLockOrWrite(t *testing.T) {
	db, mock := newBridgeSQLMock(t)
	state := exactLegacy66State()
	state.officialDirty = true
	sequence := &bridgeStateSequence{states: []legacyW1BridgeState{state}}

	guard, err := acquireLegacyW1MigrationGuard(
		context.Background(),
		db,
		sequence.inspect,
	)

	require.Nil(t, guard)
	var safetyErr *MigrationSafetyError
	require.ErrorAs(t, err, &safetyErr)
	require.ErrorContains(t, err, "dirty")
	require.Equal(t, []string{"preflight"}, sequence.seen)
	require.NoError(t, mock.ExpectationsWereMet(), "dirty state must not begin, lock, force, or write")
}

func TestAcquireLegacyW1MigrationGuardReturnsTypedSafetyErrorOnInspectionFailure(t *testing.T) {
	db, mock := newBridgeSQLMock(t)
	inspectErr := errors.New("catalog unavailable")
	inspect := func(
		context.Context,
		legacyW1StateQueryer,
	) (legacyW1BridgeState, error) {
		return legacyW1BridgeState{}, inspectErr
	}

	guard, err := acquireLegacyW1MigrationGuard(context.Background(), db, inspect)

	require.Nil(t, guard)
	var safetyErr *MigrationSafetyError
	require.ErrorAs(t, err, &safetyErr)
	require.ErrorIs(t, err, inspectErr)
	require.NoError(t, mock.ExpectationsWereMet())
}

func TestAcquireLegacyW1MigrationGuardRejectsUnknownBeforeLockOrWrite(t *testing.T) {
	db, mock := newBridgeSQLMock(t)
	state := exactLegacy66State()
	state.spanState = spanNameExpanded255
	sequence := &bridgeStateSequence{states: []legacyW1BridgeState{state}}

	guard, err := acquireLegacyW1MigrationGuard(
		context.Background(),
		db,
		sequence.inspect,
	)

	require.Nil(t, guard)
	var safetyErr *MigrationSafetyError
	require.ErrorAs(t, err, &safetyErr)
	require.ErrorContains(t, err, "unknown legacy W1 migration origin")
	require.Equal(t, []string{"preflight"}, sequence.seen)
	require.NoError(t, mock.ExpectationsWereMet(), "unknown state must remain zero-write")
}

func TestAcquireLegacyW1MigrationGuardRejectsLockedSnapshotDriftWithoutWrite(t *testing.T) {
	db, mock := newBridgeSQLMock(t)
	before := exactLegacy66State()
	after := before
	after.spanState = spanNameExpanded255
	sequence := &bridgeStateSequence{states: []legacyW1BridgeState{before, after}}

	mock.ExpectExec("SELECT pg_advisory_lock($1)").
		WithArgs(legacyW1BridgeAdvisoryLockKey).
		WillReturnResult(sqlmock.NewResult(0, 1))
	mock.ExpectBegin()
	mock.ExpectRollback()
	mock.ExpectQuery("SELECT pg_advisory_unlock($1)").
		WithArgs(legacyW1BridgeAdvisoryLockKey).
		WillReturnRows(sqlmock.NewRows([]string{"unlocked"}).AddRow(true))

	guard, err := acquireLegacyW1MigrationGuard(
		context.Background(),
		db,
		sequence.inspect,
	)

	require.Nil(t, guard)
	var safetyErr *MigrationSafetyError
	require.ErrorAs(t, err, &safetyErr)
	require.ErrorContains(t, err, "changed after advisory lock")
	require.Equal(t, []string{"preflight", "locked"}, sequence.seen)
	require.NoError(t, mock.ExpectationsWereMet())
}

func TestAcquireLegacyW1MigrationGuardConvergesOnlyExactLegacy66(t *testing.T) {
	db, mock := newBridgeSQLMock(t)
	state := exactLegacy66State()
	sequence := &bridgeStateSequence{states: []legacyW1BridgeState{state, state}}

	mock.ExpectExec("SELECT pg_advisory_lock($1)").
		WithArgs(legacyW1BridgeAdvisoryLockKey).
		WillReturnResult(sqlmock.NewResult(0, 1))
	mock.ExpectBegin()
	mock.ExpectExec(
		"ALTER TABLE knowledge_processing_spans ALTER COLUMN name TYPE VARCHAR(255)",
	).WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectExec(
		"CREATE TABLE enterprise_schema_migrations (version BIGINT NOT NULL PRIMARY KEY, dirty BOOLEAN NOT NULL)",
	).WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectExec(
		"INSERT INTO enterprise_schema_migrations (version, dirty) VALUES ($1, $2)",
	).WithArgs(1, false).WillReturnResult(sqlmock.NewResult(0, 1))
	mock.ExpectCommit()
	mock.ExpectQuery("SELECT pg_advisory_unlock($1)").
		WithArgs(legacyW1BridgeAdvisoryLockKey).
		WillReturnRows(sqlmock.NewRows([]string{"unlocked"}).AddRow(true))

	guard, err := acquireLegacyW1MigrationGuard(
		context.Background(),
		db,
		sequence.inspect,
	)
	require.NoError(t, err)
	require.NotNil(t, guard)
	require.Equal(t, legacyW1OriginExactLegacy66, guard.origin)
	require.Equal(t, []string{"preflight", "locked"}, sequence.seen)
	require.NoError(t, guard.Release(context.Background()))
	require.NoError(t, mock.ExpectationsWereMet())
}

func TestAcquireLegacyW1MigrationGuardHoldsFullCurrentLockWithoutConvergenceWrites(t *testing.T) {
	db, mock := newBridgeSQLMock(t)
	state := fullCurrentState()
	sequence := &bridgeStateSequence{states: []legacyW1BridgeState{state, state}}

	mock.ExpectExec("SELECT pg_advisory_lock($1)").
		WithArgs(legacyW1BridgeAdvisoryLockKey).
		WillReturnResult(sqlmock.NewResult(0, 1))
	mock.ExpectBegin()
	mock.ExpectRollback()
	mock.ExpectQuery("SELECT pg_advisory_unlock($1)").
		WithArgs(legacyW1BridgeAdvisoryLockKey).
		WillReturnRows(sqlmock.NewRows([]string{"unlocked"}).AddRow(true))

	guard, err := acquireLegacyW1MigrationGuard(
		context.Background(),
		db,
		sequence.inspect,
	)
	require.NoError(t, err)
	require.Equal(t, legacyW1OriginFullCurrent, guard.origin)
	require.Equal(t, []string{"preflight", "locked"}, sequence.seen)
	require.NoError(t, guard.Release(context.Background()))
	require.NoError(t, mock.ExpectationsWereMet())
}

func TestLegacyW1MigrationGuardReleaseUsesCleanupContextAndRejectsFalse(t *testing.T) {
	db, mock := newBridgeSQLMock(t)
	state := fullCurrentState()
	sequence := &bridgeStateSequence{states: []legacyW1BridgeState{state, state}}

	mock.ExpectExec("SELECT pg_advisory_lock($1)").
		WithArgs(legacyW1BridgeAdvisoryLockKey).
		WillReturnResult(sqlmock.NewResult(0, 1))
	mock.ExpectBegin()
	mock.ExpectRollback()
	mock.ExpectQuery("SELECT pg_advisory_unlock($1)").
		WithArgs(legacyW1BridgeAdvisoryLockKey).
		WillReturnRows(sqlmock.NewRows([]string{"unlocked"}).AddRow(false))

	guard, err := acquireLegacyW1MigrationGuard(
		context.Background(),
		db,
		sequence.inspect,
	)
	require.NoError(t, err)

	cancelled, cancel := context.WithCancel(context.Background())
	cancel()
	err = guard.Release(cancelled)

	var safetyErr *MigrationSafetyError
	require.ErrorAs(t, err, &safetyErr)
	require.ErrorContains(t, err, "advisory lock was not held")
	require.NoError(t, mock.ExpectationsWereMet())
}

func TestAcquireLegacyW1MigrationGuardDiscardsConnectionWhenLockStateIsUnknown(t *testing.T) {
	db, mock := newBridgeSQLMock(t)
	state := fullCurrentState()
	sequence := &bridgeStateSequence{states: []legacyW1BridgeState{state}}
	lockErr := errors.New("connection interrupted during advisory lock")
	mock.ExpectExec("SELECT pg_advisory_lock($1)").
		WithArgs(legacyW1BridgeAdvisoryLockKey).
		WillReturnError(lockErr)

	originalDiscard := discardLegacyW1Connection
	discardCalled := false
	discardLegacyW1Connection = func(*sql.Conn) error {
		discardCalled = true
		return nil
	}
	t.Cleanup(func() { discardLegacyW1Connection = originalDiscard })

	guard, err := acquireLegacyW1MigrationGuard(context.Background(), db, sequence.inspect)

	require.Nil(t, guard)
	require.ErrorIs(t, err, lockErr)
	var safetyErr *MigrationSafetyError
	require.ErrorAs(t, err, &safetyErr)
	require.True(t, discardCalled)
	require.NoError(t, mock.ExpectationsWereMet())
}

func TestLegacyW1MigrationGuardReleaseDiscardsConnectionWhenUnlockStateIsUnknown(t *testing.T) {
	db, mock := newBridgeSQLMock(t)
	conn, err := db.Conn(context.Background())
	require.NoError(t, err)
	unlockErr := errors.New("connection interrupted during advisory unlock")
	mock.ExpectQuery("SELECT pg_advisory_unlock($1)").
		WithArgs(legacyW1BridgeAdvisoryLockKey).
		WillReturnError(unlockErr)

	originalDiscard := discardLegacyW1Connection
	discardCalled := false
	discardLegacyW1Connection = func(*sql.Conn) error {
		discardCalled = true
		return nil
	}
	t.Cleanup(func() { discardLegacyW1Connection = originalDiscard })

	err = (&legacyW1MigrationGuard{conn: conn}).Release(context.Background())

	require.ErrorIs(t, err, unlockErr)
	var safetyErr *MigrationSafetyError
	require.ErrorAs(t, err, &safetyErr)
	require.True(t, discardCalled)
	require.NoError(t, mock.ExpectationsWereMet())
}
