#!/usr/bin/env python3
"""Freeze deterministic pdfplumber baseline artifacts for ProductVersion 596-1.

This task-local composer is deliberately offline.  It consumes caller-issued
source, attempt, policy, and snapshot identities; it never allocates runtime
authority and never retains PDF body text.
"""

import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import traceback
from collections.abc import Mapping
from pathlib import Path
from typing import Final, NamedTuple, Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from insurance_harness.compiler import native_pdfplumber
from insurance_harness.compiler.material_profiles import (
    MaterialProfileResolution,
    ParsePolicyReceipt,
)
from insurance_harness.compiler.parsed_documents import (
    ParseAttemptV1,
    ParsedDocumentV1,
    ParseManifestV1,
    ParseOutputFactsV1,
    ParseQualityDecisionV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
    build_parse_manifest,
    evaluate_parse_quality,
)
from insurance_harness.sources.models import GenerationOrdering, SourceRevision

_ROLES: Final[tuple[str, ...]] = ("terms", "brochure", "rate_table")
_FILENAMES: Final[dict[str, str]] = {
    "terms": "terms.json",
    "brochure": "brochure.json",
    "rate_table": "rate-table.json",
}
_SOURCE_SHA256: Final[dict[str, str]] = {
    "terms": "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
    "brochure": "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
    "rate_table": "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
}
_SECRET_PATTERN = re.compile(r"(?i)(?:bearer\s+|api[_-]?key\s*[:=]|token\s*[:=]|secret\s*[:=])")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_SAFE_REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        "ATTEMPT_NOT_COMPLETED",
        "BASELINE_CAPTURE_FAILED",
        "BASELINE_PARSE_QUALITY_BLOCKED",
        "INVALID_CAPTURE_REQUEST",
        "NONDETERMINISTIC_BASELINE_PARSE",
        "OUTPUT_ALREADY_EXISTS",
        "OUTPUT_PARENT_INVALID",
        "OUTPUT_POLICY_VIOLATION",
        "OUTPUT_PUBLISH_FAILED",
        "PARSER_POLICY_DRIFT",
        "SOURCE_IDENTITY_MISMATCH",
        "UNSAFE_CAPTURE_INPUT",
    }
)
_SAFE_DIAGNOSTIC_REASON = re.compile(r"^[a-z0-9_]{1,96}$")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
    )


class CaptureMaterialV1(_FrozenModel):
    material_role: str
    source_revision: SourceRevision
    attempt_state: str
    parse_policy_receipt: ParsePolicyReceipt
    subject: ParseSubjectV1
    parser: ParserIdentityV1
    attempt: ParseAttemptV1
    snapshot: ParseSnapshotV1
    output_facts: ParseOutputFactsV1
    material_profile_resolution: MaterialProfileResolution


class CaptureRequestV1(_FrozenModel):
    contract: str
    product_version: str
    materials: tuple[CaptureMaterialV1, ...]

    @model_validator(mode="after")
    def require_exact_material_roles(self) -> Self:
        roles = tuple(item.material_role for item in self.materials)
        if len(roles) != len(set(roles)) or set(roles) != set(_ROLES):
            raise ValueError("capture request must contain each exact material role")
        return self


class BaselineBlockedDiagnostic(_FrozenModel):
    material_role: str
    reason_codes: tuple[str, ...]
    manifest_hash: str | None
    decision_hash: str | None
    diagnostic_sha256: str


class BaselineArtifactCaptureError(ValueError):
    """Typed, body-free rejection at the offline capture boundary."""

    def __init__(
        self,
        reason_code: str,
        *,
        diagnostic: BaselineBlockedDiagnostic | None = None,
    ) -> None:
        self.reason_code = reason_code
        self.diagnostic = diagnostic
        super().__init__(reason_code)


class CaptureResult(NamedTuple):
    artifact_hashes: dict[str, str]
    manifest_sha256: str


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object_hash(value: object) -> str:
    return _sha256(_canonical_bytes(value).rstrip(b"\n"))


def _parser_fingerprint(parser: ParserIdentityV1) -> str:
    return _object_hash(parser.model_dump(mode="json"))


def _unsafe_output_string(value: str) -> bool:
    return (
        value.startswith("/")
        or bool(_WINDOWS_ABSOLUTE.match(value))
        or "://" in value
        or "\x00" in value
        or "\n" in value
        or "\r" in value
        or bool(_SECRET_PATTERN.search(value))
    )


def _validate_safe_output_identities(item: CaptureMaterialV1) -> None:
    exported = {
        "source_revision": item.source_revision.model_dump(mode="json"),
        "subject": item.subject.model_dump(mode="json"),
        "parser": item.parser.model_dump(mode="json"),
        "attempt": item.attempt.model_dump(mode="json"),
        "snapshot": item.snapshot.model_dump(mode="json"),
        "output_facts": item.output_facts.model_dump(mode="json"),
        "parse_policy_receipt": item.parse_policy_receipt.model_dump(mode="json"),
    }

    def visit(value: object) -> bool:
        if isinstance(value, str):
            return _unsafe_output_string(value)
        if isinstance(value, Mapping):
            return any(visit(child) for child in value.values())
        if isinstance(value, (tuple, list)):
            return any(visit(child) for child in value)
        return False

    if visit(exported):
        raise BaselineArtifactCaptureError("UNSAFE_CAPTURE_INPUT")


def _validate_material(item: CaptureMaterialV1, product_version: str) -> None:
    role = item.material_role
    expected_sha = _SOURCE_SHA256[role]
    resolution = item.material_profile_resolution
    receipt = resolution.parse_policy_receipt
    if item.attempt_state != "completed":
        raise BaselineArtifactCaptureError("ATTEMPT_NOT_COMPLETED")
    if (
        item.parser.parser_id != "pdfplumber"
        or item.parser.parser_profile_ref != receipt.default_parser_profile_ref
        or item.attempt.attempt_number != 1
        or item.attempt.attempt_role != "default"
        or item.parse_policy_receipt != receipt
    ):
        raise BaselineArtifactCaptureError("PARSER_POLICY_DRIFT")
    if not isinstance(item.source_revision.ordering, GenerationOrdering):
        raise BaselineArtifactCaptureError("SOURCE_IDENTITY_MISMATCH")
    if (
        item.source_revision.file_hash != expected_sha
        or item.source_revision.parser_fingerprint != _parser_fingerprint(item.parser)
        or item.source_revision.ordering.value != item.attempt.generation
        or item.subject.source_revision_id != item.source_revision.value
        or item.subject.source_sha256 != expected_sha
        or item.subject.product_version_id != product_version
        or item.subject.material_profile_id != resolution.profile.profile_id
        or item.subject.material_profile_binding_hash != resolution.binding_hash
        or item.snapshot.snapshot_generation != item.attempt.generation
        or resolution.request.product_version != product_version
        or resolution.profile.material_role != role
        or resolution.profile.source.sha256 != expected_sha
    ):
        raise BaselineArtifactCaptureError("SOURCE_IDENTITY_MISMATCH")
    if (
        item.output_facts.privacy_policy_ref != receipt.privacy_policy_ref
        or item.output_facts.output_policy_ref != receipt.output_policy_ref
        or item.output_facts.body_text_included
        or item.output_facts.secrets_included
        or item.output_facts.absolute_paths_included
        or item.output_facts.unknown_vendor_fields_included
    ):
        raise BaselineArtifactCaptureError("OUTPUT_POLICY_VIOLATION")
    _validate_safe_output_identities(item)


def _request_from_wire(raw: object) -> CaptureRequestV1:
    request: CaptureRequestV1 | None = None
    try:
        request = CaptureRequestV1.model_validate(raw)
    except (ValidationError, TypeError, ValueError):
        # The wire value may contain an unknown secret.  Drop it before raising
        # outside the handler so neither cause/context nor this frame retains it.
        raw = None
    if request is None:
        raise BaselineArtifactCaptureError("INVALID_CAPTURE_REQUEST") from None
    if request.contract != "pdfplumber-baseline-capture-request.v1":
        raise BaselineArtifactCaptureError("INVALID_CAPTURE_REQUEST")
    if request.product_version != "596-1":
        raise BaselineArtifactCaptureError("SOURCE_IDENTITY_MISMATCH")
    for item in request.materials:
        _validate_material(item, request.product_version)
    return request


def _validate_pdf_bytes(pdf_bytes_by_role: Mapping[str, bytes]) -> None:
    if set(pdf_bytes_by_role) != set(_ROLES):
        raise BaselineArtifactCaptureError("SOURCE_IDENTITY_MISMATCH")
    for role in _ROLES:
        payload = pdf_bytes_by_role[role]
        if type(payload) is not bytes or _sha256(payload) != _SOURCE_SHA256[role]:
            raise BaselineArtifactCaptureError("SOURCE_IDENTITY_MISMATCH")


def _blocked_diagnostic(
    role: str,
    reason_codes: tuple[str, ...],
    *,
    manifest_hash: str | None = None,
    decision_hash: str | None = None,
) -> BaselineBlockedDiagnostic:
    seed = {
        "contract": "baseline-parse-quality-blocked-diagnostic.v1",
        "material_role": role,
        "reason_codes": reason_codes,
        "manifest_hash": manifest_hash,
        "decision_hash": decision_hash,
    }
    return BaselineBlockedDiagnostic(
        material_role=role,
        reason_codes=reason_codes,
        manifest_hash=manifest_hash,
        decision_hash=decision_hash,
        diagnostic_sha256=_object_hash(seed),
    )


def _capture_one(item: CaptureMaterialV1, pdf_bytes: bytes) -> bytes:
    try:
        facts = native_pdfplumber.extract_native_pdfplumber_facts(
            pdf_bytes,
            expected_source_sha256=item.subject.source_sha256,
            parser_build_id=item.parser.parser_build_id,
            parser_config_hash=item.parser.parser_config_hash,
        )
        raw_document, raw_manifest, raw_decision = native_pdfplumber.build_parsed_document_v1(
            facts,
            subject=item.subject,
            parser=item.parser,
            attempt=item.attempt,
            snapshot=item.snapshot,
            output_facts=item.output_facts,
            material_profile_resolution=item.material_profile_resolution,
        )
        document = ParsedDocumentV1.model_validate(
            raw_document.model_dump(mode="json", exclude_computed_fields=True)
        )
        manifest = ParseManifestV1.model_validate(
            raw_manifest.model_dump(mode="json", exclude_computed_fields=True)
        )
        decision = ParseQualityDecisionV1.model_validate(
            raw_decision.model_dump(mode="json", exclude_computed_fields=True)
        )
        expected_manifest = build_parse_manifest(
            document,
            item.material_profile_resolution.profile,
        )
        expected_decision = evaluate_parse_quality(
            document=document,
            manifest=expected_manifest,
            material_profile_resolution=item.material_profile_resolution,
        )
    except BaselineArtifactCaptureError:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        diagnostic = _blocked_diagnostic(
            item.material_role,
            ("native_pdfplumber_contract_invalid",),
        )
        raise BaselineArtifactCaptureError(
            "BASELINE_PARSE_QUALITY_BLOCKED", diagnostic=diagnostic
        ) from exc

    if (
        document.subject != item.subject
        or document.parser != item.parser
        or document.attempt != item.attempt
        or document.snapshot != item.snapshot
        or document.output_facts != item.output_facts
        or manifest.subject != item.subject
        or manifest.parser != item.parser
        or manifest.attempt != item.attempt
        or manifest.snapshot != item.snapshot
        or manifest.document_hash != document.document_hash
        or manifest != expected_manifest
        or decision.subject != item.subject
        or decision.manifest_hash != manifest.manifest_hash
        or decision.parse_policy_receipt != item.parse_policy_receipt
        or decision != expected_decision
    ):
        diagnostic = _blocked_diagnostic(
            item.material_role,
            ("parsed_document_identity_drift",),
            manifest_hash=manifest.manifest_hash,
            decision_hash=_object_hash(decision.model_dump(mode="json")),
        )
        raise BaselineArtifactCaptureError("BASELINE_PARSE_QUALITY_BLOCKED", diagnostic=diagnostic)
    decision_hash = _object_hash(decision.model_dump(mode="json"))
    if decision.decision != "ADMIT":
        diagnostic = _blocked_diagnostic(
            item.material_role,
            tuple(decision.reason_codes) or ("parse_quality_not_admitted",),
            manifest_hash=manifest.manifest_hash,
            decision_hash=decision_hash,
        )
        raise BaselineArtifactCaptureError("BASELINE_PARSE_QUALITY_BLOCKED", diagnostic=diagnostic)

    return _canonical_bytes(
        {
            "contract": "pdfplumber-baseline-artifact.v1",
            "material_role": item.material_role,
            "source_revision": item.source_revision.model_dump(mode="json"),
            "parse_policy_receipt": item.parse_policy_receipt.model_dump(mode="json"),
            "parsed_document": document.model_dump(mode="json"),
            "parse_manifest": manifest.model_dump(mode="json"),
            "parse_quality_decision": decision.model_dump(mode="json"),
        }
    )


def _parse_pass(
    request: CaptureRequestV1,
    pdf_bytes_by_role: Mapping[str, bytes],
) -> dict[str, bytes]:
    by_role = {item.material_role: item for item in request.materials}
    return {role: _capture_one(by_role[role], pdf_bytes_by_role[role]) for role in _ROLES}


def _publish_no_replace(source: Path, target: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    raw = os.fsencode(source), os.fsencode(target)
    if sys.platform == "darwin":
        rename = getattr(libc, "renamex_np", None)
        arguments = (*raw, 0x00000004)
    elif sys.platform == "linux":
        rename = getattr(libc, "renameat2", None)
        arguments = (-100, raw[0], -100, raw[1], 1)
    else:
        raise OSError(errno.ENOTSUP, "atomic no-replace publish unsupported")
    if rename is None:
        raise OSError(errno.ENOTSUP, "atomic no-replace publish unavailable")
    if rename(*arguments):
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise FileExistsError(code, os.strerror(code), target)
        raise OSError(code, os.strerror(code), target)


def _write_private_file(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _stage_and_publish(output_dir: Path, payloads: Mapping[str, bytes]) -> None:
    parent = output_dir.parent
    if not parent.is_dir():
        raise BaselineArtifactCaptureError("OUTPUT_PARENT_INVALID")
    stage = Path(tempfile.mkdtemp(prefix=".capture-061-", dir=parent))
    os.chmod(stage, 0o700)
    published = False
    try:
        for filename, payload in payloads.items():
            _write_private_file(stage / filename, payload)
        directory_fd = os.open(stage, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        try:
            _publish_no_replace(stage, output_dir)
        except FileExistsError as exc:
            raise BaselineArtifactCaptureError("OUTPUT_ALREADY_EXISTS") from exc
        except OSError as exc:
            raise BaselineArtifactCaptureError("OUTPUT_PUBLISH_FAILED") from exc
        published = True
    finally:
        if not published and stage.exists():
            shutil.rmtree(stage)


def _safe_diagnostic_copy(
    diagnostic: BaselineBlockedDiagnostic | None,
) -> BaselineBlockedDiagnostic | None:
    if diagnostic is None:
        return None
    try:
        safe = BaselineBlockedDiagnostic.model_validate(
            diagnostic.model_dump(mode="json")
        )
    except (ValidationError, TypeError, ValueError):
        return None
    hashes = (safe.manifest_hash, safe.decision_hash, safe.diagnostic_sha256)
    if (
        safe.material_role not in _ROLES
        or not safe.reason_codes
        or any(not _SAFE_DIAGNOSTIC_REASON.fullmatch(item) for item in safe.reason_codes)
        or any(
            value is not None and not re.fullmatch(r"[0-9a-f]{64}", value)
            for value in hashes
        )
    ):
        return None
    return safe


def _clear_exception_graph(root: BaseException) -> None:
    pending = [root]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
        if current.__traceback__ is not None:
            traceback.clear_frames(current.__traceback__)
        current.__traceback__ = None
        current.__cause__ = None
        current.__context__ = None


def _safe_boundary_error(error: Exception) -> BaselineArtifactCaptureError:
    if isinstance(error, BaselineArtifactCaptureError):
        reason_code = (
            error.reason_code
            if error.reason_code in _SAFE_REASON_CODES
            else "BASELINE_CAPTURE_FAILED"
        )
        diagnostic = _safe_diagnostic_copy(error.diagnostic)
    else:
        reason_code = "BASELINE_CAPTURE_FAILED"
        diagnostic = None
    safe = BaselineArtifactCaptureError(reason_code, diagnostic=diagnostic)
    _clear_exception_graph(error)
    return safe


def _capture_pdfplumber_artifacts_private(
    raw_request: object,
    pdf_bytes_by_role: Mapping[str, bytes],
    output_dir: Path,
) -> CaptureResult:
    request = _request_from_wire(raw_request)
    _validate_pdf_bytes(pdf_bytes_by_role)
    if output_dir.exists():
        raise BaselineArtifactCaptureError("OUTPUT_ALREADY_EXISTS")
    if not output_dir.parent.is_dir():
        raise BaselineArtifactCaptureError("OUTPUT_PARENT_INVALID")

    first = _parse_pass(request, pdf_bytes_by_role)
    second = _parse_pass(request, pdf_bytes_by_role)
    if first != second:
        raise BaselineArtifactCaptureError("NONDETERMINISTIC_BASELINE_PARSE")

    artifact_hashes = {_FILENAMES[role]: _sha256(first[role]) for role in _ROLES}
    manifest = _canonical_bytes(
        {
            "contract": "pdfplumber-baseline-capture-manifest.v1",
            "product_version": request.product_version,
            "material_roles": list(_ROLES),
            "files": artifact_hashes,
        }
    )
    payloads = {
        **{_FILENAMES[role]: first[role] for role in _ROLES},
        "capture-manifest.json": manifest,
    }
    _stage_and_publish(output_dir, payloads)
    return CaptureResult(
        artifact_hashes=dict(artifact_hashes),
        manifest_sha256=_sha256(manifest),
    )


def capture_pdfplumber_artifacts(
    raw_request: object,
    pdf_bytes_by_role: Mapping[str, bytes],
    output_dir: Path,
) -> CaptureResult:
    """Run the sensitive worker behind a traceback-sanitizing public boundary."""

    result: CaptureResult | None = None
    safe_error: BaselineArtifactCaptureError | None = None
    try:
        result = _capture_pdfplumber_artifacts_private(
            raw_request,
            pdf_bytes_by_role,
            output_dir,
        )
    except Exception as error:
        safe_error = _safe_boundary_error(error)
        del raw_request, pdf_bytes_by_role, output_dir
    if safe_error is not None:
        raise safe_error from None
    if result is None:  # pragma: no cover - defensive impossible state
        raise BaselineArtifactCaptureError("BASELINE_CAPTURE_FAILED") from None
    return result
