-- Migration: 000077_remove_wiki_log (rollback)
-- Description: No-op. Migration 000077 preserves the former Wiki operation
--              log table and page bodies. It archives and soft-deletes legacy
--              log pages. Their original status is not recoverable from schema state;
--              restore the pre-upgrade database backup for an application
--              rollback.

DO $$ BEGIN RAISE NOTICE '[Migration 000077 DOWN] Frozen Wiki log history remains unchanged'; END $$;
