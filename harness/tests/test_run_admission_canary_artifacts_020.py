"""OpenSpec 020 D1.5: canary artifact and unsigned-candidate contracts (TDD RED)."""

from __future__ import annotations

import fcntl
import hashlib
import importlib
import inspect
import os
import shutil
import sqlite3
import stat
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

import pytest
from pydantic import ValidationError

from insurance_harness.goldenset.admission import (
    ArtifactEvidenceInspectionError,
    ArtifactEvidenceInspector,
    ExecutionTarget,
    InitialExecutionAuthorization,
    ProductionAdmissionEvaluator,
    RunAdmissionDocument,
    RuntimeAdmissionDecision,
    execution_plan_hash,
)
from insurance_harness.goldenset.admission_budget import (
    BudgetLedger,
    ProductSettlementSnapshot,
    role_rate_digest,
)
from insurance_harness.goldenset.admission_models import (
    CanaryReviewApprovalEnvelope,
    CanaryReviewApprovalPayload,
    CanaryReviewArtifactEvidence,
    RunAdmissionPlan,
    canonical_json_bytes,
)
from tests import test_run_admission_canary_authorization_020 as auth_cases

_ARTIFACTS_MODULE = "insurance_harness.goldenset.admission_artifacts"
_ARTIFACT_NAMES = (
    "checkpoint",
    "manifest",
    "golden",
    "quote_verification",
    "disputed_quality",
)


class _ArtifactBundleFactory(Protocol):
    def __call__(
        self,
        *,
        checkpoint: bytes,
        manifest: bytes,
        golden: bytes,
        quote_verification: bytes,
        disputed_quality: bytes,
        disputed_count: int,
        record_count: int,
        quality_threshold_version: str,
    ) -> object: ...


class _Usage(Protocol):
    input_tokens: int
    output_tokens: int
    cost_minor_units: int
    role_rate_digest: str


class _Proposal(Protocol):
    execution_plan_hash: str
    settlement_snapshot_digest: str
    artifacts: CanaryReviewArtifactEvidence
    provider_usage: _Usage

    def model_dump(self, *, mode: str) -> dict[str, object]: ...


class _Candidate(Protocol):
    kind: str
    status: str
    authority: bool
    proposed_payload: _Proposal

    def model_dump(self, *, mode: str) -> dict[str, object]: ...


class _ArtifactStore(ArtifactEvidenceInspector, Protocol):
    @classmethod
    def _for_testing(cls, *, run_root: Path) -> _ArtifactStore: ...

    def bundle_path(self, execution_plan_hash: str) -> Path: ...

    def artifact_path(self, execution_plan_hash: str, name: str) -> Path: ...

    def write_first_canary(
        self,
        *,
        execution_plan_hash: str,
        bundle: object,
    ) -> CanaryReviewArtifactEvidence: ...

    def write_annotation_bundle(
        self,
        *,
        execution_plan_hash: str,
        product_id: str,
        bundle: object,
    ) -> CanaryReviewArtifactEvidence: ...

    def inspect_optional(
        self,
        *,
        execution_plan_hash: str,
        canary_target: ExecutionTarget,
    ) -> CanaryReviewArtifactEvidence | None: ...

    def write_candidate(self, candidate: _Candidate) -> Path: ...


class _CandidateBuilder(Protocol):
    def __call__(
        self,
        *,
        document: RunAdmissionDocument,
        admission: RuntimeAdmissionDecision,
        ledger: BudgetLedger,
        artifact_inspector: ArtifactEvidenceInspector,
    ) -> _Candidate: ...


class _LockedInspector:
    def __init__(self, delegate: _ArtifactStore, locked: list[bool]) -> None:
        self._delegate = delegate
        self._locked = locked
        self.calls = 0

    def inspect(
        self,
        *,
        execution_plan_hash: str,
        canary_target: ExecutionTarget,
    ) -> CanaryReviewArtifactEvidence:
        assert self._locked == [True], "artifact evidence must be read inside the ledger lock"
        self.calls += 1
        return self._delegate.inspect(
            execution_plan_hash=execution_plan_hash,
            canary_target=canary_target,
        )


def _artifacts_module() -> ModuleType:
    try:
        return importlib.import_module(_ARTIFACTS_MODULE)
    except ModuleNotFoundError:
        pytest.fail(
            "D1.5 RED: admission_artifacts supporting module is missing",
            pytrace=False,
        )


def test_d1_1b_production_artifact_root_matches_run_entrypoint_contract() -> None:
    resolver = getattr(_artifacts_module(), "production_canary_run_root", None)
    if resolver is None:
        pytest.fail("D1.1b RED: production artifact-root resolver is missing", pytrace=False)
    assert cast(Callable[[], Path], resolver)() == Path(
        "/var/lib/insurancekb/run-admission/runs"
    )


def test_d1_5_candidate_builder_uses_public_locked_snapshot_api() -> None:
    source = inspect.getsource(_candidate_builder())
    assert "ledger._mutation" not in source
    assert "ledger._product_settlement_snapshot" not in source
    assert "ledger.locked_product_settlement_snapshot" in source


def _bundle_factory() -> _ArtifactBundleFactory:
    value = getattr(_artifacts_module(), "CanaryArtifactBundle", None)
    if value is None:
        pytest.fail("D1.5 RED: CanaryArtifactBundle is missing", pytrace=False)
    return cast(_ArtifactBundleFactory, value)


def _store_factory() -> type[_ArtifactStore]:
    value = getattr(_artifacts_module(), "CanaryArtifactStore", None)
    if not isinstance(value, type):
        pytest.fail("D1.5 RED: CanaryArtifactStore is missing", pytrace=False)
    return cast(type[_ArtifactStore], value)


def _candidate_builder() -> _CandidateBuilder:
    value = getattr(_artifacts_module(), "build_canary_review_candidate", None)
    if value is None:
        pytest.fail("D1.5 RED: candidate builder is missing", pytrace=False)
    return cast(_CandidateBuilder, value)


def _error_type(name: str) -> type[Exception]:
    value = getattr(_artifacts_module(), name, None)
    if not isinstance(value, type) or not issubclass(value, Exception):
        pytest.fail(f"D1.5 RED: {name} is missing", pytrace=False)
    return value


def _secure_root(tmp_path: Path) -> Path:
    root = tmp_path / "canary-runs"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root


def _store(tmp_path: Path) -> _ArtifactStore:
    return _store_factory()._for_testing(run_root=_secure_root(tmp_path))


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


def _bundle(*, checkpoint: bytes = b"checkpoint-v1") -> object:
    return _bundle_factory()(
        checkpoint=checkpoint,
        manifest=b'{"manifest":"v1"}',
        golden=b'{"records":[{"field":"waiting_period"}]}',
        quote_verification=b'{"verified":true}',
        disputed_quality=b'{"disputed":0,"records":1}',
        disputed_count=0,
        record_count=1,
        quality_threshold_version="quality-v1",
    )


def test_d1_5_bundle_rejects_disputed_count_above_record_count() -> None:
    with pytest.raises(ValueError, match="disputed_count.*record_count"):
        _bundle_factory()(
            checkpoint=b"checkpoint",
            manifest=b"manifest",
            golden=b"golden",
            quote_verification=b"quote-verification",
            disputed_quality=b"disputed-quality",
            disputed_count=2,
            record_count=1,
            quality_threshold_version="quality-v1",
        )


def _first_target() -> ExecutionTarget:
    return ExecutionTarget(stage="annotation", product_id=auth_cases._FIRST)


def _second_target() -> ExecutionTarget:
    return ExecutionTarget(stage="annotation", product_id=auth_cases._SECOND)


def _write_bundle(
    store: _ArtifactStore,
    plan_hash: str,
    *,
    bundle: object | None = None,
) -> CanaryReviewArtifactEvidence:
    return store.write_first_canary(
        execution_plan_hash=plan_hash,
        bundle=bundle or _bundle(),
    )


def _candidate_context(
    tmp_path: Path,
) -> tuple[
    RunAdmissionDocument,
    BudgetLedger,
    ProductionAdmissionEvaluator,
    RuntimeAdmissionDecision,
    _ArtifactStore,
]:
    document, ledger, evaluator, _source, _artifacts, _review_key = auth_cases._setup(
        tmp_path
    )
    admission = evaluator.evaluate_execution(document, ledger)
    assert isinstance(admission.authorization, InitialExecutionAuthorization)
    store = _store(tmp_path)
    _write_bundle(store, execution_plan_hash(document))
    return document, ledger, evaluator, admission, store


def _build_candidate(
    *,
    document: RunAdmissionDocument,
    admission: RuntimeAdmissionDecision,
    ledger: BudgetLedger,
    inspector: ArtifactEvidenceInspector,
) -> _Candidate:
    return _candidate_builder()(
        document=document,
        admission=admission,
        ledger=ledger,
        artifact_inspector=inspector,
    )


def _track_ledger_lock(
    ledger: BudgetLedger,
    monkeypatch: pytest.MonkeyPatch,
) -> list[bool]:
    locked = [False]
    original_mutation = ledger._mutation

    @contextmanager
    def mutation() -> Iterator[sqlite3.Connection]:
        with original_mutation() as connection:
            assert locked == [False]
            locked[0] = True
            try:
                yield connection
            finally:
                locked[0] = False

    monkeypatch.setattr(ledger, "_mutation", mutation)
    return locked


def test_d1_5_artifacts_are_located_by_plan_hash_and_fixed_first_target(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    first_hash = "1" * 64
    second_hash = "2" * 64

    first_path = store.bundle_path(first_hash)
    assert first_path.is_relative_to(tmp_path)
    assert first_hash in first_path.parts
    assert first_path == store.bundle_path(first_hash)
    assert first_path != store.bundle_path(second_hash)

    evidence = _write_bundle(store, first_hash)
    assert store.inspect(
        execution_plan_hash=first_hash,
        canary_target=_first_target(),
    ) == evidence
    with pytest.raises(ArtifactEvidenceInspectionError, match="target"):
        store.inspect(
            execution_plan_hash=first_hash,
            canary_target=_second_target(),
        )


def test_d1_5_optional_inspection_returns_none_only_under_writer_plan_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    plan_hash = "a" * 64
    lock_operations: list[int] = []
    real_flock = fcntl.flock

    def tracked_flock(descriptor: int, operation: int) -> None:
        lock_operations.append(operation)
        real_flock(descriptor, operation)

    monkeypatch.setattr(fcntl, "flock", tracked_flock)

    assert (
        store.inspect_optional(
            execution_plan_hash=plan_hash,
            canary_target=_first_target(),
        )
        is None
    )

    assert fcntl.LOCK_SH in lock_operations
    assert fcntl.LOCK_UN in lock_operations
    plan_directory = store.bundle_path(plan_hash).parent
    lock_path = plan_directory / ".canary-bundle.commit.lock"
    assert plan_directory.is_dir() and not plan_directory.is_symlink()
    assert stat.S_IMODE(plan_directory.stat().st_mode) == 0o700
    assert lock_path.is_file() and not lock_path.is_symlink()
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
    assert not store.bundle_path(plan_hash).exists()


@pytest.mark.parametrize("target_name", ["first", "second"])
def test_d1_5_optional_inspection_returns_exact_existing_evidence(
    tmp_path: Path,
    target_name: str,
) -> None:
    store = _store(tmp_path)
    plan_hash = "b" * 64
    target = _first_target() if target_name == "first" else _second_target()
    if target_name == "first":
        expected = _write_bundle(store, plan_hash)
    else:
        expected = store.write_annotation_bundle(
            execution_plan_hash=plan_hash,
            product_id=auth_cases._SECOND,
            bundle=_bundle(checkpoint=b"second-checkpoint"),
        )

    assert (
        store.inspect_optional(
            execution_plan_hash=plan_hash,
            canary_target=target,
        )
        == expected
    )


@pytest.mark.parametrize("unsafe_kind", ["symlink", "wide", "file"])
def test_d1_5_optional_inspection_rejects_unsafe_plan_directory(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    store = _store(tmp_path)
    plan_hash = "c" * 64
    plan_directory = store.bundle_path(plan_hash).parent
    if unsafe_kind == "symlink":
        actual = tmp_path / "actual-plan"
        actual.mkdir(mode=0o700)
        plan_directory.symlink_to(actual, target_is_directory=True)
    elif unsafe_kind == "wide":
        plan_directory.mkdir(mode=0o700)
        plan_directory.chmod(0o770)
    else:
        plan_directory.write_bytes(b"not-a-directory")
        plan_directory.chmod(0o600)

    with pytest.raises(ArtifactEvidenceInspectionError, match="missing|unsafe"):
        store.inspect_optional(
            execution_plan_hash=plan_hash,
            canary_target=_first_target(),
        )


@pytest.mark.parametrize(
    "unsafe_kind",
    ["symlink", "wide", "file", "partial", "drift"],
)
def test_d1_5_optional_inspection_rejects_unsafe_or_incomplete_target(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    store = _store(tmp_path)
    plan_hash = "d" * 64
    target_directory = store.bundle_path(plan_hash)
    if unsafe_kind == "drift":
        _write_bundle(store, plan_hash)
        store.artifact_path(plan_hash, "golden").write_bytes(b"drifted")
    else:
        target_directory.parent.mkdir(mode=0o700)
        if unsafe_kind == "symlink":
            actual = tmp_path / "actual-target"
            actual.mkdir(mode=0o700)
            target_directory.symlink_to(actual, target_is_directory=True)
        elif unsafe_kind == "wide":
            target_directory.mkdir(mode=0o700)
            target_directory.chmod(0o770)
        elif unsafe_kind == "file":
            target_directory.write_bytes(b"not-a-directory")
            target_directory.chmod(0o600)
        else:
            target_directory.mkdir(mode=0o700)
            checkpoint = target_directory / "checkpoint.bin"
            checkpoint.write_bytes(b"partial")
            checkpoint.chmod(0o600)

    with pytest.raises(
        ArtifactEvidenceInspectionError,
        match="missing|unsafe|drift",
    ):
        store.inspect_optional(
            execution_plan_hash=plan_hash,
            canary_target=_first_target(),
        )


def test_d1_5_artifact_writes_are_atomic_private_and_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    plan_hash = "3" * 64
    fsync_kinds: list[str] = []
    replacements: list[tuple[str, str]] = []
    original_fsync = os.fsync
    original_replace = os.replace

    def track_fsync(file_descriptor: int) -> None:
        mode = os.fstat(file_descriptor).st_mode
        fsync_kinds.append("directory" if stat.S_ISDIR(mode) else "file")
        original_fsync(file_descriptor)

    def track_replace(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        target: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        replacements.append((os.fsdecode(source), os.fsdecode(target)))
        original_replace(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(os, "fsync", track_fsync)
    monkeypatch.setattr(os, "replace", track_replace)

    _write_bundle(store, plan_hash)

    paths = tuple(store.artifact_path(plan_hash, name) for name in _ARTIFACT_NAMES)
    assert all(path.is_file() and not path.is_symlink() for path in paths)
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in paths)
    assert len(replacements) >= len(_ARTIFACT_NAMES)
    assert fsync_kinds.count("file") >= len(_ARTIFACT_NAMES)
    assert fsync_kinds.count("directory") >= len(_ARTIFACT_NAMES)


def test_d1_5_artifact_io_is_anchored_to_verified_directory_descriptors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    plan_hash = "8" * 64
    opened: list[tuple[int, int | None]] = []
    mkdir_parents: list[int | None] = []
    renamed: list[tuple[int | None, int | None]] = []
    listed: list[object] = []
    fstat_calls = 0
    geteuid_calls = 0
    real_open = os.open
    real_mkdir = os.mkdir
    real_replace = os.replace
    real_listdir = os.listdir
    real_fstat = os.fstat
    real_geteuid = os.geteuid

    def tracked_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        opened.append((flags, dir_fd))
        return real_open(path, flags, mode, dir_fd=dir_fd)

    def tracked_mkdir(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        mkdir_parents.append(dir_fd)
        real_mkdir(path, mode, dir_fd=dir_fd)

    def tracked_replace(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        target: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        renamed.append((src_dir_fd, dst_dir_fd))
        real_replace(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    def tracked_listdir(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes] | int | None = None,
    ) -> list[str]:
        listed.append(path)
        if path is None:
            return real_listdir()
        if isinstance(path, int):
            return real_listdir(path)
        return [os.fsdecode(item) for item in real_listdir(path)]

    def tracked_fstat(file_descriptor: int) -> os.stat_result:
        nonlocal fstat_calls
        fstat_calls += 1
        return real_fstat(file_descriptor)

    def tracked_geteuid() -> int:
        nonlocal geteuid_calls
        geteuid_calls += 1
        return real_geteuid()

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "mkdir", tracked_mkdir)
    monkeypatch.setattr(os, "replace", tracked_replace)
    monkeypatch.setattr(os, "listdir", tracked_listdir)
    monkeypatch.setattr(os, "fstat", tracked_fstat)
    monkeypatch.setattr(os, "geteuid", tracked_geteuid)

    expected = _write_bundle(store, plan_hash)
    assert store.inspect(
        execution_plan_hash=plan_hash,
        canary_target=_first_target(),
    ) == expected

    required_flags = os.O_NOFOLLOW | os.O_CLOEXEC
    assert opened and all(flags & required_flags == required_flags for flags, _ in opened)
    assert mkdir_parents and all(parent is not None for parent in mkdir_parents)
    assert renamed and all(source is not None and target is not None for source, target in renamed)
    assert listed and all(isinstance(target, int) for target in listed)
    assert fstat_calls >= len(opened)
    assert geteuid_calls >= len(opened)


def test_d1_5_new_directories_fsync_each_parent_before_descending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    events: list[str] = []
    real_mkdir = os.mkdir
    real_fsync = os.fsync

    def tracked_mkdir(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        events.append("mkdir")
        real_mkdir(path, mode, dir_fd=dir_fd)

    def tracked_fsync(file_descriptor: int) -> None:
        kind = "directory" if stat.S_ISDIR(os.fstat(file_descriptor).st_mode) else "file"
        events.append(f"fsync:{kind}")
        real_fsync(file_descriptor)

    monkeypatch.setattr(os, "mkdir", tracked_mkdir)
    monkeypatch.setattr(os, "fsync", tracked_fsync)
    _write_bundle(store, "9" * 64)

    mkdir_indexes = [index for index, event in enumerate(events) if event == "mkdir"]
    assert len(mkdir_indexes) == 2
    assert all(events[index + 1] == "fsync:directory" for index in mkdir_indexes)


@pytest.mark.parametrize("failed_level", ("root-to-plan", "plan-to-target"))
def test_d1_5_retry_after_parent_fsync_failure_resyncs_existing_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_level: str,
) -> None:
    store = _store(tmp_path)
    plan_hash = "0" * 64
    real_mkdir = os.mkdir
    real_fsync = os.fsync
    mkdir_count = 0
    failed = False
    failure_after_mkdir = 1 if failed_level == "root-to-plan" else 2

    def tracked_mkdir(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        nonlocal mkdir_count
        real_mkdir(path, mode, dir_fd=dir_fd)
        mkdir_count += 1

    def fail_selected_parent_fsync(file_descriptor: int) -> None:
        nonlocal failed
        if not failed and mkdir_count == failure_after_mkdir:
            failed = True
            raise OSError("injected parent fsync failure")
        real_fsync(file_descriptor)

    monkeypatch.setattr(os, "mkdir", tracked_mkdir)
    monkeypatch.setattr(os, "fsync", fail_selected_parent_fsync)
    with pytest.raises(_error_type("CanaryArtifactStoreError")) as caught:
        _write_bundle(store, plan_hash)
    assert failed
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "injected" not in _exception_chain_text(caught.value)

    root_inode = (tmp_path / "canary-runs").stat().st_ino
    plan_inode = (store.bundle_path(plan_hash).parent).stat().st_ino
    retry_parent_fsyncs: list[int] = []

    def track_retry_fsync(file_descriptor: int) -> None:
        metadata = os.fstat(file_descriptor)
        if stat.S_ISDIR(metadata.st_mode):
            retry_parent_fsyncs.append(metadata.st_ino)
        real_fsync(file_descriptor)

    monkeypatch.setattr(os, "fsync", track_retry_fsync)
    _write_bundle(store, plan_hash)

    expected = {root_inode}
    if failed_level == "plan-to-target":
        expected.add(plan_inode)
    assert expected.issubset(retry_parent_fsyncs)


@pytest.mark.parametrize("unsafe_kind", ["symlink", "wide-parent"])
def test_d1_5_artifact_store_rejects_unsafe_root(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    root = tmp_path / "unsafe-root"
    if unsafe_kind == "symlink":
        actual = tmp_path / "actual-root"
        actual.mkdir(mode=0o700)
        root.symlink_to(actual, target_is_directory=True)
    else:
        root.mkdir(mode=0o700)
        root.chmod(0o770)

    with pytest.raises(_error_type("CanaryArtifactStoreError"), match="unsafe|symlink"):
        store = _store_factory()._for_testing(run_root=root)
        _write_bundle(store, "4" * 64)


def test_d1_5_root_swap_after_open_cannot_redirect_bundle_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _secure_root(tmp_path)
    root_identity = root.stat()
    held_root = tmp_path / "held-canary-runs"
    attacker = tmp_path / "attacker"
    attacker.mkdir(mode=0o700)
    attacker.chmod(0o700)
    store = _store_factory()._for_testing(run_root=root)
    real_open = os.open
    swapped = False

    def open_and_swap(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        opened = os.fstat(descriptor)
        if (
            not swapped
            and opened.st_dev == root_identity.st_dev
            and opened.st_ino == root_identity.st_ino
        ):
            root.rename(held_root)
            root.symlink_to(attacker, target_is_directory=True)
            swapped = True
        return descriptor

    monkeypatch.setattr(os, "open", open_and_swap)
    plan_hash = "a" * 64
    expected = _write_bundle(store, plan_hash)

    assert swapped, "test hook must replace the path after the trusted root fd opens"
    assert not any(attacker.iterdir())
    held_store = _store_factory()._for_testing(run_root=held_root)
    assert held_store.inspect(
        execution_plan_hash=plan_hash,
        canary_target=_first_target(),
    ) == expected


@pytest.mark.parametrize("operation", ["construct", "inspect"])
def test_d1_5_artifact_errors_hide_host_paths_and_exception_chains(
    tmp_path: Path,
    operation: str,
) -> None:
    secret = "HOST-PATH-SECRET-CANARY"
    if operation == "construct":
        root = tmp_path / secret / "missing"
        with pytest.raises(_error_type("CanaryArtifactStoreError")) as caught:
            _store_factory()._for_testing(run_root=root)
    else:
        root = tmp_path / secret / "canary-runs"
        root.mkdir(parents=True, mode=0o700)
        root.chmod(0o700)
        store = _store_factory()._for_testing(run_root=root)
        plan_hash = "b" * 64
        _write_bundle(store, plan_hash)
        shutil.rmtree(store.bundle_path(plan_hash).parent)
        with pytest.raises(ArtifactEvidenceInspectionError) as caught:
            store.inspect(
                execution_plan_hash=plan_hash,
                canary_target=_first_target(),
            )

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert secret not in _exception_chain_text(caught.value)


def test_d1_5_inspector_conversion_clears_low_level_list_error_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "HOST-LIST-SECRET-CANARY"
    store = _store(tmp_path)
    plan_hash = "e" * 64
    _write_bundle(store, plan_hash)

    def fail_listdir(_directory_fd: object = None) -> list[str]:
        raise OSError(secret)

    monkeypatch.setattr(os, "listdir", fail_listdir)
    with pytest.raises(ArtifactEvidenceInspectionError) as caught:
        store.inspect(
            execution_plan_hash=plan_hash,
            canary_target=_first_target(),
        )

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert secret not in _exception_chain_text(caught.value)


@pytest.mark.parametrize("failure", ["missing", "drift"])
def test_d1_5_inspector_recomputes_every_artifact_and_fails_closed(
    tmp_path: Path,
    failure: str,
) -> None:
    store = _store(tmp_path)
    plan_hash = "5" * 64
    _write_bundle(store, plan_hash)
    path = store.artifact_path(plan_hash, "golden")
    if failure == "missing":
        path.unlink()
    else:
        path.write_bytes(b"forged-golden")

    with pytest.raises(ArtifactEvidenceInspectionError, match="missing|drift"):
        store.inspect(
            execution_plan_hash=plan_hash,
            canary_target=_first_target(),
        )


def test_d1_5_same_plan_rejects_ambiguous_artifact_bundle(tmp_path: Path) -> None:
    store = _store(tmp_path)
    plan_hash = "6" * 64
    evidence = _write_bundle(store, plan_hash)
    assert _write_bundle(store, plan_hash) == evidence

    with pytest.raises(_error_type("CanaryArtifactStoreError"), match="ambiguous|different"):
        _write_bundle(store, plan_hash, bundle=_bundle(checkpoint=b"different"))


def test_d1_5_second_annotation_bundle_is_durable_and_target_isolated(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    plan_hash = "e" * 64
    first = _write_bundle(store, plan_hash)
    second_bundle = _bundle(checkpoint=b"second-checkpoint")

    second = store.write_annotation_bundle(
        execution_plan_hash=plan_hash,
        product_id=auth_cases._SECOND,
        bundle=second_bundle,
    )

    assert second != first
    assert store.inspect(
        execution_plan_hash=plan_hash,
        canary_target=_first_target(),
    ) == first
    target_directories = [
        path
        for path in store.bundle_path(plan_hash).parent.iterdir()
        if path.is_dir()
    ]
    assert len(target_directories) == 2
    second_directory = next(
        path for path in target_directories if path != store.bundle_path(plan_hash)
    )
    assert (second_directory / "checkpoint.bin").read_bytes() == b"second-checkpoint"
    assert stat.S_IMODE(second_directory.stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in second_directory.iterdir()
    )
    assert (
        store.write_annotation_bundle(
            execution_plan_hash=plan_hash,
            product_id=auth_cases._SECOND,
            bundle=second_bundle,
        )
        == second
    )
    with pytest.raises(
        _error_type("CanaryArtifactStoreError"),
        match="different|ambiguous",
    ):
        store.write_annotation_bundle(
            execution_plan_hash=plan_hash,
            product_id=auth_cases._SECOND,
            bundle=_bundle(checkpoint=b"second-drift"),
        )


def test_d1_5_annotation_bundle_rejects_non_fixed_target_before_write(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    plan_hash = "f" * 64

    with pytest.raises(ValueError, match="code-fixed annotation target"):
        store.write_annotation_bundle(
            execution_plan_hash=plan_hash,
            product_id="unknown-product",
            bundle=_bundle(),
        )

    assert not (store.bundle_path(plan_hash).parent).exists()


def test_d1_5_concurrent_first_writers_cannot_overwrite_a_committed_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    plan_hash = "c" * 64
    target_name = store.bundle_path(plan_hash).name
    real_iterdir = Path.iterdir
    snapshots_ready = threading.Barrier(2)
    leader_complete = threading.Event()
    state_lock = threading.Lock()
    roles: dict[int, str] = {}
    consumed: set[int] = set()

    def stale_first_snapshot(path: Path) -> Iterator[Path]:
        thread_id = threading.get_ident()
        if path.name != target_name:
            return real_iterdir(path)
        with state_lock:
            if thread_id not in roles and len(roles) < 2:
                roles[thread_id] = "leader" if not roles else "follower"
            role = roles.get(thread_id)
            first_call = role is not None and thread_id not in consumed
            if first_call:
                consumed.add(thread_id)
        if not first_call:
            return real_iterdir(path)
        snapshot = tuple(real_iterdir(path))
        snapshots_ready.wait(timeout=3)
        if role == "follower":
            assert leader_complete.wait(timeout=3)
        return iter(snapshot)

    monkeypatch.setattr(Path, "iterdir", stale_first_snapshot)
    start = threading.Barrier(2)

    def write(checkpoint: bytes) -> tuple[str, object]:
        start.wait(timeout=3)
        try:
            return "ok", _write_bundle(
                store,
                plan_hash,
                bundle=_bundle(checkpoint=checkpoint),
            )
        except Exception as exc:
            return "error", exc
        finally:
            if roles.get(threading.get_ident()) == "leader":
                leader_complete.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(
            future.result(timeout=8)
            for future in (
                pool.submit(write, b"checkpoint-first"),
                pool.submit(write, b"checkpoint-second"),
            )
        )

    assert [status for status, _ in results].count("ok") == 1
    errors = [value for status, value in results if status == "error"]
    assert len(errors) == 1 and isinstance(
        errors[0], _error_type("CanaryArtifactStoreError")
    )


def test_d1_5_existing_bundle_replay_compares_exact_bytes_not_only_digests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _artifacts_module()
    monkeypatch.setattr(module, "_sha256", lambda _content: "d" * 64)
    store = _store(tmp_path)
    plan_hash = "d" * 64
    _write_bundle(store, plan_hash, bundle=_bundle(checkpoint=b"checkpoint-original"))

    with pytest.raises(
        _error_type("CanaryArtifactStoreError"),
        match="different|ambiguous",
    ):
        _write_bundle(
            store,
            plan_hash,
            bundle=_bundle(checkpoint=b"checkpoint-collision"),
        )


def test_d1_5_artifact_evidence_digests_exact_persisted_bytes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    plan_hash = "7" * 64
    evidence = _write_bundle(store, plan_hash)

    assert evidence.checkpoint_digest == hashlib.sha256(
        store.artifact_path(plan_hash, "checkpoint").read_bytes()
    ).hexdigest()
    assert evidence.manifest_digest == hashlib.sha256(
        store.artifact_path(plan_hash, "manifest").read_bytes()
    ).hexdigest()
    assert evidence.golden_digest == hashlib.sha256(
        store.artifact_path(plan_hash, "golden").read_bytes()
    ).hexdigest()
    assert evidence.quote_verification_digest == hashlib.sha256(
        store.artifact_path(plan_hash, "quote_verification").read_bytes()
    ).hexdigest()
    assert evidence.disputed_quality_digest == hashlib.sha256(
        store.artifact_path(plan_hash, "disputed_quality").read_bytes()
    ).hexdigest()


def test_d1_5_candidate_is_derived_under_ledger_lock_from_verified_evidence_and_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, ledger, _evaluator, admission, store = _candidate_context(tmp_path)
    locked = _track_ledger_lock(ledger, monkeypatch)
    inspector = _LockedInspector(store, locked)

    candidate = _build_candidate(
        document=document,
        admission=admission,
        ledger=ledger,
        inspector=inspector,
    )

    snapshot = ledger.product_settlement_snapshot(
        admission.account.account_id,  # type: ignore[union-attr]
        "annotation",
        auth_cases._FIRST,
    )
    expected_usage = _verified_annotator_usage(snapshot)
    assert inspector.calls == 1
    assert locked == [False]
    proposal = candidate.proposed_payload
    assert proposal.execution_plan_hash == execution_plan_hash(document)
    assert proposal.settlement_snapshot_digest == (
        ledger.product_settlement_snapshot_digest(snapshot)
    )
    assert proposal.artifacts == store.inspect(
        execution_plan_hash=execution_plan_hash(document),
        canary_target=_first_target(),
    )
    assert (
        proposal.provider_usage.input_tokens,
        proposal.provider_usage.output_tokens,
        proposal.provider_usage.cost_minor_units,
    ) == expected_usage
    assert document.budget_contract is not None
    assert proposal.provider_usage.role_rate_digest == role_rate_digest(
        document.budget_contract.role_rates["annotator"]
    )


def _verified_annotator_usage(snapshot: ProductSettlementSnapshot) -> tuple[int, int, int]:
    attempts = tuple(item for item in snapshot.attempts if item.role == "annotator")
    assert attempts and all(item.state == "terminal" and item.usage_verified for item in attempts)
    return (
        sum(item.actual.input_tokens for item in attempts),
        sum(item.actual.output_tokens for item in attempts),
        sum(item.actual.cost_minor_units for item in attempts),
    )


def test_d1_5_candidate_rejects_unverified_provider_usage(
    tmp_path: Path,
) -> None:
    document, ledger, _evaluator, admission, store = _candidate_context(tmp_path)
    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        connection.execute("UPDATE request_attempts SET usage_verified=0")

    with pytest.raises(
        _error_type("CanaryReviewCandidateError"),
        match="usage|verified",
    ):
        _build_candidate(
            document=document,
            admission=admission,
            ledger=ledger,
            inspector=store,
        )


def test_d1_5_candidate_conversion_clears_inspector_error_chain(
    tmp_path: Path,
) -> None:
    secret = "HOST-INSPECTOR-SECRET-CANARY"
    document, ledger, _evaluator, admission, _store = _candidate_context(tmp_path)

    class FailingInspector:
        def inspect(
            self,
            *,
            execution_plan_hash: str,
            canary_target: ExecutionTarget,
        ) -> CanaryReviewArtifactEvidence:
            del execution_plan_hash, canary_target
            raise ArtifactEvidenceInspectionError(secret)

    with pytest.raises(_error_type("CanaryReviewCandidateError")) as caught:
        _build_candidate(
            document=document,
            admission=admission,
            ledger=ledger,
            inspector=FailingInspector(),
        )

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert secret not in _exception_chain_text(caught.value)


def test_d1_5_candidate_is_canonical_process_display_not_approval_authority(
    tmp_path: Path,
) -> None:
    document, ledger, evaluator, admission, store = _candidate_context(tmp_path)
    before_hash = execution_plan_hash(document)
    before_authorization = admission.authorization

    candidate = _build_candidate(
        document=document,
        admission=admission,
        ledger=ledger,
        inspector=store,
    )
    rendered = candidate.model_dump(mode="python")
    proposal = candidate.proposed_payload.model_dump(mode="python")
    assert rendered.keys() == {"kind", "status", "authority", "proposed_payload"}
    assert candidate.kind == "canary-review-candidate"
    assert candidate.status == "unsigned"
    assert candidate.authority is False
    assert not isinstance(candidate.proposed_payload, CanaryReviewApprovalPayload)
    assert {
        "approver_identity",
        "approver_role",
        "issued_at",
        "expires_at",
        "review_decision",
    }.isdisjoint(proposal)
    candidate_path = store.write_candidate(candidate)

    assert candidate_path.read_bytes() == canonical_json_bytes(candidate)
    assert stat.S_IMODE(candidate_path.stat().st_mode) == 0o600
    assert execution_plan_hash(document) == before_hash
    after = evaluator.evaluate_execution(document, ledger)
    assert after.authorization == before_authorization
    assert isinstance(after.authorization, InitialExecutionAuthorization)

    with pytest.raises(ValidationError):
        CanaryReviewApprovalEnvelope.model_validate(candidate.model_dump(mode="python"))
    with pytest.raises(ValidationError):
        RunAdmissionPlan.model_validate(
            {
                **document.plan.model_dump(mode="python"),
                "approval_envelopes": [candidate.model_dump(mode="python")],
            }
        )


def test_d1_5_candidate_write_rejects_artifact_drift_since_build(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    document, ledger, _evaluator, admission, source_store = _candidate_context(source_root)
    candidate = _build_candidate(
        document=document,
        admission=admission,
        ledger=ledger,
        inspector=source_store,
    )
    plan_hash = execution_plan_hash(document)
    destination_root = tmp_path / "destination"
    destination_root.mkdir(mode=0o700)
    destination_root.chmod(0o700)
    destination_store = _store_factory()._for_testing(run_root=destination_root)
    _write_bundle(
        destination_store,
        plan_hash,
        bundle=_bundle(checkpoint=b"different-valid-checkpoint"),
    )

    with pytest.raises(
        _error_type("CanaryArtifactStoreError"),
        match="drift|mismatch|different",
    ):
        destination_store.write_candidate(candidate)
