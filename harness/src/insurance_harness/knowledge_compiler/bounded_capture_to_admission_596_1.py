"""One-shot 596-1 MinerU capture-to-admission orchestration.

This task-local module owns orchestration only. It neither parses capture payloads nor derives
relations or admission. The concrete subprocess adapter invokes the existing Go command exactly
once; the 087-facing adapter remains an injected narrow port until its dependency stack merges.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

from pydantic import SecretStr

ArtifactRole = Literal["terms", "brochure", "rate_table"]
ExecutionStatus = Literal[
    "DEPENDENCY_UNAVAILABLE",
    "CREDENTIAL_UNAVAILABLE",
    "INPUT_CONTRACT_BLOCKED",
    "CAPTURE_BLOCKED",
    "CAPTURE_CONTRACT_BLOCKED",
    "CAPTURE_CUSTODY_BLOCKED",
    "INTAKE_VALIDATION_BLOCKED",
    "RELATION_VALIDATION_BLOCKED",
    "ADMISSION_BLOCKED",
    "EXTERNAL_EFFECT_CONTRACT_VIOLATION",
    "BLOCKED_ON_CROSS_PAGE_BINDING",
    "ADMISSION_CONTRACT_BLOCKED",
    "CAPTURE_TO_ADMISSION_VERIFIED",
]

CAPTURE_CONTRACT_ID = "mineru-three-source-capture-596-1.v1"
INTAKE_CONTRACT_ID = "mineru-capture-intake-596-1.v1"
ADMISSION_CONTRACT_ID = "596-1-private-artifact-admission-runner.v1"
CAPTURE_MODULE_ID = "github.com/Tencent/WeKnora/cmd/mineru-capture-596-1"


def _identity_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


CAPTURE_CONTRACT_SHA256 = _identity_sha256(CAPTURE_CONTRACT_ID)
INTAKE_CONTRACT_SHA256 = _identity_sha256(INTAKE_CONTRACT_ID)
ADMISSION_CONTRACT_SHA256 = _identity_sha256(ADMISSION_CONTRACT_ID)
CAPTURE_MODULE_IDENTITY_SHA256 = _identity_sha256(CAPTURE_MODULE_ID)

_ROLES: tuple[ArtifactRole, ...] = ("terms", "brochure", "rate_table")
_CAPTURE_DIRECTORY_BY_ROLE = {"terms": "terms", "brochure": "brochure", "rate_table": "rate"}
_CAPTURE_ARTIFACT_NAME = "mineru-native-structure.json"
_SOURCE_SHA256_BY_ROLE: dict[str, str] = {
    "terms": "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
    "brochure": "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
    "rate_table": "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
}
_HEX = frozenset("0123456789abcdef")
_BLOCKED_087_STATUSES: frozenset[str] = frozenset(
    {
        "DEPENDENCY_UNAVAILABLE",
        "INPUT_CONTRACT_BLOCKED",
        "INTAKE_VALIDATION_BLOCKED",
        "RELATION_VALIDATION_BLOCKED",
        "ADMISSION_BLOCKED",
        "EXTERNAL_EFFECT_CONTRACT_VIOLATION",
        "BLOCKED_ON_CROSS_PAGE_BINDING",
    }
)


@dataclass(frozen=True)
class CaptureInvocation:
    output_root: Path
    expected_executable_sha256: str
    credential: SecretStr
    source_sha256_by_role: Mapping[str, str]
    retry_budget: Literal[0] = 0
    fallback_enabled: Literal[False] = False


@dataclass(frozen=True)
class CaptureExecutionReceipt:
    status: str
    invocation_count: int
    executable_sha256: str
    module_identity_sha256: str
    capture_contract_sha256: str
    artifact_sha256_by_role: Mapping[str, str]


@dataclass(frozen=True)
class PrivateRunnerInput:
    terms: Path
    brochure: Path
    rate_table: Path
    relation_receipt: Path

    def ordered(self) -> tuple[tuple[str, Path], ...]:
        return (
            ("terms", self.terms),
            ("brochure", self.brochure),
            ("rate_table", self.rate_table),
            ("relation_receipt", self.relation_receipt),
        )


@dataclass(frozen=True)
class SafeRunnerArtifact:
    role: str
    artifact_sha256: str
    outer_sha256: str


@dataclass(frozen=True)
class PrivateRunnerResult:
    status: str
    intake_contract_sha256: str
    admission_contract_sha256: str
    artifacts: tuple[SafeRunnerArtifact, ...]
    common_receipt_digest_sha256: str | None
    provider_calls: int
    golden_reads: int


class CaptureExecutorPort(Protocol):
    def __call__(self, invocation: CaptureInvocation) -> CaptureExecutionReceipt: ...


class PrivateRunnerPort(Protocol):
    def __call__(self, request: PrivateRunnerInput) -> PrivateRunnerResult: ...


@dataclass(frozen=True)
class ExecutionDependencies:
    capture_executor: CaptureExecutorPort
    private_runner: PrivateRunnerPort


@dataclass(frozen=True)
class ExecutionRequest:
    output_root: Path
    relation_receipt: Path
    expected_relation_receipt_sha256: str
    expected_capture_executable_sha256: str
    credential: SecretStr


@dataclass(frozen=True)
class ExecutionResult:
    status: ExecutionStatus
    capture_invocations: int = 0
    admission_invocations: int = 0
    artifact_sha256_by_role: Mapping[str, str] | None = None
    outer_sha256_by_role: Mapping[str, str] | None = None
    common_receipt_digest_sha256: str | None = None
    executable_sha256: str | None = None
    module_identity_sha256: str | None = None
    capture_contract_sha256: str | None = None
    intake_contract_sha256: str | None = None
    admission_contract_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.artifact_sha256_by_role is None:
            object.__setattr__(self, "artifact_sha256_by_role", {})
        if self.outer_sha256_by_role is None:
            object.__setattr__(self, "outer_sha256_by_role", {})

    def to_wire(self) -> dict[str, object]:
        return {
            "admission_contract_sha256": self.admission_contract_sha256,
            "admission_invocations": self.admission_invocations,
            "artifact_sha256_by_role": dict(self.artifact_sha256_by_role or {}),
            "capture_contract_sha256": self.capture_contract_sha256,
            "capture_invocations": self.capture_invocations,
            "common_receipt_digest_sha256": self.common_receipt_digest_sha256,
            "executable_sha256": self.executable_sha256,
            "intake_contract_sha256": self.intake_contract_sha256,
            "module_identity_sha256": self.module_identity_sha256,
            "outer_sha256_by_role": dict(self.outer_sha256_by_role or {}),
            "status": self.status,
        }


ProcessRunner = Callable[..., subprocess.CompletedProcess[bytes]]


class SubprocessCaptureExecutor:
    """Invoke only the existing Go capture executable without a shell or output capture."""

    def __init__(
        self,
        *,
        executable: Path,
        repository_root: Path,
        process_runner: ProcessRunner = subprocess.run,
    ) -> None:
        self._executable = executable
        self._repository_root = repository_root
        self._process_runner = process_runner

    def __call__(self, invocation: CaptureInvocation) -> CaptureExecutionReceipt:
        blocked = _capture_receipt("BLOCKED", invocation.expected_executable_sha256)
        if not _valid_capture_invocation(invocation):
            return blocked
        try:
            executable_sha256 = _validate_executable(
                self._executable, invocation.expected_executable_sha256
            )
            _validate_repository_root(self._repository_root)
            process = self._process_runner(
                [
                    os.fspath(self._executable),
                    "--output-root",
                    os.fspath(invocation.output_root),
                ],
                cwd=os.fspath(self._repository_root),
                env={"MINERU_API_KEY": invocation.credential.get_secret_value()},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
            )
            if type(process.returncode) is not int or process.returncode != 0:
                return blocked
            _, artifact_hashes = _validate_capture_tree(invocation.output_root, None)
        except Exception:
            return blocked
        return CaptureExecutionReceipt(
            status="COMPLETED",
            invocation_count=1,
            executable_sha256=executable_sha256,
            module_identity_sha256=CAPTURE_MODULE_IDENTITY_SHA256,
            capture_contract_sha256=CAPTURE_CONTRACT_SHA256,
            artifact_sha256_by_role=artifact_hashes,
        )


def _capture_receipt(status: str, executable_sha256: str) -> CaptureExecutionReceipt:
    return CaptureExecutionReceipt(
        status=status,
        invocation_count=1,
        executable_sha256=executable_sha256,
        module_identity_sha256=CAPTURE_MODULE_IDENTITY_SHA256,
        capture_contract_sha256=CAPTURE_CONTRACT_SHA256,
        artifact_sha256_by_role={},
    )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(character in _HEX for character in value)


def _exact_hash_mapping(value: object) -> dict[str, str] | None:
    if not isinstance(value, Mapping) or set(value) != set(_ROLES):
        return None
    copied = dict(value)
    if any(not _is_sha256(item) for item in copied.values()):
        return None
    return copied


def _valid_capture_invocation(invocation: CaptureInvocation) -> bool:
    return (
        isinstance(invocation.output_root, Path)
        and _valid_new_output_root(invocation.output_root)
        and _is_sha256(invocation.expected_executable_sha256)
        and type(invocation.credential) is SecretStr
        and bool(invocation.credential.get_secret_value().strip())
        and dict(invocation.source_sha256_by_role) == _SOURCE_SHA256_BY_ROLE
        and invocation.retry_budget == 0
        and invocation.fallback_enabled is False
    )


def _valid_new_output_root(path: Path) -> bool:
    return (
        path.is_absolute()
        and path.parent == Path("/private/tmp")
        and path.name not in {"", ".", ".."}
        and not os.path.lexists(path)
    )


def _validate_repository_root(path: Path) -> None:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("invalid repository root")


def _validate_executable(path: Path, expected_sha256: str) -> str:
    metadata = os.lstat(path)
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or mode & stat.S_IXUSR == 0
        or mode & 0o022 != 0
    ):
        raise ValueError("invalid executable")
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        payload = _read_descriptor(descriptor)
    finally:
        os.close(descriptor)
    actual = _sha256(payload)
    if actual != expected_sha256:
        raise ValueError("executable identity mismatch")
    return actual


def _read_descriptor(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _read_private_file(path: Path) -> tuple[bytes, tuple[int, int]]:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise ValueError("invalid private file")
        return _read_descriptor(descriptor), (metadata.st_dev, metadata.st_ino)
    finally:
        os.close(descriptor)


def _validate_relation_receipt(request: ExecutionRequest) -> tuple[int, int]:
    if not isinstance(request.relation_receipt, Path):
        raise ValueError("invalid relation receipt")
    parent_metadata = os.lstat(request.relation_receipt.parent)
    if (
        stat.S_ISLNK(parent_metadata.st_mode)
        or not stat.S_ISDIR(parent_metadata.st_mode)
        or stat.S_IMODE(parent_metadata.st_mode) != 0o700
    ):
        raise ValueError("invalid relation receipt root")
    payload, identity = _read_private_file(request.relation_receipt)
    if _sha256(payload) != request.expected_relation_receipt_sha256:
        raise ValueError("relation receipt identity mismatch")
    return identity


def _validate_capture_directory(path: Path, expected_entries: set[str]) -> None:
    metadata = os.lstat(path)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or set(os.listdir(path)) != expected_entries
    ):
        raise ValueError("capture directory custody mismatch")


def _validate_capture_tree(
    output_root: Path,
    relation_identity: tuple[int, int] | None,
) -> tuple[dict[str, Path], dict[str, str]]:
    _validate_capture_directory(output_root, set(_CAPTURE_DIRECTORY_BY_ROLE.values()))
    paths: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    identities: set[tuple[int, int]] = set()
    if relation_identity is not None:
        identities.add(relation_identity)
    for role in _ROLES:
        directory = output_root / _CAPTURE_DIRECTORY_BY_ROLE[role]
        _validate_capture_directory(directory, {_CAPTURE_ARTIFACT_NAME})
        artifact = directory / _CAPTURE_ARTIFACT_NAME
        payload, identity = _read_private_file(artifact)
        if identity in identities:
            raise ValueError("duplicate artifact identity")
        identities.add(identity)
        paths[role] = artifact
        hashes[role] = _sha256(payload)
    return paths, hashes


def _valid_request(request: ExecutionRequest) -> bool:
    return (
        isinstance(request.output_root, Path)
        and _valid_new_output_root(request.output_root)
        and isinstance(request.relation_receipt, Path)
        and _is_sha256(request.expected_relation_receipt_sha256)
        and _is_sha256(request.expected_capture_executable_sha256)
        and type(request.credential) is SecretStr
        and bool(request.credential.get_secret_value().strip())
    )


def _blocked(
    status: ExecutionStatus,
    *,
    capture_invocations: int = 0,
    admission_invocations: int = 0,
) -> ExecutionResult:
    return ExecutionResult(
        status=status,
        capture_invocations=capture_invocations,
        admission_invocations=admission_invocations,
    )


def _validate_capture_receipt(
    receipt: CaptureExecutionReceipt,
    request: ExecutionRequest,
) -> dict[str, str] | None:
    hashes = _exact_hash_mapping(receipt.artifact_sha256_by_role)
    if (
        receipt.status != "COMPLETED"
        or type(receipt.invocation_count) is not int
        or receipt.invocation_count != 1
        or receipt.executable_sha256 != request.expected_capture_executable_sha256
        or receipt.module_identity_sha256 != CAPTURE_MODULE_IDENTITY_SHA256
        or receipt.capture_contract_sha256 != CAPTURE_CONTRACT_SHA256
        or hashes is None
    ):
        return None
    return hashes


def _validate_successful_runner(
    runner_result: PrivateRunnerResult,
    artifact_hashes: Mapping[str, str],
) -> tuple[dict[str, str], str] | None:
    if (
        runner_result.status != "COMPOSITION_SEAM_VERIFIED"
        or type(runner_result.artifacts) is not tuple
        or len(runner_result.artifacts) != len(_ROLES)
        or not _is_sha256(runner_result.common_receipt_digest_sha256)
    ):
        return None
    outer: dict[str, str] = {}
    for expected_role, artifact in zip(_ROLES, runner_result.artifacts, strict=True):
        if (
            artifact.role != expected_role
            or artifact.artifact_sha256 != artifact_hashes[expected_role]
            or not _is_sha256(artifact.outer_sha256)
        ):
            return None
        outer[expected_role] = artifact.outer_sha256
    assert runner_result.common_receipt_digest_sha256 is not None
    return outer, runner_result.common_receipt_digest_sha256


def run_bounded_capture_to_admission(
    request: ExecutionRequest,
    dependencies: ExecutionDependencies,
) -> ExecutionResult:
    """Run one capture then one private admission call, returning only safe identities."""

    if not _valid_request(request):
        return _blocked("INPUT_CONTRACT_BLOCKED")
    try:
        relation_identity = _validate_relation_receipt(request)
    except (OSError, ValueError):
        return _blocked("INPUT_CONTRACT_BLOCKED")

    invocation = CaptureInvocation(
        output_root=request.output_root,
        expected_executable_sha256=request.expected_capture_executable_sha256,
        credential=request.credential,
        source_sha256_by_role=dict(_SOURCE_SHA256_BY_ROLE),
    )
    try:
        capture_receipt = dependencies.capture_executor(invocation)
    except Exception:
        return _blocked("CAPTURE_BLOCKED", capture_invocations=1)
    try:
        capture_status = capture_receipt.status
    except Exception:
        return _blocked("CAPTURE_CONTRACT_BLOCKED", capture_invocations=1)
    if capture_status != "COMPLETED":
        return _blocked("CAPTURE_BLOCKED", capture_invocations=1)
    try:
        reported_hashes = _validate_capture_receipt(capture_receipt, request)
    except Exception:
        return _blocked("CAPTURE_CONTRACT_BLOCKED", capture_invocations=1)
    if reported_hashes is None:
        return _blocked("CAPTURE_CONTRACT_BLOCKED", capture_invocations=1)
    try:
        artifact_paths, actual_hashes = _validate_capture_tree(
            request.output_root, relation_identity
        )
    except (OSError, ValueError):
        return _blocked("CAPTURE_CUSTODY_BLOCKED", capture_invocations=1)
    if reported_hashes != actual_hashes:
        return _blocked("CAPTURE_CUSTODY_BLOCKED", capture_invocations=1)
    try:
        fresh_relation_identity = _validate_relation_receipt(request)
    except (OSError, ValueError):
        return _blocked("INPUT_CONTRACT_BLOCKED", capture_invocations=1)
    if fresh_relation_identity != relation_identity:
        return _blocked("INPUT_CONTRACT_BLOCKED", capture_invocations=1)
    runner_input = PrivateRunnerInput(
        terms=artifact_paths["terms"],
        brochure=artifact_paths["brochure"],
        rate_table=artifact_paths["rate_table"],
        relation_receipt=request.relation_receipt,
    )
    try:
        runner_result = dependencies.private_runner(runner_input)
    except Exception:
        return _blocked(
            "ADMISSION_BLOCKED", capture_invocations=1, admission_invocations=1
        )
    try:
        if (
            type(runner_result.provider_calls) is not int
            or type(runner_result.golden_reads) is not int
            or runner_result.provider_calls != 0
            or runner_result.golden_reads != 0
            or runner_result.intake_contract_sha256 != INTAKE_CONTRACT_SHA256
            or runner_result.admission_contract_sha256 != ADMISSION_CONTRACT_SHA256
        ):
            return _blocked(
                "ADMISSION_CONTRACT_BLOCKED",
                capture_invocations=1,
                admission_invocations=1,
            )
        if runner_result.status in _BLOCKED_087_STATUSES:
            if runner_result.artifacts or runner_result.common_receipt_digest_sha256 is not None:
                return _blocked(
                    "ADMISSION_CONTRACT_BLOCKED",
                    capture_invocations=1,
                    admission_invocations=1,
                )
            return _blocked(
                cast(ExecutionStatus, runner_result.status),
                capture_invocations=1,
                admission_invocations=1,
            )
        successful = _validate_successful_runner(runner_result, actual_hashes)
    except Exception:
        return _blocked(
            "ADMISSION_CONTRACT_BLOCKED",
            capture_invocations=1,
            admission_invocations=1,
        )
    if successful is None:
        return _blocked(
            "ADMISSION_CONTRACT_BLOCKED",
            capture_invocations=1,
            admission_invocations=1,
        )
    outer_hashes, receipt_digest = successful
    return ExecutionResult(
        status="CAPTURE_TO_ADMISSION_VERIFIED",
        capture_invocations=1,
        admission_invocations=1,
        artifact_sha256_by_role=actual_hashes,
        outer_sha256_by_role=outer_hashes,
        common_receipt_digest_sha256=receipt_digest,
        executable_sha256=request.expected_capture_executable_sha256,
        module_identity_sha256=CAPTURE_MODULE_IDENTITY_SHA256,
        capture_contract_sha256=CAPTURE_CONTRACT_SHA256,
        intake_contract_sha256=INTAKE_CONTRACT_SHA256,
        admission_contract_sha256=ADMISSION_CONTRACT_SHA256,
    )


_CLI_FLAGS = (
    "--output-root",
    "--relation-receipt",
    "--relation-receipt-sha256",
    "--capture-executable-sha256",
)


def _parse_cli(arguments: Sequence[str], credential: SecretStr) -> ExecutionRequest | None:
    if len(arguments) != len(_CLI_FLAGS) * 2:
        return None
    values: dict[str, str] = {}
    for index in range(0, len(arguments), 2):
        flag = arguments[index]
        value = arguments[index + 1]
        if flag not in _CLI_FLAGS or flag in values or not value:
            return None
        values[flag] = value
    if set(values) != set(_CLI_FLAGS):
        return None
    return ExecutionRequest(
        output_root=Path(values["--output-root"]),
        relation_receipt=Path(values["--relation-receipt"]),
        expected_relation_receipt_sha256=values["--relation-receipt-sha256"],
        expected_capture_executable_sha256=values["--capture-executable-sha256"],
        credential=credential,
    )


def _emit(result: ExecutionResult) -> None:
    print(json.dumps(result.to_wire(), sort_keys=True, separators=(",", ":")))


def main(
    argv: Sequence[str] | None = None,
    *,
    dependencies: ExecutionDependencies | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if dependencies is None:
        _emit(_blocked("DEPENDENCY_UNAVAILABLE"))
        return 2
    environment = os.environ if environ is None else environ
    raw_credential = environment.get("MINERU_API_KEY")
    if type(raw_credential) is not str or not raw_credential.strip():
        _emit(_blocked("CREDENTIAL_UNAVAILABLE"))
        return 2
    request = _parse_cli(arguments, SecretStr(raw_credential))
    if request is None:
        _emit(_blocked("INPUT_CONTRACT_BLOCKED"))
        return 2
    result = run_bounded_capture_to_admission(request, dependencies)
    _emit(result)
    return 0 if result.status == "CAPTURE_TO_ADMISSION_VERIFIED" else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ADMISSION_CONTRACT_ID",
    "ADMISSION_CONTRACT_SHA256",
    "CAPTURE_CONTRACT_ID",
    "CAPTURE_CONTRACT_SHA256",
    "CAPTURE_MODULE_ID",
    "CAPTURE_MODULE_IDENTITY_SHA256",
    "INTAKE_CONTRACT_ID",
    "INTAKE_CONTRACT_SHA256",
    "CaptureExecutionReceipt",
    "CaptureInvocation",
    "ExecutionDependencies",
    "ExecutionRequest",
    "ExecutionResult",
    "PrivateRunnerInput",
    "PrivateRunnerResult",
    "SafeRunnerArtifact",
    "SubprocessCaptureExecutor",
    "main",
    "run_bounded_capture_to_admission",
]
