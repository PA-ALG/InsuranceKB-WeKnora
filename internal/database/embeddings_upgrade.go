package database

import (
	"context"
	"database/sql"
	"os"
)

const embeddingsForwardRepairMigrationPath = "migrations/enterprise/versioned/000003_embeddings_forward_repair.up.sql"

const embeddingsTableExistsSQL = "SELECT to_regclass('public.embeddings') IS NOT NULL"

func ensureEmbeddingsForwardRepair(ctx context.Context, db *sql.DB) error {
	active, err := postgresRetrievalRepairActive(ctx, db)
	if err != nil || !active {
		return err
	}

	var tableExists bool
	if err := db.QueryRowContext(ctx, embeddingsTableExistsSQL).Scan(&tableExists); err != nil {
		return newMigrationSafetyError("inspect existing PostgreSQL embeddings table", err)
	}
	if !tableExists {
		migrationSQL, err := os.ReadFile(embeddingsForwardRepairMigrationPath)
		if err != nil {
			return newMigrationSafetyError(
				"read packaged embeddings forward-repair migration",
				err,
			)
		}
		if _, err := db.ExecContext(ctx, string(migrationSQL)); err != nil {
			return newMigrationSafetyError("replay embeddings forward-repair migration", err)
		}
	}

	var contractValid bool
	if err := db.QueryRowContext(ctx, embeddingsForwardRepairContractSQL).Scan(&contractValid); err != nil {
		return newMigrationSafetyError("inspect existing PostgreSQL embeddings contract", err)
	}
	if !contractValid {
		return newMigrationSafetyError(
			"existing public.embeddings does not satisfy the current PostgreSQL repository contract",
			nil,
		)
	}
	return nil
}

func runEnterprisePostgresMigrationPhase(
	ctx context.Context,
	db *sql.DB,
	run func() error,
) error {
	if err := ensureEmbeddingsForwardRepair(ctx, db); err != nil {
		return err
	}
	return run()
}
