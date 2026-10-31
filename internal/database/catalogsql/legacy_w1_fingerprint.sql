WITH objects(present, exact) AS (
    VALUES
    (
        EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledges'
              AND column_name = 'current_parse_attempt'
        ),
        EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledges'
              AND column_name = 'current_parse_attempt'
              AND data_type = 'bigint' AND is_nullable = 'NO'
              AND column_default = '0'::text
        )
    ),
    (
        EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledges'
              AND column_name = 'file_sha256'
        ),
        EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledges'
              AND column_name = 'file_sha256'
              AND data_type = 'character varying' AND character_maximum_length = 64
              AND is_nullable = 'NO'
              AND column_default IN (
                  $default$''::character varying$default$,
                  $default$''::text$default$
              )
        )
    ),
    (
        EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'chunks'
              AND column_name = 'parse_attempt'
        ),
        EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'chunks'
              AND column_name = 'parse_attempt'
              AND data_type = 'bigint' AND is_nullable = 'NO'
              AND column_default = '0'::text
        )
    ),
    (
        to_regclass('public.knowledge_revisions') IS NOT NULL,
        to_regclass('public.knowledge_revisions') IS NOT NULL
        AND EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class t
            WHERE t.oid = to_regclass('public.knowledge_revisions')
              AND t.relkind = 'r'
        )
        AND (
            SELECT count(*) = 8
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
        )
        AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
              AND column_name = 'knowledge_id'
              AND data_type = 'character varying' AND character_maximum_length = 36
              AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
              AND column_name = 'parse_attempt'
              AND data_type = 'bigint' AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
              AND column_name = 'file_sha256'
              AND data_type = 'character varying' AND character_maximum_length = 64
              AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
              AND column_name = 'parser_identity'
              AND data_type = 'jsonb' AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
              AND column_name = 'manifest_algorithm'
              AND data_type = 'character varying' AND character_maximum_length = 64
              AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
              AND column_name = 'manifest_digest'
              AND data_type = 'character varying' AND character_maximum_length = 64
              AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
              AND column_name = 'chunk_count'
              AND data_type = 'integer' AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'knowledge_revisions'
              AND column_name = 'completed_at'
              AND data_type = 'timestamp without time zone'
              AND is_nullable = 'NO' AND column_default IS NULL
        )
        AND (
            SELECT count(*) = 6
               AND count(*) FILTER (WHERE c.contype = 'p') = 1
               AND count(*) FILTER (WHERE c.contype = 'f') = 1
               AND count(*) FILTER (WHERE c.contype = 'c') = 4
            FROM pg_catalog.pg_constraint c
            WHERE c.conrelid = to_regclass('public.knowledge_revisions')
        )
        -- PRIMARY KEY (knowledge_id, parse_attempt)
        AND EXISTS (
            SELECT 1
            FROM pg_catalog.pg_constraint c
            WHERE c.conrelid = to_regclass('public.knowledge_revisions')
              AND c.contype = 'p'
              AND c.convalidated AND NOT c.condeferrable
              AND pg_get_constraintdef(c.oid) = 'PRIMARY KEY (knowledge_id, parse_attempt)'
        )
        -- FOREIGN KEY (knowledge_id) REFERENCES knowledges(id) ON DELETE CASCADE
        AND EXISTS (
            SELECT 1
            FROM pg_catalog.pg_constraint c
            WHERE c.conrelid = to_regclass('public.knowledge_revisions')
              AND c.contype = 'f'
              AND c.confrelid = to_regclass('public.knowledges')
              AND c.confdeltype = 'c'
              AND c.convalidated AND NOT c.condeferrable
              AND pg_get_constraintdef(c.oid) =
                  'FOREIGN KEY (knowledge_id) REFERENCES knowledges(id) ON DELETE CASCADE'
        )
        -- CHECK (parse_attempt > 0), CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
        -- CHECK (manifest_digest ~ '^[0-9a-f]{64}$'), CHECK (chunk_count >= 0)
        AND (
            SELECT count(*) = 4
            FROM pg_catalog.pg_constraint c
            WHERE c.conrelid = to_regclass('public.knowledge_revisions')
              AND c.contype = 'c'
              AND c.convalidated AND NOT c.condeferrable
              AND regexp_replace(
                    pg_get_expr(c.conbin, c.conrelid),
                    '[[:space:]()]', '', 'g'
                  ) IN (
                    'parse_attempt>0',
                    'file_sha256::text~''^[0-9a-f]{64}$''::text',
                    'manifest_digest::text~''^[0-9a-f]{64}$''::text',
                    'chunk_count>=0'
                  )
            HAVING count(*) FILTER (
                       WHERE regexp_replace(
                           pg_get_expr(c.conbin, c.conrelid),
                           '[[:space:]()]', '', 'g'
                       ) = 'parse_attempt>0'
                   ) = 1
               AND count(*) FILTER (
                       WHERE regexp_replace(
                           pg_get_expr(c.conbin, c.conrelid),
                           '[[:space:]()]', '', 'g'
                       ) = 'file_sha256::text~''^[0-9a-f]{64}$''::text'
                   ) = 1
               AND count(*) FILTER (
                       WHERE regexp_replace(
                           pg_get_expr(c.conbin, c.conrelid),
                           '[[:space:]()]', '', 'g'
                       ) = 'manifest_digest::text~''^[0-9a-f]{64}$''::text'
                   ) = 1
               AND count(*) FILTER (
                       WHERE regexp_replace(
                           pg_get_expr(c.conbin, c.conrelid),
                           '[[:space:]()]', '', 'g'
                       ) = 'chunk_count>=0'
                   ) = 1
        )
    ),
    (
        to_regclass('public.idx_chunks_live_text_revision_ordinal') IS NOT NULL,
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_index i
            JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
            JOIN pg_catalog.pg_am am ON am.oid = idx.relam
            WHERE idx.oid = to_regclass('public.idx_chunks_live_text_revision_ordinal')
              AND i.indrelid = to_regclass('public.chunks')
              AND am.amname = 'btree'
              AND i.indisunique AND i.indisvalid AND i.indisready AND i.indislive
              AND i.indnkeyatts = 3 AND i.indnatts = 3
              AND ARRAY(
                    SELECT a.attname::text
                    FROM unnest(i.indkey::smallint[]) WITH ORDINALITY AS key(attnum, position)
                    JOIN pg_catalog.pg_attribute a
                      ON a.attrelid = i.indrelid AND a.attnum = key.attnum
                    ORDER BY key.position
                  ) = ARRAY['knowledge_id', 'parse_attempt', 'chunk_index']::text[]
              -- knowledge_id, parse_attempt, chunk_index
              AND regexp_replace(
                    pg_get_expr(i.indpred, i.indrelid),
                    '[[:space:]()]', '', 'g'
                  ) =
                  'deleted_atISNULLANDchunk_type::text=''text''::textANDparse_attempt>0'
              -- WHERE deleted_at IS NULL AND chunk_type = 'text' AND parse_attempt > 0
        )
    ),
    (
        to_regclass('public.idx_knowledge_revisions_completed') IS NOT NULL,
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_index i
            JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
            JOIN pg_catalog.pg_am am ON am.oid = idx.relam
            WHERE idx.oid = to_regclass('public.idx_knowledge_revisions_completed')
              AND i.indrelid = to_regclass('public.knowledge_revisions')
              AND am.amname = 'btree'
              AND NOT i.indisunique AND i.indisvalid AND i.indisready AND i.indislive
              AND i.indnkeyatts = 2 AND i.indnatts = 2
              AND i.indpred IS NULL
              AND ARRAY(
                    SELECT a.attname::text
                    FROM unnest(i.indkey::smallint[]) WITH ORDINALITY AS key(attnum, position)
                    JOIN pg_catalog.pg_attribute a
                      ON a.attrelid = i.indrelid AND a.attnum = key.attnum
                    ORDER BY key.position
                  ) = ARRAY['knowledge_id', 'completed_at']::text[]
              AND ARRAY(
                    SELECT (option::integer & 1)::smallint
                    FROM unnest(i.indoption::smallint[]) WITH ORDINALITY
                         AS ordering(option, position)
                    ORDER BY ordering.position
                  ) = ARRAY[0, 1]::smallint[]
              -- knowledge_id, completed_at DESC
        )
    )
)
SELECT
    count(*) FILTER (WHERE present),
    count(*) FILTER (WHERE exact)
FROM objects
