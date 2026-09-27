package database

import (
	"context"
	"database/sql"
	"errors"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/stretchr/testify/require"
)

func newPgSearchSQLMock(t *testing.T) (*sql.DB, sqlmock.Sqlmock) {
	t.Helper()
	db, mock, err := sqlmock.New(sqlmock.QueryMatcherOption(sqlmock.QueryMatcherEqual))
	require.NoError(t, err)
	t.Cleanup(func() {
		mock.ExpectClose()
		require.NoError(t, db.Close())
	})
	return db, mock
}

func expectPgSearchMode(mock sqlmock.Sqlmock, mode interface{}) {
	mock.ExpectQuery(pgSearchMigrationModeSQL).
		WillReturnRows(sqlmock.NewRows([]string{"skip_embedding"}).AddRow(mode))
}

func expectPgSearchState(mock sqlmock.Sqlmock, version interface{}, targetAvailable bool) {
	mock.ExpectQuery(pgSearchUpgradeStateSQL).
		WillReturnRows(sqlmock.NewRows([]string{"installed_version", "target_available"}).
			AddRow(version, targetAvailable))
}

func TestValidatePgSearchUpgradePreflight(t *testing.T) {
	tests := []struct {
		name            string
		mode            interface{}
		version         interface{}
		targetAvailable bool
		wantErr         string
	}{
		{name: "external retriever skips extension gate", mode: "true"},
		{name: "supported installed source can upgrade", mode: "false", version: "0.22.2", targetAvailable: true},
		{name: "target already installed", mode: "false", version: pgSearchTargetVersion, targetAvailable: true},
		{name: "missing target package blocks before migration", mode: "false", version: "0.22.2", wantErr: "is not available"},
		{name: "unsupported installed line blocks before migration", mode: "false", version: "0.21.0", targetAvailable: true, wantErr: "unsupported installed pg_search version"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			db, mock := newPgSearchSQLMock(t)
			expectPgSearchMode(mock, tt.mode)
			if tt.mode != "true" {
				expectPgSearchState(mock, tt.version, tt.targetAvailable)
			}

			err := validatePgSearchUpgradePreflight(context.Background(), db)
			if tt.wantErr != "" {
				require.ErrorContains(t, err, tt.wantErr)
			} else {
				require.NoError(t, err)
			}
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestValidatePgSearchUpgradePreflightAllowsFreshInstallOnly(t *testing.T) {
	t.Run("fresh database with target package available", func(t *testing.T) {
		db, mock := newPgSearchSQLMock(t)
		expectPgSearchMode(mock, nil)
		expectPgSearchState(mock, nil, true)

		require.NoError(t, validatePgSearchUpgradePreflight(context.Background(), db))
		require.NoError(t, mock.ExpectationsWereMet())
	})

	t.Run("existing official checkpoint missing extension can be reconciled", func(t *testing.T) {
		db, mock := newPgSearchSQLMock(t)
		expectPgSearchMode(mock, "false")
		expectPgSearchState(mock, nil, true)

		require.NoError(t, validatePgSearchUpgradePreflight(context.Background(), db))
		require.NoError(t, mock.ExpectationsWereMet())
	})
}

func TestValidatePgSearchUpgradePostcondition(t *testing.T) {
	for _, tt := range []struct {
		name    string
		mode    interface{}
		version interface{}
		wantErr string
	}{
		{name: "external retriever skips extension gate", mode: "true"},
		{name: "target installed", mode: "false", version: pgSearchTargetVersion},
		{name: "migration notice cannot mask old version", mode: "false", version: "0.22.2", wantErr: "expected pg_search 0.22.6"},
		{name: "missing extension is rejected", mode: "false", version: nil, wantErr: "expected pg_search 0.22.6"},
	} {
		t.Run(tt.name, func(t *testing.T) {
			db, mock := newPgSearchSQLMock(t)
			expectPgSearchMode(mock, tt.mode)
			if tt.mode != "true" {
				expectPgSearchState(mock, tt.version, true)
			}

			err := validatePgSearchUpgradePostcondition(context.Background(), db)
			if tt.wantErr != "" {
				require.ErrorContains(t, err, tt.wantErr)
			} else {
				require.NoError(t, err)
			}
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestRunOfficialPostgresMigrationPhaseEnforcesPgSearchPreAndPostconditions(t *testing.T) {
	db, mock := newPgSearchSQLMock(t)
	expectPgSearchMode(mock, "false")
	expectPgSearchState(mock, "0.22.2", true)
	expectPgSearchMode(mock, "false")
	expectPgSearchState(mock, pgSearchTargetVersion, true)
	expectPgSearchMode(mock, "false")
	expectPgSearchState(mock, pgSearchTargetVersion, true)
	runs := 0

	err := runOfficialPostgresMigrationPhase(context.Background(), db, func() error {
		runs++
		return nil
	})

	require.NoError(t, err)
	require.Equal(t, 1, runs)
	require.NoError(t, mock.ExpectationsWereMet())
}

func TestRunOfficialPostgresMigrationPhaseStopsOnPreflightOrMigrationFailure(t *testing.T) {
	t.Run("preflight failure", func(t *testing.T) {
		db, mock := newPgSearchSQLMock(t)
		expectPgSearchMode(mock, "false")
		expectPgSearchState(mock, "0.22.2", false)
		runs := 0

		err := runOfficialPostgresMigrationPhase(context.Background(), db, func() error {
			runs++
			return nil
		})

		require.ErrorContains(t, err, "is not available")
		require.Zero(t, runs)
		require.NoError(t, mock.ExpectationsWereMet())
	})

	t.Run("migration failure", func(t *testing.T) {
		db, mock := newPgSearchSQLMock(t)
		expectPgSearchMode(mock, "false")
		expectPgSearchState(mock, "0.22.2", true)
		migrationErr := errors.New("official migration failed")

		err := runOfficialPostgresMigrationPhase(context.Background(), db, func() error {
			return migrationErr
		})

		require.ErrorIs(t, err, migrationErr)
		require.NoError(t, mock.ExpectationsWereMet())
	})
}

func TestReconcilePgSearchAfterOfficialMigrationsRepairsSkippedMigration(t *testing.T) {
	for _, tt := range []struct {
		name      string
		installed interface{}
		repairSQL string
	}{
		{name: "missing extension", installed: nil, repairSQL: pgSearchInstallTargetSQL},
		{name: "old extension", installed: "0.22.2", repairSQL: pgSearchUpdateTargetSQL},
	} {
		t.Run(tt.name, func(t *testing.T) {
			db, mock := newPgSearchSQLMock(t)
			expectPgSearchMode(mock, "false")
			expectPgSearchState(mock, tt.installed, true)
			mock.ExpectExec(tt.repairSQL).WillReturnResult(sqlmock.NewResult(0, 0))

			require.NoError(t, reconcilePgSearchAfterOfficialMigrations(context.Background(), db))
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestReconcilePgSearchAfterOfficialMigrationsIsBoundedAndFailClosed(t *testing.T) {
	t.Run("already target is idempotent", func(t *testing.T) {
		db, mock := newPgSearchSQLMock(t)
		expectPgSearchMode(mock, "false")
		expectPgSearchState(mock, pgSearchTargetVersion, true)

		require.NoError(t, reconcilePgSearchAfterOfficialMigrations(context.Background(), db))
		require.NoError(t, mock.ExpectationsWereMet())
	})

	for _, tt := range []struct {
		name string
		mode interface{}
	}{
		{name: "external retriever does not mutate PostgreSQL extensions", mode: "true"},
		{name: "unset mode does not activate repair", mode: nil},
	} {
		t.Run(tt.name, func(t *testing.T) {
			db, mock := newPgSearchSQLMock(t)
			expectPgSearchMode(mock, tt.mode)

			require.NoError(t, reconcilePgSearchAfterOfficialMigrations(context.Background(), db))
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}

	for _, tt := range []struct {
		name            string
		installed       interface{}
		targetAvailable bool
		wantErr         string
	}{
		{name: "target package unavailable", installed: "0.22.2", wantErr: "is not available"},
		{name: "unsupported version", installed: "0.21.0", targetAvailable: true, wantErr: "unsupported installed pg_search version"},
	} {
		t.Run(tt.name, func(t *testing.T) {
			db, mock := newPgSearchSQLMock(t)
			expectPgSearchMode(mock, "false")
			expectPgSearchState(mock, tt.installed, tt.targetAvailable)

			err := reconcilePgSearchAfterOfficialMigrations(context.Background(), db)
			require.ErrorContains(t, err, tt.wantErr)
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestRunOfficialPostgresMigrationPhaseRepairsPgSearchAfterSkippedMigration(t *testing.T) {
	db, mock := newPgSearchSQLMock(t)
	expectPgSearchMode(mock, "false")
	expectPgSearchState(mock, "0.22.2", true)
	expectPgSearchMode(mock, "false")
	expectPgSearchState(mock, "0.22.2", true)
	mock.ExpectExec(pgSearchUpdateTargetSQL).WillReturnResult(sqlmock.NewResult(0, 0))
	expectPgSearchMode(mock, "false")
	expectPgSearchState(mock, pgSearchTargetVersion, true)
	runs := 0

	err := runOfficialPostgresMigrationPhase(context.Background(), db, func() error {
		runs++
		return nil
	})

	require.NoError(t, err)
	require.Equal(t, 1, runs)
	require.NoError(t, mock.ExpectationsWereMet())
}
