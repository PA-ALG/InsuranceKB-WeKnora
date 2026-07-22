"""OpenSpec 020 D1.5: resume candidate persistence after settlement."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, fields
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast, get_type_hints

import pytest

from insurance_harness.compiler.models import RunManifest
from insurance_harness.compiler.pipeline import RunResult
from insurance_harness.goldenset.admission import (
    InitialExecutionAuthorization,
    RuntimeAdmissionDecision,
)
from insurance_harness.goldenset.admission_artifacts import CanaryArtifactBundle
from insurance_harness.goldenset.admission_runtime import AdmissionPausedError

_MODULE_NAME = "insurance_harness.goldenset.run_020"
_FIRST_CANARY = "平安爱满分（2026）两全保险"
_SECOND_CANARY = "平安附加（2026）意外伤害保险"


@pytest.fixture
def entrypoint_module() -> ModuleType:
    return import_module(_MODULE_NAME)


@dataclass(slots=True)
class _DurableRunState:
    artifact: CanaryArtifactBundle | None = None
    settled: bool = False
    drifted: bool = False


class _SessionLock:
    def __init__(self, events: list[str], held: list[bool]) -> None:
        self._events = events
        self._held = held

    def __enter__(self) -> _SessionLock:
        assert self._held == [False]
        self._held[0] = True
        self._events.append("lock_enter")
        return self

    def __exit__(self, *_error: object) -> None:
        assert self._held == [True]
        self._events.append("lock_exit")
        self._held[0] = False


class _Product:
    def __init__(
        self,
        *,
        events: list[str],
        durable_state: _DurableRunState,
        decision: object,
    ) -> None:
        self._events = events
        self._durable_state = durable_state
        self._decision = decision

    @property
    def execution_decision(self) -> object:
        return self._decision

    def client(self, *, role: str) -> object:
        self._events.append(f"client:{role}")
        return SimpleNamespace(role=role)

    def settle(self) -> None:
        self._events.append("settle")
        self._durable_state.settled = True


class _Guard:
    def __init__(
        self,
        *,
        events: list[str],
        durable_state: _DurableRunState,
        decision: object,
        begin_allowed: bool = True,
    ) -> None:
        self._events = events
        self._durable_state = durable_state
        self._decision = decision
        self._begin_allowed = begin_allowed

    def recover_incomplete_at_startup(self) -> int:
        self._events.append("recover")
        return 0

    def begin_product(self, *, stage: str, product_id: str) -> _Product:
        self._events.append(f"begin:{stage}:{product_id}")
        if not self._begin_allowed:
            raise AssertionError("resume-only path must not begin a new product")
        return _Product(
            events=self._events,
            durable_state=self._durable_state,
            decision=self._decision,
        )

    def close(self) -> None:
        self._events.append("guard_close")


def _document() -> SimpleNamespace:
    return SimpleNamespace(
        plan=SimpleNamespace(
            payload=SimpleNamespace(
                run_identity="020-candidate-resume",
                purpose="D1.5 candidate resume-only persistence",
            )
        )
    )


def _configuration(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        ledger_path=tmp_path / "budget.sqlite3",
        run_root=tmp_path / "runs",
    )


def _annotation_result() -> CanaryArtifactBundle:
    return CanaryArtifactBundle(
        checkpoint=b"checkpoint",
        manifest=b"manifest",
        golden=b"golden",
        quote_verification=b"quote-verification",
        disputed_quality=b"disputed-quality",
        disputed_count=0,
        record_count=1,
        quality_threshold_version="gs-v0.1",
    )


def _baseline_result(tmp_path: Path) -> RunResult:
    return RunResult(
        manifest=RunManifest(run_id="020-resume-baseline", product_dir="product"),
        pred_path=tmp_path / "pred.jsonl",
        manifest_path=tmp_path / "manifest.json",
        judge_queue_path=tmp_path / "judge-queue.jsonl",
    )


def _canonical_candidate_bytes(artifact: CanaryArtifactBundle) -> bytes:
    payload = {
        "checkpoint_sha256": sha256(artifact.checkpoint).hexdigest(),
        "golden_sha256": sha256(artifact.golden).hexdigest(),
        "manifest_sha256": sha256(artifact.manifest).hexdigest(),
        "quality_threshold_version": artifact.quality_threshold_version,
        "quote_verification_sha256": sha256(
            artifact.quote_verification
        ).hexdigest(),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _fresh_initial_decision() -> RuntimeAdmissionDecision:
    authorization = object.__new__(InitialExecutionAuthorization)
    decision = object.__new__(RuntimeAdmissionDecision)
    object.__setattr__(decision, "result", SimpleNamespace(state="READY"))
    object.__setattr__(decision, "authorization", authorization)
    object.__setattr__(decision, "account", object())
    return decision


class _FreshEvaluator:
    def __init__(self, decision: RuntimeAdmissionDecision) -> None:
        self.decision = decision

    def evaluate_execution(self, _document: object, _ledger: object) -> RuntimeAdmissionDecision:
        return self.decision


def _runner(module: ModuleType) -> Callable[..., Awaitable[None]]:
    return cast(
        Callable[..., Awaitable[None]],
        module._run_ready_command_for_testing,
    )


@asynccontextmanager
async def _no_op_settlement_guard(_run_dir: Path) -> AsyncIterator[None]:
    yield


def _dependencies(**values: object) -> SimpleNamespace:
    values.setdefault("baseline_settlement_guard", _no_op_settlement_guard)
    values.setdefault("operational_finalizer", lambda **_kwargs: None)
    values.setdefault(
        "candidate_admission_boundary",
        lambda **kwargs: cast(
            _FreshEvaluator, kwargs["evaluator"]
        ).evaluate_execution(kwargs["document"], kwargs["ledger"]),
    )
    return SimpleNamespace(**values)


def _assert_resume_context(
    values: dict[str, object],
    *,
    product_id: str,
    document: object,
    evaluator: object,
    ledger: object,
    configuration: object,
) -> None:
    assert values["product_id"] == product_id
    assert values["document"] is document
    assert values["evaluator"] is evaluator
    assert values["ledger"] is ledger
    assert values["configuration"] is configuration


def test_d1_5_ready_dependencies_expose_typed_candidate_resumer_last(
    entrypoint_module: ModuleType,
) -> None:
    dependency_type = entrypoint_module._ReadyCommandDependencies
    assert fields(dependency_type)[-1].name == "candidate_resumer"
    dependency_hints = get_type_hints(
        dependency_type,
        globalns=vars(entrypoint_module),
    )
    assert dependency_hints["candidate_resumer"] is entrypoint_module._CandidateResumer
    resumer_hints = get_type_hints(
        entrypoint_module._CandidateResumer.__call__,
        globalns=vars(entrypoint_module),
    )
    assert resumer_hints["return"] is bool
    assert (
        resumer_hints["evaluator"]
        is entrypoint_module.ProductionAdmissionEvaluator
    )


@pytest.mark.asyncio
async def test_d1_5_candidate_persist_failure_resumes_only_without_second_execution(
    entrypoint_module: ModuleType,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    lock_held = [False]
    state = _DurableRunState()
    decision = object()
    fresh_decision = _fresh_initial_decision()
    document = _document()
    evaluator = _FreshEvaluator(fresh_decision)
    configuration = _configuration(tmp_path)
    ledger = object()
    execution_result = _annotation_result()
    pending_candidates: list[bytes] = []
    resumed_candidates: list[bytes] = []
    persist_failure = RuntimeError("injected candidate persistence failure")

    def session_lock_factory(_account_id: str) -> _SessionLock:
        return _SessionLock(events, lock_held)

    def ledger_factory(path: Path) -> object:
        assert path == configuration.ledger_path
        events.append("ledger")
        return ledger

    guard = _Guard(events=events, durable_state=state, decision=decision)

    def guard_factory(**_values: object) -> _Guard:
        events.append("guard")
        return guard

    def candidate_resumer(**values: object) -> bool:
        assert lock_held == [True]
        assert events[-1] == "recover"
        _assert_resume_context(
            values,
            product_id=_FIRST_CANARY,
            document=document,
            evaluator=evaluator,
            ledger=ledger,
            configuration=configuration,
        )
        if not state.settled and state.artifact is None:
            events.append("candidate_resume:false")
            return False
        assert state.settled is True
        assert state.artifact is not None
        rebuilt = _canonical_candidate_bytes(state.artifact)
        resumed_candidates.append(rebuilt)
        events.append("candidate_resume:true")
        return True

    async def annotation_executor(**_values: object) -> CanaryArtifactBundle:
        events.append("annotation_executor")
        return execution_result

    async def forbidden_baseline_executor(**_values: object) -> RunResult:
        raise AssertionError("candidate resume must not execute the baseline")

    def artifact_committer(**values: object) -> None:
        assert values["execution_result"] is execution_result
        events.append("artifact_commit")
        state.artifact = execution_result

    def candidate_builder(**values: object) -> bytes:
        assert values["execution_decision"] is fresh_decision
        assert values["document"] is document
        assert values["ledger"] is ledger
        events.append("candidate_build")
        return _canonical_candidate_bytes(execution_result)

    def candidate_persister(**values: object) -> None:
        candidate = cast(bytes, values["candidate"])
        pending_candidates.append(candidate)
        events.append("candidate_persist")
        if len(pending_candidates) == 1:
            raise persist_failure

    dependencies = _dependencies(
        session_lock_factory=session_lock_factory,
        ledger_factory=ledger_factory,
        guard_factory=guard_factory,
        annotation_executor=annotation_executor,
        baseline_executor=forbidden_baseline_executor,
        artifact_committer=artifact_committer,
        candidate_builder=candidate_builder,
        candidate_persister=candidate_persister,
        candidate_resumer=candidate_resumer,
    )

    with pytest.raises(RuntimeError) as caught:
        await _runner(entrypoint_module)(
            command="annotate-canary",
            product_id=_FIRST_CANARY,
            document=document,
            evaluator=evaluator,
            configuration=configuration,
            dependencies=dependencies,
        )

    assert caught.value is persist_failure
    assert state.artifact is execution_result
    assert state.settled is True
    assert len(pending_candidates) == 1
    second_run_start = len(events)

    await _runner(entrypoint_module)(
        command="annotate-canary",
        product_id=_FIRST_CANARY,
        document=document,
        evaluator=evaluator,
        configuration=configuration,
        dependencies=dependencies,
    )

    assert events[second_run_start:] == [
        "lock_enter",
        "ledger",
        "guard",
        "recover",
        "candidate_resume:true",
        "guard_close",
        "lock_exit",
    ]
    assert resumed_candidates == pending_candidates


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("artifact_state", "error_code"),
    (
        ("missing", "candidate_resume_artifact_missing"),
        ("drifted", "candidate_resume_artifact_drift"),
    ),
)
async def test_d1_5_settled_candidate_resume_artifact_failure_is_fail_closed(
    entrypoint_module: ModuleType,
    tmp_path: Path,
    artifact_state: str,
    error_code: str,
) -> None:
    events: list[str] = []
    lock_held = [False]
    state = _DurableRunState(
        artifact=_annotation_result() if artifact_state == "drifted" else None,
        settled=True,
        drifted=artifact_state == "drifted",
    )
    decision = object()
    document = _document()
    evaluator = object()
    configuration = _configuration(tmp_path)
    ledger = object()
    guard = _Guard(
        events=events,
        durable_state=state,
        decision=decision,
        begin_allowed=False,
    )

    def candidate_resumer(**values: object) -> bool:
        assert lock_held == [True]
        _assert_resume_context(
            values,
            product_id=_FIRST_CANARY,
            document=document,
            evaluator=evaluator,
            ledger=ledger,
            configuration=configuration,
        )
        events.append(f"candidate_resume:{artifact_state}")
        raise AdmissionPausedError(error_code)

    async def forbidden_executor(**_values: object) -> RunResult:
        raise AssertionError("fail-closed resume must make zero model calls")

    def forbidden_post_begin(**_values: object) -> object:
        raise AssertionError("fail-closed resume must not commit or settle")

    dependencies = _dependencies(
        session_lock_factory=lambda _account_id: _SessionLock(events, lock_held),
        ledger_factory=lambda _path: ledger,
        guard_factory=lambda **_values: guard,
        annotation_executor=forbidden_executor,
        baseline_executor=forbidden_executor,
        artifact_committer=forbidden_post_begin,
        candidate_builder=forbidden_post_begin,
        candidate_persister=forbidden_post_begin,
        candidate_resumer=candidate_resumer,
    )

    with pytest.raises(AdmissionPausedError) as caught:
        await _runner(entrypoint_module)(
            command="annotate-canary",
            product_id=_FIRST_CANARY,
            document=document,
            evaluator=evaluator,
            configuration=configuration,
            dependencies=dependencies,
        )

    assert caught.value.code == error_code
    assert events == [
        "lock_enter",
        "recover",
        f"candidate_resume:{artifact_state}",
        "guard_close",
        "lock_exit",
    ]


@pytest.mark.asyncio
async def test_d1_5_unsettled_without_artifact_resumer_false_starts_normal_begin(
    entrypoint_module: ModuleType,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    lock_held = [False]
    state = _DurableRunState()
    document = _document()
    evaluator = _FreshEvaluator(_fresh_initial_decision())
    configuration = _configuration(tmp_path)
    ledger = object()
    result = _annotation_result()
    guard = _Guard(events=events, durable_state=state, decision=object())

    def candidate_resumer(**values: object) -> bool:
        assert lock_held == [True]
        assert state.settled is False
        assert state.artifact is None
        _assert_resume_context(
            values,
            product_id=_FIRST_CANARY,
            document=document,
            evaluator=evaluator,
            ledger=ledger,
            configuration=configuration,
        )
        events.append("candidate_resume:false")
        return False

    async def annotation_executor(**_values: object) -> CanaryArtifactBundle:
        events.append("annotation_executor")
        return result

    def artifact_committer(**_values: object) -> None:
        events.append("artifact_commit")
        state.artifact = result

    def candidate_builder(**_values: object) -> bytes:
        events.append("candidate_build")
        return _canonical_candidate_bytes(result)

    def candidate_persister(**_values: object) -> None:
        events.append("candidate_persist")

    dependencies = _dependencies(
        session_lock_factory=lambda _account_id: _SessionLock(events, lock_held),
        ledger_factory=lambda _path: ledger,
        guard_factory=lambda **_values: guard,
        annotation_executor=annotation_executor,
        baseline_executor=lambda **_values: None,
        artifact_committer=artifact_committer,
        candidate_builder=candidate_builder,
        candidate_persister=candidate_persister,
        candidate_resumer=candidate_resumer,
    )

    await _runner(entrypoint_module)(
        command="annotate-canary",
        product_id=_FIRST_CANARY,
        document=document,
        evaluator=evaluator,
        configuration=configuration,
        dependencies=dependencies,
    )

    assert events == [
        "lock_enter",
        "recover",
        "candidate_resume:false",
        f"begin:annotation:{_FIRST_CANARY}",
        "client:annotator",
        "annotation_executor",
        "artifact_commit",
        "settle",
        "candidate_build",
        "candidate_persist",
        "guard_close",
        "lock_exit",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "product_id"),
    (
        ("annotate-canary", _SECOND_CANARY),
        ("baseline-product", _FIRST_CANARY),
    ),
)
async def test_d1_5_candidate_resumer_is_never_called_outside_first_canary_annotation(
    entrypoint_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    product_id: str,
) -> None:
    events: list[str] = []
    state = _DurableRunState()
    result = _annotation_result()
    baseline = _baseline_result(tmp_path)
    guard = _Guard(events=events, durable_state=state, decision=object())
    monkeypatch.setattr(entrypoint_module, "execution_plan_hash", lambda _document: "a" * 64)
    resumer_calls = 0

    def forbidden_resumer(**_values: object) -> bool:
        nonlocal resumer_calls
        resumer_calls += 1
        raise AssertionError("candidate resume is exclusive to the first annotation canary")

    async def annotation_executor(**_values: object) -> CanaryArtifactBundle:
        return result

    async def baseline_executor(**_values: object) -> RunResult:
        return baseline

    dependencies = _dependencies(
        session_lock_factory=lambda _account_id: _SessionLock(events, [False]),
        ledger_factory=lambda _path: object(),
        guard_factory=lambda **_values: guard,
        annotation_executor=annotation_executor,
        baseline_executor=baseline_executor,
        artifact_committer=lambda **_values: None,
        candidate_builder=lambda **_values: object(),
        candidate_persister=lambda **_values: None,
        candidate_resumer=forbidden_resumer,
    )

    await _runner(entrypoint_module)(
        command=command,
        product_id=product_id,
        document=_document(),
        evaluator=object(),
        configuration=_configuration(tmp_path),
        dependencies=dependencies,
    )

    assert resumer_calls == 0
