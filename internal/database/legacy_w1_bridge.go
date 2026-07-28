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

	"github.com/Tencent/WeKnora/deploy/upstream"
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

type MigrationSafetyError struct {
	Reason string
	Cause  error
}

func (e *MigrationSafetyError) Error() string {
	message := "migration safety check failed: " + e.Reason
	if e.Cause != nil {
		message += ": " + e.Cause.Error()
	}
	return message
}

func (e *MigrationSafetyError) Unwrap() error {
	return e.Cause
}

func newMigrationSafetyError(reason string, cause error) error {
	return &MigrationSafetyError{Reason: reason, Cause: cause}
}

type legacyW1StateQueryer interface {
	QueryRowContext(ctx context.Context, query string, args ...interface{}) *sql.Row
}

type legacyW1StateInspector func(
	ctx context.Context,
	queryer legacyW1StateQueryer,
) (legacyW1BridgeState, error)

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

const spanNameFingerprintSQL = `
SELECT
    to_regclass('public.knowledge_processing_spans') IS NOT NULL,
    COALESCE((
        SELECT relkind = 'r'
        FROM pg_catalog.pg_class
        WHERE oid = to_regclass('public.knowledge_processing_spans')
    ), false),
    EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'knowledge_processing_spans'
          AND column_name = 'name'
    ),
    COALESCE((
        SELECT data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'knowledge_processing_spans'
          AND column_name = 'name'
    ), ''),
    COALESCE((
        SELECT character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'knowledge_processing_spans'
          AND column_name = 'name'
    ), -1),
    COALESCE((
        SELECT is_nullable = 'NO'
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'knowledge_processing_spans'
          AND column_name = 'name'
    ), false),
    COALESCE((
        SELECT column_default IS NULL
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'knowledge_processing_spans'
          AND column_name = 'name'
    ), false)`

// dependencyAnchorFingerprintSQL pins only the base objects on which the
// legacy W1 objects depend. It intentionally does not inventory either table.
const dependencyAnchorFingerprintSQL = `
WITH objects(present, exact) AS (
    VALUES
    (
        to_regclass('public.knowledges') IS NOT NULL,
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class t
            WHERE t.oid = to_regclass('public.knowledges')
              AND t.relkind = 'r'
        )
        AND EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledges'
              AND column_name = 'id'
              AND data_type = 'character varying' AND character_maximum_length = 36
              AND is_nullable = 'NO'
        )
        -- PRIMARY KEY (id), so knowledge_revisions.knowledge_id can reference it.
        AND EXISTS (
            SELECT 1
            FROM pg_catalog.pg_constraint c
            WHERE c.conrelid = to_regclass('public.knowledges')
              AND c.contype = 'p'
              AND c.convalidated AND NOT c.condeferrable
              AND pg_get_constraintdef(c.oid) = 'PRIMARY KEY (id)'
        )
    ),
    (
        to_regclass('public.chunks') IS NOT NULL,
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class t
            WHERE t.oid = to_regclass('public.chunks')
              AND t.relkind = 'r'
        )
        AND EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'chunks'
              AND column_name = 'knowledge_id'
              AND data_type = 'character varying' AND character_maximum_length = 36
              AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'chunks'
              AND column_name = 'chunk_index'
              AND data_type = 'integer' AND is_nullable = 'NO'
              AND column_default IS NULL
        )
        -- chunk_type VARCHAR(20) NOT NULL DEFAULT 'text'
        AND EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'chunks'
              AND column_name = 'chunk_type'
              AND data_type = 'character varying' AND character_maximum_length = 20
              AND is_nullable = 'NO'
              AND column_default IN (
                  $default$'text'::character varying$default$,
                  $default$'text'::text$default$
              )
        )
        AND EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'chunks'
              AND column_name = 'deleted_at'
              AND data_type = 'timestamp with time zone'
              AND is_nullable = 'YES' AND column_default IS NULL
        )
    )
)
SELECT
    count(*) FILTER (WHERE present),
    count(*) FILTER (WHERE exact)
FROM objects`

// legacyW1FingerprintSQL is deliberately a fixed compatibility fingerprint,
// not a reusable schema inventory. Each VALUES row represents one legacy W1
// object: the three added columns, the eight-column table, and the two indexes.
const legacyW1FingerprintSQL = `
WITH objects(present, exact) AS (
    VALUES
    (
        EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledges'
              AND column_name = 'current_parse_attempt'
        ),
        EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledges'
              AND column_name = 'current_parse_attempt'
              AND data_type = 'bigint' AND is_nullable = 'NO'
              AND column_default = '0'::text
        )
    ),
    (
        EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledges'
              AND column_name = 'file_sha256'
        ),
        EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledges'
              AND column_name = 'file_sha256'
              AND data_type = 'character varying' AND character_maximum_length = 64
              AND is_nullable = 'NO'
              AND column_default IN (
                  $default$''::character varying$default$,
                  $default$''::text$default$
              )
        )
    ),
    (
        EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'chunks'
              AND column_name = 'parse_attempt'
        ),
        EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'chunks'
              AND column_name = 'parse_attempt'
              AND data_type = 'bigint' AND is_nullable = 'NO'
              AND column_default = '0'::text
        )
    ),
    (
        to_regclass('public.knowledge_revisions') IS NOT NULL,
        to_regclass('public.knowledge_revisions') IS NOT NULL
        AND EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class t
            WHERE t.oid = to_regclass('public.knowledge_revisions')
              AND t.relkind = 'r'
        )
        AND (
            SELECT count(*) = 8
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
        )
        AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
              AND column_name = 'knowledge_id'
              AND data_type = 'character varying' AND character_maximum_length = 36
              AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
              AND column_name = 'parse_attempt'
              AND data_type = 'bigint' AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
              AND column_name = 'file_sha256'
              AND data_type = 'character varying' AND character_maximum_length = 64
              AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
              AND column_name = 'parser_identity'
              AND data_type = 'jsonb' AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
              AND column_name = 'manifest_algorithm'
              AND data_type = 'character varying' AND character_maximum_length = 64
              AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
              AND column_name = 'manifest_digest'
              AND data_type = 'character varying' AND character_maximum_length = 64
              AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
              AND column_name = 'chunk_count'
              AND data_type = 'integer' AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
              AND column_name = 'completed_at'
              AND data_type = 'timestamp without time zone'
              AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND (
            SELECT count(*) = 6
               AND count(*) FILTER (WHERE c.contype = 'p') = 1
               AND count(*) FILTER (WHERE c.contype = 'f') = 1
               AND count(*) FILTER (WHERE c.contype = 'c') = 4
            FROM pg_catalog.pg_constraint c
            WHERE c.conrelid = to_regclass('public.knowledge_revisions')
        )
        -- PRIMARY KEY (knowledge_id, parse_attempt)
        AND EXISTS (
            SELECT 1
            FROM pg_catalog.pg_constraint c
            WHERE c.conrelid = to_regclass('public.knowledge_revisions')
              AND c.contype = 'p'
              AND c.convalidated AND NOT c.condeferrable
              AND pg_get_constraintdef(c.oid) = 'PRIMARY KEY (knowledge_id, parse_attempt)'
        )
        -- FOREIGN KEY (knowledge_id) REFERENCES knowledges(id) ON DELETE CASCADE
        AND EXISTS (
            SELECT 1
            FROM pg_catalog.pg_constraint c
            WHERE c.conrelid = to_regclass('public.knowledge_revisions')
              AND c.contype = 'f'
              AND c.confrelid = to_regclass('public.knowledges')
              AND c.confdeltype = 'c'
              AND c.convalidated AND NOT c.condeferrable
              AND pg_get_constraintdef(c.oid) =
                  'FOREIGN KEY (knowledge_id) REFERENCES knowledges(id) ON DELETE CASCADE'
        )
        -- CHECK (parse_attempt > 0), CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
        -- CHECK (manifest_digest ~ '^[0-9a-f]{64}$'), CHECK (chunk_count >= 0)
        AND (
            SELECT count(*) = 4
            FROM pg_catalog.pg_constraint c
            WHERE c.conrelid = to_regclass('public.knowledge_revisions')
              AND c.contype = 'c'
              AND c.convalidated AND NOT c.condeferrable
              AND regexp_replace(
                    pg_get_expr(c.conbin, c.conrelid),
                    '[[:space:]()]', '', 'g'
                  ) IN (
                    'parse_attempt>0',
                    'file_sha256::text~''^[0-9a-f]{64}$''::text',
                    'manifest_digest::text~''^[0-9a-f]{64}$''::text',
                    'chunk_count>=0'
                  )
            HAVING count(*) FILTER (
                       WHERE regexp_replace(
                           pg_get_expr(c.conbin, c.conrelid),
                           '[[:space:]()]', '', 'g'
                       ) = 'parse_attempt>0'
                   ) = 1
               AND count(*) FILTER (
                       WHERE regexp_replace(
                           pg_get_expr(c.conbin, c.conrelid),
                           '[[:space:]()]', '', 'g'
                       ) = 'file_sha256::text~''^[0-9a-f]{64}$''::text'
                   ) = 1
               AND count(*) FILTER (
                       WHERE regexp_replace(
                           pg_get_expr(c.conbin, c.conrelid),
                           '[[:space:]()]', '', 'g'
                       ) = 'manifest_digest::text~''^[0-9a-f]{64}$''::text'
                   ) = 1
               AND count(*) FILTER (
                       WHERE regexp_replace(
                           pg_get_expr(c.conbin, c.conrelid),
                           '[[:space:]()]', '', 'g'
                       ) = 'chunk_count>=0'
                   ) = 1
        )
    ),
    (
        to_regclass('public.idx_chunks_live_text_revision_ordinal') IS NOT NULL,
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_index i
            JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
            JOIN pg_catalog.pg_am am ON am.oid = idx.relam
            WHERE idx.oid = to_regclass('public.idx_chunks_live_text_revision_ordinal')
              AND i.indrelid = to_regclass('public.chunks')
              AND am.amname = 'btree'
              AND i.indisunique AND i.indisvalid AND i.indisready AND i.indislive
              AND i.indnkeyatts = 3 AND i.indnatts = 3
              AND ARRAY(
                    SELECT a.attname::text
                    FROM unnest(i.indkey::smallint[]) WITH ORDINALITY AS key(attnum, position)
                    JOIN pg_catalog.pg_attribute a
                      ON a.attrelid = i.indrelid AND a.attnum = key.attnum
                    ORDER BY key.position
                  ) = ARRAY['knowledge_id', 'parse_attempt', 'chunk_index']::text[]
              -- knowledge_id, parse_attempt, chunk_index
              AND regexp_replace(
                    pg_get_expr(i.indpred, i.indrelid),
                    '[[:space:]()]', '', 'g'
                  ) =
                  'deleted_atISNULLANDchunk_type::text=''text''::textANDparse_attempt>0'
              -- WHERE deleted_at IS NULL AND chunk_type = 'text' AND parse_attempt > 0
        )
    ),
    (
        to_regclass('public.idx_knowledge_revisions_completed') IS NOT NULL,
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_index i
            JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
            JOIN pg_catalog.pg_am am ON am.oid = idx.relam
            WHERE idx.oid = to_regclass('public.idx_knowledge_revisions_completed')
              AND i.indrelid = to_regclass('public.knowledge_revisions')
              AND am.amname = 'btree'
              AND NOT i.indisunique AND i.indisvalid AND i.indisready AND i.indislive
              AND i.indnkeyatts = 2 AND i.indnatts = 2
              AND i.indpred IS NULL
              AND ARRAY(
                    SELECT a.attname::text
                    FROM unnest(i.indkey::smallint[]) WITH ORDINALITY AS key(attnum, position)
                    JOIN pg_catalog.pg_attribute a
                      ON a.attrelid = i.indrelid AND a.attnum = key.attnum
                    ORDER BY key.position
                  ) = ARRAY['knowledge_id', 'completed_at']::text[]
              AND ARRAY(
                    SELECT (option::integer & 1)::smallint
                    FROM unnest(i.indoption::smallint[]) WITH ORDINALITY
                         AS ordering(option, position)
                    ORDER BY ordering.position
                  ) = ARRAY[0, 1]::smallint[]
              -- knowledge_id, completed_at DESC
        )
    )
)
SELECT
    count(*) FILTER (WHERE present),
    count(*) FILTER (WHERE exact)
FROM objects`

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
		state.enterpriseVersion != 1 {
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
		state.enterpriseVersion == 1 &&
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
