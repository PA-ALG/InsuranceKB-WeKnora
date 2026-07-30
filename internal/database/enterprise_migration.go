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
	packagedEnterpriseMigrationHead   = uint(2)
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
			return runPostgresMigrationSet(
				ctx,
				enterprisePostgresMigrationSource,
				enterpriseDSN,
				false,
			)
		},
	)
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
