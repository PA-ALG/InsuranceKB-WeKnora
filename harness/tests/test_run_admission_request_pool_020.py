"""OpenSpec 020 D1.3a/D1.3b/D1.3c/D1.5: signed dynamic request pools."""

from __future__ import annotations

import base64
import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Lock, Thread
from typing import Literal

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from insurance_harness.goldenset.admission_budget import (
    AccountSnapshot,
    BudgetAmounts,
    BudgetContract,
    BudgetLedger,
    BudgetLedgerError,
    ProductReserve,
    ProviderSpendCapAttestation,
    RequestPoolReserve,
    RequestReserve,
    RoleRate,
    SendPermit,
    budget_contract_hash,
    model_role_budget_identity_hash,
)
from insurance_harness.goldenset.admission_models import (
    BudgetApprovalEntry,
    BudgetApprovalEnvelope,
    BudgetApprovalPayload,
    ModelRolePlan,
    RunAdmissionPlanPayload,
    approval_signed_bytes,
    plan_payload_hash,
)

_NOW = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
_RUN = "gs-v0.1-request-pool-test"
_PURPOSE = "gs-v0.1-baseline"
_SCOPE = "budget:gs-v0.1"
_STAGE = "extraction"
_PRODUCT = "product-01"
type _Role = Literal["annotator", "weak_extractor", "judge"]


def _amounts(
    input_tokens: int = 700,
    output_tokens: int = 300,
    cost_minor_units: int = 80,
) -> BudgetAmounts:
    return BudgetAmounts(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_minor_units=cost_minor_units,
    )


def _roles() -> dict[str, ModelRolePlan]:
    return {
        role: ModelRolePlan(
            provider="bailian",
            model_id=f"{role}-deployment",
            expected_model_revision="2026-07-20T08:00:00Z",
            protocol="https",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            provider_policy="bailian-deployment-detail-v1",
            credential_env_name="HARNESS_DASHSCOPE_API_KEY",
        )
        for role in ("annotator", "weak_extractor", "judge")
    }


def _rates(
    roles: dict[str, ModelRolePlan],
    *,
    weak_input_rate: int = 10,
) -> dict[str, RoleRate]:
    return {
        role: RoleRate(
            model_role_identity_hash=model_role_budget_identity_hash(role_plan),
            input_cost_per_million_minor_units=(
                weak_input_rate if role == "weak_extractor" else 10
            ),
            output_cost_per_million_minor_units=20,
        )
        for role, role_plan in roles.items()
    }


def _pool(
    *,
    role: _Role = "weak_extractor",
    max_attempts: int = 3,
    maximum: BudgetAmounts | None = None,
) -> RequestPoolReserve:
    return RequestPoolReserve(
        role=role,
        max_attempts=max_attempts,
        per_attempt_maximum=maximum or _amounts(),
    )


def _contract(
    *,
    request_reserves: tuple[RequestReserve, ...] = (),
    request_pools: tuple[RequestPoolReserve, ...] | None = None,
    product_maximum: BudgetAmounts | None = None,
    weak_input_rate: int = 10,
) -> BudgetContract:
    roles = _roles()
    pools = request_pools if request_pools is not None else (_pool(),)
    product_max = product_maximum or _amounts(10_000, 5_000, 1_000)
    return BudgetContract(
        currency="CNY",
        price_snapshot_id="bailian-pricing-20260720",
        price_observed_at=_NOW - timedelta(minutes=1),
        price_expires_at=_NOW + timedelta(hours=1),
        ceiling=_amounts(20_000, 10_000, 2_000),
        role_rates=_rates(roles, weak_input_rate=weak_input_rate),
        provider_attestation=ProviderSpendCapAttestation(
            provider="bailian",
            project_ref="sha256:" + "a" * 64,
            credential_ref="sha256:" + "b" * 64,
            max_cost_minor_units=2_000,
            observed_at=_NOW - timedelta(minutes=1),
            expires_at=_NOW + timedelta(hours=1),
            evidence_digest="e" * 64,
        ),
        product_reserves=(
            ProductReserve(
                stage=_STAGE,
                product_id=_PRODUCT,
                maximum=product_max,
                request_reserves=request_reserves,
                request_pools=pools,
            ),
        ),
    )


def _plan(contract: BudgetContract) -> RunAdmissionPlanPayload:
    return RunAdmissionPlanPayload(
        run_identity=_RUN,
        purpose=_PURPOSE,
        model_roles=_roles(),
        budget_contract_hash=budget_contract_hash(contract),
    )


def _envelope(
    private_key: Ed25519PrivateKey,
    contract: BudgetContract,
    plan: RunAdmissionPlanPayload,
    *,
    revision: int = 1,
    previous_digest: str | None = None,
) -> BudgetApprovalEnvelope:
    ceiling = contract.ceiling
    payload = BudgetApprovalPayload(
        plan_payload_hash=plan_payload_hash(plan),
        run_identity=plan.run_identity,
        purpose=plan.purpose,
        scope=_SCOPE,
        approver_identity="finance-owner@example.com",
        approver_role="budget_approver",
        issued_at=_NOW - timedelta(minutes=1),
        expires_at=_NOW + timedelta(hours=1),
        revision=revision,
        previous_approval_digest=previous_digest,
        budget_entries=(
            BudgetApprovalEntry(
                currency=contract.currency,
                max_input_tokens=ceiling.input_tokens,
                max_output_tokens=ceiling.output_tokens,
                max_cost_minor_units=ceiling.cost_minor_units,
                budget_contract_hash=budget_contract_hash(contract),
            ),
        ),
    )
    return BudgetApprovalEnvelope(
        domain="budget",
        key_id="finance-key",
        payload=payload,
        signature=base64.b64encode(
            private_key.sign(approval_signed_bytes("budget", payload))
        ).decode("ascii"),
    )


def _admit(
    ledger: BudgetLedger,
    contract: BudgetContract,
    private_key: Ed25519PrivateKey,
) -> AccountSnapshot:
    plan = _plan(contract)
    return ledger.open_or_expand_account(
        plan=plan,
        contract=contract,
        envelope=_envelope(private_key, contract, plan),
        trusted_public_keys={"finance-key": private_key.public_key()},
        expected_scope=_SCOPE,
        authorized_roles=frozenset({"budget_approver"}),
        now=_NOW,
    )


def _reserve(
    tmp_path: Path,
    contract: BudgetContract,
) -> tuple[BudgetLedger, AccountSnapshot]:
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    account = _admit(ledger, contract, Ed25519PrivateKey.generate())
    product = contract.product_reserves[0]
    ledger.reserve_product(
        account.account_id,
        product.stage,
        product.product_id,
        product.maximum,
    )
    return ledger, account


def _unit(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _claim_pool(
    ledger: BudgetLedger,
    account: AccountSnapshot,
    *,
    prompt: str,
    owner: str,
    role: _Role = "weak_extractor",
    attempt_no: int = 1,
    maximum: BudgetAmounts | None = None,
) -> SendPermit | None:
    return ledger.claim_pool_attempt(
        account_id=account.account_id,
        stage=_STAGE,
        product_id=_PRODUCT,
        request_unit=_unit(prompt),
        attempt_no=attempt_no,
        owner_token=owner,
        role=role,
        maximum=maximum or _amounts(),
    )


def _terminal(ledger: BudgetLedger, permit: SendPermit | None) -> None:
    assert permit is not None
    ledger.mark_sent(permit)
    ledger.record_terminal(
        permit,
        actual=permit.maximum,
        response_digest="f" * 64,
        usage_verified=False,
    )


_PRE_POOL_ATTEMPT_COLUMNS = (
    "account_id",
    "stage",
    "product_id",
    "request_unit",
    "attempt_no",
    "owner_token_digest",
    "state",
    "max_input",
    "max_output",
    "max_cost",
    "actual_input",
    "actual_output",
    "actual_cost",
    "charged_input",
    "charged_output",
    "charged_cost",
    "response_digest",
    "provider_proof_digest",
    "provider_request_id",
    "provider_verifier_policy",
    "provider_proof_observed_at",
)
_PRE_BINDING_POOL_COLUMNS = frozenset(
    {
        "account_id",
        "stage",
        "product_id",
        "role",
        "max_attempts",
        "max_input",
        "max_output",
        "max_cost",
    }
)


def _replace_attempts_with_pre_pool_schema(db_path: Path) -> list[tuple[object, ...]]:
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            DROP TABLE deployment_role_bindings;
            DROP TABLE infrastructure_reserves;
            DROP TABLE infrastructure_authorizations;
            CREATE TABLE request_attempts_pre_pool (
                account_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                product_id TEXT NOT NULL,
                request_unit TEXT NOT NULL,
                attempt_no INTEGER NOT NULL CHECK (attempt_no >= 1),
                owner_token_digest TEXT NOT NULL,
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
            INSERT INTO request_attempts_pre_pool (
                account_id,stage,product_id,request_unit,attempt_no,
                owner_token_digest,state,max_input,max_output,max_cost,
                actual_input,actual_output,actual_cost,
                charged_input,charged_output,charged_cost,response_digest,
                provider_proof_digest,provider_request_id,provider_verifier_policy,
                provider_proof_observed_at
            )
            SELECT
                account_id,stage,product_id,request_unit,attempt_no,
                owner_token_digest,state,max_input,max_output,max_cost,
                actual_input,actual_output,actual_cost,
                charged_input,charged_output,charged_cost,response_digest,
                provider_proof_digest,provider_request_id,provider_verifier_policy,
                provider_proof_observed_at
            FROM request_attempts;
            DROP TABLE request_attempts;
            ALTER TABLE request_attempts_pre_pool RENAME TO request_attempts;
            DROP TABLE request_pool_limits;
            PRAGMA user_version = 1;
            COMMIT;
            """
        )
        rows = connection.execute(
            "SELECT * FROM request_attempts ORDER BY attempt_no"
        ).fetchall()
    return [tuple(row) for row in rows]


def _pre_pool_db(
    tmp_path: Path,
) -> tuple[Path, AccountSnapshot, tuple[SendPermit, SendPermit, SendPermit]]:
    db_path = tmp_path / "budget.sqlite3"
    exact = RequestReserve(
        request_unit=_unit("legacy exact request"),
        role="weak_extractor",
        maximum=_amounts(),
    )
    contract = _contract(request_reserves=(exact,), request_pools=())
    ledger, account = _reserve(tmp_path, contract)
    first = ledger.claim_attempt(
        account.account_id,
        _STAGE,
        _PRODUCT,
        exact.request_unit,
        1,
        "legacy-owner-1",
        exact.maximum,
    )
    assert first is not None
    ledger.mark_sent(first)
    ledger.record_terminal(
        first,
        actual=_amounts(600, 250, 70),
        response_digest="1" * 64,
        usage_verified=False,
    )
    second = ledger.claim_attempt(
        account.account_id,
        _STAGE,
        _PRODUCT,
        exact.request_unit,
        2,
        "legacy-owner-2",
        exact.maximum,
    )
    assert second is not None
    ledger.mark_uncertain(second)
    third = ledger.claim_attempt(
        account.account_id,
        _STAGE,
        _PRODUCT,
        exact.request_unit,
        3,
        "legacy-owner-3",
        exact.maximum,
    )
    assert third is not None
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """UPDATE request_attempts
               SET provider_proof_digest=?,provider_request_id=?,
                   provider_verifier_policy=?,provider_proof_observed_at=?
               WHERE attempt_no=2""",
            (
                "2" * 64,
                "legacy-provider-request",
                "bailian-usage-reconciliation-v1",
                _NOW.isoformat(),
            ),
        )
    return db_path, account, (first, second, third)


def _replace_pool_with_pre_binding_schema(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            DROP TABLE deployment_role_bindings;
            DROP TABLE infrastructure_reserves;
            DROP TABLE infrastructure_authorizations;
            CREATE TABLE request_pool_limits_pre_binding (
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
                PRIMARY KEY (account_id, stage, product_id, role),
                FOREIGN KEY (account_id, stage, product_id)
                    REFERENCES product_limits(account_id, stage, product_id)
            );
            INSERT INTO request_pool_limits_pre_binding
            SELECT account_id,stage,product_id,role,max_attempts,
                   max_input,max_output,max_cost
            FROM request_pool_limits;
            DROP TABLE request_pool_limits;
            ALTER TABLE request_pool_limits_pre_binding
                RENAME TO request_pool_limits;
            PRAGMA user_version = 0;
            COMMIT;
            """
        )


def test_d1_3a_pool_model_rates_and_bounds_are_signed_in_contract_hash() -> None:
    base = _contract()
    changed_attempts = _contract(request_pools=(_pool(max_attempts=4),))
    changed_per_attempt = _contract(request_pools=(_pool(maximum=_amounts(701, 300, 80)),))
    changed_rate = _contract(weak_input_rate=11)

    assert budget_contract_hash(base) != budget_contract_hash(changed_attempts)
    assert budget_contract_hash(base) != budget_contract_hash(changed_per_attempt)
    assert budget_contract_hash(base) != budget_contract_hash(changed_rate)

    with pytest.raises(ValidationError, match="rate"):
        _contract(
            request_pools=(_pool(maximum=_amounts(2, 0, 1)),),
            weak_input_rate=1_000_000,
        )


def test_d1_3a_pool_worst_case_must_fit_product_total_reserve() -> None:
    with pytest.raises(ValidationError, match="product maximum"):
        _contract(
            request_pools=(_pool(max_attempts=2, maximum=_amounts(700, 300, 80)),),
            product_maximum=_amounts(1_399, 600, 160),
        )


def test_d1_5_dynamic_prompt_units_do_not_require_signed_pre_enumeration(
    tmp_path: Path,
) -> None:
    ledger, account = _reserve(tmp_path, _contract())

    first = _claim_pool(ledger, account, prompt="dynamic page 1", owner="owner-a")
    second = _claim_pool(ledger, account, prompt="dynamic page 2", owner="owner-b")

    assert first is not None and first.key.request_unit == _unit("dynamic page 1")
    assert second is not None and second.key.request_unit == _unit("dynamic page 2")
    assert first.role == second.role == "weak_extractor"


def test_d1_3b_pool_accepts_only_exact_sha256_request_fingerprints(
    tmp_path: Path,
) -> None:
    ledger, account = _reserve(tmp_path, _contract())

    with pytest.raises(BudgetLedgerError, match="fingerprint"):
        ledger.claim_pool_attempt(
            account_id=account.account_id,
            stage=_STAGE,
            product_id=_PRODUCT,
            request_unit="mutable-human-label",
            attempt_no=1,
            owner_token="owner-a",
            role="weak_extractor",
            maximum=_amounts(),
        )


@pytest.mark.parametrize(
    "mismatch",
    (
        _amounts(699, 300, 80),
        _amounts(700, 301, 80),
        _amounts(700, 300, 79),
    ),
)
def test_d1_3b_pool_claim_requires_exact_per_attempt_maximum(
    tmp_path: Path,
    mismatch: BudgetAmounts,
) -> None:
    ledger, account = _reserve(tmp_path, _contract())

    with pytest.raises(BudgetLedgerError, match="bound"):
        _claim_pool(
            ledger,
            account,
            prompt="dynamic page 1",
            owner="owner-a",
            maximum=mismatch,
        )


def test_d1_3b_pool_enforces_per_role_max_attempts_even_with_headroom(
    tmp_path: Path,
) -> None:
    contract = _contract(
        request_pools=(_pool(max_attempts=2),),
        product_maximum=_amounts(10_000, 5_000, 1_000),
    )
    ledger, account = _reserve(tmp_path, contract)
    first = _claim_pool(ledger, account, prompt="dynamic 1", owner="owner-a")
    second = _claim_pool(ledger, account, prompt="dynamic 2", owner="owner-b")
    assert first is not None
    assert second is not None

    with pytest.raises(BudgetLedgerError, match="attempt"):
        _claim_pool(ledger, account, prompt="dynamic 3", owner="owner-c")

    assert ledger.account_snapshot(account.account_id).attempt_count == 2


def test_d1_3b_pool_and_exact_worst_case_share_one_product_hard_limit() -> None:
    exact = RequestReserve(
        request_unit=_unit("required exact request"),
        role="judge",
        maximum=_amounts(100, 50, 10),
    )
    with pytest.raises(ValidationError, match="product maximum"):
        _contract(
            request_reserves=(exact,),
            request_pools=(_pool(max_attempts=2),),
            product_maximum=_amounts(1_500, 650, 169),
        )


def test_d1_3b_concurrent_same_dynamic_unit_has_exactly_one_permit(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    contract = _contract()
    ledger, account = _reserve(tmp_path, contract)
    del ledger
    barrier = Barrier(2)
    lock = Lock()
    permits: list[SendPermit] = []
    errors: list[BaseException] = []

    def worker(owner: str) -> None:
        try:
            contender = BudgetLedger(db_path)
            barrier.wait()
            permit = _claim_pool(
                contender,
                account,
                prompt="same dynamic prompt",
                owner=owner,
            )
            if permit is not None:
                with lock:
                    permits.append(permit)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [Thread(target=worker, args=(owner,)) for owner in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(permits) == 1
    assert BudgetLedger(db_path).account_snapshot(account.account_id).attempt_count == 1


def test_d1_3b_unvisited_pool_branches_do_not_block_product_settlement(
    tmp_path: Path,
) -> None:
    ledger, account = _reserve(
        tmp_path,
        _contract(request_pools=(_pool(max_attempts=3),)),
    )
    permit = _claim_pool(
        ledger,
        account,
        prompt="the only visited branch",
        owner="owner-a",
    )
    _terminal(ledger, permit)

    ledger.settle_product(account.account_id, _STAGE, _PRODUCT)

    snapshot = ledger.account_snapshot(account.account_id)
    assert snapshot.reserved == _amounts(0, 0, 0)
    assert snapshot.settled == _amounts()
    assert snapshot.attempt_count == 1


def test_d1_3b_created_pool_attempt_must_resolve_before_settlement(
    tmp_path: Path,
) -> None:
    ledger, account = _reserve(tmp_path, _contract())
    permit = _claim_pool(
        ledger,
        account,
        prompt="created but not completed",
        owner="owner-a",
    )
    assert permit is not None

    with pytest.raises(BudgetLedgerError, match="unresolved"):
        ledger.settle_product(account.account_id, _STAGE, _PRODUCT)

    ledger.mark_uncertain(permit)
    ledger.settle_product(account.account_id, _STAGE, _PRODUCT)
    assert ledger.attempt_snapshot(permit.key).state == "uncertain"


@pytest.mark.parametrize("mark_sent", (False, True))
def test_d1_3b_recovery_marks_incomplete_pool_attempt_uncertain_full_charge(
    tmp_path: Path,
    mark_sent: bool,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger, account = _reserve(tmp_path, _contract())
    permit = _claim_pool(
        ledger,
        account,
        prompt="crash boundary",
        owner="owner-a",
    )
    assert permit is not None
    if mark_sent:
        ledger.mark_sent(permit)

    recovered = BudgetLedger(db_path)
    assert recovered.recover_incomplete(account.account_id) == 1
    attempt = recovered.attempt_snapshot(permit.key)
    assert attempt.state == "uncertain"
    assert attempt.charged == _amounts()
    recovered.settle_product(account.account_id, _STAGE, _PRODUCT)


def test_d1_3b_exact_request_reserve_legacy_contract_and_settlement_remain_compatible(
    tmp_path: Path,
) -> None:
    exact = RequestReserve(
        request_unit=_unit("legacy exact request"),
        role="weak_extractor",
        maximum=_amounts(),
    )
    contract = _contract(request_reserves=(exact,), request_pools=())
    legacy_payload = contract.model_dump(mode="python")
    for product in legacy_payload["product_reserves"]:
        product.pop("request_pools", None)
    legacy_contract = BudgetContract.model_validate(legacy_payload)
    ledger, account = _reserve(tmp_path, legacy_contract)

    with pytest.raises(BudgetLedgerError, match="signed request unit"):
        ledger.settle_product(account.account_id, _STAGE, _PRODUCT)

    with pytest.raises(BudgetLedgerError, match="pool"):
        _claim_pool(
            ledger,
            account,
            prompt="unsigned dynamic request",
            owner="pool-owner",
        )

    permit = ledger.claim_attempt(
        account.account_id,
        _STAGE,
        _PRODUCT,
        exact.request_unit,
        1,
        "legacy-owner",
        exact.maximum,
    )
    _terminal(ledger, permit)
    ledger.settle_product(account.account_id, _STAGE, _PRODUCT)


@pytest.mark.parametrize("mutation", ("model_identity", "role_rate"))
def test_d1_3b_d1_3c_pool_revision_cannot_rebind_model_or_rate(
    tmp_path: Path,
    mutation: str,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger(db_path)
    initial_contract = _contract()
    initial_plan = _plan(initial_contract)
    initial = ledger.open_or_expand_account(
        plan=initial_plan,
        contract=initial_contract,
        envelope=_envelope(private_key, initial_contract, initial_plan),
        trusted_public_keys={"finance-key": private_key.public_key()},
        expected_scope=_SCOPE,
        authorized_roles=frozenset({"budget_approver"}),
        now=_NOW,
    )
    ledger.reserve_product(
        initial.account_id,
        _STAGE,
        _PRODUCT,
        initial_contract.product_reserves[0].maximum,
    )
    permit = _claim_pool(
        ledger,
        initial,
        prompt="durable debit",
        owner="owner-a",
    )
    _terminal(ledger, permit)

    changed_roles = _roles()
    weak_role = changed_roles["weak_extractor"]
    if mutation == "model_identity":
        changed_roles["weak_extractor"] = weak_role.model_copy(
            update={"model_id": "replacement-deployment"}
        )
        weak_input_rate = 10
    else:
        weak_input_rate = 11
    expanded_contract = initial_contract.model_copy(
        update={
            "ceiling": _amounts(30_000, 15_000, 3_000),
            "role_rates": _rates(
                changed_roles,
                weak_input_rate=weak_input_rate,
            ),
        }
    )
    expanded_plan = RunAdmissionPlanPayload(
        run_identity=_RUN,
        purpose=_PURPOSE,
        model_roles=changed_roles,
        budget_contract_hash=budget_contract_hash(expanded_contract),
    )
    expanded_envelope = _envelope(
        private_key,
        expanded_contract,
        expanded_plan,
        revision=2,
        previous_digest=initial.approval_digest,
    )
    with sqlite3.connect(db_path) as connection:
        pool_before = connection.execute(
            "SELECT * FROM request_pool_limits"
        ).fetchall()
        attempts_before = connection.execute(
            "SELECT * FROM request_attempts"
        ).fetchall()
        approvals_before = connection.execute(
            "SELECT * FROM budget_approvals"
        ).fetchall()

    with pytest.raises(BudgetLedgerError, match="only the account ceiling"):
        ledger.open_or_expand_account(
            plan=expanded_plan,
            contract=expanded_contract,
            envelope=expanded_envelope,
            trusted_public_keys={"finance-key": private_key.public_key()},
            expected_scope=_SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=_NOW,
        )

    after = ledger.account_snapshot(initial.account_id)
    assert after.revision == 1
    assert after.approval_digest == initial.approval_digest
    assert after.attempt_count == 1
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT * FROM request_pool_limits").fetchall() == (
            pool_before
        )
        assert connection.execute("SELECT * FROM request_attempts").fetchall() == (
            attempts_before
        )
        assert connection.execute("SELECT * FROM budget_approvals").fetchall() == (
            approvals_before
        )


@pytest.mark.parametrize("mutation", ("add_pool", "remove_pool", "change_pool"))
def test_d1_3c_revision_rejects_any_request_pool_difference_before_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "budget.sqlite3"
    initial_pools = (
        _pool(),
        _pool(role="judge", max_attempts=1, maximum=_amounts(100, 50, 10)),
    )
    initial_contract = _contract(
        request_pools=(initial_pools if mutation == "remove_pool" else initial_pools[:1])
    )
    initial_plan = _plan(initial_contract)
    ledger = BudgetLedger(db_path)
    initial = ledger.open_or_expand_account(
        plan=initial_plan,
        contract=initial_contract,
        envelope=_envelope(private_key, initial_contract, initial_plan),
        trusted_public_keys={"finance-key": private_key.public_key()},
        expected_scope=_SCOPE,
        authorized_roles=frozenset({"budget_approver"}),
        now=_NOW,
    )
    product = initial_contract.product_reserves[0]
    changed_pools: tuple[RequestPoolReserve, ...]
    if mutation == "add_pool":
        changed_pools = initial_pools
    elif mutation == "remove_pool":
        changed_pools = initial_pools[:1]
    else:
        changed_pools = (_pool(max_attempts=2),)
    changed_product = product.model_copy(update={"request_pools": changed_pools})
    changed_contract = initial_contract.model_copy(
        update={
            "ceiling": _amounts(30_000, 15_000, 3_000),
            "product_reserves": (changed_product,),
        }
    )
    changed_plan = _plan(changed_contract)
    changed_envelope = _envelope(
        private_key,
        changed_contract,
        changed_plan,
        revision=2,
        previous_digest=initial.approval_digest,
    )
    with sqlite3.connect(db_path) as connection:
        before = tuple(
            connection.execute(f"SELECT * FROM {table}").fetchall()
            for table in (
                "budget_accounts",
                "budget_approvals",
                "product_limits",
                "request_limits",
                "request_pool_limits",
            )
        )

    with pytest.raises(BudgetLedgerError, match="only the account ceiling"):
        ledger.open_or_expand_account(
            plan=changed_plan,
            contract=changed_contract,
            envelope=changed_envelope,
            trusted_public_keys={"finance-key": private_key.public_key()},
            expected_scope=_SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=_NOW,
        )

    with sqlite3.connect(db_path) as connection:
        after = tuple(
            connection.execute(f"SELECT * FROM {table}").fetchall()
            for table in (
                "budget_accounts",
                "budget_approvals",
                "product_limits",
                "request_limits",
                "request_pool_limits",
            )
        )
    assert after == before


@pytest.mark.parametrize("mutation", ("model_identity", "role_rate"))
def test_d1_3a_d1_3c_account_role_rates_lock_before_new_pool_revision(
    tmp_path: Path,
    mutation: str,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger(db_path)
    exact = RequestReserve(
        request_unit=_unit("initial judge request"),
        role="judge",
        maximum=_amounts(100, 50, 10),
    )
    initial_contract = _contract(request_reserves=(exact,), request_pools=())
    initial_plan = _plan(initial_contract)
    initial = ledger.open_or_expand_account(
        plan=initial_plan,
        contract=initial_contract,
        envelope=_envelope(private_key, initial_contract, initial_plan),
        trusted_public_keys={"finance-key": private_key.public_key()},
        expected_scope=_SCOPE,
        authorized_roles=frozenset({"budget_approver"}),
        now=_NOW,
    )
    changed_roles = _roles()
    weak_role = changed_roles["weak_extractor"]
    if mutation == "model_identity":
        changed_roles["weak_extractor"] = weak_role.model_copy(
            update={"model_id": "new-pool-deployment"}
        )
        weak_input_rate = 10
    else:
        weak_input_rate = 11
    expanded_product = initial_contract.product_reserves[0].model_copy(
        update={"request_pools": (_pool(),)}
    )
    expanded_contract = initial_contract.model_copy(
        update={
            "ceiling": _amounts(30_000, 15_000, 3_000),
            "role_rates": _rates(
                changed_roles,
                weak_input_rate=weak_input_rate,
            ),
            "product_reserves": (expanded_product,),
        }
    )
    expanded_plan = RunAdmissionPlanPayload(
        run_identity=_RUN,
        purpose=_PURPOSE,
        model_roles=changed_roles,
        budget_contract_hash=budget_contract_hash(expanded_contract),
    )
    expanded_envelope = _envelope(
        private_key,
        expanded_contract,
        expanded_plan,
        revision=2,
        previous_digest=initial.approval_digest,
    )
    with sqlite3.connect(db_path) as connection:
        account_before = connection.execute(
            "SELECT * FROM budget_accounts"
        ).fetchall()
        approvals_before = connection.execute(
            "SELECT * FROM budget_approvals"
        ).fetchall()
        limits_before = connection.execute("SELECT * FROM product_limits").fetchall()
        pools_before = connection.execute(
            "SELECT * FROM request_pool_limits"
        ).fetchall()

    with pytest.raises(BudgetLedgerError, match="only the account ceiling"):
        ledger.open_or_expand_account(
            plan=expanded_plan,
            contract=expanded_contract,
            envelope=expanded_envelope,
            trusted_public_keys={"finance-key": private_key.public_key()},
            expected_scope=_SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=_NOW,
        )

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT * FROM budget_accounts").fetchall() == (
            account_before
        )
        assert connection.execute("SELECT * FROM budget_approvals").fetchall() == (
            approvals_before
        )
        assert connection.execute("SELECT * FROM product_limits").fetchall() == (
            limits_before
        )
        assert connection.execute("SELECT * FROM request_pool_limits").fetchall() == (
            pools_before
        )


def test_d1_3b_d1_3c_pre_pool_schema_migrates_rows_and_remains_operable(
    tmp_path: Path,
) -> None:
    db_path, account, permits = _pre_pool_db(tmp_path)
    old_rows = _replace_attempts_with_pre_pool_schema(db_path)
    assert [row[6] for row in old_rows] == ["terminal", "uncertain", "prepared"]

    migrated = BudgetLedger(db_path)

    with sqlite3.connect(db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(request_attempts)")
        }
        preserved_rows = connection.execute(
            """SELECT
                   account_id,stage,product_id,request_unit,attempt_no,
                   owner_token_digest,state,max_input,max_output,max_cost,
                   actual_input,actual_output,actual_cost,
                   charged_input,charged_output,charged_cost,response_digest,
                   provider_proof_digest,provider_request_id,
                   provider_verifier_policy,provider_proof_observed_at
               FROM request_attempts ORDER BY attempt_no"""
        ).fetchall()
        migrated_bindings = connection.execute(
            "SELECT role,limit_kind FROM request_attempts ORDER BY attempt_no"
        ).fetchall()
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    assert version == (5,)
    assert {"role", "limit_kind"}.issubset(columns)
    assert [tuple(row) for row in preserved_rows] == old_rows
    assert [tuple(row) for row in migrated_bindings] == [
        ("weak_extractor", "exact"),
        ("weak_extractor", "exact"),
        ("weak_extractor", "exact"),
    ]
    assert foreign_key_errors == []
    assert migrated.attempt_snapshot(permits[0].key).state == "terminal"
    assert migrated.attempt_snapshot(permits[1].key).state == "uncertain"
    assert migrated.recover_incomplete(account.account_id) == 1
    assert migrated.attempt_snapshot(permits[2].key).state == "uncertain"

    fourth = migrated.claim_attempt(
        account.account_id,
        _STAGE,
        _PRODUCT,
        permits[0].key.request_unit,
        4,
        "post-migration-owner",
        _amounts(),
    )
    _terminal(migrated, fourth)
    migrated.settle_product(account.account_id, _STAGE, _PRODUCT)


def test_d1_3c_pre_pool_schema_migration_failure_preserves_old_table(
    tmp_path: Path,
) -> None:
    db_path, _account, _permits = _pre_pool_db(tmp_path)
    _replace_attempts_with_pre_pool_schema(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE request_attempts SET request_unit=? WHERE attempt_no=3",
            (_unit("missing signed limit"),),
        )
        rows_before = connection.execute(
            "SELECT * FROM request_attempts ORDER BY attempt_no"
        ).fetchall()
        schema_before = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='request_attempts'"
        ).fetchone()
    assert schema_before is not None

    with pytest.raises(BudgetLedgerError, match="migration"):
        BudgetLedger(db_path)

    with sqlite3.connect(db_path) as connection:
        rows_after = connection.execute(
            "SELECT * FROM request_attempts ORDER BY attempt_no"
        ).fetchall()
        schema_after = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='request_attempts'"
        ).fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(request_attempts)")
        }
    assert rows_after == rows_before
    assert schema_after == schema_before
    assert version == (1,)
    assert "role" not in columns
    assert "limit_kind" not in columns


def test_d1_3b_d1_3c_pre_binding_pool_migration_uses_immutable_revision_one_identity(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger(db_path)
    initial_contract = _contract()
    initial_plan = _plan(initial_contract)
    initial = ledger.open_or_expand_account(
        plan=initial_plan,
        contract=initial_contract,
        envelope=_envelope(private_key, initial_contract, initial_plan),
        trusted_public_keys={"finance-key": private_key.public_key()},
        expected_scope=_SCOPE,
        authorized_roles=frozenset({"budget_approver"}),
        now=_NOW,
    )
    expanded_contract = initial_contract.model_copy(
        update={"ceiling": _amounts(30_000, 15_000, 3_000)}
    )
    expanded_plan = _plan(expanded_contract)
    ledger.open_or_expand_account(
        plan=expanded_plan,
        contract=expanded_contract,
        envelope=_envelope(
            private_key,
            expanded_contract,
            expanded_plan,
            revision=2,
            previous_digest=initial.approval_digest,
        ),
        trusted_public_keys={"finance-key": private_key.public_key()},
        expected_scope=_SCOPE,
        authorized_roles=frozenset({"budget_approver"}),
        now=_NOW,
    )
    _replace_pool_with_pre_binding_schema(db_path)

    BudgetLedger(db_path)

    expected_rate = expanded_contract.role_rates["weak_extractor"]
    with sqlite3.connect(db_path) as connection:
        binding = connection.execute(
            """SELECT model_role_identity_hash,role_rate_digest
               FROM request_pool_limits WHERE role='weak_extractor'"""
        ).fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()
    assert binding is not None
    assert binding[0] == expected_rate.model_role_identity_hash
    assert isinstance(binding[1], str) and len(binding[1]) == 64
    assert version == (5,)


def test_d1_3b_d1_3c_pre_binding_pool_migration_rejects_historical_rebind(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger(db_path)
    initial_contract = _contract()
    initial = _admit(ledger, initial_contract, private_key)
    rebound_contract = initial_contract.model_copy(
        update={"role_rates": _rates(_roles(), weak_input_rate=11)}
    )
    rebound_digest = "3" * 64
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """INSERT INTO budget_approvals VALUES (
                   ?, 2, ?, ?, ?, ?, ?, ?, ?, ?
               )""",
            (
                initial.account_id,
                rebound_digest,
                initial.approval_digest,
                "4" * 64,
                budget_contract_hash(rebound_contract),
                rebound_contract.model_dump_json().encode("utf-8"),
                rebound_contract.ceiling.input_tokens,
                rebound_contract.ceiling.output_tokens,
                rebound_contract.ceiling.cost_minor_units,
            ),
        )
        connection.execute(
            """UPDATE budget_accounts
               SET current_revision=2,approval_digest=? WHERE account_id=?""",
            (rebound_digest, initial.account_id),
        )
    _replace_pool_with_pre_binding_schema(db_path)

    with pytest.raises(BudgetLedgerError, match="binding changed"):
        BudgetLedger(db_path)

    with sqlite3.connect(db_path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(request_pool_limits)")
        }
        version = connection.execute("PRAGMA user_version").fetchone()
    assert columns == set(_PRE_BINDING_POOL_COLUMNS)
    assert version == (0,)


def test_d1_3b_d1_3c_pre_binding_pool_migration_rejects_historical_bound_change(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger(db_path)
    initial_contract = _contract()
    initial = _admit(ledger, initial_contract, private_key)
    changed_product = initial_contract.product_reserves[0].model_copy(
        update={"request_pools": (_pool(max_attempts=4),)}
    )
    changed_contract = initial_contract.model_copy(
        update={"product_reserves": (changed_product,)}
    )
    changed_digest = "5" * 64
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """INSERT INTO budget_approvals VALUES (
                   ?, 2, ?, ?, ?, ?, ?, ?, ?, ?
               )""",
            (
                initial.account_id,
                changed_digest,
                initial.approval_digest,
                "6" * 64,
                budget_contract_hash(changed_contract),
                changed_contract.model_dump_json().encode("utf-8"),
                changed_contract.ceiling.input_tokens,
                changed_contract.ceiling.output_tokens,
                changed_contract.ceiling.cost_minor_units,
            ),
        )
        connection.execute(
            """UPDATE budget_accounts
               SET current_revision=2,approval_digest=? WHERE account_id=?""",
            (changed_digest, initial.account_id),
        )
        connection.execute(
            "UPDATE request_pool_limits SET max_attempts=4"
        )
    _replace_pool_with_pre_binding_schema(db_path)
    with sqlite3.connect(db_path) as connection:
        rows_before = connection.execute(
            "SELECT * FROM request_pool_limits"
        ).fetchall()

    with pytest.raises(BudgetLedgerError, match="history changed"):
        BudgetLedger(db_path)

    with sqlite3.connect(db_path) as connection:
        rows_after = connection.execute(
            "SELECT * FROM request_pool_limits"
        ).fetchall()
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(request_pool_limits)")
        }
        version = connection.execute("PRAGMA user_version").fetchone()
    assert rows_after == rows_before
    assert columns == set(_PRE_BINDING_POOL_COLUMNS)
    assert version == (0,)
