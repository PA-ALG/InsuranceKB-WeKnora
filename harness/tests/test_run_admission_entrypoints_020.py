"""OpenSpec 020 D1.5: formal guarded single-product entrypoint contracts."""

from __future__ import annotations

import argparse
import ast
import asyncio
import inspect
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import NoReturn, cast

import pytest

from insurance_harness.compiler.models import RunManifest
from insurance_harness.compiler.pipeline import RunResult
from insurance_harness.goldenset.admission import (
    AdmissionBlocker,
    AdmissionResult,
    InitialExecutionAuthorization,
    RuntimeAdmissionDecision,
)
from insurance_harness.goldenset.admission_artifacts import CanaryArtifactBundle
from insurance_harness.goldenset.admission_runtime import (
    AdmissionBlockedError,
    AdmissionPausedError,
)

_MODULE_NAME = "insurance_harness.goldenset.run_020"
_SOURCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src/insurance_harness/goldenset/run_020.py"
)
_FIRST_CANARY = "平安爱满分（2026）两全保险"
_SECOND_CANARY = "平安附加（2026）意外伤害保险"
_COMMANDS = ("annotate-canary", "baseline-product")


@pytest.fixture
def entrypoint_module() -> ModuleType:
    """Activate behavioral contracts only after the production module exists.

    The separate source-existence test is the first RED checkpoint.  This keeps the
    remaining failures meaningful instead of reporting the same ImportError for every
    parser, bootstrap, and fail-closed contract.
    """

    if not _SOURCE_PATH.is_file():
        pytest.skip("D1.5 production entrypoint has not been created yet")
    return import_module(_MODULE_NAME)


def _parser(module: ModuleType) -> argparse.ArgumentParser:
    factory = cast(
        Callable[[], argparse.ArgumentParser],
        module._build_parser,
    )
    return factory()


def _parse_rejected(parser: argparse.ArgumentParser, argv: list[str]) -> None:
    with pytest.raises((SystemExit, ValueError)):
        parser.parse_args(argv)


def test_d1_5_production_entrypoint_source_exists() -> None:
    assert _SOURCE_PATH.is_file(), (
        "D1.5 requires insurance_harness.goldenset.run_020 before guarded commands "
        "can be implemented"
    )


@pytest.mark.parametrize("command", _COMMANDS)
def test_d1_5_entrypoint_accepts_exactly_one_product(
    entrypoint_module: ModuleType,
    command: str,
) -> None:
    parsed = _parser(entrypoint_module).parse_args(
        [command, "--product", _FIRST_CANARY]
    )

    assert vars(parsed) == {"command": command, "product": _FIRST_CANARY}


@pytest.mark.parametrize("command", _COMMANDS)
def test_d1_5_entrypoint_rejects_missing_or_repeated_product(
    entrypoint_module: ModuleType,
    command: str,
) -> None:
    parser = _parser(entrypoint_module)

    _parse_rejected(parser, [command])
    _parse_rejected(
        parser,
        [
            command,
            "--product",
            _FIRST_CANARY,
            "--product",
            "另一个产品",
        ],
    )


@pytest.mark.parametrize("command", _COMMANDS)
@pytest.mark.parametrize(
    "forbidden_arguments",
    (
        ("--unknown", "value"),
        ("--force",),
        ("--probe",),
        ("--trust", "/tmp/trust.yaml"),
        ("--model", "unapproved-model"),
        ("--key", "secret"),
        ("--path", "/tmp/input"),
        ("--line", "endowment"),
        ("--resume",),
    ),
)
def test_d1_5_entrypoint_rejects_non_product_overrides(
    entrypoint_module: ModuleType,
    command: str,
    forbidden_arguments: tuple[str, ...],
) -> None:
    _parse_rejected(
        _parser(entrypoint_module),
        [command, "--product", _FIRST_CANARY, *forbidden_arguments],
    )


def test_d1_5_production_bootstrap_forces_remote_probe_and_fixed_paths(
    entrypoint_module: ModuleType,
) -> None:
    configuration_factory = cast(
        Callable[[], object],
        entrypoint_module._production_configuration,
    )
    configuration = configuration_factory()
    module_file = entrypoint_module.__file__
    assert module_file is not None
    repository_root = Path(module_file).resolve().parents[4]
    state_root = Path("/var/lib/insurancekb/run-admission")

    expected = {
        "repo_root": repository_root,
        "plan_path": (
            repository_root
            / "openspec/changes/020-golden-v01-baseline-run/run-admission.yaml"
        ),
        "trust_path": Path("/etc/insurancekb/run-admission-trust.yaml"),
        "review_inbox": state_root / "canary-review-inbox",
        "ledger_path": state_root / "budget.sqlite3",
        "session_root": state_root / "sessions",
        "run_root": state_root / "runs",
        "probe": True,
    }
    assert {
        field_name: getattr(configuration, field_name) for field_name in expected
    } == expected


class _BlockedEvaluator:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def __call__(self, _document: object) -> SimpleNamespace:
        self._events.append("evaluate")
        return SimpleNamespace(state="BLOCKED")


class _ReadyEvaluator:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def __call__(self, _document: object) -> SimpleNamespace:
        self._events.append("evaluate")
        return SimpleNamespace(state="READY")


def _unexpected_construction(events: list[str], label: str) -> Callable[..., NoReturn]:
    def fail(*_args: object, **_kwargs: object) -> NoReturn:
        events.append(label)
        raise AssertionError(f"BLOCKED preflight constructed {label}")

    return fail


def _install_construction_bombs(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
) -> None:
    for name in (
        "_open_budget_ledger",
        "_build_runtime_guard",
        "_execute_annotation",
        "_execute_baseline",
        "BudgetLedger",
        "AdmissionRuntimeGuard",
        "GoldenAnnotator",
        "ExtractionPipeline",
    ):
        monkeypatch.setattr(
            module,
            name,
            _unexpected_construction(events, name),
            raising=False,
        )


@pytest.mark.parametrize("command", _COMMANDS)
def test_d1_5_blocked_entrypoint_constructs_no_ledger_client_or_pipeline(
    entrypoint_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    events: list[str] = []
    document = SimpleNamespace(
        identity_request=SimpleNamespace(
            products=(SimpleNamespace(product_id=_FIRST_CANARY),),
        )
    )

    def load_document(_configuration: object) -> object:
        events.append("load_document")
        return document

    def build_evaluator(_configuration: object) -> _BlockedEvaluator:
        events.append("build_evaluator")
        return _BlockedEvaluator(events)

    monkeypatch.setattr(
        entrypoint_module,
        "_load_production_document",
        load_document,
    )
    monkeypatch.setattr(
        entrypoint_module,
        "_build_production_evaluator",
        build_evaluator,
    )
    _install_construction_bombs(entrypoint_module, monkeypatch, events)

    main = cast(Callable[[list[str]], int], entrypoint_module.main)
    assert main([command, "--product", _FIRST_CANARY]) == 2
    # 031 A-C deliberately fail closed before the legacy 020 evaluator or any
    # runtime dependency is constructed. D owns the canonical finalizer wiring
    # that restores the downstream execution assertions.
    assert events == []


@pytest.mark.parametrize("command", _COMMANDS)
@pytest.mark.parametrize(
    "requested_product",
    (
        "不存在的产品",
        unicodedata.normalize("NFKC", _FIRST_CANARY),
    ),
)
def test_d1_5_product_must_exactly_match_typed_identity_before_ledger_or_client(
    entrypoint_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    requested_product: str,
) -> None:
    assert requested_product != _FIRST_CANARY
    events: list[str] = []
    document = SimpleNamespace(
        identity_request=SimpleNamespace(
            products=(SimpleNamespace(product_id=_FIRST_CANARY),),
        )
    )

    def load_document(_configuration: object) -> object:
        events.append("load_document")
        return document

    def build_evaluator(_configuration: object) -> _ReadyEvaluator:
        events.append("build_evaluator")
        return _ReadyEvaluator(events)

    monkeypatch.setattr(
        entrypoint_module,
        "_load_production_document",
        load_document,
    )
    monkeypatch.setattr(
        entrypoint_module,
        "_build_production_evaluator",
        build_evaluator,
    )
    _install_construction_bombs(entrypoint_module, monkeypatch, events)

    main = cast(Callable[[list[str]], int], entrypoint_module.main)
    assert main([command, "--product", requested_product]) == 2
    assert events == []


def _qualified_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def test_d1_5_production_entrypoint_imports_or_constructs_no_raw_model_client() -> None:
    if not _SOURCE_PATH.is_file():
        pytest.skip("D1.5 production entrypoint has not been created yet")
    tree = ast.parse(_SOURCE_PATH.read_text(encoding="utf-8"), filename=str(_SOURCE_PATH))
    forbidden_modules = {
        "httpx",
        "litellm",
        "insurance_harness.compiler.llm",
    }
    forbidden_constructors = {
        "AsyncClient",
        "LiteLLMClient",
        "OpenAICompatClient",
        "ReplayClient",
        "_BailianApprovedModelInvoker",
    }

    imported_modules: set[str] = set()
    imported_names: set[str] = set()
    constructed_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                imported_modules.add(node.module)
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Call):
            name = _qualified_name(node.func)
            if name:
                constructed_names.add(name.rsplit(".", maxsplit=1)[-1])

    assert forbidden_modules.isdisjoint(imported_modules)
    assert forbidden_constructors.isdisjoint(imported_names)
    assert forbidden_constructors.isdisjoint(constructed_names)


class _FakeSessionLock:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def __enter__(self) -> _FakeSessionLock:
        self._events.append("lock_enter")
        return self

    def __exit__(self, *_exc: object) -> None:
        self._events.append("lock_exit")


class _FakeProductAdmission:
    def __init__(
        self,
        events: list[str],
        execution_decision: object,
        phase_probe: Callable[[str], None] | None = None,
        settle_error: BaseException | None = None,
    ) -> None:
        self._events = events
        self._execution_decision = execution_decision
        self._phase_probe = phase_probe
        self._settle_error = settle_error

    @property
    def execution_decision(self) -> object:
        return self._execution_decision

    def client(self, *, role: str) -> object:
        self._events.append(f"client:{role}")
        return SimpleNamespace(role=role)

    def settle(self) -> None:
        self._events.append("settle")
        if self._phase_probe is not None:
            self._phase_probe("settle")
        if self._settle_error is not None:
            raise self._settle_error


class _FakeRuntimeGuard:
    def __init__(
        self,
        events: list[str],
        *,
        begin_error: Exception | None = None,
        execution_decision: object | None = None,
        phase_probe: Callable[[str], None] | None = None,
        settle_error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self._events = events
        self._begin_error = begin_error
        self._execution_decision = execution_decision or object()
        self._phase_probe = phase_probe
        self._settle_error = settle_error
        self._close_error = close_error

    def recover_incomplete_at_startup(self) -> int:
        self._events.append("recover")
        if self._phase_probe is not None:
            self._phase_probe("recovery")
        return 0

    def begin_product(self, *, stage: str, product_id: str) -> _FakeProductAdmission:
        self._events.append(f"begin:{stage}:{product_id}")
        if self._begin_error is not None:
            raise self._begin_error
        return _FakeProductAdmission(
            self._events,
            self._execution_decision,
            self._phase_probe,
            self._settle_error,
        )

    def close(self) -> None:
        self._events.append("guard_close")
        if self._close_error is not None:
            raise self._close_error


def _ready_dependencies(module: ModuleType, **values: object) -> object:
    factory = cast(
        Callable[..., object],
        module._ReadyCommandDependencies,
    )
    return factory(**values)


def _ready_runner(module: ModuleType) -> Callable[..., Awaitable[None]]:
    return cast(
        Callable[..., Awaitable[None]],
        module._run_ready_command_for_testing,
    )


def _ready_document() -> SimpleNamespace:
    return SimpleNamespace(
        plan=SimpleNamespace(
            payload=SimpleNamespace(
                run_identity="020-ready-entrypoint",
                purpose="D1.5 guarded single-product execution",
            )
        )
    )


def _ready_configuration() -> SimpleNamespace:
    return SimpleNamespace(
        ledger_path=Path("/var/lib/insurancekb/run-admission/budget.sqlite3"),
        run_root=Path("/var/lib/insurancekb/run-admission/runs"),
    )


def _annotation_execution_result() -> CanaryArtifactBundle:
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


def _fresh_initial_decision() -> RuntimeAdmissionDecision:
    authorization = object.__new__(InitialExecutionAuthorization)
    decision = object.__new__(RuntimeAdmissionDecision)
    object.__setattr__(decision, "result", SimpleNamespace(state="READY"))
    object.__setattr__(decision, "authorization", authorization)
    object.__setattr__(decision, "account", object())
    return decision


class _FreshCandidateEvaluator:
    def __init__(
        self,
        decision: RuntimeAdmissionDecision,
        callback: Callable[[], None] | None = None,
    ) -> None:
        self.decision = decision
        self.callback = callback
        self.calls: list[tuple[object, object]] = []

    def evaluate_execution(self, document: object, ledger: object) -> RuntimeAdmissionDecision:
        self.calls.append((document, ledger))
        if self.callback is not None:
            self.callback()
        return self.decision


def _baseline_execution_result(tmp_path: Path) -> RunResult:
    return RunResult(
        manifest=RunManifest(run_id="020-ready-baseline", product_dir="product"),
        pred_path=tmp_path / "pred.jsonl",
        manifest_path=tmp_path / "manifest.json",
        judge_queue_path=tmp_path / "judge-queue.jsonl",
    )


def test_d1_5_main_ready_is_typed_blocked_until_031_finalizer_is_wired(
    entrypoint_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    document = _ready_document()
    document.identity_request = SimpleNamespace(
        products=(SimpleNamespace(product_id=_FIRST_CANARY),)
    )
    evaluator = _ReadyEvaluator(events)

    def load_document(_configuration: object) -> object:
        events.append("load_document")
        return document

    def build_evaluator(_configuration: object) -> _ReadyEvaluator:
        events.append("build_evaluator")
        return evaluator

    async def run_ready_command(
        *,
        command: str,
        product_id: str,
        document: object,
        evaluator: object,
        configuration: object,
    ) -> None:
        del configuration
        assert command == "annotate-canary"
        assert product_id == _FIRST_CANARY
        assert document is globals_document
        assert evaluator is globals_evaluator
        events.append("production_dispatch")

    globals_document = document
    globals_evaluator = evaluator
    monkeypatch.setattr(entrypoint_module, "_load_production_document", load_document)
    monkeypatch.setattr(entrypoint_module, "_build_production_evaluator", build_evaluator)
    monkeypatch.setattr(
        entrypoint_module,
        "_run_ready_command",
        run_ready_command,
        raising=False,
    )

    main = cast(Callable[[list[str]], int], entrypoint_module.main)
    assert main(["annotate-canary", "--product", _FIRST_CANARY]) == 2
    assert events == []


def test_d1_5_main_returns_two_when_fresh_product_boundary_is_blocked(
    entrypoint_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    document = _ready_document()
    document.identity_request = SimpleNamespace(
        products=(SimpleNamespace(product_id=_FIRST_CANARY),)
    )
    evaluator = _ReadyEvaluator(events)
    blocked_result = AdmissionResult(
        state="BLOCKED",
        plan_payload_hash="a" * 64,
        evaluated_revision="f" * 40,
        evaluated_at=datetime(2026, 7, 20, tzinfo=UTC),
        checker_version="020.1",
        runtime_capability_version="budget-ledger-v1",
        checks=(),
        blockers=(AdmissionBlocker(check="identity", code="product_drift"),),
    )

    def load_document(_configuration: object) -> object:
        events.append("load_document")
        return document

    def build_evaluator(_configuration: object) -> _ReadyEvaluator:
        events.append("build_evaluator")
        return evaluator

    async def run_ready_command(**_kwargs: object) -> None:
        events.append("fresh_boundary")
        raise AdmissionBlockedError(blocked_result)

    monkeypatch.setattr(entrypoint_module, "_load_production_document", load_document)
    monkeypatch.setattr(entrypoint_module, "_build_production_evaluator", build_evaluator)
    monkeypatch.setattr(entrypoint_module, "_run_ready_command", run_ready_command)

    main = cast(Callable[[list[str]], int], entrypoint_module.main)
    assert main(["annotate-canary", "--product", _FIRST_CANARY]) == 2
    assert events == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "stage", "expected_roles", "executor_event"),
    (
        ("annotate-canary", "annotation", ("annotator",), "annotation_executor"),
        (
            "baseline-product",
            "baseline",
            ("weak_extractor", "judge"),
            "baseline_executor",
        ),
    ),
)
async def test_d1_5_ready_entrypoint_commits_exact_executor_result_under_one_lock(
    entrypoint_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    stage: str,
    expected_roles: tuple[str, ...],
    executor_event: str,
) -> None:
    from insurance_harness.goldenset.admission_budget import (
        budget_account_identity,
    )

    events: list[str] = []
    plan_hash = "a" * 64
    monkeypatch.setattr(entrypoint_module, "execution_plan_hash", lambda _document: plan_hash)
    document = _ready_document()
    configuration = _ready_configuration()
    fresh_decision = _fresh_initial_decision()
    evaluator: object = (
        _FreshCandidateEvaluator(
            fresh_decision,
            lambda: events.append("fresh_evaluate"),
        )
        if command == "annotate-canary"
        else object()
    )
    execution_decision = object()
    ledger = object()
    guard = _FakeRuntimeGuard(events, execution_decision=execution_decision)
    execution_result: CanaryArtifactBundle | RunResult = (
        _annotation_execution_result()
        if command == "annotate-canary"
        else _baseline_execution_result(tmp_path)
    )
    candidate = object()

    def session_lock_factory(account_id: str) -> _FakeSessionLock:
        events.append(f"lock_factory:{account_id}")
        return _FakeSessionLock(events)

    def ledger_factory(path: Path) -> object:
        assert path == configuration.ledger_path
        events.append("ledger")
        return ledger

    def guard_factory(
        *,
        document: object,
        evaluator: object,
        ledger: object,
        response_root: Path,
    ) -> _FakeRuntimeGuard:
        del document, evaluator, ledger
        assert response_root.is_relative_to(configuration.run_root)
        events.append("guard")
        return guard

    async def annotation_executor(
        *,
        document: object,
        product_id: str,
        client: object,
        configuration: object,
    ) -> CanaryArtifactBundle:
        del configuration
        assert document is globals_document
        assert product_id == _FIRST_CANARY
        assert cast(SimpleNamespace, client).role == "annotator"
        events.append("annotation_executor")
        assert isinstance(execution_result, CanaryArtifactBundle)
        return execution_result

    globals_document = document

    async def baseline_executor(
        *,
        document: object,
        product_id: str,
        extractor_client: object,
        judge_client: object,
        configuration: object,
    ) -> RunResult:
        del configuration
        assert document is globals_document
        assert product_id == _FIRST_CANARY
        assert cast(SimpleNamespace, extractor_client).role == "weak_extractor"
        assert cast(SimpleNamespace, judge_client).role == "judge"
        events.append("baseline_executor")
        assert isinstance(execution_result, RunResult)
        return execution_result

    def artifact_committer(
        *,
        document: object,
        command: str,
        product_id: str,
        execution_result: CanaryArtifactBundle | RunResult,
        configuration: object,
    ) -> None:
        del configuration
        assert document is globals_document
        assert command in _COMMANDS
        assert product_id == _FIRST_CANARY
        assert execution_result is globals_execution_result
        events.append("artifact_commit_verify")

    globals_execution_result = execution_result

    def candidate_builder(
        *,
        document: object,
        ledger: object,
        execution_decision: object,
        configuration: object,
    ) -> object:
        del configuration
        assert command == "annotate-canary"
        assert document is globals_document
        assert ledger is globals_ledger
        assert execution_decision is globals_fresh_decision
        events.append("candidate_build")
        return candidate

    globals_fresh_decision = fresh_decision
    globals_ledger = ledger

    def candidate_persister(*, candidate: object, configuration: object) -> None:
        del configuration
        assert candidate is globals_candidate
        events.append("candidate_persist")

    globals_candidate = candidate

    @asynccontextmanager
    async def baseline_settlement_guard(run_dir: Path) -> AsyncIterator[None]:
        assert run_dir == (
            configuration.run_root
            / plan_hash
            / entrypoint_module._baseline_target_digest(_FIRST_CANARY)
        )
        events.append("settlement_guard_enter")
        yield
        events.append("settlement_guard_exit")

    dependencies = _ready_dependencies(
        entrypoint_module,
        session_lock_factory=session_lock_factory,
        ledger_factory=ledger_factory,
        guard_factory=guard_factory,
        annotation_executor=annotation_executor,
        baseline_executor=baseline_executor,
        artifact_committer=artifact_committer,
        candidate_builder=candidate_builder,
        candidate_persister=candidate_persister,
        baseline_settlement_guard=baseline_settlement_guard,
    )
    await _ready_runner(entrypoint_module)(
        command=command,
        product_id=_FIRST_CANARY,
        document=document,
        evaluator=evaluator,
        configuration=configuration,
        dependencies=dependencies,
    )

    account_id = budget_account_identity(
        document.plan.payload.run_identity,
        document.plan.payload.purpose,
    )
    assert events == [
        f"lock_factory:{account_id}",
        "lock_enter",
        "ledger",
        "guard",
        "recover",
        f"begin:{stage}:{_FIRST_CANARY}",
        *(f"client:{role}" for role in expected_roles),
        executor_event,
        *(("settlement_guard_enter",) if command == "baseline-product" else ()),
        "artifact_commit_verify",
        "settle",
        *(("settlement_guard_exit",) if command == "baseline-product" else ()),
        *(
            ("fresh_evaluate", "candidate_build", "candidate_persist")
            if command == "annotate-canary"
            else ()
        ),
        "guard_close",
        "lock_exit",
    ]


@pytest.mark.asyncio
async def test_d1_5_ready_dispatch_keeps_real_cross_process_lock_for_every_phase(
    entrypoint_module: ModuleType,
    tmp_path: Path,
) -> None:
    from tests import test_run_admission_session_lock_020 as lock_cases

    root = lock_cases._secure_lock_root(tmp_path)
    document = _ready_document()
    configuration = _ready_configuration()
    execution_decision = object()
    fresh_decision = _fresh_initial_decision()
    execution_result = _annotation_execution_result()
    events: list[str] = []
    account_ids: list[str] = []

    def assert_locked(phase: str) -> None:
        events.append(phase)
        assert len(account_ids) == 1
        assert lock_cases._probe_lock_once(root, account_ids[0]) == "blocked"

    guard = _FakeRuntimeGuard(
        events,
        execution_decision=execution_decision,
        phase_probe=assert_locked,
    )

    def session_lock_factory(account_id: str) -> object:
        account_ids.append(account_id)
        return lock_cases._lock(root, account_id)

    def ledger_factory(_path: Path) -> object:
        assert_locked("ledger")
        return object()

    def guard_factory(**_kwargs: object) -> _FakeRuntimeGuard:
        assert_locked("guard")
        return guard

    async def annotation_executor(**_kwargs: object) -> CanaryArtifactBundle:
        assert_locked("executor")
        return execution_result

    async def forbidden_baseline_executor(**_kwargs: object) -> RunResult:
        raise AssertionError("annotation command must not construct baseline clients")

    def artifact_committer(*, execution_result: object, **_kwargs: object) -> None:
        assert execution_result is globals_execution_result
        assert_locked("artifact")

    globals_execution_result = execution_result

    def candidate_builder(
        *, execution_decision: object, **_kwargs: object
    ) -> object:
        assert execution_decision is globals_fresh_decision
        assert_locked("candidate_build")
        return object()

    globals_fresh_decision = fresh_decision

    def candidate_persister(**_kwargs: object) -> None:
        assert_locked("candidate_persist")

    dependencies = _ready_dependencies(
        entrypoint_module,
        session_lock_factory=session_lock_factory,
        ledger_factory=ledger_factory,
        guard_factory=guard_factory,
        annotation_executor=annotation_executor,
        baseline_executor=forbidden_baseline_executor,
        artifact_committer=artifact_committer,
        candidate_builder=candidate_builder,
        candidate_persister=candidate_persister,
    )
    await _ready_runner(entrypoint_module)(
        command="annotate-canary",
        product_id=_FIRST_CANARY,
        document=document,
        evaluator=_FreshCandidateEvaluator(
            fresh_decision,
            lambda: assert_locked("fresh_evaluate"),
        ),
        configuration=configuration,
        dependencies=dependencies,
    )

    assert {"recovery", "executor", "artifact", "settle"}.issubset(events)
    assert len(account_ids) == 1
    assert lock_cases._probe_lock_once(root, account_ids[0]) == "acquired"


@pytest.mark.asyncio
@pytest.mark.parametrize("command", _COMMANDS)
async def test_d1_5_begin_blocked_constructs_zero_client_executor_model_or_settlement(
    entrypoint_module: ModuleType,
    command: str,
) -> None:
    events: list[str] = []
    blocked = RuntimeError("fresh authorization blocked this product")
    guard = _FakeRuntimeGuard(events, begin_error=blocked)

    def session_lock_factory(_account_id: str) -> _FakeSessionLock:
        return _FakeSessionLock(events)

    def ledger_factory(_path: Path) -> object:
        events.append("ledger")
        return object()

    def guard_factory(**_kwargs: object) -> _FakeRuntimeGuard:
        events.append("guard")
        return guard

    async def forbidden_executor(**_kwargs: object) -> None:
        events.append("forbidden_executor")

    def forbidden_post_begin(**_kwargs: object) -> object:
        events.append("forbidden_post_begin")
        return object()

    dependencies = _ready_dependencies(
        entrypoint_module,
        session_lock_factory=session_lock_factory,
        ledger_factory=ledger_factory,
        guard_factory=guard_factory,
        annotation_executor=forbidden_executor,
        baseline_executor=forbidden_executor,
        artifact_committer=forbidden_post_begin,
        candidate_builder=forbidden_post_begin,
        candidate_persister=forbidden_post_begin,
    )
    with pytest.raises(RuntimeError, match="fresh authorization blocked"):
        await _ready_runner(entrypoint_module)(
            command=command,
            product_id=_FIRST_CANARY,
            document=_ready_document(),
            evaluator=_FreshCandidateEvaluator(_fresh_initial_decision()),
            configuration=_ready_configuration(),
            dependencies=dependencies,
        )

    assert events == [
        "lock_enter",
        "ledger",
        "guard",
        "recover",
        f"begin:{'annotation' if command == 'annotate-canary' else 'baseline'}:"
        f"{_FIRST_CANARY}",
        "guard_close",
        "lock_exit",
    ]


@pytest.mark.asyncio
async def test_d1_5_renderer_error_causes_zero_commit_settle_or_candidate(
    entrypoint_module: ModuleType,
) -> None:
    events: list[str] = []
    guard = _FakeRuntimeGuard(events)

    def session_lock_factory(_account_id: str) -> _FakeSessionLock:
        return _FakeSessionLock(events)

    def ledger_factory(_path: Path) -> object:
        events.append("ledger")
        return object()

    def guard_factory(**_kwargs: object) -> _FakeRuntimeGuard:
        events.append("guard")
        return guard

    async def failing_annotation_executor(**_kwargs: object) -> None:
        events.append("annotation_executor")
        raise AdmissionPausedError("annotation_quote_verification_failed")

    async def forbidden_baseline_executor(**_kwargs: object) -> None:
        events.append("forbidden_baseline_executor")

    def forbidden_post_execution(**_kwargs: object) -> object:
        events.append("forbidden_post_execution")
        return object()

    dependencies = _ready_dependencies(
        entrypoint_module,
        session_lock_factory=session_lock_factory,
        ledger_factory=ledger_factory,
        guard_factory=guard_factory,
        annotation_executor=failing_annotation_executor,
        baseline_executor=forbidden_baseline_executor,
        artifact_committer=forbidden_post_execution,
        candidate_builder=forbidden_post_execution,
        candidate_persister=forbidden_post_execution,
    )
    with pytest.raises(AdmissionPausedError) as error:
        await _ready_runner(entrypoint_module)(
            command="annotate-canary",
            product_id=_FIRST_CANARY,
            document=_ready_document(),
            evaluator=_FreshCandidateEvaluator(_fresh_initial_decision()),
            configuration=_ready_configuration(),
            dependencies=dependencies,
        )

    assert error.value.code == "annotation_quote_verification_failed"

    assert events == [
        "lock_enter",
        "ledger",
        "guard",
        "recover",
        f"begin:annotation:{_FIRST_CANARY}",
        "client:annotator",
        "annotation_executor",
        "guard_close",
        "lock_exit",
    ]


@pytest.mark.asyncio
async def test_d1_5_baseline_verifier_error_causes_zero_settlement_or_candidate(
    entrypoint_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    guard = _FakeRuntimeGuard(events)
    baseline_result = _baseline_execution_result(tmp_path)
    monkeypatch.setattr(entrypoint_module, "execution_plan_hash", lambda _document: "a" * 64)

    def session_lock_factory(_account_id: str) -> _FakeSessionLock:
        return _FakeSessionLock(events)

    def ledger_factory(_path: Path) -> object:
        events.append("ledger")
        return object()

    def guard_factory(**_kwargs: object) -> _FakeRuntimeGuard:
        events.append("guard")
        return guard

    async def forbidden_annotation_executor(**_kwargs: object) -> None:
        events.append("forbidden_annotation_executor")

    async def baseline_executor(**_kwargs: object) -> RunResult:
        events.append("baseline_executor")
        return baseline_result

    def failing_artifact_committer(**_kwargs: object) -> None:
        events.append("baseline_artifact_verify")
        raise AdmissionPausedError("baseline_artifact_path_unsafe")

    def forbidden_candidate(**_kwargs: object) -> object:
        events.append("forbidden_candidate")
        return object()

    dependencies = _ready_dependencies(
        entrypoint_module,
        session_lock_factory=session_lock_factory,
        ledger_factory=ledger_factory,
        guard_factory=guard_factory,
        annotation_executor=forbidden_annotation_executor,
        baseline_executor=baseline_executor,
        artifact_committer=failing_artifact_committer,
        candidate_builder=forbidden_candidate,
        candidate_persister=forbidden_candidate,
    )
    with pytest.raises(AdmissionPausedError) as error:
        await _ready_runner(entrypoint_module)(
            command="baseline-product",
            product_id=_FIRST_CANARY,
            document=_ready_document(),
            evaluator=object(),
            configuration=_ready_configuration(),
            dependencies=dependencies,
        )

    assert error.value.code == "baseline_artifact_path_unsafe"
    assert events == [
        "lock_enter",
        "ledger",
        "guard",
        "recover",
        f"begin:baseline:{_FIRST_CANARY}",
        "client:weak_extractor",
        "client:judge",
        "baseline_executor",
        "baseline_artifact_verify",
        "guard_close",
        "lock_exit",
    ]


def _annotation_lifecycle_dependencies(
    module: ModuleType,
    *,
    events: list[str],
    guard: _FakeRuntimeGuard,
    failure_phase: str | None = None,
    primary_error: BaseException | None = None,
) -> object:
    def session_lock_factory(_account_id: str) -> _FakeSessionLock:
        return _FakeSessionLock(events)

    def ledger_factory(_path: Path) -> object:
        events.append("ledger")
        return object()

    def guard_factory(**_kwargs: object) -> _FakeRuntimeGuard:
        events.append("guard")
        return guard

    async def annotation_executor(**_kwargs: object) -> CanaryArtifactBundle:
        events.append("annotation_executor")
        if failure_phase == "executor" and primary_error is not None:
            raise primary_error
        return _annotation_execution_result()

    async def forbidden_baseline_executor(**_kwargs: object) -> RunResult:
        raise AssertionError("annotation command must not execute the baseline")

    def artifact_committer(**_kwargs: object) -> None:
        events.append("artifact_commit_verify")
        if failure_phase == "artifact" and primary_error is not None:
            raise primary_error

    def candidate_builder(**_kwargs: object) -> object:
        events.append("candidate_build")
        return object()

    def candidate_persister(**_kwargs: object) -> None:
        events.append("candidate_persist")

    return _ready_dependencies(
        module,
        session_lock_factory=session_lock_factory,
        ledger_factory=ledger_factory,
        guard_factory=guard_factory,
        annotation_executor=annotation_executor,
        baseline_executor=forbidden_baseline_executor,
        artifact_committer=artifact_committer,
        candidate_builder=candidate_builder,
        candidate_persister=candidate_persister,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_phase", ("executor", "artifact", "settle"))
async def test_d1_5_guard_close_failure_preserves_active_product_error(
    entrypoint_module: ModuleType,
    failure_phase: str,
) -> None:
    events: list[str] = []
    primary_error = RuntimeError(f"{failure_phase} failed")
    close_error = RuntimeError("guard close failed")
    guard = _FakeRuntimeGuard(
        events,
        settle_error=primary_error if failure_phase == "settle" else None,
        close_error=close_error,
    )
    dependencies = _annotation_lifecycle_dependencies(
        entrypoint_module,
        events=events,
        guard=guard,
        failure_phase=failure_phase,
        primary_error=primary_error,
    )

    with pytest.raises(RuntimeError) as caught:
        await _ready_runner(entrypoint_module)(
            command="annotate-canary",
            product_id=_FIRST_CANARY,
            document=_ready_document(),
            evaluator=_FreshCandidateEvaluator(_fresh_initial_decision()),
            configuration=_ready_configuration(),
            dependencies=dependencies,
        )

    assert caught.value is primary_error
    assert events[-2:] == ["guard_close", "lock_exit"]


@pytest.mark.asyncio
async def test_d1_5_guard_close_failure_preserves_asyncio_cancellation(
    entrypoint_module: ModuleType,
) -> None:
    events: list[str] = []
    cancellation = asyncio.CancelledError()
    guard = _FakeRuntimeGuard(
        events,
        close_error=RuntimeError("guard close failed"),
    )
    dependencies = _annotation_lifecycle_dependencies(
        entrypoint_module,
        events=events,
        guard=guard,
        failure_phase="executor",
        primary_error=cancellation,
    )

    with pytest.raises(asyncio.CancelledError) as caught:
        await _ready_runner(entrypoint_module)(
            command="annotate-canary",
            product_id=_FIRST_CANARY,
            document=_ready_document(),
            evaluator=object(),
            configuration=_ready_configuration(),
            dependencies=dependencies,
        )

    assert caught.value is cancellation
    assert events[-2:] == ["guard_close", "lock_exit"]


@pytest.mark.asyncio
async def test_d1_5_guard_close_failure_propagates_without_active_error(
    entrypoint_module: ModuleType,
) -> None:
    events: list[str] = []
    close_error = RuntimeError("guard close failed")
    guard = _FakeRuntimeGuard(events, close_error=close_error)
    dependencies = _annotation_lifecycle_dependencies(
        entrypoint_module,
        events=events,
        guard=guard,
    )

    with pytest.raises(RuntimeError) as caught:
        await _ready_runner(entrypoint_module)(
            command="annotate-canary",
            product_id=_FIRST_CANARY,
            document=_ready_document(),
            evaluator=_FreshCandidateEvaluator(_fresh_initial_decision()),
            configuration=_ready_configuration(),
            dependencies=dependencies,
        )

    assert caught.value is close_error
    assert events[-4:] == [
        "candidate_build",
        "candidate_persist",
        "guard_close",
        "lock_exit",
    ]


@pytest.mark.asyncio
async def test_d1_5_second_reviewed_annotation_settles_without_new_candidate(
    entrypoint_module: ModuleType,
) -> None:
    events: list[str] = []
    guard = _FakeRuntimeGuard(events)
    dependencies = _annotation_lifecycle_dependencies(
        entrypoint_module,
        events=events,
        guard=guard,
    )

    await _ready_runner(entrypoint_module)(
        command="annotate-canary",
        product_id=_SECOND_CANARY,
        document=_ready_document(),
        evaluator=object(),
        configuration=_ready_configuration(),
        dependencies=dependencies,
    )

    assert events == [
        "lock_enter",
        "ledger",
        "guard",
        "recover",
        f"begin:annotation:{_SECOND_CANARY}",
        "client:annotator",
        "annotation_executor",
        "artifact_commit_verify",
        "settle",
        "guard_close",
        "lock_exit",
    ]


def _calls_named(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _qualified_name(node.func).rsplit(".", maxsplit=1)[-1] == name
    ]


def _keyword_names(call: ast.Call) -> set[str]:
    return {keyword.arg for keyword in call.keywords if keyword.arg is not None}


def test_d1_5_ready_executors_use_current_annotation_and_directory_pipeline_apis() -> None:
    from insurance_harness.compiler.judge import JudgeDispatcher
    from insurance_harness.compiler.pipeline import ExtractionPipeline
    from insurance_harness.goldenset.annotator import GoldenAnnotator
    from insurance_harness.goldenset.runner import annotate_product
    from insurance_harness.sources.directory import (
        DirectoryDocumentSource,
        DirectorySourceRequest,
    )

    assert tuple(inspect.signature(GoldenAnnotator).parameters) == (
        "model_client",
        "registry",
        "annotator_model",
        "doc_char_budget",
    )
    assert tuple(inspect.signature(annotate_product).parameters) == (
        "product_dir",
        "registry",
        "annotator",
        "cache_dir",
        "line_key",
    )
    assert tuple(inspect.signature(JudgeDispatcher).parameters) == ("mode", "client")
    assert tuple(inspect.signature(DirectoryDocumentSource).parameters) == (
        "replay_identity",
        "parser_fingerprint",
        "page_loader",
    )
    assert set(DirectorySourceRequest.model_fields) == {"product_dir"}
    assert tuple(inspect.signature(ExtractionPipeline.run).parameters)[:3] == (
        "self",
        "run_dir",
        "source_request",
    )

    tree = ast.parse(_SOURCE_PATH.read_text(encoding="utf-8"), filename=str(_SOURCE_PATH))
    source_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "claude-session" not in source_literals
    assert "legacy" not in source_literals
    assert _calls_named(tree, "GoldenAnnotator")
    assert _calls_named(tree, "annotate_product")

    judge_calls = _calls_named(tree, "JudgeDispatcher")
    assert any(
        _keyword_names(call) >= {"mode", "client"}
        and any(
            keyword.arg == "mode"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == "gateway"
            for keyword in call.keywords
        )
        for call in judge_calls
    )
    assert any(
        _keyword_names(call) >= {"replay_identity", "parser_fingerprint"}
        for call in _calls_named(tree, "DirectoryDocumentSource")
    )
    assert any(
        _keyword_names(call) == {"product_dir"}
        for call in _calls_named(tree, "DirectorySourceRequest")
    )
    assert any(
        _keyword_names(call)
        >= {"run_dir", "source_request", "product_dir", "product_id"}
        for call in _calls_named(tree, "run")
    )
