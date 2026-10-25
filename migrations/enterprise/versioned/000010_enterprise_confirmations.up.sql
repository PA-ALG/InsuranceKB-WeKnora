-- Confirmation items are immutable once submitted; answers append with a database-owned order,
-- and an item closes once. The platform stores titles, details and options as opaque text.
CREATE TABLE enterprise_confirmations (
    id             TEXT PRIMARY KEY,
    tenant_id      BIGINT NOT NULL,
    space_id       TEXT NOT NULL,
    subject        TEXT NOT NULL,
    revision       TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    title          TEXT NOT NULL,
    detail         TEXT NOT NULL,
    options        JSONB NOT NULL,
    created_by     TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX enterprise_confirmations_identity_idx
    ON enterprise_confirmations (tenant_id, space_id, subject, revision, content_digest);

CREATE TABLE enterprise_confirmation_answers (
    id              TEXT PRIMARY KEY,
    seq             BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    tenant_id       BIGINT NOT NULL,
    space_id        TEXT NOT NULL,
    confirmation_id TEXT NOT NULL REFERENCES enterprise_confirmations(id),
    option_key      TEXT NOT NULL,
    note            TEXT NOT NULL,
    answerer        TEXT NOT NULL,
    answered_at     TIMESTAMPTZ NOT NULL
);

CREATE INDEX enterprise_confirmation_answers_item_seq_idx
    ON enterprise_confirmation_answers (confirmation_id, seq);

CREATE TABLE enterprise_confirmation_closures (
    confirmation_id TEXT PRIMARY KEY REFERENCES enterprise_confirmations(id),
    tenant_id       BIGINT NOT NULL,
    space_id        TEXT NOT NULL,
    reason          TEXT NOT NULL CHECK (reason IN ('applied', 'obsolete')),
    answer_id       TEXT REFERENCES enterprise_confirmation_answers(id),
    closed_by       TEXT NOT NULL,
    closed_at       TIMESTAMPTZ NOT NULL,
    CHECK ((reason = 'applied') = (answer_id IS NOT NULL))
);
