package database

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/golang-migrate/migrate/v4/source"
	_ "github.com/golang-migrate/migrate/v4/source/file"
	"github.com/stretchr/testify/require"
)

// Two pull requests that each take the next migration number both pass their
// own checks and collide once both are merged: golang-migrate refuses to load
// a directory with a duplicate version, so every deployment fails to migrate.
// 000104 did exactly that. Loading each directory catches it, since pull
// request CI runs on the merge with the current main.
func TestMigrationDirectoriesLoad(t *testing.T) {
	root := sqliteRepoRoot(t)
	for _, dir := range []string{"versioned", "sqlite"} {
		src, err := source.Open("file://" + filepath.Join(root, "migrations", dir))
		require.NoError(t, err, "migrations/%s must load", dir)
		require.NoError(t, src.Close())
	}
}

func TestMigration077FreezesWikiLogHistoryAndArchivesLegacyPage(t *testing.T) {
	root := sqliteRepoRoot(t)
	up, err := os.ReadFile(filepath.Join(
		root,
		"migrations",
		"versioned",
		"000077_remove_wiki_log.up.sql",
	))
	require.NoError(t, err)
	down, err := os.ReadFile(filepath.Join(
		root,
		"migrations",
		"versioned",
		"000077_remove_wiki_log.down.sql",
	))
	require.NoError(t, err)

	upSQL := strings.ToUpper(string(up))
	downSQL := strings.ToUpper(string(down))
	require.NotContains(t, upSQL, "DROP TABLE")
	require.NotContains(t, upSQL, "TRUNCATE")
	require.NotContains(t, upSQL, "DELETE FROM WIKI_LOG_ENTRIES")
	require.NotContains(t, upSQL, "DELETE FROM WIKI_PAGES")
	require.Contains(t, upSQL, "UPDATE WIKI_PAGES")
	require.Contains(t, upSQL, "SET STATUS = 'ARCHIVED'")
	require.Contains(t, upSQL, "DELETED_AT = COALESCE(DELETED_AT, CURRENT_TIMESTAMP)")
	require.Contains(t, upSQL, "WHERE PAGE_TYPE = 'LOG'")
	require.NotContains(t, downSQL, "DROP TABLE")
	require.NotContains(t, downSQL, "DELETE FROM WIKI_PAGES")
}
