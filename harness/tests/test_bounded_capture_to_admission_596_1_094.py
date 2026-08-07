from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import SecretStr

from insurance_harness.knowledge_compiler.bounded_capture_to_admission_596_1 import (
    ADMISSION_CONTRACT_ID,
    ADMISSION_CONTRACT_SHA256,
    CAPTURE_CONTRACT_ID,
    CAPTURE_CONTRACT_SHA256,
    CAPTURE_MODULE_ID,
    CAPTURE_MODULE_IDENTITY_SHA256,
    INTAKE_CONTRACT_ID,
    INTAKE_CONTRACT_SHA256,
    CaptureExecutionReceipt,
    CaptureInvocation,
    ExecutionDependencies,
    ExecutionRequest,
    PrivateRunnerInput,
    PrivateRunnerResult,
    SafeRunnerArtifact,
    SubprocessCaptureExecutor,
    main,
    run_bounded_capture_to_admission,
)

_SOURCE_SHA256_BY_ROLE = {
    "terms": "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
    "brochure": "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
    "rate_table": "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
}
_CAPTURE_DIR_BY_ROLE = {"terms": "terms", "brochure": "brochure", "rate_table": "rate"}
_ARTIFACT_BYTES_BY_ROLE = {
    "terms": b'{"contract":"synthetic-terms"}\n',
    "brochure": b'{"contract":"synthetic-brochure"}\n',
    "rate_table": b'{"contract":"synthetic-rate"}\n',
}
_ARTIFACT_SHA256_BY_ROLE = {
    role: hashlib.sha256(payload).hexdigest()
    for role, payload in _ARTIFACT_BYTES_BY_ROLE.items()
}
_OUTER_SHA256_BY_ROLE = {
    "terms": "1" * 64,
    "brochure": "2" * 64,
    "rate_table": "3" * 64,
}
_EXECUTABLE_SHA256 = "4" * 64
_RELATION_BYTES = b'{"contract":"synthetic-relation-receipt"}\n'
_RELATION_SHA256 = hashlib.sha256(_RELATION_BYTES).hexdigest()
_SECRET = "synthetic-mineru-secret-must-not-escape"


def test_frozen_dependency_identity_preimages_have_exact_hashes() -> None:
    identities = {
        "mineru-three-source-capture-596-1.v1": CAPTURE_CONTRACT_SHA256,
        "mineru-capture-intake-596-1.v1": INTAKE_CONTRACT_SHA256,
        "596-1-private-artifact-admission-runner.v1": ADMISSION_CONTRACT_SHA256,
        "github.com/Tencent/WeKnora/cmd/mineru-capture-596-1": (
            CAPTURE_MODULE_IDENTITY_SHA256
        ),
    }
    assert CAPTURE_CONTRACT_ID in identities
    assert INTAKE_CONTRACT_ID in identities
    assert ADMISSION_CONTRACT_ID in identities
    assert CAPTURE_MODULE_ID in identities
    assert {
        identity: hashlib.sha256(identity.encode("utf-8")).hexdigest()
        for identity in identities
    } == identities


@pytest.fixture
def output_root() -> Iterator[Path]:
    root = Path("/private/tmp") / f"094-capture-{uuid.uuid4().hex}"
    assert not root.exists()
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _private_file(path: Path, payload: bytes) -> Path:
    path.write_bytes(payload)
    path.chmod(0o600)
    return path


def _publish_capture_tree(root: Path) -> None:
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    for role, directory_name in _CAPTURE_DIR_BY_ROLE.items():
        directory = root / directory_name
        directory.mkdir(mode=0o700)
        directory.chmod(0o700)
        artifact = directory / "mineru-native-structure.json"
        artifact.write_bytes(_ARTIFACT_BYTES_BY_ROLE[role])
        artifact.chmod(0o600)


@dataclass
class _CaptureExecutor:
    status: str = "COMPLETED"
    overrides: dict[str, object] = field(default_factory=dict)
    error: Exception | None = None
    publish: bool = True
    calls: list[CaptureInvocation] = field(default_factory=list)

    def __call__(self, invocation: CaptureInvocation) -> CaptureExecutionReceipt:
        self.calls.append(invocation)
        if self.error is not None:
            raise self.error
        if self.publish:
            _publish_capture_tree(invocation.output_root)
        values: dict[str, object] = {
            "status": self.status,
            "invocation_count": 1,
            "executable_sha256": invocation.expected_executable_sha256,
            "module_identity_sha256": CAPTURE_MODULE_IDENTITY_SHA256,
            "capture_contract_sha256": CAPTURE_CONTRACT_SHA256,
            "artifact_sha256_by_role": dict(_ARTIFACT_SHA256_BY_ROLE),
        }
        values.update(self.overrides)
        return CaptureExecutionReceipt(**values)  # type: ignore[arg-type]


@dataclass
class _PrivateRunner:
    status: str = "COMPOSITION_SEAM_VERIFIED"
    error: Exception | None = None
    intake_contract_sha256: str = INTAKE_CONTRACT_SHA256
    admission_contract_sha256: str = ADMISSION_CONTRACT_SHA256
    artifacts: tuple[SafeRunnerArtifact, ...] = tuple(
        SafeRunnerArtifact(
            role=role,
            artifact_sha256=_ARTIFACT_SHA256_BY_ROLE[role],
            outer_sha256=_OUTER_SHA256_BY_ROLE[role],
        )
        for role in ("terms", "brochure", "rate_table")
    )
    common_receipt_digest_sha256: str | None = "5" * 64
    provider_calls: int = 0
    golden_reads: int = 0
    calls: list[PrivateRunnerInput] = field(default_factory=list)

    def __call__(self, request: PrivateRunnerInput) -> PrivateRunnerResult:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return PrivateRunnerResult(
            status=self.status,
            intake_contract_sha256=self.intake_contract_sha256,
            admission_contract_sha256=self.admission_contract_sha256,
            artifacts=self.artifacts,
            common_receipt_digest_sha256=self.common_receipt_digest_sha256,
            provider_calls=self.provider_calls,
            golden_reads=self.golden_reads,
        )


def _request(output_root: Path, relation_receipt: Path) -> ExecutionRequest:
    return ExecutionRequest(
        output_root=output_root,
        relation_receipt=relation_receipt,
        expected_relation_receipt_sha256=_RELATION_SHA256,
        expected_capture_executable_sha256=_EXECUTABLE_SHA256,
        credential=SecretStr(_SECRET),
    )


def _dependencies(
    *,
    capture: _CaptureExecutor | None = None,
    runner: _PrivateRunner | None = None,
) -> tuple[ExecutionDependencies, _CaptureExecutor, _PrivateRunner]:
    actual_capture = capture or _CaptureExecutor()
    actual_runner = runner or _PrivateRunner()
    return (
        ExecutionDependencies(capture_executor=actual_capture, private_runner=actual_runner),
        actual_capture,
        actual_runner,
    )


def test_exact_capture_then_admission_runs_once_in_fixed_order(
    tmp_path: Path, output_root: Path
) -> None:
    relation = _private_file(tmp_path / "relation.receipt", _RELATION_BYTES)
    dependencies, capture, runner = _dependencies()

    result = run_bounded_capture_to_admission(_request(output_root, relation), dependencies)

    assert result.status == "CAPTURE_TO_ADMISSION_VERIFIED"
    assert result.capture_invocations == result.admission_invocations == 1
    assert result.artifact_sha256_by_role == _ARTIFACT_SHA256_BY_ROLE
    assert result.outer_sha256_by_role == _OUTER_SHA256_BY_ROLE
    assert result.common_receipt_digest_sha256 == "5" * 64
    assert result.capture_contract_sha256 == CAPTURE_CONTRACT_SHA256
    assert result.intake_contract_sha256 == INTAKE_CONTRACT_SHA256
    assert result.admission_contract_sha256 == ADMISSION_CONTRACT_SHA256
    assert len(capture.calls) == len(runner.calls) == 1
    assert capture.calls[0].source_sha256_by_role == _SOURCE_SHA256_BY_ROLE
    assert capture.calls[0].retry_budget == 0
    assert capture.calls[0].fallback_enabled is False
    assert capture.calls[0].credential.get_secret_value() == _SECRET
    assert runner.calls[0].ordered() == (
        ("terms", output_root / "terms" / "mineru-native-structure.json"),
        ("brochure", output_root / "brochure" / "mineru-native-structure.json"),
        ("rate_table", output_root / "rate" / "mineru-native-structure.json"),
        ("relation_receipt", relation),
    )
    encoded = json.dumps(result.to_wire(), sort_keys=True)
    for forbidden in (_SECRET, os.fspath(output_root), os.fspath(relation), "Golden", "Release"):
        assert forbidden not in encoded


@pytest.mark.parametrize(
    "status",
    [
        "INPUT_CONTRACT_BLOCKED",
        "INTAKE_VALIDATION_BLOCKED",
        "RELATION_VALIDATION_BLOCKED",
        "ADMISSION_BLOCKED",
        "BLOCKED_ON_CROSS_PAGE_BINDING",
    ],
)
def test_087_blocked_status_is_preserved_without_partial_identity(
    tmp_path: Path, output_root: Path, status: str
) -> None:
    relation = _private_file(tmp_path / "relation.receipt", _RELATION_BYTES)
    runner = _PrivateRunner(
        status=status,
        artifacts=(),
        common_receipt_digest_sha256=None,
    )
    dependencies, capture, runner = _dependencies(runner=runner)

    result = run_bounded_capture_to_admission(_request(output_root, relation), dependencies)

    assert result.status == status
    assert result.capture_invocations == result.admission_invocations == 1
    assert result.artifact_sha256_by_role == {}
    assert result.outer_sha256_by_role == {}
    assert result.common_receipt_digest_sha256 is None
    assert len(capture.calls) == len(runner.calls) == 1


@pytest.mark.parametrize("failure", ["status", "exception"])
def test_capture_failure_stops_before_087_without_retry(
    tmp_path: Path, output_root: Path, failure: str
) -> None:
    relation = _private_file(tmp_path / "relation.receipt", _RELATION_BYTES)
    secret_error = ValueError(f"raw body {_SECRET} https://signed.invalid/token {output_root}")
    capture = (
        _CaptureExecutor(status="FAILED", publish=False)
        if failure == "status"
        else _CaptureExecutor(error=secret_error, publish=False)
    )
    dependencies, capture, runner = _dependencies(capture=capture)

    result = run_bounded_capture_to_admission(_request(output_root, relation), dependencies)

    assert result.status == "CAPTURE_BLOCKED"
    assert result.capture_invocations == 1
    assert result.admission_invocations == 0
    assert len(capture.calls) == 1
    assert runner.calls == []
    encoded = json.dumps(result.to_wire(), sort_keys=True)
    assert _SECRET not in encoded
    assert "signed.invalid" not in encoded
    assert os.fspath(output_root) not in encoded


@pytest.mark.parametrize(
    ("capture_overrides", "expected_status"),
    [
        ({"invocation_count": 2}, "CAPTURE_CONTRACT_BLOCKED"),
        ({"executable_sha256": "a" * 64}, "CAPTURE_CONTRACT_BLOCKED"),
        ({"module_identity_sha256": "b" * 64}, "CAPTURE_CONTRACT_BLOCKED"),
        ({"capture_contract_sha256": "c" * 64}, "CAPTURE_CONTRACT_BLOCKED"),
        (
            {"artifact_sha256_by_role": {**_ARTIFACT_SHA256_BY_ROLE, "terms": "d" * 64}},
            "CAPTURE_CUSTODY_BLOCKED",
        ),
    ],
)
def test_capture_identity_drift_blocks_before_087(
    tmp_path: Path,
    output_root: Path,
    capture_overrides: dict[str, object],
    expected_status: str,
) -> None:
    relation = _private_file(tmp_path / "relation.receipt", _RELATION_BYTES)
    dependencies, capture, runner = _dependencies(
        capture=_CaptureExecutor(overrides=capture_overrides)
    )

    result = run_bounded_capture_to_admission(_request(output_root, relation), dependencies)

    assert result.status == expected_status
    assert len(capture.calls) == 1
    assert runner.calls == []


@pytest.mark.parametrize("case", ["wrong-mode", "extra", "symlink", "wrong-bytes"])
def test_capture_custody_drift_blocks_before_087(
    tmp_path: Path, output_root: Path, case: str
) -> None:
    relation = _private_file(tmp_path / "relation.receipt", _RELATION_BYTES)

    class _DriftCapture(_CaptureExecutor):
        def __call__(self, invocation: CaptureInvocation) -> CaptureExecutionReceipt:
            receipt = super().__call__(invocation)
            target = invocation.output_root / "terms" / "mineru-native-structure.json"
            if case == "wrong-mode":
                target.chmod(0o644)
            elif case == "extra":
                _private_file(invocation.output_root / "terms" / "extra.json", b"extra")
            elif case == "symlink":
                target.unlink()
                target.symlink_to(invocation.output_root / "brochure" / target.name)
            else:
                target.write_bytes(b"drift")
                target.chmod(0o600)
            return receipt

    dependencies, _, runner = _dependencies(capture=_DriftCapture())

    result = run_bounded_capture_to_admission(_request(output_root, relation), dependencies)

    assert result.status == "CAPTURE_CUSTODY_BLOCKED"
    assert runner.calls == []


@pytest.mark.parametrize("case", ["hash", "mode", "parent-mode", "symlink"])
def test_relation_receipt_drift_blocks_before_capture(
    tmp_path: Path, output_root: Path, case: str
) -> None:
    relation_root = tmp_path
    if case == "parent-mode":
        relation_root = tmp_path / "unsafe-relation-root"
        relation_root.mkdir(mode=0o755)
        relation_root.chmod(0o755)
    relation = _private_file(relation_root / "relation.receipt", _RELATION_BYTES)
    expected = _RELATION_SHA256
    if case == "hash":
        expected = "f" * 64
    elif case == "mode":
        relation.chmod(0o644)
    elif case == "symlink":
        target = _private_file(tmp_path / "relation-target", _RELATION_BYTES)
        relation.unlink()
        relation.symlink_to(target)
    dependencies, capture, runner = _dependencies()
    request = replace(_request(output_root, relation), expected_relation_receipt_sha256=expected)

    result = run_bounded_capture_to_admission(request, dependencies)

    assert result.status == "INPUT_CONTRACT_BLOCKED"
    assert capture.calls == []
    assert runner.calls == []


def test_relation_receipt_is_rechecked_after_capture_before_087(
    tmp_path: Path, output_root: Path
) -> None:
    relation = _private_file(tmp_path / "relation.receipt", _RELATION_BYTES)

    class _RelationTakeoverCapture(_CaptureExecutor):
        def __call__(self, invocation: CaptureInvocation) -> CaptureExecutionReceipt:
            receipt = super().__call__(invocation)
            relation.write_bytes(b"foreign relation takeover")
            relation.chmod(0o600)
            return receipt

    dependencies, capture, runner = _dependencies(capture=_RelationTakeoverCapture())

    result = run_bounded_capture_to_admission(_request(output_root, relation), dependencies)

    assert result.status == "INPUT_CONTRACT_BLOCKED"
    assert len(capture.calls) == 1
    assert runner.calls == []


def test_malformed_dependency_results_are_typed_without_raw_exception(
    tmp_path: Path, output_root: Path
) -> None:
    relation = _private_file(tmp_path / "relation.receipt", _RELATION_BYTES)

    class _MalformedCapture:
        def __call__(self, invocation: CaptureInvocation) -> CaptureExecutionReceipt:
            del invocation
            return cast(CaptureExecutionReceipt, object())

    capture_dependencies = ExecutionDependencies(
        capture_executor=_MalformedCapture(),
        private_runner=_PrivateRunner(),
    )
    capture_result = run_bounded_capture_to_admission(
        _request(output_root, relation), capture_dependencies
    )
    assert capture_result.status == "CAPTURE_CONTRACT_BLOCKED"

    shutil.rmtree(output_root, ignore_errors=True)

    class _MalformedRunner:
        def __call__(self, request: PrivateRunnerInput) -> PrivateRunnerResult:
            del request
            return cast(PrivateRunnerResult, object())

    runner_capture = _CaptureExecutor()
    runner_dependencies = ExecutionDependencies(
        capture_executor=runner_capture,
        private_runner=_MalformedRunner(),
    )
    runner_result = run_bounded_capture_to_admission(
        _request(output_root, relation), runner_dependencies
    )
    assert runner_result.status == "ADMISSION_CONTRACT_BLOCKED"


@pytest.mark.parametrize("field", ["intake", "admission", "provider", "golden"])
def test_087_contract_or_external_effect_drift_is_blocked(
    tmp_path: Path, output_root: Path, field: str
) -> None:
    relation = _private_file(tmp_path / "relation.receipt", _RELATION_BYTES)
    runner = _PrivateRunner()
    if field == "intake":
        runner.intake_contract_sha256 = "a" * 64
    elif field == "admission":
        runner.admission_contract_sha256 = "b" * 64
    elif field == "provider":
        runner.provider_calls = 1
    else:
        runner.golden_reads = 1
    dependencies, _, runner = _dependencies(runner=runner)

    result = run_bounded_capture_to_admission(_request(output_root, relation), dependencies)

    assert result.status == "ADMISSION_CONTRACT_BLOCKED"
    assert result.artifact_sha256_by_role == {}
    assert result.outer_sha256_by_role == {}
    assert len(runner.calls) == 1


def test_cli_loads_secret_from_environment_and_never_emits_it(
    tmp_path: Path,
    output_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    relation = _private_file(tmp_path / "relation.receipt", _RELATION_BYTES)
    dependencies, capture, runner = _dependencies()
    argv = (
        "--output-root",
        os.fspath(output_root),
        "--relation-receipt",
        os.fspath(relation),
        "--relation-receipt-sha256",
        _RELATION_SHA256,
        "--capture-executable-sha256",
        _EXECUTABLE_SHA256,
    )

    exit_code = main(argv, dependencies=dependencies, environ={"MINERU_API_KEY": _SECRET})

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["status"] == "CAPTURE_TO_ADMISSION_VERIFIED"
    assert _SECRET not in captured.out
    assert os.fspath(output_root) not in captured.out
    assert os.fspath(relation) not in captured.out
    assert len(capture.calls) == len(runner.calls) == 1


def test_cli_missing_composition_or_credential_performs_zero_io(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main((), dependencies=None, environ={}) == 2
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "DEPENDENCY_UNAVAILABLE"

    dependencies, capture, runner = _dependencies()
    assert main((), dependencies=dependencies, environ={}) == 2
    second = json.loads(capsys.readouterr().out)
    assert second["status"] == "CREDENTIAL_UNAVAILABLE"
    assert capture.calls == []
    assert runner.calls == []


def test_subprocess_adapter_uses_one_no_shell_command_and_secret_only_in_environment(
    tmp_path: Path, output_root: Path
) -> None:
    executable = tmp_path / "mineru-capture-596-1"
    executable.write_bytes(b"synthetic executable")
    executable.chmod(0o700)
    executable_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    process_calls: list[tuple[Sequence[str], Mapping[str, Any]]] = []

    def _run_process(argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        process_calls.append((argv, kwargs))
        _publish_capture_tree(output_root)
        return subprocess.CompletedProcess(argv, 0)

    executor = SubprocessCaptureExecutor(
        executable=executable,
        repository_root=tmp_path,
        process_runner=_run_process,
    )
    invocation = CaptureInvocation(
        output_root=output_root,
        expected_executable_sha256=executable_sha256,
        credential=SecretStr(_SECRET),
        source_sha256_by_role=dict(_SOURCE_SHA256_BY_ROLE),
        retry_budget=0,
        fallback_enabled=False,
    )

    receipt = executor(invocation)

    assert receipt.status == "COMPLETED"
    assert receipt.invocation_count == 1
    assert len(process_calls) == 1
    argv, kwargs = process_calls[0]
    assert tuple(argv) == (os.fspath(executable), "--output-root", os.fspath(output_root))
    assert _SECRET not in repr(argv)
    assert kwargs["shell"] is False
    assert kwargs["check"] is False
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["env"]["MINERU_API_KEY"] == _SECRET
    assert kwargs["cwd"] == os.fspath(tmp_path)


def test_subprocess_adapter_rejects_symlink_or_nonzero_without_retry(
    tmp_path: Path, output_root: Path
) -> None:
    executable = tmp_path / "mineru-capture-596-1-real"
    executable.write_bytes(b"synthetic executable")
    executable.chmod(stat.S_IRWXU)
    linked = tmp_path / "mineru-capture-596-1"
    linked.symlink_to(executable)
    calls: list[Sequence[str]] = []

    def _run_process(argv: Sequence[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1)

    invocation = CaptureInvocation(
        output_root=output_root,
        expected_executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
        credential=SecretStr(_SECRET),
        source_sha256_by_role=dict(_SOURCE_SHA256_BY_ROLE),
        retry_budget=0,
        fallback_enabled=False,
    )
    linked_executor = SubprocessCaptureExecutor(
        executable=linked,
        repository_root=tmp_path,
        process_runner=_run_process,
    )
    assert linked_executor(invocation).status == "BLOCKED"
    assert calls == []

    direct_executor = SubprocessCaptureExecutor(
        executable=executable,
        repository_root=tmp_path,
        process_runner=_run_process,
    )
    assert direct_executor(invocation).status == "BLOCKED"
    assert len(calls) == 1
