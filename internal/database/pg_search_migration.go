package database

import (
	"context"
	"database/sql"
	"fmt"
)

const pgSearchTargetVersion = "0.22.6"

const pgSearchMigrationModeSQL = "SELECT current_setting('app.skip_embedding', true)"

const pgSearchInstallTargetSQL = "CREATE EXTENSION IF NOT EXISTS pg_search WITH VERSION '0.22.6'"

const pgSearchUpdateTargetSQL = "ALTER EXTENSION pg_search UPDATE TO '0.22.6'"

const pgSearchUpgradeStateSQL = `
SELECT
    (SELECT extversion FROM pg_extension WHERE extname = 'pg_search'),
    EXISTS (
        SELECT 1
        FROM pg_available_extension_versions
        WHERE name = 'pg_search' AND version = '0.22.6'
    )`

type pgSearchUpgradeState struct {
	installedVersion sql.NullString
	targetAvailable  bool
}

func readSkipEmbeddingMigrationMode(ctx context.Context, db *sql.DB) (sql.NullString, error) {
	var skipEmbedding sql.NullString
	if err := db.QueryRowContext(ctx, pgSearchMigrationModeSQL).Scan(&skipEmbedding); err != nil {
		return sql.NullString{}, newMigrationSafetyError(
			"read PostgreSQL retrieval migration mode",
			err,
		)
	}
	return skipEmbedding, nil
}

func postgresRetrievalMigrationActive(ctx context.Context, db *sql.DB) (bool, error) {
	skipEmbedding, err := readSkipEmbeddingMigrationMode(ctx, db)
	if err != nil {
		return false, err
	}
	return !skipEmbedding.Valid || skipEmbedding.String != "true", nil
}

func postgresRetrievalRepairActive(ctx context.Context, db *sql.DB) (bool, error) {
	skipEmbedding, err := readSkipEmbeddingMigrationMode(ctx, db)
	if err != nil {
		return false, err
	}
	return skipEmbedding.Valid && skipEmbedding.String == "false", nil
}

func inspectPgSearchUpgradeState(
	ctx context.Context,
	db *sql.DB,
) (pgSearchUpgradeState, error) {
	var state pgSearchUpgradeState
	if err := db.QueryRowContext(ctx, pgSearchUpgradeStateSQL).Scan(
		&state.installedVersion,
		&state.targetAvailable,
	); err != nil {
		return pgSearchUpgradeState{}, newMigrationSafetyError(
			"inspect PostgreSQL pg_search upgrade state",
			err,
		)
	}
	return state, nil
}

func validatePgSearchUpgradePreflight(ctx context.Context, db *sql.DB) error {
	active, err := postgresRetrievalMigrationActive(ctx, db)
	if err != nil || !active {
		return err
	}
	state, err := inspectPgSearchUpgradeState(ctx, db)
	if err != nil {
		return err
	}

	if !state.installedVersion.Valid {
		if !state.targetAvailable {
			return newMigrationSafetyError(
				"pg_search 0.22.6 is not available for a fresh PostgreSQL retrieval schema",
				nil,
			)
		}
		return nil
	}

	switch state.installedVersion.String {
	case pgSearchTargetVersion:
		return nil
	case "0.22.2", "0.22.3", "0.22.4", "0.22.5":
		if !state.targetAvailable {
			return newMigrationSafetyError(
				"pg_search 0.22.6 is not available; update the PostgreSQL server image before migration",
				nil,
			)
		}
		return nil
	default:
		return newMigrationSafetyError(
			fmt.Sprintf(
				"unsupported installed pg_search version %q; expected 0.22.2-0.22.6",
				state.installedVersion.String,
			),
			nil,
		)
	}
}

func reconcilePgSearchAfterOfficialMigrations(ctx context.Context, db *sql.DB) error {
	active, err := postgresRetrievalRepairActive(ctx, db)
	if err != nil || !active {
		return err
	}
	state, err := inspectPgSearchUpgradeState(ctx, db)
	if err != nil {
		return err
	}
	if state.installedVersion.Valid && state.installedVersion.String == pgSearchTargetVersion {
		return nil
	}
	if !state.targetAvailable {
		return newMigrationSafetyError(
			"pg_search 0.22.6 is not available; update the PostgreSQL server image before repair",
			nil,
		)
	}

	repairSQL := pgSearchInstallTargetSQL
	if state.installedVersion.Valid {
		switch state.installedVersion.String {
		case "0.22.2", "0.22.3", "0.22.4", "0.22.5":
			repairSQL = pgSearchUpdateTargetSQL
		default:
			return newMigrationSafetyError(
				fmt.Sprintf(
					"unsupported installed pg_search version %q; expected 0.22.2-0.22.6",
					state.installedVersion.String,
				),
				nil,
			)
		}
	}
	if _, err := db.ExecContext(ctx, repairSQL); err != nil {
		return newMigrationSafetyError("repair PostgreSQL pg_search 0.22.6 state", err)
	}
	return nil
}

func validatePgSearchUpgradePostcondition(ctx context.Context, db *sql.DB) error {
	active, err := postgresRetrievalMigrationActive(ctx, db)
	if err != nil || !active {
		return err
	}
	state, err := inspectPgSearchUpgradeState(ctx, db)
	if err != nil {
		return err
	}
	if state.installedVersion.Valid && state.installedVersion.String == pgSearchTargetVersion {
		return nil
	}
	installed := "missing"
	if state.installedVersion.Valid {
		installed = state.installedVersion.String
	}
	return newMigrationSafetyError(
		fmt.Sprintf("expected pg_search 0.22.6 after official migrations, found %s", installed),
		nil,
	)
}

func runOfficialPostgresMigrationPhase(
	ctx context.Context,
	db *sql.DB,
	run func() error,
) error {
	if err := validatePgSearchUpgradePreflight(ctx, db); err != nil {
		return err
	}
	if err := run(); err != nil {
		return err
	}
	if err := reconcilePgSearchAfterOfficialMigrations(ctx, db); err != nil {
		return err
	}
	return validatePgSearchUpgradePostcondition(ctx, db)
}
