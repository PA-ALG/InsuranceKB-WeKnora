"""Human-controlled governance CLI for OpenSpec 029 release authority.

The repository has no production composition root for the 028 compiler bundle or a
production ``ReleaseAuthorizer``.  Consequently ``python -m`` without an explicitly
injected trusted context is a typed, zero-write terminal block.  Requests and receipts
can never self-attest authority, and this module does not discover a factory from the
environment or dynamically import one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
    build_staging_candidate_manifest,
)
from insurance_harness.knowledge.release_manifest import (
    ReleaseManifest,
    ReleaseManifestIntegrityError,
    verify_release_manifest,
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
    authorization_receipt: str
    approved_at: str
    receipt_hash: str


class ReleaseProof(_StrictFrozenModel):
    schema_version: Literal["release-proof-v1"] = "release-proof-v1"
    space_id: str
    snapshot_id: str
    manifest_hash: str
    request_hash: str
    approval_receipt_hash: str
    previous_snapshot_id: str | None
    audit_id: str
    proof_hash: str


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


class CompilationManifest(_StrictFrozenModel):
    schema_version: Literal["028-minimal-v1"]
    space_id: str
    files: tuple[CompilationArtifact, ...] = Field(min_length=1)
    change_set_ids: tuple[str, ...] = Field(min_length=1)
    blocking_review_ids: tuple[str, ...] = Field(min_length=1)
    manifest_hash: str

    _space = field_validator("space_id")(_canonical_text)
    _hash = field_validator("manifest_hash")(_literal_sha256)

    @field_validator("files", "change_set_ids", "blocking_review_ids", mode="before")
    @classmethod
    def _tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def _unique_entries(self) -> CompilationManifest:
        for values in (
            tuple(artifact.path for artifact in self.files),
            self.change_set_ids,
            self.blocking_review_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("compilation manifest entries must be unique")
        for value in (*self.change_set_ids, *self.blocking_review_ids):
            _canonical_text(value)
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


def _read_json(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        raise ReleaseCLIError("unsafe_artifact_path", "artifact must be a regular file")
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ReleaseCLIError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
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


def load_compilation_manifest(path: str | Path) -> CompilationManifest:
    manifest_path = Path(path)
    try:
        manifest = CompilationManifest.model_validate(_read_json(manifest_path))
    except ValidationError as exc:
        message = str(exc)
        code = "unsafe_artifact_path" if "artifact path" in message else "invalid_manifest"
        raise ReleaseCLIError(code, "compilation manifest schema is invalid") from exc
    payload = manifest.model_dump(mode="json", exclude={"manifest_hash"})
    if canonical_sha256(payload) != manifest.manifest_hash:
        raise ReleaseCLIError("compilation_manifest_mismatch", "manifest hash mismatch")
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
    try:
        value = model_type.model_validate(_read_json(path))
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
    try:
        raw = _read_json(Path(path))
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


def _read_yaml(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        raise ReleaseCLIError("unsafe_artifact_path", "request must be a regular file")
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except ReleaseCLIError:
        raise
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
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
        expected_item_decision = "approved" if decision.action == "approve" else "rejected"
        if (
            review.review_key != decision.review_key
            or item.id != decision.change_item_id
            or change_set.id != decision.change_set_id
            or review.status != "resolved"
            or resolution.get("action") != decision.action
            or resolution.get("actor") != decision.principal
            or resolution.get("reason") != decision.reason
            or item.decision != expected_item_decision
        ):
            raise ReleaseCLIError("review_receipt_mismatch", "review resolution drifted")
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
    current_before = context.session.scalar(
        select(CurrentRelease.snapshot_id).where(
            CurrentRelease.space_id == context.scope.space_id
        )
    )
    try:
        manifest = build_staging_candidate_manifest(
            context.session,
            context.scope,
            snapshot_id=request.snapshot_id,
            schema_version=request.knowledge_schema_version,
            template_hashes=request.template_hashes,
            model_plan_hash=request.model_plan_hash,
        )
    except Exception as exc:
        raise ReleaseCLIError(
            "candidate_build_failed", "candidate snapshot is unavailable"
        ) from exc
    current_after = context.session.scalar(
        select(CurrentRelease.snapshot_id).where(
            CurrentRelease.space_id == context.scope.space_id
        )
    )
    if current_after != current_before:
        raise ReleaseCLIError("candidate_moved_current", "candidate moved CurrentRelease")
    snapshot = context.session.scalar(
        select(ReleaseSnapshot).where(
            ReleaseSnapshot.space_id == context.scope.space_id,
            ReleaseSnapshot.id == request.snapshot_id,
        )
    )
    if snapshot is None or snapshot.status != "building":
        raise ReleaseCLIError("candidate_build_failed", "candidate snapshot state is invalid")
    snapshot.status = "published"
    context.session.flush()

    request_hash = canonical_sha256(request.model_dump(mode="json"))
    candidate_payload = {
        "schema_version": "candidate-receipt-v1",
        "space_id": context.scope.space_id,
        "snapshot_id": request.snapshot_id,
        "compilation_manifest_hash": compilation.manifest_hash,
        "review_receipt_hash": receipt.receipt_hash,
        "manifest_hash": manifest.manifest_sha256,
        "request_hash": request_hash,
    }
    candidate = CandidateReceipt.model_validate(
        {**candidate_payload, "receipt_hash": canonical_sha256(candidate_payload)}
    )
    parent = destination.parent
    if parent.is_symlink() or not parent.is_dir():
        raise ReleaseCLIError("unsafe_artifact_path", "candidate parent is unavailable")
    temporary = Path(tempfile.mkdtemp(prefix=".candidate-", dir=parent))
    try:
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
        except OSError as exc:
            raise ReleaseCLIError("output_exists", "candidate output could not be sealed") from exc
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
        "authorization_receipt": approval.authorization_receipt,
        "approved_at": approval.approved_at.isoformat(),
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
        or request.snapshot_id != manifest.snapshot_id
        or approval.snapshot_id != manifest.snapshot_id
        or request.manifest_hash != manifest.manifest_sha256
        or approval.manifest_hash != manifest.manifest_sha256
        or approval.request_hash != request_hash
        or approval.principal != request.principal
        or approval.authorization_receipt != request.authorization_receipt
    ):
        raise ReleaseCLIError("promotion_binding_mismatch", "promotion artifacts mismatch")
    persisted_approval = context.session.scalar(
        select(ReleaseApproval).where(
            ReleaseApproval.space_id == context.scope.space_id,
            ReleaseApproval.id == approval.approval_id,
            ReleaseApproval.snapshot_id == manifest.snapshot_id,
            ReleaseApproval.manifest_hash == manifest.manifest_sha256,
            ReleaseApproval.actor == approval.principal,
            ReleaseApproval.actor_type == approval.actor_type,
            ReleaseApproval.authorization_receipt == approval.authorization_receipt,
        )
    )
    if persisted_approval is None:
        raise ReleaseCLIError(
            "promotion_binding_mismatch", "approval receipt is not persisted and exact"
        )
    result = ReleaseAuthorityService(context.session).promote(
        context.scope,
        snapshot_id=request.snapshot_id,
        manifest_hash=request.manifest_hash,
        expected_current_snapshot_id=request.expected_current_snapshot_id,
        reason=request.reason,
    )
    if isinstance(result, ReleaseActivationFailure):
        raise ReleaseCLIError(result.code, "release CAS failed")
    payload = {
        "schema_version": "release-proof-v1",
        "space_id": context.scope.space_id,
        "snapshot_id": result.snapshot_id,
        "manifest_hash": result.manifest_hash,
        "request_hash": request_hash,
        "approval_receipt_hash": approval.receipt_hash,
        "previous_snapshot_id": result.previous_snapshot_id,
        "audit_id": result.audit_id,
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
        value = _read_json(path)
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
    compilation: CompilationManifest,
    release_proof: ReleaseProof,
    serving_proof: ServingProof,
) -> ReleaseManifest:
    review_request = ReviewDecisionsRequest.model_validate(
        _read_yaml(paths["review-decisions.yaml"])
    )
    review_receipt = load_review_receipt(paths["review-receipt.json"])
    run_request = CandidateRunRequest.model_validate(_read_yaml(paths["run-request.yaml"]))
    candidate = _load_candidate_receipt(paths["candidate-snapshot.json"])
    manifest = _load_release_manifest(paths["release-manifest.json"])
    approval_request = ReleaseApprovalRequest.model_validate(
        _read_yaml(paths["release-approval-request.yaml"])
    )
    approval = _load_approval_receipt(paths["approval-receipt.json"])
    review_request_hash = canonical_sha256(review_request.model_dump(mode="json"))
    run_request_hash = canonical_sha256(run_request.model_dump(mode="json"))
    approval_request_hash = canonical_sha256(approval_request.model_dump(mode="json"))
    if (
        compilation.space_id != context.scope.space_id
        or review_request.compilation_manifest_hash != compilation.manifest_hash
        or review_receipt.compilation_manifest_hash != compilation.manifest_hash
        or review_receipt.request_hash != review_request_hash
        or run_request.compilation_manifest_hash != compilation.manifest_hash
        or run_request.review_receipt_hash != review_receipt.receipt_hash
        or candidate.compilation_manifest_hash != compilation.manifest_hash
        or candidate.review_receipt_hash != review_receipt.receipt_hash
        or candidate.request_hash != run_request_hash
        or candidate.snapshot_id != manifest.snapshot_id
        or candidate.manifest_hash != manifest.manifest_sha256
        or approval_request.snapshot_id != manifest.snapshot_id
        or approval_request.manifest_hash != manifest.manifest_sha256
        or approval.snapshot_id != manifest.snapshot_id
        or approval.manifest_hash != manifest.manifest_sha256
        or approval.request_hash != approval_request_hash
        or release_proof.snapshot_id != manifest.snapshot_id
        or release_proof.manifest_hash != manifest.manifest_sha256
        or release_proof.request_hash != approval_request_hash
        or release_proof.approval_receipt_hash != approval.receipt_hash
    ):
        raise ReleaseCLIError("artifact_chain_mismatch", "governance chain drifted")
    readers = (serving_proof.human_reader, serving_proof.mcp_reader)
    if (
        serving_proof.space_id != context.scope.space_id
        or serving_proof.snapshot_id != manifest.snapshot_id
        or serving_proof.manifest_hash != manifest.manifest_sha256
        or readers[0] != readers[1]
        or any(reader.snapshot_id != manifest.snapshot_id for reader in readers)
        or any(reader.manifest_hash != manifest.manifest_sha256 for reader in readers)
        or any(reader.fact_count != manifest.facts_digest.count for reader in readers)
        or any(reader.facts_hash != manifest.facts_digest.sha256 for reader in readers)
        or any(reader.evidence_hash != _serving_evidence_hash(manifest) for reader in readers)
        or any(reader.ordering_hash != _serving_ordering_hash(manifest) for reader in readers)
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
        )
    )
    if (
        current is None
        or current.snapshot_id != manifest.snapshot_id
        or record is None
        or audit is None
    ):
        raise ReleaseCLIError("release_proof_mismatch", "release is not current and exact")
    return manifest


def seal_run_artifacts(
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
    compilation = load_compilation_manifest(supplied_compilation)
    release_proof = _load_release_proof(supplied_release)
    serving_proof = _load_serving_proof(supplied_serving)
    manifest = _verify_governance_chain(
        context,
        paths=paths,
        compilation=compilation,
        release_proof=release_proof,
        serving_proof=serving_proof,
    )
    files: list[SealedArtifact] = []
    allowed_paths = {path.resolve() for path in paths.values()}
    allowed_paths.update(
        _safe_bundle_file(supplied_compilation.parent, item.path).resolve()
        for item in compilation.files
    )
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ReleaseCLIError("unsafe_artifact_path", "run contains a symlink")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        try:
            SealedArtifact._safe_path(relative)
        except ValueError as exc:
            raise ReleaseCLIError(
                "unsafe_artifact_path", "run contains a sensitive or unsafe path"
            ) from exc
        if path.resolve() not in allowed_paths:
            raise ReleaseCLIError(
                "unexpected_artifact", f"run contains an unbound artifact: {relative}"
            )
        raw = path.read_bytes()
        files.append(
            SealedArtifact(
                path=relative,
                sha256=hashlib.sha256(raw).hexdigest(),
                size_bytes=len(raw),
                item_count=_artifact_item_count(path, raw),
            )
        )
    if not files:
        raise ReleaseCLIError("artifact_chain_incomplete", "run has no artifacts")
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
    _write_json_exclusive(output, artifact_manifest.model_dump(mode="json"))
    return artifact_manifest


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
