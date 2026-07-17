"""Source-aware fixtures shared by OpenSpec 018 release tests."""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Literal

from sqlalchemy.orm import Session

from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.knowledge.snapshots import SnapshotFactView
from insurance_harness.knowledge.tables import (
    Claim,
    ClaimEvidence,
    ClaimRevision,
    CurrentRelease,
    ReleaseSnapshot,
    SnapshotFact,
)
from tests.kbhelpers import seed_bound_scope, seed_product

NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)


def release_scope(session: Session, suffix: str = "a") -> KnowledgeScope:
    return seed_bound_scope(
        session,
        tenant_id=f"tenant-{suffix}",
        raw_kb_id=f"raw-{suffix}",
        wiki_kb_id=f"wiki-{suffix}",
    )


def release_product(
    session: Session,
    scope: KnowledgeScope,
    *,
    code: str,
    name: str | None = None,
) -> tuple[InsuranceProduct, ProductVersion]:
    return seed_product(
        session,
        scope=scope,
        code=code,
        name=name or f"产品{code}",
        version_label="V1",
    )


def release_claim(
    session: Session,
    scope: KnowledgeScope,
    version: ProductVersion,
    *,
    claim_id: str,
    predicate: str,
    value: str = "90天",
    value_state: Literal["present", "absent_explicitly", "unknown"] = "present",
    status: str = "published",
    current_revision: int = 1,
    add_revision: bool = True,
    add_evidence: bool = True,
    effective_from: date | None = None,
    effective_to: date | None = None,
) -> tuple[Claim, ClaimEvidence | None]:
    claim = Claim(
        id=claim_id,
        space_id=scope.space_id,
        product_version_id=version.id,
        predicate=predicate,
        value_state=value_state,
        value=None if value_state == "absent_explicitly" else {"text": value},
        effective_from=effective_from,
        effective_to=effective_to,
        status=status,
        confidence=0.9,
        extraction_method="llm",
        schema_version="v1.1+release",
        current_revision=current_revision,
    )
    session.add(claim)
    session.flush()
    if add_revision:
        session.add(
            ClaimRevision(
                id=f"revision-{claim_id}",
                claim_id=claim.id,
                revision_no=1,
                before=None,
                after={"value": claim.value},
                actor="test",
                at=NOW,
            )
        )
    evidence: ClaimEvidence | None = None
    if add_evidence:
        evidence = ClaimEvidence(
            id=f"evidence-{claim_id}",
            claim_id=claim.id,
            knowledge_id=f"knowledge-{claim_id}",
            chunk_id=f"chunk-{claim_id}",
            quote=f"{predicate}={value}",
            page=3,
            section="保险责任",
            table_ref=None,
            timestamp_ms=None,
            authority_level=1,
            doc_role="terms",
            extraction_method="llm",
            extracted_at=NOW,
            raw_kb_id=scope.raw_kb_id,
            source_revision="a" * 64,
            file_hash="b" * 32,
            original_digest="c" * 64,
            parser_version="parser/1",
            chunk_hash="d" * 64,
            lineage_status="linked",
            stale_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(evidence)
    session.flush()
    return claim, evidence


def persist_release_snapshot(
    session: Session,
    scope: KnowledgeScope,
    *,
    snapshot_id: str,
    facts: Sequence[SnapshotFactView] = (),
    read_model_version: int = 1,
    make_current: bool = True,
) -> ReleaseSnapshot:
    snapshot = ReleaseSnapshot(
        id=snapshot_id,
        space_id=scope.space_id,
        label=snapshot_id,
        rendered_pages=[],
        status="building",
        read_model_version=read_model_version,
        published_at=None,
        published_by="test",
    )
    session.add(snapshot)
    session.flush()
    for index, fact in enumerate(facts):
        session.add(
            SnapshotFact(
                id=f"fact-{index}-{snapshot_id}",
                space_id=fact.space_id,
                snapshot_id=snapshot.id,
                claim_id=fact.claim_id,
                revision_no=fact.revision_no,
                product_id=fact.product_id,
                product_version_id=fact.product_version_id,
                product_code=fact.product_code,
                product_name=fact.product_name,
                version_label=fact.version_label,
                predicate=fact.predicate,
                field_name=fact.field_name,
                field_group=fact.field_group,
                value_state=fact.value_state,
                value=fact.value,
                effective_from=fact.effective_from,
                effective_to=fact.effective_to,
                confidence=fact.confidence,
                schema_version=fact.schema_version,
                evidence=[item.model_dump(mode="json") for item in fact.evidence],
            )
        )
    session.flush()
    snapshot.projection_frozen_at = NOW
    snapshot.status = "published"
    snapshot.published_at = NOW
    if make_current:
        current = session.get(CurrentRelease, (scope.space_id, "current"))
        if current is None:
            session.add(
                CurrentRelease(
                    space_id=scope.space_id,
                    id="current",
                    snapshot_id=snapshot.id,
                )
            )
        else:
            current.snapshot_id = snapshot.id
    session.commit()
    return snapshot
