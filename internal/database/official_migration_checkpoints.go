package database

import (
	"context"
	"fmt"

	"github.com/Tencent/WeKnora/deploy/upstream"
)

// releasedOfficial75Checkpoint is the official migration head shipped with
// the product immediately before the fixed WeKnora v0.8.2 adoption target.
// Every clean ledger version from this checkpoint through the packaged head is
// a resumable point in the same immutable golang-migrate chain.
const releasedOfficial75Checkpoint int64 = 75

func enterpriseVersionKnownAtOfficialCheckpoint(
	officialVersion int64,
	enterpriseVersion int64,
) bool {
	if enterpriseVersion == 1 {
		return true
	}
	if enterpriseVersion <= 1 || enterpriseVersion > int64(packagedEnterpriseMigrationHead) {
		return false
	}
	return officialVersion >= releasedOfficial75Checkpoint &&
		officialVersion <= upstream.OfficialMigrationHead()
}

const officialMigrationLedgerShapeSQL = `
SELECT
    to_regclass('public.schema_migrations') IS NOT NULL,
    COALESCE((
        SELECT relkind = 'r'
        FROM pg_catalog.pg_class
        WHERE oid = to_regclass('public.schema_migrations')
    ), false)
    AND COALESCE((
        SELECT
            count(*) = 2
            AND count(*) FILTER (
                WHERE a.attname = 'version'
                  AND pg_catalog.format_type(a.atttypid, a.atttypmod) = 'bigint'
                  AND a.attnotnull
            ) = 1
            AND count(*) FILTER (
                WHERE a.attname = 'dirty'
                  AND pg_catalog.format_type(a.atttypid, a.atttypmod) = 'boolean'
                  AND a.attnotnull
            ) = 1
            AND (
                SELECT count(*) = 1
                   AND count(*) FILTER (WHERE c.contype = 'p' AND c.convalidated AND NOT c.condeferrable) = 1
                   AND bool_and(c.conkey = ARRAY[version_column.attnum]::smallint[])
                FROM pg_catalog.pg_constraint c
                JOIN pg_catalog.pg_attribute version_column
                  ON version_column.attrelid = c.conrelid
                 AND version_column.attname = 'version'
                WHERE c.conrelid = to_regclass('public.schema_migrations')
            )
        FROM pg_catalog.pg_attribute a
        WHERE a.attrelid = to_regclass('public.schema_migrations')
          AND a.attnum > 0
          AND NOT a.attisdropped
    ), false)`

const officialMigrationLedgerStateSQL = `
SELECT count(*), COALESCE(max(version), 0), COALESCE(bool_or(dirty), false)
FROM public.schema_migrations`

const enterpriseMigrationLedgerShapeSQL = `
SELECT
    to_regclass('public.enterprise_schema_migrations') IS NOT NULL,
    COALESCE((
        SELECT relkind = 'r'
        FROM pg_catalog.pg_class
        WHERE oid = to_regclass('public.enterprise_schema_migrations')
    ), false)
    AND COALESCE((
        SELECT
            count(*) = 2
            AND count(*) FILTER (
                WHERE a.attname = 'version'
                  AND pg_catalog.format_type(a.atttypid, a.atttypmod) = 'bigint'
                  AND a.attnotnull
            ) = 1
            AND count(*) FILTER (
                WHERE a.attname = 'dirty'
                  AND pg_catalog.format_type(a.atttypid, a.atttypmod) = 'boolean'
                  AND a.attnotnull
            ) = 1
            AND (
                SELECT count(*) = 1
                   AND count(*) FILTER (WHERE c.contype = 'p' AND c.convalidated AND NOT c.condeferrable) = 1
                   AND bool_and(c.conkey = ARRAY[version_column.attnum]::smallint[])
                FROM pg_catalog.pg_constraint c
                JOIN pg_catalog.pg_attribute version_column
                  ON version_column.attrelid = c.conrelid
                 AND version_column.attname = 'version'
                WHERE c.conrelid = to_regclass('public.enterprise_schema_migrations')
            )
        FROM pg_catalog.pg_attribute a
        WHERE a.attrelid = to_regclass('public.enterprise_schema_migrations')
          AND a.attnum > 0
          AND NOT a.attisdropped
    ), false)`

const enterpriseMigrationLedgerStateSQL = `
SELECT count(*), COALESCE(max(version), 0), COALESCE(bool_or(dirty), false)
FROM public.enterprise_schema_migrations`

func inspectMigrationLedger(
	ctx context.Context,
	queryer legacyW1StateQueryer,
	shapeSQL string,
	stateSQL string,
	name string,
) (bool, int64, bool, error) {
	var exists, exact bool
	if err := queryer.QueryRowContext(ctx, shapeSQL).Scan(&exists, &exact); err != nil {
		return false, 0, false, fmt.Errorf("inspect %s migration ledger structure: %w", name, err)
	}
	if !exists {
		return false, 0, false, nil
	}
	if !exact {
		return false, 0, false, fmt.Errorf("%s migration ledger has unexpected structure", name)
	}

	var rowCount, version int64
	var dirty bool
	if err := queryer.QueryRowContext(ctx, stateSQL).Scan(&rowCount, &version, &dirty); err != nil {
		return false, 0, false, fmt.Errorf("read %s migration ledger: %w", name, err)
	}
	if rowCount == 0 {
		return true, -1, false, nil
	}
	if rowCount != 1 {
		return false, 0, false, fmt.Errorf(
			"%s migration ledger must contain exactly one row, found %d",
			name,
			rowCount,
		)
	}
	return true, version, dirty, nil
}

func inspectOfficialMigrationLedger(
	ctx context.Context,
	queryer legacyW1StateQueryer,
) (bool, int64, bool, error) {
	return inspectMigrationLedger(
		ctx,
		queryer,
		officialMigrationLedgerShapeSQL,
		officialMigrationLedgerStateSQL,
		"official",
	)
}

func inspectEnterpriseMigrationLedger(
	ctx context.Context,
	queryer legacyW1StateQueryer,
) (bool, int64, bool, error) {
	return inspectMigrationLedger(
		ctx,
		queryer,
		enterpriseMigrationLedgerShapeSQL,
		enterpriseMigrationLedgerStateSQL,
		"enterprise",
	)
}

type legacyW1Origin string

const (
	legacyW1OriginFresh          legacyW1Origin = "fresh"
	legacyW1OriginPre66          legacyW1Origin = "pre66"
	legacyW1OriginUpstream66Plus legacyW1Origin = "upstream66_plus"
	legacyW1OriginExactLegacy66  legacyW1Origin = "exact_legacy66"
	legacyW1OriginKnownBridged   legacyW1Origin = "known_bridged"
	legacyW1OriginFullCurrent    legacyW1Origin = "full_current"
)

type legacyW1Fingerprint uint8

const (
	legacyW1Absent legacyW1Fingerprint = iota
	legacyW1Exact
	legacyW1Partial
)

type spanNameFingerprint uint8

const (
	spanNameAbsent spanNameFingerprint = iota
	spanNameLegacy64
	spanNameExpanded255
	spanNameUnknown
)

type dependencyAnchorFingerprint uint8

const (
	dependencyAnchorsUnchecked dependencyAnchorFingerprint = iota
	dependencyAnchorsAbsent
	dependencyAnchorsExact
	dependencyAnchorsPartial
)

type legacyW1BridgeState struct {
	fixtureChecksumValid bool

	officialLedgerExists bool
	officialVersion      int64
	officialDirty        bool

	enterpriseLedgerExists bool
	enterpriseVersion      int64
	enterpriseDirty        bool

	w1State   legacyW1Fingerprint
	spanState spanNameFingerprint

	dependencyState dependencyAnchorFingerprint
}

func classifyLegacyW1Origin(state legacyW1BridgeState) (legacyW1Origin, error) {
	officialMigrationHead := upstream.OfficialMigrationHead()
	enterpriseVersionKnown := enterpriseVersionKnownAtOfficialCheckpoint(
		state.officialVersion,
		state.enterpriseVersion,
	)
	if !state.fixtureChecksumValid {
		return "", fmt.Errorf("legacy W1 fixture checksum mismatch")
	}
	if state.officialDirty || state.enterpriseDirty {
		return "", fmt.Errorf("migration ledger is dirty")
	}
	if state.dependencyState != dependencyAnchorsUnchecked {
		wantDependencyState := dependencyAnchorsExact
		if !state.officialLedgerExists || state.officialVersion == -1 {
			wantDependencyState = dependencyAnchorsAbsent
		}
		if state.dependencyState != wantDependencyState {
			return "", fmt.Errorf(
				"legacy W1 dependency anchors are not exact for this migration checkpoint",
			)
		}
	}
	if !state.officialLedgerExists {
		if !state.enterpriseLedgerExists &&
			state.w1State == legacyW1Absent &&
			state.spanState == spanNameAbsent {
			return legacyW1OriginFresh, nil
		}
		return "", unknownLegacyW1Origin(state)
	}
	if state.officialVersion == -1 {
		if !state.enterpriseLedgerExists &&
			state.w1State == legacyW1Absent &&
			state.spanState == spanNameAbsent {
			return legacyW1OriginFresh, nil
		}
		return "", unknownLegacyW1Origin(state)
	}
	if state.officialVersion < 0 {
		return "", unknownLegacyW1Origin(state)
	}
	if state.officialVersion > officialMigrationHead {
		return "", fmt.Errorf(
			"official migration version %d is newer than packaged head %d",
			state.officialVersion,
			officialMigrationHead,
		)
	}
	if state.enterpriseLedgerExists &&
		state.enterpriseVersion != -1 &&
		!enterpriseVersionKnown {
		return "", unknownLegacyW1Origin(state)
	}
	if state.w1State == legacyW1Partial || state.spanState == spanNameUnknown {
		return "", unknownLegacyW1Origin(state)
	}

	if state.officialVersion < 66 {
		expectedSpanState := spanNameAbsent
		if state.officialVersion >= 55 {
			expectedSpanState = spanNameLegacy64
		}
		if !state.enterpriseLedgerExists &&
			state.w1State == legacyW1Absent &&
			state.spanState == expectedSpanState {
			return legacyW1OriginPre66, nil
		}
		return "", unknownLegacyW1Origin(state)
	}

	if !state.enterpriseLedgerExists &&
		state.w1State == legacyW1Absent &&
		state.spanState == spanNameExpanded255 {
		return legacyW1OriginUpstream66Plus, nil
	}
	if state.officialVersion == officialMigrationHead &&
		state.enterpriseLedgerExists &&
		state.enterpriseVersion == -1 &&
		state.w1State == legacyW1Absent &&
		state.spanState == spanNameExpanded255 {
		return legacyW1OriginUpstream66Plus, nil
	}
	if state.officialVersion == 66 &&
		!state.enterpriseLedgerExists &&
		state.w1State == legacyW1Exact &&
		state.spanState == spanNameLegacy64 {
		return legacyW1OriginExactLegacy66, nil
	}
	if state.enterpriseLedgerExists &&
		enterpriseVersionKnown &&
		state.w1State == legacyW1Exact &&
		state.spanState == spanNameExpanded255 {
		if state.officialVersion == 66 {
			return legacyW1OriginKnownBridged, nil
		}
		return legacyW1OriginFullCurrent, nil
	}
	return "", unknownLegacyW1Origin(state)
}

func unknownLegacyW1Origin(state legacyW1BridgeState) error {
	return fmt.Errorf(
		"unknown legacy W1 migration origin (official=%d, w1=%d, span=%d, enterprise=%t/%d)",
		state.officialVersion,
		state.w1State,
		state.spanState,
		state.enterpriseLedgerExists,
		state.enterpriseVersion,
	)
}
