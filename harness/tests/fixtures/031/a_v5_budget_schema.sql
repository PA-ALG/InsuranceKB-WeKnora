-- Fixed schema fixture copied from admission_budget.py at commit 4f282589.
-- This is the complete schema created for a fresh schema-v5 BudgetLedger.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS budget_accounts (
    account_id TEXT PRIMARY KEY,
    run_identity TEXT NOT NULL,
    purpose TEXT NOT NULL,
    currency TEXT NOT NULL,
    ceiling_input INTEGER NOT NULL CHECK (ceiling_input >= 0),
    ceiling_output INTEGER NOT NULL CHECK (ceiling_output >= 0),
    ceiling_cost INTEGER NOT NULL CHECK (ceiling_cost >= 0),
    current_revision INTEGER NOT NULL CHECK (current_revision >= 1),
    approval_digest TEXT NOT NULL UNIQUE,
    overage INTEGER NOT NULL DEFAULT 0 CHECK (overage IN (0, 1)),
    UNIQUE (run_identity, purpose)
);

CREATE TABLE IF NOT EXISTS budget_approvals (
    account_id TEXT NOT NULL REFERENCES budget_accounts(account_id),
    revision INTEGER NOT NULL,
    approval_digest TEXT NOT NULL UNIQUE,
    previous_digest TEXT,
    plan_payload_hash TEXT NOT NULL,
    contract_hash TEXT NOT NULL,
    contract_json BLOB NOT NULL,
    ceiling_input INTEGER NOT NULL,
    ceiling_output INTEGER NOT NULL,
    ceiling_cost INTEGER NOT NULL,
    PRIMARY KEY (account_id, revision)
);

CREATE TABLE IF NOT EXISTS product_limits (
    account_id TEXT NOT NULL REFERENCES budget_accounts(account_id),
    stage TEXT NOT NULL,
    product_id TEXT NOT NULL,
    max_input INTEGER NOT NULL,
    max_output INTEGER NOT NULL,
    max_cost INTEGER NOT NULL,
    PRIMARY KEY (account_id, stage, product_id)
);

CREATE TABLE IF NOT EXISTS request_limits (
    account_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    product_id TEXT NOT NULL,
    request_unit TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('annotator','weak_extractor','judge')),
    max_input INTEGER NOT NULL,
    max_output INTEGER NOT NULL,
    max_cost INTEGER NOT NULL,
    PRIMARY KEY (account_id, stage, product_id, request_unit),
    FOREIGN KEY (account_id, stage, product_id)
        REFERENCES product_limits(account_id, stage, product_id)
);

CREATE TABLE IF NOT EXISTS product_reservations (
    account_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    product_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('reserved','settled','released')),
    max_input INTEGER NOT NULL,
    max_output INTEGER NOT NULL,
    max_cost INTEGER NOT NULL,
    actual_input INTEGER NOT NULL DEFAULT 0,
    actual_output INTEGER NOT NULL DEFAULT 0,
    actual_cost INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (account_id, stage, product_id),
    FOREIGN KEY (account_id, stage, product_id)
        REFERENCES product_limits(account_id, stage, product_id)
);

CREATE TABLE request_attempts (
    account_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    product_id TEXT NOT NULL,
    request_unit TEXT NOT NULL,
    attempt_no INTEGER NOT NULL CHECK (attempt_no >= 1),
    owner_token_digest TEXT NOT NULL,
    role TEXT NOT NULL CHECK (
        role IN ('annotator','weak_extractor','judge')
    ),
    limit_kind TEXT NOT NULL CHECK (limit_kind IN ('exact','pool')),
    state TEXT NOT NULL CHECK (
        state IN ('prepared','sent','terminal','uncertain','no_usage')
    ),
    max_input INTEGER NOT NULL,
    max_output INTEGER NOT NULL,
    max_cost INTEGER NOT NULL,
    actual_input INTEGER NOT NULL DEFAULT 0,
    actual_output INTEGER NOT NULL DEFAULT 0,
    actual_cost INTEGER NOT NULL DEFAULT 0,
    charged_input INTEGER NOT NULL DEFAULT 0,
    charged_output INTEGER NOT NULL DEFAULT 0,
    charged_cost INTEGER NOT NULL DEFAULT 0,
    response_digest TEXT,
    usage_verified INTEGER NOT NULL DEFAULT 0 CHECK (
        usage_verified IN (0, 1)
    ),
    provider_proof_digest TEXT,
    provider_request_id TEXT,
    provider_verifier_policy TEXT,
    provider_proof_observed_at TEXT,
    PRIMARY KEY (
        account_id, stage, product_id, request_unit, attempt_no
    ),
    FOREIGN KEY (account_id, stage, product_id)
        REFERENCES product_reservations(account_id, stage, product_id)
);

CREATE TABLE request_pool_limits (
    account_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    product_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (
        role IN ('annotator','weak_extractor','judge')
    ),
    max_attempts INTEGER NOT NULL CHECK (max_attempts >= 1),
    max_input INTEGER NOT NULL,
    max_output INTEGER NOT NULL,
    max_cost INTEGER NOT NULL,
    model_role_identity_hash TEXT NOT NULL,
    role_rate_digest TEXT NOT NULL,
    PRIMARY KEY (account_id, stage, product_id, role),
    FOREIGN KEY (account_id, stage, product_id)
        REFERENCES product_limits(account_id, stage, product_id)
);

CREATE TABLE canary_capability_claims (
    account_id TEXT NOT NULL REFERENCES budget_accounts(account_id),
    capability_digest TEXT NOT NULL,
    canary_stage TEXT NOT NULL,
    canary_product_id TEXT NOT NULL,
    settlement_digest TEXT NOT NULL,
    budget_revision INTEGER NOT NULL CHECK (budget_revision >= 1),
    approval_digest TEXT NOT NULL,
    target_stage TEXT NOT NULL,
    target_product_id TEXT NOT NULL,
    target_max_input INTEGER NOT NULL CHECK (target_max_input >= 0),
    target_max_output INTEGER NOT NULL CHECK (target_max_output >= 0),
    target_max_cost INTEGER NOT NULL CHECK (target_max_cost >= 0),
    PRIMARY KEY (
        account_id, capability_digest, target_stage, target_product_id
    ),
    FOREIGN KEY (account_id, canary_stage, canary_product_id)
        REFERENCES product_limits(account_id, stage, product_id),
    FOREIGN KEY (account_id, target_stage, target_product_id)
        REFERENCES product_limits(account_id, stage, product_id)
);

CREATE TABLE infrastructure_authorizations (
    authorization_digest TEXT PRIMARY KEY,
    domain TEXT NOT NULL CHECK (domain='insurancekb.run-admission.provisioning.v1'),
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
    state TEXT NOT NULL CHECK (state='reserved'),
    created_at TEXT NOT NULL,
    UNIQUE (account_id, operation_id)
);

PRAGMA user_version = 5;
