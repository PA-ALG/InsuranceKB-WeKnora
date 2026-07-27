package versioned

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestKnowledgeRevisionManifestMigrationContract(t *testing.T) {
	_, file, _, ok := runtime.Caller(0)
	require.True(t, ok)
	dir := filepath.Dir(file)
	up, err := os.ReadFile(filepath.Join(dir, "000066_knowledge_revision_manifest.up.sql"))
	require.NoError(t, err)
	down, err := os.ReadFile(filepath.Join(dir, "000066_knowledge_revision_manifest.down.sql"))
	require.NoError(t, err)

	for _, fragment := range []string{
		"current_parse_attempt BIGINT NOT NULL DEFAULT 0",
		"file_sha256 VARCHAR(64) NOT NULL DEFAULT ''",
		"parse_attempt BIGINT NOT NULL DEFAULT 0",
		"CREATE TABLE IF NOT EXISTS knowledge_revisions",
		"PRIMARY KEY (knowledge_id, parse_attempt)",
		"WHERE deleted_at IS NULL AND chunk_type = 'text' AND parse_attempt > 0",
	} {
		require.Contains(t, string(up), fragment)
	}
	require.Contains(t, string(down), "DROP TABLE IF EXISTS knowledge_revisions")
	require.Contains(t, string(down), "DROP COLUMN IF EXISTS current_parse_attempt")

	upFiles, err := filepath.Glob(filepath.Join(dir, "000066_*.up.sql"))
	require.NoError(t, err)
	downFiles, err := filepath.Glob(filepath.Join(dir, "000066_*.down.sql"))
	require.NoError(t, err)
	require.Len(t, upFiles, 1)
	require.Len(t, downFiles, 1)
	require.True(t, strings.HasSuffix(upFiles[0], "knowledge_revision_manifest.up.sql"))
}
