-- Frozen RED schema: old runtime can reach behavior assertions before migration13 exists.
ALTER TABLE wiki_releases ADD COLUMN member_storage TEXT NOT NULL DEFAULT '';
ALTER TABLE wiki_release_preparations ADD COLUMN member_storage TEXT NOT NULL DEFAULT '';
ALTER TABLE wiki_releases ADD UNIQUE(release_id,tenant_id,space_id,raw_kb_id,wiki_kb_id);
ALTER TABLE wiki_release_preparations ADD UNIQUE(preparation_id,tenant_id,space_id,raw_kb_id,wiki_kb_id);
CREATE TABLE enterprise_member_scopes (
 id BIGSERIAL PRIMARY KEY, tenant_id BIGINT NOT NULL, space_id TEXT NOT NULL,
 raw_kb_id TEXT NOT NULL, wiki_kb_id TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'bridge',
 observation_started_at TIMESTAMPTZ, read_failures BIGINT NOT NULL DEFAULT 0,
 UNIQUE(tenant_id,space_id,raw_kb_id,wiki_kb_id), UNIQUE(id,tenant_id,space_id,raw_kb_id,wiki_kb_id),
 CHECK(mode IN ('bridge','reference','legacy')), CHECK(read_failures>=0)
);
CREATE TABLE enterprise_member_contents (
 scope_id BIGINT NOT NULL REFERENCES enterprise_member_scopes(id), digest BYTEA NOT NULL,
 codec INTEGER NOT NULL, kind TEXT NOT NULL, logical_slug TEXT NOT NULL, revision_id TEXT NOT NULL,
 member_digest TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL, payload_json TEXT NOT NULL,
 PRIMARY KEY(scope_id,digest), CHECK(octet_length(digest)=32), CHECK(codec=1)
);
CREATE TABLE enterprise_member_chunks (
 scope_id BIGINT NOT NULL REFERENCES enterprise_member_scopes(id), digest BYTEA NOT NULL,
 codec INTEGER NOT NULL, count INTEGER NOT NULL, refs BYTEA NOT NULL,
 PRIMARY KEY(scope_id,digest), CHECK(octet_length(digest)=32), CHECK(codec=1),
 CHECK(count BETWEEN 1 AND 128), CHECK(octet_length(refs)=count*32)
);
CREATE TABLE enterprise_member_sets (
 scope_id BIGINT NOT NULL REFERENCES enterprise_member_scopes(id), digest BYTEA NOT NULL,
 codec INTEGER NOT NULL, order_mode TEXT NOT NULL, member_count BIGINT NOT NULL,
 chunk_count INTEGER NOT NULL, blocks BYTEA NOT NULL,
 PRIMARY KEY(scope_id,digest), CHECK(octet_length(digest)=32), CHECK(codec=1),
 CHECK(order_mode IN ('slug_asc','legacy_sequence')), CHECK(member_count>=0), CHECK(chunk_count>=0),
 CHECK(octet_length(blocks)=chunk_count*36)
);
CREATE TABLE enterprise_member_releases (
 release_id TEXT PRIMARY KEY, scope_id BIGINT NOT NULL, tenant_id BIGINT NOT NULL,
 space_id TEXT NOT NULL, raw_kb_id TEXT NOT NULL, wiki_kb_id TEXT NOT NULL,
 root_digest BYTEA NOT NULL, verified BOOLEAN NOT NULL,
 FOREIGN KEY(release_id,tenant_id,space_id,raw_kb_id,wiki_kb_id)
 REFERENCES wiki_releases(release_id,tenant_id,space_id,raw_kb_id,wiki_kb_id),
 FOREIGN KEY(scope_id,tenant_id,space_id,raw_kb_id,wiki_kb_id)
 REFERENCES enterprise_member_scopes(id,tenant_id,space_id,raw_kb_id,wiki_kb_id),
 FOREIGN KEY(scope_id,root_digest) REFERENCES enterprise_member_sets(scope_id,digest)
);
CREATE TABLE enterprise_member_preparations (
 preparation_id TEXT PRIMARY KEY, scope_id BIGINT NOT NULL, tenant_id BIGINT NOT NULL,
 space_id TEXT NOT NULL, raw_kb_id TEXT NOT NULL, wiki_kb_id TEXT NOT NULL,
 root_digest BYTEA NOT NULL, verified BOOLEAN NOT NULL,
 FOREIGN KEY(preparation_id,tenant_id,space_id,raw_kb_id,wiki_kb_id)
 REFERENCES wiki_release_preparations(preparation_id,tenant_id,space_id,raw_kb_id,wiki_kb_id),
 FOREIGN KEY(scope_id,tenant_id,space_id,raw_kb_id,wiki_kb_id)
 REFERENCES enterprise_member_scopes(id,tenant_id,space_id,raw_kb_id,wiki_kb_id),
 FOREIGN KEY(scope_id,root_digest) REFERENCES enterprise_member_sets(scope_id,digest)
);
CREATE TABLE enterprise_member_progress (
 release_id TEXT PRIMARY KEY REFERENCES wiki_releases(release_id), scope_id BIGINT NOT NULL
 REFERENCES enterprise_member_scopes(id), source_digest BYTEA NOT NULL,
 phase TEXT NOT NULL, source_bytes BIGINT NOT NULL, CHECK(octet_length(source_digest)=32),
 CHECK(phase IN ('staged','verified','restored')), CHECK(source_bytes>=0)
);

-- Independent operational journal: deliberately NO foreign keys to activation-locked rows.
-- Pending reservations survive failed terminal writes and caller transaction rollback.
CREATE TABLE enterprise_member_validation_pending (
 tenant_id BIGINT NOT NULL, space_id TEXT NOT NULL, raw_kb_id TEXT NOT NULL, wiki_kb_id TEXT NOT NULL,
 attempt_id TEXT PRIMARY KEY, started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX enterprise_member_validation_pending_scope ON enterprise_member_validation_pending
 (tenant_id,space_id,raw_kb_id,wiki_kb_id);
CREATE TABLE enterprise_member_validation_failures (
 tenant_id BIGINT NOT NULL, space_id TEXT NOT NULL, raw_kb_id TEXT NOT NULL, wiki_kb_id TEXT NOT NULL,
 attempt_id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('integrity','gap','probe')),
 recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX enterprise_member_validation_failures_scope ON enterprise_member_validation_failures
 (tenant_id,space_id,raw_kb_id,wiki_kb_id,recorded_at) WHERE kind<>'probe';
