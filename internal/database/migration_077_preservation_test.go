package database

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

// UPG-07: our 000077 freezes the legacy Wiki log history instead of dropping it.
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
