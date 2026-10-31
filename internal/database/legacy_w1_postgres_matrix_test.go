package database

import (
	"context"
	"database/sql"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/Tencent/WeKnora/deploy/upstream"
	"github.com/golang-migrate/migrate/v4"
	"github.com/stretchr/testify/require"
)

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
