"""Human-controlled governance CLI for OpenSpec 029 release authority.

The repository has no production composition root for the 028 compiler bundle or a
production ``ReleaseAuthorizer``.  Consequently ``python -m`` without an explicitly
injected trusted context is a typed, zero-write terminal block.  Requests and receipts
can never self-attest authority, and this module does not discover a factory from the
environment or dynamically import one.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.scope import KnowledgeScope, require_current_scope
from insurance_harness.knowledge.merge import (
    ReviewDecisionConflict,
    ReviewPreconditionRequired,
    ReviewStale,
    resolve_review,
)
from insurance_harness.knowledge.release_approval import (
    ReleaseApprovalError,
    ReleaseApprovalService,
    ReleaseAuthorizer,
    ReleaseManifestPersistenceError,
    persist_release_manifest,
)
from insurance_harness.knowledge.release_authority import (
    ReleaseActivationFailure,
    ReleaseAuthorityService,
)
from insurance_harness.knowledge.release_boundary import (
    build_fresh_staging_candidate_manifest,
)
from insurance_harness.knowledge.release_manifest import (
    ReleaseManifest,
    ReleaseManifestBuildError,
    ReleaseManifestIntegrityError,
    verify_release_manifest,
)
from insurance_harness.knowledge.serving import (
    ApprovedSnapshotReader,
    ApprovedSnapshotResult,
    CanonicalServingFact,
)
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    CurrentRelease,
    ReleaseActivationAudit,
    ReleaseApproval,
    ReleaseManifestRecord,
    ReleaseSnapshot,
    ReviewItem,
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_SENSITIVE_PATH = re.compile(
    r"(^|[-_.])(secret|password|api[-_]?key|provider[-_]?raw|raw[-_]?provider)($|[-_.])",
    re.IGNORECASE,
)


class ReleaseCLIError(ValueError):
    """Typed fail-closed governance command failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


def _canonical_text(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("value must be non-empty canonical text")
    return value


def _literal_sha256(value: str) -> str:
    if _SHA256.fullmatch(value) is None:
        raise ValueError("value must be an exact lowercase SHA-256")
    return value


def _canonical_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("timestamp must be canonical ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC).isoformat()


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat()


class ReviewDecision(_StrictFrozenModel):
    review_id: str
    expected_version: str
    action: Literal["approve", "reject"]
    principal: str
    actor_type: Literal["human", "principal"]
    authorization_receipt: str
    reason: str
    request_id: str

    _text = field_validator(
        "review_id",
        "expected_version",
        "principal",
        "authorization_receipt",
        "reason",
        "request_id",
    )(_canonical_text)


class ReviewDecisionsRequest(_StrictFrozenModel):
    input_origin: Literal["human-authored"]
    space_id: str
    compilation_manifest_hash: str
    decisions: tuple[ReviewDecision, ...] = Field(min_length=1)

    _space = field_validator("space_id")(_canonical_text)
    _hash = field_validator("compilation_manifest_hash")(_literal_sha256)

    @field_validator("decisions", mode="before")
    @classmethod
    def _tuple_decisions(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def _unique_decisions(self) -> ReviewDecisionsRequest:
        review_ids = [decision.review_id for decision in self.decisions]
        request_ids = [decision.request_id for decision in self.decisions]
        if len(review_ids) != len(set(review_ids)) or len(request_ids) != len(
            set(request_ids)
        ):
            raise ValueError("review decisions must be unique")
        return self


class ReleaseApprovalRequest(_StrictFrozenModel):
    input_origin: Literal["human-authored"]
    space_id: str
    manifest_hash: str
    snapshot_id: str
    expected_current_snapshot_id: str | None
    principal: str
    actor_type: Literal["human", "principal"]
    authorization_receipt: str
    reason: str

    _text = field_validator(
        "space_id",
        "snapshot_id",
        "principal",
        "authorization_receipt",
        "reason",
    )(_canonical_text)
    _hash = field_validator("manifest_hash")(_literal_sha256)

    @field_validator("expected_current_snapshot_id")
    @classmethod
    def _expected_current(cls, value: str | None) -> str | None:
        return None if value is None else _canonical_text(value)


class ReviewAuthorizationDecision(_StrictFrozenModel):
    outcome: Literal["authorized", "denied"]
    space_id: str
    review_id: str
    principal: str
    actor_type: str
    compilation_manifest_hash: str
    authorization_receipt: str

    _text = field_validator(
        "space_id",
        "review_id",
        "principal",
        "actor_type",
        "authorization_receipt",
    )(_canonical_text)
    _hash = field_validator("compilation_manifest_hash")(_literal_sha256)


class ReviewAuthorizer(Protocol):
    def authorize_review(
        self,
        *,
        space_id: str,
        review_id: str,
        principal: str,
        actor_type: str,
        compilation_manifest_hash: str,
        authorization_receipt: str,
    ) -> ReviewAuthorizationDecision: ...


@dataclass(frozen=True, slots=True)
class GovernanceContext:
    """Trusted application composition; artifact files never create this authority."""

    session: Session
    scope: KnowledgeScope
    review_authorizer: ReviewAuthorizer | None
    release_authorizer: ReleaseAuthorizer | None
    approved_snapshot_reader: ApprovedSnapshotReader | None = None


class AppliedReviewDecision(_StrictFrozenModel):
    review_id: str
    review_key: str
    change_set_id: str
    change_item_id: str
    expected_version: str
    action: Literal["approve", "reject"]
    principal: str
    actor_type: Literal["human", "principal"]
    authorization_receipt: str
    reason: str
    request_id: str
    resolved_at: str


class ReviewReceipt(_StrictFrozenModel):
    schema_version: Literal["review-receipt-v1"] = "review-receipt-v1"
    space_id: str
    compilation_manifest_hash: str
    request_hash: str
    change_set_ids: tuple[str, ...]
    decisions: tuple[AppliedReviewDecision, ...]
    receipt_hash: str

    @field_validator("change_set_ids", "decisions", mode="before")
    @classmethod
    def _receipt_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class CandidateRunRequest(_StrictFrozenModel):
    schema_version: Literal["candidate-run-request-v1"]
    space_id: str
    compilation_manifest_path: str
    compilation_manifest_hash: str
    review_receipt_hash: str
    snapshot_id: str
    knowledge_schema_version: str
    template_hashes: tuple[str, ...] = Field(min_length=1)
    model_plan_hash: str

    _text = field_validator(
        "space_id",
        "snapshot_id",
        "knowledge_schema_version",
    )(_canonical_text)
    _hash = field_validator(
        "compilation_manifest_hash",
        "review_receipt_hash",
        "model_plan_hash",
    )(_literal_sha256)

    @field_validator("template_hashes")
    @classmethod
    def _template_hash_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("template hashes must be unique")
        for item in value:
            _literal_sha256(item)
        return value

    @field_validator("template_hashes", mode="before")
    @classmethod
    def _template_tuple(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("compilation_manifest_path")
    @classmethod
    def _compilation_path(cls, value: str) -> str:
        return CompilationArtifact._safe_relative_path(value)


class CandidateReceipt(_StrictFrozenModel):
    schema_version: Literal["candidate-receipt-v1"] = "candidate-receipt-v1"
    space_id: str
    snapshot_id: str
    compilation_manifest_hash: str
    review_receipt_hash: str
    manifest_hash: str
    provenance_hash: str
    request_hash: str
    receipt_hash: str


class ApprovalReceipt(_StrictFrozenModel):
    schema_version: Literal["approval-receipt-v1"] = "approval-receipt-v1"
    space_id: str
    snapshot_id: str
    manifest_hash: str
    request_hash: str
    approval_id: str
    principal: str
    actor_type: Literal["human", "principal"]
    role: Literal["release_approver"]
    authorization_receipt: str
    reason: str
    approved_at: str
    created_at: str
    receipt_hash: str

    _timestamps = field_validator("approved_at", "created_at")(_canonical_timestamp)


class ReleaseProof(_StrictFrozenModel):
    schema_version: Literal["release-proof-v1"] = "release-proof-v1"
    action: Literal["promote"]
    space_id: str
    snapshot_id: str
    manifest_hash: str
    request_hash: str
    approval_receipt_hash: str
    previous_snapshot_id: str | None
    audit_id: str
    approval_id: str
    principal: str
    reason: str
    activated_at: str
    audit_created_at: str
    proof_hash: str

    _timestamps = field_validator("activated_at", "audit_created_at")(
        _canonical_timestamp
    )


class ReaderServingProof(_StrictFrozenModel):
    snapshot_id: str
    manifest_hash: str
    fact_count: int = Field(ge=0)
    facts_hash: str
    evidence_hash: str
    ordering_hash: str

    _text = field_validator("snapshot_id")(_canonical_text)
    _hashes = field_validator(
        "manifest_hash", "facts_hash", "evidence_hash", "ordering_hash"
    )(_literal_sha256)


class ServingProof(_StrictFrozenModel):
    schema_version: Literal["serving-proof-v1"] = "serving-proof-v1"
    space_id: str
    snapshot_id: str
    manifest_hash: str
    human_reader: ReaderServingProof
    mcp_reader: ReaderServingProof
    proof_hash: str

    _text = field_validator("space_id", "snapshot_id")(_canonical_text)
    _hashes = field_validator("manifest_hash", "proof_hash")(_literal_sha256)


class SealedArtifact(_StrictFrozenModel):
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)
    item_count: int = Field(ge=0)

    _hash = field_validator("sha256")(_literal_sha256)

    @field_validator("path")
    @classmethod
    def _safe_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or value != value.strip()
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or _SENSITIVE_PATH.search(value)
        ):
            raise ValueError("artifact path must be safe and relative")
        return value


class ArtifactManifest(_StrictFrozenModel):
    schema_version: Literal["artifact-manifest-v1"] = "artifact-manifest-v1"
    space_id: str
    snapshot_id: str
    release_manifest_hash: str
    compilation_manifest_hash: str
    release_proof_hash: str
    serving_proof_hash: str
    file_count: int = Field(ge=1)
    files: tuple[SealedArtifact, ...] = Field(min_length=1)
    manifest_hash: str

    @field_validator("files", mode="before")
    @classmethod
    def _files_tuple(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class CompilationArtifact(_StrictFrozenModel):
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)
    item_count: int = Field(ge=0)

    _hash = field_validator("sha256")(_literal_sha256)

    @field_validator("path")
    @classmethod
    def _safe_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or value != value.strip()
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or _SENSITIVE_PATH.search(value)
        ):
            raise ValueError("artifact path must be safe and relative")
        return value


class CompilationClaimRevision(_StrictFrozenModel):
    claim_id: str
    revision_no: int = Field(ge=1)

    _claim = field_validator("claim_id")(_canonical_text)


class CompilationChangeItem(_StrictFrozenModel):
    change_set_id: str
    change_item_id: str
    claim_id: str | None
    action: str
    decision: Literal["auto_applied", "approved", "rejected"]

    _text = field_validator("change_set_id", "change_item_id", "action")(
        _canonical_text
    )

    @field_validator("claim_id")
    @classmethod
    def _optional_claim(cls, value: str | None) -> str | None:
        return None if value is None else _canonical_text(value)


class CompilationManifest(_StrictFrozenModel):
    schema_version: Literal["028-minimal-v1"]
    space_id: str
    compiled_at: str
    files: tuple[CompilationArtifact, ...] = Field(min_length=1)
    change_set_ids: tuple[str, ...] = Field(min_length=1)
    blocking_review_ids: tuple[str, ...] = Field(min_length=1)
    base_snapshot_id: str | None
    base_manifest_hash: str | None
    target_claim_revisions: tuple[CompilationClaimRevision, ...]
    target_facts_hash: str
    change_items: tuple[CompilationChangeItem, ...] = Field(min_length=1)
    manifest_hash: str

    _space = field_validator("space_id")(_canonical_text)
    _compiled_at = field_validator("compiled_at")(_canonical_timestamp)
    _hash = field_validator("manifest_hash", "target_facts_hash")(_literal_sha256)

    @field_validator(
        "files",
        "change_set_ids",
        "blocking_review_ids",
        "target_claim_revisions",
        "change_items",
        mode="before",
    )
    @classmethod
    def _tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def _unique_entries(self) -> CompilationManifest:
        for values in (
            tuple(artifact.path for artifact in self.files),
            self.change_set_ids,
            self.blocking_review_ids,
            tuple(item.claim_id for item in self.target_claim_revisions),
            tuple(item.change_item_id for item in self.change_items),
        ):
            if len(values) != len(set(values)):
                raise ValueError("compilation manifest entries must be unique")
        for value in (*self.change_set_ids, *self.blocking_review_ids):
            _canonical_text(value)
        if (self.base_snapshot_id is None) != (self.base_manifest_hash is None):
            raise ValueError("base snapshot and manifest identities must be paired")
        if self.base_snapshot_id is not None:
            _canonical_text(self.base_snapshot_id)
        if self.base_manifest_hash is not None:
            _literal_sha256(self.base_manifest_hash)
        if {item.change_set_id for item in self.change_items} != set(
            self.change_set_ids
        ):
            raise ValueError("change item inventory must cover exact ChangeSets")
        return self


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseCLIError("duplicate_key", f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode_json(raw: bytes) -> object:
    try:
        return json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ReleaseCLIError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseCLIError("invalid_artifact", "artifact is not canonical JSON") from exc


def _read_json(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        raise ReleaseCLIError("unsafe_artifact_path", "artifact must be a regular file")
    try:
        return _decode_json(path.read_bytes())
    except OSError as exc:
        raise ReleaseCLIError("invalid_artifact", "artifact is not canonical JSON") from exc


def _safe_bundle_file(root: Path, relative: str) -> Path:
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    try:
        root_resolved = root.resolve(strict=True)
        candidate_resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ReleaseCLIError("unsafe_artifact_path", "artifact path is unavailable") from exc
    if candidate.is_symlink() or root_resolved not in candidate_resolved.parents:
        raise ReleaseCLIError("unsafe_artifact_path", "artifact escapes its sealed bundle")
    current = candidate
    while current != root:
        if current.is_symlink():
            raise ReleaseCLIError("unsafe_artifact_path", "artifact symlinks are forbidden")
        current = current.parent
    if not candidate.is_file():
        raise ReleaseCLIError("unsafe_artifact_path", "artifact must be a regular file")
    return candidate


def _item_count(raw: bytes, path: Path) -> int:
    if path.suffix == ".jsonl":
        return sum(1 for line in raw.splitlines() if line.strip())
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseCLIError("invalid_artifact", "counted artifact must be JSON") from exc
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict) and isinstance(value.get("items"), list):
        return len(value["items"])
    return 1


def _parse_compilation_manifest(raw: bytes) -> CompilationManifest:
    try:
        manifest = CompilationManifest.model_validate(_decode_json(raw))
    except ValidationError as exc:
        message = str(exc)
        code = "unsafe_artifact_path" if "artifact path" in message else "invalid_manifest"
        raise ReleaseCLIError(code, "compilation manifest schema is invalid") from exc
    payload = manifest.model_dump(mode="json", exclude={"manifest_hash"})
    if canonical_sha256(payload) != manifest.manifest_hash:
        raise ReleaseCLIError("compilation_manifest_mismatch", "manifest hash mismatch")
    return manifest


def load_compilation_manifest(path: str | Path) -> CompilationManifest:
    manifest_path = Path(path)
    manifest = _parse_compilation_manifest(_canonical_bytes(_read_json(manifest_path)))
    root = manifest_path.parent
    for entry in manifest.files:
        artifact_path = _safe_bundle_file(root, entry.path)
        raw = artifact_path.read_bytes()
        if (
            hashlib.sha256(raw).hexdigest() != entry.sha256
            or len(raw) != entry.size_bytes
            or _item_count(raw, artifact_path) != entry.item_count
        ):
            raise ReleaseCLIError(
                "compilation_artifact_mismatch",
                f"compiler artifact no longer matches: {entry.path}",
            )
    return manifest


def _verified_hashed_model(
    path: Path,
    model_type: type[_StrictFrozenModel],
    hash_field: str,
    error_code: str,
) -> _StrictFrozenModel:
    return _verified_hashed_model_raw(
        _canonical_bytes(_read_json(path)), model_type, hash_field, error_code
    )


def _verified_hashed_model_raw(
    raw: bytes,
    model_type: type[_StrictFrozenModel],
    hash_field: str,
    error_code: str,
) -> _StrictFrozenModel:
    try:
        value = model_type.model_validate(_decode_json(raw))
    except ValidationError as exc:
        raise ReleaseCLIError(error_code, "receipt schema is invalid") from exc
    payload = value.model_dump(mode="json", exclude={hash_field})
    if canonical_sha256(payload) != getattr(value, hash_field):
        raise ReleaseCLIError(error_code, "receipt hash mismatch")
    return value


def load_review_receipt(path: str | Path) -> ReviewReceipt:
    value = _verified_hashed_model(
        Path(path), ReviewReceipt, "receipt_hash", "review_receipt_mismatch"
    )
    assert isinstance(value, ReviewReceipt)
    return value


def _load_approval_receipt(path: str | Path) -> ApprovalReceipt:
    value = _verified_hashed_model(
        Path(path), ApprovalReceipt, "receipt_hash", "approval_receipt_mismatch"
    )
    assert isinstance(value, ApprovalReceipt)
    return value


def _load_release_manifest(path: str | Path) -> ReleaseManifest:
    return _load_release_manifest_raw(_canonical_bytes(_read_json(Path(path))))


def _load_release_manifest_raw(raw_bytes: bytes) -> ReleaseManifest:
    try:
        raw = _decode_json(raw_bytes)
        manifest = ReleaseManifest.model_validate_json(
            json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
        )
        verify_release_manifest(manifest)
    except (ValidationError, ReleaseManifestIntegrityError, TypeError, ValueError) as exc:
        raise ReleaseCLIError("release_manifest_mismatch", "release manifest is invalid") from exc
    return manifest


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ReleaseCLIError("duplicate_key", f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _decode_yaml(raw: bytes) -> object:
    try:
        return yaml.load(raw.decode("utf-8"), Loader=_UniqueKeyLoader)
    except ReleaseCLIError:
        raise
    except (UnicodeError, yaml.YAMLError) as exc:
        raise ReleaseCLIError("invalid_request", "request YAML is invalid") from exc


def _read_yaml(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        raise ReleaseCLIError("unsafe_artifact_path", "request must be a regular file")
    try:
        return _decode_yaml(path.read_bytes())
    except OSError as exc:
        raise ReleaseCLIError("invalid_request", "request YAML is invalid") from exc


def dump_yaml(value: Mapping[str, object]) -> str:
    return yaml.safe_dump(dict(value), allow_unicode=True, sort_keys=True)


def _write_json_exclusive(path: Path, value: object) -> None:
    if path.is_symlink():
        raise ReleaseCLIError("output_exists", "output path already exists")
    try:
        with path.open("x", encoding="utf-8") as output:
            output.write(_canonical_bytes(value).decode("utf-8"))
            output.write("\n")
    except FileExistsError as exc:
        raise ReleaseCLIError("output_exists", "output path already exists") from exc
    except OSError as exc:
        raise ReleaseCLIError("output_unavailable", "output could not be created") from exc


def _review_subject_binding(
    session: Session,
    scope: KnowledgeScope,
    review: ReviewItem,
) -> tuple[ChangeItem, ChangeSet]:
    change_item_id = (review.subject or {}).get("change_item_id")
    if not isinstance(change_item_id, str):
        raise ReleaseCLIError("review_binding_mismatch", "review lacks a ChangeItem")
    row = session.execute(
        select(ChangeItem, ChangeSet)
        .join(ChangeSet, ChangeSet.id == ChangeItem.change_set_id)
        .where(
            ChangeItem.id == change_item_id,
            ChangeSet.space_id == scope.space_id,
        )
    ).one_or_none()
    if row is None:
        raise ReleaseCLIError("review_binding_mismatch", "review ChangeItem is unavailable")
    return row[0], row[1]


def _exact_review_authorization(
    authorizer: ReviewAuthorizer,
    decision: ReviewDecision,
    *,
    scope: KnowledgeScope,
    compilation_manifest_hash: str,
) -> None:
    try:
        authorized = authorizer.authorize_review(
            space_id=scope.space_id,
            review_id=decision.review_id,
            principal=decision.principal,
            actor_type=decision.actor_type,
            compilation_manifest_hash=compilation_manifest_hash,
            authorization_receipt=decision.authorization_receipt,
        )
    except Exception as exc:
        raise ReleaseCLIError("review_authorization_failed", "review authorization failed") from exc
    expected = (
        "authorized",
        scope.space_id,
        decision.review_id,
        decision.principal,
        decision.actor_type,
        compilation_manifest_hash,
        decision.authorization_receipt,
    )
    observed = (
        authorized.outcome,
        authorized.space_id,
        authorized.review_id,
        authorized.principal,
        authorized.actor_type,
        authorized.compilation_manifest_hash,
        authorized.authorization_receipt,
    )
    if observed != expected:
        raise ReleaseCLIError("review_authorization_failed", "review authorization mismatch")


def apply_review_decisions(
    context: GovernanceContext,
    *,
    request_path: str | Path,
    compilation_manifest_path: str | Path,
    output_path: str | Path,
) -> ReviewReceipt:
    """Apply an exact complete human decision set; caller owns the transaction."""

    require_current_scope(context.session, context.scope)
    if context.review_authorizer is None:
        raise ReleaseCLIError("trusted_context_required", "review authorizer is unavailable")
    output = Path(output_path)
    if output.exists() or output.is_symlink():
        raise ReleaseCLIError("output_exists", "review receipt already exists")
    compilation = load_compilation_manifest(compilation_manifest_path)
    try:
        request = ReviewDecisionsRequest.model_validate(_read_yaml(Path(request_path)))
    except ValidationError as exc:
        raise ReleaseCLIError("invalid_review_request", "review request is invalid") from exc
    if (
        request.space_id != context.scope.space_id
        or compilation.space_id != context.scope.space_id
        or request.compilation_manifest_hash != compilation.manifest_hash
        or {decision.review_id for decision in request.decisions}
        != set(compilation.blocking_review_ids)
    ):
        raise ReleaseCLIError("review_request_mismatch", "review request binding mismatch")

    reviews = list(
        context.session.scalars(
            select(ReviewItem).where(
                ReviewItem.space_id == context.scope.space_id,
                ReviewItem.id.in_(compilation.blocking_review_ids),
            )
        )
    )
    if {review.id for review in reviews} != set(compilation.blocking_review_ids):
        raise ReleaseCLIError("review_coverage_incomplete", "blocking reviews are incomplete")
    review_by_id = {review.id: review for review in reviews}
    bindings: dict[str, tuple[ChangeItem, ChangeSet]] = {}
    for decision in request.decisions:
        review = review_by_id[decision.review_id]
        item, change_set = _review_subject_binding(
            context.session, context.scope, review
        )
        bindings[decision.review_id] = (item, change_set)
        if (
            review.status != "open"
            or decision.expected_version != review.updated_at.isoformat()
            or change_set.id not in compilation.change_set_ids
            or item.decision != "needs_review"
        ):
            raise ReleaseCLIError("review_stale", "review version or binding is stale")
        _exact_review_authorization(
            context.review_authorizer,
            decision,
            scope=context.scope,
            compilation_manifest_hash=compilation.manifest_hash,
        )
    if {binding[1].id for binding in bindings.values()} != set(
        compilation.change_set_ids
    ):
        raise ReleaseCLIError("changeset_coverage_incomplete", "ChangeSet coverage is incomplete")

    applied: list[AppliedReviewDecision] = []
    for decision in request.decisions:
        review = review_by_id[decision.review_id]
        item, change_set = bindings[decision.review_id]
        try:
            resolved = resolve_review(
                context.session,
                context.scope,
                review.review_key,
                decision.action,
                actor=decision.principal,
                reason=decision.reason,
                expected_version=decision.expected_version,
                request_id=decision.request_id,
            )
        except (ReviewDecisionConflict, ReviewPreconditionRequired, ReviewStale) as exc:
            raise ReleaseCLIError("review_stale", "review could not be resolved") from exc
        resolution = resolved.resolution or {}
        if (
            resolved.status != "resolved"
            or resolution.get("action") != decision.action
            or resolution.get("actor") != decision.principal
            or resolution.get("reason") != decision.reason
        ):
            raise ReleaseCLIError("review_resolution_mismatch", "review receipt mismatch")
        applied.append(
            AppliedReviewDecision(
                review_id=review.id,
                review_key=review.review_key,
                change_set_id=change_set.id,
                change_item_id=item.id,
                expected_version=decision.expected_version,
                action=decision.action,
                principal=decision.principal,
                actor_type=decision.actor_type,
                authorization_receipt=decision.authorization_receipt,
                reason=decision.reason,
                request_id=decision.request_id,
                resolved_at=str(resolution.get("at")),
            )
        )
    request_hash = canonical_sha256(request.model_dump(mode="json"))
    receipt_payload = {
        "schema_version": "review-receipt-v1",
        "space_id": context.scope.space_id,
        "compilation_manifest_hash": compilation.manifest_hash,
        "request_hash": request_hash,
        "change_set_ids": list(compilation.change_set_ids),
        "decisions": [decision.model_dump(mode="json") for decision in applied],
    }
    receipt = ReviewReceipt.model_validate(
        {**receipt_payload, "receipt_hash": canonical_sha256(receipt_payload)}
    )
    _write_json_exclusive(output, receipt.model_dump(mode="json"))
    return receipt


def _verify_review_completion(
    context: GovernanceContext,
    compilation: CompilationManifest,
    receipt: ReviewReceipt,
) -> None:
    if (
        receipt.space_id != context.scope.space_id
        or receipt.compilation_manifest_hash != compilation.manifest_hash
        or set(receipt.change_set_ids) != set(compilation.change_set_ids)
        or {decision.review_id for decision in receipt.decisions}
        != set(compilation.blocking_review_ids)
    ):
        raise ReleaseCLIError("review_receipt_mismatch", "review receipt binding mismatch")
    for decision in receipt.decisions:
        review = context.session.scalar(
            select(ReviewItem).where(
                ReviewItem.space_id == context.scope.space_id,
                ReviewItem.id == decision.review_id,
            )
        )
        if review is None:
            raise ReleaseCLIError("review_receipt_mismatch", "review is unavailable")
        item, change_set = _review_subject_binding(
            context.session, context.scope, review
        )
        resolution = review.resolution or {}
        events = resolution.get("events")
        if not isinstance(events, list):
            raise ReleaseCLIError(
                "review_receipt_mismatch", "review event history is unavailable"
            )
        matching_events = [
            event
            for event in events
            if isinstance(event, dict)
            and event.get("request_id") == decision.request_id
        ]
        if len(matching_events) != 1:
            raise ReleaseCLIError(
                "review_receipt_mismatch", "review event identity is not unique"
            )
        event = matching_events[0]
        expected_item_decision = "approved" if decision.action == "approve" else "rejected"
        if (
            review.review_key != decision.review_key
            or item.id != decision.change_item_id
            or change_set.id != decision.change_set_id
            or review.status != "resolved"
            or resolution.get("action") != decision.action
            or resolution.get("actor") != decision.principal
            or resolution.get("reason") != decision.reason
            or resolution.get("at") != decision.resolved_at
            or event.get("action") != decision.action
            or event.get("actor") != decision.principal
            or event.get("reason") != decision.reason
            or event.get("request_id") != decision.request_id
            or event.get("expected_version") != decision.expected_version
            or event.get("at") != decision.resolved_at
            or item.decision != expected_item_decision
        ):
            raise ReleaseCLIError("review_receipt_mismatch", "review resolution drifted")
        if context.review_authorizer is None:
            raise ReleaseCLIError(
                "trusted_context_required", "review authorizer is unavailable"
            )
        _exact_review_authorization(
            context.review_authorizer,
            ReviewDecision(
                review_id=decision.review_id,
                expected_version=decision.expected_version,
                action=decision.action,
                principal=decision.principal,
                actor_type=decision.actor_type,
                authorization_receipt=decision.authorization_receipt,
                reason=decision.reason,
                request_id=decision.request_id,
            ),
            scope=context.scope,
            compilation_manifest_hash=compilation.manifest_hash,
        )
    items = list(
        context.session.scalars(
            select(ChangeItem).where(
                ChangeItem.change_set_id.in_(compilation.change_set_ids)
            )
        )
    )
    if not items or any(
        item.decision not in {"auto_applied", "approved", "rejected"}
        for item in items
    ):
        raise ReleaseCLIError(
            "changeset_coverage_incomplete", "ChangeSet still has unresolved items"
        )
    if {item.change_set_id for item in items} != set(compilation.change_set_ids):
        raise ReleaseCLIError(
            "changeset_coverage_incomplete", "ChangeSet coverage is incomplete"
        )
    observed_items = {
        (
            item.change_set_id,
            item.id,
            item.claim_id,
            item.action,
            item.decision,
        )
        for item in items
    }
    sealed_items = {
        (
            item.change_set_id,
            item.change_item_id,
            item.claim_id,
            item.action,
            item.decision,
        )
        for item in compilation.change_items
    }
    if observed_items != sealed_items:
        raise ReleaseCLIError(
            "changeset_coverage_incomplete", "sealed ChangeItem inventory drifted"
        )


def _candidate_provenance_hash(
    compilation: CompilationManifest,
    *,
    review_receipt_hash: str,
    manifest_hash: str,
) -> str:
    return canonical_sha256(
        {
            "compilation_manifest_hash": compilation.manifest_hash,
            "review_receipt_hash": review_receipt_hash,
            "base_snapshot_id": compilation.base_snapshot_id,
            "base_manifest_hash": compilation.base_manifest_hash,
            "target_claim_revisions": [
                item.model_dump(mode="json")
                for item in compilation.target_claim_revisions
            ],
            "change_items": [
                item.model_dump(mode="json") for item in compilation.change_items
            ],
            "manifest_hash": manifest_hash,
        }
    )


def _review_request_semantics(
    request: ReviewDecisionsRequest,
) -> tuple[tuple[str, str, str, str, str, str, str, str], ...]:
    return tuple(
        (
            decision.review_id,
            decision.expected_version,
            decision.action,
            decision.principal,
            decision.actor_type,
            decision.authorization_receipt,
            decision.reason,
            decision.request_id,
        )
        for decision in request.decisions
    )


def _review_receipt_semantics(
    receipt: ReviewReceipt,
) -> tuple[tuple[str, str, str, str, str, str, str, str], ...]:
    return tuple(
        (
            decision.review_id,
            decision.expected_version,
            decision.action,
            decision.principal,
            decision.actor_type,
            decision.authorization_receipt,
            decision.reason,
            decision.request_id,
        )
        for decision in receipt.decisions
    )


def build_candidate(
    context: GovernanceContext,
    *,
    run_request_path: str | Path,
    review_receipt_path: str | Path,
    output_dir: str | Path,
) -> CandidateReceipt:
    """Verify sealed inputs and materialize a non-current approved-data candidate."""

    require_current_scope(context.session, context.scope)
    destination = Path(output_dir)
    if destination.exists() or destination.is_symlink():
        raise ReleaseCLIError("output_exists", "candidate output directory exists")
    request_file = Path(run_request_path)
    try:
        request = CandidateRunRequest.model_validate(_read_yaml(request_file))
    except ValidationError as exc:
        raise ReleaseCLIError("invalid_run_request", "candidate run request is invalid") from exc
    compilation_path = _safe_bundle_file(
        request_file.parent, request.compilation_manifest_path
    )
    compilation = load_compilation_manifest(compilation_path)
    receipt = load_review_receipt(review_receipt_path)
    if (
        request.space_id != context.scope.space_id
        or compilation.space_id != context.scope.space_id
        or request.compilation_manifest_hash != compilation.manifest_hash
        or request.review_receipt_hash != receipt.receipt_hash
    ):
        raise ReleaseCLIError("candidate_binding_mismatch", "candidate input binding mismatch")
    _verify_review_completion(context, compilation, receipt)
    parent = destination.parent
    if parent.is_symlink() or not parent.is_dir():
        raise ReleaseCLIError("unsafe_artifact_path", "candidate parent is unavailable")
    if context.session.get(ReleaseSnapshot, request.snapshot_id) is not None:
        raise ReleaseCLIError(
            "candidate_snapshot_exists", "candidate snapshot already exists"
        )
    current_before = context.session.scalar(
        select(CurrentRelease.snapshot_id).where(
            CurrentRelease.space_id == context.scope.space_id
        )
    )
    temporary = Path(tempfile.mkdtemp(prefix=".candidate-", dir=parent))
    destination_created = False
    try:
        with context.session.begin_nested():
            try:
                manifest = build_fresh_staging_candidate_manifest(
                    context.session,
                    context.scope,
                    snapshot_id=request.snapshot_id,
                    compiled_at=compilation.compiled_at,
                    expected_base_snapshot_id=compilation.base_snapshot_id,
                    expected_base_manifest_hash=compilation.base_manifest_hash,
                    target_claim_revisions=(
                        (item.claim_id, item.revision_no)
                        for item in compilation.target_claim_revisions
                    ),
                    authorized_change_items=(
                        (item.change_item_id, item.claim_id)
                        for item in compilation.change_items
                        if item.decision in {"auto_applied", "approved"}
                    ),
                    expected_target_facts_hash=compilation.target_facts_hash,
                    schema_version=request.knowledge_schema_version,
                    template_hashes=request.template_hashes,
                    model_plan_hash=request.model_plan_hash,
                )
            except ReleaseManifestBuildError as exc:
                raise ReleaseCLIError(
                    "candidate_build_failed", "candidate snapshot is unavailable"
                ) from exc
            current_after = context.session.scalar(
                select(CurrentRelease.snapshot_id).where(
                    CurrentRelease.space_id == context.scope.space_id
                )
            )
            if current_after != current_before:
                raise ReleaseCLIError(
                    "candidate_moved_current", "candidate moved CurrentRelease"
                )
            snapshot = context.session.get(ReleaseSnapshot, request.snapshot_id)
            if snapshot is None or snapshot.status != "building":
                raise ReleaseCLIError(
                    "candidate_build_failed", "candidate snapshot state is invalid"
                )
            snapshot.status = "published"
            snapshot.published_at = snapshot.projection_frozen_at
            context.session.flush()
            request_hash = canonical_sha256(request.model_dump(mode="json"))
            provenance_hash = _candidate_provenance_hash(
                compilation,
                review_receipt_hash=receipt.receipt_hash,
                manifest_hash=manifest.manifest_sha256,
            )
            candidate_payload = {
                "schema_version": "candidate-receipt-v1",
                "space_id": context.scope.space_id,
                "snapshot_id": request.snapshot_id,
                "compilation_manifest_hash": compilation.manifest_hash,
                "review_receipt_hash": receipt.receipt_hash,
                "manifest_hash": manifest.manifest_sha256,
                "provenance_hash": provenance_hash,
                "request_hash": request_hash,
            }
            candidate = CandidateReceipt.model_validate(
                {**candidate_payload, "receipt_hash": canonical_sha256(candidate_payload)}
            )
            _write_json_exclusive(
                temporary / "candidate-snapshot.json",
                candidate.model_dump(mode="json"),
            )
            _write_json_exclusive(
                temporary / "release-manifest.json",
                manifest.model_dump(mode="json"),
            )
            try:
                os.rename(temporary, destination)
                destination_created = True
            except OSError as exc:
                raise ReleaseCLIError(
                    "output_exists", "candidate output could not be sealed"
                ) from exc
    except Exception:
        if destination_created and destination.exists():
            shutil.rmtree(destination)
        raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return candidate


def approve_manifest(
    context: GovernanceContext,
    *,
    request_path: str | Path,
    manifest_path: str | Path,
    output_path: str | Path,
) -> ApprovalReceipt:
    """Persist and append approval only; caller owns the transaction."""

    require_current_scope(context.session, context.scope)
    if context.release_authorizer is None:
        raise ReleaseCLIError("trusted_context_required", "release authorizer is unavailable")
    output = Path(output_path)
    if output.exists() or output.is_symlink():
        raise ReleaseCLIError("output_exists", "approval receipt exists")
    try:
        request = ReleaseApprovalRequest.model_validate(_read_yaml(Path(request_path)))
    except ValidationError as exc:
        raise ReleaseCLIError("invalid_approval_request", "approval request is invalid") from exc
    manifest = _load_release_manifest(manifest_path)
    current = context.session.scalar(
        select(CurrentRelease.snapshot_id).where(
            CurrentRelease.space_id == context.scope.space_id
        )
    )
    if (
        request.space_id != context.scope.space_id
        or manifest.space_id != context.scope.space_id
        or request.snapshot_id != manifest.snapshot_id
        or request.manifest_hash != manifest.manifest_sha256
        or current != request.expected_current_snapshot_id
    ):
        raise ReleaseCLIError("approval_request_mismatch", "approval binding mismatch")
    try:
        persist_release_manifest(context.session, context.scope, manifest)
        approval = ReleaseApprovalService(
            context.session, context.release_authorizer
        ).approve(
            context.scope,
            snapshot_id=request.snapshot_id,
            manifest_hash=request.manifest_hash,
            actor=request.principal,
            actor_type=request.actor_type,
            authorization_receipt=request.authorization_receipt,
            reason=request.reason,
        )
    except (ReleaseApprovalError, ReleaseManifestPersistenceError) as exc:
        raise ReleaseCLIError("approval_failed", "approval service rejected request") from exc
    request_hash = canonical_sha256(request.model_dump(mode="json"))
    payload = {
        "schema_version": "approval-receipt-v1",
        "space_id": context.scope.space_id,
        "snapshot_id": approval.snapshot_id,
        "manifest_hash": approval.manifest_hash,
        "request_hash": request_hash,
        "approval_id": approval.id,
        "principal": approval.actor,
        "actor_type": approval.actor_type,
        "role": approval.role,
        "authorization_receipt": approval.authorization_receipt,
        "reason": approval.reason,
        "approved_at": _utc_iso(approval.approved_at),
        "created_at": _utc_iso(approval.created_at),
    }
    receipt = ApprovalReceipt.model_validate(
        {**payload, "receipt_hash": canonical_sha256(payload)}
    )
    _write_json_exclusive(output, receipt.model_dump(mode="json"))
    return receipt


def promote_approved(
    context: GovernanceContext,
    *,
    request_path: str | Path,
    manifest_path: str | Path,
    approval_receipt_path: str | Path,
    output_path: str | Path,
) -> ReleaseProof:
    """Revalidate exact artifacts and invoke RA3 CAS exactly once."""

    require_current_scope(context.session, context.scope)
    output = Path(output_path)
    if output.exists() or output.is_symlink():
        raise ReleaseCLIError("output_exists", "release proof exists")
    if output.parent.is_symlink() or not output.parent.is_dir():
        raise ReleaseCLIError("output_unavailable", "release proof parent is unavailable")
    try:
        request = ReleaseApprovalRequest.model_validate(_read_yaml(Path(request_path)))
    except ValidationError as exc:
        raise ReleaseCLIError("invalid_approval_request", "approval request is invalid") from exc
    manifest = _load_release_manifest(manifest_path)
    approval = _load_approval_receipt(approval_receipt_path)
    request_hash = canonical_sha256(request.model_dump(mode="json"))
    if (
        request.space_id != context.scope.space_id
        or manifest.space_id != context.scope.space_id
        or approval.space_id != context.scope.space_id
        or request.snapshot_id != manifest.snapshot_id
        or approval.snapshot_id != manifest.snapshot_id
        or request.manifest_hash != manifest.manifest_sha256
        or approval.manifest_hash != manifest.manifest_sha256
        or approval.request_hash != request_hash
        or approval.principal != request.principal
        or approval.actor_type != request.actor_type
        or approval.role != "release_approver"
        or approval.authorization_receipt != request.authorization_receipt
        or approval.reason != request.reason
    ):
        raise ReleaseCLIError("promotion_binding_mismatch", "promotion artifacts mismatch")
    persisted_approval = context.session.scalar(
        select(ReleaseApproval).where(
            ReleaseApproval.space_id == approval.space_id,
            ReleaseApproval.space_id == context.scope.space_id,
            ReleaseApproval.id == approval.approval_id,
            ReleaseApproval.snapshot_id == manifest.snapshot_id,
            ReleaseApproval.manifest_hash == manifest.manifest_sha256,
            ReleaseApproval.actor == approval.principal,
            ReleaseApproval.actor_type == approval.actor_type,
            ReleaseApproval.role == approval.role,
            ReleaseApproval.authorization_receipt == approval.authorization_receipt,
            ReleaseApproval.reason == approval.reason,
        )
    )
    if (
        persisted_approval is None
        or _utc_iso(persisted_approval.approved_at) != approval.approved_at
        or _utc_iso(persisted_approval.created_at) != approval.created_at
    ):
        raise ReleaseCLIError(
            "promotion_binding_mismatch", "approval receipt is not persisted and exact"
        )
    with context.session.begin_nested():
        result = ReleaseAuthorityService(context.session).promote(
            context.scope,
            snapshot_id=request.snapshot_id,
            manifest_hash=request.manifest_hash,
            expected_current_snapshot_id=request.expected_current_snapshot_id,
            reason=request.reason,
        )
        if isinstance(result, ReleaseActivationFailure):
            raise ReleaseCLIError(result.code, "release CAS failed")
        audit = context.session.get(ReleaseActivationAudit, result.audit_id)
        if audit is None:
            raise ReleaseCLIError("promotion_binding_mismatch", "release audit is missing")
        payload = {
            "schema_version": "release-proof-v1",
            "action": "promote",
            "space_id": context.scope.space_id,
            "snapshot_id": result.snapshot_id,
            "manifest_hash": result.manifest_hash,
            "request_hash": request_hash,
            "approval_receipt_hash": approval.receipt_hash,
            "previous_snapshot_id": result.previous_snapshot_id,
            "audit_id": result.audit_id,
            "approval_id": approval.approval_id,
            "principal": request.principal,
            "reason": request.reason,
            "activated_at": _utc_iso(audit.activated_at),
            "audit_created_at": _utc_iso(audit.created_at),
        }
        proof = ReleaseProof.model_validate(
            {**payload, "proof_hash": canonical_sha256(payload)}
        )
        _write_json_exclusive(output, proof.model_dump(mode="json"))
    return proof


def _load_candidate_receipt(path: Path) -> CandidateReceipt:
    value = _verified_hashed_model(
        path, CandidateReceipt, "receipt_hash", "candidate_receipt_mismatch"
    )
    assert isinstance(value, CandidateReceipt)
    return value


def _load_release_proof(path: Path) -> ReleaseProof:
    value = _verified_hashed_model(
        path, ReleaseProof, "proof_hash", "release_proof_mismatch"
    )
    assert isinstance(value, ReleaseProof)
    return value


def _load_serving_proof(path: Path) -> ServingProof:
    value = _verified_hashed_model(
        path, ServingProof, "proof_hash", "serving_proof_mismatch"
    )
    assert isinstance(value, ServingProof)
    return value


def _contained_artifact(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    try:
        relative = candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ReleaseCLIError(
            "unsafe_artifact_path", "artifact must be a regular file inside the run"
        ) from exc
    if candidate.is_symlink() or not candidate.is_file():
        raise ReleaseCLIError("unsafe_artifact_path", "artifact is not a regular file")
    SealedArtifact._safe_path(relative.as_posix())
    return candidate


def _unique_run_artifact(root: Path, basename: str) -> Path:
    matches = [path for path in root.rglob(basename) if path.is_file()]
    if len(matches) != 1:
        raise ReleaseCLIError(
            "artifact_chain_incomplete", f"expected exactly one {basename}"
        )
    return _contained_artifact(root, matches[0])


def _artifact_item_count(path: Path, raw: bytes) -> int:
    if path.suffix == ".jsonl":
        return sum(1 for line in raw.splitlines() if line.strip())
    if path.suffix == ".json":
        try:
            value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReleaseCLIError("invalid_artifact", "artifact JSON is invalid") from exc
        return len(value) if isinstance(value, list) else 1
    return 1


def _seal_chain_paths(root: Path) -> dict[str, Path]:
    return {
        name: _unique_run_artifact(root, name)
        for name in (
            "compilation-manifest.json",
            "review-decisions.yaml",
            "review-receipt.json",
            "run-request.yaml",
            "candidate-snapshot.json",
            "release-manifest.json",
            "release-approval-request.yaml",
            "approval-receipt.json",
            "release-proof.json",
            "metrics.json",
            "serving-proof.json",
        )
    }


def _expected_serving_facts(
    manifest: ReleaseManifest,
) -> tuple[CanonicalServingFact, ...]:
    facts = []
    for fact in manifest.facts:
        payload = fact.model_dump(
            mode="python", exclude={"space_id", "snapshot_id", "evidence"}
        )
        evidence = tuple(
            item.model_dump(mode="python") | {"kind": "document"}
            for item in fact.evidence
        )
        facts.append(
            CanonicalServingFact.model_validate(payload | {"evidence": evidence})
        )
    return tuple(
        sorted(
            facts,
            key=_serving_fact_order_key,
        )
    )


def _serving_fact_order_key(
    fact: CanonicalServingFact,
) -> tuple[str, str, str, date, date, str, int]:
    return (
        fact.product_id,
        fact.product_version_id,
        fact.predicate,
        fact.effective_from or date.min,
        fact.effective_to or date.max,
        fact.claim_id,
        fact.revision_no,
    )


def _actual_serving_hashes(
    result: ApprovedSnapshotResult,
) -> tuple[str, str, str]:
    facts = result.facts
    facts_hash = canonical_sha256(
        [item.model_dump(mode="json") for item in facts]
    )
    evidence_hash = canonical_sha256(
        [
            {
                "claim_id": fact.claim_id,
                "revision_no": fact.revision_no,
                "evidence": [item.model_dump(mode="json") for item in fact.evidence],
            }
            for fact in facts
        ]
    )
    ordering_hash = canonical_sha256(
        [
            {
                "position": position,
                "claim_id": fact.claim_id,
                "revision_no": fact.revision_no,
                "predicate": fact.predicate,
            }
            for position, fact in enumerate(facts)
        ]
    )
    return facts_hash, evidence_hash, ordering_hash


def _serving_evidence_hash(manifest: ReleaseManifest) -> str:
    return canonical_sha256(
        [
            {
                "claim_id": fact.claim_id,
                "revision_no": fact.revision_no,
                "evidence": [item.model_dump(mode="json") for item in fact.evidence],
            }
            for fact in manifest.facts
        ]
    )


def _serving_ordering_hash(manifest: ReleaseManifest) -> str:
    return canonical_sha256(
        [
            {
                "position": position,
                "claim_id": fact.claim_id,
                "revision_no": fact.revision_no,
                "predicate": fact.predicate,
            }
            for position, fact in enumerate(manifest.facts)
        ]
    )


def _verify_governance_chain(
    context: GovernanceContext,
    *,
    paths: Mapping[str, Path],
    raw_files: Mapping[str, bytes],
    compilation: CompilationManifest,
    release_proof: ReleaseProof,
    serving_proof: ServingProof,
) -> ReleaseManifest:
    def raw(name: str) -> bytes:
        try:
            return raw_files[paths[name].as_posix()]
        except KeyError as exc:
            raise ReleaseCLIError(
                "artifact_chain_incomplete", f"sealed bytes are missing: {name}"
            ) from exc

    try:
        review_request = ReviewDecisionsRequest.model_validate(
            _decode_yaml(raw("review-decisions.yaml"))
        )
    except ValidationError as exc:
        raise ReleaseCLIError(
            "artifact_chain_mismatch", "review request is invalid"
        ) from exc
    review_receipt = _verified_hashed_model_raw(
        raw("review-receipt.json"),
        ReviewReceipt,
        "receipt_hash",
        "review_receipt_mismatch",
    )
    assert isinstance(review_receipt, ReviewReceipt)
    try:
        run_request = CandidateRunRequest.model_validate(
            _decode_yaml(raw("run-request.yaml"))
        )
    except ValidationError as exc:
        raise ReleaseCLIError(
            "artifact_chain_mismatch", "candidate request is invalid"
        ) from exc
    candidate = _verified_hashed_model_raw(
        raw("candidate-snapshot.json"),
        CandidateReceipt,
        "receipt_hash",
        "candidate_receipt_mismatch",
    )
    assert isinstance(candidate, CandidateReceipt)
    manifest = _load_release_manifest_raw(raw("release-manifest.json"))
    try:
        approval_request = ReleaseApprovalRequest.model_validate(
            _decode_yaml(raw("release-approval-request.yaml"))
        )
    except ValidationError as exc:
        raise ReleaseCLIError(
            "artifact_chain_mismatch", "approval request is invalid"
        ) from exc
    approval = _verified_hashed_model_raw(
        raw("approval-receipt.json"),
        ApprovalReceipt,
        "receipt_hash",
        "approval_receipt_mismatch",
    )
    assert isinstance(approval, ApprovalReceipt)
    review_request_hash = canonical_sha256(review_request.model_dump(mode="json"))
    run_request_hash = canonical_sha256(run_request.model_dump(mode="json"))
    approval_request_hash = canonical_sha256(approval_request.model_dump(mode="json"))
    _verify_review_completion(context, compilation, review_receipt)
    expected_provenance_hash = _candidate_provenance_hash(
        compilation,
        review_receipt_hash=review_receipt.receipt_hash,
        manifest_hash=manifest.manifest_sha256,
    )
    if candidate.provenance_hash != expected_provenance_hash:
        raise ReleaseCLIError(
            "candidate_receipt_mismatch", "candidate provenance is not exact"
        )
    expected_compilation_path = paths["compilation-manifest.json"].relative_to(
        paths["run-request.yaml"].parent
    ).as_posix()
    if (
        compilation.space_id != context.scope.space_id
        or review_request.space_id != context.scope.space_id
        or _review_request_semantics(review_request)
        != _review_receipt_semantics(review_receipt)
        or review_request.compilation_manifest_hash != compilation.manifest_hash
        or review_receipt.compilation_manifest_hash != compilation.manifest_hash
        or review_receipt.request_hash != review_request_hash
        or run_request.space_id != context.scope.space_id
        or run_request.compilation_manifest_path != expected_compilation_path
        or run_request.compilation_manifest_hash != compilation.manifest_hash
        or run_request.review_receipt_hash != review_receipt.receipt_hash
        or run_request.snapshot_id != candidate.snapshot_id
        or run_request.snapshot_id != manifest.snapshot_id
        or run_request.knowledge_schema_version != manifest.schema_version
        or run_request.template_hashes != manifest.template_hashes
        or run_request.model_plan_hash != manifest.model_plan_hash
        or candidate.space_id != context.scope.space_id
        or candidate.compilation_manifest_hash != compilation.manifest_hash
        or candidate.review_receipt_hash != review_receipt.receipt_hash
        or candidate.request_hash != run_request_hash
        or candidate.snapshot_id != manifest.snapshot_id
        or candidate.manifest_hash != manifest.manifest_sha256
        or approval_request.space_id != context.scope.space_id
        or approval_request.snapshot_id != manifest.snapshot_id
        or approval_request.manifest_hash != manifest.manifest_sha256
        or approval_request.principal != approval.principal
        or approval_request.actor_type != approval.actor_type
        or approval_request.authorization_receipt != approval.authorization_receipt
        or approval_request.reason != approval.reason
        or approval_request.expected_current_snapshot_id
        != release_proof.previous_snapshot_id
        or approval.snapshot_id != manifest.snapshot_id
        or approval.space_id != context.scope.space_id
        or approval.manifest_hash != manifest.manifest_sha256
        or approval.request_hash != approval_request_hash
        or release_proof.snapshot_id != manifest.snapshot_id
        or release_proof.space_id != context.scope.space_id
        or release_proof.manifest_hash != manifest.manifest_sha256
        or release_proof.request_hash != approval_request_hash
        or release_proof.approval_receipt_hash != approval.receipt_hash
        or release_proof.action != "promote"
        or release_proof.approval_id != approval.approval_id
        or release_proof.principal != approval.principal
        or release_proof.reason != approval.reason
    ):
        raise ReleaseCLIError("artifact_chain_mismatch", "governance chain drifted")
    approval_row = context.session.scalar(
        select(ReleaseApproval).where(
            ReleaseApproval.space_id == approval.space_id,
            ReleaseApproval.space_id == context.scope.space_id,
            ReleaseApproval.id == approval.approval_id,
            ReleaseApproval.snapshot_id == approval.snapshot_id,
            ReleaseApproval.manifest_hash == approval.manifest_hash,
            ReleaseApproval.actor == approval.principal,
            ReleaseApproval.actor_type == approval.actor_type,
            ReleaseApproval.role == approval.role,
            ReleaseApproval.authorization_receipt == approval.authorization_receipt,
            ReleaseApproval.reason == approval.reason,
        )
    )
    if (
        approval_row is None
        or _utc_iso(approval_row.approved_at) != approval.approved_at
        or _utc_iso(approval_row.created_at) != approval.created_at
    ):
        raise ReleaseCLIError(
            "approval_receipt_mismatch", "approval receipt is not DB exact"
        )
    if context.approved_snapshot_reader is None:
        raise ReleaseCLIError(
            "trusted_context_required", "approved snapshot reader is unavailable"
        )
    actual_human = context.approved_snapshot_reader.read_current(context.scope)
    actual_mcp = context.approved_snapshot_reader.read_current(context.scope)
    if not isinstance(actual_human, ApprovedSnapshotResult) or not isinstance(
        actual_mcp, ApprovedSnapshotResult
    ):
        raise ReleaseCLIError("serving_proof_mismatch", "approved reader failed")
    expected_facts = _expected_serving_facts(manifest)
    human_facts = actual_human.facts
    mcp_facts = actual_mcp.facts
    expected_approved_at = datetime.fromisoformat(approval.approved_at)
    facts_hash, evidence_hash, ordering_hash = _actual_serving_hashes(actual_human)
    readers = (serving_proof.human_reader, serving_proof.mcp_reader)
    if (
        serving_proof.space_id != context.scope.space_id
        or serving_proof.snapshot_id != manifest.snapshot_id
        or serving_proof.manifest_hash != manifest.manifest_sha256
        or actual_human.snapshot_id != manifest.snapshot_id
        or actual_human.manifest_hash != manifest.manifest_sha256
        or actual_mcp.snapshot_id != manifest.snapshot_id
        or actual_mcp.manifest_hash != manifest.manifest_sha256
        or actual_human.approval_principal != approval.principal
        or actual_mcp.approval_principal != approval.principal
        or actual_human.approved_at != expected_approved_at
        or actual_mcp.approved_at != expected_approved_at
        or actual_human.read_model_version != manifest.read_model_version
        or actual_mcp.read_model_version != manifest.read_model_version
        or actual_human != actual_mcp
        or human_facts != expected_facts
        or mcp_facts != expected_facts
        or readers[0] != readers[1]
        or any(reader.snapshot_id != manifest.snapshot_id for reader in readers)
        or any(reader.manifest_hash != manifest.manifest_sha256 for reader in readers)
        or any(reader.fact_count != manifest.facts_digest.count for reader in readers)
        or any(reader.facts_hash != facts_hash for reader in readers)
        or any(reader.evidence_hash != evidence_hash for reader in readers)
        or any(reader.ordering_hash != ordering_hash for reader in readers)
    ):
        raise ReleaseCLIError("serving_proof_mismatch", "reader proof drifted")
    current = context.session.get(CurrentRelease, (context.scope.space_id, "current"))
    record = context.session.scalar(
        select(ReleaseManifestRecord).where(
            ReleaseManifestRecord.space_id == context.scope.space_id,
            ReleaseManifestRecord.snapshot_id == manifest.snapshot_id,
            ReleaseManifestRecord.manifest_hash == manifest.manifest_sha256,
        )
    )
    audit = context.session.scalar(
        select(ReleaseActivationAudit).where(
            ReleaseActivationAudit.space_id == context.scope.space_id,
            ReleaseActivationAudit.id == release_proof.audit_id,
            ReleaseActivationAudit.kind == "promote",
            ReleaseActivationAudit.target_snapshot_id == manifest.snapshot_id,
            ReleaseActivationAudit.manifest_hash == manifest.manifest_sha256,
            ReleaseActivationAudit.approval_id == approval.approval_id,
            ReleaseActivationAudit.actor == release_proof.principal,
            ReleaseActivationAudit.reason == release_proof.reason,
        )
    )
    if (
        current is None
        or current.snapshot_id != manifest.snapshot_id
        or record is None
        or audit is None
        or audit.from_snapshot_id != release_proof.previous_snapshot_id
        or _utc_iso(audit.activated_at) != release_proof.activated_at
        or _utc_iso(audit.created_at) != release_proof.audit_created_at
    ):
        raise ReleaseCLIError("release_proof_mismatch", "release is not current and exact")
    return manifest


@contextmanager
def _exclusive_seal_lock(root: Path) -> Iterator[None]:
    lock_path = root.parent / f".{root.name}.seal.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ReleaseCLIError("seal_lock_unavailable", "seal lock is unavailable") from exc
    acquired = False
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            acquired = True
        except OSError as exc:
            raise ReleaseCLIError(
                "seal_lock_unavailable", "seal lock cannot be acquired"
            ) from exc
        yield
    finally:
        try:
            if acquired:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            os.close(descriptor)


def _stable_read_at(root: Path, relative: str) -> bytes:
    parts = PurePosixPath(relative).parts
    root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    try:
        current = os.open(root, root_flags | no_follow)
        descriptors.append(current)
        for part in parts[:-1]:
            current = os.open(part, root_flags | no_follow, dir_fd=current)
            descriptors.append(current)
        file_descriptor = os.open(parts[-1], os.O_RDONLY | no_follow, dir_fd=current)
        descriptors.append(file_descriptor)
        before = os.fstat(file_descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(file_descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ReleaseCLIError(
                "artifact_changed_during_seal", "artifact changed while being read"
            )
        raw = b"".join(chunks)
        if len(raw) != after.st_size:
            raise ReleaseCLIError(
                "artifact_changed_during_seal", "artifact read was incomplete"
            )
        return raw
    except ReleaseCLIError:
        raise
    except OSError as exc:
        raise ReleaseCLIError(
            "artifact_changed_during_seal", "artifact could not be read stably"
        ) from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _scan_sealed_files(
    root: Path,
    allowed_paths: set[str],
    *,
    output: Path,
) -> tuple[tuple[SealedArtifact, ...], dict[str, bytes]]:
    observed: list[SealedArtifact] = []
    raw_files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ReleaseCLIError("unsafe_artifact_path", "run contains a symlink")
        if not path.is_file() or path == output:
            continue
        relative = path.relative_to(root).as_posix()
        try:
            SealedArtifact._safe_path(relative)
        except ValueError as exc:
            raise ReleaseCLIError(
                "unsafe_artifact_path", "run contains a sensitive or unsafe path"
            ) from exc
        if relative not in allowed_paths:
            raise ReleaseCLIError(
                "unexpected_artifact", f"run contains an unbound artifact: {relative}"
            )
        raw = _stable_read_at(root, relative)
        raw_files[path.as_posix()] = raw
        observed.append(
            SealedArtifact(
                path=relative,
                sha256=hashlib.sha256(raw).hexdigest(),
                size_bytes=len(raw),
                item_count=_artifact_item_count(path, raw),
            )
        )
    if {item.path for item in observed} != allowed_paths:
        raise ReleaseCLIError("artifact_chain_incomplete", "artifact set changed")
    return tuple(observed), raw_files


def _seal_run_artifacts_locked(
    context: GovernanceContext,
    *,
    directory: str | Path,
    compilation_manifest_path: str | Path,
    release_proof_path: str | Path,
    serving_proof_path: str | Path,
) -> ArtifactManifest:
    """Revalidate the complete release chain and create its final file exactly once."""

    require_current_scope(context.session, context.scope)
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ReleaseCLIError("unsafe_artifact_path", "run directory is unavailable")
    output = root / "artifact-manifest.json"
    if output.exists() or output.is_symlink():
        raise ReleaseCLIError("artifact_manifest_exists", "artifact manifest already exists")
    supplied_compilation = _contained_artifact(root, compilation_manifest_path)
    supplied_release = _contained_artifact(root, release_proof_path)
    supplied_serving = _contained_artifact(root, serving_proof_path)
    paths = _seal_chain_paths(root)
    if (
        supplied_compilation.resolve() != paths["compilation-manifest.json"].resolve()
        or supplied_release.resolve() != paths["release-proof.json"].resolve()
        or supplied_serving.resolve() != paths["serving-proof.json"].resolve()
    ):
        raise ReleaseCLIError("artifact_chain_mismatch", "supplied chain path mismatch")
    compilation_path = paths["compilation-manifest.json"]
    release_path = paths["release-proof.json"]
    serving_path = paths["serving-proof.json"]
    compilation_relative = compilation_path.relative_to(root).as_posix()
    bootstrap_compilation_raw = _stable_read_at(root, compilation_relative)
    compilation = _parse_compilation_manifest(bootstrap_compilation_raw)
    allowed_paths = {
        path.relative_to(root).as_posix() for path in paths.values()
    }
    compilation_parent = PurePosixPath(compilation_relative).parent
    allowed_paths.update(
        (compilation_parent / item.path).as_posix() for item in compilation.files
    )
    files, raw_files = _scan_sealed_files(root, allowed_paths, output=output)
    if not files:
        raise ReleaseCLIError("artifact_chain_incomplete", "run has no artifacts")
    if raw_files[compilation_path.as_posix()] != bootstrap_compilation_raw:
        raise ReleaseCLIError(
            "artifact_changed_during_seal", "compilation changed during stable capture"
        )
    for entry in compilation.files:
        relative = (compilation_parent / entry.path).as_posix()
        artifact_path = root / relative
        raw = raw_files[artifact_path.as_posix()]
        if (
            hashlib.sha256(raw).hexdigest() != entry.sha256
            or len(raw) != entry.size_bytes
            or _item_count(raw, artifact_path) != entry.item_count
        ):
            raise ReleaseCLIError(
                "compilation_artifact_mismatch",
                f"compiler artifact no longer matches: {entry.path}",
            )
    release_proof = _verified_hashed_model_raw(
        raw_files[release_path.as_posix()],
        ReleaseProof,
        "proof_hash",
        "release_proof_mismatch",
    )
    serving_proof = _verified_hashed_model_raw(
        raw_files[serving_path.as_posix()],
        ServingProof,
        "proof_hash",
        "serving_proof_mismatch",
    )
    assert isinstance(release_proof, ReleaseProof)
    assert isinstance(serving_proof, ServingProof)
    manifest = _verify_governance_chain(
        context,
        paths=paths,
        raw_files=raw_files,
        compilation=compilation,
        release_proof=release_proof,
        serving_proof=serving_proof,
    )
    payload = {
        "schema_version": "artifact-manifest-v1",
        "space_id": context.scope.space_id,
        "snapshot_id": manifest.snapshot_id,
        "release_manifest_hash": manifest.manifest_sha256,
        "compilation_manifest_hash": compilation.manifest_hash,
        "release_proof_hash": release_proof.proof_hash,
        "serving_proof_hash": serving_proof.proof_hash,
        "file_count": len(files),
        "files": [item.model_dump(mode="json") for item in files],
    }
    artifact_manifest = ArtifactManifest.model_validate(
        {**payload, "manifest_hash": canonical_sha256(payload)}
    )
    if _scan_sealed_files(root, allowed_paths, output=output) != (files, raw_files):
        raise ReleaseCLIError(
            "artifact_changed_during_seal", "artifact changed before final create"
        )
    try:
        _write_json_exclusive(output, artifact_manifest.model_dump(mode="json"))
        if _scan_sealed_files(root, allowed_paths, output=output) != (files, raw_files):
            raise ReleaseCLIError(
                "artifact_changed_during_seal", "artifact changed during final create"
            )
    except Exception:
        try:
            output.unlink()
        except FileNotFoundError:
            pass
        raise
    return artifact_manifest


def seal_run_artifacts(
    context: GovernanceContext,
    *,
    directory: str | Path,
    compilation_manifest_path: str | Path,
    release_proof_path: str | Path,
    serving_proof_path: str | Path,
) -> ArtifactManifest:
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ReleaseCLIError("unsafe_artifact_path", "run directory is unavailable")
    with _exclusive_seal_lock(root):
        return _seal_run_artifacts_locked(
            context,
            directory=root,
            compilation_manifest_path=compilation_manifest_path,
            release_proof_path=release_proof_path,
            serving_proof_path=serving_proof_path,
        )


def _required_path(parser: argparse.ArgumentParser, flag: str) -> None:
    parser.add_argument(flag, required=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="insurance_harness.knowledge.release_cli")
    commands = parser.add_subparsers(dest="command", required=True)

    apply_review = commands.add_parser("apply-review-decisions")
    for flag in ("--request", "--compilation-manifest", "--output"):
        _required_path(apply_review, flag)

    candidate = commands.add_parser("build-candidate")
    for flag in ("--run-request", "--review-receipt", "--output-dir"):
        _required_path(candidate, flag)

    approve = commands.add_parser("approve-manifest")
    for flag in ("--request", "--manifest", "--output"):
        _required_path(approve, flag)

    promote = commands.add_parser("promote-approved")
    for flag in (
        "--request",
        "--manifest",
        "--approval-receipt",
        "--output",
    ):
        _required_path(promote, flag)

    seal = commands.add_parser("seal-run-artifacts")
    for flag in (
        "--directory",
        "--compilation-manifest",
        "--release-proof",
        "--serving-proof",
    ):
        _required_path(seal, flag)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _build_parser().parse_args(argv)
    sys.stderr.write(
        json.dumps(
            {"code": "trusted_context_required", "status": "blocked"},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 2


if __name__ == "__main__":  # pragma: no cover - exercised through module execution
    raise SystemExit(main())
