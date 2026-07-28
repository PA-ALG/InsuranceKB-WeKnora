DO $$ BEGIN RAISE NOTICE '[Migration 000001 down] Removing revision manifest contract...'; END $$;

DROP INDEX IF EXISTS idx_knowledge_revisions_completed;
DROP INDEX IF EXISTS idx_chunks_live_text_revision_ordinal;
DROP TABLE IF EXISTS knowledge_revisions;

ALTER TABLE chunks DROP COLUMN IF EXISTS parse_attempt;
ALTER TABLE knowledges DROP COLUMN IF EXISTS file_sha256;
ALTER TABLE knowledges DROP COLUMN IF EXISTS current_parse_attempt;

DO $$ BEGIN RAISE NOTICE '[Migration 000001 down] Revision manifest contract removed'; END $$;
