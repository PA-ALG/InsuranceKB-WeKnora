package postgres

// U-1 fix, #471 review R1 (written by Claude): the pg_search-0.22-compatible exclusion must drop exactly
// the rows the original `NOT (K AND P)` dropped, including rows where K AND P is UNKNOWN
// (e.g. chunk_id IS NULL), where K is "knowledge_base_id IN (excluded KBs)" and P the generated-question
// row predicate.

import (
	"fmt"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"gorm.io/gorm/logger"
)

func TestKeywordExclusionSelectsTrueOrUnknownRows(t *testing.T) {
	q := keywordSQL(t, []string{"kb-a"})
	pred := types.GeneratedQuestionRowPredicate("")
	require.Contains(t, q, "knowledge_base_id IN ($4) IS NOT FALSE AND ("+pred+") IS NOT FALSE)")
}

type exclusionRow struct {
	ID       int
	SourceID string
	ChunkID  *string
	KBID     *string
	Score    float64
}

func strp(s string) *string { return &s }

func exclusionDB(t *testing.T, rows []exclusionRow) *gorm.DB {
	t.Helper()
	db, err := gorm.Open(sqlite.Open("file::memory:"), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	require.NoError(t, err)
	require.NoError(t, db.Exec(`CREATE TABLE embeddings (id INTEGER PRIMARY KEY, source_id TEXT NOT NULL,
		source_type INTEGER NOT NULL, chunk_id TEXT, knowledge_base_id TEXT, score REAL)`).Error)
	for _, r := range rows {
		require.NoError(t, db.Exec(`INSERT INTO embeddings VALUES (?, ?, ?, ?, ?, ?)`,
			r.ID, r.SourceID, int(types.ChunkSourceType), r.ChunkID, r.KBID, r.Score).Error)
	}
	return db
}

func ids(t *testing.T, db *gorm.DB, where string, vars []interface{}, limit int) []int {
	t.Helper()
	sql := "SELECT id FROM embeddings WHERE " + where + " ORDER BY score DESC"
	if limit > 0 {
		sql += fmt.Sprintf(" LIMIT %d", limit)
	}
	var out []int
	require.NoError(t, db.Raw(sql, vars...).Scan(&out).Error)
	return out
}

func exclusionExpr(t *testing.T, kbIDs []string) clause.Expr {
	t.Helper()
	expr, ok := generatedQuestionExclusionClause(kbIDs).(clause.Expr)
	require.True(t, ok)
	return expr
}

// Codex's counterexample: an ordinary body row and a NULL-chunk row in the excluded KB, TopK = 1.
func TestNullChunkRowStaysExcludedUnderTopK(t *testing.T) {
	db := exclusionDB(t, []exclusionRow{
		{ID: 1, SourceID: "a", ChunkID: strp("a"), KBID: strp("kb-a"), Score: 10},
		{ID: 2, SourceID: "missing-chunk", ChunkID: nil, KBID: strp("kb-a"), Score: 100},
	})
	expr := exclusionExpr(t, []string{"kb-a"})
	scope := "knowledge_base_id = 'kb-a' AND "
	require.Equal(t, []int{1}, ids(t, db, scope+expr.SQL, expr.Vars, 1))
}

// Every three-valued combination: the new clause keeps exactly the rows NOT (K AND P) keeps.
func TestExclusionMatchesTheOriginalThreeValuedSemantics(t *testing.T) {
	rows := []exclusionRow{
		{ID: 1, SourceID: "a", ChunkID: strp("a"), KBID: strp("kb-a"), Score: 10},         // normal body
		{ID: 2, SourceID: "missing-chunk", ChunkID: nil, KBID: strp("kb-a"), Score: 100},  // chunk_id NULL
		{ID: 3, SourceID: "x", ChunkID: strp(""), KBID: strp("kb-a"), Score: 50},          // empty chunk_id
		{ID: 4, SourceID: "a-q1", ChunkID: strp("a"), KBID: strp("kb-a"), Score: 90},      // generated question
		{ID: 5, SourceID: "b-q1", ChunkID: strp("b"), KBID: strp("kb-b"), Score: 95},      // other KB
		{ID: 6, SourceID: "n-q1", ChunkID: strp("n"), KBID: nil, Score: 80},               // KB NULL, P true
		{ID: 7, SourceID: "m", ChunkID: strp("m"), KBID: nil, Score: 70},                  // KB NULL, P false
		{ID: 8, SourceID: "missing-chunk-b", ChunkID: nil, KBID: strp("kb-b"), Score: 60}, // other KB, NULL
		{ID: 9, SourceID: "missing-chunk-n", ChunkID: nil, KBID: nil, Score: 40},          // both NULL
		{ID: 10, SourceID: "e-q1", ChunkID: strp("e"), KBID: strp("kb-a"), Score: 30},     // generated question
		{ID: 11, SourceID: "f", ChunkID: strp("f-other"), KBID: strp("kb-a"), Score: 20},  // unrelated source
	}
	db := exclusionDB(t, rows)
	expr := exclusionExpr(t, []string{"kb-a"})
	original := fmt.Sprintf("NOT (knowledge_base_id IN (?) AND %s)", types.GeneratedQuestionRowPredicate(""))
	want := ids(t, db, original, []interface{}{"kb-a"}, 0)
	got := ids(t, db, expr.SQL, expr.Vars, 0)
	require.Equal(t, want, got)
	require.Equal(t, []int{5, 7, 8, 3, 11, 1}, got, "kept rows, score order")
	require.False(t, strings.Contains(expr.SQL, "NOT ("), "no NOT (...) beside the BM25 match")
}
