-- Migration: 000077_remove_wiki_log
-- Description: Retire the duplicate Wiki-only operation feed while preserving
--              its frozen audit rows. Knowledge-base activity is authoritative
--              for new mutations.

DO $$ BEGIN RAISE NOTICE '[Migration 000077] Freezing legacy Wiki operation log history'; END $$;

-- The v0.8.2 application no longer recognizes page_type='log' as a special
-- page. Archive and soft-delete legacy rows so both status-aware paths and
-- ordinary GORM reads exclude them. Identity and content stay intact for audit
-- and backup-based recovery.
UPDATE wiki_pages
SET status = 'archived',
    deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP)
WHERE page_type = 'log'
  AND (status <> 'archived' OR deleted_at IS NULL);

DO $$ BEGIN RAISE NOTICE '[Migration 000077] Legacy Wiki operation log history frozen'; END $$;
