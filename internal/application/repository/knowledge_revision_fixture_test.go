package repository

import (
	"strings"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func setupRevisionTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	dsn := "file:" + uuid.NewString() + "?mode=memory&cache=shared&_busy_timeout=5000"
	db, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{})
	require.NoError(t, err)
	sqlDB, err := db.DB()
	require.NoError(t, err)
	sqlDB.SetMaxOpenConns(1)
	require.NoError(t, db.Exec(`
CREATE TABLE knowledges (
	id TEXT PRIMARY KEY,
	tenant_id INTEGER NOT NULL,
	knowledge_base_id TEXT NOT NULL,
	parse_status TEXT NOT NULL,
	enable_status TEXT NOT NULL,
	pending_subtasks_count INTEGER NOT NULL DEFAULT 0,
	current_parse_attempt INTEGER NOT NULL DEFAULT 0,
	file_path TEXT NOT NULL DEFAULT '',
	file_sha256 TEXT NOT NULL DEFAULT '',
	embedding_model_id TEXT NOT NULL DEFAULT '',
	description TEXT NOT NULL DEFAULT '',
	error_message TEXT NOT NULL DEFAULT '',
	processed_at DATETIME,
	updated_at DATETIME,
	deleted_at DATETIME
);
CREATE TABLE chunks (
	id TEXT PRIMARY KEY,
	tenant_id INTEGER NOT NULL,
	knowledge_id TEXT NOT NULL,
	knowledge_base_id TEXT NOT NULL,
	content TEXT NOT NULL,
	chunk_index INTEGER NOT NULL,
	chunk_type TEXT NOT NULL,
	parse_attempt INTEGER NOT NULL DEFAULT 0,
	deleted_at DATETIME
);
CREATE TABLE knowledge_revisions (
	knowledge_id TEXT NOT NULL,
	parse_attempt INTEGER NOT NULL,
	file_sha256 TEXT NOT NULL,
	parser_identity TEXT NOT NULL,
	manifest_algorithm TEXT NOT NULL,
	manifest_digest TEXT NOT NULL,
	chunk_count INTEGER NOT NULL,
	completed_at DATETIME NOT NULL,
	PRIMARY KEY (knowledge_id, parse_attempt)
);
CREATE TABLE resources (
	id TEXT PRIMARY KEY,
	handle TEXT NOT NULL UNIQUE,
	tenant_id INTEGER NOT NULL,
	provider TEXT NOT NULL,
	physical_path TEXT NOT NULL,
	location_hash TEXT NOT NULL,
	kind TEXT NOT NULL,
	mime_type TEXT NOT NULL,
	original_name TEXT NOT NULL,
	size INTEGER NOT NULL,
	content_hash TEXT NOT NULL DEFAULT '',
	lifecycle TEXT NOT NULL,
	state TEXT NOT NULL,
	created_at DATETIME,
	updated_at DATETIME,
	deleted_at DATETIME
);
CREATE TABLE resource_bindings (
	id TEXT PRIMARY KEY,
	resource_id TEXT NOT NULL,
	tenant_id INTEGER NOT NULL,
	owner_type TEXT NOT NULL,
	owner_id TEXT NOT NULL,
	relation TEXT NOT NULL,
	created_at DATETIME
);
CREATE TABLE knowledge_bases (
	id TEXT PRIMARY KEY,
	tenant_id INTEGER NOT NULL,
	name TEXT NOT NULL DEFAULT '',
	created_at DATETIME,
	updated_at DATETIME,
	deleted_at DATETIME
);
CREATE TABLE knowledge_revision_sources (
	tenant_id INTEGER NOT NULL,
	knowledge_id TEXT NOT NULL,
	parse_attempt INTEGER NOT NULL,
	revision_source_id TEXT NOT NULL UNIQUE,
	resource_id TEXT NOT NULL,
	resource_handle TEXT NOT NULL DEFAULT '',
	file_sha256 TEXT NOT NULL,
	object_sha256 TEXT NOT NULL DEFAULT '',
	size INTEGER NOT NULL,
	mime_type TEXT NOT NULL,
	page_count INTEGER,
	manifest_algorithm TEXT NOT NULL DEFAULT '',
	manifest_digest TEXT NOT NULL DEFAULT '',
	chunk_count INTEGER NOT NULL DEFAULT 0,
	immutable_locator TEXT NOT NULL DEFAULT '',
	binding_digest TEXT NOT NULL DEFAULT '',
	retention_state TEXT NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	released_at DATETIME,
	PRIMARY KEY (knowledge_id, parse_attempt)
);
`).Error)
	// S4c-2b-1: pinning and sealing check the knowledge base is live; the seeded knowledge
	// belongs to tenant 1 / kb-1.
	require.NoError(t, db.Exec(`INSERT INTO knowledge_bases (id, tenant_id, name) VALUES ('kb-1', 1, 'kb-1')`).Error)
	t.Cleanup(func() { _ = sqlDB.Close() })
	return db
}

func seedRevisionKnowledge(t *testing.T, db *gorm.DB, status string, attempt int64, pending int) string {
	t.Helper()
	id := uuid.NewString()
	resourceID := uuid.NewString()
	handle := strings.ReplaceAll(uuid.NewString(), "-", "")[:types.ResourceHandleLength]
	fileSHA256 := "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	require.NoError(t, db.Exec(`
INSERT INTO resources (
	id, handle, tenant_id, provider, physical_path, location_hash, kind,
	mime_type, original_name, size, content_hash, lifecycle, state, created_at, updated_at
) VALUES (?, ?, 1, 'local', ?, ?, 'file', 'application/pdf', 'input.pdf', 1024, '', 'persistent', 'active', ?, ?)
`, resourceID, handle, "/files/"+id+".pdf", strings.Repeat("f", 64),
		time.Now().UTC(), time.Now().UTC()).Error)
	require.NoError(t, db.Exec(`
INSERT INTO resource_bindings (
	id, resource_id, tenant_id, owner_type, owner_id, relation, created_at
) VALUES (?, ?, 1, 'knowledge', ?, 'source_file', ?)
`, uuid.NewString(), resourceID, id, time.Now().UTC()).Error)
	require.NoError(t, db.Exec(`
INSERT INTO knowledges (
	id, tenant_id, knowledge_base_id, parse_status, enable_status,
	pending_subtasks_count, current_parse_attempt, file_path, file_sha256,
	embedding_model_id, updated_at
) VALUES (?, 1, 'kb-1', ?, 'disabled', ?, ?, ?, ?, 'embed-1', ?)
`, id, status, pending, attempt, types.BuildResourcePath(handle), fileSHA256,
		time.Now().UTC()).Error)
	return id
}

func seedRevisionChunk(t *testing.T, db *gorm.DB, knowledgeID string, attempt int64, index int, content string) {
	t.Helper()
	require.NoError(t, db.Exec(`
INSERT INTO chunks (
	id, tenant_id, knowledge_id, knowledge_base_id, content, chunk_index,
	chunk_type, parse_attempt
) VALUES (?, 1, ?, 'kb-1', ?, ?, 'text', ?)
`, uuid.NewString(), knowledgeID, content, index, attempt).Error)
}

func testRevisionBinding(attempt int64) types.RevisionCommitBinding {
	return types.RevisionCommitBinding{
		ParseAttempt: attempt,
		FileSHA256:   "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		ParserIdentity: types.RevisionParserIdentity{
			AppVersion:       "1.0.0",
			AppCommit:        "deadbeef",
			DocReader:        "docreader-v1",
			ParserEngine:     "builtin",
			ChunkSize:        512,
			ChunkOverlap:     64,
			EmbeddingModelID: "embed-1",
		},
	}
}
