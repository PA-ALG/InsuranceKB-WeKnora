package database

import (
	"context"
	"database/sql"
	"net/url"
	"os"
	"testing"

	"github.com/Tencent/WeKnora/deploy/upstream"
	retrieverpostgres "github.com/Tencent/WeKnora/internal/application/repository/retriever/postgres"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/golang-migrate/migrate/v4"
	"github.com/lib/pq"
	"github.com/stretchr/testify/require"
	gormpostgres "gorm.io/driver/postgres"
	"gorm.io/gorm"
)

func TestPostgresEmbeddingsForwardRepair(t *testing.T) {
	rawDSN := os.Getenv("WEKNORA_TEST_POSTGRES_URL")
	if rawDSN == "" {
		t.Skip("WEKNORA_TEST_POSTGRES_URL is not set")
	}
	requireEmbeddingsRepairTestDSN(t, rawDSN)
	matrix := newPostgresMigrationMatrix(t, rawDSN)

	t.Run("advanced ledgers with missing table are repaired", func(t *testing.T) {
		matrix.prepareEmbeddingsRepairPredecessor(t, rawDSN, true)
		require.False(t, matrix.embeddingsTableExists(t))
		repairDSN, err := postgresMatrixDSNWithSkip(rawDSN, false)
		require.NoError(t, err)

		require.NoError(t, RunMigrationsWithOptions(
			repairDSN,
			MigrationOptions{AutoRecoverDirty: true},
		))

		require.True(t, matrix.embeddingsTableExists(t))
		matrix.requireEmbeddingsSchema(t)
		matrix.requireRepository1024InsertRollsBack(t)
		require.NoError(t, RunMigrationsWithOptions(
			repairDSN,
			MigrationOptions{AutoRecoverDirty: true},
		))
	})

	t.Run("existing table and data remain unchanged", func(t *testing.T) {
		repairDSN := matrix.prepareEmbeddingsRepairPredecessor(t, rawDSN, false)
		result, err := matrix.db.ExecContext(
			context.Background(),
			`INSERT INTO embeddings
				(source_id, source_type, content, dimension, is_enabled)
			 VALUES ('existing-source', 0, 'existing-content', 1024, true)`,
		)
		require.NoError(t, err)
		affected, err := result.RowsAffected()
		require.NoError(t, err)
		require.EqualValues(t, 1, affected)

		require.NoError(t, RunMigrationsWithOptions(
			repairDSN,
			MigrationOptions{AutoRecoverDirty: true},
		))

		var content string
		require.NoError(t, matrix.db.QueryRowContext(
			context.Background(),
			"SELECT content FROM embeddings WHERE source_id = 'existing-source'",
		).Scan(&content))
		require.Equal(t, "existing-content", content)
		matrix.requireEmbeddingsSchema(t)
	})

	t.Run("partial existing table fails before enterprise ledger advances", func(t *testing.T) {
		repairDSN := matrix.prepareEmbeddingsRepairPredecessor(t, rawDSN, false)
		_, err := matrix.db.ExecContext(
			context.Background(),
			`INSERT INTO embeddings
				(source_id, source_type, content, dimension, is_enabled)
			 VALUES ('partial-source', 0, 'partial-sentinel', 1024, true);
			 DROP INDEX idx_embeddings_tag_id;
			 ALTER TABLE embeddings DROP COLUMN tag_id`,
		)
		require.NoError(t, err)
		require.False(t, matrix.embeddingsColumnExists(t, "tag_id"))

		migrationSQL, err := os.ReadFile(
			"migrations/enterprise/versioned/000003_embeddings_forward_repair.up.sql",
		)
		require.NoError(t, err)
		directDB, err := sql.Open("postgres", repairDSN)
		require.NoError(t, err)
		require.NoError(t, directDB.PingContext(context.Background()))
		_, directErr := directDB.ExecContext(
			context.Background(),
			string(migrationSQL),
		)
		require.Error(t, directErr)
		var postgresErr *pq.Error
		require.ErrorAs(t, directErr, &postgresErr)
		require.Equal(t, pq.ErrorCode("55000"), postgresErr.Code)
		require.NoError(t, directDB.Close())
		migrationErr := RunMigrationsWithOptions(
			repairDSN,
			MigrationOptions{AutoRecoverDirty: true},
		)
		require.Error(t, migrationErr)
		var safetyErr *MigrationSafetyError
		require.ErrorAs(t, migrationErr, &safetyErr)

		matrix.requireEnterpriseVersion(t, 2)
		var sentinel string
		require.NoError(t, matrix.db.QueryRowContext(
			context.Background(),
			"SELECT content FROM embeddings WHERE source_id = 'partial-source'",
		).Scan(&sentinel))
		require.Equal(t, "partial-sentinel", sentinel)
		require.False(t, matrix.embeddingsColumnExists(t, "tag_id"))
	})

	t.Run("skip embedding remains a no-op", func(t *testing.T) {
		matrix.prepareEmbeddingsRepairPredecessor(t, rawDSN, true)

		require.NoError(t, matrix.run())

		require.False(t, matrix.embeddingsTableExists(t))
		matrix.requireEnterpriseVersion(t, packagedEnterpriseMigrationHead)
	})

	t.Run("conservative down preserves the repaired table", func(t *testing.T) {
		matrix.prepareEmbeddingsRepairPredecessor(t, rawDSN, true)
		repairDSN, err := postgresMatrixDSNWithSkip(rawDSN, false)
		require.NoError(t, err)
		require.NoError(t, RunMigrationsWithOptions(
			repairDSN,
			MigrationOptions{AutoRecoverDirty: true},
		))
		_, err = matrix.db.ExecContext(
			context.Background(),
			`INSERT INTO embeddings
				(source_id, source_type, content, dimension, is_enabled)
			 VALUES ('down-source', 0, 'preserve-on-down', 1024, true)`,
		)
		require.NoError(t, err)

		enterpriseDSN, err := enterpriseMigrationDSN(repairDSN)
		require.NoError(t, err)
		enterpriseMigrator, err := migrate.New(enterprisePostgresMigrationSource, enterpriseDSN)
		require.NoError(t, err)
		require.NoError(t, enterpriseMigrator.Steps(-1))
		matrix.requireEnterpriseVersion(t, 2)
		require.True(t, matrix.embeddingsTableExists(t))
		var content string
		require.NoError(t, matrix.db.QueryRowContext(
			context.Background(),
			"SELECT content FROM embeddings WHERE source_id = 'down-source'",
		).Scan(&content))
		require.Equal(t, "preserve-on-down", content)
		require.NoError(t, enterpriseMigrator.Migrate(packagedEnterpriseMigrationHead))
		sourceErr, databaseErr := enterpriseMigrator.Close()
		require.NoError(t, sourceErr)
		require.NoError(t, databaseErr)
		matrix.requireEnterpriseVersion(t, packagedEnterpriseMigrationHead)
	})
}

func requireEmbeddingsRepairTestDSN(t *testing.T, rawDSN string) {
	t.Helper()
	parsed, err := url.Parse(rawDSN)
	require.NoError(t, err)
	require.Equal(t, "/weknora_embeddings_repair_test", parsed.Path)
}

func (m *postgresMigrationMatrix) prepareEmbeddingsRepairPredecessor(
	t *testing.T,
	rawDSN string,
	skipEmbedding bool,
) string {
	t.Helper()
	m.reset(t)
	dsn, err := postgresMatrixDSNWithSkip(rawDSN, skipEmbedding)
	require.NoError(t, err)
	migratePostgresSourceTo(
		t,
		officialPostgresMigrationSource,
		dsn,
		uint(upstream.OfficialMigrationHead()),
	)
	enterpriseDSN, err := enterpriseMigrationDSN(dsn)
	require.NoError(t, err)
	migratePostgresSourceTo(t, enterprisePostgresMigrationSource, enterpriseDSN, 2)
	return dsn
}

func migratePostgresSourceTo(t *testing.T, source, dsn string, version uint) {
	t.Helper()
	migrator, err := migrate.New(source, dsn)
	require.NoError(t, err)
	require.NoError(t, migrator.Migrate(version))
	sourceErr, databaseErr := migrator.Close()
	require.NoError(t, sourceErr)
	require.NoError(t, databaseErr)
}

func (m *postgresMigrationMatrix) embeddingsTableExists(t *testing.T) bool {
	t.Helper()
	var exists bool
	require.NoError(t, m.db.QueryRowContext(
		context.Background(),
		"SELECT to_regclass('public.embeddings') IS NOT NULL",
	).Scan(&exists))
	return exists
}

func (m *postgresMigrationMatrix) embeddingsColumnExists(
	t *testing.T,
	columnName string,
) bool {
	t.Helper()
	var exists bool
	require.NoError(t, m.db.QueryRowContext(
		context.Background(),
		`SELECT EXISTS (
			SELECT 1
			  FROM information_schema.columns
			 WHERE table_schema = 'public'
			   AND table_name = 'embeddings'
			   AND column_name = $1
		)`,
		columnName,
	).Scan(&exists))
	return exists
}

func (m *postgresMigrationMatrix) requireEnterpriseVersion(t *testing.T, want uint) {
	t.Helper()
	var version uint
	var dirty bool
	require.NoError(t, m.db.QueryRowContext(
		context.Background(),
		"SELECT version, dirty FROM enterprise_schema_migrations",
	).Scan(&version, &dirty))
	require.Equal(t, want, version)
	require.False(t, dirty)
}

func (m *postgresMigrationMatrix) requireEmbeddingsSchema(t *testing.T) {
	t.Helper()
	type column struct {
		name     string
		dataType string
		notNull  bool
	}
	rows, err := m.db.QueryContext(
		context.Background(),
		`SELECT attname, format_type(atttypid, atttypmod), attnotnull
		   FROM pg_attribute
		  WHERE attrelid = 'public.embeddings'::regclass
		    AND attnum > 0
		    AND NOT attisdropped
		  ORDER BY attnum`,
	)
	require.NoError(t, err)
	defer rows.Close()
	var got []column
	for rows.Next() {
		var value column
		require.NoError(t, rows.Scan(&value.name, &value.dataType, &value.notNull))
		got = append(got, value)
	}
	require.NoError(t, rows.Err())
	require.Equal(t, []column{
		{name: "id", dataType: "integer", notNull: true},
		{name: "created_at", dataType: "timestamp with time zone"},
		{name: "updated_at", dataType: "timestamp with time zone"},
		{name: "source_id", dataType: "character varying(64)", notNull: true},
		{name: "source_type", dataType: "integer", notNull: true},
		{name: "chunk_id", dataType: "character varying(64)"},
		{name: "knowledge_id", dataType: "character varying(64)"},
		{name: "knowledge_base_id", dataType: "character varying(64)"},
		{name: "content", dataType: "text"},
		{name: "dimension", dataType: "integer", notNull: true},
		{name: "embedding", dataType: "halfvec"},
		{name: "is_enabled", dataType: "boolean"},
		{name: "tag_id", dataType: "character varying(36)"},
	}, got)

	indexRows, err := m.db.QueryContext(
		context.Background(),
		`SELECT indexname
		   FROM pg_indexes
		  WHERE schemaname = 'public' AND tablename = 'embeddings'`,
	)
	require.NoError(t, err)
	defer indexRows.Close()
	var indexes []string
	for indexRows.Next() {
		var name string
		require.NoError(t, indexRows.Scan(&name))
		indexes = append(indexes, name)
	}
	require.NoError(t, indexRows.Err())
	require.ElementsMatch(t, []string{
		"embeddings_pkey",
		"embeddings_unique_source",
		"embeddings_search_idx",
		"embeddings_embedding_idx_3584",
		"embeddings_embedding_idx_798",
		"embeddings_embedding_idx_1024",
		"idx_embeddings_is_enabled",
		"idx_embeddings_knowledge_base_id",
		"idx_embeddings_tag_id",
	}, indexes)
}

func (m *postgresMigrationMatrix) requireRepository1024InsertRollsBack(
	t *testing.T,
) {
	t.Helper()
	tx, err := m.db.BeginTx(context.Background(), nil)
	require.NoError(t, err)
	gormDB, err := gorm.Open(
		gormpostgres.New(gormpostgres.Config{Conn: tx}),
		&gorm.Config{DisableAutomaticPing: true, SkipDefaultTransaction: true},
	)
	require.NoError(t, err)
	repository := retrieverpostgres.NewPostgresRetrieveEngineRepository(gormDB)
	const sourceID = "repair-1024-source"
	require.NoError(t, repository.BatchSave(
		context.Background(),
		[]*types.IndexInfo{{
			Content:         "synthetic repair verification",
			SourceID:        sourceID,
			SourceType:      types.ChunkSourceType,
			ChunkID:         "repair-1024-chunk",
			KnowledgeID:     "repair-1024-knowledge",
			KnowledgeBaseID: "repair-1024-kb",
			IsEnabled:       true,
		}},
		map[string]any{"embedding": map[string][]float32{
			sourceID: make([]float32, 1024),
		}},
	))
	var count int
	require.NoError(t, tx.QueryRowContext(
		context.Background(),
		"SELECT COUNT(*) FROM embeddings WHERE source_id = $1",
		sourceID,
	).Scan(&count))
	require.Equal(t, 1, count)
	require.NoError(t, tx.Rollback())
	require.NoError(t, m.db.QueryRowContext(
		context.Background(),
		"SELECT COUNT(*) FROM embeddings WHERE source_id = $1",
		sourceID,
	).Scan(&count))
	require.Zero(t, count)
}
