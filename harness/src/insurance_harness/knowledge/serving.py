"""Approved, hash-bound serving reader over the frozen release projection."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.scope import KnowledgeScope, ScopeViolation, require_current_scope
from insurance_harness.knowledge.release_manifest import (
    CanonicalSnapshotFact,
    ImmutableJson,
    ReleaseManifest,
    ReleaseManifestBuildError,
    ReleaseManifestIntegrityError,
    build_release_manifest_from_snapshot,
    verify_release_manifest,
)
from insurance_harness.knowledge.tables import (
    CurrentRelease,
    ReleaseApproval,
    ReleaseManifestRecord,
    ReleaseSnapshot,
)

type ServingFailureCode = Literal[
    "no_release",
    "unsupported_read_model",
    "approval_missing",
    "manifest_missing",
    "manifest_mismatch",
    "product_not_found",
    "predicate_not_found",
    "effective_date_miss",
    "claim_not_found",
    "scope_mismatch",
]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        arbitrary_types_allowed=True,
    )


class ServingDocumentEvidence(_StrictFrozenModel):
    """Complete document evidence copied only from a frozen approved manifest."""

    kind: Literal["document"]
    id: str
    claim_id: str
    knowledge_id: str
    doc_title: str
    chunk_id: str | None
    quote: str
    page: int | None
    section: str | None
    table_ref: str | None
    timestamp_ms: int | None
    authority_level: int
    doc_role: str
    extraction_method: str
    extracted_at: datetime
    raw_kb_id: str
    source_revision: str
    file_hash: str
    original_digest: str
    parser_version: str
    chunk_hash: str | None
    lineage_status: Literal["linked", "page_only", "ambiguous"]
    stale_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ServingStructuredEvidence(_StrictFrozenModel):
    """Reserved structured provenance contract; populated by change 010 later."""

    kind: Literal["structured"]
    id: str
    claim_id: str
    source_system: str
    source_record_id: str
    source_revision: str
    source_locator: str
    source_hash: str
    mapping_version: str


ServingEvidence = Annotated[
    ServingDocumentEvidence | ServingStructuredEvidence,
    Field(discriminator="kind"),
]


def _evidence_sort_key(evidence: ServingEvidence) -> tuple[str, ...]:
    if isinstance(evidence, ServingDocumentEvidence):
        return (
            evidence.kind,
            evidence.raw_kb_id,
            evidence.knowledge_id,
            evidence.source_revision,
            evidence.file_hash,
            evidence.chunk_id or "",
            evidence.id,
        )
    return (
        evidence.kind,
        evidence.source_system,
        evidence.source_record_id,
        evidence.source_revision,
        evidence.source_hash,
        evidence.source_locator,
        evidence.id,
    )


class CanonicalServingFact(_StrictFrozenModel):
    """Public canonical fact detached from all mutable knowledge-domain rows."""

    claim_id: str
    revision_no: int
    product_id: str
    product_version_id: str
    product_code: str
    product_name: str
    version_label: str
    predicate: str
    field_name: str
    field_group: str
    value_state: Literal["present", "absent_explicitly", "unknown"]
    value: ImmutableJson
    effective_from: date | None
    effective_to: date | None
    confidence: float
    schema_version: str
    evidence: tuple[ServingEvidence, ...]

    @field_validator("evidence", mode="after")
    @classmethod
    def _canonical_evidence(
        cls,
        value: tuple[ServingEvidence, ...],
    ) -> tuple[ServingEvidence, ...]:
        return tuple(sorted(value, key=_evidence_sort_key))


class ApprovedSnapshotResult(_StrictFrozenModel):
    snapshot_id: str
    manifest_hash: str
    approval_principal: str
    approved_at: datetime
    read_model_version: int
    facts: tuple[CanonicalServingFact, ...]


class ServingFailure(_StrictFrozenModel):
    code: ServingFailureCode
    snapshot_id: str | None = None
    manifest_hash: str | None = None


def _fact_sort_key(
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


def _serving_fact(fact: CanonicalSnapshotFact) -> CanonicalServingFact:
    payload = fact.model_dump(mode="python", exclude={"space_id", "snapshot_id", "evidence"})
    document_evidence = tuple(
        ServingDocumentEvidence.model_validate(
            evidence.model_dump(mode="python") | {"kind": "document"}
        )
        for evidence in fact.evidence
    )
    return CanonicalServingFact.model_validate(
        payload | {"evidence": tuple(sorted(document_evidence, key=_evidence_sort_key))}
    )


def _manifest_from_record(record: ReleaseManifestRecord) -> ReleaseManifest:
    return ReleaseManifest.model_validate_json(
        json.dumps(
            record.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )


def _predicates(value: tuple[str, ...] | None) -> frozenset[str] | None:
    if value is None:
        return None
    if (
        not isinstance(value, tuple)
        or not value
        or any(not isinstance(item, str) or not item or item != item.strip() for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError("predicates must be a non-empty tuple of unique canonical names")
    return frozenset(value)


class ApprovedSnapshotReader:
    """Read one fully attested current release without consulting mutable Claims."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def read_current(
        self,
        scope: KnowledgeScope,
        *,
        product_id: str | None = None,
        product_version_id: str | None = None,
        predicates: tuple[str, ...] | None = None,
        effective_on: date | None = None,
        claim_id: str | None = None,
    ) -> ApprovedSnapshotResult | ServingFailure:
        requested_predicates = _predicates(predicates)
        with self._session_factory() as session:
            try:
                require_current_scope(session, scope)
            except ScopeViolation:
                return ServingFailure(code="scope_mismatch")

            snapshot_id = session.scalar(
                select(CurrentRelease.snapshot_id).where(
                    CurrentRelease.space_id == scope.space_id
                )
            )
            if snapshot_id is None:
                return ServingFailure(code="no_release")
            snapshot = session.scalar(
                select(ReleaseSnapshot).where(
                    ReleaseSnapshot.space_id == scope.space_id,
                    ReleaseSnapshot.id == snapshot_id,
                )
            )
            if snapshot is None:
                return ServingFailure(code="scope_mismatch")
            if (
                snapshot.status != "published"
                or snapshot.read_model_version != 1
                or snapshot.projection_frozen_at is None
            ):
                return ServingFailure(
                    code="unsupported_read_model",
                    snapshot_id=snapshot_id,
                )

            record = session.scalar(
                select(ReleaseManifestRecord).where(
                    ReleaseManifestRecord.space_id == scope.space_id,
                    ReleaseManifestRecord.snapshot_id == snapshot_id,
                )
            )
            if record is None:
                return ServingFailure(code="manifest_missing", snapshot_id=snapshot_id)
            safe_identity = {
                "snapshot_id": snapshot_id,
                "manifest_hash": record.manifest_hash,
            }
            try:
                manifest = _manifest_from_record(record)
                verify_release_manifest(manifest)
                rebuilt = build_release_manifest_from_snapshot(
                    session,
                    scope,
                    snapshot_id=snapshot_id,
                    schema_version=manifest.schema_version,
                    template_hashes=manifest.template_hashes,
                    model_plan_hash=manifest.model_plan_hash,
                )
                if (
                    record.manifest_hash != manifest.manifest_sha256
                    or manifest.space_id != scope.space_id
                    or manifest.snapshot_id != snapshot_id
                    or manifest.read_model_version != snapshot.read_model_version
                    or rebuilt != manifest
                ):
                    raise ReleaseManifestIntegrityError("serving manifest mismatch")
            except (
                ValidationError,
                ReleaseManifestBuildError,
                ReleaseManifestIntegrityError,
                TypeError,
                ValueError,
            ):
                return ServingFailure(code="manifest_mismatch", **safe_identity)

            approval = session.scalar(
                select(ReleaseApproval).where(
                    ReleaseApproval.space_id == scope.space_id,
                    ReleaseApproval.snapshot_id == snapshot_id,
                    ReleaseApproval.manifest_hash == manifest.manifest_sha256,
                )
            )
            if (
                approval is None
                or approval.actor_type not in {"human", "principal"}
                or approval.role != "release_approver"
            ):
                return ServingFailure(code="approval_missing", **safe_identity)

            facts = sorted((_serving_fact(fact) for fact in manifest.facts), key=_fact_sort_key)
            if product_id is not None:
                facts = [fact for fact in facts if fact.product_id == product_id]
            if product_version_id is not None:
                facts = [
                    fact
                    for fact in facts
                    if fact.product_version_id == product_version_id
                ]
            if not facts:
                return ServingFailure(code="product_not_found", **safe_identity)
            if requested_predicates is not None:
                facts = [fact for fact in facts if fact.predicate in requested_predicates]
                if not facts:
                    return ServingFailure(code="predicate_not_found", **safe_identity)
            if effective_on is not None:
                facts = [
                    fact
                    for fact in facts
                    if (fact.effective_from is None or fact.effective_from <= effective_on)
                    and (fact.effective_to is None or effective_on <= fact.effective_to)
                ]
                if not facts:
                    return ServingFailure(code="effective_date_miss", **safe_identity)
            if claim_id is not None:
                facts = [fact for fact in facts if fact.claim_id == claim_id]
                if not facts:
                    return ServingFailure(code="claim_not_found", **safe_identity)

            observed_snapshot_id = session.scalar(
                select(CurrentRelease.snapshot_id).where(
                    CurrentRelease.space_id == scope.space_id
                )
            )
            if observed_snapshot_id != snapshot_id:
                return ServingFailure(code="manifest_mismatch", **safe_identity)
            approved_at = approval.approved_at
            if approved_at.tzinfo is None or approved_at.utcoffset() is None:
                approved_at = approved_at.replace(tzinfo=UTC)
            else:
                approved_at = approved_at.astimezone(UTC)
            return ApprovedSnapshotResult(
                snapshot_id=snapshot_id,
                manifest_hash=manifest.manifest_sha256,
                approval_principal=approval.actor,
                approved_at=approved_at,
                read_model_version=snapshot.read_model_version,
                facts=tuple(sorted(facts, key=_fact_sort_key)),
            )


__all__ = [
    "ApprovedSnapshotReader",
    "ApprovedSnapshotResult",
    "CanonicalServingFact",
    "ServingDocumentEvidence",
    "ServingFailure",
    "ServingFailureCode",
    "ServingStructuredEvidence",
]
