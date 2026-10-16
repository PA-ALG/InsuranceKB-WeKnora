package releasestore

import (
	"fmt"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

var postgresSourceRef = "source:v1:k-1:1:" + fileSHA

func setupRevisionSourceTables(t *testing.T, db *gorm.DB) {
	t.Helper()
	require.NoError(t, db.Exec(`CREATE TABLE knowledge_bases (
id VARCHAR(36) PRIMARY KEY, tenant_id BIGINT NOT NULL, deleted_at TIMESTAMPTZ);
CREATE TABLE knowledges (
 id VARCHAR(36) PRIMARY KEY, tenant_id BIGINT NOT NULL, knowledge_base_id TEXT NOT NULL,
 parse_status TEXT NOT NULL, enable_status TEXT NOT NULL DEFAULT 'enabled',
 file_path TEXT NOT NULL DEFAULT '', updated_at TIMESTAMPTZ, deleted_at TIMESTAMPTZ);
CREATE TABLE chunks (id TEXT PRIMARY KEY, knowledge_id TEXT, chunk_index INT, chunk_type TEXT,
 deleted_at TIMESTAMPTZ);`).Error)
	require.NoError(t, db.AutoMigrate(&types.StoredResource{}, &types.ResourceBinding{}))
	for _, name := range []string{
		"000001_knowledge_revision_manifest.up.sql", "000004_knowledge_revision_sources.up.sql",
		"000005_knowledge_revision_source_binding.up.sql", "000007_release_source_pins.up.sql",
	} {
		require.NoError(t, db.Exec(migrationSQL(t, name)).Error)
	}
	seedSource(t, db, "k-1", 7, "raw-1", 1)
}

func seedSource(t *testing.T, db *gorm.DB, id string, tenantID uint64, kbID string, attempt int64) string {
	t.Helper()
	now := time.Now().UTC()
	require.NoError(t, db.Exec(`INSERT INTO knowledge_bases (id, tenant_id) VALUES (?, ?)
ON CONFLICT (id) DO NOTHING`, kbID, tenantID).Error)
	handle := shortDigest(fmt.Sprintf("%s:%d", id, attempt))[:22]
	resource := types.StoredResource{
		ID: "res-" + shortDigest(id+handle), TenantID: tenantID, Handle: handle,
		Provider: "local", PhysicalPath: "test-source.pdf", LocationHash: shortDigest(handle),
		MimeType: "application/pdf", Size: 42, ContentHash: fileSHA,
	}
	require.NoError(t, db.Create(&resource).Error)
	require.NoError(t, db.Exec(`INSERT INTO knowledges
(id, tenant_id, knowledge_base_id, parse_status, current_parse_attempt, file_path, file_sha256)
VALUES (?, ?, ?, 'completed', ?, ?, ?) ON CONFLICT (id) DO NOTHING`,
		id, tenantID, kbID, attempt, types.BuildResourcePath(handle), fileSHA).Error)
	require.NoError(t, db.Create(&types.ResourceBinding{
		ResourceID: resource.ID, TenantID: tenantID, OwnerType: "knowledge", OwnerID: id, Relation: "source_file",
	}).Error)
	require.NoError(t, db.Exec(`INSERT INTO knowledge_revisions
(knowledge_id, parse_attempt, file_sha256, parser_identity,
 manifest_algorithm, manifest_digest, chunk_count, completed_at)
VALUES (?, ?, ?, '{}', ?, ?, 1, ?)`, id, attempt, fileSHA, types.RevisionManifestAlgorithm, fileSHA, now).Error)
	source := types.KnowledgeRevisionSource{
		TenantID: tenantID, KnowledgeID: id, ParseAttempt: attempt, ResourceID: resource.ID,
		ResourceHandle: handle, FileSHA256: fileSHA, ObjectSHA256: fileSHA, Size: resource.Size,
		MimeType: resource.MimeType, ManifestAlgorithm: types.RevisionManifestAlgorithm,
		ManifestDigest: fileSHA, ChunkCount: 1, ImmutableLocator: types.BuildResourcePath(handle),
		RetentionState: types.KnowledgeRevisionSourceReleased, ReleasedAt: &now, CreatedAt: now, UpdatedAt: now,
	}
	var err error
	source.RevisionSourceID, err = types.ComputeKnowledgeRevisionSourceID(source)
	require.NoError(t, err)
	require.NoError(t, db.Create(&source).Error)
	return fmt.Sprintf("source:v1:%s:%d:%s", id, attempt, fileSHA)
}
