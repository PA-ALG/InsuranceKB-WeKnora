-- Expert revisions of published claims (S9a). Records are immutable: rows are inserted
-- once and never updated or deleted; a published claim cites its record by id and digest.
CREATE TABLE enterprise_expert_revisions (
    id                 TEXT PRIMARY KEY,
    tenant_id          BIGINT NOT NULL,
    space_id           TEXT NOT NULL,
    base_release_id    TEXT NOT NULL,
    member_slug        TEXT NOT NULL,
    base_member_digest TEXT NOT NULL,
    actor              TEXT NOT NULL,
    role               TEXT NOT NULL,
    recorded_at        TIMESTAMPTZ NOT NULL,
    before_json        TEXT NOT NULL,
    after_json         TEXT NOT NULL,
    reason             TEXT NOT NULL,
    record_sha256      TEXT NOT NULL
);

CREATE INDEX enterprise_expert_revisions_member_idx
    ON enterprise_expert_revisions (tenant_id, space_id, member_slug, recorded_at);
