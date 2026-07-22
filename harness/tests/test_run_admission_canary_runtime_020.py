"""OpenSpec 020 D1.5: runtime consumption of fresh execution authority."""

from __future__ import annotations

import base64
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Protocol, cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import insurance_harness.goldenset.admission_runtime as admission_runtime
from insurance_harness.goldenset.admission import (
    InitialExecutionAuthorization,
    ProductionAdmissionEvaluator,
    ReviewedExecutionAuthorization,
    RunAdmissionDocument,
    RuntimeAdmissionDecision,
)
from insurance_harness.goldenset.admission_budget import (
    BudgetAmounts,
    BudgetLedger,
    budget_contract_hash,
)
from insurance_harness.goldenset.admission_models import (
    BudgetApprovalEntry,
    BudgetApprovalEnvelope,
    BudgetApprovalPayload,
    approval_signed_bytes,
    plan_payload_hash,
)
from insurance_harness.goldenset.admission_runtime import (
    AdmissionBlockedError,
    AdmissionPausedError,
    AdmissionRuntimeGuard,
    ApprovedModelResponse,
)
from tests import test_run_admission_canary_authorization_020 as auth_cases

_SECRET_CANARY = "SECRET-CANARY"


class _ExecutionDecisionProduct(Protocol):
    @property
    def execution_decision(self) -> RuntimeAdmissionDecision: ...


def _reservation_count(db_path: Path, product_id: str) -> int:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM product_reservations WHERE product_id=?",
            (product_id,),
        ).fetchone()
    assert row is not None
    return int(row[0])


def _claim_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM canary_capability_claims").fetchone()
    assert row is not None
    return int(row[0])


def _assert_sanitized_pause(
    error: AdmissionPausedError,
    *,
    expected_code: str,
) -> None:
    assert error.code == expected_code
    assert error.__cause__ is None
    assert error.__context__ is None
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        assert _SECRET_CANARY not in str(current)
        assert _SECRET_CANARY not in repr(current)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)


class _MutableClock:
    def __init__(self, current: datetime = auth_cases._NOW) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


def _initial_runtime_context(
    tmp_path: Path,
    clock: _MutableClock,
) -> tuple[
    RunAdmissionDocument,
    BudgetLedger,
    ProductionAdmissionEvaluator,
    auth_cases._ReviewSource,
    Ed25519PrivateKey,
    Ed25519PrivateKey,
]:
    provenance_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    review_key = Ed25519PrivateKey.generate()
    source = auth_cases._ReviewSource()
    evaluator = auth_cases._evaluator(
        provenance_key,
        budget_key,
        review_key,
        source,
        auth_cases._ArtifactInspector(auth_cases._artifacts()),
        clock=clock,
    )
    document = auth_cases._document(provenance_key, budget_key)
    ledger = BudgetLedger._for_testing(
        tmp_path / "budget.sqlite3",
        clock=clock,
    )
    return document, ledger, evaluator, source, budget_key, review_key


def _install_zero_model_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[tuple[object, ...], dict[str, object]]]:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def complete(
        _self: object,
        *_args: object,
        **_kwargs: object,
    ) -> ApprovedModelResponse:
        calls.append((_args, _kwargs))
        raise AssertionError("model must not be called before an authorized reservation")

    monkeypatch.setattr(admission_runtime._BailianApprovedModelInvoker, "complete", complete)
    return calls


def _expand_budget_account(
    *,
    document: RunAdmissionDocument,
    ledger: BudgetLedger,
    budget_key: Ed25519PrivateKey,
    previous_approval_digest: str,
) -> None:
    contract = document.budget_contract
    assert contract is not None
    expanded_ceiling = BudgetAmounts(
        input_tokens=contract.ceiling.input_tokens * 2,
        output_tokens=contract.ceiling.output_tokens * 2,
        cost_minor_units=contract.ceiling.cost_minor_units,
    )
    expanded_contract = contract.model_copy(update={"ceiling": expanded_ceiling})
    expanded_plan = document.plan.payload.model_copy(
        update={"budget_contract_hash": budget_contract_hash(expanded_contract)}
    )
    payload = BudgetApprovalPayload(
        plan_payload_hash=plan_payload_hash(expanded_plan),
        run_identity=expanded_plan.run_identity,
        purpose=expanded_plan.purpose,
        scope="budget:gs-v0.1",
        approver_identity="finance-owner@example.com",
        approver_role="budget_approver",
        issued_at=auth_cases._NOW - timedelta(minutes=1),
        expires_at=auth_cases._NOW + timedelta(hours=1),
        revision=2,
        previous_approval_digest=previous_approval_digest,
        budget_entries=(
            BudgetApprovalEntry(
                currency=expanded_contract.currency,
                max_input_tokens=expanded_ceiling.input_tokens,
                max_output_tokens=expanded_ceiling.output_tokens,
                max_cost_minor_units=expanded_ceiling.cost_minor_units,
                budget_contract_hash=budget_contract_hash(expanded_contract),
            ),
        ),
    )
    envelope = BudgetApprovalEnvelope(
        domain="budget",
        key_id="budget-key",
        payload=payload,
        signature=base64.b64encode(
            budget_key.sign(approval_signed_bytes("budget", payload))
        ).decode("ascii"),
    )
    ledger._open_or_expand_account_for_testing(
        plan=expanded_plan,
        contract=expanded_contract,
        envelope=envelope,
        trusted_public_keys={"budget-key": budget_key.public_key()},
        expected_scope="budget:gs-v0.1",
        authorized_roles=frozenset({"budget_approver"}),
        now=auth_cases._NOW,
    )


def test_d1_5_evaluation_exception_chain_is_sanitized_before_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _MutableClock()
    document, ledger, evaluator, _source, _budget_key, _review_key = _initial_runtime_context(
        tmp_path, clock
    )
    model_calls = _install_zero_model_counter(monkeypatch)

    def fail_evaluation(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError(_SECRET_CANARY)

    monkeypatch.setattr(evaluator, "evaluate_execution", fail_evaluation)
    guard = AdmissionRuntimeGuard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=tmp_path / "responses",
    )
    try:
        with pytest.raises(AdmissionPausedError) as caught:
            guard.begin_product(stage="annotation", product_id=auth_cases._FIRST)
    finally:
        guard.close()

    _assert_sanitized_pause(caught.value, expected_code="admission_evaluation_failed")
    assert _reservation_count(tmp_path / "budget.sqlite3", auth_cases._FIRST) == 0
    assert _claim_count(tmp_path / "budget.sqlite3") == 0
    assert model_calls == []


def test_d1_5_initial_revalidation_exception_chain_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _MutableClock()
    document, ledger, evaluator, _source, _budget_key, _review_key = _initial_runtime_context(
        tmp_path, clock
    )
    model_calls = _install_zero_model_counter(monkeypatch)

    def fail_revalidation(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(_SECRET_CANARY)

    monkeypatch.setattr(evaluator, "revalidate_initial_authorization", fail_revalidation)
    guard = AdmissionRuntimeGuard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=tmp_path / "responses",
    )
    try:
        with pytest.raises(AdmissionPausedError) as caught:
            guard.begin_product(stage="annotation", product_id=auth_cases._FIRST)
    finally:
        guard.close()

    _assert_sanitized_pause(
        caught.value,
        expected_code="initial_execution_authorization_invalid",
    )
    assert _reservation_count(tmp_path / "budget.sqlite3", auth_cases._FIRST) == 0
    assert _claim_count(tmp_path / "budget.sqlite3") == 0
    assert model_calls == []


def test_d1_5_initial_atomic_reserve_exception_chain_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _MutableClock()
    document, ledger, evaluator, _source, _budget_key, _review_key = _initial_runtime_context(
        tmp_path, clock
    )
    model_calls = _install_zero_model_counter(monkeypatch)

    def fail_reserve(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(_SECRET_CANARY)

    monkeypatch.setattr(ledger, "reserve_product_for_authorized_snapshot", fail_reserve)
    guard = AdmissionRuntimeGuard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=tmp_path / "responses",
    )
    try:
        with pytest.raises(AdmissionPausedError) as caught:
            guard.begin_product(stage="annotation", product_id=auth_cases._FIRST)
    finally:
        guard.close()

    _assert_sanitized_pause(
        caught.value,
        expected_code="initial_authorized_reservation_failed",
    )
    assert _reservation_count(tmp_path / "budget.sqlite3", auth_cases._FIRST) == 0
    assert _claim_count(tmp_path / "budget.sqlite3") == 0
    assert model_calls == []


def test_d1_5_reviewed_revalidation_exception_chain_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, ledger, evaluator, source, _artifacts, review_key = auth_cases._setup(tmp_path)
    _install_valid_review(document, ledger, evaluator, source, review_key)
    model_calls = _install_zero_model_counter(monkeypatch)

    def fail_revalidation(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(_SECRET_CANARY)

    monkeypatch.setattr(evaluator, "revalidate_review_authorization", fail_revalidation)
    guard = AdmissionRuntimeGuard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=tmp_path / "responses",
    )
    try:
        with pytest.raises(AdmissionPausedError) as caught:
            guard.begin_product(stage="annotation", product_id=auth_cases._SECOND)
    finally:
        guard.close()

    _assert_sanitized_pause(
        caught.value,
        expected_code="reviewed_execution_authorization_invalid",
    )
    assert _reservation_count(tmp_path / "budget.sqlite3", auth_cases._SECOND) == 0
    assert _claim_count(tmp_path / "budget.sqlite3") == 0
    assert model_calls == []


def test_d1_5_reviewed_claim_exception_chain_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, ledger, evaluator, source, _artifacts, review_key = auth_cases._setup(tmp_path)
    _install_valid_review(document, ledger, evaluator, source, review_key)
    model_calls = _install_zero_model_counter(monkeypatch)

    def fail_claim(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(_SECRET_CANARY)

    monkeypatch.setattr(ledger, "claim_canary_capability_and_reserve", fail_claim)
    guard = AdmissionRuntimeGuard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=tmp_path / "responses",
    )
    try:
        with pytest.raises(AdmissionPausedError) as caught:
            guard.begin_product(stage="annotation", product_id=auth_cases._SECOND)
    finally:
        guard.close()

    _assert_sanitized_pause(
        caught.value,
        expected_code="reviewed_capability_claim_failed",
    )
    assert _reservation_count(tmp_path / "budget.sqlite3", auth_cases._SECOND) == 0
    assert _claim_count(tmp_path / "budget.sqlite3") == 0
    assert model_calls == []


def test_d1_5_public_guard_initial_authorization_uses_fresh_evaluation_and_reserve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, ledger, evaluator, _source, _artifacts, _review_key = auth_cases._setup(tmp_path)
    evaluation_calls = 0
    decisions: list[RuntimeAdmissionDecision] = []
    authorized_reserve_calls: list[dict[str, object]] = []
    ordinary_reserve_calls = 0
    original_evaluate = evaluator.evaluate_execution
    original_authorized_reserve = ledger.reserve_product_for_authorized_snapshot
    original_plain_reserve = ledger.reserve_product

    def evaluate(
        document: RunAdmissionDocument,
        active_ledger: BudgetLedger,
    ) -> RuntimeAdmissionDecision:
        nonlocal evaluation_calls
        evaluation_calls += 1
        decision = original_evaluate(document, active_ledger)
        decisions.append(decision)
        return decision

    def authorized_reserve(
        *,
        account_id: str,
        expected_account_revision: int,
        expected_approval_digest: str,
        authorization_evaluated_at: datetime,
        authorization_expires_at: datetime,
        stage: str,
        product_id: str,
        maximum: BudgetAmounts,
    ) -> None:
        authorized_reserve_calls.append(
            {
                "account_id": account_id,
                "account_revision": expected_account_revision,
                "approval_digest": expected_approval_digest,
                "evaluated_at": authorization_evaluated_at,
                "expires_at": authorization_expires_at,
                "target": (stage, product_id),
                "maximum": maximum,
            }
        )
        original_authorized_reserve(
            account_id=account_id,
            expected_account_revision=expected_account_revision,
            expected_approval_digest=expected_approval_digest,
            authorization_evaluated_at=authorization_evaluated_at,
            authorization_expires_at=authorization_expires_at,
            stage=stage,
            product_id=product_id,
            maximum=maximum,
        )

    def plain_reserve(
        account_id: str,
        stage: str,
        product_id: str,
        maximum: BudgetAmounts,
    ) -> None:
        nonlocal ordinary_reserve_calls
        ordinary_reserve_calls += 1
        original_plain_reserve(account_id, stage, product_id, maximum)

    monkeypatch.setattr(evaluator, "evaluate_execution", evaluate)
    monkeypatch.setattr(
        ledger,
        "reserve_product_for_authorized_snapshot",
        authorized_reserve,
    )
    monkeypatch.setattr(ledger, "reserve_product", plain_reserve)
    guard = AdmissionRuntimeGuard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=tmp_path / "responses",
    )
    try:
        guard.begin_product(stage="annotation", product_id=auth_cases._FIRST)
    finally:
        guard.close()

    assert evaluation_calls == 1
    assert ordinary_reserve_calls == 0
    assert len(decisions) == 1
    authorization = decisions[0].authorization
    assert isinstance(authorization, InitialExecutionAuthorization)
    assert authorized_reserve_calls == [
        {
            "account_id": authorization.account_id,
            "account_revision": authorization.account_revision,
            "approval_digest": authorization.account_approval_digest,
            "evaluated_at": authorization.evaluated_at,
            "expires_at": authorization.expires_at,
            "target": ("annotation", auth_cases._FIRST),
            "maximum": auth_cases._PRODUCT_MAX,
        }
    ]


def test_d1_5_product_admission_exposes_same_read_only_execution_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _MutableClock()
    document, ledger, evaluator, _source, _budget_key, _review_key = _initial_runtime_context(
        tmp_path, clock
    )
    observed: list[RuntimeAdmissionDecision] = []
    original_evaluate = evaluator.evaluate_execution

    def evaluate(
        active_document: RunAdmissionDocument,
        active_ledger: BudgetLedger,
    ) -> RuntimeAdmissionDecision:
        decision = original_evaluate(active_document, active_ledger)
        observed.append(decision)
        return decision

    monkeypatch.setattr(evaluator, "evaluate_execution", evaluate)
    guard = AdmissionRuntimeGuard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=tmp_path / "responses",
    )
    try:
        product = guard.begin_product(
            stage="annotation",
            product_id=auth_cases._FIRST,
        )
    finally:
        guard.close()

    assert len(observed) == 1
    decision_product = cast(_ExecutionDecisionProduct, product)
    assert decision_product.execution_decision is observed[0]
    with pytest.raises(AttributeError):
        object.__setattr__(product, "execution_decision", observed[0])


def test_d1_5_initial_authorization_rejects_second_target_with_zero_reservation(
    tmp_path: Path,
) -> None:
    document, ledger, evaluator, _source, _artifacts, _review_key = auth_cases._setup(tmp_path)
    guard = AdmissionRuntimeGuard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=tmp_path / "responses",
    )
    try:
        with pytest.raises(AdmissionBlockedError) as caught:
            guard.begin_product(stage="annotation", product_id=auth_cases._SECOND)
    finally:
        guard.close()

    assert caught.value.result.state == "BLOCKED"
    assert any(
        blocker.check == "execution_authorization"
        and blocker.code == "execution_target_unauthorized"
        for blocker in caught.value.result.blockers
    )
    assert _reservation_count(tmp_path / "budget.sqlite3", auth_cases._SECOND) == 0


def test_d1_5_initial_authorization_expiry_between_revalidation_and_reserve_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _MutableClock()
    document, ledger, evaluator, _source, _budget_key, _review_key = _initial_runtime_context(
        tmp_path, clock
    )
    model_calls = _install_zero_model_counter(monkeypatch)
    original_revalidate = getattr(evaluator, "revalidate_initial_authorization", None)

    def revalidate(
        active_document: RunAdmissionDocument,
        authorization: InitialExecutionAuthorization,
    ) -> None:
        if original_revalidate is not None:
            original_revalidate(active_document, authorization)
        clock.current = authorization.expires_at

    monkeypatch.setattr(
        evaluator,
        "revalidate_initial_authorization",
        revalidate,
        raising=False,
    )
    guard = AdmissionRuntimeGuard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=tmp_path / "responses",
    )
    try:
        with pytest.raises(
            AdmissionPausedError,
            match="initial_authorized_reservation_failed",
        ):
            guard.begin_product(stage="annotation", product_id=auth_cases._FIRST)
    finally:
        guard.close()

    assert _reservation_count(tmp_path / "budget.sqlite3", auth_cases._FIRST) == 0
    assert model_calls == []


def test_d1_5_initial_authorization_real_budget_revision_drift_reserves_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _MutableClock()
    document, ledger, evaluator, _source, budget_key, _review_key = _initial_runtime_context(
        tmp_path, clock
    )
    model_calls = _install_zero_model_counter(monkeypatch)
    original_revalidate = getattr(evaluator, "revalidate_initial_authorization", None)
    expand = Event()
    expanded = Event()
    expansion_errors: list[BaseException] = []
    initial_authorizations: list[InitialExecutionAuthorization] = []

    def expand_account() -> None:
        expand.wait(timeout=5)
        try:
            authorization = initial_authorizations[0]
            _expand_budget_account(
                document=document,
                ledger=ledger,
                budget_key=budget_key,
                previous_approval_digest=authorization.account_approval_digest,
            )
        except BaseException as exc:
            expansion_errors.append(exc)
        finally:
            expanded.set()

    worker = Thread(target=expand_account)
    worker.start()

    def revalidate(
        active_document: RunAdmissionDocument,
        authorization: InitialExecutionAuthorization,
    ) -> None:
        if original_revalidate is not None:
            original_revalidate(active_document, authorization)
        initial_authorizations.append(authorization)
        expand.set()
        assert expanded.wait(timeout=5)

    monkeypatch.setattr(
        evaluator,
        "revalidate_initial_authorization",
        revalidate,
        raising=False,
    )
    guard = AdmissionRuntimeGuard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=tmp_path / "responses",
    )
    try:
        with pytest.raises(
            AdmissionPausedError,
            match="initial_authorized_reservation_failed",
        ):
            guard.begin_product(stage="annotation", product_id=auth_cases._FIRST)
    finally:
        expand.set()
        worker.join(timeout=5)
        guard.close()

    assert not worker.is_alive()
    assert expansion_errors == []
    assert ledger.account_snapshot(initial_authorizations[0].account_id).revision == 2
    assert _reservation_count(tmp_path / "budget.sqlite3", auth_cases._FIRST) == 0
    assert model_calls == []


def test_d1_5_reviewed_authorization_expiry_after_revalidation_claims_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _MutableClock()
    document, ledger, evaluator, source, _budget_key, review_key = _initial_runtime_context(
        tmp_path, clock
    )
    auth_cases._settle_canary(evaluator, document, ledger)
    initial = evaluator.evaluate_execution(document, ledger)
    source.envelope = auth_cases._signed_review(
        review_key,
        auth_cases._review_payload(document, ledger, initial),
    )
    model_calls = _install_zero_model_counter(monkeypatch)
    original_revalidate = evaluator.revalidate_review_authorization

    def revalidate(
        active_document: RunAdmissionDocument,
        authorization: ReviewedExecutionAuthorization,
    ) -> None:
        original_revalidate(active_document, authorization)
        clock.current = authorization.expires_at

    monkeypatch.setattr(evaluator, "revalidate_review_authorization", revalidate)
    guard = AdmissionRuntimeGuard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=tmp_path / "responses",
    )
    try:
        with pytest.raises(
            AdmissionPausedError,
            match="reviewed_capability_claim_failed",
        ):
            guard.begin_product(stage="annotation", product_id=auth_cases._SECOND)
    finally:
        guard.close()

    assert _claim_count(tmp_path / "budget.sqlite3") == 0
    assert _reservation_count(tmp_path / "budget.sqlite3", auth_cases._SECOND) == 0
    assert model_calls == []


def test_d1_5_authorization_clock_rollback_before_evaluation_reserves_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _MutableClock()
    document, ledger, evaluator, _source, _budget_key, _review_key = _initial_runtime_context(
        tmp_path, clock
    )
    model_calls = _install_zero_model_counter(monkeypatch)
    original_revalidate = getattr(evaluator, "revalidate_initial_authorization", None)

    def revalidate(
        active_document: RunAdmissionDocument,
        authorization: InitialExecutionAuthorization,
    ) -> None:
        if original_revalidate is not None:
            original_revalidate(active_document, authorization)
        clock.current = authorization.evaluated_at - timedelta(microseconds=1)

    monkeypatch.setattr(
        evaluator,
        "revalidate_initial_authorization",
        revalidate,
        raising=False,
    )
    guard = AdmissionRuntimeGuard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=tmp_path / "responses",
    )
    try:
        with pytest.raises(
            AdmissionPausedError,
            match="initial_authorized_reservation_failed",
        ):
            guard.begin_product(stage="annotation", product_id=auth_cases._FIRST)
    finally:
        guard.close()

    assert _reservation_count(tmp_path / "budget.sqlite3", auth_cases._FIRST) == 0
    assert model_calls == []


def test_d1_5_reviewed_authorization_revalidates_and_claims_signed_values_verbatim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, ledger, evaluator, source, _artifacts, review_key = auth_cases._setup(tmp_path)
    initial = evaluator.evaluate_execution(document, ledger)
    payload = auth_cases._review_payload(document, ledger, initial)
    source.envelope = auth_cases._signed_review(review_key, payload)
    expected = evaluator.evaluate_execution(document, ledger)
    authorization = expected.authorization
    assert isinstance(authorization, ReviewedExecutionAuthorization)

    revalidated: list[ReviewedExecutionAuthorization] = []
    claim_calls: list[dict[str, object]] = []
    ordinary_reserve_calls = 0
    original_revalidate = evaluator.revalidate_review_authorization
    original_claim = ledger.claim_canary_capability_and_reserve
    original_reserve = ledger.reserve_product

    def revalidate(
        active_document: RunAdmissionDocument,
        active_authorization: ReviewedExecutionAuthorization,
    ) -> None:
        revalidated.append(active_authorization)
        original_revalidate(active_document, active_authorization)

    def claim(
        *,
        account_id: str,
        capability_digest: str,
        canary_stage: str,
        canary_product_id: str,
        expected_settlement_digest: str,
        authorization_evaluated_at: datetime,
        authorization_expires_at: datetime,
        target_stage: str,
        target_product_id: str,
        target_maximum: BudgetAmounts,
        granted_targets: tuple[tuple[str, str], ...],
    ) -> None:
        claim_calls.append(
            {
                "account_id": account_id,
                "capability_digest": capability_digest,
                "expected_settlement_digest": expected_settlement_digest,
                "evaluated_at": authorization_evaluated_at,
                "expires_at": authorization_expires_at,
                "target": (target_stage, target_product_id),
                "target_maximum": target_maximum,
                "granted_targets": granted_targets,
            }
        )
        original_claim(
            account_id=account_id,
            capability_digest=capability_digest,
            canary_stage=canary_stage,
            canary_product_id=canary_product_id,
            expected_settlement_digest=expected_settlement_digest,
            authorization_evaluated_at=authorization_evaluated_at,
            authorization_expires_at=authorization_expires_at,
            target_stage=target_stage,
            target_product_id=target_product_id,
            target_maximum=target_maximum,
            granted_targets=granted_targets,
        )

    def reserve(
        account_id: str,
        stage: str,
        product_id: str,
        maximum: BudgetAmounts,
    ) -> None:
        nonlocal ordinary_reserve_calls
        ordinary_reserve_calls += 1
        original_reserve(account_id, stage, product_id, maximum)

    monkeypatch.setattr(evaluator, "revalidate_review_authorization", revalidate)
    monkeypatch.setattr(ledger, "claim_canary_capability_and_reserve", claim)
    monkeypatch.setattr(ledger, "reserve_product", reserve)
    guard = AdmissionRuntimeGuard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=tmp_path / "responses",
    )
    try:
        guard.begin_product(stage="annotation", product_id=auth_cases._SECOND)
    finally:
        guard.close()

    assert revalidated == [authorization]
    assert ordinary_reserve_calls == 0
    assert claim_calls == [
        {
            "account_id": authorization.account_id,
            "capability_digest": authorization.capability_digest,
            "expected_settlement_digest": authorization.settlement_snapshot_digest,
            "evaluated_at": authorization.evaluated_at,
            "expires_at": authorization.expires_at,
            "target": ("annotation", auth_cases._SECOND),
            "target_maximum": auth_cases._PRODUCT_MAX,
            "granted_targets": tuple(
                (target.stage, target.product_id) for target in authorization.targets
            ),
        }
    ]


def _install_valid_review(
    document: RunAdmissionDocument,
    ledger: BudgetLedger,
    evaluator: object,
    source: auth_cases._ReviewSource,
    review_key: object,
) -> ReviewedExecutionAuthorization:
    initial = evaluator.evaluate_execution(document, ledger)  # type: ignore[attr-defined]
    payload = auth_cases._review_payload(document, ledger, initial)
    source.envelope = auth_cases._signed_review(review_key, payload)  # type: ignore[arg-type]
    decision = evaluator.evaluate_execution(document, ledger)  # type: ignore[attr-defined]
    assert isinstance(decision.authorization, ReviewedExecutionAuthorization)
    return decision.authorization


def test_d1_5_derive_to_claim_ledger_drift_does_not_replace_signed_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, ledger, evaluator, source, _artifacts, review_key = auth_cases._setup(tmp_path)
    authorization = _install_valid_review(document, ledger, evaluator, source, review_key)
    original_evaluate = evaluator.evaluate_execution
    drifted = False

    def evaluate(
        active_document: RunAdmissionDocument,
        active_ledger: BudgetLedger,
    ) -> RuntimeAdmissionDecision:
        nonlocal drifted
        decision = original_evaluate(active_document, active_ledger)
        if not drifted:
            with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
                connection.execute(
                    """UPDATE request_attempts SET response_digest=?
                       WHERE product_id=?""",
                    ("a" * 64, auth_cases._FIRST),
                )
            drifted = True
        return decision

    monkeypatch.setattr(evaluator, "evaluate_execution", evaluate)
    guard = AdmissionRuntimeGuard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=tmp_path / "responses",
    )
    try:
        with pytest.raises(AdmissionPausedError, match="reviewed_capability_claim_failed"):
            guard.begin_product(stage="annotation", product_id=auth_cases._SECOND)
    finally:
        guard.close()

    assert authorization.settlement_snapshot_digest != ledger.product_settlement_snapshot_digest(
        ledger.product_settlement_snapshot(
            authorization.account_id,
            "annotation",
            auth_cases._FIRST,
        )
    )
    assert _reservation_count(tmp_path / "budget.sqlite3", auth_cases._SECOND) == 0


def test_d1_5_review_revalidation_failure_never_falls_back_to_plain_reserve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, ledger, evaluator, source, _artifacts, review_key = auth_cases._setup(tmp_path)
    _install_valid_review(document, ledger, evaluator, source, review_key)
    ordinary_calls = 0
    original_reserve = ledger.reserve_product

    def reject_review(
        _document: RunAdmissionDocument,
        _authorization: ReviewedExecutionAuthorization,
    ) -> None:
        raise ValueError("test-controlled artifact/time drift")

    def reserve(
        account_id: str,
        stage: str,
        product_id: str,
        maximum: BudgetAmounts,
    ) -> None:
        nonlocal ordinary_calls
        ordinary_calls += 1
        original_reserve(account_id, stage, product_id, maximum)

    monkeypatch.setattr(evaluator, "revalidate_review_authorization", reject_review)
    monkeypatch.setattr(ledger, "reserve_product", reserve)
    guard = AdmissionRuntimeGuard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=tmp_path / "responses",
    )
    try:
        with pytest.raises(AdmissionPausedError, match="reviewed_execution_authorization_invalid"):
            guard.begin_product(stage="annotation", product_id=auth_cases._SECOND)
    finally:
        guard.close()

    assert ordinary_calls == 0
    assert _reservation_count(tmp_path / "budget.sqlite3", auth_cases._SECOND) == 0


def test_d1_5_reviewed_same_target_concurrent_recovery_is_idempotent(
    tmp_path: Path,
) -> None:
    document, ledger, evaluator, source, _artifacts, review_key = auth_cases._setup(tmp_path)
    _install_valid_review(document, ledger, evaluator, source, review_key)
    guard = AdmissionRuntimeGuard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=tmp_path / "responses",
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            admissions = list(
                executor.map(
                    lambda _: guard.begin_product(
                        stage="annotation", product_id=auth_cases._SECOND
                    ),
                    range(2),
                )
            )
    finally:
        guard.close()

    assert len(admissions) == 2
    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM canary_capability_claims").fetchone() == (
            1,
        )
    assert _reservation_count(tmp_path / "budget.sqlite3", auth_cases._SECOND) == 1
