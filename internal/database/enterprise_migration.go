package database

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net/url"

	"github.com/Tencent/WeKnora/deploy/upstream"
	"github.com/Tencent/WeKnora/internal/logger"
	"github.com/golang-migrate/migrate/v4"
)

const (
	officialPostgresMigrationSource   = "file://migrations/versioned"
	enterprisePostgresMigrationSource = "file://migrations/enterprise/versioned"
	enterpriseMigrationLedgerTable    = "enterprise_schema_migrations"
	packagedEnterpriseMigrationHead   = uint(3)

	embeddingsForwardRepairContractSQL = `
WITH required_columns(name, data_type, not_null) AS (
    VALUES
        ('id', 'integer', true),
        ('created_at', 'timestamp with time zone', false),
        ('updated_at', 'timestamp with time zone', false),
        ('source_id', 'character varying(64)', true),
        ('source_type', 'integer', true),
        ('chunk_id', 'character varying(64)', false),
        ('knowledge_id', 'character varying(64)', false),
        ('knowledge_base_id', 'character varying(64)', false),
        ('content', 'text', false),
        ('dimension', 'integer', true),
        ('embedding', 'halfvec', false),
        ('is_enabled', 'boolean', false),
        ('tag_id', 'character varying(36)', false)
), actual_columns AS (
    SELECT
        attribute.attname AS name,
        format_type(attribute.atttypid, attribute.atttypmod) AS data_type,
        attribute.attnotnull AS not_null
    FROM pg_attribute AS attribute
    WHERE attribute.attrelid = 'public.embeddings'::regclass
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
), required_indexes(name, access_method, must_be_unique, must_be_primary) AS (
    VALUES
        ('embeddings_pkey', 'btree', true, true),
        ('embeddings_unique_source', 'btree', true, false),
        ('embeddings_search_idx', 'bm25', false, false),
        ('embeddings_embedding_idx_3584', 'hnsw', false, false),
        ('embeddings_embedding_idx_798', 'hnsw', false, false),
        ('embeddings_embedding_idx_1024', 'hnsw', false, false),
        ('idx_embeddings_is_enabled', 'btree', false, false),
        ('idx_embeddings_knowledge_base_id', 'btree', false, false),
        ('idx_embeddings_tag_id', 'btree', false, false)
), actual_indexes AS (
    SELECT
        index_class.relname AS name,
        access_method.amname AS access_method,
        index_row.indisunique AS is_unique,
        index_row.indisprimary AS is_primary
    FROM pg_index AS index_row
    JOIN pg_class AS index_class ON index_class.oid = index_row.indexrelid
    JOIN pg_namespace AS namespace ON namespace.oid = index_class.relnamespace
    JOIN pg_am AS access_method ON access_method.oid = index_class.relam
    WHERE index_row.indrelid = 'public.embeddings'::regclass
      AND namespace.nspname = 'public'
)
SELECT
    NOT EXISTS (
        SELECT 1
        FROM required_columns AS required
        LEFT JOIN actual_columns AS actual USING (name)
        WHERE actual.name IS NULL
           OR actual.data_type <> required.data_type
           OR actual.not_null <> required.not_null
    )
    AND NOT EXISTS (
        SELECT 1
        FROM required_indexes AS required
        LEFT JOIN actual_indexes AS actual USING (name)
        WHERE actual.name IS NULL
           OR actual.access_method <> required.access_method
           OR actual.is_unique <> required.must_be_unique
           OR actual.is_primary <> required.must_be_primary
    )`
)

type postgresMigrationPhaseGuard interface {
	Release(context.Context) error
}

func runPostgresMigrationPhases(
	ctx context.Context,
	acquire func() (postgresMigrationPhaseGuard, error),
	official func() error,
	enterprise func() error,
) (err error) {
	guard, err := acquire()
	if err != nil {
		return ensureMigrationSafetyError("acquire PostgreSQL migration guard", err)
	}
	if guard == nil {
		return newMigrationSafetyError("migration guard acquisition returned nil", nil)
	}
	defer func() {
		releaseErr := guard.Release(ctx)
		if releaseErr != nil {
			releaseErr = ensureMigrationSafetyError(
				"release PostgreSQL migration guard",
				releaseErr,
			)
		}
		err = errors.Join(err, releaseErr)
	}()

	if err := official(); err != nil {
		return ensureMigrationSafetyError("run official PostgreSQL migrations", err)
	}
	if err := enterprise(); err != nil {
		return ensureMigrationSafetyError("run enterprise PostgreSQL migrations", err)
	}
	return nil
}

func enterpriseMigrationDSN(dsn string) (string, error) {
	parsed, err := url.Parse(dsn)
	if err != nil {
		return "", fmt.Errorf("parse PostgreSQL migration DSN: %w", err)
	}
	query := parsed.Query()
	query.Set("x-migrations-table", enterpriseMigrationLedgerTable)
	parsed.RawQuery = query.Encode()
	return parsed.String(), nil
}

func runPostgresMigrations(ctx context.Context, dsn string, _ MigrationOptions) (err error) {
	rawDB, err := sql.Open("postgres", dsn)
	if err != nil {
		return newMigrationSafetyError("open PostgreSQL migration preflight connection", err)
	}
	defer func() {
		closeErr := rawDB.Close()
		if closeErr != nil {
			closeErr = ensureMigrationSafetyError(
				"close PostgreSQL migration preflight pool",
				closeErr,
			)
		}
		err = errors.Join(err, closeErr)
	}()

	enterpriseDSN, err := enterpriseMigrationDSN(dsn)
	if err != nil {
		return newMigrationSafetyError("prepare enterprise migration ledger DSN", err)
	}

	return runPostgresMigrationPhases(
		ctx,
		func() (postgresMigrationPhaseGuard, error) {
			return acquireLegacyW1MigrationGuard(ctx, rawDB, inspectLegacyW1BridgeState)
		},
		func() error {
			return runPostgresMigrationSet(
				ctx,
				officialPostgresMigrationSource,
				dsn,
				true,
			)
		},
		func() error {
			if err := validateEmbeddingsForwardRepairPreflight(ctx, rawDB); err != nil {
				return err
			}
			return runPostgresMigrationSet(
				ctx,
				enterprisePostgresMigrationSource,
				enterpriseDSN,
				false,
			)
		},
	)
}

func validateEmbeddingsForwardRepairPreflight(
	ctx context.Context,
	db *sql.DB,
) error {
	var skipEmbedding sql.NullString
	if err := db.QueryRowContext(
		ctx,
		"SELECT current_setting('app.skip_embedding', true)",
	).Scan(&skipEmbedding); err != nil {
		return newMigrationSafetyError(
			"read PostgreSQL embeddings migration mode",
			err,
		)
	}
	if !skipEmbedding.Valid || skipEmbedding.String != "false" {
		return nil
	}

	var tableExists bool
	if err := db.QueryRowContext(
		ctx,
		"SELECT to_regclass('public.embeddings') IS NOT NULL",
	).Scan(&tableExists); err != nil {
		return newMigrationSafetyError(
			"inspect existing PostgreSQL embeddings table",
			err,
		)
	}
	if !tableExists {
		return nil
	}

	var contractValid bool
	if err := db.QueryRowContext(
		ctx,
		embeddingsForwardRepairContractSQL,
	).Scan(&contractValid); err != nil {
		return newMigrationSafetyError(
			"inspect existing PostgreSQL embeddings contract",
			err,
		)
	}
	if !contractValid {
		return newMigrationSafetyError(
			"existing public.embeddings does not satisfy the current PostgreSQL repository contract",
			nil,
		)
	}
	return nil
}

func runPostgresMigrationSet(
	ctx context.Context,
	sourceURL string,
	dsn string,
	cacheOfficial bool,
) (err error) {
	migrator, err := migrate.New(sourceURL, dsn)
	if err != nil {
		wrapped := newMigrationSafetyError(
			fmt.Sprintf("create PostgreSQL migrator for %s", sourceURL),
			err,
		)
		if cacheOfficial {
			setMigrationState(0, false, wrapped.Error(), false)
		}
		return wrapped
	}
	defer func() {
		sourceErr, databaseErr := migrator.Close()
		closeErr := errors.Join(sourceErr, databaseErr)
		if closeErr != nil {
			closeErr = newMigrationSafetyError(
				fmt.Sprintf("close PostgreSQL migrator for %s", sourceURL),
				closeErr,
			)
		}
		err = errors.Join(err, closeErr)
	}()

	oldVersion, oldDirty, versionErr := migrator.Version()
	oldVersionKnown := versionErr == nil
	if versionErr != nil && versionErr != migrate.ErrNilVersion {
		return recordPostgresMigrationSetFailure(
			migrator,
			cacheOfficial,
			newMigrationSafetyError(
				fmt.Sprintf("read PostgreSQL migration version for %s", sourceURL),
				versionErr,
			),
		)
	}
	if oldDirty {
		return recordPostgresMigrationSetFailure(
			migrator,
			cacheOfficial,
			newMigrationSafetyError(
				fmt.Sprintf(
					"%s migration ledger is dirty at version %d; automatic force recovery is disabled",
					sourceURL,
					oldVersion,
				),
				nil,
			),
		)
	}

	if err := migrator.Up(); err != nil && err != migrate.ErrNoChange {
		currentVersion, currentDirty, currentErr := migrator.Version()
		if currentErr == nil && currentDirty {
			return recordPostgresMigrationSetFailure(
				migrator,
				cacheOfficial,
				newMigrationSafetyError(
					fmt.Sprintf(
						"%s migration failed dirty at version %d; automatic force recovery is disabled",
						sourceURL,
						currentVersion,
					),
					err,
				),
			)
		}
		return recordPostgresMigrationSetFailure(
			migrator,
			cacheOfficial,
			newMigrationSafetyError(
				fmt.Sprintf("run PostgreSQL migrations for %s", sourceURL),
				err,
			),
		)
	}

	version, dirty, err := migrator.Version()
	if err != nil {
		return recordPostgresMigrationSetFailure(
			migrator,
			cacheOfficial,
			newMigrationSafetyError(
				fmt.Sprintf("read final PostgreSQL migration version for %s", sourceURL),
				err,
			),
		)
	}
	if dirty {
		return recordPostgresMigrationSetFailure(
			migrator,
			cacheOfficial,
			newMigrationSafetyError(
				fmt.Sprintf(
					"%s migration ledger is dirty at version %d",
					sourceURL,
					version,
				),
				nil,
			),
		)
	}
	if err := validatePostgresMigrationSetVersion(sourceURL, cacheOfficial, version); err != nil {
		return recordPostgresMigrationSetFailure(migrator, cacheOfficial, err)
	}

	if cacheOfficial {
		setMigrationState(version, false, "", true)
		if oldVersionKnown && oldVersion != version {
			logger.Infof(ctx, "Database migrated from version %d to %d", oldVersion, version)
		} else {
			logger.Infof(ctx, "Database is up to date (version: %d)", version)
		}
	}
	return nil
}

func validatePostgresMigrationSetVersion(
	sourceURL string,
	cacheOfficial bool,
	version uint,
) error {
	expected := packagedEnterpriseMigrationHead
	if cacheOfficial {
		expected = uint(upstream.OfficialMigrationHead())
	}
	if version == expected {
		return nil
	}
	return newMigrationSafetyError(
		fmt.Sprintf(
			"%s migration finished at version %d, expected frozen head %d",
			sourceURL,
			version,
			expected,
		),
		nil,
	)
}

func ensureMigrationSafetyError(reason string, err error) error {
	if err == nil {
		return nil
	}
	var safetyErr *MigrationSafetyError
	if errors.As(err, &safetyErr) {
		return err
	}
	return newMigrationSafetyError(reason, err)
}

func recordPostgresMigrationSetFailure(
	migrator *migrate.Migrate,
	cacheOfficial bool,
	err error,
) error {
	if !cacheOfficial {
		return err
	}
	return captureMigrationFailure(migrator, err)
}
