-- RV6b: a point approval and its immutable publication commit together.
CREATE TABLE enterprise_point_decisions (
    id TEXT PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    space_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL REFERENCES enterprise_candidates(id),
    slug TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('approve', 'reject')),
    reason TEXT NOT NULL,
    subject TEXT NOT NULL,
    release_id TEXT REFERENCES wiki_releases(release_id),
    created_at TIMESTAMPTZ NOT NULL,
    CHECK ((outcome = 'approve' AND release_id IS NOT NULL AND release_id <> '')
        OR (outcome = 'reject' AND release_id IS NULL)),
    UNIQUE (tenant_id, space_id, candidate_id, slug)
);
