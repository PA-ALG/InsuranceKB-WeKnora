DO $$ BEGIN RAISE NOTICE '[Migration 000001] Creating revision manifest contract...'; END $$;

ALTER TABLE knowledges
    ADD COLUMN IF NOT EXISTS current_parse_attempt BIGINT NOT NULL DEFAULT 0;
ALTER TABLE knowledges
    ADD COLUMN IF NOT EXISTS file_sha256 VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS parse_attempt BIGINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS knowledge_revisions (
    knowledge_id VARCHAR(36) NOT NULL REFERENCES knowledges(id) ON DELETE CASCADE,
    parse_attempt BIGINT NOT NULL CHECK (parse_attempt > 0),
    file_sha256 VARCHAR(64) NOT NULL CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
    parser_identity JSONB NOT NULL,
    manifest_algorithm VARCHAR(64) NOT NULL,
    manifest_digest VARCHAR(64) NOT NULL CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
    chunk_count INTEGER NOT NULL CHECK (chunk_count >= 0),
    completed_at TIMESTAMP NOT NULL,
    PRIMARY KEY (knowledge_id, parse_attempt)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_live_text_revision_ordinal
    ON chunks (knowledge_id, parse_attempt, chunk_index)
    WHERE deleted_at IS NULL AND chunk_type = 'text' AND parse_attempt > 0;

CREATE INDEX IF NOT EXISTS idx_knowledge_revisions_completed
    ON knowledge_revisions (knowledge_id, completed_at DESC);

DO $$ BEGIN RAISE NOTICE '[Migration 000001] Revision manifest contract ready'; END $$;
