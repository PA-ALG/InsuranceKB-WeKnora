-- Published-member samples are immutable; verdicts append with a database-owned
-- order, independent of reviewer clocks or caller-generated identifiers.
CREATE TABLE enterprise_samples (
    id            TEXT PRIMARY KEY,
    tenant_id     BIGINT NOT NULL,
    space_id      TEXT NOT NULL,
    release_id    TEXT NOT NULL,
    logical_slug  TEXT NOT NULL,
    member_digest TEXT NOT NULL,
    stratum       TEXT NOT NULL,
    created_by    TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX enterprise_samples_identity_idx
    ON enterprise_samples (tenant_id, space_id, release_id, logical_slug);

CREATE TABLE enterprise_sample_verdicts (
    id         TEXT PRIMARY KEY,
    seq        BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    tenant_id  BIGINT NOT NULL,
    space_id   TEXT NOT NULL,
    sample_id  TEXT NOT NULL REFERENCES enterprise_samples(id),
    outcome    TEXT NOT NULL CHECK (outcome IN ('correct', 'incomplete', 'wrong')),
    note       TEXT NOT NULL,
    reviewer   TEXT NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX enterprise_sample_verdicts_sample_seq_idx
    ON enterprise_sample_verdicts (sample_id, seq);
