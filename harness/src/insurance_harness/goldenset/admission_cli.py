"""Filesystem boundary for the Golden-set run-admission check."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import os
import secrets
import stat
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePath
from types import MappingProxyType
from typing import Annotated, Any, Never, Self

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import (
    BaseModel,
    ConfigDict,
    StrictStr,
    StringConstraints,
    ValidationError,
    field_serializer,
)
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.resolver import BaseResolver

from insurance_harness.goldenset.admission import (
    AdmissionResult,
    ProductionAdmissionEvaluator,
    RunAdmissionDocument,
)
from insurance_harness.goldenset.admission_models import (
    CanaryReviewApprovalEnvelope,
    RunAdmissionPlan,
    canonical_json_bytes,
)

type AdmissionEvaluator = Callable[[RunAdmissionPlan], AdmissionResult]
type AdmissionDocumentEvaluator = Callable[[RunAdmissionDocument], AdmissionResult]
type NonBlankStr = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1)
]
_DEPLOYMENT_TRUST_PATH = Path("/etc/insurancekb/run-admission-trust.yaml")
_CANARY_REVIEW_APPROVAL_INBOX = Path(
    "/var/lib/insurancekb/run-admission/canary-review-inbox"
)
_MAX_TRUST_CONFIGURATION_BYTES = 1024 * 1024
_MAX_CANARY_REVIEW_BYTES = 256 * 1024


class CanaryReviewApprovalInputError(ValueError):
    """The unique external review file is syntactically or structurally invalid."""


class CanaryReviewInboxError(PermissionError):
    """The deployment-owned review inbox is ambiguous or not protected."""


class _TrustedApprovalConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    public_keys: Mapping[NonBlankStr, NonBlankStr]
    budget_roles: tuple[NonBlankStr, ...]
    provenance_roles: tuple[NonBlankStr, ...]
    canary_review_roles: tuple[NonBlankStr, ...] = ()

    def model_post_init(self, _context: Any) -> None:
        object.__setattr__(
            self,
            "public_keys",
            MappingProxyType(dict(self.public_keys)),
        )

    @field_serializer("public_keys")
    def serialize_public_keys(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)

    def copy(
        self,
        *,
        include: object = None,
        exclude: object = None,
        update: dict[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        raise TypeError("copy() is disabled")


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys at every depth."""


def _construct_unique_mapping(
    loader: yaml.SafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found a duplicate mapping key",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _safe_load_unique(payload: str) -> object:
    return yaml.load(payload, Loader=_UniqueKeySafeLoader)


def _require_protected_inode(
    metadata: os.stat_result,
    *,
    required_uid: int,
    inode_kind: str,
) -> None:
    expected_type = stat.S_ISDIR if inode_kind == "directory" else stat.S_ISREG
    if (
        not expected_type(metadata.st_mode)
        or metadata.st_uid != required_uid
        or metadata.st_mode & 0o022
    ):
        raise CanaryReviewInboxError(
            f"canary review {inode_kind} is not deployment-protected"
        )


def _read_bounded_descriptor(descriptor: int, *, maximum: int) -> bytes:
    chunks: list[bytes] = []
    consumed = 0
    while consumed <= maximum:
        chunk = os.read(descriptor, min(64 * 1024, maximum + 1 - consumed))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        consumed += len(chunk)
    raise CanaryReviewInboxError("canary review approval exceeds the size limit")


def _load_canary_review_approval_from_inbox(
    inbox: Path,
    *,
    anchor: Path,
    required_uid: int,
) -> CanaryReviewApprovalEnvelope:
    """Safely load exactly one envelope below an already selected trust anchor.

    Production calls this only with the code-fixed absolute inbox and ``/`` anchor.
    The explicit parameters exist so deterministic tests can exercise the same
    dir-fd/O_NOFOLLOW traversal without weakening the production owner requirement.
    """

    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise CanaryReviewInboxError(
            "platform cannot safely traverse the canary review inbox"
        )
    if not inbox.is_absolute() or not anchor.is_absolute():
        raise CanaryReviewInboxError("canary review inbox and anchor must be absolute")
    try:
        relative = inbox.relative_to(anchor)
    except ValueError as exc:
        raise CanaryReviewInboxError(
            "canary review inbox is outside its deployment anchor"
        ) from exc
    if not relative.parts or ".." in relative.parts:
        raise CanaryReviewInboxError("canary review inbox path is invalid")

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW
    current_fd = -1
    try:
        current_fd = os.open(anchor, directory_flags)
        _require_protected_inode(
            os.fstat(current_fd),
            required_uid=required_uid,
            inode_kind="directory",
        )
        for component in relative.parts:
            next_fd = os.open(component, directory_flags, dir_fd=current_fd)
            try:
                _require_protected_inode(
                    os.fstat(next_fd),
                    required_uid=required_uid,
                    inode_kind="directory",
                )
            except Exception:
                os.close(next_fd)
                raise
            os.close(current_fd)
            current_fd = next_fd

        entries = os.listdir(current_fd)
        if len(entries) != 1:
            raise CanaryReviewInboxError(
                "canary review inbox must contain exactly one envelope"
            )
        filename = entries[0]
        if (
            filename in {".", ".."}
            or Path(filename).name != filename
            or Path(filename).suffix.casefold() not in {".json", ".yaml", ".yml"}
        ):
            raise CanaryReviewInboxError("canary review envelope filename is invalid")

        file_fd = os.open(filename, file_flags, dir_fd=current_fd)
        try:
            metadata = os.fstat(file_fd)
            _require_protected_inode(
                metadata,
                required_uid=required_uid,
                inode_kind="file",
            )
            if metadata.st_size == 0:
                raise CanaryReviewApprovalInputError(
                    "canary review approval has invalid syntax or schema"
                )
            if metadata.st_size > _MAX_CANARY_REVIEW_BYTES:
                raise CanaryReviewInboxError(
                    "canary review approval exceeds the size limit"
                )
            payload = _read_bounded_descriptor(
                file_fd,
                maximum=_MAX_CANARY_REVIEW_BYTES,
            )
        finally:
            os.close(file_fd)
    except CanaryReviewInboxError:
        raise
    except OSError as exc:
        raise CanaryReviewInboxError("canary review inbox traversal failed") from exc
    finally:
        if current_fd >= 0:
            os.close(current_fd)

    try:
        raw = _safe_load_unique(payload.decode("utf-8"))
        return CanaryReviewApprovalEnvelope.model_validate(raw)
    except (UnicodeDecodeError, yaml.YAMLError, ValidationError, TypeError) as exc:
        raise CanaryReviewApprovalInputError(
            "canary review approval has invalid syntax or schema"
        ) from exc


def _load_deployment_canary_review_approval() -> (
    CanaryReviewApprovalEnvelope | None
):
    """Load the optional review only from the code-fixed, root-owned inbox."""

    try:
        _CANARY_REVIEW_APPROVAL_INBOX.lstat()
    except FileNotFoundError:
        return None
    return _load_canary_review_approval_from_inbox(
        _CANARY_REVIEW_APPROVAL_INBOX,
        anchor=Path("/"),
        required_uid=0,
    )


def _write_temporary(path: Path, payload: str) -> Path:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _render_markdown(result: AdmissionResult, result_digest: str) -> str:
    lines = [
        f"# Run admission: {result.state}",
        "",
        f"- Canonical JSON commit marker: `{result_digest}`",
        "- This report is non-authoritative without the matching JSON artifact.",
        f"- Plan payload: `{result.plan_payload_hash}`",
        f"- Evaluated revision: `{result.evaluated_revision}`",
        f"- Evaluated at: `{result.evaluated_at.isoformat()}`",
        f"- Checker version: `{result.checker_version}`",
        f"- Runtime capability: `{result.runtime_capability_version}`",
        "",
        "## Checks",
        "",
    ]
    for check in result.checks:
        status = "PASS" if check.passed else "BLOCKED"
        lines.append(f"- `{check.name}`: {status}")
    if result.blockers:
        lines.extend(["", "## Blockers", ""])
        for blocker in result.blockers:
            lines.append(f"- `{blocker.check}`: `{blocker.code}`")
    if result.evidence is not None:
        identity = result.evidence.identity
        lines.extend(
            [
                "",
                "## Identity evidence",
                "",
                f"- Shared inputs: `{identity.shared_input_digest}`",
                f"- Execution surface: `{identity.execution_surface_digest}`",
                f"- Product fingerprints: {len(identity.product_digests)}",
            ]
        )
        for identity_blocker in identity.blockers:
            qualifier = identity_blocker.product_id or identity_blocker.subject
            suffix = f" (`{qualifier}`)" if qualifier is not None else ""
            lines.append(f"- Blocker `{identity_blocker.code}`{suffix}")
        lines.extend(["", "## Approval evidence", ""])
        for approval in result.evidence.approvals:
            status = "VERIFIED" if approval.verified else "BLOCKED"
            lines.append(f"- `{approval.domain}`: {status}")
        lines.extend(["", "## Provider probes", ""])
        for probe in result.evidence.probes:
            status = "VERIFIED" if probe.verified else "BLOCKED"
            lines.append(f"- `{probe.role}`: {status} (`{probe.status_class}`)")
        if result.evidence.budget is not None:
            lines.extend(
                [
                    "",
                    "## Budget evidence",
                    "",
                    f"- Contract: `{result.evidence.budget.contract_hash}`",
                    f"- Approval revision: {result.evidence.budget.revision}",
                    f"- Currency: `{result.evidence.budget.currency}`",
                ]
            )
    return "\n".join(lines) + "\n"


def _remove_artifacts(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _same_path(left: Path, right: Path) -> bool:
    try:
        if left.resolve(strict=False) == right.resolve(strict=False):
            return True
        if left.exists() and right.exists():
            return os.path.samefile(left, right)
    except (OSError, RuntimeError):
        return True
    return False


def _fsync_parent_directories(*paths: Path) -> None:
    parents = {path.parent.resolve(strict=True) for path in paths}
    for parent in sorted(parents):
        descriptor = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _publish_result(
    *,
    result: AdmissionResult,
    result_json: Path,
    report_md: Path,
) -> int:
    if _same_path(result_json, report_md):
        _remove_artifacts(result_json)
        return 1
    result_temporary: Path | None = None
    report_temporary: Path | None = None
    try:
        canonical_payload = canonical_json_bytes(result)
        result_digest = hashlib.sha256(canonical_payload).hexdigest()
        result_temporary = _write_temporary(
            result_json,
            canonical_payload.decode("utf-8") + "\n",
        )
        report_temporary = _write_temporary(
            report_md,
            _render_markdown(result, result_digest),
        )
        os.replace(report_temporary, report_md)
        report_temporary = None
        os.replace(result_temporary, result_json)
        result_temporary = None
        _fsync_parent_directories(result_json, report_md)
        return 0 if result.state == "READY" else 2
    except Exception:
        if result_temporary is not None:
            result_temporary.unlink(missing_ok=True)
        if report_temporary is not None:
            report_temporary.unlink(missing_ok=True)
        _remove_artifacts(result_json, report_md)
        return 1


def run_check(
    *,
    plan_path: Path,
    result_json: Path,
    report_md: Path,
    evaluator: AdmissionEvaluator,
) -> int:
    """Evaluate one plan, returning 0 READY, 2 BLOCKED, or 1 invalid/checker error.

    Result JSON is installed last and therefore acts as the commit marker.  Exceptions
    are intentionally not rendered: provider bodies, secrets, and host paths must not
    leak into either durable artifact.
    """

    if _same_path(plan_path, result_json) or _same_path(plan_path, report_md):
        return 1
    if _same_path(result_json, report_md):
        _remove_artifacts(result_json)
        return 1
    try:
        _remove_artifacts(result_json, report_md)
        raw = _safe_load_unique(plan_path.read_text(encoding="utf-8"))
        plan = RunAdmissionPlan.model_validate(raw)
        result = evaluator(plan)
        return _publish_result(
            result=result,
            result_json=result_json,
            report_md=report_md,
        )
    except Exception:
        _remove_artifacts(result_json, report_md)
        return 1


def run_document_check(
    *,
    plan_path: Path,
    result_json: Path,
    report_md: Path,
    evaluator: AdmissionDocumentEvaluator,
) -> int:
    """Load and evaluate the full production admission document."""

    if _same_path(plan_path, result_json) or _same_path(plan_path, report_md):
        return 1
    if _same_path(result_json, report_md):
        _remove_artifacts(result_json)
        return 1
    try:
        _remove_artifacts(result_json, report_md)
        raw = _safe_load_unique(plan_path.read_text(encoding="utf-8"))
        document = RunAdmissionDocument.model_validate(raw)
        result = evaluator(document)
        return _publish_result(
            result=result,
            result_json=result_json,
            report_md=report_md,
        )
    except Exception:
        _remove_artifacts(result_json, report_md)
        return 1


def _parse_trusted_approval_configuration(
    payload: str,
) -> tuple[
    Mapping[str, Ed25519PublicKey],
    frozenset[str],
    frozenset[str],
    frozenset[str],
]:
    raw = _safe_load_unique(payload)
    configuration = _TrustedApprovalConfiguration.model_validate(raw)
    public_keys: dict[str, Ed25519PublicKey] = {}
    for key_id, encoded in configuration.public_keys.items():
        try:
            key_bytes = base64.b64decode(encoded, validate=True)
            public_keys[key_id] = Ed25519PublicKey.from_public_bytes(key_bytes)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("trusted approval public key is invalid") from exc
    return (
        MappingProxyType(public_keys),
        frozenset(configuration.budget_roles),
        frozenset(configuration.provenance_roles),
        frozenset(configuration.canary_review_roles),
    )


def _load_deployment_approval_configuration() -> tuple[
    Mapping[str, Ed25519PublicKey],
    frozenset[str],
    frozenset[str],
    frozenset[str],
]:
    """Load only the root-owned, code-fixed trust store; run CLI cannot replace it."""

    try:
        _DEPLOYMENT_TRUST_PATH.lstat()
    except FileNotFoundError:
        return {}, frozenset(), frozenset(), frozenset()
    if not hasattr(os, "O_NOFOLLOW"):
        raise OSError("platform cannot safely open deployment trust configuration")
    descriptor = os.open(
        _DEPLOYMENT_TRUST_PATH,
        os.O_RDONLY | os.O_NOFOLLOW,
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_mode & 0o022
            or metadata.st_size > _MAX_TRUST_CONFIGURATION_BYTES
        ):
            raise PermissionError("deployment trust configuration is not protected")
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = -1
            return _parse_trusted_approval_configuration(stream.read())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise ValueError(message)


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="python -m insurance_harness.goldenset.admission_cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check")
    check.add_argument("--plan", required=True)
    check.add_argument("--repo-root", required=True)
    check.add_argument("--result-json", required=True)
    check.add_argument("--report-md", required=True)
    check.add_argument("--probe", action="store_true")
    return parser


def _resolve_relative_plan(repo_root: Path, value: str) -> Path:
    requested = PurePath(value)
    if requested.is_absolute() or ".." in requested.parts:
        raise ValueError("plan path must be repository-relative")
    resolved = (repo_root / requested).resolve(strict=True)
    if not resolved.is_relative_to(repo_root):
        raise ValueError("plan path escapes repository root")
    return resolved


def main(argv: Sequence[str] | None = None) -> int:
    result_json: Path | None = None
    report_md: Path | None = None
    try:
        arguments = _build_parser().parse_args(argv)
        result_json = Path(arguments.result_json)
        report_md = Path(arguments.report_md)
        repo_root = Path(arguments.repo_root).resolve(strict=True)
        plan_path = _resolve_relative_plan(repo_root, str(arguments.plan))
        public_keys, budget_roles, provenance_roles, _canary_review_roles = (
            _load_deployment_approval_configuration()
        )
        evaluator = ProductionAdmissionEvaluator(
            repo_root=repo_root,
            trusted_public_keys=public_keys,
            allowed_budget_roles=budget_roles,
            allowed_provenance_roles=provenance_roles,
            probe=bool(arguments.probe),
        )
        return run_document_check(
            plan_path=plan_path,
            result_json=result_json,
            report_md=report_md,
            evaluator=evaluator,
        )
    except Exception:
        if result_json is not None and report_md is not None:
            _remove_artifacts(result_json, report_md)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AdmissionDocumentEvaluator",
    "AdmissionEvaluator",
    "main",
    "run_check",
    "run_document_check",
]
