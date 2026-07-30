CREATE TABLE wiki_release_preparations (
    preparation_id TEXT PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    space_id TEXT NOT NULL,
    raw_kb_id TEXT NOT NULL,
    wiki_kb_id TEXT NOT NULL,
    candidate_digest TEXT NOT NULL,
    manifest_digest TEXT NOT NULL,
    ready_receipt_digest TEXT NOT NULL,
    review_decision_digest TEXT NOT NULL,
    review_policy_id TEXT NOT NULL,
    expected_release_id TEXT NOT NULL,
    expected_activation_epoch BIGINT NOT NULL,
    status TEXT NOT NULL,
    manifest JSONB NOT NULL,
    members JSONB NOT NULL,
    preparation_digest TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX wiki_release_preparations_digest_idx
    ON wiki_release_preparations (preparation_digest);

CREATE TABLE wiki_releases (
    release_id TEXT PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    space_id TEXT NOT NULL,
    raw_kb_id TEXT NOT NULL,
    wiki_kb_id TEXT NOT NULL,
    candidate_digest TEXT NOT NULL,
    manifest_digest TEXT NOT NULL,
    base_release_id TEXT NOT NULL,
    base_activation_epoch BIGINT NOT NULL,
    preparation_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    activated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX wiki_releases_manifest_idx
    ON wiki_releases (tenant_id, space_id, wiki_kb_id, manifest_digest);

CREATE TABLE wiki_release_members (
    id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL REFERENCES wiki_releases(release_id),
    kind TEXT NOT NULL,
    logical_slug TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    member_digest TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    payload JSONB NOT NULL
);

CREATE UNIQUE INDEX wiki_release_members_identity_idx
    ON wiki_release_members (release_id, logical_slug);

CREATE TABLE wiki_release_heads (
    id TEXT PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    space_id TEXT NOT NULL,
    raw_kb_id TEXT NOT NULL,
    wiki_kb_id TEXT NOT NULL,
    active_release_id TEXT NOT NULL REFERENCES wiki_releases(release_id),
    activation_epoch BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX wiki_release_heads_scope_idx
    ON wiki_release_heads (tenant_id, space_id);

CREATE TABLE wiki_release_receipts (
    receipt_id TEXT PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    space_id TEXT NOT NULL,
    raw_kb_id TEXT NOT NULL,
    wiki_kb_id TEXT NOT NULL,
    nonce TEXT NOT NULL,
    authorization_digest TEXT NOT NULL,
    previous_release_id TEXT NOT NULL,
    release_id TEXT NOT NULL REFERENCES wiki_releases(release_id),
    activation_epoch BIGINT NOT NULL,
    activated_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX wiki_release_receipts_nonce_idx
    ON wiki_release_receipts (space_id, wiki_kb_id, nonce);
