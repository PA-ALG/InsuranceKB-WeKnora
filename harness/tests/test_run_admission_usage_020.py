"""OpenSpec 020 D1.5: typed provider usage and durable provenance."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pytest
import respx

import insurance_harness.goldenset.admission_runtime as admission_runtime
from insurance_harness.goldenset.admission import (
    ProductionAdmissionEvaluator,
    RunAdmissionDocument,
)
from insurance_harness.goldenset.admission_budget import (
    SQLITE_SAFE_INTEGER_MAX,
    AttemptKey,
    BudgetAmounts,
    BudgetLedger,
    RoleRate,
    budget_account_identity,
)
from insurance_harness.goldenset.admission_models import ModelRolePlan
from insurance_harness.goldenset.admission_runtime import (
    AdmissionPausedError,
    AdmissionRuntimeGuard,
    ApprovedModelResponse,
    request_unit_fingerprint,
)
from tests import test_run_admission_runtime_020 as runtime_cases


class _UsageInvoker(runtime_cases._CountingInvoker):
    async def complete(
        self,
        role_plan: ModelRolePlan,
        maximum: BudgetAmounts,
        system: str,
        user: str,
    ) -> ApprovedModelResponse:
        self._record(role_plan, maximum, system, user)
        return ApprovedModelResponse(
            content="durable answer",
            input_tokens=123,
            output_tokens=45,
            usage_verified=True,
        )


def _attempt_key(document: RunAdmissionDocument) -> AttemptKey:
    role_plan = document.plan.payload.model_roles[runtime_cases._ROLE]
    assert isinstance(role_plan, ModelRolePlan)
    return AttemptKey(
        account_id=budget_account_identity(
            document.plan.payload.run_identity,
            document.plan.payload.purpose,
        ),
        stage=runtime_cases._STAGE,
        product_id="product-01",
        request_unit=request_unit_fingerprint(
            runtime_cases._ROLE,
            role_plan,
            runtime_cases._SYSTEM,
            runtime_cases._USER,
        ),
        attempt_no=1,
    )


def _production_invoker_test_guard(
    *,
    document: RunAdmissionDocument,
    evaluator: ProductionAdmissionEvaluator,
    ledger: BudgetLedger,
    response_root: Path,
) -> AdmissionRuntimeGuard:
    return AdmissionRuntimeGuard._for_testing(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=response_root,
        model_invoker=admission_runtime._BailianApprovedModelInvoker(),
        enforce_execution_authorization=False,
    )


async def test_d1_5_valid_provider_usage_persists_exact_actual_and_verified(
    tmp_path: Path,
) -> None:
    invoker = _UsageInvoker()
    guard, _, ledger, _, document, _ = runtime_cases._runtime(
        tmp_path,
        invoker=invoker,
    )

    assert (
        await runtime_cases._client(guard).complete(runtime_cases._SYSTEM, runtime_cases._USER)
        == "durable answer"
    )

    snapshot = ledger.attempt_snapshot(_attempt_key(document))
    assert snapshot.state == "terminal"
    expected_actual = BudgetAmounts(
        input_tokens=123,
        output_tokens=45,
        cost_minor_units=2,
    )
    assert snapshot.actual == expected_actual
    assert snapshot.charged == expected_actual
    assert snapshot.usage_verified is True
    assert invoker.calls == 1


@respx.mock
async def test_d1_5_bailian_usage_is_strict_and_cost_uses_signed_role_rate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, ledger, response_root, document, evaluator = runtime_cases._runtime(
        tmp_path,
        weak_input_rate=50_000,
        weak_output_rate=100_000,
    )
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", "usage-test-key")
    route = respx.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "provider answer"}}],
                "usage": {"prompt_tokens": 123, "completion_tokens": 45},
            },
        )
    )
    guard = _production_invoker_test_guard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=response_root,
    )

    assert (
        await runtime_cases._client(guard).complete(runtime_cases._SYSTEM, runtime_cases._USER)
        == "provider answer"
    )

    snapshot = ledger.attempt_snapshot(_attempt_key(document))
    expected_actual = BudgetAmounts(
        input_tokens=123,
        output_tokens=45,
        cost_minor_units=12,
    )
    assert snapshot.actual == expected_actual
    assert snapshot.charged == expected_actual
    assert snapshot.usage_verified is True
    assert route.call_count == 1


@pytest.mark.parametrize(
    "usage",
    (
        pytest.param("missing", id="missing"),
        pytest.param("malformed", id="malformed"),
        pytest.param(
            {"prompt_tokens": True, "completion_tokens": 45},
            id="boolean",
        ),
        pytest.param(
            {"prompt_tokens": -1, "completion_tokens": 45},
            id="negative",
        ),
    ),
)
@respx.mock
async def test_d1_5_unverified_usage_charges_full_reserve_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    usage: object,
) -> None:
    _, _, ledger, response_root, document, evaluator = runtime_cases._runtime(tmp_path)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", "usage-test-key")
    payload: dict[str, object] = {"choices": [{"message": {"content": "provider answer"}}]}
    if usage != "missing":
        payload["usage"] = usage
    route = respx.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=payload)
    )
    guard = _production_invoker_test_guard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=response_root,
    )
    client = runtime_cases._client(guard)

    assert await client.complete(runtime_cases._SYSTEM, runtime_cases._USER) == "provider answer"
    assert await client.complete(runtime_cases._SYSTEM, runtime_cases._USER) == "provider answer"

    snapshot = ledger.attempt_snapshot(_attempt_key(document))
    assert snapshot.state == "terminal"
    assert snapshot.actual == runtime_cases._REQUEST_MAXIMUM
    assert snapshot.charged == runtime_cases._REQUEST_MAXIMUM
    assert snapshot.usage_verified is False
    assert route.call_count == 1


@respx.mock
async def test_d1_5_verified_usage_over_bound_marks_overage_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, ledger, response_root, document, evaluator = runtime_cases._runtime(tmp_path)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", "usage-test-key")
    route = respx.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "provider answer"}}],
                "usage": {"prompt_tokens": 701, "completion_tokens": 45},
            },
        )
    )
    guard = _production_invoker_test_guard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=response_root,
    )
    client = runtime_cases._client(guard)

    assert await client.complete(runtime_cases._SYSTEM, runtime_cases._USER) == "provider answer"
    assert await client.complete(runtime_cases._SYSTEM, runtime_cases._USER) == "provider answer"

    snapshot = ledger.attempt_snapshot(_attempt_key(document))
    assert snapshot.state == "terminal"
    assert snapshot.charged.input_tokens == 701
    assert snapshot.usage_verified is True
    assert ledger.account_snapshot(snapshot.key.account_id).overage is True
    assert route.call_count == 1
    with pytest.raises(
        AdmissionPausedError,
        match="product_budget_reservation_failed",
    ):
        guard.begin_product(stage=runtime_cases._STAGE, product_id="product-02")
    assert route.call_count == 1


@respx.mock
async def test_d1_5_unrepresentable_provider_usage_is_terminal_overage_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, ledger, response_root, document, evaluator = runtime_cases._runtime(tmp_path)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", "usage-test-key")
    route = respx.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "provider answer"}}],
                "usage": {
                    "prompt_tokens": 2**63,
                    "completion_tokens": 45,
                },
            },
        )
    )
    guard = _production_invoker_test_guard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=response_root,
    )
    client = runtime_cases._client(guard)

    assert await client.complete(runtime_cases._SYSTEM, runtime_cases._USER) == "provider answer"
    assert await client.complete(runtime_cases._SYSTEM, runtime_cases._USER) == "provider answer"

    snapshot = ledger.attempt_snapshot(_attempt_key(document))
    assert snapshot.state == "terminal"
    assert snapshot.actual == runtime_cases._REQUEST_MAXIMUM
    assert snapshot.charged == runtime_cases._REQUEST_MAXIMUM
    assert snapshot.usage_verified is False
    assert ledger.account_snapshot(snapshot.key.account_id).overage is True
    assert route.call_count == 1


def test_d1_5_signed_rate_cost_overflow_is_not_treated_as_verified_usage() -> None:
    response = ApprovedModelResponse(
        content="provider answer",
        input_tokens=SQLITE_SAFE_INTEGER_MAX,
        output_tokens=SQLITE_SAFE_INTEGER_MAX,
        usage_verified=True,
    )
    rate = RoleRate(
        model_role_identity_hash="a" * 64,
        input_cost_per_million_minor_units=SQLITE_SAFE_INTEGER_MAX,
        output_cost_per_million_minor_units=SQLITE_SAFE_INTEGER_MAX,
    )

    assert admission_runtime._verified_actual(response, rate) is None


def _downgrade_to_v2(db_path: Path) -> list[tuple[object, ...]]:
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE request_attempts_v2 (
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
            INSERT INTO request_attempts_v2 (
                account_id,stage,product_id,request_unit,attempt_no,
                owner_token_digest,role,limit_kind,state,
                max_input,max_output,max_cost,
                actual_input,actual_output,actual_cost,
                charged_input,charged_output,charged_cost,response_digest,
                provider_proof_digest,provider_request_id,
                provider_verifier_policy,provider_proof_observed_at
            )
            SELECT account_id,stage,product_id,request_unit,attempt_no,
                   owner_token_digest,role,limit_kind,state,
                   max_input,max_output,max_cost,
                   actual_input,actual_output,actual_cost,
                   charged_input,charged_output,charged_cost,response_digest,
                   provider_proof_digest,provider_request_id,
                   provider_verifier_policy,provider_proof_observed_at
            FROM request_attempts;
            DROP TABLE request_attempts;
            ALTER TABLE request_attempts_v2 RENAME TO request_attempts;
            PRAGMA user_version = 2;
            COMMIT;
            """
        )
        rows = connection.execute("SELECT * FROM request_attempts ORDER BY attempt_no").fetchall()
    return [tuple(row) for row in rows]


async def test_d1_5_v2_schema_migration_preserves_rows_and_marks_usage_unverified(
    tmp_path: Path,
) -> None:
    invoker = _UsageInvoker()
    guard, _, _ledger, _, document, _ = runtime_cases._runtime(
        tmp_path,
        invoker=invoker,
    )
    assert (
        await runtime_cases._client(guard).complete(runtime_cases._SYSTEM, runtime_cases._USER)
        == "durable answer"
    )
    db_path = tmp_path / "budget.sqlite3"
    old_rows = _downgrade_to_v2(db_path)

    migrated = BudgetLedger(db_path)

    with sqlite3.connect(db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()
        new_rows = connection.execute(
            """SELECT account_id,stage,product_id,request_unit,attempt_no,
                      owner_token_digest,role,limit_kind,state,
                      max_input,max_output,max_cost,
                      actual_input,actual_output,actual_cost,
                      charged_input,charged_output,charged_cost,response_digest,
                      provider_proof_digest,provider_request_id,
                      provider_verifier_policy,provider_proof_observed_at
               FROM request_attempts ORDER BY attempt_no"""
        ).fetchall()
    assert version == (4,)
    assert [tuple(row) for row in new_rows] == old_rows
    assert migrated.attempt_snapshot(_attempt_key(document)).usage_verified is False
