"""OpenSpec 020 D1.3b/D1.5: adversarial admitted-runtime security tests."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
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
    AttemptKey,
    BudgetLedger,
    BudgetLedgerError,
    budget_account_identity,
)
from insurance_harness.goldenset.admission_models import ModelRolePlan
from insurance_harness.goldenset.admission_runtime import (
    AdmissionPausedError,
    AdmissionRuntimeGuard,
    request_unit_fingerprint,
)
from tests import test_run_admission_runtime_020 as runtime_cases

_CHAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_SECRET_CANARY = "SECRET-CANARY"


def _response_files(root: Path) -> tuple[Path, ...]:
    return tuple(path for path in root.rglob("*") if path.is_file())


def _attempt_key(
    document: RunAdmissionDocument,
    *,
    system: str = runtime_cases._SYSTEM,
    user: str = runtime_cases._USER,
) -> AttemptKey:
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
            role=runtime_cases._ROLE,
            role_plan=role_plan,
            system=system,
            user=user,
        ),
        attempt_no=1,
    )


def _production_guard(
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


async def test_d1_3b_response_root_rename_and_symlink_swap_stays_on_open_dirfd(
    tmp_path: Path,
) -> None:
    invoker = runtime_cases._CountingInvoker()
    guard, _, ledger, response_root, document, _ = runtime_cases._runtime(
        tmp_path,
        invoker=invoker,
    )
    opened_directory = response_root.with_name("opened-response-directory")
    attacker_directory = tmp_path / "attacker"
    attacker_directory.mkdir()
    response_root.rename(opened_directory)
    response_root.symlink_to(attacker_directory, target_is_directory=True)

    response = await runtime_cases._client(guard).complete(
        runtime_cases._SYSTEM,
        runtime_cases._USER,
    )

    assert response == "durable answer"
    assert _response_files(attacker_directory) == ()
    assert len(_response_files(opened_directory)) == 1
    assert ledger.attempt_snapshot(_attempt_key(document)).state == "terminal"
    assert invoker.calls == 1


def test_d1_3b_response_root_parent_symlink_is_rejected(tmp_path: Path) -> None:
    _, _, ledger, _, document, evaluator = runtime_cases._runtime(tmp_path / "setup")
    actual_parent = tmp_path / "actual-parent"
    actual_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(actual_parent, target_is_directory=True)

    with pytest.raises(AdmissionPausedError, match="response_root_unsafe"):
        AdmissionRuntimeGuard._for_testing(
            document=document,
            evaluator=evaluator,
            ledger=ledger,
            response_root=linked_parent / "responses",
            model_invoker=runtime_cases._CountingInvoker(),
        )

    assert not (actual_parent / "responses").exists()


def test_d1_3b_response_root_must_be_owned_by_current_effective_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, ledger, _, document, evaluator = runtime_cases._runtime(tmp_path / "setup")
    candidate = tmp_path / "foreign-owned-response-root"
    candidate.mkdir()
    actual_owner = candidate.stat().st_uid
    monkeypatch.setattr(os, "geteuid", lambda: actual_owner + 1)

    with pytest.raises(AdmissionPausedError, match="response_root_unsafe"):
        AdmissionRuntimeGuard._for_testing(
            document=document,
            evaluator=evaluator,
            ledger=ledger,
            response_root=candidate,
            model_invoker=runtime_cases._CountingInvoker(),
        )


def test_d1_3b_new_nested_response_root_fsyncs_each_parent_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, ledger, _, document, evaluator = runtime_cases._runtime(tmp_path / "setup")
    fsync_calls: list[int] = []
    original_fsync = os.fsync

    def tracking_fsync(descriptor: int) -> None:
        fsync_calls.append(descriptor)
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", tracking_fsync)
    guard = AdmissionRuntimeGuard._for_testing(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=tmp_path / "new-parent" / "new-response-root",
        model_invoker=runtime_cases._CountingInvoker(),
    )

    assert len(fsync_calls) == 2
    guard.close()


class _OversizedChunkedBody(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"choices":[{"message":{"content":"'
        chunk = b"a" * (1024 * 1024)
        for _ in range(17):
            yield chunk
        yield b'"},"finish_reason":"stop"}]}'

    async def aclose(self) -> None:
        return None


def _oversized_provider_response(mode: str) -> httpx.Response:
    if mode == "content-length":
        body = b'{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'
        return httpx.Response(
            200,
            headers={"Content-Length": str(_MAX_RESPONSE_BYTES + 1)},
            content=body,
        )
    assert mode == "chunked"
    return httpx.Response(
        200,
        headers={"Transfer-Encoding": "chunked"},
        stream=_OversizedChunkedBody(),
    )


@pytest.mark.parametrize("mode", ("content-length", "chunked"))
@respx.mock
async def test_d1_3b_production_invoker_bounds_provider_response_before_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    _, _, ledger, response_root, document, evaluator = runtime_cases._runtime(tmp_path)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", "provider-key-for-size-test")
    respx.post(_CHAT_URL).mock(return_value=_oversized_provider_response(mode))
    guard = _production_guard(document, evaluator, ledger, response_root)
    client = runtime_cases._client(guard)

    with pytest.raises(AdmissionPausedError) as caught:
        await client.complete(runtime_cases._SYSTEM, runtime_cases._USER)

    assert caught.value.code == "provider_response_too_large"
    account = ledger.account_snapshot(_attempt_key(document).account_id)
    assert account.uncertain == runtime_cases._REQUEST_MAXIMUM
    assert _response_files(response_root) == ()


def _exception_chain_text(error: BaseException) -> str:
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    rendered: list[str] = []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        rendered.extend((str(current), repr(current)))
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return "\n".join(rendered)


def _assert_sanitized_pause(
    error: AdmissionPausedError,
    *,
    expected_code: str,
) -> None:
    assert error.code == expected_code
    assert error.__cause__ is None
    assert error.__context__ is None
    assert _SECRET_CANARY not in _exception_chain_text(error)


def test_d1_3b_response_store_exception_chain_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_guard, _, ledger, _, document, evaluator = runtime_cases._runtime(
        tmp_path / "seed"
    )
    seed_guard.close()

    def fail_open(_root: Path) -> int:
        raise OSError(_SECRET_CANARY)

    monkeypatch.setattr(admission_runtime, "_open_owned_directory", fail_open)
    with pytest.raises(AdmissionPausedError) as caught:
        AdmissionRuntimeGuard._for_testing(
            document=document,
            evaluator=evaluator,
            ledger=ledger,
            response_root=tmp_path / "unsafe-response-root",
            model_invoker=runtime_cases._CountingInvoker(),
            enforce_execution_authorization=False,
        )

    _assert_sanitized_pause(caught.value, expected_code="response_root_unsafe")


async def test_d1_3b_request_claim_exception_chain_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoker = runtime_cases._CountingInvoker()
    guard, _, ledger, _, _, _ = runtime_cases._runtime(tmp_path, invoker=invoker)
    client = runtime_cases._client(guard)

    def fail_claim(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError(_SECRET_CANARY)

    monkeypatch.setattr(ledger, "claim_attempt", fail_claim)
    with pytest.raises(AdmissionPausedError) as caught:
        await client.complete(runtime_cases._SYSTEM, runtime_cases._USER)

    _assert_sanitized_pause(caught.value, expected_code="request_budget_claim_failed")
    assert invoker.calls == 0


def test_d1_3b_product_settlement_exception_chain_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoker = runtime_cases._CountingInvoker()
    guard, _, ledger, _, _, _ = runtime_cases._runtime(tmp_path, invoker=invoker)
    product = guard.begin_product(stage=runtime_cases._STAGE, product_id="product-01")

    def fail_settlement(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(_SECRET_CANARY)

    monkeypatch.setattr(ledger, "settle_product", fail_settlement)
    with pytest.raises(AdmissionPausedError) as caught:
        product.settle()

    _assert_sanitized_pause(
        caught.value,
        expected_code="product_budget_settlement_failed",
    )
    assert invoker.calls == 0


async def test_d1_3b_model_invoker_exception_chain_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoker = runtime_cases._CountingInvoker()
    guard, _, ledger, _, document, _ = runtime_cases._runtime(tmp_path, invoker=invoker)
    client = runtime_cases._client(guard)

    async def fail_model(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError(_SECRET_CANARY)

    monkeypatch.setattr(invoker, "complete", fail_model)
    with pytest.raises(AdmissionPausedError) as caught:
        await client.complete(runtime_cases._SYSTEM, runtime_cases._USER)

    _assert_sanitized_pause(caught.value, expected_code="model_attempt_ambiguous")
    assert ledger.account_snapshot(_attempt_key(document).account_id).uncertain == (
        runtime_cases._REQUEST_MAXIMUM
    )


@respx.mock
async def test_d1_3b_provider_exception_chain_never_leaks_key_or_prompts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = "sk-CANARY-DO-NOT-LEAK"
    system = "SYSTEM-CANARY-DO-NOT-LEAK"
    user = "USER-CANARY-DO-NOT-LEAK"
    monkeypatch.setattr(runtime_cases, "_SYSTEM", system)
    monkeypatch.setattr(runtime_cases, "_USER", user)
    _, _, ledger, response_root, document, evaluator = runtime_cases._runtime(tmp_path)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", api_key)

    def fail_with_sensitive_request(request: httpx.Request) -> httpx.Response:
        raise httpx.RequestError(
            f"provider failure headers={request.headers!r} system={system} user={user}",
            request=request,
        )

    respx.post(_CHAT_URL).mock(side_effect=fail_with_sensitive_request)
    guard = _production_guard(document, evaluator, ledger, response_root)

    with pytest.raises(AdmissionPausedError) as caught:
        await runtime_cases._client(guard).complete(system, user)

    rendered = _exception_chain_text(caught.value)
    for canary in (api_key, system, user):
        assert canary not in rendered
    account = ledger.account_snapshot(_attempt_key(document, system=system, user=user).account_id)
    assert account.uncertain == runtime_cases._REQUEST_MAXIMUM
    assert _response_files(response_root) == ()


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"choices": []},
        {"choices": [None]},
        {"choices": [{"message": None}]},
        {"choices": [{"message": {"content": 123}}]},
    ),
)
@respx.mock
async def test_d1_3b_malformed_provider_shapes_are_typed_and_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    _, _, ledger, response_root, document, evaluator = runtime_cases._runtime(tmp_path)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", "shape-test-key")
    respx.post(_CHAT_URL).mock(return_value=httpx.Response(200, json=payload))
    guard = _production_guard(document, evaluator, ledger, response_root)

    with pytest.raises(AdmissionPausedError) as caught:
        await runtime_cases._client(guard).complete(runtime_cases._SYSTEM, runtime_cases._USER)

    assert caught.value.code == "provider_response_invalid"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert _response_files(response_root) == ()


async def test_d1_5_closed_guard_blocks_existing_client_before_invocation(
    tmp_path: Path,
) -> None:
    invoker = runtime_cases._CountingInvoker()
    guard, _, _, _, _, _ = runtime_cases._runtime(tmp_path, invoker=invoker)
    client = runtime_cases._client(guard)
    guard.close()

    with pytest.raises(AdmissionPausedError, match="runtime_guard_closed"):
        await client.complete(runtime_cases._SYSTEM, runtime_cases._USER)

    assert invoker.calls == 0


async def test_d1_3b_close_during_provider_call_keeps_request_dirfd_lease(
    tmp_path: Path,
) -> None:
    invoker = runtime_cases._BlockingInvoker()
    guard, _, ledger, response_root, document, _ = runtime_cases._runtime(tmp_path, invoker=invoker)
    client = runtime_cases._client(guard)
    task = asyncio.create_task(client.complete(runtime_cases._SYSTEM, runtime_cases._USER))
    await invoker.started.wait()

    guard.close()
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    descriptors = [os.open(decoy, os.O_RDONLY) for _ in range(4)]
    try:
        invoker.release.set()
        assert await task == "durable answer"
    finally:
        for descriptor in descriptors:
            os.close(descriptor)

    assert len(_response_files(response_root)) == 1
    assert _response_files(decoy) == ()
    assert ledger.attempt_snapshot(_attempt_key(document)).state == "terminal"
    assert invoker.calls == 1
    with pytest.raises(AdmissionPausedError, match="runtime_guard_closed"):
        await client.complete(runtime_cases._SYSTEM, runtime_cases._USER)
    assert invoker.calls == 1


def test_d1_5_evaluator_fault_is_typed_and_constructs_no_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoker = runtime_cases._CountingInvoker()
    guard, _, _, _, _, evaluator = runtime_cases._runtime(
        tmp_path,
        invoker=invoker,
    )

    def evaluator_fault(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("raw evaluator storage fault")

    monkeypatch.setattr(evaluator, "admit_budget_account", evaluator_fault)

    with pytest.raises(AdmissionPausedError) as caught:
        guard.begin_product(stage=runtime_cases._STAGE, product_id="product-01")

    assert caught.value.code == "admission_evaluation_failed"
    assert invoker.calls == 0


def test_d1_3b_ledger_fault_is_typed_and_constructs_no_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoker = runtime_cases._CountingInvoker()
    guard, _, ledger, _, _, _ = runtime_cases._runtime(tmp_path, invoker=invoker)

    def ledger_fault(*_args: object, **_kwargs: object) -> None:
        raise OSError("raw ledger storage fault")

    monkeypatch.setattr(ledger, "reserve_product", ledger_fault)

    with pytest.raises(AdmissionPausedError) as caught:
        guard.begin_product(stage=runtime_cases._STAGE, product_id="product-01")

    assert caught.value.code == "product_budget_reservation_failed"
    assert invoker.calls == 0


async def test_d1_3b_mark_uncertain_failure_has_distinct_typed_pause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoker = runtime_cases._FailingInvoker()
    guard, _, ledger, response_root, _, _ = runtime_cases._runtime(
        tmp_path,
        invoker=invoker,
    )
    client = runtime_cases._client(guard)

    def settlement_fault(*_args: object, **_kwargs: object) -> None:
        raise BudgetLedgerError("uncertain settlement storage fault")

    monkeypatch.setattr(ledger, "mark_uncertain", settlement_fault)

    with pytest.raises(AdmissionPausedError) as caught:
        await client.complete(runtime_cases._SYSTEM, runtime_cases._USER)

    assert caught.value.code == "uncertain_settlement_failed"
    assert invoker.calls == 1
    assert _response_files(response_root) == ()
