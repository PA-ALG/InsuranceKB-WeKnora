DO $$ BEGIN RAISE NOTICE '[Enterprise 000004] Creating immutable knowledge revision sources...'; END $$;

CREATE TABLE knowledge_revision_sources (
    tenant_id BIGINT NOT NULL,
    knowledge_id VARCHAR(36) NOT NULL,
    parse_attempt BIGINT NOT NULL CHECK (parse_attempt > 0),
    revision_source_id VARCHAR(64) NOT NULL UNIQUE
        CHECK (revision_source_id ~ '^[0-9a-f]{64}$'),
    resource_id VARCHAR(36) NOT NULL REFERENCES resources(id) ON DELETE RESTRICT,
    file_sha256 VARCHAR(64) NOT NULL CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
    size BIGINT NOT NULL CHECK (size > 0),
    mime_type VARCHAR(255) NOT NULL,
    page_count INTEGER NULL CHECK (page_count > 0),
    retention_state VARCHAR(16) NOT NULL DEFAULT 'pinned',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    released_at TIMESTAMPTZ NULL,
    PRIMARY KEY (knowledge_id, parse_attempt),
    FOREIGN KEY (knowledge_id, parse_attempt)
        REFERENCES knowledge_revisions (knowledge_id, parse_attempt) ON DELETE RESTRICT,
    CHECK (retention_state IN ('pinned', 'released'))
);

CREATE INDEX idx_knowledge_revision_sources_resource
    ON knowledge_revision_sources (tenant_id, resource_id);
CREATE INDEX idx_knowledge_revision_sources_pinned
    ON knowledge_revision_sources (resource_id)
    WHERE retention_state = 'pinned';

DO $$ BEGIN RAISE NOTICE '[Enterprise 000004] Immutable knowledge revision sources ready'; END $$;
