CREATE TABLE enterprise_release_sources (
    tenant_id BIGINT NOT NULL,
    space_id TEXT NOT NULL,
    release_id TEXT NOT NULL,
    knowledge_id VARCHAR(36) NOT NULL,
    parse_attempt BIGINT NOT NULL CHECK (parse_attempt > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (release_id, knowledge_id, parse_attempt)
);
CREATE INDEX idx_enterprise_release_sources_knowledge
    ON enterprise_release_sources (tenant_id, knowledge_id);

CREATE TABLE enterprise_release_retirements (
    release_id TEXT PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    space_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    subject TEXT NOT NULL,
    retired_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Only G3's sealed bindings remain fixed before a release actually cites them.
UPDATE knowledge_revision_sources
SET retention_state = 'released', released_at = now(), updated_at = now()
WHERE retention_state = 'pinned' AND binding_digest = '';
