WITH objects(present, exact) AS (
    VALUES
    (
        to_regclass('public.knowledges') IS NOT NULL,
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class t
            WHERE t.oid = to_regclass('public.knowledges')
              AND t.relkind = 'r'
        )
        AND EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledges'
              AND column_name = 'id'
              AND data_type = 'character varying' AND character_maximum_length = 36
              AND is_nullable = 'NO'
        )
        -- PRIMARY KEY (id), so knowledge_revisions.knowledge_id can reference it.
        AND EXISTS (
            SELECT 1
            FROM pg_catalog.pg_constraint c
            WHERE c.conrelid = to_regclass('public.knowledges')
              AND c.contype = 'p'
              AND c.convalidated AND NOT c.condeferrable
              AND pg_get_constraintdef(c.oid) = 'PRIMARY KEY (id)'
        )
    ),
    (
        to_regclass('public.chunks') IS NOT NULL,
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class t
            WHERE t.oid = to_regclass('public.chunks')
              AND t.relkind = 'r'
        )
        AND EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'chunks'
              AND column_name = 'knowledge_id'
              AND data_type = 'character varying' AND character_maximum_length = 36
              AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'chunks'
              AND column_name = 'chunk_index'
              AND data_type = 'integer' AND is_nullable = 'NO'
              AND column_default IS NULL
        )
        -- chunk_type VARCHAR(20) NOT NULL DEFAULT 'text'
        AND EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'chunks'
              AND column_name = 'chunk_type'
              AND data_type = 'character varying' AND character_maximum_length = 20
              AND is_nullable = 'NO'
              AND column_default IN (
                  $default$'text'::character varying$default$,
                  $default$'text'::text$default$
              )
        )
        AND EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'chunks'
              AND column_name = 'deleted_at'
              AND data_type = 'timestamp with time zone'
              AND is_nullable = 'YES' AND column_default IS NULL
        )
    )
)
SELECT
    count(*) FILTER (WHERE present),
    count(*) FILTER (WHERE exact)
FROM objects
