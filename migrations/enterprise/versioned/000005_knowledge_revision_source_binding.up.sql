DO $$ BEGIN RAISE NOTICE '[Enterprise 000005] Binding immutable revision source objects...'; END $$;

ALTER TABLE knowledge_revision_sources
    DROP CONSTRAINT knowledge_revision_sources_pkey,
    ADD COLUMN resource_handle VARCHAR(22) NOT NULL DEFAULT '',
    ADD COLUMN object_sha256 VARCHAR(64) NOT NULL DEFAULT '',
    ADD COLUMN manifest_algorithm VARCHAR(64) NOT NULL DEFAULT '',
    ADD COLUMN manifest_digest VARCHAR(64) NOT NULL DEFAULT '',
    ADD COLUMN chunk_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN immutable_locator TEXT NOT NULL DEFAULT '',
    ADD COLUMN binding_digest VARCHAR(64) NOT NULL DEFAULT '',
    ADD CONSTRAINT knowledge_revision_sources_pkey
        PRIMARY KEY (tenant_id, knowledge_id, parse_attempt),
    ADD CONSTRAINT knowledge_revision_sources_knowledge_attempt_key
        UNIQUE (knowledge_id, parse_attempt),
    ADD CONSTRAINT knowledge_revision_source_binding_state CHECK (
        (
            binding_digest = '' AND
            (resource_handle = '' OR object_sha256 = '' OR manifest_algorithm = '' OR
             manifest_digest = '' OR chunk_count = 0 OR immutable_locator = '' OR page_count IS NULL)
        ) OR (
            binding_digest ~ '^[0-9a-f]{64}$' AND
            resource_handle ~ '^[A-Za-z0-9_-]{22}$' AND
            object_sha256 ~ '^[0-9a-f]{64}$' AND
            manifest_algorithm = 'weknora.chunk_manifest.v1' AND
            manifest_digest ~ '^[0-9a-f]{64}$' AND
            chunk_count > 0 AND
            immutable_locator = 'resource://' || resource_handle AND
            page_count > 0 AND
            retention_state = 'pinned'
        )
    );

DO $$ BEGIN RAISE NOTICE '[Enterprise 000005] Immutable revision source binding ready'; END $$;
