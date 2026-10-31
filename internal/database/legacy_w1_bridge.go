package database

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"database/sql/driver"
	_ "embed"
	"errors"
	"fmt"
	"time"
)

const legacyW1BridgeAdvisoryLockKey int64 = 0x574B4E4F00000066

const (
	legacyW1UpSHA256   = "7fd004f131840b938e599d6ac65f20024dcbc7e6b2d7c274e456e32290a8817f"
	legacyW1DownSHA256 = "19f60a922f682deb818897a05b84e7fe70d9cedf82eba942dc40b1c9ec60dc58"
)

//go:embed testdata/000066_knowledge_revision_manifest.up.sql
var legacyW1UpFixture []byte

//go:embed testdata/000066_knowledge_revision_manifest.down.sql
var legacyW1DownFixture []byte

type legacyW1StateQueryer interface {
	QueryRowContext(ctx context.Context, query string, args ...interface{}) *sql.Row
}

type legacyW1StateInspector func(
	ctx context.Context,
	queryer legacyW1StateQueryer,
) (legacyW1BridgeState, error)

//go:embed catalogsql/span_name_fingerprint.sql
var spanNameFingerprintSQL string

// dependencyAnchorFingerprintSQL pins only the base objects on which the
// legacy W1 objects depend. It intentionally does not inventory either table.
//
//go:embed catalogsql/dependency_anchor_fingerprint.sql
var dependencyAnchorFingerprintSQL string

// legacyW1FingerprintSQL is deliberately a fixed compatibility fingerprint,
// not a reusable schema inventory. Each VALUES row represents one legacy W1
// object: the three added columns, the eight-column table, and the two indexes.
//
//go:embed catalogsql/legacy_w1_fingerprint.sql
var legacyW1FingerprintSQL string

func inspectSpanNameFingerprint(
	ctx context.Context,
	queryer legacyW1StateQueryer,
) (spanNameFingerprint, error) {
	var tableExists, tableOrdinary, columnExists, notNull, noDefault bool
	var dataType string
	var length int64
	if err := queryer.QueryRowContext(ctx, spanNameFingerprintSQL).Scan(
		&tableExists,
		&tableOrdinary,
		&columnExists,
		&dataType,
		&length,
		&notNull,
		&noDefault,
	); err != nil {
		return spanNameUnknown, fmt.Errorf("inspect knowledge span name column: %w", err)
	}
	if !tableExists && !columnExists {
		return spanNameAbsent, nil
	}
	if !tableExists ||
		!tableOrdinary ||
		!columnExists ||
		dataType != "character varying" ||
		!notNull ||
		!noDefault {
		return spanNameUnknown, nil
	}
	switch length {
	case 64:
		return spanNameLegacy64, nil
	case 255:
		return spanNameExpanded255, nil
	default:
		return spanNameUnknown, nil
	}
}

func inspectLegacyW1Fingerprint(
	ctx context.Context,
	queryer legacyW1StateQueryer,
) (legacyW1Fingerprint, error) {
	var presentCount, exactCount int64
	if err := queryer.QueryRowContext(ctx, legacyW1FingerprintSQL).Scan(
		&presentCount,
		&exactCount,
	); err != nil {
		return legacyW1Partial, fmt.Errorf("inspect legacy W1 object fingerprint: %w", err)
	}
	switch {
	case presentCount == 0:
		return legacyW1Absent, nil
	case presentCount == 6 && exactCount == 6:
		return legacyW1Exact, nil
	default:
		return legacyW1Partial, nil
	}
}

func inspectDependencyAnchorFingerprint(
	ctx context.Context,
	queryer legacyW1StateQueryer,
) (dependencyAnchorFingerprint, error) {
	var presentCount, exactCount int64
	if err := queryer.QueryRowContext(ctx, dependencyAnchorFingerprintSQL).Scan(
		&presentCount,
		&exactCount,
	); err != nil {
		return dependencyAnchorsPartial, fmt.Errorf(
			"inspect legacy W1 dependency anchors: %w",
			err,
		)
	}
	switch {
	case presentCount == 0:
		return dependencyAnchorsAbsent, nil
	case presentCount == 2 && exactCount == 2:
		return dependencyAnchorsExact, nil
	default:
		return dependencyAnchorsPartial, nil
	}
}

func inspectLegacyW1BridgeState(
	ctx context.Context,
	queryer legacyW1StateQueryer,
) (legacyW1BridgeState, error) {
	state := legacyW1BridgeState{fixtureChecksumValid: legacyW1FixtureChecksumsValid()}

	var err error
	state.officialLedgerExists, state.officialVersion, state.officialDirty, err =
		inspectOfficialMigrationLedger(ctx, queryer)
	if err != nil {
		return legacyW1BridgeState{}, err
	}
	state.enterpriseLedgerExists, state.enterpriseVersion, state.enterpriseDirty, err =
		inspectEnterpriseMigrationLedger(ctx, queryer)
	if err != nil {
		return legacyW1BridgeState{}, err
	}
	state.dependencyState, err = inspectDependencyAnchorFingerprint(ctx, queryer)
	if err != nil {
		return legacyW1BridgeState{}, err
	}
	state.spanState, err = inspectSpanNameFingerprint(ctx, queryer)
	if err != nil {
		return legacyW1BridgeState{}, err
	}
	state.w1State, err = inspectLegacyW1Fingerprint(ctx, queryer)
	if err != nil {
		return legacyW1BridgeState{}, err
	}
	return state, nil
}

type legacyW1MigrationGuard struct {
	conn   *sql.Conn
	origin legacyW1Origin
}

var discardLegacyW1Connection = func(conn *sql.Conn) error {
	return conn.Raw(func(any) error {
		return driver.ErrBadConn
	})
}

func (g *legacyW1MigrationGuard) Release(_ context.Context) error {
	if g == nil || g.conn == nil {
		return nil
	}
	cleanupCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	var unlocked bool
	unlockErr := g.conn.QueryRowContext(
		cleanupCtx,
		"SELECT pg_advisory_unlock($1)",
		legacyW1BridgeAdvisoryLockKey,
	).Scan(&unlocked)
	var discardErr error
	if unlockErr != nil {
		discardErr = discardLegacyW1Connection(g.conn)
	}
	closeErr := g.conn.Close()
	g.conn = nil

	switch {
	case unlockErr != nil:
		return newMigrationSafetyError(
			"release legacy W1 migration advisory lock",
			errors.Join(unlockErr, discardErr, closeErr),
		)
	case !unlocked:
		return newMigrationSafetyError(
			"legacy W1 migration advisory lock was not held by its reserved connection",
			closeErr,
		)
	case closeErr != nil:
		return newMigrationSafetyError(
			"close legacy W1 migration advisory-lock connection",
			closeErr,
		)
	default:
		return nil
	}
}

func legacyW1FixtureChecksumsValid() bool {
	up := fmt.Sprintf("%x", sha256.Sum256(legacyW1UpFixture))
	down := fmt.Sprintf("%x", sha256.Sum256(legacyW1DownFixture))
	return up == legacyW1UpSHA256 && down == legacyW1DownSHA256
}

func acquireLegacyW1MigrationGuard(
	ctx context.Context,
	db *sql.DB,
	inspect legacyW1StateInspector,
) (*legacyW1MigrationGuard, error) {
	before, err := inspect(ctx, db)
	if err != nil {
		return nil, newMigrationSafetyError("inspect legacy W1 migration origin", err)
	}
	origin, err := classifyLegacyW1Origin(before)
	if err != nil {
		return nil, newMigrationSafetyError(err.Error(), err)
	}

	conn, err := db.Conn(ctx)
	if err != nil {
		return nil, newMigrationSafetyError("reserve migration bridge connection", err)
	}
	guard := &legacyW1MigrationGuard{conn: conn, origin: origin}
	cleanup := func(cause error) (*legacyW1MigrationGuard, error) {
		return nil, errors.Join(cause, guard.Release(ctx))
	}
	rollbackAndCleanup := func(tx *sql.Tx, cause error) (*legacyW1MigrationGuard, error) {
		if rollbackErr := tx.Rollback(); rollbackErr != nil {
			cause = errors.Join(
				cause,
				newMigrationSafetyError("roll back legacy W1 migration bridge", rollbackErr),
			)
		}
		return cleanup(cause)
	}

	if _, err := conn.ExecContext(
		ctx,
		"SELECT pg_advisory_lock($1)",
		legacyW1BridgeAdvisoryLockKey,
	); err != nil {
		discardErr := discardLegacyW1Connection(conn)
		closeErr := conn.Close()
		guard.conn = nil
		return nil, newMigrationSafetyError(
			"acquire legacy W1 migration advisory lock",
			errors.Join(err, discardErr, closeErr),
		)
	}

	tx, err := conn.BeginTx(ctx, &sql.TxOptions{})
	if err != nil {
		return cleanup(newMigrationSafetyError(
			"begin locked legacy W1 migration inspection",
			err,
		))
	}
	locked, err := inspect(ctx, tx)
	if err != nil {
		return rollbackAndCleanup(tx, newMigrationSafetyError(
			"reinspect locked legacy W1 migration origin",
			err,
		))
	}
	if locked != before {
		return rollbackAndCleanup(tx, &MigrationSafetyError{
			Reason: "migration origin changed after advisory lock",
		})
	}
	lockedOrigin, err := classifyLegacyW1Origin(locked)
	if err != nil {
		return rollbackAndCleanup(tx, newMigrationSafetyError(err.Error(), err))
	}

	if lockedOrigin != legacyW1OriginExactLegacy66 {
		if err := tx.Rollback(); err != nil {
			return cleanup(newMigrationSafetyError(
				"close locked migration inspection",
				err,
			))
		}
		return guard, nil
	}

	if _, err := tx.ExecContext(
		ctx,
		"ALTER TABLE knowledge_processing_spans ALTER COLUMN name TYPE VARCHAR(255)",
	); err != nil {
		return rollbackAndCleanup(tx, newMigrationSafetyError(
			"apply official 000066 span expansion",
			err,
		))
	}
	if _, err := tx.ExecContext(
		ctx,
		"CREATE TABLE enterprise_schema_migrations (version BIGINT NOT NULL PRIMARY KEY, dirty BOOLEAN NOT NULL)",
	); err != nil {
		return rollbackAndCleanup(tx, newMigrationSafetyError(
			"create enterprise migration ledger",
			err,
		))
	}
	if _, err := tx.ExecContext(
		ctx,
		"INSERT INTO enterprise_schema_migrations (version, dirty) VALUES ($1, $2)",
		1,
		false,
	); err != nil {
		return rollbackAndCleanup(tx, newMigrationSafetyError(
			"record legacy W1 enterprise baseline",
			err,
		))
	}
	if err := tx.Commit(); err != nil {
		return cleanup(newMigrationSafetyError(
			"commit legacy W1 migration bridge",
			err,
		))
	}
	return guard, nil
}
