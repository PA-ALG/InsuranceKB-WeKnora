"""Immutable full-Space release projection (OpenSpec 018 R1/R3.2)."""

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from insurance_harness.compiler.routing_data import group_of_field
from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.db.scope import KnowledgeScope, require_current_scope
from insurance_harness.knowledge.models import LineageStatus, ProposedEvidence
from insurance_harness.knowledge.pages import field_name_of
from insurance_harness.knowledge.tables import (
    Claim,
    ClaimEvidence,
    ClaimRevision,
)
from insurance_harness.schemas import SchemaRegistry


class SnapshotBuildError(RuntimeError):
    """The complete scoped projection cannot be frozen safely."""


class FrozenEvidence(BaseModel):
    """Every persisted ClaimEvidence field plus release-time display title."""

    model_config = ConfigDict(frozen=True, extra="forbid")

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


class SnapshotFactView(BaseModel):
    """Detached fact projection consumed by Reader and Wiki rendering."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    space_id: str
    snapshot_id: str
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
    value_state: Literal["present", "absent_explicitly"]
    value: JsonValue
    effective_from: date | None
    effective_to: date | None
    confidence: float
    schema_version: str
    evidence: tuple[FrozenEvidence, ...]


@dataclass
class _Candidate:
    claim: Claim
    revision: ClaimRevision | None
    version: ProductVersion | None
    product: InsuranceProduct | None
    evidence: list[ClaimEvidence] = field(default_factory=list)


def _candidate_rows(session: Session, scope: KnowledgeScope) -> list[_Candidate]:
    statement = (
        select(Claim, ClaimRevision, ProductVersion, InsuranceProduct, ClaimEvidence)
        .outerjoin(
            ClaimRevision,
            and_(
                ClaimRevision.claim_id == Claim.id,
                ClaimRevision.revision_no == Claim.current_revision,
            ),
        )
        .outerjoin(
            ProductVersion,
            and_(
                ProductVersion.id == Claim.product_version_id,
                ProductVersion.space_id == Claim.space_id,
            ),
        )
        .outerjoin(
            InsuranceProduct,
            and_(
                InsuranceProduct.id == ProductVersion.product_id,
                InsuranceProduct.space_id == Claim.space_id,
            ),
        )
        .outerjoin(ClaimEvidence, ClaimEvidence.claim_id == Claim.id)
        .where(
            Claim.space_id == scope.space_id,
            Claim.status == "published",
            Claim.product_version_id.is_not(None),
            Claim.value_state != "unknown",
        )
        .order_by(Claim.id, ClaimEvidence.id)
    )
    candidates: dict[str, _Candidate] = {}
    for claim, revision, version, product, evidence in session.execute(
        statement
    ).tuples():
        candidate = candidates.setdefault(
            claim.id,
            _Candidate(
                claim=claim,
                revision=revision,
                version=version,
                product=product,
            ),
        )
        if evidence is not None:
            candidate.evidence.append(evidence)
    return list(candidates.values())


def _freeze_evidence(
    row: ClaimEvidence,
    *,
    scope: KnowledgeScope,
    doc_titles: Mapping[str, str] | None,
) -> FrozenEvidence:
    if row.stale_at is not None or row.lineage_status is None:
        raise SnapshotBuildError(f"snapshot candidate {row.claim_id}: evidence unavailable")
    try:
        ProposedEvidence(
            knowledge_id=row.knowledge_id,
            doc_title=(doc_titles or {}).get(row.knowledge_id, row.knowledge_id),
            chunk_id=row.chunk_id,
            quote=row.quote,
            page=row.page,
            doc_role=row.doc_role,
            authority_level=row.authority_level,
            extraction_method=row.extraction_method,
            raw_kb_id=row.raw_kb_id,
            source_revision=row.source_revision,
            file_hash=row.file_hash,
            original_digest=row.original_digest,
            parser_version=row.parser_version,
            chunk_hash=row.chunk_hash,
            lineage_status=cast(LineageStatus, row.lineage_status),
            stale_at=None,
        )
    except ValidationError as exc:
        raise SnapshotBuildError(
            f"snapshot candidate {row.claim_id}: evidence audit invalid"
        ) from exc
    if row.raw_kb_id != scope.raw_kb_id:
        raise SnapshotBuildError(
            f"snapshot candidate {row.claim_id}: evidence scope mismatch"
        )
    assert row.raw_kb_id is not None
    assert row.source_revision is not None
    assert row.file_hash is not None
    assert row.original_digest is not None
    assert row.parser_version is not None
    return FrozenEvidence(
        id=row.id,
        claim_id=row.claim_id,
        knowledge_id=row.knowledge_id,
        doc_title=(doc_titles or {}).get(row.knowledge_id, row.knowledge_id),
        chunk_id=row.chunk_id,
        quote=row.quote,
        page=row.page,
        section=row.section,
        table_ref=row.table_ref,
        timestamp_ms=row.timestamp_ms,
        authority_level=row.authority_level,
        doc_role=row.doc_role,
        extraction_method=row.extraction_method,
        extracted_at=row.extracted_at,
        raw_kb_id=row.raw_kb_id,
        source_revision=row.source_revision,
        file_hash=row.file_hash,
        original_digest=row.original_digest,
        parser_version=row.parser_version,
        chunk_hash=row.chunk_hash,
        lineage_status=cast(LineageStatus, row.lineage_status),
        stale_at=None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def build_snapshot_facts(
    session: Session,
    scope: KnowledgeScope,
    *,
    snapshot_id: str,
    registry: SchemaRegistry | None = None,
    field_names: Mapping[str, str] | None = None,
    doc_titles: Mapping[str, str] | None = None,
) -> tuple[SnapshotFactView, ...]:
    """Freeze every eligible Claim in the attested Space or fail as a whole."""

    require_current_scope(session, scope)
    facts: list[SnapshotFactView] = []
    for candidate in _candidate_rows(session, scope):
        claim = candidate.claim
        if candidate.revision is None or candidate.version is None or candidate.product is None:
            raise SnapshotBuildError(
                f"snapshot candidate {claim.id}: revision or product identity missing"
            )
        if not candidate.evidence:
            raise SnapshotBuildError(
                f"snapshot candidate {claim.id}: evidence unavailable"
            )
        if claim.value_state not in ("present", "absent_explicitly"):
            raise SnapshotBuildError(
                f"snapshot candidate {claim.id}: value state invalid"
            )
        name = (field_names or {}).get(claim.predicate) or field_name_of(
            claim.predicate, registry
        )
        evidence = tuple(
            sorted(
                (
                    _freeze_evidence(row, scope=scope, doc_titles=doc_titles)
                    for row in candidate.evidence
                ),
                key=lambda item: (
                    item.knowledge_id,
                    item.page if item.page is not None else -1,
                    item.section or "",
                    item.chunk_id or "",
                    item.quote,
                    item.id,
                ),
            )
        )
        facts.append(
            SnapshotFactView(
                space_id=scope.space_id,
                snapshot_id=snapshot_id,
                claim_id=claim.id,
                revision_no=candidate.revision.revision_no,
                product_id=candidate.product.id,
                product_version_id=candidate.version.id,
                product_code=candidate.product.product_code,
                product_name=candidate.product.canonical_name,
                version_label=candidate.version.version_label,
                predicate=claim.predicate,
                field_name=name,
                field_group=group_of_field(name),
                value_state=cast(
                    Literal["present", "absent_explicitly"], claim.value_state
                ),
                value=copy.deepcopy(claim.value),
                effective_from=claim.effective_from,
                effective_to=claim.effective_to,
                confidence=claim.confidence,
                schema_version=claim.schema_version,
                evidence=evidence,
            )
        )
    facts.sort(
        key=lambda item: (
            item.product_code,
            item.version_label,
            item.predicate,
            item.effective_from or date.min,
            item.effective_to or date.max,
            item.claim_id,
            item.revision_no,
        )
    )
    return tuple(facts)
