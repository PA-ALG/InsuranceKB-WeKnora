SELECT
    to_regclass('public.knowledge_processing_spans') IS NOT NULL,
    COALESCE((
        SELECT relkind = 'r'
        FROM pg_catalog.pg_class
        WHERE oid = to_regclass('public.knowledge_processing_spans')
    ), false),
    EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'knowledge_processing_spans'
          AND column_name = 'name'
    ),
    COALESCE((
        SELECT data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'knowledge_processing_spans'
          AND column_name = 'name'
    ), ''),
    COALESCE((
        SELECT character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'knowledge_processing_spans'
          AND column_name = 'name'
    ), -1),
    COALESCE((
        SELECT is_nullable = 'NO'
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'knowledge_processing_spans'
          AND column_name = 'name'
    ), false),
    COALESCE((
        SELECT column_default IS NULL
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'knowledge_processing_spans'
          AND column_name = 'name'
    ), false)
