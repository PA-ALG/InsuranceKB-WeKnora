"""Protected canary artifacts and unsigned review-candidate derivation.

The artifact tree is deliberately outside the immutable admission input tree.  A
bundle is committed by writing each content file durably and writing its evidence
index last.  The unsigned candidate is a display of the exact payload a deployment
approver may sign; neither this module nor the evaluator treats it as authority.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict

from insurance_harness.goldenset.admission import (
    ArtifactEvidenceInspectionError,
    ArtifactEvidenceInspector,
    ExecutionTarget,
    InitialExecutionAuthorization,
    RunAdmissionDocument,
    RuntimeAdmissionDecision,
    execution_plan_hash,
)
from insurance_harness.goldenset.admission_budget import (
    BudgetLedger,
    BudgetLedgerError,
    ProductSettlementAttempt,
    ProductSettlementSnapshot,
    role_rate_cost,
    role_rate_digest,
)
from insurance_harness.goldenset.admission_models import (
    CanaryReviewArtifactEvidence,
    CanaryReviewTarget,
    CanaryReviewUsageEvidence,
    canonical_json_bytes,
    plan_payload_hash,
)

_PRODUCTION_RUN_ROOT = Path("/var/lib/insurancekb/run-admission/runs")
_FIRST_STAGE: Final[Literal["annotation"]] = "annotation"
_FIRST_PRODUCT: Final[Literal["平安爱满分（2026）两全保险"]] = (
    "平安爱满分（2026）两全保险"
)
_SECOND_STAGE: Final[Literal["annotation"]] = "annotation"
_SECOND_PRODUCT: Final[Literal["平安附加（2026）意外伤害保险"]] = (
    "平安附加（2026）意外伤害保险"
)
type _AnnotationProduct = Literal[
    "平安爱满分（2026）两全保险",
    "平安附加（2026）意外伤害保险",
]
_CANARY_REVIEW_SCOPE = "canary-review:gs-v0.1"


def _annotation_product(product_id: str) -> _AnnotationProduct:
    if product_id not in {_FIRST_PRODUCT, _SECOND_PRODUCT}:
        raise ValueError("product_id is not a code-fixed annotation target")
    return product_id


def _annotation_target_directory(product_id: str) -> str:
    target_product = _annotation_product(product_id)
    return hashlib.sha256(
        b"insurancekb.run-admission.canary-artifact-target.v1\0"
        + _FIRST_STAGE.encode("utf-8")
        + b"\0"
        + target_product.encode("utf-8")
    ).hexdigest()


_TARGET_DIRECTORY = _annotation_target_directory(_FIRST_PRODUCT)
_EVIDENCE_NAME = "evidence.json"
_CANDIDATE_NAME = "canary-review-candidate.json"
_MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
_MAX_METADATA_BYTES = 128 * 1024
_ARTIFACT_FILES: Final[dict[str, str]] = {
    "checkpoint": "checkpoint.bin",
    "manifest": "manifest.json",
    "golden": "golden.json",
    "quote_verification": "quote-verification.json",
    "disputed_quality": "disputed-quality.json",
}


class CanaryArtifactStoreError(ValueError):
    """A protected artifact bundle could not be committed safely."""


class CanaryReviewCandidateError(ValueError):
    """Current ledger/artifact evidence cannot form a review candidate."""


@dataclass(frozen=True, slots=True)
class CanaryArtifactBundle:
    """Exact bytes and typed quality metadata for one annotation target."""

    checkpoint: bytes
    manifest: bytes
    golden: bytes
    quote_verification: bytes
    disputed_quality: bytes
    disputed_count: int
    record_count: int
    quality_threshold_version: str

    def __post_init__(self) -> None:
        for label in _ARTIFACT_FILES:
            value = getattr(self, label)
            if not isinstance(value, bytes) or not value:
                raise ValueError(f"{label} artifact must be non-empty bytes")
            if len(value) > _MAX_ARTIFACT_BYTES:
                raise ValueError(f"{label} artifact exceeds the size limit")
        if type(self.disputed_count) is not int or self.disputed_count < 0:
            raise ValueError("disputed_count must be a non-negative integer")
        if type(self.record_count) is not int or self.record_count < 1:
            raise ValueError("record_count must be a positive integer")
        if self.disputed_count > self.record_count:
            raise ValueError("disputed_count must not exceed record_count")
        if (
            not isinstance(self.quality_threshold_version, str)
            or not self.quality_threshold_version.strip()
        ):
            raise ValueError("quality_threshold_version must be non-blank")


class CanaryReviewProposal(BaseModel):
    """Machine-derived evidence proposed for a later human signing decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_payload_hash: str
    run_identity: str
    purpose: str
    scope: str
    granted_targets: tuple[CanaryReviewTarget, ...]
    execution_plan_hash: str
    evaluated_revision: str
    runtime_capability_version: str
    canary_target: CanaryReviewTarget
    budget_account_identity: str
    budget_revision: int
    budget_approval_digest: str
    settlement_snapshot_digest: str
    artifacts: CanaryReviewArtifactEvidence
    provider_usage: CanaryReviewUsageEvidence


class CanaryReviewCandidate(BaseModel):
    """Explicitly unsigned, non-authoritative canonical proposal wrapper."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["canary-review-candidate"] = "canary-review-candidate"
    status: Literal["unsigned"] = "unsigned"
    authority: Literal[False] = False
    proposed_payload: CanaryReviewProposal


class _ArtifactEvidenceIndex(BaseModel):
    """Commit marker binding one evidence set to its plan and fixed target."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_plan_hash: str
    target_stage: Literal["annotation"]
    target_product_id: Literal[
        "平安爱满分（2026）两全保险",
        "平安附加（2026）意外伤害保险",
    ]
    evidence: CanaryReviewArtifactEvidence


def production_canary_run_root() -> Path:
    """Return the deployment-owned root shared with the run entrypoint."""

    return _PRODUCTION_RUN_ROOT


def _require_digest(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _evidence(bundle: CanaryArtifactBundle) -> CanaryReviewArtifactEvidence:
    return CanaryReviewArtifactEvidence(
        checkpoint_digest=_sha256(bundle.checkpoint),
        manifest_digest=_sha256(bundle.manifest),
        golden_digest=_sha256(bundle.golden),
        quote_verification_digest=_sha256(bundle.quote_verification),
        disputed_quality_digest=_sha256(bundle.disputed_quality),
        disputed_count=bundle.disputed_count,
        record_count=bundle.record_count,
        quality_threshold_version=bundle.quality_threshold_version,
    )


_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600
_DIRECTORY_OPEN_FLAGS = (
    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
)
_READ_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_LOCK_NAME = ".canary-bundle.commit.lock"


def _close_quietly(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


def _open_at(
    path: str | Path,
    flags: int,
    *,
    mode: int = 0o777,
    dir_fd: int | None = None,
    message: str,
) -> int:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, mode, dir_fd=dir_fd)
    except OSError:
        pass
    if descriptor is None:
        raise CanaryArtifactStoreError(message)
    return descriptor


def _metadata(descriptor: int, *, message: str) -> os.stat_result:
    result: os.stat_result | None = None
    try:
        result = os.fstat(descriptor)
    except OSError:
        pass
    if result is None:
        raise CanaryArtifactStoreError(message)
    return result


def _require_private_directory_fd(descriptor: int, *, final_root: bool = True) -> None:
    metadata = _metadata(descriptor, message="protected artifact directory is unsafe")
    mode = stat.S_IMODE(metadata.st_mode)
    effective_uid = os.geteuid()
    if not stat.S_ISDIR(metadata.st_mode):
        raise CanaryArtifactStoreError("protected artifact directory is unsafe")
    if final_root:
        if metadata.st_uid != effective_uid or mode != _PRIVATE_DIRECTORY_MODE:
            raise CanaryArtifactStoreError(
                "protected artifact directory has unsafe ownership or mode"
            )
        return
    if metadata.st_uid not in {0, effective_uid}:
        raise CanaryArtifactStoreError(
            "protected artifact directory has unsafe ownership or mode"
        )
    if mode & (stat.S_IWGRP | stat.S_IWOTH) and not mode & stat.S_ISVTX:
        raise CanaryArtifactStoreError(
            "protected artifact directory has unsafe ownership or mode"
        )


def _require_private_file_fd(descriptor: int, *, message: str) -> os.stat_result:
    metadata = _metadata(descriptor, message=message)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE
    ):
        raise CanaryArtifactStoreError(message)
    return metadata


def _open_verified_root(path: Path) -> int:
    absolute = Path(os.path.abspath(path))
    if not absolute.is_absolute():
        raise CanaryArtifactStoreError("protected artifact root must be absolute")
    current = _open_at(
        absolute.anchor,
        _DIRECTORY_OPEN_FLAGS,
        message="protected artifact directory is missing or unsafe",
    )
    try:
        parts = absolute.parts[1:]
        _require_private_directory_fd(current, final_root=not parts)
        for index, part in enumerate(parts):
            child = _open_at(
                part,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=current,
                message="protected artifact directory is missing or unsafe",
            )
            try:
                _require_private_directory_fd(
                    child,
                    final_root=index == len(parts) - 1,
                )
            except BaseException:
                _close_quietly(child)
                raise
            _close_quietly(current)
            current = child
        result = current
        current = -1
        return result
    finally:
        if current >= 0:
            _close_quietly(current)


def _open_or_create_private_directory(
    parent_fd: int,
    name: str,
    *,
    create: bool,
) -> int:
    failed = False
    if create:
        try:
            os.mkdir(name, _PRIVATE_DIRECTORY_MODE, dir_fd=parent_fd)
        except FileExistsError:
            pass
        except OSError:
            failed = True
        if failed:
            raise CanaryArtifactStoreError("protected artifact directory cannot be created")
        # A previous attempt may have created the child but failed to persist the
        # parent directory entry.  Re-sync the parent on every create-capable open,
        # including FileExists recovery, before descending into the child.
        sync_failed = False
        try:
            os.fsync(parent_fd)
        except OSError:
            sync_failed = True
        if sync_failed:
            raise CanaryArtifactStoreError("protected artifact directory is not durable")
    descriptor = _open_at(
        name,
        _DIRECTORY_OPEN_FLAGS,
        dir_fd=parent_fd,
        message="protected artifact directory is missing or unsafe",
    )
    try:
        _require_private_directory_fd(descriptor)
    except BaseException:
        _close_quietly(descriptor)
        raise
    return descriptor


def _open_optional_private_directory(parent_fd: int, name: str) -> int | None:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            _DIRECTORY_OPEN_FLAGS,
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        return None
    except OSError:
        pass
    if descriptor is None:
        raise CanaryArtifactStoreError(
            "protected artifact directory is missing or unsafe"
        )
    try:
        _require_private_directory_fd(descriptor)
    except BaseException:
        _close_quietly(descriptor)
        raise
    return descriptor


def _open_commit_lock(plan_fd: int) -> int:
    created = False
    descriptor: int | None = None
    create_flags = (
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        descriptor = os.open(
            _LOCK_NAME,
            create_flags,
            _PRIVATE_FILE_MODE,
            dir_fd=plan_fd,
        )
        created = True
    except FileExistsError:
        pass
    except OSError:
        pass
    if descriptor is None and not created:
        descriptor = _open_at(
            _LOCK_NAME,
            os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=plan_fd,
            message="canary bundle commit lock is unsafe",
        )
    if descriptor is None:  # Defensive: both open paths above failed closed.
        raise CanaryArtifactStoreError("canary bundle commit lock is unsafe")
    try:
        _require_private_file_fd(
            descriptor,
            message="canary bundle commit lock is unsafe",
        )
        if created:
            sync_failed = False
            try:
                os.fsync(plan_fd)
            except OSError:
                sync_failed = True
            if sync_failed:
                raise CanaryArtifactStoreError("canary bundle commit lock is not durable")
    except BaseException:
        _close_quietly(descriptor)
        raise
    return descriptor


def _flock(descriptor: int, operation: int) -> None:
    failed = False
    try:
        fcntl.flock(descriptor, operation)
    except OSError:
        failed = True
    if failed:
        raise CanaryArtifactStoreError("canary bundle commit lock failed")


@contextmanager
def _locked_plan_directory(
    root: Path,
    plan_hash: str,
    *,
    create: bool,
    exclusive: bool,
) -> Iterator[int]:
    root_fd = _open_verified_root(root)
    plan_fd = -1
    lock_fd = -1
    acquired = False
    try:
        plan_fd = _open_or_create_private_directory(root_fd, plan_hash, create=create)
        lock_fd = _open_commit_lock(plan_fd)
        _flock(lock_fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        acquired = True
        yield plan_fd
    finally:
        if acquired:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
        if lock_fd >= 0:
            _close_quietly(lock_fd)
        if plan_fd >= 0:
            _close_quietly(plan_fd)
        _close_quietly(root_fd)


@contextmanager
def _locked_bundle_directory(
    root: Path,
    plan_hash: str,
    *,
    create: bool,
    exclusive: bool,
    target_directory: str = _TARGET_DIRECTORY,
) -> Iterator[int]:
    target_fd = -1
    with _locked_plan_directory(
        root,
        plan_hash,
        create=create,
        exclusive=exclusive,
    ) as plan_fd:
        try:
            target_fd = _open_or_create_private_directory(
                plan_fd,
                target_directory,
                create=create,
            )
            yield target_fd
        finally:
            if target_fd >= 0:
                _close_quietly(target_fd)


def _list_names(directory_fd: int) -> set[str]:
    names: list[str] | None = None
    try:
        names = os.listdir(directory_fd)
    except OSError:
        pass
    if names is None or any(not isinstance(name, str) for name in names):
        raise CanaryArtifactStoreError("canary artifact bundle cannot be listed safely")
    return set(names)


def _read_private_file_at(directory_fd: int, name: str, *, maximum: int) -> bytes:
    descriptor = _open_at(
        name,
        _READ_OPEN_FLAGS,
        dir_fd=directory_fd,
        message="canary artifact is missing or unsafe",
    )
    try:
        metadata = _require_private_file_fd(
            descriptor,
            message="canary artifact is missing or unsafe",
        )
        if metadata.st_size > maximum:
            raise CanaryArtifactStoreError("canary artifact exceeds the size limit")
        chunks: list[bytes] = []
        total = 0
        read_failed = False
        while not read_failed:
            try:
                chunk = os.read(
                    descriptor,
                    min(1024 * 1024, maximum + 1 - total),
                )
            except OSError:
                read_failed = True
                continue
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise CanaryArtifactStoreError("canary artifact exceeds the size limit")
            chunks.append(chunk)
        if read_failed:
            raise CanaryArtifactStoreError("canary artifact cannot be read safely")
        return b"".join(chunks)
    finally:
        _close_quietly(descriptor)


def _atomic_private_write_at(directory_fd: int, name: str, content: bytes) -> None:
    temporary = f".{name}.{secrets.token_hex(12)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = _open_at(
        temporary,
        flags,
        mode=_PRIVATE_FILE_MODE,
        dir_fd=directory_fd,
        message="atomic artifact staging file cannot be created safely",
    )
    staged = True
    failure = False
    try:
        try:
            _require_private_file_fd(
                descriptor,
                message="atomic artifact staging file is unsafe",
            )
            os.fchmod(descriptor, _PRIVATE_FILE_MODE)
            _require_private_file_fd(
                descriptor,
                message="atomic artifact staging file is unsafe",
            )
            view = memoryview(content)
            written = 0
            while written < len(view):
                count = os.write(descriptor, view[written:])
                if count <= 0:
                    failure = True
                    break
                written += count
            if not failure:
                os.fsync(descriptor)
        except OSError:
            failure = True
    finally:
        _close_quietly(descriptor)
    if not failure:
        try:
            os.replace(
                temporary,
                name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            staged = False
            os.fsync(directory_fd)
        except OSError:
            failure = True
    if staged:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except OSError:
            pass
    if failure:
        raise CanaryArtifactStoreError("atomic artifact write failed")


def _inspection_failure(message: str) -> ArtifactEvidenceInspectionError:
    return ArtifactEvidenceInspectionError(message)


class CanaryArtifactStore(ArtifactEvidenceInspector):
    """Code-rooted content-addressed storage for fixed annotation targets."""

    def __init__(self) -> None:
        self._initialize(_PRODUCTION_RUN_ROOT)

    @classmethod
    def _for_testing(cls, *, run_root: Path) -> Self:
        instance = cls.__new__(cls)
        instance._initialize(run_root)
        return instance

    def _initialize(self, run_root: Path) -> None:
        self._run_root = Path(run_root)
        descriptor = _open_verified_root(self._run_root)
        _close_quietly(descriptor)

    def bundle_path(self, execution_plan_hash: str) -> Path:
        _require_digest(execution_plan_hash, "execution_plan_hash")
        return self._run_root / execution_plan_hash / _TARGET_DIRECTORY

    def artifact_path(self, execution_plan_hash: str, name: str) -> Path:
        filename = _ARTIFACT_FILES.get(name)
        if filename is None:
            raise ValueError("unknown canary artifact name")
        return self.bundle_path(execution_plan_hash) / filename

    def write_first_canary(
        self,
        *,
        execution_plan_hash: str,
        bundle: object,
    ) -> CanaryReviewArtifactEvidence:
        return self.write_annotation_bundle(
            execution_plan_hash=execution_plan_hash,
            product_id=_FIRST_PRODUCT,
            bundle=bundle,
        )

    def write_annotation_bundle(
        self,
        *,
        execution_plan_hash: str,
        product_id: str,
        bundle: object,
    ) -> CanaryReviewArtifactEvidence:
        """Durably commit one exact bundle for either code-fixed annotation target."""

        target_product = _annotation_product(product_id)
        target_directory = _annotation_target_directory(target_product)
        if not isinstance(bundle, CanaryArtifactBundle):
            raise TypeError("annotation artifact bundle must be typed")
        _require_digest(execution_plan_hash, "execution_plan_hash")
        expected = _evidence(bundle)
        values = {
            "checkpoint": bundle.checkpoint,
            "manifest": bundle.manifest,
            "golden": bundle.golden,
            "quote_verification": bundle.quote_verification,
            "disputed_quality": bundle.disputed_quality,
        }
        try:
            with _locked_bundle_directory(
                self._run_root,
                execution_plan_hash,
                create=True,
                exclusive=True,
                target_directory=target_directory,
            ) as directory_fd:
                names = _list_names(directory_fd)
                if names:
                    observed = self._inspect_target_fd(
                        directory_fd,
                        execution_plan_hash=execution_plan_hash,
                        expected_product_id=target_product,
                    )
                    exact = all(
                        _read_private_file_at(
                            directory_fd,
                            _ARTIFACT_FILES[name],
                            maximum=_MAX_ARTIFACT_BYTES,
                        )
                        == content
                        for name, content in values.items()
                    )
                    if observed != expected or not exact:
                        raise CanaryArtifactStoreError(
                            "existing canary artifact bundle contains different evidence"
                        )
                    return observed

                for name, content in values.items():
                    _atomic_private_write_at(
                        directory_fd,
                        _ARTIFACT_FILES[name],
                        content,
                    )
                index = _ArtifactEvidenceIndex(
                    execution_plan_hash=execution_plan_hash,
                    target_stage=_FIRST_STAGE,
                    target_product_id=target_product,
                    evidence=expected,
                )
                _atomic_private_write_at(
                    directory_fd,
                    _EVIDENCE_NAME,
                    canonical_json_bytes(index),
                )
                return self._inspect_target_fd(
                    directory_fd,
                    execution_plan_hash=execution_plan_hash,
                    expected_product_id=target_product,
                )
        except ArtifactEvidenceInspectionError:
            inspection_failed = True
        else:  # pragma: no cover - every successful branch returns above
            inspection_failed = False
        if inspection_failed:
            raise CanaryArtifactStoreError(
                "existing canary artifact bundle is ambiguous or incomplete"
            )
        raise CanaryArtifactStoreError("canary artifact bundle write failed")

    def inspect(
        self,
        *,
        execution_plan_hash: str,
        canary_target: ExecutionTarget,
    ) -> CanaryReviewArtifactEvidence:
        if (canary_target.stage, canary_target.product_id) != (
            _FIRST_STAGE,
            _FIRST_PRODUCT,
        ):
            raise ArtifactEvidenceInspectionError(
                "artifact evidence target is not the code-fixed first canary"
            )
        _require_digest(execution_plan_hash, "execution_plan_hash")
        result: CanaryReviewArtifactEvidence | None = None
        storage_failed = False
        try:
            with _locked_bundle_directory(
                self._run_root,
                execution_plan_hash,
                create=False,
                exclusive=False,
            ) as directory_fd:
                result = self._inspect_target_fd(
                    directory_fd,
                    execution_plan_hash=execution_plan_hash,
                )
        except CanaryArtifactStoreError:
            storage_failed = True
        if storage_failed or result is None:
            raise _inspection_failure("canary artifact bundle is missing or unsafe")
        return result

    def inspect_optional(
        self,
        *,
        execution_plan_hash: str,
        canary_target: ExecutionTarget,
    ) -> CanaryReviewArtifactEvidence | None:
        """Return exact evidence, or ``None`` only for a locked absent target."""

        if canary_target.stage != _FIRST_STAGE or canary_target.product_id not in {
            _FIRST_PRODUCT,
            _SECOND_PRODUCT,
        }:
            raise ArtifactEvidenceInspectionError(
                "artifact evidence target is not a code-fixed canary"
            )
        target_product = _annotation_product(canary_target.product_id)
        target_directory = _annotation_target_directory(target_product)
        _require_digest(execution_plan_hash, "execution_plan_hash")
        result: CanaryReviewArtifactEvidence | None = None
        target_absent = False
        storage_failed = False
        try:
            with _locked_plan_directory(
                self._run_root,
                execution_plan_hash,
                create=True,
                exclusive=False,
            ) as plan_fd:
                target_fd = _open_optional_private_directory(
                    plan_fd,
                    target_directory,
                )
                if target_fd is None:
                    target_absent = True
                else:
                    try:
                        result = self._inspect_target_fd(
                            target_fd,
                            execution_plan_hash=execution_plan_hash,
                            expected_product_id=target_product,
                        )
                    finally:
                        _close_quietly(target_fd)
        except CanaryArtifactStoreError:
            storage_failed = True
        if storage_failed:
            raise _inspection_failure("canary artifact bundle is missing or unsafe")
        if target_absent:
            return None
        if result is None:  # pragma: no cover - every safe branch resolves above
            raise _inspection_failure("canary artifact bundle is missing or unsafe")
        return result

    @staticmethod
    def _inspect_target_fd(
        directory_fd: int,
        *,
        execution_plan_hash: str,
        expected_product_id: str = _FIRST_PRODUCT,
    ) -> CanaryReviewArtifactEvidence:
        allowed = {
            *_ARTIFACT_FILES.values(),
            _EVIDENCE_NAME,
            _CANDIDATE_NAME,
        }
        observed_names: set[str] | None = None
        try:
            observed_names = _list_names(directory_fd)
        except CanaryArtifactStoreError:
            pass
        if observed_names is None:
            raise _inspection_failure("canary artifact bundle is unsafe")
        if not observed_names.issubset(allowed):
            raise ArtifactEvidenceInspectionError("canary artifact bundle is ambiguous")
        required = {*_ARTIFACT_FILES.values(), _EVIDENCE_NAME}
        if not required.issubset(observed_names):
            raise ArtifactEvidenceInspectionError("canary artifact bundle is missing")
        invalid_entry = False
        try:
            for name in observed_names:
                descriptor = _open_at(
                    name,
                    _READ_OPEN_FLAGS,
                    dir_fd=directory_fd,
                    message="canary artifact bundle is unsafe",
                )
                try:
                    _require_private_file_fd(
                        descriptor,
                        message="canary artifact bundle is unsafe",
                    )
                finally:
                    _close_quietly(descriptor)
            index = _ArtifactEvidenceIndex.model_validate_json(
                _read_private_file_at(
                    directory_fd,
                    _EVIDENCE_NAME,
                    maximum=_MAX_METADATA_BYTES,
                )
            )
        except CanaryArtifactStoreError:
            invalid_entry = True
            index = None
        except ValueError:
            index = None
        if invalid_entry:
            raise _inspection_failure("canary artifact bundle is unsafe")
        if index is None:
            raise _inspection_failure("canary evidence index is invalid")
        if (
            index.execution_plan_hash != execution_plan_hash
            or index.target_stage != _FIRST_STAGE
            or index.target_product_id != expected_product_id
        ):
            raise ArtifactEvidenceInspectionError("canary evidence index identity drifted")
        evidence = index.evidence

        digests = {
            "checkpoint": evidence.checkpoint_digest,
            "manifest": evidence.manifest_digest,
            "golden": evidence.golden_digest,
            "quote_verification": evidence.quote_verification_digest,
            "disputed_quality": evidence.disputed_quality_digest,
        }
        for name, expected_digest in digests.items():
            read_failed = False
            try:
                content = _read_private_file_at(
                    directory_fd,
                    _ARTIFACT_FILES[name],
                    maximum=_MAX_ARTIFACT_BYTES,
                )
            except CanaryArtifactStoreError:
                read_failed = True
                content = b""
            if read_failed:
                raise _inspection_failure(f"{name} artifact is missing or unsafe")
            if _sha256(content) != expected_digest:
                raise ArtifactEvidenceInspectionError(f"{name} artifact drifted")
        return evidence

    def write_candidate(self, candidate: CanaryReviewCandidate) -> Path:
        if not isinstance(candidate, CanaryReviewCandidate):
            raise TypeError("canary review candidate must be typed")
        plan_hash = candidate.proposed_payload.execution_plan_hash
        _require_digest(plan_hash, "execution_plan_hash")
        path = self.bundle_path(plan_hash) / _CANDIDATE_NAME
        content = canonical_json_bytes(candidate)
        try:
            with _locked_bundle_directory(
                self._run_root,
                plan_hash,
                create=False,
                exclusive=True,
            ) as directory_fd:
                observed = self._inspect_target_fd(
                    directory_fd,
                    execution_plan_hash=plan_hash,
                )
                if observed != candidate.proposed_payload.artifacts:
                    raise CanaryArtifactStoreError(
                        "canary candidate artifact evidence drifted since build"
                    )
                names = _list_names(directory_fd)
                if _CANDIDATE_NAME in names:
                    existing = _read_private_file_at(
                        directory_fd,
                        _CANDIDATE_NAME,
                        maximum=_MAX_METADATA_BYTES,
                    )
                    if existing == content:
                        return path
                    raise CanaryArtifactStoreError(
                        "existing canary candidate contains different evidence"
                    )
                _atomic_private_write_at(directory_fd, _CANDIDATE_NAME, content)
                return path
        except ArtifactEvidenceInspectionError:
            inspection_failed = True
        else:  # pragma: no cover - every successful branch returns above
            inspection_failed = False
        if inspection_failed:
            raise CanaryArtifactStoreError("existing canary candidate is unsafe")
        raise CanaryArtifactStoreError("canary candidate write failed")


def _amounts_fit(
    actual_input: int,
    actual_output: int,
    actual_cost: int,
    attempt: ProductSettlementAttempt,
) -> bool:
    return (
        actual_input <= attempt.maximum.input_tokens
        and actual_output <= attempt.maximum.output_tokens
        and actual_cost <= attempt.maximum.cost_minor_units
    )


def _verified_usage(
    snapshot: ProductSettlementSnapshot,
    document: RunAdmissionDocument,
) -> CanaryReviewUsageEvidence:
    contract = document.budget_contract
    if contract is None:
        raise CanaryReviewCandidateError("candidate requires a signed budget contract")
    rate = contract.role_rates["annotator"]
    if snapshot.reservation_state != "settled" or not snapshot.attempts:
        raise CanaryReviewCandidateError("canary settlement is not complete")
    input_tokens = 0
    output_tokens = 0
    cost_minor_units = 0
    for attempt in snapshot.attempts:
        actual = attempt.actual
        if (
            attempt.role != "annotator"
            or attempt.state != "terminal"
            or not attempt.usage_verified
            or attempt.response_digest is None
            or attempt.no_usage_proof is not None
            or not _amounts_fit(
                actual.input_tokens,
                actual.output_tokens,
                actual.cost_minor_units,
                attempt,
            )
        ):
            raise CanaryReviewCandidateError(
                "canary usage must be terminal and provider verified"
            )
        expected_cost = role_rate_cost(
            rate,
            input_tokens=actual.input_tokens,
            output_tokens=actual.output_tokens,
        )
        if actual.cost_minor_units != expected_cost:
            raise CanaryReviewCandidateError(
                "canary usage cost does not match the signed RoleRate"
            )
        input_tokens += actual.input_tokens
        output_tokens += actual.output_tokens
        cost_minor_units += actual.cost_minor_units
    if (
        input_tokens != snapshot.reservation_actual.input_tokens
        or output_tokens != snapshot.reservation_actual.output_tokens
        or cost_minor_units != snapshot.reservation_actual.cost_minor_units
    ):
        raise CanaryReviewCandidateError("canary usage does not match settlement actuals")
    return CanaryReviewUsageEvidence(
        role="annotator",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_minor_units=cost_minor_units,
        role_rate_digest=role_rate_digest(rate),
    )


def build_canary_review_candidate(
    *,
    document: RunAdmissionDocument,
    admission: RuntimeAdmissionDecision,
    ledger: BudgetLedger,
    artifact_inspector: ArtifactEvidenceInspector,
) -> CanaryReviewCandidate:
    """Derive a non-authoritative proposal under one locked ledger snapshot."""

    authorization = admission.authorization
    account = admission.account
    if (
        admission.result.state != "READY"
        or not isinstance(authorization, InitialExecutionAuthorization)
        or account is None
    ):
        raise CanaryReviewCandidateError(
            "candidate requires fresh initial-canary admission authority"
        )
    plan_hash = execution_plan_hash(document)
    if authorization.execution_plan_hash != plan_hash:
        raise CanaryReviewCandidateError("candidate admission plan drifted")

    evidence_failed = False
    try:
        with ledger.locked_product_settlement_snapshot(
            account.account_id,
            _FIRST_STAGE,
            _FIRST_PRODUCT,
        ) as snapshot:
            if (
                snapshot.account_id != authorization.account_id
                or snapshot.budget_revision != authorization.account_revision
                or snapshot.approval_digest != authorization.account_approval_digest
            ):
                raise CanaryReviewCandidateError("candidate budget snapshot drifted")
            usage = _verified_usage(snapshot, document)
            artifacts = artifact_inspector.inspect(
                execution_plan_hash=plan_hash,
                canary_target=ExecutionTarget(
                    stage=_FIRST_STAGE,
                    product_id=_FIRST_PRODUCT,
                ),
            )
            settlement_digest = ledger.product_settlement_snapshot_digest(snapshot)
    except CanaryReviewCandidateError:
        raise
    except (BudgetLedgerError, ArtifactEvidenceInspectionError):
        evidence_failed = True
    if evidence_failed:
        raise CanaryReviewCandidateError(
            "candidate ledger or artifact evidence is unavailable"
        )

    proposal: CanaryReviewProposal | None = None
    try:
        proposal = CanaryReviewProposal(
            plan_payload_hash=plan_payload_hash(document.plan),
            run_identity=document.plan.payload.run_identity,
            purpose=document.plan.payload.purpose,
            scope=_CANARY_REVIEW_SCOPE,
            granted_targets=(
                CanaryReviewTarget(stage=_SECOND_STAGE, product_id=_SECOND_PRODUCT),
            ),
            execution_plan_hash=plan_hash,
            evaluated_revision=admission.result.evaluated_revision,
            runtime_capability_version=admission.result.runtime_capability_version,
            canary_target=CanaryReviewTarget(
                stage=_FIRST_STAGE,
                product_id=_FIRST_PRODUCT,
            ),
            budget_account_identity=snapshot.account_id,
            budget_revision=snapshot.budget_revision,
            budget_approval_digest=snapshot.approval_digest,
            settlement_snapshot_digest=settlement_digest,
            artifacts=artifacts,
            provider_usage=usage,
        )
    except ValueError:
        pass
    if proposal is None:
        raise CanaryReviewCandidateError("candidate payload is invalid")
    return CanaryReviewCandidate(proposed_payload=proposal)


__all__ = [
    "CanaryArtifactBundle",
    "CanaryArtifactStore",
    "CanaryArtifactStoreError",
    "CanaryReviewCandidate",
    "CanaryReviewCandidateError",
    "CanaryReviewProposal",
    "build_canary_review_candidate",
    "production_canary_run_root",
]
