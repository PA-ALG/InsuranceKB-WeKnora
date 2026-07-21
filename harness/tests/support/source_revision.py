"""Shared builders for source-revision and source-import tests."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from insurance_harness.compiler.models import PredRecord
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.goldenset.records import Evidence
from insurance_harness.knowledge.models import SourceImportIdentity
from insurance_harness.knowledge.tables import Claim, ClaimEvidence
from insurance_harness.sources import ProcessedAtOrdering, SourceRevision
from tests.kbhelpers import pred, seed_bound_scope, seed_product

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
EARLIER = datetime(2026, 7, 14, 7, 0, tzinfo=UTC)


def count_rows(session: Session, table: type) -> int:
    return session.scalar(select(func.count()).select_from(table)) or 0


def bound_scope(session: Session, suffix: str = "a") -> KnowledgeScope:
    return seed_bound_scope(
        session,
        tenant_id=f"tenant-{suffix}",
        raw_kb_id=f"raw-{suffix}",
        wiki_kb_id=f"wiki-{suffix}",
    )


def source_identity(
    scope: KnowledgeScope,
    *,
    knowledge_id: str = "knowledge-1",
    revision_char: str = "a",
    ordering_offset: int | None = None,
) -> SourceImportIdentity:
    if ordering_offset is None:
        ordering_offset = ord(revision_char) - ord("a")
    processed_at = NOW + timedelta(seconds=ordering_offset)
    revision = SourceRevision(
        file_hash=revision_char * 32,
        ordering=ProcessedAtOrdering(value=processed_at),
        parser_fingerprint="pdfplumber@0.11:text-v1",
    )
    return SourceImportIdentity(
        knowledge_id=knowledge_id,
        raw_kb_id=scope.raw_kb_id,
        source_revision=revision.value,
        ordering=revision.ordering,
        file_hash=revision.file_hash,
        original_digest=revision_char * 64,
        parser_version=revision.parser_fingerprint,
    )


def claim_with_evidence(
    session: Session,
    scope: KnowledgeScope,
    *,
    predicate: str,
    identities: list[SourceImportIdentity],
) -> tuple[Claim, list[ClaimEvidence]]:
    _, version = seed_product(
        session,
        scope=scope,
        code=f"P-{predicate}",
        name=f"Product {predicate}",
    )
    claim = Claim(
        space_id=scope.space_id,
        product_version_id=version.id,
        subject_type="product_version",
        predicate=predicate,
        value_state="present",
        value={"text": predicate},
        status="published",
        confidence=0.9,
        extraction_method="llm",
        schema_version="v1",
        current_revision=1,
        pending_judge=False,
    )
    session.add(claim)
    session.flush()
    rows = [
        ClaimEvidence(
            claim_id=claim.id,
            knowledge_id=identity.knowledge_id,
            chunk_id=None,
            quote=f"{predicate}:{identity.knowledge_id}",
            page=1,
            authority_level=1,
            doc_role="terms",
            extraction_method="llm",
            extracted_at=NOW,
            raw_kb_id=identity.raw_kb_id,
            source_revision=identity.source_revision,
            file_hash=identity.file_hash,
            original_digest=identity.original_digest,
            parser_version=identity.parser_version,
            chunk_hash=None,
            lineage_status="page_only",
            stale_at=None,
        )
        for identity in identities
    ]
    session.add_all(rows)
    session.flush()
    return claim, rows


def source_record(
    identity: SourceImportIdentity,
    *,
    doc: str = "new.pdf",
) -> PredRecord:
    record = pred(
        "grace_period",
        value="60天",
        doc=doc,
        quote="宽限期为60日",
    )
    return record.model_copy(
        update={
            "evidence": [
                Evidence(
                    page=2,
                    quote="宽限期为60日",
                    **identity.model_dump(mode="python"),
                    lineage_status="page_only",
                )
            ]
        }
    )
