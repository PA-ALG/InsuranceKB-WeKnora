package postgres

// U-1 fix acceptance (protected, written by Claude): keyword retrieval with the generated-question
// exclusion must run on pg_search 0.22 (Spec docs/design/slices/U-1修复-关键词检索兼容pg_search0.22.md).
// pg_search 0.22 rejects `NOT (knowledge_base_id IN (...) AND <predicate>)` next to the `|||` match
// ("Unsupported query shape"); an anti-join subquery keeps the same "exclude before TopK" meaning.

import (
	"context"
	"os"
	"strings"
	"sync"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	gormpostgres "gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

type recordedQueries struct {
	mu  sync.Mutex
	sql []string
}

func (r *recordedQueries) Match(_ string, actual string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.sql = append(r.sql, actual)
	return nil
}

func keywordSQL(t *testing.T, exclude []string) string {
	t.Helper()
	rec := &recordedQueries{}
	db, mock, err := sqlmock.New(sqlmock.QueryMatcherOption(sqlmock.QueryMatcherFunc(rec.Match)))
	require.NoError(t, err)
	t.Cleanup(func() { _ = db.Close() })
	gdb, err := gorm.Open(gormpostgres.New(gormpostgres.Config{Conn: db}), &gorm.Config{
		DisableAutomaticPing: true,
		Logger:               logger.Default.LogMode(logger.Silent),
	})
	require.NoError(t, err)
	repo := NewPostgresRetrieveEngineRepository(gdb).(*pgRepository)
	mock.ExpectQuery("probe").WillReturnRows(sqlmock.NewRows([]string{"score_function"}).AddRow("paradedb.score"))
	mock.ExpectQuery("keywords").WillReturnRows(sqlmock.NewRows([]string{"id", "chunk_id", "score"}).
		AddRow(1, "chunk-a", 3.5))
	_, err = repo.Retrieve(context.Background(), types.RetrieveParams{
		RetrieverType: types.KeywordsRetrieverType, Query: "合同内容变更", TopK: 5,
		KnowledgeBaseIDs: []string{"kb-a"}, ExcludeGeneratedQuestionKBIDs: exclude,
	})
	require.NoError(t, err)
	require.NoError(t, mock.ExpectationsWereMet())
	require.Len(t, rec.sql, 2, "score-function probe, then the keyword query")
	return rec.sql[1]
}

func TestKeywordExclusionUsesAnAntiJoinSubquery(t *testing.T) {
	q := keywordSQL(t, []string{"kb-a"})
	require.Contains(t, q, "id NOT IN (SELECT id FROM embeddings WHERE knowledge_base_id IN (")
	require.Contains(t, q, types.GeneratedQuestionRowPredicate(""))
	require.NotContains(t, q, "NOT (knowledge_base_id IN",
		"pg_search 0.22 cannot run a NOT(... AND ...) beside the BM25 match")
	require.Less(t, strings.Index(q, "content ||| "), strings.Index(q, "id NOT IN ("))
}

func TestKeywordQueryWithoutExclusionIsUnchanged(t *testing.T) {
	q := keywordSQL(t, nil)
	require.NotContains(t, q, "NOT IN")
	require.NotContains(t, q, "NOT (")
	require.Contains(t, q, "content ||| ")
}

// Runs only against a disposable ParadeDB database (pg_search 0.22 reproduces the production failure).
func TestKeywordExclusionRunsOnParadeDB(t *testing.T) {
	dsn := os.Getenv("WEKNORA_RETRIEVER_TEST_PARADEDB_DSN")
	if dsn == "" {
		t.Skip("set WEKNORA_RETRIEVER_TEST_PARADEDB_DSN to a disposable ParadeDB database")
	}
	gdb, err := gorm.Open(gormpostgres.Open(dsn), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	require.NoError(t, err)
	ctx := context.Background()
	for _, stmt := range []string{
		`CREATE EXTENSION IF NOT EXISTS pg_search`,
		`DROP TABLE IF EXISTS embeddings`,
		`CREATE TABLE embeddings (id serial PRIMARY KEY, created_at timestamptz DEFAULT now(),
		 updated_at timestamptz DEFAULT now(), source_id text NOT NULL, source_type int NOT NULL,
		 chunk_id text, knowledge_id text, knowledge_base_id text, tag_id text, content text NOT NULL,
		 is_enabled boolean DEFAULT true)`,
		`INSERT INTO embeddings (source_id, source_type, chunk_id, knowledge_id, knowledge_base_id, content) VALUES
		 ('c1', 0, 'c1', 'k1', 'kb-a', '合同内容变更 应当 批注 或者 附贴 批单 或者 订立 书面 变更 协议'),
		 ('c1-q1', 0, 'c1', 'k1', 'kb-a', '合同内容变更 需要 什么 形式'),
		 ('c2', 0, 'c2', 'k2', 'kb-b', '合同内容变更 其他 知识库')`,
		`CREATE INDEX embeddings_search_idx ON embeddings
		 USING bm25 (id, knowledge_base_id, content, knowledge_id, chunk_id)
		 WITH (key_field = 'id', text_fields = '{"content": {"tokenizer": {"type": "chinese_lindera"}}}')`,
	} {
		require.NoError(t, gdb.WithContext(ctx).Exec(stmt).Error, stmt)
	}
	t.Cleanup(func() { _ = gdb.Exec(`DROP TABLE IF EXISTS embeddings`).Error })

	repo := NewPostgresRetrieveEngineRepository(gdb)
	results, err := repo.Retrieve(ctx, types.RetrieveParams{
		RetrieverType: types.KeywordsRetrieverType, Query: "合同内容变更", TopK: 10,
		KnowledgeBaseIDs: []string{"kb-a"}, ExcludeGeneratedQuestionKBIDs: []string{"kb-a"},
	})
	require.NoError(t, err)
	require.Len(t, results, 1)
	sources := make([]string, 0, len(results[0].Results))
	for _, r := range results[0].Results {
		sources = append(sources, r.SourceID)
	}
	require.Equal(t, []string{"c1"}, sources, "the ordinary chunk stays; its generated question row is excluded")
}
