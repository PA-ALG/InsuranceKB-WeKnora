-- Static pre-provider-cap-sidecar schema-v7 overlay copied from aggregate HEAD 5fa17d96.
-- Apply after a_v5_budget_schema.sql; this does not execute current BudgetLedger migration code.

DROP TABLE infrastructure_reserves;
DROP TABLE infrastructure_authorizations;

CREATE TABLE infrastructure_authorizations (
    authorization_digest TEXT PRIMARY KEY,
    domain TEXT NOT NULL CHECK (domain =
        'insurancekb.run-admission.provisioning.v1'
    ),
    envelope_json BLOB NOT NULL UNIQUE,
    run_identity TEXT NOT NULL,
    purpose TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    reserve_id TEXT NOT NULL UNIQUE,
    recorded_at TEXT NOT NULL,
    UNIQUE (run_identity, purpose, operation_id)
);

CREATE TABLE infrastructure_reserves (
    reserve_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    run_identity TEXT NOT NULL,
    purpose TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    authorization_digest TEXT NOT NULL UNIQUE
        REFERENCES infrastructure_authorizations(authorization_digest),
    pricing_evidence_digest TEXT NOT NULL,
    pricing_approval_digest TEXT NOT NULL,
    provider_cap_evidence_digest TEXT NOT NULL,
    provider_cap_approval_digest TEXT NOT NULL,
    provider_cap_max_cost INTEGER NOT NULL CHECK (provider_cap_max_cost > 0),
    provider_cap_expires_at TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider='bailian'),
    currency TEXT NOT NULL CHECK (currency='CNY'),
    workspace_ref TEXT NOT NULL,
    project_ref TEXT NOT NULL,
    credential_ref TEXT NOT NULL,
    region TEXT NOT NULL,
    base_model TEXT NOT NULL,
    request_plan TEXT NOT NULL CHECK (request_plan='ptu_v2'),
    receipt_plan TEXT NOT NULL CHECK (receipt_plan='ptu'),
    input_tpm_quota INTEGER NOT NULL CHECK (input_tpm_quota=10000),
    output_tpm_quota INTEGER NOT NULL CHECK (output_tpm_quota=1000),
    covers_fixed_infrastructure INTEGER NOT NULL CHECK (covers_fixed_infrastructure=1),
    covers_inference INTEGER NOT NULL CHECK (covers_inference=1),
    cleanup_deadline TEXT NOT NULL,
    max_cost INTEGER NOT NULL CHECK (max_cost > 0),
    state TEXT NOT NULL CHECK (state IN ('reserved','bound')),
    deployed_model TEXT UNIQUE,
    receipt_digest TEXT UNIQUE,
    remote_manifest_digest TEXT UNIQUE,
    receipt_json BLOB,
    final_approval_digest TEXT,
    created_at TEXT NOT NULL,
    bound_at TEXT,
    UNIQUE (account_id, operation_id),
    CHECK ((state='reserved' AND deployed_model IS NULL AND receipt_digest IS NULL
            AND remote_manifest_digest IS NULL
            AND receipt_json IS NULL AND final_approval_digest IS NULL AND bound_at IS NULL)
        OR (state='bound' AND deployed_model IS NOT NULL AND receipt_digest IS NOT NULL
            AND remote_manifest_digest IS NOT NULL
            AND receipt_json IS NOT NULL AND final_approval_digest IS NOT NULL
            AND bound_at IS NOT NULL))
);

CREATE TABLE deployment_role_bindings (
    account_id TEXT NOT NULL REFERENCES budget_accounts(account_id),
    role TEXT NOT NULL CHECK (role IN ('annotator','weak_extractor','judge')),
    reserve_id TEXT NOT NULL REFERENCES infrastructure_reserves(reserve_id),
    PRIMARY KEY (account_id, role)
);

CREATE TABLE final_infrastructure_topologies (
    account_id TEXT PRIMARY KEY REFERENCES budget_accounts(account_id),
    strong_reserve_id TEXT NOT NULL UNIQUE REFERENCES infrastructure_reserves(reserve_id),
    weak_reserve_id TEXT NOT NULL UNIQUE REFERENCES infrastructure_reserves(reserve_id),
    topology_json BLOB NOT NULL UNIQUE,
    topology_digest TEXT NOT NULL UNIQUE,
    recorded_at TEXT NOT NULL,
    CHECK (strong_reserve_id != weak_reserve_id)
);

CREATE TABLE final_topology_receipt_annexes (
    annex_digest TEXT PRIMARY KEY,
    reserve_id TEXT NOT NULL UNIQUE REFERENCES infrastructure_reserves(reserve_id),
    receipt_digest TEXT NOT NULL UNIQUE,
    artifact_json BLOB NOT NULL UNIQUE,
    recorded_at TEXT NOT NULL
);

INSERT INTO infrastructure_authorizations VALUES (
    '1111111111111111111111111111111111111111111111111111111111111111',
    'insurancekb.run-admission.provisioning.v1',
    X'7B226C6567616379223A22617574686F72697A6174696F6E227D',
    'golden-v01-run-031',
    'golden-v0.1 production run',
    'op-pre-sidecar-v7-031',
    'infra-pre-sidecar-v7-031',
    '2026-07-21T08:00:00+00:00'
);

INSERT INTO infrastructure_reserves VALUES (
    'infra-pre-sidecar-v7-031',
    '697b5006da9d1c4c12e933028f795259d93ce698dd1ac4c70f2e45d746f1cc88',
    'golden-v01-run-031',
    'golden-v0.1 production run',
    'op-pre-sidecar-v7-031',
    '1111111111111111111111111111111111111111111111111111111111111111',
    '2222222222222222222222222222222222222222222222222222222222222222',
    '3333333333333333333333333333333333333333333333333333333333333333',
    '4444444444444444444444444444444444444444444444444444444444444444',
    '5555555555555555555555555555555555555555555555555555555555555555',
    10000,
    '2026-07-21T09:00:00+00:00',
    'bailian',
    'CNY',
    'workspace-pre-sidecar-v7-031',
    'sha256:6666666666666666666666666666666666666666666666666666666666666666',
    'sha256:7777777777777777777777777777777777777777777777777777777777777777',
    'cn-beijing',
    'qwen3.7-plus-2026-05-26',
    'ptu_v2',
    'ptu',
    10000,
    1000,
    1,
    1,
    '2026-07-21T16:00:00+00:00',
    6720,
    'reserved',
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    '2026-07-21T08:00:00+00:00',
    NULL
);

PRAGMA user_version = 7;
