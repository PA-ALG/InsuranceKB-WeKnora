"""Production run-session lock for the OpenSpec 020 execution boundary."""

from __future__ import annotations

import argparse
import asyncio
import errno
import fcntl
import hashlib
import json
import os
import sqlite3
import stat
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager, closing
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version as installed_package_version
from pathlib import Path, PurePosixPath
from typing import Never, Protocol, Self

from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import ValidationError

from insurance_harness.compiler.judge import JudgeDispatcher
from insurance_harness.compiler.models import BaselineAdmissionIdentity, RunManifest
from insurance_harness.compiler.pipeline import (
    ExtractionPipeline,
    PipelineConfig,
    RunArtifactCommitCandidate,
    RunResult,
    run_settlement_guard,
)
from insurance_harness.compiler.templates import (
    load_template_registry,
    select_table_provider,
)
from insurance_harness.goldenset.admission import (
    AdmissionBlocker,
    ArtifactEvidenceInspectionError,
    ExecutionTarget,
    InitialExecutionAuthorization,
    ProductionAdmissionEvaluator,
    RunAdmissionDocument,
    RuntimeAdmissionDecision,
    execution_plan_hash,
)
from insurance_harness.goldenset.admission_artifacts import (
    CanaryArtifactBundle,
    CanaryArtifactStore,
    CanaryArtifactStoreError,
    CanaryReviewCandidate,
    CanaryReviewCandidateError,
    build_canary_review_candidate,
)
from insurance_harness.goldenset.admission_budget import (
    BudgetLedger,
    BudgetLedgerError,
    budget_account_identity,
)
from insurance_harness.goldenset.admission_cli import (
    _load_deployment_approval_configuration,
    _load_deployment_canary_review_approval,
    _safe_load_unique,
)
from insurance_harness.goldenset.admission_models import (
    ModelRolePlan,
    ProductInputPlan,
)
from insurance_harness.goldenset.admission_runtime import (
    AdmissionBlockedError,
    AdmissionPausedError,
    AdmissionRuntimeGuard,
    AdmittedModelClient,
)
from insurance_harness.goldenset.annotator import GoldenAnnotator
from insurance_harness.goldenset.execution_artifacts_020 import (
    directory_parser_fingerprint,
    render_annotation_artifacts,
    validate_annotation_bundle,
    validate_baseline_commit_candidate,
    validate_baseline_result,
)
from insurance_harness.goldenset.pdf import PageText, extract_pages_bytes
from insurance_harness.goldenset.runner import annotate_product
from insurance_harness.schemas import load_schema_registry
from insurance_harness.sources.directory import (
    DirectoryDocumentSource,
    DirectorySourceRequest,
)

_PRODUCTION_SESSION_ROOT = Path("/var/lib/insurancekb/run-admission/sessions")
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600
_LOWER_HEX = frozenset("0123456789abcdef")
_STATE_ROOT = Path("/var/lib/insurancekb/run-admission")
_TRUST_PATH = Path("/etc/insurancekb/run-admission-trust.yaml")
_FIRST_CANARY_PRODUCT_ID = "平安爱满分（2026）两全保险"
_ANNOTATION_BUSINESS_PRODUCT_IDS = {
    "平安爱满分（2026）两全保险": "1818",
    "平安附加（2026）意外伤害保险": "1814",
}
_ANNOTATION_CACHE_ROOT = "annotation-cache"
_ANNOTATION_SNAPSHOT_ROOT = "annotation-input-snapshots"
_ANNOTATION_SNAPSHOT_DOMAIN = b"insurancekb.annotation-input-snapshot.v1\0"
_BASELINE_SNAPSHOT_ROOT = "baseline-input-snapshots"
_BASELINE_SNAPSHOT_DOMAIN = b"insurancekb.baseline-input-snapshot.v1\0"
_SCHEMA_BASELINE = Path("docs/insurance-kb/schema-baseline")
_TEMPLATE_BASELINE = Path("dataset/templates")
_MAX_ANNOTATION_INPUT_BYTES = 256 * 1024 * 1024
_BASELINE_TARGET_DOMAIN = b"insurancekb.run-admission.baseline-target.v1\0"
_BASELINE_RUN_NAMES = frozenset(
    {
        ".run.lock",
        "checkpoint.sqlite3",
        "dead-letters.jsonl",
        "judge-queue.jsonl",
        "manifest.json",
        "pred.jsonl",
    }
)


@dataclass(frozen=True, slots=True)
class _ProductionConfiguration:
    repo_root: Path
    plan_path: Path
    trust_path: Path
    review_inbox: Path
    ledger_path: Path
    session_root: Path
    run_root: Path
    probe: bool


class _ReadyConfiguration(Protocol):
    @property
    def repo_root(self) -> Path: ...

    @property
    def ledger_path(self) -> Path: ...

    @property
    def run_root(self) -> Path: ...


class _SessionLockFactory(Protocol):
    def __call__(self, account_id: str) -> RunSessionLock: ...


class _LedgerFactory(Protocol):
    def __call__(self, path: Path) -> BudgetLedger: ...


class _GuardFactory(Protocol):
    def __call__(
        self,
        *,
        document: RunAdmissionDocument,
        evaluator: ProductionAdmissionEvaluator,
        ledger: BudgetLedger,
        response_root: Path,
    ) -> AdmissionRuntimeGuard: ...


class _AnnotationExecutor(Protocol):
    def __call__(
        self,
        *,
        document: RunAdmissionDocument,
        product_id: str,
        client: AdmittedModelClient,
        configuration: _ReadyConfiguration,
    ) -> Awaitable[CanaryArtifactBundle]: ...


class _BaselineExecutor(Protocol):
    def __call__(
        self,
        *,
        document: RunAdmissionDocument,
        product_id: str,
        extractor_client: AdmittedModelClient,
        judge_client: AdmittedModelClient,
        configuration: _ReadyConfiguration,
    ) -> Awaitable[RunResult]: ...


class _ArtifactCommitter(Protocol):
    def __call__(
        self,
        *,
        document: RunAdmissionDocument,
        command: str,
        product_id: str,
        execution_result: CanaryArtifactBundle | RunResult,
        configuration: _ReadyConfiguration,
    ) -> None: ...


class _CandidateBuilder(Protocol):
    def __call__(
        self,
        *,
        document: RunAdmissionDocument,
        ledger: BudgetLedger,
        execution_decision: RuntimeAdmissionDecision,
        configuration: _ReadyConfiguration,
    ) -> CanaryReviewCandidate: ...


class _CandidatePersister(Protocol):
    def __call__(
        self,
        *,
        candidate: object,
        configuration: _ReadyConfiguration,
    ) -> None: ...


class _CandidateResumer(Protocol):
    def __call__(
        self,
        *,
        product_id: str,
        document: RunAdmissionDocument,
        evaluator: ProductionAdmissionEvaluator,
        ledger: BudgetLedger,
        configuration: _ReadyConfiguration,
    ) -> bool: ...


type _BaselineSettlementGuardFactory = Callable[
    [Path], AbstractAsyncContextManager[None]
]


def _candidate_resume_disabled(
    *,
    product_id: str,
    document: RunAdmissionDocument,
    evaluator: ProductionAdmissionEvaluator,
    ledger: BudgetLedger,
    configuration: _ReadyConfiguration,
) -> bool:
    """Compatibility default for injected test dependencies without resume state."""

    del product_id, document, evaluator, ledger, configuration
    return False


@asynccontextmanager
async def _baseline_settlement_guard_disabled(_run_dir: Path) -> AsyncIterator[None]:
    """Compatibility seam for unit-injected dependencies outside production wiring."""

    yield


@dataclass(frozen=True, slots=True)
class _ReadyCommandDependencies:
    """Typed seams for one locked READY product execution."""

    session_lock_factory: _SessionLockFactory
    ledger_factory: _LedgerFactory
    guard_factory: _GuardFactory
    annotation_executor: _AnnotationExecutor
    baseline_executor: _BaselineExecutor
    artifact_committer: _ArtifactCommitter
    candidate_builder: _CandidateBuilder
    candidate_persister: _CandidatePersister
    baseline_settlement_guard: _BaselineSettlementGuardFactory = (
        _baseline_settlement_guard_disabled
    )
    candidate_resumer: _CandidateResumer = _candidate_resume_disabled


def _production_configuration() -> _ProductionConfiguration:
    repo_root = Path(__file__).resolve().parents[4]
    return _ProductionConfiguration(
        repo_root=repo_root,
        plan_path=(repo_root / "openspec/changes/020-golden-v01-baseline-run/run-admission.yaml"),
        trust_path=_TRUST_PATH,
        review_inbox=_STATE_ROOT / "canary-review-inbox",
        ledger_path=_STATE_ROOT / "budget.sqlite3",
        session_root=_PRODUCTION_SESSION_ROOT,
        run_root=_STATE_ROOT / "runs",
        probe=True,
    )


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise ValueError(message)


class _SingleUseProduct(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[str] | None,
        option_string: str | None = None,
    ) -> None:
        del option_string
        if getattr(namespace, self.dest, None) is not None:
            parser.error("--product may be supplied exactly once")
        if not isinstance(values, str) or not values:
            parser.error("--product requires one non-empty value")
        setattr(namespace, self.dest, values)


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="python -m insurance_harness.goldenset.run_020")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("annotate-canary", "baseline-product"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument(
            "--product",
            required=True,
            action=_SingleUseProduct,
            default=None,
        )
    return parser


def _load_production_document(
    configuration: _ProductionConfiguration,
) -> RunAdmissionDocument:
    raw = _safe_load_unique(configuration.plan_path.read_text(encoding="utf-8"))
    return RunAdmissionDocument.model_validate(raw)


def _build_production_evaluator(
    configuration: _ProductionConfiguration,
) -> ProductionAdmissionEvaluator:
    public_keys, budget_roles, provenance_roles, review_roles = (
        _load_deployment_approval_configuration()
    )
    return ProductionAdmissionEvaluator._for_production_canary(
        repo_root=configuration.repo_root,
        trusted_public_keys=public_keys,
        allowed_budget_roles=budget_roles,
        allowed_provenance_roles=provenance_roles,
        allowed_canary_review_roles=review_roles,
        canary_review_source=_load_deployment_canary_review_approval,
        artifact_evidence_inspector=CanaryArtifactStore(),
        probe=configuration.probe,
    )


def _contains_exact_product(document: object, product_id: str) -> bool:
    try:
        products = document.identity_request.products  # type: ignore[attr-defined]
        return any(item.product_id == product_id for item in products)
    except (AttributeError, TypeError):
        return False


def _open_budget_ledger(path: Path) -> BudgetLedger:
    return BudgetLedger(path)


def _build_runtime_guard(
    *,
    document: RunAdmissionDocument,
    evaluator: ProductionAdmissionEvaluator,
    ledger: BudgetLedger,
    response_root: Path,
) -> AdmissionRuntimeGuard:
    return AdmissionRuntimeGuard(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=response_root,
    )


class _AnnotationInputFault(Exception):
    """Internal sentinel mapped to one non-sensitive production pause code."""


class _BaselineInputFault(Exception):
    """Internal sentinel for an admitted baseline input mismatch."""


class _BaselineResumeFault(Exception):
    """Internal sentinel for an unsafe or ambiguous durable run state."""


@dataclass(frozen=True, slots=True)
class _AdmittedAnnotationInputs:
    repo_root: Path
    product_dir: Path
    schema_root: Path
    schema_version: str
    line_key: str
    annotator_model: str
    source_files: tuple[tuple[str, bytes], ...]
    schema_files: tuple[tuple[str, bytes], ...]
    shared_input_digests: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _AnnotationSnapshot:
    root: Path
    product_dir: Path
    schema_root: Path


@dataclass(frozen=True, slots=True)
class _AdmittedBaselineInputs:
    repo_root: Path
    source_root: Path
    product_dir: Path
    product_name: str
    plan_code: str
    line_key: str
    schema_version: str
    extractor_model: str
    judge_model: str
    product_files: tuple[tuple[str, bytes], ...]
    schema_files: tuple[tuple[str, bytes], ...]
    template_files: tuple[tuple[str, bytes], ...]
    verified_repo_files: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True, slots=True)
class _BaselineSnapshot:
    root: Path
    product_dir: Path
    schema_root: Path
    template_root: Path


@dataclass(frozen=True, slots=True)
class _BaselineRunIdentity:
    run_dir: Path
    checkpoint_path: Path
    run_id: str
    product_dir: Path
    product_id: str
    product_name: str
    line_key: str
    model_id: str


def _annotation_parts(value: str, *, single: bool = False) -> tuple[str, ...]:
    if not isinstance(value, str) or not value:
        raise _AnnotationInputFault
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
        or (single and len(path.parts) != 1)
    ):
        raise _AnnotationInputFault
    return path.parts


class _AnnotationInputRoot:
    """Read admitted inputs relative to a no-follow repository descriptor."""

    def __init__(self, root: Path) -> None:
        try:
            self._root_fd = os.open(
                root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            if not stat.S_ISDIR(os.fstat(self._root_fd).st_mode):
                raise _AnnotationInputFault
        except (OSError, _AnnotationInputFault) as error:
            if hasattr(self, "_root_fd"):
                os.close(self._root_fd)
            raise _AnnotationInputFault from error

    def close(self) -> None:
        os.close(self._root_fd)

    def _directory(self, parts: Sequence[str]) -> int:
        descriptor = os.dup(self._root_fd)
        try:
            for part in parts:
                next_descriptor = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = next_descriptor
            return descriptor
        except OSError as error:
            os.close(descriptor)
            raise _AnnotationInputFault from error

    def names(self, parts: Sequence[str]) -> set[str]:
        descriptor = self._directory(parts)
        try:
            return set(os.listdir(descriptor))
        except OSError as error:
            raise _AnnotationInputFault from error
        finally:
            os.close(descriptor)

    def read(self, parts: Sequence[str]) -> bytes:
        if not parts:
            raise _AnnotationInputFault
        parent = self._directory(parts[:-1])
        descriptor: int | None = None
        try:
            descriptor = os.open(
                parts[-1],
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent,
            )
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_ANNOTATION_INPUT_BYTES:
                raise _AnnotationInputFault
            chunks: list[bytes] = []
            total = 0
            while chunk := os.read(descriptor, 1024 * 1024):
                total += len(chunk)
                if total > _MAX_ANNOTATION_INPUT_BYTES:
                    raise _AnnotationInputFault
                chunks.append(chunk)
            return b"".join(chunks)
        except OSError as error:
            raise _AnnotationInputFault from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent)

    def flat_files(self, parts: Sequence[str]) -> tuple[tuple[str, bytes], ...]:
        """Read one loader directory exactly; nested/special entries fail closed."""

        descriptor = self._directory(parts)
        try:
            names = sorted(os.listdir(descriptor))
            files: list[tuple[str, bytes]] = []
            for name in names:
                _annotation_parts(name, single=True)
                metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if not stat.S_ISREG(metadata.st_mode):
                    raise _AnnotationInputFault
                files.append((name, self.read((*parts, name))))
            return tuple(files)
        except (OSError, _AnnotationInputFault) as error:
            raise _AnnotationInputFault from error
        finally:
            os.close(descriptor)


def _annotation_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_object(value: bytes) -> dict[str, object]:
    try:
        decoded = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _AnnotationInputFault from error
    if not isinstance(decoded, dict):
        raise _AnnotationInputFault
    return decoded


def _load_annotation_inputs(
    *,
    document: RunAdmissionDocument,
    product_id: str,
    configuration: _ReadyConfiguration,
) -> _AdmittedAnnotationInputs:
    """Rebuild exactly one signed ProductInputPlan from current repository bytes."""

    try:
        repo_root = configuration.repo_root
        if not isinstance(repo_root, Path) or not repo_root.is_absolute():
            raise _AnnotationInputFault
        matches = tuple(
            product
            for product in document.identity_request.products
            if product.product_id == product_id
        )
        if len(matches) != 1 or not isinstance(matches[0], ProductInputPlan):
            raise _AnnotationInputFault
        product = matches[0]
        expected_plan_code = _ANNOTATION_BUSINESS_PRODUCT_IDS.get(product_id)
        if expected_plan_code is None or not product.pdf_digests:
            raise _AnnotationInputFault

        product_parts = _annotation_parts(product_id, single=True)
        source_parts = (
            *_annotation_parts(document.identity_request.source_products_root),
            *product_parts,
        )
        golden_parts = (
            *_annotation_parts(document.identity_request.golden_products_root),
            *product_parts,
        )
        meta_parts = _annotation_parts(product.product_meta_path, single=True)
        pdf_parts = {name: _annotation_parts(name, single=True) for name in product.pdf_digests}
        consumed_parts = {
            name: _annotation_parts(name, single=True) for name in product.consumed_input_digests
        }
        if any(not name.casefold().endswith(".pdf") for name in pdf_parts):
            raise _AnnotationInputFault

        root = _AnnotationInputRoot(repo_root)
        try:
            if root.names(source_parts) != set(pdf_parts) | {product.product_meta_path}:
                raise _AnnotationInputFault
            if root.names(golden_parts) != set(consumed_parts) | {"fields.json"}:
                raise _AnnotationInputFault
            schema_files = root.flat_files(_SCHEMA_BASELINE.parts)
            if not schema_files:
                raise _AnnotationInputFault
            pdf_bytes = {
                name: root.read((*source_parts, *parts)) for name, parts in pdf_parts.items()
            }
            meta_bytes = root.read((*source_parts, *meta_parts))
            fields_bytes = root.read((*golden_parts, "fields.json"))
            consumed_bytes = {
                name: root.read((*golden_parts, *parts)) for name, parts in consumed_parts.items()
            }
        finally:
            root.close()

        if (
            {name: _annotation_digest(value) for name, value in pdf_bytes.items()}
            != product.pdf_digests
            or _annotation_digest(meta_bytes) != product.product_meta_digest
            or _annotation_digest(fields_bytes) != product.fields_digest
            or {name: _annotation_digest(value) for name, value in consumed_bytes.items()}
            != product.consumed_input_digests
        ):
            raise _AnnotationInputFault
        shared_input_digests = document.identity_request.shared_input_digests
        schema_prefix = _SCHEMA_BASELINE.parts
        observed_schema_digests = {
            PurePosixPath(*schema_prefix, name).as_posix(): _annotation_digest(value)
            for name, value in schema_files
        }
        signed_schema_digests = {
            path: digest
            for path, digest in shared_input_digests.items()
            if PurePosixPath(path).parts[: len(schema_prefix)] == schema_prefix
        }
        if signed_schema_digests != observed_schema_digests:
            raise _AnnotationInputFault

        meta = _json_object(meta_bytes)
        plan_code = meta.get("planCode")
        clause_name = meta.get("clauseName")
        if (
            not isinstance(plan_code, str)
            or plan_code != expected_plan_code
            or (
                clause_name is not None
                and (not isinstance(clause_name, str) or clause_name != product_id)
            )
        ):
            raise _AnnotationInputFault
        fields = _json_object(fields_bytes)
        if fields.get("line_key") != product.line_key:
            raise _AnnotationInputFault
        schema_version = fields.get("schema_version")
        if not isinstance(schema_version, str) or not schema_version:
            raise _AnnotationInputFault

        annotator_role = document.plan.payload.model_roles.get("annotator")
        if not isinstance(annotator_role, ModelRolePlan):
            raise _AnnotationInputFault
        return _AdmittedAnnotationInputs(
            repo_root=repo_root,
            product_dir=repo_root.joinpath(*source_parts),
            schema_root=repo_root / _SCHEMA_BASELINE,
            schema_version=schema_version,
            line_key=product.line_key,
            annotator_model=annotator_role.model_id,
            source_files=tuple(
                sorted(
                    {
                        **pdf_bytes,
                        product.product_meta_path: meta_bytes,
                    }.items()
                )
            ),
            schema_files=schema_files,
            shared_input_digests=tuple(sorted(shared_input_digests.items())),
        )
    except (AttributeError, OSError, TypeError, ValueError, _AnnotationInputFault):
        raise AdmissionPausedError("annotation_identity_mismatch") from None


def _revalidate_annotation_inputs(
    *,
    document: RunAdmissionDocument,
    product_id: str,
    client: AdmittedModelClient,
    configuration: _ReadyConfiguration,
) -> _AdmittedAnnotationInputs:
    """Rebuild one signed ProductInputPlan at the pre-model execution boundary."""

    if not isinstance(client, AdmittedModelClient):
        raise AdmissionPausedError("annotation_identity_mismatch")
    return _load_annotation_inputs(
        document=document,
        product_id=product_id,
        configuration=configuration,
    )


def _open_private_directory(path: Path) -> int:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise _AnnotationInputFault
        return descriptor
    except (OSError, _AnnotationInputFault) as error:
        if "descriptor" in locals():
            os.close(descriptor)
        raise _AnnotationInputFault from error


def _private_child(parent_fd: int, name: str) -> int:
    _annotation_parts(name, single=True)
    created = False
    try:
        os.mkdir(name, _PRIVATE_DIRECTORY_MODE, dir_fd=parent_fd)
        created = True
    except FileExistsError:
        pass
    if created:
        os.fsync(parent_fd)
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise _AnnotationInputFault
        return descriptor
    except (OSError, _AnnotationInputFault) as error:
        if "descriptor" in locals():
            os.close(descriptor)
        raise _AnnotationInputFault from error


def _read_private_file(descriptor: int) -> bytes:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or metadata.st_mode & 0o777 not in {0o400, 0o600}
        or metadata.st_size > _MAX_ANNOTATION_INPUT_BYTES
    ):
        raise _AnnotationInputFault
    chunks: list[bytes] = []
    total = 0
    while chunk := os.read(descriptor, 1024 * 1024):
        total += len(chunk)
        if total > _MAX_ANNOTATION_INPUT_BYTES:
            raise _AnnotationInputFault
        chunks.append(chunk)
    return b"".join(chunks)


def _write_all(descriptor: int, value: bytes) -> None:
    position = 0
    while position < len(value):
        written = os.write(descriptor, value[position:])
        if written <= 0:
            raise _AnnotationInputFault
        position += written


def _materialize_snapshot_file(parent_fd: int, name: str, value: bytes) -> None:
    _annotation_parts(name, single=True)
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
        except FileNotFoundError:
            descriptor = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=parent_fd,
            )
            _write_all(descriptor, value)
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o400)
            os.fsync(descriptor)
            os.fsync(parent_fd)
            return
        if _read_private_file(descriptor) != value:
            raise _AnnotationInputFault
    except (OSError, _AnnotationInputFault) as error:
        raise _AnnotationInputFault from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _annotation_snapshot_digest(inputs: _AdmittedAnnotationInputs) -> str:
    digest = hashlib.sha256(_ANNOTATION_SNAPSHOT_DOMAIN)
    digest.update(inputs.product_dir.name.encode("utf-8") + b"\0")
    for group, files in (
        ("product", inputs.source_files),
        ("schema", inputs.schema_files),
    ):
        digest.update(group.encode("utf-8") + b"\0")
        for name, value in files:
            digest.update(name.encode("utf-8") + b"\0")
            digest.update(len(value).to_bytes(8, "big"))
            digest.update(value)
    return digest.hexdigest()


def _private_annotation_snapshot(
    *,
    configuration: _ReadyConfiguration,
    inputs: _AdmittedAnnotationInputs,
    plan_hash: str,
) -> _AnnotationSnapshot:
    """Materialize immutable product/schema bytes in one content-addressed tree."""

    try:
        run_root = configuration.run_root
        if (
            not isinstance(run_root, Path)
            or not run_root.is_absolute()
            or run_root.resolve().is_relative_to(inputs.repo_root.resolve())
        ):
            raise _AnnotationInputFault
        snapshot_digest = _annotation_snapshot_digest(inputs)
        product_id = inputs.product_dir.name
        root_fd = _open_private_directory(run_root)
        snapshots_fd: int | None = None
        plan_fd: int | None = None
        content_fd: int | None = None
        product_group_fd: int | None = None
        product_fd: int | None = None
        schema_fd: int | None = None
        try:
            snapshots_fd = _private_child(root_fd, _ANNOTATION_SNAPSHOT_ROOT)
            plan_fd = _private_child(snapshots_fd, plan_hash)
            content_fd = _private_child(plan_fd, snapshot_digest)
            expected_groups = {"product", "schema"}
            if not set(os.listdir(content_fd)) <= expected_groups:
                raise _AnnotationInputFault
            product_group_fd = _private_child(content_fd, "product")
            if not set(os.listdir(product_group_fd)) <= {product_id}:
                raise _AnnotationInputFault
            product_fd = _materialize_snapshot_directory(
                product_group_fd,
                product_id,
                inputs.source_files,
            )
            if set(os.listdir(product_group_fd)) != {product_id}:
                raise _AnnotationInputFault
            schema_fd = _materialize_snapshot_directory(
                content_fd,
                "schema",
                inputs.schema_files,
            )
            if set(os.listdir(content_fd)) != expected_groups:
                raise _AnnotationInputFault
            os.fsync(content_fd)
        finally:
            for descriptor in (
                schema_fd,
                product_fd,
                product_group_fd,
                content_fd,
                plan_fd,
                snapshots_fd,
                root_fd,
            ):
                if descriptor is not None:
                    os.close(descriptor)
        root = (
            run_root
            / _ANNOTATION_SNAPSHOT_ROOT
            / plan_hash
            / snapshot_digest
        )
        return _AnnotationSnapshot(
            root=root,
            product_dir=root / "product" / product_id,
            schema_root=root / "schema",
        )
    except (OSError, RuntimeError, _AnnotationInputFault):
        raise AdmissionPausedError("annotation_snapshot_invalid") from None


def _baseline_snapshot_digest(inputs: _AdmittedBaselineInputs) -> str:
    digest = hashlib.sha256(_BASELINE_SNAPSHOT_DOMAIN)
    for group, files in (
        ("product", inputs.product_files),
        ("schema", inputs.schema_files),
        ("templates", inputs.template_files),
    ):
        digest.update(group.encode("utf-8") + b"\0")
        for name, value in files:
            digest.update(name.encode("utf-8") + b"\0")
            digest.update(len(value).to_bytes(8, "big"))
            digest.update(value)
    return digest.hexdigest()


def _materialize_snapshot_directory(
    parent_fd: int,
    name: str,
    files: tuple[tuple[str, bytes], ...],
) -> int:
    descriptor = _private_child(parent_fd, name)
    try:
        expected_names = {file_name for file_name, _value in files}
        if len(expected_names) != len(files) or not set(os.listdir(descriptor)) <= expected_names:
            raise _AnnotationInputFault
        for file_name, value in files:
            _materialize_snapshot_file(descriptor, file_name, value)
        if set(os.listdir(descriptor)) != expected_names:
            raise _AnnotationInputFault
        os.fsync(descriptor)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _private_baseline_snapshot(
    *,
    configuration: _ReadyConfiguration,
    inputs: _AdmittedBaselineInputs,
    plan_hash: str,
) -> _BaselineSnapshot:
    """Materialize content-addressed, immutable baseline inputs outside the repo."""

    try:
        snapshot_digest = _baseline_snapshot_digest(inputs)
        root_fd = _open_private_directory(configuration.run_root)
        snapshots_fd: int | None = None
        plan_fd: int | None = None
        content_fd: int | None = None
        product_fd: int | None = None
        schema_fd: int | None = None
        template_fd: int | None = None
        try:
            snapshots_fd = _private_child(root_fd, _BASELINE_SNAPSHOT_ROOT)
            plan_fd = _private_child(snapshots_fd, plan_hash)
            content_fd = _private_child(plan_fd, snapshot_digest)
            expected_groups = {"product", "schema", "templates"}
            if not set(os.listdir(content_fd)) <= expected_groups:
                raise _AnnotationInputFault
            product_fd = _materialize_snapshot_directory(
                content_fd, "product", inputs.product_files
            )
            schema_fd = _materialize_snapshot_directory(
                content_fd, "schema", inputs.schema_files
            )
            template_fd = _materialize_snapshot_directory(
                content_fd, "templates", inputs.template_files
            )
            if set(os.listdir(content_fd)) != expected_groups:
                raise _AnnotationInputFault
            os.fsync(content_fd)
        finally:
            for descriptor in (
                template_fd,
                schema_fd,
                product_fd,
                content_fd,
                plan_fd,
                snapshots_fd,
                root_fd,
            ):
                if descriptor is not None:
                    os.close(descriptor)
        root = (
            configuration.run_root
            / _BASELINE_SNAPSHOT_ROOT
            / plan_hash
            / snapshot_digest
        )
        return _BaselineSnapshot(
            root=root,
            product_dir=root / "product",
            schema_root=root / "schema",
            template_root=root / "templates",
        )
    except (OSError, RuntimeError, _AnnotationInputFault):
        raise AdmissionPausedError("baseline_snapshot_invalid") from None


def _snapshot_page_loader(
    *,
    repo_product_dir: Path,
    snapshot_product_dir: Path,
    pdf_names: frozenset[str],
) -> Callable[[str, bytes], list[PageText]]:
    def load(doc: str, verified_bytes: bytes) -> list[PageText]:
        if type(doc) is not str or type(verified_bytes) is not bytes:
            raise AdmissionPausedError("annotation_quote_verification_failed")
        if doc not in pdf_names or not verified_bytes:
            raise AdmissionPausedError("annotation_quote_verification_failed")
        descriptor: int | None = None
        try:
            repo_bytes = (repo_product_dir / doc).read_bytes()
            descriptor = os.open(
                snapshot_product_dir / doc,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            snapshot_bytes = _read_private_file(descriptor)
        except (OSError, _AnnotationInputFault):
            raise AdmissionPausedError("annotation_quote_verification_failed") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if repo_bytes != verified_bytes or snapshot_bytes != verified_bytes:
            raise AdmissionPausedError("annotation_quote_verification_failed")
        return list(extract_pages_bytes(verified_bytes, source_name=doc))

    return load


def _private_annotation_cache(
    *,
    configuration: _ReadyConfiguration,
    repo_root: Path,
    product_id: str,
    plan_hash: str,
) -> Path:
    """Create the model cache beneath the provisioned private production root."""

    try:
        run_root = configuration.run_root
        if (
            not isinstance(run_root, Path)
            or not run_root.is_absolute()
            or run_root.resolve().is_relative_to(repo_root.resolve())
        ):
            raise _AnnotationInputFault
        root_fd = _open_private_directory(run_root)
        cache_fd: int | None = None
        plan_fd: int | None = None
        product_fd: int | None = None
        try:
            cache_fd = _private_child(root_fd, _ANNOTATION_CACHE_ROOT)
            plan_fd = _private_child(cache_fd, plan_hash)
            product_fd = _private_child(plan_fd, product_id)
        finally:
            if product_fd is not None:
                os.close(product_fd)
            if plan_fd is not None:
                os.close(plan_fd)
            if cache_fd is not None:
                os.close(cache_fd)
            os.close(root_fd)
        return run_root / _ANNOTATION_CACHE_ROOT / plan_hash
    except (OSError, RuntimeError, _AnnotationInputFault):
        raise AdmissionPausedError("annotation_cache_invalid") from None


async def _execute_annotation(
    *,
    document: RunAdmissionDocument,
    product_id: str,
    client: AdmittedModelClient,
    configuration: _ReadyConfiguration,
) -> CanaryArtifactBundle:
    inputs = _revalidate_annotation_inputs(
        document=document,
        product_id=product_id,
        client=client,
        configuration=configuration,
    )
    plan_hash = execution_plan_hash(document)
    snapshot = _private_annotation_snapshot(
        configuration=configuration,
        inputs=inputs,
        plan_hash=plan_hash,
    )
    cache_dir = _private_annotation_cache(
        configuration=configuration,
        repo_root=inputs.repo_root,
        product_id=product_id,
        plan_hash=plan_hash,
    )
    registry = load_schema_registry(snapshot.schema_root)
    if registry.version != inputs.schema_version:
        raise AdmissionPausedError("annotation_identity_mismatch")
    annotator = GoldenAnnotator(client, registry, inputs.annotator_model)
    started_at = datetime.now(UTC)
    records = await annotate_product(
        snapshot.product_dir,
        registry,
        annotator,
        cache_dir,
        line_key=inputs.line_key,
    )
    finished_at = datetime.now(UTC)
    bundle = render_annotation_artifacts(
        document=document,
        configuration=configuration,
        product_id=product_id,
        records=records,
        cache_dir=cache_dir,
        page_loader=_snapshot_page_loader(
            repo_product_dir=inputs.product_dir,
            snapshot_product_dir=snapshot.product_dir,
            pdf_names=frozenset(
                name for name, _value in inputs.source_files if name.casefold().endswith(".pdf")
            ),
        ),
        started_at=started_at,
        finished_at=finished_at,
        execution_plan_hash=plan_hash,
    )
    if (
        _revalidate_annotation_inputs(
            document=document,
            product_id=product_id,
            client=client,
            configuration=configuration,
        )
        != inputs
    ):
        raise AdmissionPausedError("annotation_identity_mismatch")
    return bundle


def _revalidate_baseline_inputs(
    *,
    document: RunAdmissionDocument,
    product_id: str,
    extractor_client: AdmittedModelClient,
    judge_client: AdmittedModelClient,
    configuration: _ReadyConfiguration,
) -> _AdmittedBaselineInputs:
    """Rebuild one signed baseline product identity before parser or model I/O."""

    try:
        if not isinstance(extractor_client, AdmittedModelClient) or not isinstance(
            judge_client, AdmittedModelClient
        ):
            raise _BaselineInputFault
        repo_root = configuration.repo_root
        run_root = configuration.run_root
        if (
            not isinstance(repo_root, Path)
            or not repo_root.is_absolute()
            or not isinstance(run_root, Path)
            or not run_root.is_absolute()
            or run_root.resolve().is_relative_to(repo_root.resolve())
        ):
            raise _BaselineInputFault

        matching_products = tuple(
            product
            for product in document.identity_request.products
            if product.product_id == product_id
        )
        if len(matching_products) != 1 or type(matching_products[0]) is not ProductInputPlan:
            raise _BaselineInputFault
        product = matching_products[0]
        if not product.pdf_digests:
            raise _BaselineInputFault

        extractor_role = document.plan.payload.model_roles.get("weak_extractor")
        judge_role = document.plan.payload.model_roles.get("judge")
        if not isinstance(extractor_role, ModelRolePlan) or not isinstance(
            judge_role, ModelRolePlan
        ):
            raise _BaselineInputFault

        product_parts = _annotation_parts(product_id, single=True)
        source_root_parts = _annotation_parts(document.identity_request.source_products_root)
        golden_root_parts = _annotation_parts(document.identity_request.golden_products_root)
        source_parts = (*source_root_parts, *product_parts)
        golden_parts = (*golden_root_parts, *product_parts)
        meta_parts = _annotation_parts(product.product_meta_path, single=True)
        pdf_parts = {name: _annotation_parts(name, single=True) for name in product.pdf_digests}
        consumed_parts = {
            name: _annotation_parts(name, single=True) for name in product.consumed_input_digests
        }
        if any(not name.casefold().endswith(".pdf") for name in pdf_parts):
            raise _BaselineInputFault

        root = _AnnotationInputRoot(repo_root)
        try:
            if root.names(source_parts) != set(pdf_parts) | {product.product_meta_path}:
                raise _BaselineInputFault
            if root.names(golden_parts) != set(consumed_parts) | {"fields.json"}:
                raise _BaselineInputFault
            schema_files = root.flat_files(_SCHEMA_BASELINE.parts)
            template_files = root.flat_files(_TEMPLATE_BASELINE.parts)
            pdf_bytes = {
                name: root.read((*source_parts, *parts)) for name, parts in pdf_parts.items()
            }
            meta_bytes = root.read((*source_parts, *meta_parts))
            fields_bytes = root.read((*golden_parts, "fields.json"))
            consumed_bytes = {
                name: root.read((*golden_parts, *parts)) for name, parts in consumed_parts.items()
            }
        finally:
            root.close()

        if (
            {name: _annotation_digest(value) for name, value in pdf_bytes.items()}
            != product.pdf_digests
            or _annotation_digest(meta_bytes) != product.product_meta_digest
            or _annotation_digest(fields_bytes) != product.fields_digest
            or {name: _annotation_digest(value) for name, value in consumed_bytes.items()}
            != product.consumed_input_digests
        ):
            raise _BaselineInputFault
        shared_input_digests = document.identity_request.shared_input_digests
        consumed_shared_files = {
            PurePosixPath(*root_parts, name).as_posix(): value
            for root_parts, files in (
                (_SCHEMA_BASELINE.parts, schema_files),
                (_TEMPLATE_BASELINE.parts, template_files),
            )
            for name, value in files
        }
        if any(
            shared_input_digests.get(path) != _annotation_digest(value)
            for path, value in consumed_shared_files.items()
        ):
            raise _BaselineInputFault

        meta = _json_object(meta_bytes)
        fields = _json_object(fields_bytes)
        plan_code = meta.get("planCode")
        clause_name = meta.get("clauseName")
        if (
            not isinstance(plan_code, str)
            or not plan_code.strip()
            or plan_code != plan_code.strip()
            or (
                clause_name is not None
                and (not isinstance(clause_name, str) or clause_name != product_id)
            )
        ):
            raise _BaselineInputFault
        fields_line_key = fields.get("line_key")
        schema_version = fields.get("schema_version")
        if (
            fields_line_key != product.line_key
            or not isinstance(schema_version, str)
            or not schema_version.strip()
            or schema_version != schema_version.strip()
        ):
            raise _BaselineInputFault

        root_fd = _open_private_directory(run_root)
        os.close(root_fd)
        product_files = tuple(
            sorted(
                {
                    **pdf_bytes,
                    product.product_meta_path: meta_bytes,
                }.items()
            )
        )
        verified_repo_files = tuple(
            sorted(
                (
                    *(
                        (
                            PurePosixPath(*source_parts, name).as_posix(),
                            value,
                        )
                        for name, value in product_files
                    ),
                    (
                        PurePosixPath(*golden_parts, "fields.json").as_posix(),
                        fields_bytes,
                    ),
                    *(
                        (
                            PurePosixPath(*golden_parts, name).as_posix(),
                            value,
                        )
                        for name, value in consumed_bytes.items()
                    ),
                    *(
                        (
                            PurePosixPath(*_SCHEMA_BASELINE.parts, name).as_posix(),
                            value,
                        )
                        for name, value in schema_files
                    ),
                    *(
                        (
                            PurePosixPath(*_TEMPLATE_BASELINE.parts, name).as_posix(),
                            value,
                        )
                        for name, value in template_files
                    ),
                )
            )
        )
        return _AdmittedBaselineInputs(
            repo_root=repo_root,
            source_root=repo_root.joinpath(*source_root_parts),
            product_dir=repo_root.joinpath(*source_parts),
            product_name=product_id,
            plan_code=plan_code,
            line_key=product.line_key,
            schema_version=schema_version,
            extractor_model=extractor_role.model_id,
            judge_model=judge_role.model_id,
            product_files=product_files,
            schema_files=schema_files,
            template_files=template_files,
            verified_repo_files=verified_repo_files,
        )
    except (
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        _AnnotationInputFault,
        _BaselineInputFault,
    ):
        raise AdmissionPausedError("baseline_identity_mismatch") from None


def _baseline_target_digest(product_name: str) -> str:
    return hashlib.sha256(
        _BASELINE_TARGET_DOMAIN + b"baseline\0" + product_name.encode("utf-8")
    ).hexdigest()


def _open_baseline_run_child(parent_fd: int, name: str, *, create: bool) -> int | None:
    try:
        _annotation_parts(name, single=True)
    except _AnnotationInputFault as error:
        raise _BaselineResumeFault from error
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        if not create:
            return None
        try:
            os.mkdir(name, _PRIVATE_DIRECTORY_MODE, dir_fd=parent_fd)
            os.fsync(parent_fd)
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
        except OSError as error:
            raise _BaselineResumeFault from error
    except OSError as error:
        raise _BaselineResumeFault from error
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o022
        ):
            raise _BaselineResumeFault
        return descriptor
    except (OSError, _BaselineResumeFault) as error:
        os.close(descriptor)
        raise _BaselineResumeFault from error


def _read_baseline_manifest(run_fd: int) -> RunManifest | None:
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(
                "manifest.json",
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=run_fd,
            )
        except FileNotFoundError:
            return None
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o022
            or metadata.st_size > _MAX_ANNOTATION_INPUT_BYTES
        ):
            raise _BaselineResumeFault
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            total += len(chunk)
            if total > _MAX_ANNOTATION_INPUT_BYTES:
                raise _BaselineResumeFault
            chunks.append(chunk)
        return RunManifest.model_validate_json(b"".join(chunks))
    except (OSError, ValidationError, ValueError, _BaselineResumeFault) as error:
        raise _BaselineResumeFault from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _require_private_baseline_run_lock(run_fd: int) -> None:
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(
                ".run.lock",
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=run_fd,
            )
        except FileNotFoundError:
            return
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE
            or metadata.st_nlink != 1
        ):
            raise _BaselineResumeFault
    except (OSError, _BaselineResumeFault) as error:
        raise _BaselineResumeFault from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _private_baseline_checkpoint_status(
    run_fd: int,
    *,
    identity: _BaselineRunIdentity,
    schema_version: str,
) -> tuple[bool, bool]:
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(
                "checkpoint.sqlite3",
                os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=run_fd,
            )
        except FileNotFoundError:
            return False, False
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE
            or metadata.st_nlink != 1
        ):
            raise _BaselineResumeFault
        if metadata.st_size == 0:
            return True, False
        try:
            path_metadata = os.stat(
                "checkpoint.sqlite3",
                dir_fd=run_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(path_metadata.st_mode)
                or (path_metadata.st_dev, path_metadata.st_ino)
                != (metadata.st_dev, metadata.st_ino)
            ):
                raise _BaselineResumeFault
            chunks: list[bytes] = []
            total = 0
            os.lseek(descriptor, 0, os.SEEK_SET)
            while chunk := os.read(descriptor, 1024 * 1024):
                total += len(chunk)
                if total > _MAX_ANNOTATION_INPUT_BYTES:
                    raise _BaselineResumeFault
                chunks.append(chunk)
            checkpoint_bytes = b"".join(chunks)
            if (
                not checkpoint_bytes.startswith(b"SQLite format 3\x00")
                or len(checkpoint_bytes) < 20
                or checkpoint_bytes[18] not in {1, 2}
                or checkpoint_bytes[19] not in {1, 2}
            ):
                raise _BaselineResumeFault
            memory_image = bytearray(checkpoint_bytes)
            memory_image[18:20] = b"\x01\x01"
            with closing(sqlite3.connect(":memory:")) as connection:
                connection.deserialize(bytes(memory_image))
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                if not {"checkpoints", "writes"} <= tables:
                    raise _BaselineResumeFault
                row = connection.execute(
                    "SELECT type, checkpoint FROM checkpoints "
                    "WHERE thread_id = ? AND checkpoint_ns = '' "
                    "ORDER BY checkpoint_id DESC LIMIT 1",
                    (identity.run_id,),
                ).fetchone()
                if row is None and connection.execute(
                    "SELECT 1 FROM checkpoints LIMIT 1"
                ).fetchone() is not None:
                    raise _BaselineResumeFault
                if row is not None:
                    try:
                        decoded = SqliteSaver(connection).serde.loads_typed(
                            (str(row[0]), bytes(row[1]))
                        )
                    except Exception as error:
                        raise _BaselineResumeFault from error
                    if not isinstance(decoded, Mapping):
                        raise _BaselineResumeFault
                    values = decoded.get("channel_values")
                    if not isinstance(values, Mapping):
                        raise _BaselineResumeFault
                    expected = {
                        "run_id": identity.run_id,
                        "run_dir": str(identity.run_dir),
                        "checkpoint_path": str(identity.checkpoint_path),
                        "product_dir": str(identity.product_dir),
                        "product_id": identity.product_id,
                        "product_name": identity.product_name,
                        "line_key": identity.line_key,
                        "schema_version": schema_version,
                        "model_id": identity.model_id,
                        "judge_mode": "gateway",
                    }
                    if any(values.get(key) != value for key, value in expected.items()):
                        raise _BaselineResumeFault
                    checkpoint_manifest = values.get("manifest")
                    if checkpoint_manifest is not None:
                        try:
                            manifest = RunManifest.model_validate(checkpoint_manifest)
                        except ValidationError as error:
                            raise _BaselineResumeFault from error
                        _require_baseline_manifest_identity(
                            manifest,
                            identity,
                            schema_version=schema_version,
                        )
            final_metadata = os.stat(
                "checkpoint.sqlite3",
                dir_fd=run_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(final_metadata.st_mode)
                or (final_metadata.st_dev, final_metadata.st_ino)
                != (metadata.st_dev, metadata.st_ino)
            ):
                raise _BaselineResumeFault
            return True, row is not None
        except Exception as error:
            raise _BaselineResumeFault from error
    except (OSError, _BaselineResumeFault) as error:
        raise _BaselineResumeFault from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _create_private_baseline_checkpoint(run_fd: int) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            "checkpoint.sqlite3",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            _PRIVATE_FILE_MODE,
            dir_fd=run_fd,
        )
        os.fchmod(descriptor, _PRIVATE_FILE_MODE)
        os.fsync(descriptor)
        os.fsync(run_fd)
    except OSError as error:
        raise _BaselineResumeFault from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _require_baseline_manifest_identity(
    manifest: RunManifest,
    identity: _BaselineRunIdentity,
    *,
    schema_version: str | None,
) -> None:
    if (
        manifest.run_id != identity.run_id
        or Path(manifest.run_dir) != identity.run_dir
        or Path(manifest.checkpoint_path) != identity.checkpoint_path
        or Path(manifest.product_dir) != identity.product_dir
        or manifest.product_id != identity.product_id
        or manifest.product_name != identity.product_name
        or manifest.line_key != identity.line_key
        or manifest.model_id != identity.model_id
        or manifest.judge_mode != "gateway"
        or (schema_version is not None and manifest.schema_version != schema_version)
    ):
        raise _BaselineResumeFault


def _baseline_resume_state(
    *,
    run_root: Path,
    plan_hash: str,
    target_digest: str,
    identity: _BaselineRunIdentity,
    schema_version: str | None,
    provision: bool,
) -> bool:
    """Inspect or provision the sole admitted checkpoint via no-follow dirfds."""

    root_fd: int | None = None
    plan_fd: int | None = None
    run_fd: int | None = None
    resume_fault = False
    try:
        root_fd = _open_private_directory(run_root)
        plan_fd = _open_baseline_run_child(root_fd, plan_hash, create=provision)
        if plan_fd is None:
            return False
        run_fd = _open_baseline_run_child(plan_fd, target_digest, create=provision)
        if run_fd is None:
            return False
        names = set(os.listdir(run_fd))
        if not names <= _BASELINE_RUN_NAMES:
            raise _BaselineResumeFault
        _require_private_baseline_run_lock(run_fd)
        checkpoint_exists, checkpoint_initialized = (
            _private_baseline_checkpoint_status(
                run_fd,
                identity=identity,
                schema_version=schema_version or "",
            )
        )
        manifest = _read_baseline_manifest(run_fd)
        if manifest is not None:
            if not checkpoint_exists:
                raise _BaselineResumeFault
            _require_baseline_manifest_identity(
                manifest,
                identity,
                schema_version=schema_version,
            )
        if not checkpoint_exists and provision:
            _create_private_baseline_checkpoint(run_fd)
        return checkpoint_initialized
    except (OSError, RuntimeError, _AnnotationInputFault, _BaselineResumeFault):
        resume_fault = True
    finally:
        if run_fd is not None:
            os.close(run_fd)
        if plan_fd is not None:
            os.close(plan_fd)
        if root_fd is not None:
            os.close(root_fd)
    if resume_fault:
        raise AdmissionPausedError("baseline_resume_state_unsafe") from None
    raise AssertionError("baseline resume state did not return or fail")


async def _execute_baseline(
    *,
    document: RunAdmissionDocument,
    product_id: str,
    extractor_client: AdmittedModelClient,
    judge_client: AdmittedModelClient,
    configuration: _ReadyConfiguration,
) -> RunResult:
    inputs = _revalidate_baseline_inputs(
        document=document,
        product_id=product_id,
        extractor_client=extractor_client,
        judge_client=judge_client,
        configuration=configuration,
    )
    plan_hash = execution_plan_hash(document)
    snapshot = _private_baseline_snapshot(
        configuration=configuration,
        inputs=inputs,
        plan_hash=plan_hash,
    )
    target_digest = _baseline_target_digest(inputs.product_name)
    run_dir = configuration.run_root / plan_hash / target_digest
    checkpoint_path = run_dir / "checkpoint.sqlite3"
    identity = _BaselineRunIdentity(
        run_dir=run_dir,
        checkpoint_path=checkpoint_path,
        run_id=target_digest,
        product_dir=snapshot.product_dir,
        product_id=inputs.plan_code,
        product_name=inputs.product_name,
        line_key=inputs.line_key,
        model_id=inputs.extractor_model,
    )
    resume = _baseline_resume_state(
        run_root=configuration.run_root,
        plan_hash=plan_hash,
        target_digest=target_digest,
        identity=identity,
        schema_version=inputs.schema_version,
        provision=False,
    )

    registry = load_schema_registry(snapshot.schema_root)
    if registry.version != inputs.schema_version:
        raise AdmissionPausedError("baseline_identity_mismatch")
    registry.line(inputs.line_key)
    templates = load_template_registry(snapshot.template_root)
    parser_fingerprint = directory_parser_fingerprint(
        document=document,
        configuration=configuration,
        installed_version=installed_package_version,
    )
    table_provider = select_table_provider("pdfplumber")
    matching_products = tuple(
        product
        for product in document.identity_request.products
        if product.product_id == product_id
    )
    if len(matching_products) != 1 or type(matching_products[0]) is not ProductInputPlan:
        raise AdmissionPausedError("baseline_identity_mismatch")
    product_plan = matching_products[0]
    admission_identity = BaselineAdmissionIdentity(
        format="insurancekb.baseline-admission-identity.v1",
        execution_plan_hash=plan_hash,
        parser_fingerprint=parser_fingerprint,
        pdf_digests=product_plan.pdf_digests,
        product_meta_digest=product_plan.product_meta_digest,
        fields_digest=product_plan.fields_digest,
        consumed_input_digests=product_plan.consumed_input_digests,
        shared_input_digests=document.identity_request.shared_input_digests,
        extractor_model_id=inputs.extractor_model,
        judge_model_id=inputs.judge_model,
        schema_version=registry.version,
        template_registry_version=templates.version,
    )

    def precommit_validator(candidate: RunArtifactCommitCandidate) -> None:
        if (
            _revalidate_baseline_inputs(
                document=document,
                product_id=product_id,
                extractor_client=extractor_client,
                judge_client=judge_client,
                configuration=configuration,
            )
            != inputs
        ):
            raise AdmissionPausedError("baseline_identity_mismatch")
        validate_baseline_commit_candidate(
            candidate,
            expected_run_id=target_digest,
            expected_run_dir=run_dir,
            expected_checkpoint_path=checkpoint_path,
            expected_product_dir=snapshot.product_dir,
            expected_product_id=inputs.plan_code,
            expected_product_name=inputs.product_name,
            expected_line_key=inputs.line_key,
            expected_schema_version=registry.version,
            expected_model_id=inputs.extractor_model,
            expected_judge_mode="gateway",
            expected_admission_identity=admission_identity,
        )

    provisioned_resume = _baseline_resume_state(
        run_root=configuration.run_root,
        plan_hash=plan_hash,
        target_digest=target_digest,
        identity=identity,
        schema_version=registry.version,
        provision=True,
    )
    if provisioned_resume is not resume:
        raise AdmissionPausedError("baseline_resume_state_unsafe")

    source = DirectoryDocumentSource(
        replay_identity=f"run-admission-020/{plan_hash}/{target_digest}",
        parser_fingerprint=parser_fingerprint,
    )
    pipeline = ExtractionPipeline(
        client=extractor_client,
        registry=registry,
        model_id=inputs.extractor_model,
        source=source,
        config=PipelineConfig(judge_mode="gateway"),
        judge=JudgeDispatcher(mode="gateway", client=judge_client),
        template_registry=templates,
        table_provider=table_provider,
        baseline_admission_identity=admission_identity,
        precommit_validator=precommit_validator,
    )
    raw_result = await pipeline.run(
        run_dir=run_dir,
        source_request=DirectorySourceRequest(product_dir=snapshot.product_dir),
        product_dir=snapshot.product_dir,
        product_id=inputs.plan_code,
        product_name=inputs.product_name,
        line_key=inputs.line_key,
        thread_id=target_digest,
        checkpoint_path=checkpoint_path,
        resume=resume,
    )
    if (
        _revalidate_baseline_inputs(
            document=document,
            product_id=product_id,
            extractor_client=extractor_client,
            judge_client=judge_client,
            configuration=configuration,
        )
        != inputs
    ):
        raise AdmissionPausedError("baseline_identity_mismatch")
    return validate_baseline_result(
        result=raw_result,
        run_root=configuration.run_root,
        expected_source_root=snapshot.root,
        expected_product_dir=snapshot.product_dir,
        expected_run_id=target_digest,
        expected_run_dir=run_dir,
        expected_product_id=inputs.plan_code,
        expected_product_name=inputs.product_name,
        expected_line_key=inputs.line_key,
        expected_schema_version=registry.version,
        expected_model_id=inputs.extractor_model,
        expected_judge_mode="gateway",
        expected_admission_identity=admission_identity,
    )


def _commit_execution_artifact(
    *,
    document: RunAdmissionDocument,
    command: str,
    product_id: str,
    execution_result: CanaryArtifactBundle | RunResult,
    configuration: _ReadyConfiguration,
) -> None:
    if command not in {"annotate-canary", "baseline-product"}:
        raise AdmissionPausedError("canary_artifact_commit_invalid")
    if command == "annotate-canary":
        if (
            product_id not in _ANNOTATION_BUSINESS_PRODUCT_IDS
            or not isinstance(execution_result, CanaryArtifactBundle)
        ):
            raise AdmissionPausedError("canary_artifact_commit_invalid")
        try:
            plan_hash = execution_plan_hash(document)
            inputs = _load_annotation_inputs(
                document=document,
                product_id=product_id,
                configuration=configuration,
            )
            snapshot = _private_annotation_snapshot(
                configuration=configuration,
                inputs=inputs,
                plan_hash=plan_hash,
            )
            cache_dir = _private_annotation_cache(
                configuration=configuration,
                repo_root=inputs.repo_root,
                product_id=product_id,
                plan_hash=plan_hash,
            )
            validated_bundle = validate_annotation_bundle(
                document=document,
                configuration=configuration,
                product_id=product_id,
                bundle=execution_result,
                cache_dir=cache_dir,
                page_loader=_snapshot_page_loader(
                    repo_product_dir=inputs.product_dir,
                    snapshot_product_dir=snapshot.product_dir,
                    pdf_names=frozenset(
                        name
                        for name, _value in inputs.source_files
                        if name.casefold().endswith(".pdf")
                    ),
                ),
                execution_plan_hash=plan_hash,
            )
            store = CanaryArtifactStore()
            if product_id == _FIRST_CANARY_PRODUCT_ID:
                store.write_first_canary(
                    execution_plan_hash=plan_hash,
                    bundle=validated_bundle,
                )
            else:
                store.write_annotation_bundle(
                    execution_plan_hash=plan_hash,
                    product_id=product_id,
                    bundle=validated_bundle,
                )
        except (
            AdmissionPausedError,
            CanaryArtifactStoreError,
            TypeError,
            ValueError,
        ):
            raise AdmissionPausedError("canary_artifact_commit_invalid") from None
        return
    if command != "baseline-product" or not isinstance(execution_result, RunResult):
        raise AdmissionPausedError("baseline_artifact_commit_invalid")
    manifest = execution_result.manifest
    admission_identity = manifest.baseline_admission
    run_dir = Path(manifest.run_dir)
    product_dir = Path(manifest.product_dir)
    try:
        products = tuple(
            item
            for item in document.identity_request.products
            if item.product_id == product_id
        )
        if len(products) != 1 or not isinstance(admission_identity, BaselineAdmissionIdentity):
            raise _BaselineInputFault
        product = products[0]
        extractor_role = document.plan.payload.model_roles["weak_extractor"]
        judge_role = document.plan.payload.model_roles["judge"]
        expected_plan_code = _ANNOTATION_BUSINESS_PRODUCT_IDS[product_id]
        plan_hash = execution_plan_hash(document)
        target_digest = _baseline_target_digest(product_id)
        expected_run_dir = configuration.run_root / plan_hash / target_digest
        snapshot_parent = (
            configuration.run_root / _BASELINE_SNAPSHOT_ROOT / plan_hash
        )
        snapshot_parts = product_dir.relative_to(snapshot_parent).parts
        if (
            plan_hash != admission_identity.execution_plan_hash
            or manifest.run_id != target_digest
            or run_dir != expected_run_dir
            or len(snapshot_parts) != 2
            or snapshot_parts[1] != "product"
            or len(snapshot_parts[0]) != 64
            or any(character not in _LOWER_HEX for character in snapshot_parts[0])
            or product.line_key != manifest.line_key
            or dict(product.pdf_digests) != dict(admission_identity.pdf_digests)
            or product.product_meta_digest != admission_identity.product_meta_digest
            or product.fields_digest != admission_identity.fields_digest
            or dict(product.consumed_input_digests)
            != dict(admission_identity.consumed_input_digests)
            or dict(document.identity_request.shared_input_digests)
            != dict(admission_identity.shared_input_digests)
            or extractor_role.model_id != admission_identity.extractor_model_id
            or judge_role.model_id != admission_identity.judge_model_id
            or manifest.product_id != expected_plan_code
            or manifest.product_name != product_id
            or manifest.schema_version != admission_identity.schema_version
            or manifest.template_registry_version
            != admission_identity.template_registry_version
        ):
            raise _BaselineInputFault
    except (AttributeError, KeyError, TypeError, ValueError, _BaselineInputFault):
        raise AdmissionPausedError("baseline_artifact_commit_invalid") from None

    validate_baseline_result(
        result=execution_result,
        run_root=configuration.run_root,
        expected_source_root=product_dir.parent,
        expected_product_dir=product_dir,
        expected_run_id=target_digest,
        expected_run_dir=expected_run_dir,
        expected_product_id=expected_plan_code,
        expected_product_name=product_id,
        expected_line_key=product.line_key,
        expected_schema_version=admission_identity.schema_version,
        expected_model_id=admission_identity.extractor_model_id,
        expected_judge_mode="gateway",
        expected_admission_identity=admission_identity,
    )


def _build_annotation_candidate(
    *,
    document: RunAdmissionDocument,
    ledger: BudgetLedger,
    execution_decision: RuntimeAdmissionDecision,
    configuration: _ReadyConfiguration,
) -> CanaryReviewCandidate:
    del configuration
    try:
        return build_canary_review_candidate(
            document=document,
            admission=execution_decision,
            ledger=ledger,
            artifact_inspector=CanaryArtifactStore(),
        )
    except (CanaryArtifactStoreError, CanaryReviewCandidateError, BudgetLedgerError):
        raise AdmissionPausedError("canary_candidate_build_invalid") from None


def _persist_annotation_candidate(
    *,
    candidate: object,
    configuration: _ReadyConfiguration,
) -> None:
    del configuration
    if not isinstance(candidate, CanaryReviewCandidate):
        raise AdmissionPausedError("canary_candidate_persist_invalid")
    try:
        CanaryArtifactStore().write_candidate(candidate)
    except (CanaryArtifactStoreError, TypeError, ValueError):
        raise AdmissionPausedError("canary_candidate_persist_invalid") from None


def _resume_annotation_candidate_fail_closed(
    *,
    product_id: str,
    document: RunAdmissionDocument,
    evaluator: ProductionAdmissionEvaluator,
    ledger: BudgetLedger,
    configuration: _ReadyConfiguration,
) -> bool:
    if product_id != _FIRST_CANARY_PRODUCT_ID:
        raise AdmissionPausedError("candidate_resume_state_unsafe")
    payload = document.plan.payload
    account_id = budget_account_identity(payload.run_identity, payload.purpose)
    try:
        settlement = ledger.product_settlement_snapshot(
            account_id,
            "annotation",
            product_id,
        )
    except BudgetLedgerError as error:
        if str(error) != "product reservation not found":
            raise AdmissionPausedError("candidate_resume_state_unsafe") from None
        settlement = None

    store = CanaryArtifactStore()
    try:
        artifacts = store.inspect_optional(
            execution_plan_hash=execution_plan_hash(document),
            canary_target=ExecutionTarget(
                stage="annotation",
                product_id=product_id,
            ),
        )
    except (ArtifactEvidenceInspectionError, CanaryArtifactStoreError, ValueError):
        raise AdmissionPausedError("candidate_resume_state_unsafe") from None

    if settlement is None and artifacts is None:
        return False
    if (
        settlement is None
        or artifacts is None
        or settlement.reservation_state != "settled"
    ):
        raise AdmissionPausedError("candidate_resume_state_unsafe")

    decision = _fresh_initial_candidate_decision(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
    )
    candidate = _build_annotation_candidate(
        document=document,
        ledger=ledger,
        execution_decision=decision,
        configuration=configuration,
    )
    _persist_annotation_candidate(
        candidate=candidate,
        configuration=configuration,
    )
    return True


def _fresh_initial_candidate_decision(
    *,
    document: RunAdmissionDocument,
    evaluator: ProductionAdmissionEvaluator,
    ledger: BudgetLedger,
) -> RuntimeAdmissionDecision:
    """Evaluate the post-settlement boundary and require first-canary authority."""

    try:
        decision = evaluator.evaluate_execution(document, ledger)
    except Exception:
        raise AdmissionPausedError("candidate_evaluation_failed") from None
    if decision.result.state != "READY":
        raise AdmissionBlockedError(decision.result)
    if not isinstance(decision.authorization, InitialExecutionAuthorization):
        blocked_result = decision.result.model_copy(
            update={
                "state": "BLOCKED",
                "blockers": (
                    AdmissionBlocker(
                        check="execution_authorization",
                        code="candidate_authorization_invalid",
                    ),
                ),
            }
        )
        raise AdmissionBlockedError(blocked_result)
    return decision


def _build_session_lock(account_id: str) -> RunSessionLock:
    return RunSessionLock(account_id=account_id)


def _production_ready_dependencies() -> _ReadyCommandDependencies:
    return _ReadyCommandDependencies(
        session_lock_factory=_build_session_lock,
        ledger_factory=_open_budget_ledger,
        guard_factory=_build_runtime_guard,
        annotation_executor=_execute_annotation,
        baseline_executor=_execute_baseline,
        artifact_committer=_commit_execution_artifact,
        candidate_builder=_build_annotation_candidate,
        candidate_persister=_persist_annotation_candidate,
        baseline_settlement_guard=run_settlement_guard,
        candidate_resumer=_resume_annotation_candidate_fail_closed,
    )


async def _run_ready_command_for_testing(
    *,
    command: str,
    product_id: str,
    document: RunAdmissionDocument,
    evaluator: ProductionAdmissionEvaluator,
    configuration: _ReadyConfiguration,
    dependencies: _ReadyCommandDependencies,
) -> None:
    """Run one admitted product while holding the account-level session lock."""

    if command == "annotate-canary":
        stage = "annotation"
    elif command == "baseline-product":
        stage = "baseline"
    else:
        raise ValueError("unsupported READY command")

    payload = document.plan.payload
    account_id = budget_account_identity(payload.run_identity, payload.purpose)
    response_root = configuration.run_root / account_id / "responses"
    with dependencies.session_lock_factory(account_id):
        ledger = dependencies.ledger_factory(configuration.ledger_path)
        guard = dependencies.guard_factory(
            document=document,
            evaluator=evaluator,
            ledger=ledger,
            response_root=response_root,
        )
        active_error: BaseException | None = None
        try:
            guard.recover_incomplete_at_startup()
            if (
                command == "annotate-canary"
                and product_id == _FIRST_CANARY_PRODUCT_ID
                and dependencies.candidate_resumer(
                    product_id=product_id,
                    document=document,
                    evaluator=evaluator,
                    ledger=ledger,
                    configuration=configuration,
                )
            ):
                return
            product = guard.begin_product(stage=stage, product_id=product_id)
            if command == "annotate-canary":
                annotation_result = await dependencies.annotation_executor(
                    document=document,
                    product_id=product_id,
                    client=product.client(role="annotator"),
                    configuration=configuration,
                )
                if not isinstance(annotation_result, CanaryArtifactBundle):
                    raise RuntimeError("annotation executor did not return a CanaryArtifactBundle")
                execution_result: CanaryArtifactBundle | RunResult = annotation_result
            else:
                baseline_result = await dependencies.baseline_executor(
                    document=document,
                    product_id=product_id,
                    extractor_client=product.client(role="weak_extractor"),
                    judge_client=product.client(role="judge"),
                    configuration=configuration,
                )
                if not isinstance(baseline_result, RunResult):
                    raise RuntimeError("baseline executor did not return a RunResult")
                execution_result = baseline_result

            if command == "baseline-product":
                settlement_run_dir = (
                    configuration.run_root
                    / execution_plan_hash(document)
                    / _baseline_target_digest(product_id)
                )
                async with dependencies.baseline_settlement_guard(settlement_run_dir):
                    dependencies.artifact_committer(
                        document=document,
                        command=command,
                        product_id=product_id,
                        execution_result=execution_result,
                        configuration=configuration,
                    )
                    product.settle()
            else:
                dependencies.artifact_committer(
                    document=document,
                    command=command,
                    product_id=product_id,
                    execution_result=execution_result,
                    configuration=configuration,
                )
                product.settle()
            if command == "annotate-canary" and product_id == _FIRST_CANARY_PRODUCT_ID:
                fresh_decision = _fresh_initial_candidate_decision(
                    document=document,
                    evaluator=evaluator,
                    ledger=ledger,
                )
                candidate = dependencies.candidate_builder(
                    document=document,
                    ledger=ledger,
                    execution_decision=fresh_decision,
                    configuration=configuration,
                )
                dependencies.candidate_persister(
                    candidate=candidate,
                    configuration=configuration,
                )
        except BaseException as error:
            active_error = error
            raise
        finally:
            try:
                guard.close()
            except BaseException:
                if active_error is None:
                    raise


async def _run_ready_command(
    *,
    command: str,
    product_id: str,
    document: RunAdmissionDocument,
    evaluator: ProductionAdmissionEvaluator,
    configuration: _ProductionConfiguration,
) -> None:
    await _run_ready_command_for_testing(
        command=command,
        product_id=product_id,
        document=document,
        evaluator=evaluator,
        configuration=configuration,
        dependencies=_production_ready_dependencies(),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Preflight fixed inputs, then dispatch a freshly guarded READY product."""

    try:
        arguments = _build_parser().parse_args(argv)
        configuration = _production_configuration()
        document = _load_production_document(configuration)
        if not _contains_exact_product(document, str(arguments.product)):
            return 2
        evaluator = _build_production_evaluator(configuration)
        result = evaluator(document)
        if result.state == "BLOCKED":
            return 2
        try:
            asyncio.run(
                _run_ready_command(
                    command=str(arguments.command),
                    product_id=str(arguments.product),
                    document=document,
                    evaluator=evaluator,
                    configuration=configuration,
                )
            )
        except AdmissionBlockedError:
            return 2
        return 0
    except Exception:
        return 1


class RunSessionLockUnavailableError(RuntimeError):
    """The same budget account already has an active run session."""


class RunSessionLockSecurityError(RuntimeError):
    """The run-session lock path or metadata is not safe to trust."""


class RunSessionLock:
    """Hold one non-blocking OS lock for an entire admitted run session."""

    def __init__(self, *, account_id: str) -> None:
        self._initialize(
            lock_root=_PRODUCTION_SESSION_ROOT,
            account_id=account_id,
        )

    @classmethod
    def _for_testing(cls, *, lock_root: Path, account_id: str) -> Self:
        instance = cls.__new__(cls)
        instance._initialize(lock_root=lock_root, account_id=account_id)
        return instance

    def _initialize(self, *, lock_root: Path, account_id: str) -> None:
        if (
            not isinstance(account_id, str)
            or len(account_id) != 64
            or any(character not in _LOWER_HEX for character in account_id)
        ):
            raise RunSessionLockSecurityError(
                "run-session account id must be 64 lowercase hexadecimal characters"
            )
        root = Path(lock_root)
        if not root.is_absolute():
            raise RunSessionLockSecurityError("run-session lock root must be absolute")
        self._lock_root = root
        self._account_id = account_id
        self._lock_path = root / f"{account_id}.lock"
        self._fd: int | None = None

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    def __enter__(self) -> Self:
        if self._fd is not None:
            raise RunSessionLockSecurityError("run-session lock object is already acquired")
        root_fd = self._open_verified_root()
        lock_fd: int | None = None
        try:
            flags = os.O_NOFOLLOW | os.O_CLOEXEC | os.O_CREAT | os.O_RDWR
            open_failed = False
            try:
                lock_fd = os.open(
                    self._lock_path.name,
                    flags,
                    _PRIVATE_FILE_MODE,
                    dir_fd=root_fd,
                )
            except OSError:
                open_failed = True
            if open_failed or lock_fd is None:
                raise RunSessionLockSecurityError("run-session lock file cannot be opened safely")
            self._verify_lock_file(lock_fd)
            acquisition_errno: int | None = None
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                acquisition_errno = exc.errno
            if acquisition_errno in {errno.EACCES, errno.EAGAIN}:
                raise RunSessionLockUnavailableError("run-session lock is already held")
            if acquisition_errno is not None:
                raise RunSessionLockSecurityError("run-session lock acquisition failed")
            self._fd = lock_fd
            lock_fd = None
            return self
        finally:
            self._close_fd(root_fd)
            if lock_fd is not None:
                self._close_fd(lock_fd)

    def __exit__(self, *_exc: object) -> None:
        business_error_active = bool(_exc and _exc[0] is not None)
        try:
            self.release()
        except RunSessionLockSecurityError:
            if not business_error_active:
                raise

    def release(self) -> None:
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        unlock_failed = False
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            unlock_failed = True
        close_failed = not self._close_fd(fd)
        if unlock_failed or close_failed:
            raise RunSessionLockSecurityError("run-session lock release failed")

    def _open_verified_root(self) -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        absolute = Path(os.path.abspath(self._lock_root))
        current_fd = self._open_directory(absolute.anchor, flags=flags)
        try:
            self._verify_directory(current_fd, final=not absolute.parts[1:])
            final_index = len(absolute.parts) - 2
            for index, part in enumerate(absolute.parts[1:]):
                child_fd = self._open_directory(part, flags=flags, dir_fd=current_fd)
                try:
                    self._verify_directory(child_fd, final=index == final_index)
                except BaseException:
                    self._close_fd(child_fd)
                    raise
                self._close_fd(current_fd)
                current_fd = child_fd
            verified_fd = current_fd
            current_fd = -1
            return verified_fd
        finally:
            if current_fd >= 0:
                self._close_fd(current_fd)

    @staticmethod
    def _open_directory(
        path: str,
        *,
        flags: int,
        dir_fd: int | None = None,
    ) -> int:
        descriptor: int | None = None
        try:
            descriptor = os.open(path, flags, dir_fd=dir_fd)
        except OSError:
            pass
        if descriptor is None:
            raise RunSessionLockSecurityError("run-session lock root path cannot be opened safely")
        return descriptor

    @staticmethod
    def _verify_directory(fd: int, *, final: bool) -> None:
        metadata: os.stat_result | None = None
        try:
            metadata = os.fstat(fd)
        except OSError:
            pass
        if metadata is None or not stat.S_ISDIR(metadata.st_mode):
            raise RunSessionLockSecurityError(
                "run-session lock root path contains an unsafe component"
            )
        effective_uid = os.geteuid()
        mode = stat.S_IMODE(metadata.st_mode)
        if final:
            if metadata.st_uid != effective_uid or mode != _PRIVATE_DIRECTORY_MODE:
                raise RunSessionLockSecurityError(
                    "run-session lock root must be an owned private directory"
                )
            return
        if metadata.st_uid not in {0, effective_uid}:
            raise RunSessionLockSecurityError("run-session lock root path has an untrusted owner")
        writable_by_others = bool(mode & (stat.S_IWGRP | stat.S_IWOTH))
        sticky_directory = bool(mode & stat.S_ISVTX)
        if writable_by_others and not sticky_directory:
            raise RunSessionLockSecurityError("run-session lock root path has an unsafe mode")

    @staticmethod
    def _verify_lock_file(fd: int) -> None:
        metadata: os.stat_result | None = None
        try:
            metadata = os.fstat(fd)
        except OSError:
            pass
        if (
            metadata is None
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE
        ):
            raise RunSessionLockSecurityError(
                "run-session lock file must be owned, regular, and private"
            )

    @staticmethod
    def _close_fd(fd: int) -> bool:
        try:
            os.close(fd)
        except OSError:
            return False
        return True


async def _run_locked_session_for_testing(
    *,
    session_lock: RunSessionLock,
    recovery: Callable[[], None],
    begin: Callable[[], None],
    construct_client: Callable[[], None],
    model_io: Callable[[], Awaitable[None]],
    artifact: Callable[[], None],
    settle: Callable[[], None],
) -> None:
    """Exercise the lock-owned lifecycle without exposing a production runner."""

    with session_lock:
        recovery()
        begin()
        construct_client()
        await model_io()
        artifact()
        settle()


__all__ = [
    "RunSessionLock",
    "RunSessionLockSecurityError",
    "RunSessionLockUnavailableError",
]
