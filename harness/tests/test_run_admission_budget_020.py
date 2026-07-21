"""OpenSpec 020 D1.3a-D1.3c: durable, signed run-budget accounting."""

from __future__ import annotations

import base64
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Lock, Thread

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
    ProviderNoUsageProof,
    ProviderSpendCapAttestation,
    RequestReserve,
    RoleRate,
    budget_account_identity,
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

_NOW = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
_RUN = "gs-v0.1-run-001"
_PURPOSE = "gs-v0.1-baseline"
_SCOPE = "budget:gs-v0.1"


def _model_roles() -> dict[str, ModelRolePlan]:
    return {
        role: ModelRolePlan(
            provider="bailian",
            model_id=f"{role}-model",
            expected_model_revision="2026-07-19T08:00:00Z",
            protocol="https",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            provider_policy="bailian-deployment-detail-v1",
            credential_env_name="HARNESS_DASHSCOPE_API_KEY",
        )
        for role in ("annotator", "weak_extractor", "judge")
    }


def _amounts(
    input_tokens: int = 1_000,
    output_tokens: int = 500,
    cost_minor_units: int = 100,
) -> BudgetAmounts:
    return BudgetAmounts(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_minor_units=cost_minor_units,
    )


def _contract(
    *,
    ceiling: BudgetAmounts | None = None,
    provider_cap: int = 900,
    products: tuple[str, ...] = ("product-01", "product-02", "product-03"),
    requests: tuple[RequestReserve, ...] | None = None,
) -> BudgetContract:
    cap = ceiling or _amounts(10_000, 5_000, 1_000)
    roles = _model_roles()
    rates = {
        role: RoleRate(
            model_role_identity_hash=model_role_budget_identity_hash(roles[role]),
            input_cost_per_million_minor_units=10,
            output_cost_per_million_minor_units=20,
        )
        for role in ("annotator", "weak_extractor", "judge")
    }
    request_limits = requests or (
        RequestReserve(
            request_unit="page-001",
            role="weak_extractor",
            maximum=_amounts(700, 300, 80),
        ),
    )
    return BudgetContract(
        currency="CNY",
        price_snapshot_id="bailian-pricing-20260719",
        price_observed_at=_NOW,
        price_expires_at=_NOW + timedelta(hours=1),
        ceiling=cap,
        role_rates=rates,
        provider_attestation=ProviderSpendCapAttestation(
            provider="bailian",
            project_ref="sha256:" + "a" * 64,
            credential_ref="sha256:" + "b" * 64,
            max_cost_minor_units=provider_cap,
            observed_at=_NOW,
            expires_at=_NOW + timedelta(hours=1),
            evidence_digest="e" * 64,
        ),
        product_reserves=tuple(
            ProductReserve(
                stage="extraction",
                product_id=product,
                maximum=_amounts(),
                request_reserves=request_limits,
            )
            for product in products
        ),
    )


def _plan(
    contract: BudgetContract,
    *,
    run_identity: str = _RUN,
) -> RunAdmissionPlanPayload:
    return RunAdmissionPlanPayload(
        run_identity=run_identity,
        purpose=_PURPOSE,
        model_roles=_model_roles(),
        budget_contract_hash=budget_contract_hash(contract),
    )


def _envelope(
    private_key: Ed25519PrivateKey,
    contract: BudgetContract,
    *,
    plan: RunAdmissionPlanPayload | None = None,
    revision: int = 1,
    previous_digest: str | None = None,
) -> BudgetApprovalEnvelope:
    active_plan = plan or _plan(contract)
    ceiling = contract.ceiling
    payload = BudgetApprovalPayload(
        plan_payload_hash=plan_payload_hash(active_plan),
        run_identity=active_plan.run_identity,
        purpose=active_plan.purpose,
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
    signature = private_key.sign(approval_signed_bytes("budget", payload))
    return BudgetApprovalEnvelope(
        domain="budget",
        key_id="finance-key",
        payload=payload,
        signature=base64.b64encode(signature).decode("ascii"),
    )


def _admit(
    ledger: BudgetLedger,
    contract: BudgetContract,
    private_key: Ed25519PrivateKey,
    *,
    envelope: BudgetApprovalEnvelope | None = None,
    plan: RunAdmissionPlanPayload | None = None,
) -> AccountSnapshot:
    active_plan = plan or _plan(contract)
    approval = envelope or _envelope(private_key, contract, plan=active_plan)
    return ledger.open_or_expand_account(
        plan=active_plan,
        contract=contract,
        envelope=approval,
        trusted_public_keys={"finance-key": private_key.public_key()},
        expected_scope=_SCOPE,
        authorized_roles=frozenset({"budget_approver"}),
        now=_NOW,
    )


def test_d1_3a_invalid_caps_rates_attestation_or_approval_block(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError):
        _amounts(cost_minor_units=-1)
    with pytest.raises(ValidationError):
        BudgetContract.model_validate(
            {
                **_contract().model_dump(),
                "role_rates": {
                    "annotator": RoleRate(
                        model_role_identity_hash="f" * 64,
                        input_cost_per_million_minor_units=10,
                        output_cost_per_million_minor_units=20,
                    )
                },
            }
        )
    with pytest.raises(ValidationError):
        _contract(provider_cap=1_001)
    underpriced = _contract().model_dump()
    underpriced["product_reserves"][0]["request_reserves"][0]["maximum"][
        "cost_minor_units"
    ] = 0
    with pytest.raises(ValidationError):
        BudgetContract.model_validate(underpriced)

    private_key = Ed25519PrivateKey.generate()
    contract = _contract()
    wrong_contract = _contract(provider_cap=899)
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    with pytest.raises(BudgetLedgerError, match="contract"):
        _admit(
            ledger,
            wrong_contract,
            private_key,
            envelope=_envelope(private_key, contract),
            plan=_plan(contract),
        )


def test_d1_3a_product_worst_case_cost_cannot_exceed_provider_cap() -> None:
    ten_products = tuple(f"product-{index:02d}" for index in range(1, 11))

    with pytest.raises(ValidationError, match="provider"):
        _contract(provider_cap=900, products=ten_products)


@pytest.mark.parametrize(
    ("revision", "approval_digest"),
    (
        pytest.param(2, None, id="revision"),
        pytest.param(None, "f" * 64, id="approval-digest"),
    ),
)
def test_d1_3c_authorized_snapshot_drift_rolls_back_before_reservation(
    tmp_path: Path,
    revision: int | None,
    approval_digest: str | None,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    ledger = BudgetLedger._for_testing(
        tmp_path / "budget.sqlite3",
        clock=lambda: _NOW,
    )
    account = _admit(ledger, _contract(), private_key)

    with pytest.raises(BudgetLedgerError, match="snapshot drifted"):
        ledger.reserve_product_for_authorized_snapshot(
            account_id=account.account_id,
            expected_account_revision=(revision or account.revision),
            expected_approval_digest=(approval_digest or account.approval_digest),
            authorization_evaluated_at=_NOW,
            authorization_expires_at=_NOW + timedelta(minutes=5),
            stage="extraction",
            product_id="product-01",
            maximum=_amounts(),
        )

    assert ledger.account_snapshot(account.account_id).reserved == _amounts(0, 0, 0)


def test_d1_3c_authorized_snapshot_expiry_precedes_idempotent_reserve_return(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    current = [_NOW]
    ledger = BudgetLedger._for_testing(
        tmp_path / "budget.sqlite3",
        clock=lambda: current[0],
    )
    account = _admit(ledger, _contract(), private_key)
    def reserve() -> None:
        ledger.reserve_product_for_authorized_snapshot(
            account_id=account.account_id,
            expected_account_revision=account.revision,
            expected_approval_digest=account.approval_digest,
            authorization_evaluated_at=_NOW,
            authorization_expires_at=_NOW + timedelta(minutes=5),
            stage="extraction",
            product_id="product-01",
            maximum=_amounts(),
        )

    reserve()
    current[0] = _NOW + timedelta(minutes=5)

    with pytest.raises(BudgetLedgerError, match="expired"):
        reserve()

    assert ledger.account_snapshot(account.account_id).reserved == _amounts()


def test_d1_3b_two_processes_debit_once_and_only_owner_sends(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    contract = _contract()
    db_path = tmp_path / "budget.sqlite3"
    account = _admit(BudgetLedger(db_path), contract, private_key)
    barrier = Barrier(2)
    lock = Lock()
    outbound_owners: list[str] = []
    errors: list[BaseException] = []

    def worker(owner: str) -> None:
        try:
            ledger = BudgetLedger(db_path)
            barrier.wait()
            ledger.reserve_product(
                account.account_id, "extraction", "product-01", _amounts()
            )
            permit = ledger.claim_attempt(
                account.account_id,
                "extraction",
                "product-01",
                "page-001",
                1,
                owner,
                _amounts(700, 300, 80),
            )
            if permit is not None:
                with lock:
                    outbound_owners.append(owner)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [Thread(target=worker, args=(owner,)) for owner in ("owner-a", "owner-b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    snapshot = BudgetLedger(db_path).account_snapshot(account.account_id)
    assert errors == []
    assert len(outbound_owners) == 1
    assert snapshot.reserved == _amounts()
    assert snapshot.attempt_count == 1
    with sqlite3.connect(db_path) as connection:
        stored_owner = connection.execute(
            "SELECT owner_token_digest FROM request_attempts"
        ).fetchone()
    assert stored_owner is not None
    assert stored_owner[0] not in {"owner-a", "owner-b"}


def test_d1_3b_release_and_attempt_claim_share_one_lock(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger(db_path)
    account = _admit(ledger, _contract(), private_key)
    ledger.reserve_product(account.account_id, "extraction", "product-01", _amounts())
    barrier = Barrier(2)
    outcomes: dict[str, object] = {}

    def release() -> None:
        barrier.wait()
        outcomes["released"] = BudgetLedger(db_path).release_product(
            account.account_id, "extraction", "product-01"
        )

    def claim() -> None:
        barrier.wait()
        outcomes["permit"] = BudgetLedger(db_path).claim_attempt(
            account.account_id,
            "extraction",
            "product-01",
            "page-001",
            1,
            "owner-a",
            _amounts(700, 300, 80),
        )

    threads = [Thread(target=release), Thread(target=claim)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    released = outcomes["released"] is True
    claimed = outcomes["permit"] is not None
    assert released != claimed


@pytest.mark.parametrize("mark_sent", (False, True))
def test_d1_3b_crash_boundaries_become_uncertain_full_charge_and_never_replay(
    tmp_path: Path,
    mark_sent: bool,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger(db_path)
    account = _admit(ledger, _contract(), private_key)
    ledger.reserve_product(account.account_id, "extraction", "product-01", _amounts())
    bound = _amounts(700, 300, 80)
    permit = ledger.claim_attempt(
        account.account_id,
        "extraction",
        "product-01",
        "page-001",
        1,
        "owner-a",
        bound,
    )
    assert permit is not None
    if mark_sent:
        ledger.mark_sent(permit)

    recovered = BudgetLedger(db_path)
    assert recovered.recover_incomplete(account.account_id) == 1
    attempt = recovered.attempt_snapshot(permit.key)
    assert attempt.state == "uncertain"
    assert attempt.charged == bound
    assert recovered.claim_attempt(
        account.account_id,
        "extraction",
        "product-01",
        "page-001",
        1,
        "owner-b",
        bound,
    ) is None
    assert recovered.release_product(
        account.account_id, "extraction", "product-01"
    ) is False


def test_d1_3b_terminal_or_provider_no_usage_proof_controls_resume(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger(db_path)
    account = _admit(ledger, _contract(), private_key)
    ledger.reserve_product(account.account_id, "extraction", "product-01", _amounts())
    terminal = ledger.claim_attempt(
        account.account_id, "extraction", "product-01", "page-001", 1,
        "owner-a", _amounts(700, 300, 80),
    )
    assert terminal is not None
    ledger.record_terminal(
        terminal,
        actual=_amounts(600, 250, 70),
        response_digest="a" * 64,
        usage_verified=False,
    )
    assert ledger.recover_incomplete(account.account_id) == 0
    ledger.settle_product(account.account_id, "extraction", "product-01")

    ledger.reserve_product(account.account_id, "extraction", "product-02", _amounts())
    unused = ledger.claim_attempt(
        account.account_id, "extraction", "product-02", "page-001", 1,
        "owner-b", _amounts(700, 300, 80),
    )
    assert unused is not None
    assert ledger.release_product(
        account.account_id, "extraction", "product-02"
    ) is False
    ledger.record_provider_no_usage(
        unused,
        proof=ProviderNoUsageProof(
            provider="bailian",
            provider_request_id="request-001",
            evidence_digest="b" * 64,
            observed_at=_NOW,
            verifier_policy="bailian-usage-reconciliation-v1",
        ),
    )
    assert ledger.release_product(
        account.account_id, "extraction", "product-02"
    ) is True


def test_d1_3b_owner_can_mark_only_its_attempt_uncertain_and_full_charge(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    account = _admit(ledger, _contract(), private_key)
    ledger.reserve_product(account.account_id, "extraction", "product-01", _amounts())
    bound = _amounts(700, 300, 80)
    permit = ledger.claim_attempt(
        account.account_id,
        "extraction",
        "product-01",
        "page-001",
        1,
        "owner-a",
        bound,
    )
    assert permit is not None
    ledger.mark_sent(permit)

    ledger.mark_uncertain(permit)

    attempt = ledger.attempt_snapshot(permit.key)
    assert attempt.state == "uncertain"
    assert attempt.charged == bound
    assert attempt.response_digest is None
    with pytest.raises(BudgetLedgerError, match="current attempt owner"):
        ledger.mark_uncertain(permit)


def test_d1_3b_terminal_snapshot_exposes_only_verified_response_digest(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    account = _admit(ledger, _contract(), private_key)
    ledger.reserve_product(account.account_id, "extraction", "product-01", _amounts())
    permit = ledger.claim_attempt(
        account.account_id,
        "extraction",
        "product-01",
        "page-001",
        1,
        "owner-a",
        _amounts(700, 300, 80),
    )
    assert permit is not None
    ledger.mark_sent(permit)
    digest = "a" * 64
    ledger.record_terminal(
        permit,
        actual=permit.maximum,
        response_digest=digest,
        usage_verified=False,
    )

    attempt = ledger.attempt_snapshot(permit.key)
    assert attempt.state == "terminal"
    assert attempt.response_digest == digest


def test_d1_3b_settle_requires_every_signed_request_unit(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    requests = tuple(
        RequestReserve(
            request_unit=f"page-{index:03d}",
            role="weak_extractor",
            maximum=_amounts(400, 200, 40),
        )
        for index in (1, 2)
    )
    contract = _contract(products=("product-01",), requests=requests)
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    account = _admit(ledger, contract, private_key)
    ledger.reserve_product(account.account_id, "extraction", "product-01", _amounts())

    first = ledger.claim_attempt(
        account.account_id,
        "extraction",
        "product-01",
        "page-001",
        1,
        "owner-a",
        _amounts(400, 200, 40),
    )
    assert first is not None
    ledger.record_terminal(
        first,
        actual=_amounts(300, 150, 30),
        response_digest="d" * 64,
        usage_verified=False,
    )
    with pytest.raises(BudgetLedgerError, match="signed request"):
        ledger.settle_product(account.account_id, "extraction", "product-01")

    second = ledger.claim_attempt(
        account.account_id,
        "extraction",
        "product-01",
        "page-002",
        1,
        "owner-b",
        _amounts(400, 200, 40),
    )
    assert second is not None
    ledger.record_terminal(
        second,
        actual=_amounts(300, 150, 30),
        response_digest="e" * 64,
        usage_verified=False,
    )
    ledger.settle_product(account.account_id, "extraction", "product-01")


def test_d1_3a_d1_3b_request_bound_is_signed_and_retry_is_sequential(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    account = _admit(ledger, _contract(), private_key)
    ledger.reserve_product(account.account_id, "extraction", "product-03", _amounts())

    with pytest.raises(BudgetLedgerError, match="request bound"):
        ledger.claim_attempt(
            account.account_id,
            "extraction",
            "product-03",
            "page-001",
            1,
            "owner-a",
            _amounts(1, 1, 1),
        )
    first = ledger.claim_attempt(
        account.account_id,
        "extraction",
        "product-03",
        "page-001",
        1,
        "owner-a",
        _amounts(700, 300, 80),
    )
    assert first is not None
    ledger.record_provider_no_usage(
        first,
        proof=ProviderNoUsageProof(
            provider="bailian",
            provider_request_id="request-002",
            evidence_digest="c" * 64,
            observed_at=_NOW,
            verifier_policy="bailian-usage-reconciliation-v1",
        ),
    )
    with pytest.raises(BudgetLedgerError, match="attempt number"):
        ledger.claim_attempt(
            account.account_id,
            "extraction",
            "product-03",
            "page-001",
            3,
            "owner-c",
            _amounts(700, 300, 80),
        )
    assert ledger.claim_attempt(
        account.account_id,
        "extraction",
        "product-03",
        "page-001",
        2,
        "owner-b",
        _amounts(700, 300, 80),
    ) is not None


def test_d1_3c_cross_run_replay_cannot_open_or_debit_account(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    contract = _contract()
    envelope = _envelope(private_key, contract)
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    another_plan = _plan(contract, run_identity="another-run")

    with pytest.raises(BudgetLedgerError, match="approval"):
        ledger.open_or_expand_account(
            plan=another_plan,
            contract=contract,
            envelope=envelope,
            trusted_public_keys={"finance-key": private_key.public_key()},
            expected_scope=_SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=_NOW,
        )
    assert budget_account_identity(_RUN, _PURPOSE) != budget_account_identity(
        "another-run", _PURPOSE
    )


def test_d1_3c_cap_revision_preserves_debits_and_cannot_reduce_ceiling(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger(db_path)
    first = _admit(ledger, _contract(), private_key)
    ledger.reserve_product(first.account_id, "extraction", "product-01", _amounts())
    permit = ledger.claim_attempt(
        first.account_id, "extraction", "product-01", "page-001", 1,
        "owner-a", _amounts(700, 300, 80),
    )
    assert permit is not None
    ledger.recover_incomplete(first.account_id)

    expanded_contract = _contract(ceiling=_amounts(20_000, 10_000, 2_000), provider_cap=1_800)
    expanded_plan = _plan(expanded_contract)
    expanded_envelope = _envelope(
        private_key,
        expanded_contract,
        plan=expanded_plan,
        revision=2,
        previous_digest=first.approval_digest,
    )
    expanded = _admit(
        ledger,
        expanded_contract,
        private_key,
        envelope=expanded_envelope,
        plan=expanded_plan,
    )
    assert expanded.account_id == first.account_id
    assert expanded.revision == 2
    assert ledger.attempt_snapshot(permit.key).state == "uncertain"
    assert ledger.account_snapshot(first.account_id).reserved == _amounts()

    lower_contract = _contract()
    lower_plan = _plan(lower_contract)
    lower_envelope = _envelope(
        private_key,
        lower_contract,
        plan=lower_plan,
        revision=3,
        previous_digest=expanded.approval_digest,
    )
    with pytest.raises(BudgetLedgerError, match="ceiling"):
        _admit(
            ledger,
            lower_contract,
            private_key,
            envelope=lower_envelope,
            plan=lower_plan,
        )
