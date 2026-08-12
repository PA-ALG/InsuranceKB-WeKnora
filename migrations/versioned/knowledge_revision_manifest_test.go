package versioned

import (
	"crypto/sha256"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestKnowledgeRevisionManifestMigrationContract(t *testing.T) {
	_, file, _, ok := runtime.Caller(0)
	require.True(t, ok)
	officialDir := filepath.Dir(file)
	enterpriseDir := filepath.Join(officialDir, "..", "enterprise", "versioned")
	fixtureDir := filepath.Join(officialDir, "..", "..", "internal", "database", "testdata")

	officialUp := readMigrationContractFile(t, officialDir, "000066_expand_knowledge_span_name.up.sql")
	officialDown := readMigrationContractFile(t, officialDir, "000066_expand_knowledge_span_name.down.sql")
	require.Equal(
		t,
		"0e4e63bb11743284145859f8731c3b877eb47b176a1aef43ed99c41da54e8a82",
		sha256Hex(officialUp),
	)
	require.Equal(
		t,
		"7a80e0486dbe5673840a5008cca2f673da2f5fda39ba837bbfbc7fff01f2563b",
		sha256Hex(officialDown),
	)
	require.Contains(t, string(officialUp), "ALTER COLUMN name TYPE VARCHAR(255)")
	require.NotContains(t, string(officialUp), "knowledge_revisions")

	upFiles, err := filepath.Glob(filepath.Join(officialDir, "000066_*.up.sql"))
	require.NoError(t, err)
	downFiles, err := filepath.Glob(filepath.Join(officialDir, "000066_*.down.sql"))
	require.NoError(t, err)
	require.Len(t, upFiles, 1)
	require.Len(t, downFiles, 1)
	require.True(t, strings.HasSuffix(upFiles[0], "000066_expand_knowledge_span_name.up.sql"))
	require.True(t, strings.HasSuffix(downFiles[0], "000066_expand_knowledge_span_name.down.sql"))

	enterpriseUp := readMigrationContractFile(
		t,
		enterpriseDir,
		"000001_knowledge_revision_manifest.up.sql",
	)
	enterpriseDown := readMigrationContractFile(
		t,
		enterpriseDir,
		"000001_knowledge_revision_manifest.down.sql",
	)
	for _, fragment := range []string{
		"current_parse_attempt BIGINT NOT NULL DEFAULT 0",
		"file_sha256 VARCHAR(64) NOT NULL DEFAULT ''",
		"parse_attempt BIGINT NOT NULL DEFAULT 0",
		"CREATE TABLE IF NOT EXISTS knowledge_revisions",
		"PRIMARY KEY (knowledge_id, parse_attempt)",
		"WHERE deleted_at IS NULL AND chunk_type = 'text' AND parse_attempt > 0",
	} {
		require.Contains(t, string(enterpriseUp), fragment)
	}
	require.Contains(t, string(enterpriseDown), "DROP TABLE IF EXISTS knowledge_revisions")
	require.Contains(t, string(enterpriseDown), "DROP COLUMN IF EXISTS current_parse_attempt")

	legacyUp := readMigrationContractFile(
		t,
		fixtureDir,
		"000066_knowledge_revision_manifest.up.sql",
	)
	legacyDown := readMigrationContractFile(
		t,
		fixtureDir,
		"000066_knowledge_revision_manifest.down.sql",
	)
	require.Equal(
		t,
		"7fd004f131840b938e599d6ac65f20024dcbc7e6b2d7c274e456e32290a8817f",
		sha256Hex(legacyUp),
	)
	require.Equal(
		t,
		"19f60a922f682deb818897a05b84e7fe70d9cedf82eba942dc40b1c9ec60dc58",
		sha256Hex(legacyDown),
	)
}

func TestKnowledgeRevisionSourceMigrationContract(t *testing.T) {
	_, file, _, ok := runtime.Caller(0)
	require.True(t, ok)
	enterpriseDir := filepath.Join(filepath.Dir(file), "..", "enterprise", "versioned")

	up := readMigrationContractFile(
		t,
		enterpriseDir,
		"000004_knowledge_revision_sources.up.sql",
	)
	down := readMigrationContractFile(
		t,
		enterpriseDir,
		"000004_knowledge_revision_sources.down.sql",
	)
	for _, fragment := range []string{
		"CREATE TABLE knowledge_revision_sources",
		"PRIMARY KEY (knowledge_id, parse_attempt)",
		"revision_source_id VARCHAR(64) NOT NULL UNIQUE",
		"FOREIGN KEY (knowledge_id, parse_attempt)",
		"REFERENCES knowledge_revisions (knowledge_id, parse_attempt)",
		"resource_id VARCHAR(36) NOT NULL REFERENCES resources(id)",
		"tenant_id BIGINT NOT NULL",
		"file_sha256 VARCHAR(64) NOT NULL",
		"size BIGINT NOT NULL CHECK (size > 0)",
		"mime_type VARCHAR(255) NOT NULL",
		"page_count INTEGER NULL CHECK (page_count > 0)",
		"retention_state VARCHAR(16) NOT NULL",
		"CHECK (retention_state IN ('pinned', 'released'))",
		"idx_knowledge_revision_sources_resource",
		"idx_knowledge_revision_sources_pinned",
	} {
		require.Contains(t, string(up), fragment)
	}
	require.NotContains(t, string(up), "DROP TABLE")
	require.Contains(t, string(down), "DROP TABLE knowledge_revision_sources")
	require.NotContains(t, string(down), "DROP COLUMN content_hash")
}

func TestKnowledgeRevisionSourceBindingMigrationPreservesRowsAndFreezesTenantAttemptKey(t *testing.T) {
	_, file, _, ok := runtime.Caller(0)
	require.True(t, ok)
	enterpriseDir := filepath.Join(filepath.Dir(file), "..", "enterprise", "versioned")

	up := readMigrationContractFile(t, enterpriseDir, "000005_knowledge_revision_source_binding.up.sql")
	down := readMigrationContractFile(t, enterpriseDir, "000005_knowledge_revision_source_binding.down.sql")
	for _, fragment := range []string{
		"ALTER TABLE knowledge_revision_sources",
		"resource_handle VARCHAR(22)",
		"object_sha256 VARCHAR(64)",
		"manifest_algorithm VARCHAR(64)",
		"manifest_digest VARCHAR(64)",
		"chunk_count INTEGER",
		"immutable_locator TEXT",
		"binding_digest VARCHAR(64)",
		"PRIMARY KEY (tenant_id, knowledge_id, parse_attempt)",
		"UNIQUE (knowledge_id, parse_attempt)",
		"knowledge_revision_source_binding_state",
	} {
		require.Contains(t, string(up), fragment)
	}
	require.NotContains(t, string(up), "DROP TABLE knowledge_revision_sources")
	require.NotContains(t, string(up), "DELETE FROM knowledge_revision_sources")
	require.Contains(t, string(down), "PRIMARY KEY (knowledge_id, parse_attempt)")
	require.Contains(t, string(down), "DROP COLUMN binding_digest")
	require.NotContains(t, string(down), "DROP TABLE knowledge_revision_sources")
}

func TestMigrationSafetyFailureStopsContainerStartup(t *testing.T) {
	_, file, _, ok := runtime.Caller(0)
	require.True(t, ok)
	root := filepath.Join(filepath.Dir(file), "..", "..")
	containerSource := readMigrationContractFile(
		t,
		filepath.Join(root, "internal", "container"),
		"container.go",
	)

	require.Contains(t, string(containerSource), "var safetyErr *database.MigrationSafetyError")
	require.Contains(t, string(containerSource), "errors.As(err, &safetyErr)")
	require.Contains(t, string(containerSource), "return nil, err")
	require.Contains(
		t,
		string(containerSource),
		"Continuing with application startup. Please run migrations manually if needed.",
	)
}

func TestMigrationScriptRejectsLedgerOpeningCommands(t *testing.T) {
	_, file, _, ok := runtime.Caller(0)
	require.True(t, ok)
	script := filepath.Join(filepath.Dir(file), "..", "..", "scripts", "migrate.sh")

	for _, command := range []string{"up", "down", "goto", "force", "version"} {
		t.Run(command, func(t *testing.T) {
			cmd := exec.Command("bash", script, command)
			output, err := cmd.CombinedOutput()

			require.Error(t, err)
			require.Contains(t, string(output), "direct '"+command+"' migration commands are disabled")
			require.Contains(t, string(output), "canonical guarded application migration path")
			require.NotContains(t, string(output), "DB_PASSWORD")
		})
	}
}

func TestMigrationScriptCreatesEnterpriseMigrationsByDefault(t *testing.T) {
	_, file, _, ok := runtime.Caller(0)
	require.True(t, ok)
	script := readMigrationContractFile(
		t,
		filepath.Join(filepath.Dir(file), "..", "..", "scripts"),
		"migrate.sh",
	)

	require.Contains(
		t,
		string(script),
		`MIGRATIONS_DIR="migrations/enterprise/versioned"`,
	)
	require.NotContains(t, string(script), "MIGRATIONS_DIR:-")
}

func TestMigrationScriptCreateIgnoresOfficialDirectoryOverride(t *testing.T) {
	_, file, _, ok := runtime.Caller(0)
	require.True(t, ok)
	root := filepath.Join(filepath.Dir(file), "..", "..")
	script := filepath.Join(root, "scripts", "migrate.sh")
	tempDir := t.TempDir()
	fakeMigrate := filepath.Join(tempDir, "migrate")
	logPath := filepath.Join(tempDir, "migrate-args")
	require.NoError(t, os.WriteFile(
		fakeMigrate,
		[]byte("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$MIGRATE_LOG\"\n"),
		0o755,
	))

	cmd := exec.Command("bash", script, "create", "matrix_probe")
	cmd.Dir = root
	cmd.Env = append(
		os.Environ(),
		"MIGRATIONS_DIR=migrations/versioned",
		"MIGRATE_LOG="+logPath,
		"PATH="+tempDir+":"+os.Getenv("PATH"),
	)
	output, err := cmd.CombinedOutput()
	require.NoError(t, err, string(output))
	args, err := os.ReadFile(logPath)
	require.NoError(t, err)
	require.Contains(t, string(args), "migrations/enterprise/versioned")
	require.NotContains(t, string(args), "migrations/versioned")
}

func readMigrationContractFile(t *testing.T, dir, name string) []byte {
	t.Helper()
	content, err := os.ReadFile(filepath.Join(dir, name))
	require.NoError(t, err)
	return content
}

func sha256Hex(content []byte) string {
	return fmt.Sprintf("%x", sha256.Sum256(content))
}
