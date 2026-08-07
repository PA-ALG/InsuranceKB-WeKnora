"""Task-local composition seam for the 596-1 private MinerU artifacts.

The module deliberately owns no content parser, digest implementation, provider client or
admission logic. 083, 086 and 084 adapters are injected through the three narrow ports below.
Until those adapters are composed, the command fails closed as ``DEPENDENCY_UNAVAILABLE``.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

ArtifactRole = Literal["terms", "brochure", "rate_table"]
RunnerStatus = Literal[
    "DEPENDENCY_UNAVAILABLE",
    "INPUT_CONTRACT_BLOCKED",
    "INTAKE_VALIDATION_BLOCKED",
    "RELATION_VALIDATION_BLOCKED",
    "ADMISSION_BLOCKED",
    "EXTERNAL_EFFECT_CONTRACT_VIOLATION",
    "BLOCKED_ON_CROSS_PAGE_BINDING",
    "COMPOSITION_SEAM_VERIFIED",
]

_ROLES: tuple[ArtifactRole, ...] = ("terms", "brochure", "rate_table")
_HEX = frozenset("0123456789abcdef")
_SAFE_CONTRACT_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._-")


class ValidatedIntakePort(Protocol):
    @property
    def role(self) -> str: ...

    @property
    def contract_id(self) -> str: ...

    @property
    def outer_sha256(self) -> str: ...

    @property
    def artifact_sha256(self) -> str: ...

    @property
    def parser_identity_sha256(self) -> str: ...

    @property
    def attempt_identity_sha256(self) -> str: ...


class ValidatedRelationPort(Protocol):
    @property
    def status(self) -> str: ...

    @property
    def receipt_sha256(self) -> str: ...

    @property
    def artifact_outer_sha256_by_role(self) -> Mapping[str, str]: ...

    @property
    def artifact_sha256_by_role(self) -> Mapping[str, str]: ...

    @property
    def parser_identity_sha256_by_role(self) -> Mapping[str, str]: ...

    @property
    def attempt_identity_sha256_by_role(self) -> Mapping[str, str]: ...

    @property
    def bindings(self) -> tuple[object, ...]: ...


class AdmissionResultPort(Protocol):
    @property
    def status(self) -> str: ...

    @property
    def provider_calls(self) -> int: ...

    @property
    def golden_reads(self) -> int: ...

    @property
    def receipt_digest_sha256(self) -> str | None: ...


class IntakeValidatorPort(Protocol):
    def __call__(self, artifact_bytes: bytes, *, expected_role: str) -> ValidatedIntakePort: ...


class RelationValidatorPort(Protocol):
    def __call__(self, receipt_bytes: bytes) -> ValidatedRelationPort: ...


class AdmissionAssemblerPort(Protocol):
    def __call__(
        self,
        *,
        validated_intakes: tuple[ValidatedIntakePort, ...],
        relation_bindings: tuple[object, ...],
    ) -> AdmissionResultPort: ...


@dataclass(frozen=True)
class RunnerDependencies:
    intake_validator: IntakeValidatorPort
    relation_validator: RelationValidatorPort
    admission_assembler: AdmissionAssemblerPort


@dataclass(frozen=True)
class PrivateArtifactPaths:
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
class SafeArtifactIdentity:
    role: ArtifactRole
    contract_id: str
    outer_sha256: str
    artifact_sha256: str

    def to_wire(self) -> dict[str, str]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "contract_id": self.contract_id,
            "outer_sha256": self.outer_sha256,
            "role": self.role,
        }


@dataclass(frozen=True)
class PrivateAdmissionRunnerResult:
    status: RunnerStatus
    artifacts: tuple[SafeArtifactIdentity, ...] = ()
    common_receipt_digest_sha256: str | None = None
    provider_calls: Literal[0] = 0
    golden_reads: Literal[0] = 0

    def to_wire(self) -> dict[str, object]:
        return {
            "artifacts": [artifact.to_wire() for artifact in self.artifacts],
            "common_receipt_digest_sha256": self.common_receipt_digest_sha256,
            "golden_reads": self.golden_reads,
            "provider_calls": self.provider_calls,
            "status": self.status,
        }


class _InputContractError(Exception):
    pass


class _IntakeContractError(Exception):
    pass


class _RelationContractError(Exception):
    pass


def _blocked(status: RunnerStatus) -> PrivateAdmissionRunnerResult:
    return PrivateAdmissionRunnerResult(status=status)


def _is_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(character in _HEX for character in value)


def _is_safe_contract_id(value: object) -> bool:
    return (
        type(value) is str
        and 1 <= len(value) <= 64
        and value[0] in "abcdefghijklmnopqrstuvwxyz0123456789"
        and all(character in _SAFE_CONTRACT_CHARS for character in value)
    )


def _read_private_file(path: Path) -> tuple[bytes, tuple[int, int]]:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise _InputContractError
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise _InputContractError
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks), (metadata.st_dev, metadata.st_ino)
    finally:
        os.close(descriptor)


def _read_exact_inputs(paths: PrivateArtifactPaths) -> dict[str, bytes]:
    read: dict[str, bytes] = {}
    identities: set[tuple[int, int]] = set()
    for name, path in paths.ordered():
        if not isinstance(path, Path):
            raise _InputContractError
        payload, identity = _read_private_file(path)
        if identity in identities:
            raise _InputContractError
        identities.add(identity)
        read[name] = payload
    return read


def _validate_intake_identity(
    intake: ValidatedIntakePort, *, expected_role: ArtifactRole
) -> SafeArtifactIdentity:
    if intake.role != expected_role:
        raise _IntakeContractError
    if not _is_safe_contract_id(intake.contract_id):
        raise _IntakeContractError
    for digest in (
        intake.outer_sha256,
        intake.artifact_sha256,
        intake.parser_identity_sha256,
        intake.attempt_identity_sha256,
    ):
        if not _is_sha256(digest):
            raise _IntakeContractError
    return SafeArtifactIdentity(
        role=expected_role,
        contract_id=intake.contract_id,
        outer_sha256=intake.outer_sha256,
        artifact_sha256=intake.artifact_sha256,
    )


def _exact_role_mapping(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(_ROLES):
        raise _RelationContractError
    if any(not _is_sha256(item) for item in value.values()):
        raise _RelationContractError
    return value


def _validate_relation(
    relation: ValidatedRelationPort,
    intakes: tuple[ValidatedIntakePort, ...],
) -> tuple[object, ...]:
    if relation.status != "VALIDATED" or not _is_sha256(relation.receipt_sha256):
        raise _RelationContractError
    outer = _exact_role_mapping(relation.artifact_outer_sha256_by_role)
    artifact = _exact_role_mapping(relation.artifact_sha256_by_role)
    parser = _exact_role_mapping(relation.parser_identity_sha256_by_role)
    attempt = _exact_role_mapping(relation.attempt_identity_sha256_by_role)
    for role, intake in zip(_ROLES, intakes, strict=True):
        if (
            outer[role] != intake.outer_sha256
            or artifact[role] != intake.artifact_sha256
            or parser[role] != intake.parser_identity_sha256
            or attempt[role] != intake.attempt_identity_sha256
        ):
            raise _RelationContractError
    if type(relation.bindings) is not tuple or not relation.bindings:
        raise _RelationContractError
    return relation.bindings


def run_private_artifact_admission(
    paths: PrivateArtifactPaths,
    dependencies: RunnerDependencies,
) -> PrivateAdmissionRunnerResult:
    """Compose validated private inputs without claiming real runtime admission."""

    try:
        payloads = _read_exact_inputs(paths)
    except (OSError, _InputContractError):
        return _blocked("INPUT_CONTRACT_BLOCKED")

    intakes: list[ValidatedIntakePort] = []
    safe_identities: list[SafeArtifactIdentity] = []
    for role in _ROLES:
        try:
            intake = dependencies.intake_validator(payloads[role], expected_role=role)
            safe_identity = _validate_intake_identity(intake, expected_role=role)
        except Exception:
            return _blocked("INTAKE_VALIDATION_BLOCKED")
        intakes.append(intake)
        safe_identities.append(safe_identity)

    try:
        relation = dependencies.relation_validator(payloads["relation_receipt"])
        bindings = _validate_relation(relation, tuple(intakes))
    except Exception:
        return _blocked("RELATION_VALIDATION_BLOCKED")

    try:
        assembled = dependencies.admission_assembler(
            validated_intakes=tuple(intakes),
            relation_bindings=bindings,
        )
    except Exception:
        return _blocked("ADMISSION_BLOCKED")

    if (
        type(assembled.provider_calls) is not int
        or type(assembled.golden_reads) is not int
        or assembled.provider_calls != 0
        or assembled.golden_reads != 0
    ):
        return _blocked("EXTERNAL_EFFECT_CONTRACT_VIOLATION")
    if assembled.status == "BLOCKED_ON_CROSS_PAGE_BINDING":
        return _blocked("BLOCKED_ON_CROSS_PAGE_BINDING")
    if assembled.status != "READY" or not _is_sha256(assembled.receipt_digest_sha256):
        return _blocked("ADMISSION_BLOCKED")
    return PrivateAdmissionRunnerResult(
        status="COMPOSITION_SEAM_VERIFIED",
        artifacts=tuple(safe_identities),
        common_receipt_digest_sha256=assembled.receipt_digest_sha256,
    )


_CLI_FLAGS = (
    "--terms-artifact",
    "--brochure-artifact",
    "--rate-artifact",
    "--relation-receipt",
)


def _parse_cli(argv: Sequence[str]) -> PrivateArtifactPaths | None:
    if len(argv) != 8:
        return None
    values: dict[str, Path] = {}
    for index in range(0, len(argv), 2):
        flag = argv[index]
        value = argv[index + 1]
        if flag not in _CLI_FLAGS or flag in values or not value:
            return None
        values[flag] = Path(value)
    if set(values) != set(_CLI_FLAGS):
        return None
    return PrivateArtifactPaths(
        terms=values["--terms-artifact"],
        brochure=values["--brochure-artifact"],
        rate_table=values["--rate-artifact"],
        relation_receipt=values["--relation-receipt"],
    )


def _emit(result: PrivateAdmissionRunnerResult) -> None:
    print(json.dumps(result.to_wire(), sort_keys=True, separators=(",", ":")))


def main(
    argv: Sequence[str] | None = None,
    *,
    dependencies: RunnerDependencies | None = None,
) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if dependencies is None:
        _emit(_blocked("DEPENDENCY_UNAVAILABLE"))
        return 2
    paths = _parse_cli(arguments)
    if paths is None:
        _emit(_blocked("INPUT_CONTRACT_BLOCKED"))
        return 2
    result = run_private_artifact_admission(paths, dependencies)
    _emit(result)
    return 0 if result.status == "COMPOSITION_SEAM_VERIFIED" else 2


if __name__ == "__main__":  # pragma: no cover - exercised through ``main``.
    raise SystemExit(main())
