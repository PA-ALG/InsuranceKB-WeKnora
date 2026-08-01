-- Deliberately conservative: this repair cannot distinguish a table created
-- here from a historical table that became populated after upgrade. Rolling
-- the enterprise ledger back must therefore preserve embeddings and its data.
DO $$
BEGIN
    RAISE NOTICE '[Enterprise 000003] conservative down migration preserves embeddings';
END $$;
