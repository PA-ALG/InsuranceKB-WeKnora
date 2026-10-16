DROP TABLE enterprise_release_retirements;
DROP TABLE enterprise_release_sources;

-- Conservative rollback restores the previous commit-time retention policy.
UPDATE knowledge_revision_sources
SET retention_state = 'pinned', released_at = NULL, updated_at = now()
WHERE retention_state = 'released' AND binding_digest = '';
