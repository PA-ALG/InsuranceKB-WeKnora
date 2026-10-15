-- Rollback of 000006: removes the enterprise candidate and decision records only.
-- Releases activated from them stay in wiki_release_* (immutable history).
DROP TABLE enterprise_decisions;
DROP TABLE enterprise_candidates;
