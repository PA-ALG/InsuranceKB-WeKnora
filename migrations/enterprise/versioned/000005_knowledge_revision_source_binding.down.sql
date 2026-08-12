ALTER TABLE knowledge_revision_sources
    DROP CONSTRAINT knowledge_revision_source_binding_state,
    DROP CONSTRAINT knowledge_revision_sources_pkey,
    ADD CONSTRAINT knowledge_revision_sources_pkey PRIMARY KEY (knowledge_id, parse_attempt),
    DROP CONSTRAINT knowledge_revision_sources_knowledge_attempt_key,
    DROP COLUMN binding_digest,
    DROP COLUMN immutable_locator,
    DROP COLUMN chunk_count,
    DROP COLUMN manifest_digest,
    DROP COLUMN manifest_algorithm,
    DROP COLUMN object_sha256,
    DROP COLUMN resource_handle;
