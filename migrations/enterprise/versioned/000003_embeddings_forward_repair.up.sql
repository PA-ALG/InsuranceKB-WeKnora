-- Forward repair for deployments that advanced the official ledger while
-- app.skip_embedding=true and later enabled PostgreSQL retrieval.
DO $$
BEGIN
    IF current_setting('app.skip_embedding', true) IS DISTINCT FROM 'false' THEN
        RAISE NOTICE '[Enterprise 000003] PostgreSQL retrieval is not active; skipping embeddings repair';
        RETURN;
    END IF;

    IF to_regclass('public.embeddings') IS NOT NULL THEN
        IF NOT (
            WITH required_columns(name, data_type, not_null) AS (
                VALUES
                    ('id', 'integer', true),
                    ('created_at', 'timestamp with time zone', false),
                    ('updated_at', 'timestamp with time zone', false),
                    ('source_id', 'character varying(64)', true),
                    ('source_type', 'integer', true),
                    ('chunk_id', 'character varying(64)', false),
                    ('knowledge_id', 'character varying(64)', false),
                    ('knowledge_base_id', 'character varying(64)', false),
                    ('content', 'text', false),
                    ('dimension', 'integer', true),
                    ('embedding', 'halfvec', false),
                    ('is_enabled', 'boolean', false),
                    ('tag_id', 'character varying(36)', false)
            ), actual_columns AS (
                SELECT
                    attribute.attname AS name,
                    format_type(attribute.atttypid, attribute.atttypmod) AS data_type,
                    attribute.attnotnull AS not_null
                FROM pg_attribute AS attribute
                WHERE attribute.attrelid = 'public.embeddings'::regclass
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
            ), required_indexes(name, access_method, must_be_unique, must_be_primary) AS (
                VALUES
                    ('embeddings_pkey', 'btree', true, true),
                    ('embeddings_unique_source', 'btree', true, false),
                    ('embeddings_search_idx', 'bm25', false, false),
                    ('embeddings_embedding_idx_3584', 'hnsw', false, false),
                    ('embeddings_embedding_idx_798', 'hnsw', false, false),
                    ('embeddings_embedding_idx_1024', 'hnsw', false, false),
                    ('idx_embeddings_is_enabled', 'btree', false, false),
                    ('idx_embeddings_knowledge_base_id', 'btree', false, false),
                    ('idx_embeddings_tag_id', 'btree', false, false)
            ), actual_indexes AS (
                SELECT
                    index_class.relname AS name,
                    access_method.amname AS access_method,
                    index_row.indisunique AS is_unique,
                    index_row.indisprimary AS is_primary
                FROM pg_index AS index_row
                JOIN pg_class AS index_class ON index_class.oid = index_row.indexrelid
                JOIN pg_namespace AS namespace ON namespace.oid = index_class.relnamespace
                JOIN pg_am AS access_method ON access_method.oid = index_class.relam
                WHERE index_row.indrelid = 'public.embeddings'::regclass
                  AND namespace.nspname = 'public'
            )
            SELECT
                NOT EXISTS (
                    SELECT 1
                    FROM required_columns AS required
                    LEFT JOIN actual_columns AS actual USING (name)
                    WHERE actual.name IS NULL
                       OR actual.data_type <> required.data_type
                       OR actual.not_null <> required.not_null
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM required_indexes AS required
                    LEFT JOIN actual_indexes AS actual USING (name)
                    WHERE actual.name IS NULL
                       OR actual.access_method <> required.access_method
                       OR actual.is_unique <> required.must_be_unique
                       OR actual.is_primary <> required.must_be_primary
                )
        ) THEN
            RAISE EXCEPTION USING
                ERRCODE = '55000',
                MESSAGE = 'existing public.embeddings does not satisfy the current PostgreSQL repository contract';
        END IF;
        RAISE NOTICE '[Enterprise 000003] healthy embeddings already exists; preserving it unchanged';
        RETURN;
    END IF;

    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE EXTENSION IF NOT EXISTS pg_search;

    CREATE TABLE embeddings (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        source_id VARCHAR(64) NOT NULL,
        source_type INTEGER NOT NULL,
        chunk_id VARCHAR(64),
        knowledge_id VARCHAR(64),
        knowledge_base_id VARCHAR(64),
        content TEXT,
        dimension INTEGER NOT NULL,
        embedding halfvec,
        is_enabled BOOLEAN DEFAULT TRUE,
        tag_id VARCHAR(36)
    );

    CREATE UNIQUE INDEX embeddings_unique_source
        ON embeddings(source_id, source_type);
    CREATE INDEX embeddings_search_idx ON embeddings
        USING bm25 (id, knowledge_base_id, content, knowledge_id, chunk_id)
        WITH (
            key_field = 'id',
            text_fields = '{
                "content": {
                  "tokenizer": {"type": "chinese_lindera"}
                }
            }'
        );
    CREATE INDEX embeddings_embedding_idx_3584 ON embeddings
        USING hnsw ((embedding::halfvec(3584)) halfvec_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        WHERE (dimension = 3584);
    CREATE INDEX embeddings_embedding_idx_798 ON embeddings
        USING hnsw ((embedding::halfvec(798)) halfvec_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        WHERE (dimension = 798);
    CREATE INDEX embeddings_embedding_idx_1024 ON embeddings
        USING hnsw ((embedding::halfvec(1024)) halfvec_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        WHERE (dimension = 1024);
    CREATE INDEX idx_embeddings_is_enabled ON embeddings(is_enabled);
    CREATE INDEX idx_embeddings_knowledge_base_id ON embeddings(knowledge_base_id);
    CREATE INDEX idx_embeddings_tag_id ON embeddings(tag_id);
END $$;
