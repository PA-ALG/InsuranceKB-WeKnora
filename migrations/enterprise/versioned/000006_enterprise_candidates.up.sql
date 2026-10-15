-- S4c-2a: generic candidate bundles and review decisions of the enterprise release path.
-- Bundles keep their exact submitted bytes (BYTEA), never JSONB, because the bundle digest
-- binds those bytes. Releases themselves reuse the wiki_release_* tables of 000002.
CREATE TABLE enterprise_candidates (
    id               TEXT PRIMARY KEY,
    tenant_id        BIGINT NOT NULL,
    space_id         TEXT NOT NULL,
    bundle_digest    TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    base_release_id  TEXT NOT NULL,
    raw_bundle       BYTEA NOT NULL,
    created_by       TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX enterprise_candidates_digest_idx
    ON enterprise_candidates (tenant_id, space_id, bundle_digest);

CREATE TABLE enterprise_decisions (
    id            TEXT PRIMARY KEY,
    tenant_id     BIGINT NOT NULL,
    space_id      TEXT NOT NULL,
    candidate_id  TEXT NOT NULL REFERENCES enterprise_candidates(id),
    bundle_digest TEXT NOT NULL,
    digest        TEXT NOT NULL,
    outcome       TEXT NOT NULL CHECK (outcome IN ('approve', 'reject', 'manual')),
    mode          TEXT NOT NULL CHECK (mode IN ('machine', 'human')),
    policy_ref    TEXT NOT NULL,
    score         TEXT NOT NULL,
    reason        TEXT NOT NULL,
    subject       TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX enterprise_decisions_digest_idx
    ON enterprise_decisions (tenant_id, space_id, digest);
