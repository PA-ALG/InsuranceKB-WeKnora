package database

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/stretchr/testify/require"
)

func TestEnsureEmbeddingsForwardRepairReplaysExistingMigrationAfterModeTransition(t *testing.T) {
	root := sqliteRepoRoot(t)
	migrationSQL, err := os.ReadFile(filepath.Join(root, embeddingsForwardRepairMigrationPath))
	require.NoError(t, err)
	t.Chdir(root)
	db, mock := newPgSearchSQLMock(t)
	expectPgSearchMode(mock, "false")
	mock.ExpectQuery(embeddingsTableExistsSQL).
		WillReturnRows(sqlmock.NewRows([]string{"exists"}).AddRow(false))
	mock.ExpectExec(string(migrationSQL)).WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectQuery(embeddingsForwardRepairContractSQL).
		WillReturnRows(sqlmock.NewRows([]string{"valid"}).AddRow(true))

	require.NoError(t, ensureEmbeddingsForwardRepair(context.Background(), db))
	require.NoError(t, mock.ExpectationsWereMet())
}

func TestEnsureEmbeddingsForwardRepairPreservesValidSchemaAndRejectsPartial(t *testing.T) {
	for _, tt := range []struct {
		name          string
		contractValid bool
		wantErr       string
	}{
		{name: "valid existing schema", contractValid: true},
		{name: "partial existing schema", wantErr: "does not satisfy", contractValid: false},
	} {
		t.Run(tt.name, func(t *testing.T) {
			db, mock := newPgSearchSQLMock(t)
			expectPgSearchMode(mock, "false")
			mock.ExpectQuery(embeddingsTableExistsSQL).
				WillReturnRows(sqlmock.NewRows([]string{"exists"}).AddRow(true))
			mock.ExpectQuery(embeddingsForwardRepairContractSQL).
				WillReturnRows(sqlmock.NewRows([]string{"valid"}).AddRow(tt.contractValid))

			err := ensureEmbeddingsForwardRepair(context.Background(), db)
			if tt.wantErr != "" {
				require.ErrorContains(t, err, tt.wantErr)
			} else {
				require.NoError(t, err)
			}
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestEnsureEmbeddingsForwardRepairSkipsExternalRetriever(t *testing.T) {
	for _, tt := range []struct {
		name string
		mode interface{}
	}{
		{name: "external retriever", mode: "true"},
		{name: "unset mode", mode: nil},
	} {
		t.Run(tt.name, func(t *testing.T) {
			db, mock := newPgSearchSQLMock(t)
			expectPgSearchMode(mock, tt.mode)

			require.NoError(t, ensureEmbeddingsForwardRepair(context.Background(), db))
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestEnsureEmbeddingsForwardRepairFailsClosedWhenPackagedMigrationIsUnreadable(t *testing.T) {
	t.Chdir(t.TempDir())
	db, mock := newPgSearchSQLMock(t)
	expectPgSearchMode(mock, "false")
	mock.ExpectQuery(embeddingsTableExistsSQL).
		WillReturnRows(sqlmock.NewRows([]string{"exists"}).AddRow(false))

	err := ensureEmbeddingsForwardRepair(context.Background(), db)
	require.ErrorContains(t, err, "read packaged embeddings forward-repair migration")
	require.NoError(t, mock.ExpectationsWereMet())
}

func TestRunEnterprisePostgresMigrationPhaseRepairsBeforeLedgerAdvance(t *testing.T) {
	root := sqliteRepoRoot(t)
	migrationSQL, err := os.ReadFile(filepath.Join(root, embeddingsForwardRepairMigrationPath))
	require.NoError(t, err)
	t.Chdir(root)
	db, mock := newPgSearchSQLMock(t)
	expectPgSearchMode(mock, "false")
	mock.ExpectQuery(embeddingsTableExistsSQL).
		WillReturnRows(sqlmock.NewRows([]string{"exists"}).AddRow(false))
	mock.ExpectExec(string(migrationSQL)).WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectQuery(embeddingsForwardRepairContractSQL).
		WillReturnRows(sqlmock.NewRows([]string{"valid"}).AddRow(true))
	runs := 0

	err = runEnterprisePostgresMigrationPhase(context.Background(), db, func() error {
		runs++
		return nil
	})

	require.NoError(t, err)
	require.Equal(t, 1, runs)
	require.NoError(t, mock.ExpectationsWereMet())
}

func TestRunEnterprisePostgresMigrationPhaseStopsBeforeLedgerAdvanceOnRepairFailure(t *testing.T) {
	db, mock := newPgSearchSQLMock(t)
	expectPgSearchMode(mock, "false")
	mock.ExpectQuery(embeddingsTableExistsSQL).
		WillReturnRows(sqlmock.NewRows([]string{"exists"}).AddRow(true))
	mock.ExpectQuery(embeddingsForwardRepairContractSQL).
		WillReturnRows(sqlmock.NewRows([]string{"valid"}).AddRow(false))
	runs := 0

	err := runEnterprisePostgresMigrationPhase(context.Background(), db, func() error {
		runs++
		return nil
	})

	require.ErrorContains(t, err, "does not satisfy")
	require.Zero(t, runs)
	require.NoError(t, mock.ExpectationsWereMet())
}

func TestPgSearchActivationAfterSkipEmbeddingUpgradeRunsInsideMigrationGuard(t *testing.T) {
	root := sqliteRepoRoot(t)
	migrationSQL, err := os.ReadFile(filepath.Join(root, embeddingsForwardRepairMigrationPath))
	require.NoError(t, err)
	t.Chdir(root)
	db, mock := newPgSearchSQLMock(t)

	expectPgSearchMode(mock, "false")
	expectPgSearchState(mock, nil, true)
	expectPgSearchMode(mock, "false")
	expectPgSearchState(mock, nil, true)
	mock.ExpectExec(pgSearchInstallTargetSQL).WillReturnResult(sqlmock.NewResult(0, 0))
	expectPgSearchMode(mock, "false")
	expectPgSearchState(mock, pgSearchTargetVersion, true)
	expectPgSearchMode(mock, "false")
	mock.ExpectQuery(embeddingsTableExistsSQL).
		WillReturnRows(sqlmock.NewRows([]string{"exists"}).AddRow(false))
	mock.ExpectExec(string(migrationSQL)).WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectQuery(embeddingsForwardRepairContractSQL).
		WillReturnRows(sqlmock.NewRows([]string{"valid"}).AddRow(true))

	var events []string
	err = runPostgresMigrationPhases(
		context.Background(),
		func() (postgresMigrationPhaseGuard, error) {
			events = append(events, "acquire")
			return &recordingMigrationPhaseGuard{events: &events}, nil
		},
		func() error {
			return runOfficialPostgresMigrationPhase(context.Background(), db, func() error {
				events = append(events, "official")
				return nil
			})
		},
		func() error {
			return runEnterprisePostgresMigrationPhase(context.Background(), db, func() error {
				events = append(events, "enterprise")
				return nil
			})
		},
	)

	require.NoError(t, err)
	require.Equal(t, []string{"acquire", "official", "enterprise", "release"}, events)
	require.NoError(t, mock.ExpectationsWereMet())
}
