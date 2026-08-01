package database

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/Tencent/WeKnora/deploy/upstream"
	retrieverpostgres "github.com/Tencent/WeKnora/internal/application/repository/retriever/postgres"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/golang-migrate/migrate/v4"
	"github.com/lib/pq"
	"github.com/stretchr/testify/require"
	gormpostgres "gorm.io/driver/postgres"
	"gorm.io/gorm"
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
		SchemaVersion         int   `json:"schema_version"`
		OfficialMigrationHead int64 `json:"official_migration_head"`
	}
	require.NoError(t, json.Unmarshal(manifestBytes, &manifest))

	target := upstream.Must()
	require.Equal(t, 1, target.SchemaVersion)
	require.Equal(t, manifest.SchemaVersion, target.SchemaVersion)
	require.Equal(t, manifest.OfficialMigrationHead, target.OfficialMigrationHead)
	require.Equal(t, manifest.OfficialMigrationHead, upstream.OfficialMigrationHead())
	require.Positive(t, upstream.OfficialMigrationHead())
}

func TestClassifyLegacyW1Origin(t *testing.T) {
	officialHead := upstream.OfficialMigrationHead()
	tests := []struct {
		name    string
		state   legacyW1BridgeState
		want    legacyW1Origin
		wantErr string
	}{
		{
			name:  "fresh",
			state: legacyW1BridgeState{fixtureChecksumValid: true},
			want:  legacyW1OriginFresh,
		},
		{
			name: "official constructor residue is fresh",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      -1,
			},
			want: legacyW1OriginFresh,
		},
		{
			name: "pre66 at known runtime checkpoint",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      65,
				spanState:            spanNameLegacy64,
			},
			want: legacyW1OriginPre66,
		},
		{
			name: "early pre66 before span table",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      54,
			},
			want: legacyW1OriginPre66,
		},
		{
			name: "version65 without span table is partial",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      65,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "version54 with span table is partial",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      54,
				spanState:            spanNameLegacy64,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "upstream66 plus",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      officialHead,
				spanState:            spanNameExpanded255,
			},
			want: legacyW1OriginUpstream66Plus,
		},
		{
			name: "enterprise constructor residue after official migration",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        officialHead,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      -1,
			},
			want: legacyW1OriginUpstream66Plus,
		},
		{
			name: "exact legacy66",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      66,
				w1State:              legacyW1Exact,
				spanState:            spanNameLegacy64,
			},
			want: legacyW1OriginExactLegacy66,
		},
		{
			name: "known bridged checkpoint",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        66,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      1,
			},
			want: legacyW1OriginKnownBridged,
		},
		{
			name: "packaged enterprise head at official66 is unknown",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        66,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      int64(packagedEnterpriseMigrationHead),
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "enterprise version1 remains a known upgradeable state",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        officialHead,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      1,
			},
			want: legacyW1OriginFullCurrent,
		},
		{
			name: "packaged enterprise head before official head is unknown",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        officialHead - 1,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      int64(packagedEnterpriseMigrationHead),
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "full current at packaged enterprise head",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        officialHead,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      int64(packagedEnterpriseMigrationHead),
			},
			want: legacyW1OriginFullCurrent,
		},
		{
			name: "previous enterprise head remains upgradeable at official head",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        officialHead,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      2,
			},
			want: legacyW1OriginFullCurrent,
		},
		{
			name: "official dirty",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      66,
				officialDirty:        true,
			},
			wantErr: "dirty",
		},
		{
			name: "enterprise dirty",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        officialHead,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      1,
				enterpriseDirty:        true,
			},
			wantErr: "dirty",
		},
		{
			name: "legacy fixture checksum mismatch",
			state: legacyW1BridgeState{
				officialLedgerExists: true,
				officialVersion:      66,
				w1State:              legacyW1Exact,
				spanState:            spanNameLegacy64,
			},
			wantErr: "fixture checksum",
		},
		{
			name: "partial W1 schema",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      66,
				w1State:              legacyW1Partial,
				spanState:            spanNameLegacy64,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "legacy66 span already expanded without enterprise ledger",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      66,
				w1State:              legacyW1Exact,
				spanState:            spanNameExpanded255,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "official span and W1 exact without enterprise ledger",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      officialHead,
				w1State:              legacyW1Exact,
				spanState:            spanNameExpanded255,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "enterprise ledger without W1",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        officialHead,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      1,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "enterprise version above packaged head",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        officialHead,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      int64(packagedEnterpriseMigrationHead) + 1,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "packaged official head exceeded",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      officialHead + 1,
				spanState:            spanNameExpanded255,
			},
			wantErr: "newer than packaged head",
		},
		{
			name: "legacy W1 with empty enterprise ledger is partial",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        66,
				w1State:                legacyW1Exact,
				spanState:              spanNameLegacy64,
				enterpriseLedgerExists: true,
				enterpriseVersion:      -1,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "enterprise constructor residue before official66 is partial",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        65,
				spanState:              spanNameLegacy64,
				enterpriseLedgerExists: true,
				enterpriseVersion:      -1,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "objects without official ledger",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				w1State:              legacyW1Exact,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := classifyLegacyW1Origin(tt.state)
			if tt.wantErr != "" {
				require.ErrorContains(t, err, tt.wantErr)
				return
			}
			require.NoError(t, err)
			require.Equal(t, tt.want, got)
		})
	}
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

func TestInspectOfficialMigrationLedger(t *testing.T) {
	tests := []struct {
		name      string
		exists    bool
		exact     bool
		rows      *sqlmock.Rows
		wantExist bool
		wantVer   int64
		wantDirty bool
		wantErr   string
	}{
		{
			name:      "absent",
			wantExist: false,
		},
		{
			name:      "single clean row",
			exists:    true,
			exact:     true,
			rows:      sqlmock.NewRows([]string{"count", "version", "dirty"}).AddRow(1, 66, false),
			wantExist: true,
			wantVer:   66,
		},
		{
			name:      "empty constructor residue",
			exists:    true,
			exact:     true,
			rows:      sqlmock.NewRows([]string{"count", "version", "dirty"}).AddRow(0, 0, false),
			wantExist: true,
			wantVer:   -1,
		},
		{
			name:      "single dirty row",
			exists:    true,
			exact:     true,
			rows:      sqlmock.NewRows([]string{"count", "version", "dirty"}).AddRow(1, 66, true),
			wantExist: true,
			wantVer:   66,
			wantDirty: true,
		},
		{
			name:    "multiple rows",
			exists:  true,
			exact:   true,
			rows:    sqlmock.NewRows([]string{"count", "version", "dirty"}).AddRow(2, 66, false),
			wantErr: "exactly one row",
		},
		{
			name:    "bad structure",
			exists:  true,
			wantErr: "unexpected structure",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			db, mock := newBridgeSQLMock(t)
			mock.ExpectQuery(officialMigrationLedgerShapeSQL).
				WillReturnRows(sqlmock.NewRows([]string{"exists", "exact"}).AddRow(tt.exists, tt.exact))
			if tt.rows != nil {
				mock.ExpectQuery(officialMigrationLedgerStateSQL).WillReturnRows(tt.rows)
			}

			exists, version, dirty, err := inspectOfficialMigrationLedger(context.Background(), db)

			if tt.wantErr != "" {
				require.ErrorContains(t, err, tt.wantErr)
			} else {
				require.NoError(t, err)
				require.Equal(t, tt.wantExist, exists)
				require.Equal(t, tt.wantVer, version)
				require.Equal(t, tt.wantDirty, dirty)
			}
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestInspectEnterpriseMigrationLedgerUsesIndependentTable(t *testing.T) {
	db, mock := newBridgeSQLMock(t)
	mock.ExpectQuery(enterpriseMigrationLedgerShapeSQL).
		WillReturnRows(sqlmock.NewRows([]string{"exists", "exact"}).AddRow(true, true))
	mock.ExpectQuery(enterpriseMigrationLedgerStateSQL).
		WillReturnRows(sqlmock.NewRows([]string{"count", "version", "dirty"}).AddRow(1, 1, false))

	exists, version, dirty, err := inspectEnterpriseMigrationLedger(context.Background(), db)

	require.NoError(t, err)
	require.True(t, exists)
	require.EqualValues(t, 1, version)
	require.False(t, dirty)
	require.NoError(t, mock.ExpectationsWereMet())
}

func TestMigrationLedgerShapeSQLPinsExactConstraintInventory(t *testing.T) {
	for _, query := range []string{
		officialMigrationLedgerShapeSQL,
		enterpriseMigrationLedgerShapeSQL,
	} {
		require.Contains(t, query, "count(*) = 1")
		require.Contains(
			t,
			query,
			"count(*) FILTER (WHERE c.contype = 'p' AND c.convalidated AND NOT c.condeferrable)",
		)
	}
}

func TestInspectSpanNameFingerprint(t *testing.T) {
	tests := []struct {
		name      string
		table     bool
		column    bool
		dataType  string
		length    int64
		notNull   bool
		ordinary  bool
		noDefault bool
		wantState spanNameFingerprint
	}{
		{name: "absent", wantState: spanNameAbsent},
		{
			name: "legacy64", table: true, column: true,
			dataType: "character varying", length: 64, notNull: true,
			ordinary: true, noDefault: true, wantState: spanNameLegacy64,
		},
		{
			name: "expanded255", table: true, column: true,
			dataType: "character varying", length: 255, notNull: true,
			ordinary: true, noDefault: true, wantState: spanNameExpanded255,
		},
		{
			name: "unknown width", table: true, column: true,
			dataType: "character varying", length: 128, notNull: true,
			ordinary: true, noDefault: true, wantState: spanNameUnknown,
		},
		{
			name: "table without column", table: true,
			wantState: spanNameUnknown,
		},
		{
			name: "wrong type", table: true, column: true,
			dataType: "text", length: -1, notNull: true,
			ordinary: true, noDefault: true, wantState: spanNameUnknown,
		},
		{
			name: "nullable varchar64 is unknown", table: true, column: true,
			dataType: "character varying", length: 64,
			ordinary: true, noDefault: true, wantState: spanNameUnknown,
		},
		{
			name: "view is unknown", table: true, column: true,
			dataType: "character varying", length: 64, notNull: true,
			noDefault: true, wantState: spanNameUnknown,
		},
		{
			name: "default is unknown", table: true, column: true,
			dataType: "character varying", length: 64, notNull: true,
			ordinary: true, wantState: spanNameUnknown,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			db, mock := newBridgeSQLMock(t)
			mock.ExpectQuery(spanNameFingerprintSQL).WillReturnRows(
				sqlmock.NewRows([]string{
					"table_exists", "ordinary", "column_exists", "data_type",
					"length", "not_null", "no_default",
				}).AddRow(
					tt.table, tt.ordinary, tt.column, tt.dataType,
					tt.length, tt.notNull, tt.noDefault,
				),
			)

			got, err := inspectSpanNameFingerprint(context.Background(), db)

			require.NoError(t, err)
			require.Equal(t, tt.wantState, got)
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestInspectLegacyW1Fingerprint(t *testing.T) {
	tests := []struct {
		name         string
		presentCount int64
		exactCount   int64
		want         legacyW1Fingerprint
	}{
		{name: "all absent", want: legacyW1Absent},
		{name: "all exact", presentCount: 6, exactCount: 6, want: legacyW1Exact},
		{name: "partial presence", presentCount: 5, exactCount: 5, want: legacyW1Partial},
		{name: "all present but definition drift", presentCount: 6, exactCount: 5, want: legacyW1Partial},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			db, mock := newBridgeSQLMock(t)
			mock.ExpectQuery(legacyW1FingerprintSQL).WillReturnRows(
				sqlmock.NewRows([]string{"present_count", "exact_count"}).
					AddRow(tt.presentCount, tt.exactCount),
			)

			got, err := inspectLegacyW1Fingerprint(context.Background(), db)

			require.NoError(t, err)
			require.Equal(t, tt.want, got)
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestLegacyW1FingerprintSQLPinsEveryLegacyObjectDefinition(t *testing.T) {
	for _, fragment := range []string{
		"current_parse_attempt", "file_sha256", "parse_attempt",
		"knowledge_revisions", "knowledge_id", "parser_identity",
		"manifest_algorithm", "manifest_digest", "chunk_count", "completed_at",
		"PRIMARY KEY", "FOREIGN KEY", "ON DELETE CASCADE",
		"parse_attempt > 0", "^[0-9a-f]{64}$", "chunk_count >= 0",
		"idx_chunks_live_text_revision_ordinal", "knowledge_id, parse_attempt, chunk_index",
		"deleted_at IS NULL", "chunk_type", "idx_knowledge_revisions_completed",
		"knowledge_id, completed_at DESC",
	} {
		require.Contains(t, legacyW1FingerprintSQL, fragment)
	}
}

func TestFixedCatalogFingerprintSQLPinsStructuralExactness(t *testing.T) {
	for _, query := range []string{
		officialMigrationLedgerShapeSQL,
		enterpriseMigrationLedgerShapeSQL,
	} {
		require.Contains(t, query, "relkind = 'r'")
	}
	for _, fragment := range []string{
		"relkind = 'r'", "c.convalidated", "NOT c.condeferrable",
		"am.amname = 'btree'", "i.indislive", "i.indnkeyatts",
		"i.indnatts", "WITH ORDINALITY",
	} {
		require.Contains(t, legacyW1FingerprintSQL, fragment)
	}
	for _, fragment := range []string{"relkind = 'r'", "column_default IS NULL"} {
		require.Contains(t, spanNameFingerprintSQL, fragment)
	}
}

func TestLegacyW1FingerprintSQLPinsExactRevisionConstraintInventory(t *testing.T) {
	for _, fragment := range []string{
		"count(*) = 6",
		"count(*) FILTER (WHERE c.contype = 'p') = 1",
		"count(*) FILTER (WHERE c.contype = 'f') = 1",
		"count(*) FILTER (WHERE c.contype = 'c') = 4",
	} {
		require.Contains(t, legacyW1FingerprintSQL, fragment)
	}
}

func TestInspectDependencyAnchorFingerprint(t *testing.T) {
	tests := []struct {
		name         string
		presentCount int64
		exactCount   int64
		want         dependencyAnchorFingerprint
	}{
		{name: "both tables absent", want: dependencyAnchorsAbsent},
		{name: "both exact", presentCount: 2, exactCount: 2, want: dependencyAnchorsExact},
		{name: "half-created official schema", presentCount: 1, exactCount: 1, want: dependencyAnchorsPartial},
		{name: "definition drift", presentCount: 2, exactCount: 1, want: dependencyAnchorsPartial},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			db, mock := newBridgeSQLMock(t)
			mock.ExpectQuery(dependencyAnchorFingerprintSQL).WillReturnRows(
				sqlmock.NewRows([]string{"present_count", "exact_count"}).
					AddRow(tt.presentCount, tt.exactCount),
			)

			got, err := inspectDependencyAnchorFingerprint(context.Background(), db)

			require.NoError(t, err)
			require.Equal(t, tt.want, got)
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestDependencyAnchorFingerprintSQLPinsOnlyW1Dependencies(t *testing.T) {
	for _, fragment := range []string{
		"knowledges", "relkind = 'r'", "id", "character varying", "36",
		"PRIMARY KEY (id)",
		"chunks", "knowledge_id", "chunk_index", "integer",
		"chunk_type", "20", "DEFAULT 'text'", "deleted_at",
		"timestamp with time zone",
	} {
		require.Contains(t, dependencyAnchorFingerprintSQL, fragment)
	}
}

func TestClassifyLegacyW1OriginRequiresDependencyAnchorsAtKnownCheckpoints(t *testing.T) {
	tests := []struct {
		name    string
		state   legacyW1BridgeState
		want    legacyW1Origin
		wantErr string
	}{
		{
			name: "fresh has no dependency anchors",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				dependencyState:      dependencyAnchorsAbsent,
			},
			want: legacyW1OriginFresh,
		},
		{
			name: "no ledger with half-created official schema blocks",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				dependencyState:      dependencyAnchorsPartial,
			},
			wantErr: "dependency anchors",
		},
		{
			name: "official checkpoint requires exact anchors",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      65,
				spanState:            spanNameLegacy64,
				dependencyState:      dependencyAnchorsExact,
			},
			want: legacyW1OriginPre66,
		},
		{
			name: "official checkpoint with missing anchors blocks",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      65,
				spanState:            spanNameLegacy64,
				dependencyState:      dependencyAnchorsAbsent,
			},
			wantErr: "dependency anchors",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := classifyLegacyW1Origin(tt.state)
			if tt.wantErr != "" {
				require.ErrorContains(t, err, tt.wantErr)
				return
			}
			require.NoError(t, err)
			require.Equal(t, tt.want, got)
		})
	}
}

type recordingMigrationPhaseGuard struct {
	events *[]string
	err    error
}

func (g *recordingMigrationPhaseGuard) Release(context.Context) error {
	*g.events = append(*g.events, "release")
	return g.err
}

func TestRunPostgresMigrationPhasesOrdersPreflightOfficialEnterpriseRelease(t *testing.T) {
	var events []string
	acquire := func() (postgresMigrationPhaseGuard, error) {
		events = append(events, "raw_preflight_and_lock")
		return &recordingMigrationPhaseGuard{events: &events}, nil
	}
	official := func() error {
		events = append(events, "official_constructor_and_up")
		return nil
	}
	enterprise := func() error {
		events = append(events, "enterprise_constructor_and_up")
		return nil
	}

	err := runPostgresMigrationPhases(
		context.Background(),
		acquire,
		official,
		enterprise,
	)

	require.NoError(t, err)
	require.Equal(t, []string{
		"raw_preflight_and_lock",
		"official_constructor_and_up",
		"enterprise_constructor_and_up",
		"release",
	}, events)
}

func TestRunPostgresMigrationPhasesStopsAfterOfficialFailureAndReleases(t *testing.T) {
	var events []string
	officialErr := errors.New("official migration failed")
	err := runPostgresMigrationPhases(
		context.Background(),
		func() (postgresMigrationPhaseGuard, error) {
			events = append(events, "preflight")
			return &recordingMigrationPhaseGuard{events: &events}, nil
		},
		func() error {
			events = append(events, "official")
			return officialErr
		},
		func() error {
			events = append(events, "enterprise")
			return nil
		},
	)

	require.ErrorIs(t, err, officialErr)
	var safetyErr *MigrationSafetyError
	require.ErrorAs(t, err, &safetyErr)
	require.Equal(t, []string{"preflight", "official", "release"}, events)
}

func TestRunPostgresMigrationPhasesDoesNotLoseReleaseError(t *testing.T) {
	var events []string
	releaseErr := errors.New("unlock failed")

	err := runPostgresMigrationPhases(
		context.Background(),
		func() (postgresMigrationPhaseGuard, error) {
			return &recordingMigrationPhaseGuard{events: &events, err: releaseErr}, nil
		},
		func() error { return nil },
		func() error { return nil },
	)

	require.ErrorIs(t, err, releaseErr)
	var safetyErr *MigrationSafetyError
	require.ErrorAs(t, err, &safetyErr)
	require.Equal(t, []string{"release"}, events)
}

func TestEnterpriseMigrationDSNUsesIndependentLedger(t *testing.T) {
	got, err := enterpriseMigrationDSN(
		"postgres://user:pass@localhost:5432/weknora?sslmode=disable",
	)

	require.NoError(t, err)
	require.Contains(t, got, "x-migrations-table=enterprise_schema_migrations")
	require.Contains(t, got, "sslmode=disable")
}

func TestValidatePostgresMigrationSetVersionRequiresFrozenHeads(t *testing.T) {
	officialHead := uint(upstream.OfficialMigrationHead())
	require.NoError(t, validatePostgresMigrationSetVersion(
		officialPostgresMigrationSource,
		true,
		officialHead,
	))
	require.NoError(t, validatePostgresMigrationSetVersion(
		enterprisePostgresMigrationSource,
		false,
		packagedEnterpriseMigrationHead,
	))

	for _, tt := range []struct {
		source        string
		cacheOfficial bool
		version       uint
	}{
		{source: officialPostgresMigrationSource, cacheOfficial: true, version: officialHead - 1},
		{source: enterprisePostgresMigrationSource, version: 1},
	} {
		err := validatePostgresMigrationSetVersion(tt.source, tt.cacheOfficial, tt.version)
		var safetyErr *MigrationSafetyError
		require.ErrorAs(t, err, &safetyErr)
	}
}

func TestEnterpriseFailureDoesNotOverwriteOfficialMigrationCache(t *testing.T) {
	officialHead := uint(upstream.OfficialMigrationHead())
	oldVersion, oldDirty, oldKnown := CachedMigrationVersion()
	oldError := CachedMigrationError()
	t.Cleanup(func() {
		setMigrationState(oldVersion, oldDirty, oldError, oldKnown)
	})
	setMigrationState(officialHead, false, "", true)
	enterpriseErr := errors.New("enterprise migration failed")

	got := recordPostgresMigrationSetFailure(nil, false, enterpriseErr)

	require.ErrorIs(t, got, enterpriseErr)
	version, dirty, known := CachedMigrationVersion()
	require.True(t, known)
	require.Equal(t, officialHead, version)
	require.False(t, dirty)
	require.Empty(t, CachedMigrationError())
}

func TestPostgresLegacyW1MigrationMatrix(t *testing.T) {
	rawDSN := os.Getenv("WEKNORA_TEST_POSTGRES_URL")
	if rawDSN == "" {
		t.Skip("WEKNORA_TEST_POSTGRES_URL is not set")
	}
	matrix := newPostgresMigrationMatrix(t, rawDSN)
	officialHead := uint(upstream.OfficialMigrationHead())

	t.Run("fresh reaches both frozen heads and restarts without change", func(t *testing.T) {
		matrix.reset(t)
		require.NoError(t, matrix.run())
		matrix.requireCurrent(t)
		require.NoError(t, matrix.run())
		matrix.requireCurrent(t)
	})

	t.Run("official65 upgrades through official then enterprise", func(t *testing.T) {
		matrix.reset(t)
		matrix.migrateOfficialTo(t, 65)
		require.NoError(t, matrix.run())
		matrix.requireCurrent(t)
	})

	t.Run("official head without W1 applies enterprise1", func(t *testing.T) {
		matrix.reset(t)
		matrix.migrateOfficialTo(t, officialHead)
		require.NoError(t, matrix.run())
		matrix.requireCurrent(t)
	})

	t.Run("exact legacy66 preserves nondefault rows through bridge and restart", func(t *testing.T) {
		matrix.reset(t)
		matrix.migrateOfficialTo(t, 65)
		matrix.seedExactLegacy66(t)
		require.NoError(t, matrix.run())
		matrix.requireCurrent(t)
		matrix.requireLegacySeedPreserved(t)
		require.NoError(t, matrix.run())
		matrix.requireCurrent(t)
		matrix.requireLegacySeedPreserved(t)
	})

	t.Run("empty enterprise constructor checkpoint applies enterprise1", func(t *testing.T) {
		matrix.reset(t)
		matrix.migrateOfficialTo(t, officialHead)
		matrix.seedEmptyEnterpriseLedger(t)
		require.NoError(t, matrix.run())
		matrix.requireCurrent(t)
	})

	t.Run("dirty ledger fails typed without persistent change", func(t *testing.T) {
		matrix.reset(t)
		matrix.migrateOfficialTo(t, 65)
		matrix.markOfficialDirty(t)
		before := matrix.inspect(t)

		err := matrix.run()

		var safetyErr *MigrationSafetyError
		require.ErrorAs(t, err, &safetyErr)
		require.Equal(t, before, matrix.inspect(t))
	})

	t.Run("partial W1 fails typed without persistent change", func(t *testing.T) {
		matrix.reset(t)
		matrix.migrateOfficialTo(t, officialHead)
		matrix.seedPartialW1(t)
		before := matrix.inspect(t)

		err := matrix.run()

		var safetyErr *MigrationSafetyError
		require.ErrorAs(t, err, &safetyErr)
		require.Equal(t, before, matrix.inspect(t))
	})
}

func TestPostgresEmbeddingsForwardRepair(t *testing.T) {
	rawDSN := os.Getenv("WEKNORA_TEST_POSTGRES_URL")
	if rawDSN == "" {
		t.Skip("WEKNORA_TEST_POSTGRES_URL is not set")
	}
	requireEmbeddingsRepairTestDSN(t, rawDSN)
	matrix := newPostgresMigrationMatrix(t, rawDSN)

	t.Run("advanced ledgers with missing table are repaired", func(t *testing.T) {
		matrix.prepareEmbeddingsRepairPredecessor(t, rawDSN, true)
		require.False(t, matrix.embeddingsTableExists(t))
		repairDSN, err := postgresMatrixDSNWithSkip(rawDSN, false)
		require.NoError(t, err)

		require.NoError(t, RunMigrationsWithOptions(
			repairDSN,
			MigrationOptions{AutoRecoverDirty: true},
		))

		require.True(t, matrix.embeddingsTableExists(t))
		matrix.requireEmbeddingsSchema(t)
		matrix.requireRepository1024InsertRollsBack(t)
		require.NoError(t, RunMigrationsWithOptions(
			repairDSN,
			MigrationOptions{AutoRecoverDirty: true},
		))
	})

	t.Run("existing table and data remain unchanged", func(t *testing.T) {
		repairDSN := matrix.prepareEmbeddingsRepairPredecessor(t, rawDSN, false)
		result, err := matrix.db.ExecContext(
			context.Background(),
			`INSERT INTO embeddings
				(source_id, source_type, content, dimension, is_enabled)
			 VALUES ('existing-source', 0, 'existing-content', 1024, true)`,
		)
		require.NoError(t, err)
		affected, err := result.RowsAffected()
		require.NoError(t, err)
		require.EqualValues(t, 1, affected)

		require.NoError(t, RunMigrationsWithOptions(
			repairDSN,
			MigrationOptions{AutoRecoverDirty: true},
		))

		var content string
		require.NoError(t, matrix.db.QueryRowContext(
			context.Background(),
			"SELECT content FROM embeddings WHERE source_id = 'existing-source'",
		).Scan(&content))
		require.Equal(t, "existing-content", content)
		matrix.requireEmbeddingsSchema(t)
	})

	t.Run("partial existing table fails before enterprise ledger advances", func(t *testing.T) {
		repairDSN := matrix.prepareEmbeddingsRepairPredecessor(t, rawDSN, false)
		_, err := matrix.db.ExecContext(
			context.Background(),
			`INSERT INTO embeddings
				(source_id, source_type, content, dimension, is_enabled)
			 VALUES ('partial-source', 0, 'partial-sentinel', 1024, true);
			 DROP INDEX idx_embeddings_tag_id;
			 ALTER TABLE embeddings DROP COLUMN tag_id`,
		)
		require.NoError(t, err)
		require.False(t, matrix.embeddingsColumnExists(t, "tag_id"))

		migrationSQL, err := os.ReadFile(
			"migrations/enterprise/versioned/000003_embeddings_forward_repair.up.sql",
		)
		require.NoError(t, err)
		directDB, err := sql.Open("postgres", repairDSN)
		require.NoError(t, err)
		require.NoError(t, directDB.PingContext(context.Background()))
		_, directErr := directDB.ExecContext(
			context.Background(),
			string(migrationSQL),
		)
		require.Error(t, directErr)
		var postgresErr *pq.Error
		require.ErrorAs(t, directErr, &postgresErr)
		require.Equal(t, pq.ErrorCode("55000"), postgresErr.Code)
		require.NoError(t, directDB.Close())
		migrationErr := RunMigrationsWithOptions(
			repairDSN,
			MigrationOptions{AutoRecoverDirty: true},
		)
		require.Error(t, migrationErr)
		var safetyErr *MigrationSafetyError
		require.ErrorAs(t, migrationErr, &safetyErr)

		matrix.requireEnterpriseVersion(t, 2)
		var sentinel string
		require.NoError(t, matrix.db.QueryRowContext(
			context.Background(),
			"SELECT content FROM embeddings WHERE source_id = 'partial-source'",
		).Scan(&sentinel))
		require.Equal(t, "partial-sentinel", sentinel)
		require.False(t, matrix.embeddingsColumnExists(t, "tag_id"))
	})

	t.Run("skip embedding remains a no-op", func(t *testing.T) {
		matrix.prepareEmbeddingsRepairPredecessor(t, rawDSN, true)

		require.NoError(t, matrix.run())

		require.False(t, matrix.embeddingsTableExists(t))
		matrix.requireEnterpriseVersion(t, packagedEnterpriseMigrationHead)
	})

	t.Run("conservative down preserves the repaired table", func(t *testing.T) {
		matrix.prepareEmbeddingsRepairPredecessor(t, rawDSN, true)
		repairDSN, err := postgresMatrixDSNWithSkip(rawDSN, false)
		require.NoError(t, err)
		require.NoError(t, RunMigrationsWithOptions(
			repairDSN,
			MigrationOptions{AutoRecoverDirty: true},
		))
		_, err = matrix.db.ExecContext(
			context.Background(),
			`INSERT INTO embeddings
				(source_id, source_type, content, dimension, is_enabled)
			 VALUES ('down-source', 0, 'preserve-on-down', 1024, true)`,
		)
		require.NoError(t, err)

		enterpriseDSN, err := enterpriseMigrationDSN(repairDSN)
		require.NoError(t, err)
		enterpriseMigrator, err := migrate.New(enterprisePostgresMigrationSource, enterpriseDSN)
		require.NoError(t, err)
		require.NoError(t, enterpriseMigrator.Steps(-1))
		matrix.requireEnterpriseVersion(t, 2)
		require.True(t, matrix.embeddingsTableExists(t))
		var content string
		require.NoError(t, matrix.db.QueryRowContext(
			context.Background(),
			"SELECT content FROM embeddings WHERE source_id = 'down-source'",
		).Scan(&content))
		require.Equal(t, "preserve-on-down", content)
		require.NoError(t, enterpriseMigrator.Migrate(packagedEnterpriseMigrationHead))
		sourceErr, databaseErr := enterpriseMigrator.Close()
		require.NoError(t, sourceErr)
		require.NoError(t, databaseErr)
		matrix.requireEnterpriseVersion(t, packagedEnterpriseMigrationHead)
	})
}

type postgresMigrationMatrix struct {
	db  *sql.DB
	dsn string
}

func newPostgresMigrationMatrix(t *testing.T, rawDSN string) *postgresMigrationMatrix {
	t.Helper()
	dsn, err := postgresMatrixDSN(rawDSN)
	require.NoError(t, err)

	_, file, _, ok := runtime.Caller(0)
	require.True(t, ok)
	t.Chdir(filepath.Join(filepath.Dir(file), "..", ".."))

	db, err := sql.Open("postgres", dsn)
	require.NoError(t, err)
	require.NoError(t, db.PingContext(context.Background()))
	matrix := &postgresMigrationMatrix{db: db, dsn: dsn}
	t.Cleanup(func() {
		_, resetErr := db.ExecContext(
			context.Background(),
			"DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public",
		)
		require.NoError(t, resetErr)
		require.NoError(t, db.Close())
	})
	return matrix
}

func postgresMatrixDSN(rawDSN string) (string, error) {
	return postgresMatrixDSNWithSkip(rawDSN, true)
}

func postgresMatrixDSNWithSkip(rawDSN string, skipEmbedding bool) (string, error) {
	parsed, err := url.Parse(rawDSN)
	if err != nil {
		return "", fmt.Errorf("parse PostgreSQL matrix DSN: %w", err)
	}
	if parsed.Scheme != "postgres" && parsed.Scheme != "postgresql" {
		return "", fmt.Errorf("PostgreSQL matrix DSN has unsupported scheme %q", parsed.Scheme)
	}
	query := parsed.Query()
	options := query.Get("options")
	if options != "" {
		options += " "
	}
	query.Set("options", fmt.Sprintf(
		"%s-c app.skip_embedding=%t",
		options,
		skipEmbedding,
	))
	query.Del("x-migrations-table")
	query.Del("x-migrations-table-quoted")
	parsed.RawQuery = query.Encode()
	return parsed.String(), nil
}

func requireEmbeddingsRepairTestDSN(t *testing.T, rawDSN string) {
	t.Helper()
	parsed, err := url.Parse(rawDSN)
	require.NoError(t, err)
	require.Equal(t, "/weknora_embeddings_repair_test", parsed.Path)
}

func (m *postgresMigrationMatrix) prepareEmbeddingsRepairPredecessor(
	t *testing.T,
	rawDSN string,
	skipEmbedding bool,
) string {
	t.Helper()
	m.reset(t)
	dsn, err := postgresMatrixDSNWithSkip(rawDSN, skipEmbedding)
	require.NoError(t, err)
	migratePostgresSourceTo(
		t,
		officialPostgresMigrationSource,
		dsn,
		uint(upstream.OfficialMigrationHead()),
	)
	enterpriseDSN, err := enterpriseMigrationDSN(dsn)
	require.NoError(t, err)
	migratePostgresSourceTo(t, enterprisePostgresMigrationSource, enterpriseDSN, 2)
	return dsn
}

func migratePostgresSourceTo(t *testing.T, source, dsn string, version uint) {
	t.Helper()
	migrator, err := migrate.New(source, dsn)
	require.NoError(t, err)
	require.NoError(t, migrator.Migrate(version))
	sourceErr, databaseErr := migrator.Close()
	require.NoError(t, sourceErr)
	require.NoError(t, databaseErr)
}

func (m *postgresMigrationMatrix) embeddingsTableExists(t *testing.T) bool {
	t.Helper()
	var exists bool
	require.NoError(t, m.db.QueryRowContext(
		context.Background(),
		"SELECT to_regclass('public.embeddings') IS NOT NULL",
	).Scan(&exists))
	return exists
}

func (m *postgresMigrationMatrix) embeddingsColumnExists(
	t *testing.T,
	columnName string,
) bool {
	t.Helper()
	var exists bool
	require.NoError(t, m.db.QueryRowContext(
		context.Background(),
		`SELECT EXISTS (
			SELECT 1
			  FROM information_schema.columns
			 WHERE table_schema = 'public'
			   AND table_name = 'embeddings'
			   AND column_name = $1
		)`,
		columnName,
	).Scan(&exists))
	return exists
}

func (m *postgresMigrationMatrix) requireEnterpriseVersion(t *testing.T, want uint) {
	t.Helper()
	var version uint
	var dirty bool
	require.NoError(t, m.db.QueryRowContext(
		context.Background(),
		"SELECT version, dirty FROM enterprise_schema_migrations",
	).Scan(&version, &dirty))
	require.Equal(t, want, version)
	require.False(t, dirty)
}

func (m *postgresMigrationMatrix) requireEmbeddingsSchema(t *testing.T) {
	t.Helper()
	type column struct {
		name     string
		dataType string
		notNull  bool
	}
	rows, err := m.db.QueryContext(
		context.Background(),
		`SELECT attname, format_type(atttypid, atttypmod), attnotnull
		   FROM pg_attribute
		  WHERE attrelid = 'public.embeddings'::regclass
		    AND attnum > 0
		    AND NOT attisdropped
		  ORDER BY attnum`,
	)
	require.NoError(t, err)
	defer rows.Close()
	var got []column
	for rows.Next() {
		var value column
		require.NoError(t, rows.Scan(&value.name, &value.dataType, &value.notNull))
		got = append(got, value)
	}
	require.NoError(t, rows.Err())
	require.Equal(t, []column{
		{name: "id", dataType: "integer", notNull: true},
		{name: "created_at", dataType: "timestamp with time zone"},
		{name: "updated_at", dataType: "timestamp with time zone"},
		{name: "source_id", dataType: "character varying(64)", notNull: true},
		{name: "source_type", dataType: "integer", notNull: true},
		{name: "chunk_id", dataType: "character varying(64)"},
		{name: "knowledge_id", dataType: "character varying(64)"},
		{name: "knowledge_base_id", dataType: "character varying(64)"},
		{name: "content", dataType: "text"},
		{name: "dimension", dataType: "integer", notNull: true},
		{name: "embedding", dataType: "halfvec"},
		{name: "is_enabled", dataType: "boolean"},
		{name: "tag_id", dataType: "character varying(36)"},
	}, got)

	indexRows, err := m.db.QueryContext(
		context.Background(),
		`SELECT indexname
		   FROM pg_indexes
		  WHERE schemaname = 'public' AND tablename = 'embeddings'`,
	)
	require.NoError(t, err)
	defer indexRows.Close()
	var indexes []string
	for indexRows.Next() {
		var name string
		require.NoError(t, indexRows.Scan(&name))
		indexes = append(indexes, name)
	}
	require.NoError(t, indexRows.Err())
	require.ElementsMatch(t, []string{
		"embeddings_pkey",
		"embeddings_unique_source",
		"embeddings_search_idx",
		"embeddings_embedding_idx_3584",
		"embeddings_embedding_idx_798",
		"embeddings_embedding_idx_1024",
		"idx_embeddings_is_enabled",
		"idx_embeddings_knowledge_base_id",
		"idx_embeddings_tag_id",
	}, indexes)
}

func (m *postgresMigrationMatrix) requireRepository1024InsertRollsBack(
	t *testing.T,
) {
	t.Helper()
	tx, err := m.db.BeginTx(context.Background(), nil)
	require.NoError(t, err)
	gormDB, err := gorm.Open(
		gormpostgres.New(gormpostgres.Config{Conn: tx}),
		&gorm.Config{DisableAutomaticPing: true, SkipDefaultTransaction: true},
	)
	require.NoError(t, err)
	repository := retrieverpostgres.NewPostgresRetrieveEngineRepository(gormDB)
	const sourceID = "repair-1024-source"
	require.NoError(t, repository.BatchSave(
		context.Background(),
		[]*types.IndexInfo{{
			Content:         "synthetic repair verification",
			SourceID:        sourceID,
			SourceType:      types.ChunkSourceType,
			ChunkID:         "repair-1024-chunk",
			KnowledgeID:     "repair-1024-knowledge",
			KnowledgeBaseID: "repair-1024-kb",
			IsEnabled:       true,
		}},
		map[string]any{"embedding": map[string][]float32{
			sourceID: make([]float32, 1024),
		}},
	))
	var count int
	require.NoError(t, tx.QueryRowContext(
		context.Background(),
		"SELECT COUNT(*) FROM embeddings WHERE source_id = $1",
		sourceID,
	).Scan(&count))
	require.Equal(t, 1, count)
	require.NoError(t, tx.Rollback())
	require.NoError(t, m.db.QueryRowContext(
		context.Background(),
		"SELECT COUNT(*) FROM embeddings WHERE source_id = $1",
		sourceID,
	).Scan(&count))
	require.Zero(t, count)
}

func (m *postgresMigrationMatrix) reset(t *testing.T) {
	t.Helper()
	_, err := m.db.ExecContext(
		context.Background(),
		"DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public",
	)
	require.NoError(t, err)
}

func (m *postgresMigrationMatrix) run() error {
	return RunMigrationsWithOptions(
		m.dsn,
		MigrationOptions{AutoRecoverDirty: true},
	)
}

func (m *postgresMigrationMatrix) migrateOfficialTo(t *testing.T, version uint) {
	t.Helper()
	migrator, err := migrate.New(officialPostgresMigrationSource, m.dsn)
	require.NoError(t, err)
	require.NoError(t, migrator.Migrate(version))
	sourceErr, databaseErr := migrator.Close()
	require.NoError(t, sourceErr)
	require.NoError(t, databaseErr)
}

func (m *postgresMigrationMatrix) requireCurrent(t *testing.T) {
	t.Helper()
	state := m.inspect(t)
	require.True(t, state.fixtureChecksumValid)
	require.True(t, state.officialLedgerExists)
	require.EqualValues(t, upstream.OfficialMigrationHead(), state.officialVersion)
	require.False(t, state.officialDirty)
	require.True(t, state.enterpriseLedgerExists)
	require.EqualValues(t, packagedEnterpriseMigrationHead, state.enterpriseVersion)
	require.False(t, state.enterpriseDirty)
	require.Equal(t, dependencyAnchorsExact, state.dependencyState)
	require.Equal(t, spanNameExpanded255, state.spanState)
	require.Equal(t, legacyW1Exact, state.w1State)
	origin, err := classifyLegacyW1Origin(state)
	require.NoError(t, err)
	require.Equal(t, legacyW1OriginFullCurrent, origin)
}

func (m *postgresMigrationMatrix) inspect(t *testing.T) legacyW1BridgeState {
	t.Helper()
	state, err := inspectLegacyW1BridgeState(context.Background(), m.db)
	require.NoError(t, err)
	return state
}

func (m *postgresMigrationMatrix) seedExactLegacy66(t *testing.T) {
	t.Helper()
	_, err := m.db.ExecContext(context.Background(), string(legacyW1UpFixture))
	require.NoError(t, err)
	result, err := m.db.ExecContext(
		context.Background(),
		"UPDATE schema_migrations SET version = 66, dirty = false WHERE version = 65",
	)
	require.NoError(t, err)
	affected, err := result.RowsAffected()
	require.NoError(t, err)
	require.EqualValues(t, 1, affected)

	const knowledgeID = "11111111-1111-1111-1111-111111111111"
	const knowledgeBaseID = "22222222-2222-2222-2222-222222222222"
	const chunkID = "33333333-3333-3333-3333-333333333333"
	const fileSHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	const manifestSHA = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

	_, err = m.db.ExecContext(
		context.Background(),
		`INSERT INTO knowledges (
		    id, tenant_id, knowledge_base_id, type, title, source,
		    current_parse_attempt, file_sha256
		) VALUES ($1, 12345, $2, 'file', 'legacy matrix title', 'legacy://matrix', 42, $3)`,
		knowledgeID,
		knowledgeBaseID,
		fileSHA,
	)
	require.NoError(t, err)
	_, err = m.db.ExecContext(
		context.Background(),
		`INSERT INTO chunks (
		    id, tenant_id, knowledge_base_id, knowledge_id, content,
		    chunk_index, start_at, end_at, parse_attempt
		) VALUES ($1, 12345, $2, $3, 'legacy matrix content', 7, 11, 29, 42)`,
		chunkID,
		knowledgeBaseID,
		knowledgeID,
	)
	require.NoError(t, err)
	_, err = m.db.ExecContext(
		context.Background(),
		`INSERT INTO knowledge_revisions (
		    knowledge_id, parse_attempt, file_sha256, parser_identity,
		    manifest_algorithm, manifest_digest, chunk_count, completed_at
		) VALUES (
		    $1, 42, $2, '{"mode":"legacy","v":9}'::jsonb,
		    'matrix-v9', $3, 7, TIMESTAMP '2024-02-03 04:05:06'
		)`,
		knowledgeID,
		fileSHA,
		manifestSHA,
	)
	require.NoError(t, err)
}

func (m *postgresMigrationMatrix) requireLegacySeedPreserved(t *testing.T) {
	t.Helper()
	const knowledgeID = "11111111-1111-1111-1111-111111111111"
	const fileSHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	const manifestSHA = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

	var attempt int64
	var fileHash, title string
	require.NoError(t, m.db.QueryRowContext(
		context.Background(),
		`SELECT current_parse_attempt, file_sha256, title
		 FROM knowledges WHERE id = $1`,
		knowledgeID,
	).Scan(&attempt, &fileHash, &title))
	require.EqualValues(t, 42, attempt)
	require.Equal(t, fileSHA, fileHash)
	require.Equal(t, "legacy matrix title", title)

	var chunkAttempt int64
	var content string
	var chunkIndex int
	require.NoError(t, m.db.QueryRowContext(
		context.Background(),
		`SELECT parse_attempt, content, chunk_index
		 FROM chunks WHERE knowledge_id = $1`,
		knowledgeID,
	).Scan(&chunkAttempt, &content, &chunkIndex))
	require.EqualValues(t, 42, chunkAttempt)
	require.Equal(t, "legacy matrix content", content)
	require.Equal(t, 7, chunkIndex)

	var parserIdentity, algorithm, manifestDigest, completedAt string
	var chunkCount int
	require.NoError(t, m.db.QueryRowContext(
		context.Background(),
		`SELECT parser_identity::text, manifest_algorithm, manifest_digest,
		        chunk_count, to_char(completed_at, 'YYYY-MM-DD HH24:MI:SS')
		 FROM knowledge_revisions
		 WHERE knowledge_id = $1 AND parse_attempt = 42`,
		knowledgeID,
	).Scan(
		&parserIdentity,
		&algorithm,
		&manifestDigest,
		&chunkCount,
		&completedAt,
	))
	require.JSONEq(t, `{"mode":"legacy","v":9}`, parserIdentity)
	require.Equal(t, "matrix-v9", algorithm)
	require.Equal(t, manifestSHA, manifestDigest)
	require.Equal(t, 7, chunkCount)
	require.Equal(t, "2024-02-03 04:05:06", completedAt)
}

func (m *postgresMigrationMatrix) seedEmptyEnterpriseLedger(t *testing.T) {
	t.Helper()
	_, err := m.db.ExecContext(
		context.Background(),
		`CREATE TABLE enterprise_schema_migrations (
		    version BIGINT NOT NULL PRIMARY KEY,
		    dirty BOOLEAN NOT NULL
		)`,
	)
	require.NoError(t, err)
}

func (m *postgresMigrationMatrix) markOfficialDirty(t *testing.T) {
	t.Helper()
	result, err := m.db.ExecContext(
		context.Background(),
		"UPDATE schema_migrations SET dirty = true WHERE version = 65",
	)
	require.NoError(t, err)
	affected, err := result.RowsAffected()
	require.NoError(t, err)
	require.EqualValues(t, 1, affected)
}

func (m *postgresMigrationMatrix) seedPartialW1(t *testing.T) {
	t.Helper()
	_, err := m.db.ExecContext(
		context.Background(),
		"ALTER TABLE knowledges ADD COLUMN current_parse_attempt BIGINT NOT NULL DEFAULT 0",
	)
	require.NoError(t, err)
}
