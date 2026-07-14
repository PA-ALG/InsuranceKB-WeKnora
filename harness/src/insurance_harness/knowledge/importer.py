"""pred JSONL → Claim 导入器（change 007；specs K2）。

004 抽取管道的 pred.jsonl（compiler.models.PredRecord 行格式）→ ProposedClaim →
合并引擎。绑定 product_id / product_version_id；evidence 带页码；confidence 与
pending_judge 原样保留。幂等：
- 记录级：product+field+value_hash+source_doc（重导零新增）；
- 批级：change_sets(source_kind, external_record_id, source_revision)。
"""

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.compiler.models import PredRecord
from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
    require_current_scope,
)
from insurance_harness.knowledge.authority import (
    CONFIDENCE_TO_FLOAT,
    authority_of,
    guess_doc_role,
)
from insurance_harness.knowledge.merge import (
    MergeEngine,
    claim_value_text,
    validate_scoped_change_set_items,
)
from insurance_harness.knowledge.models import (
    ImportPartitionReport,
    ImportReport,
    MergePolicy,
    ProposedClaim,
    ProposedEvidence,
    SourceImportContext,
    SourceImportIdentity,
    value_hash,
)
from insurance_harness.knowledge.source_revision import (
    derive_retract_event_key,
    validate_retract_tombstone,
    validate_source_change_set_aggregate,
)
from insurance_harness.knowledge.tables import ChangeSet, Claim, ClaimEvidence


def load_pred_records(path: Path) -> list[PredRecord]:
    return [
        PredRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _record_import_key(product_id: str, record: PredRecord) -> str:
    """记录级幂等键（K2.3）：product+field+value_hash+source_doc。"""
    payload = "::".join(
        [product_id, record.field_id, value_hash(record.tri_state, record.value), record.doc]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _batch_key(product_id: str, records: list[PredRecord]) -> str:
    keys = sorted(_record_import_key(product_id, r) for r in records)
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()[:32]


def _require_scoped_product_version(
    session: Session,
    scope: KnowledgeScope,
    *,
    product_id: str,
    product_version_id: str,
) -> str:
    """Validate product/version ownership and return the canonical product UUID."""
    product = session.execute(
        select(InsuranceProduct)
        .join(ProductVersion, ProductVersion.product_id == InsuranceProduct.id)
        .where(
            ProductVersion.id == product_version_id,
            ProductVersion.space_id == scope.space_id,
            InsuranceProduct.space_id == scope.space_id,
        )
    ).scalar_one_or_none()
    if product is None or product_id not in (product.id, product.product_code):
        raise ScopeViolation("scope mismatch")
    return product.id


def _already_imported(
    session: Session,
    scope: KnowledgeScope,
    product_version_id: str,
    record: PredRecord,
    knowledge_id: str,
    source_revision: str | None = None,
) -> bool:
    """同 (product, field, value_hash, source_doc) 的事实已在库（任何非撤回状态）。"""
    target_hash = value_hash(record.tri_state, record.value)
    claims = session.execute(
        select(Claim).where(
            Claim.space_id == scope.space_id,
            Claim.product_version_id == product_version_id,
            Claim.predicate == record.field_id,
            Claim.status != "retracted",
        )
    ).scalars()
    for claim in claims:
        if value_hash(claim.value_state, claim_value_text(claim)) != target_hash:
            continue
        if claim.value_state == "unknown":
            return True  # unknown 占位与来源无关，一个 predicate 只落一次
        evidence_filters = [
            ClaimEvidence.claim_id == claim.id,
            ClaimEvidence.knowledge_id == knowledge_id,
        ]
        if source_revision is not None:
            evidence_filters.append(ClaimEvidence.source_revision == source_revision)
        has_source = session.execute(
            select(ClaimEvidence.id)
            .join(Claim, Claim.id == ClaimEvidence.claim_id)
            .where(Claim.space_id == scope.space_id, *evidence_filters)
        ).first()
        if has_source is not None:
            return True
    return False


def to_proposed_claim(
    record: PredRecord,
    *,
    scope: KnowledgeScope,
    product_version_id: str,
    knowledge_id: str,
    doc_role: str,
    doc_title: str,
) -> ProposedClaim:
    """PredRecord → ProposedClaim（K2.1：confidence 离散→浮点，evidence 带页码）。"""
    authority = authority_of(doc_role)
    return ProposedClaim(
        space_id=scope.space_id,
        product_version_id=product_version_id,
        predicate=record.field_id,
        field_name=record.field_name,
        value_state=record.tri_state,
        value=record.value,
        confidence=CONFIDENCE_TO_FLOAT.get(record.confidence, 0.3),
        extraction_method="llm",
        schema_version=record.schema_version,
        pending_judge=record.pending_judge,
        evidence=[
            ProposedEvidence(
                knowledge_id=e.knowledge_id or knowledge_id,
                doc_title=doc_title or record.doc,
                chunk_id=e.chunk_id,
                quote=e.quote,
                page=e.page,
                doc_role=doc_role,
                authority_level=authority,
                raw_kb_id=e.raw_kb_id,
                source_revision=e.source_revision,
                file_hash=e.file_hash,
                original_digest=e.original_digest,
                parser_version=e.parser_version,
                chunk_hash=e.chunk_hash,
                lineage_status=e.lineage_status,
                stale_at=None,
            )
            for e in record.evidence
        ],
    )


def _validated_source_context(
    value: SourceImportContext | dict[str, Any] | None,
    scope: KnowledgeScope,
) -> SourceImportContext:
    try:
        parsed = SourceImportContext.model_validate(value)
        context = SourceImportContext.model_validate(parsed.model_dump(mode="python"))
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ScopeViolation("source context mismatch") from exc
    if (
        context.space_id != scope.space_id
        or context.tenant_id != scope.tenant_id
        or context.raw_kb_id != scope.raw_kb_id
        or any(
            identity.raw_kb_id != scope.raw_kb_id
            for identity in context.documents.values()
        )
    ):
        raise ScopeViolation("source context mismatch")
    return context


def _validated_record_identity(
    record: PredRecord,
    identity: SourceImportIdentity,
) -> None:
    for raw in record.evidence:
        try:
            evidence = type(raw).model_validate(raw.model_dump(mode="python"))
        except ValidationError as exc:
            raise ScopeViolation("source lineage mismatch") from exc
        actual = (
            evidence.knowledge_id,
            evidence.raw_kb_id,
            evidence.source_revision,
            evidence.file_hash,
            evidence.original_digest,
            evidence.parser_version,
        )
        expected = (
            identity.knowledge_id,
            identity.raw_kb_id,
            identity.source_revision,
            identity.file_hash,
            identity.original_digest,
            identity.parser_version,
        )
        if evidence.lineage_status is None or actual != expected:
            raise ScopeViolation("source identity mismatch")


def _existing_source_change_set(
    session: Session,
    scope: KnowledgeScope,
    identity: SourceImportIdentity,
) -> tuple[ChangeSet | None, bool]:
    rows = list(
        session.execute(
            select(ChangeSet).where(
                ChangeSet.space_id == scope.space_id,
                ChangeSet.external_record_id == identity.knowledge_id,
                ChangeSet.source_revision == identity.source_revision,
                ChangeSet.source_kind.in_(("document", "recompile")),
            )
        ).scalars()
    )
    if len(rows) > 1:
        raise ScopeViolation("ambiguous source change set")
    if not rows:
        return None, False
    change_set = rows[0]
    item_count = validate_source_change_set_aggregate(
        session,
        scope,
        identity,
        change_set,
        allowed_source_kinds=("document", "recompile"),
    )
    if change_set.status == "applied":
        validate_scoped_change_set_items(session, scope, change_set)
        return change_set, True
    if change_set.status == "pending" and item_count == 0:
        return change_set, False
    raise ScopeViolation("source change set cannot be replayed")


def _reject_source_tombstone(
    session: Session,
    scope: KnowledgeScope,
    identity: SourceImportIdentity,
) -> None:
    tombstone = session.scalar(
        select(ChangeSet).where(
            ChangeSet.space_id == scope.space_id,
            ChangeSet.source_kind == "document",
            ChangeSet.external_record_id == identity.knowledge_id,
            ChangeSet.source_revision
            == derive_retract_event_key(
                identity.knowledge_id,
                identity.source_revision,
            ),
        )
    )
    if tombstone is None:
        return
    validate_retract_tombstone(
        session,
        scope,
        tombstone,
        knowledge_id=identity.knowledge_id,
    )
    raise ScopeViolation("source revision is tombstoned")


def _apply_partition(
    session: Session,
    records: list[PredRecord],
    *,
    scope: KnowledgeScope,
    product_version_id: str,
    identity: SourceImportIdentity,
    doc_roles: dict[str, str] | None,
    doc_titles: dict[str, str] | None,
    policy: MergePolicy | None,
    risk_of: dict[str, str] | None,
    created_by: str,
    existing_change_set: ChangeSet | None,
    duplicate: bool,
) -> ImportPartitionReport:
    risk_map = risk_of or {}
    engine = MergeEngine(
        session,
        scope=scope,
        policy=policy,
        risk_of=lambda predicate: risk_map.get(predicate, "low"),
        created_by=created_by,
    )
    change_set = existing_change_set
    if change_set is None:
        change_set, _ = engine.open_change_set(
            source_kind="document",
            knowledge_ids=[identity.knowledge_id],
            external_record_id=identity.knowledge_id,
            source_revision=identity.source_revision,
        )
    part = ImportPartitionReport(
        knowledge_id=identity.knowledge_id,
        source_revision=identity.source_revision,
        source_kind=change_set.source_kind,
        change_set_id=change_set.id,
        duplicate_batch=duplicate,
        total_records=len(records),
    )
    if duplicate:
        return part

    proposals: list[ProposedClaim] = []
    for record in records:
        doc_role = (doc_roles or {}).get(record.doc) or guess_doc_role(record.doc)
        if record.tri_state in ("present", "absent_explicitly") and not record.evidence:
            part.skipped_no_evidence += 1
            continue
        if _already_imported(
            session,
            scope,
            product_version_id,
            record,
            identity.knowledge_id,
            identity.source_revision,
        ):
            part.skipped_duplicates += 1
            continue
        if record.tri_state == "unknown":
            part.unknown_placeholders += 1
        proposals.append(
            to_proposed_claim(
                record,
                scope=scope,
                product_version_id=product_version_id,
                knowledge_id=identity.knowledge_id,
                doc_role=doc_role,
                doc_title=(doc_titles or {}).get(record.doc, record.doc),
            )
        )
        part.imported += 1
    part.merge = engine.apply_batch(change_set, proposals)
    part.judge_queue = list(engine.judge_queue)
    return part


def _aggregate_partitions(
    report: ImportReport,
    parts: list[ImportPartitionReport],
) -> ImportReport:
    report.partitions = parts
    report.change_set_ids = [part.change_set_id for part in parts]
    report.imported = sum(part.imported for part in parts)
    report.skipped_duplicates = sum(part.skipped_duplicates for part in parts)
    report.skipped_no_evidence = sum(part.skipped_no_evidence for part in parts)
    report.unknown_placeholders = sum(part.unknown_placeholders for part in parts)
    report.judge_queue = [item for part in parts for item in part.judge_queue]
    for part in parts:
        for action, count in part.merge.actions.items():
            report.merge.actions[action] = report.merge.actions.get(action, 0) + count
        report.merge.review_keys.extend(part.merge.review_keys)
        report.merge.judge_queue_size += part.merge.judge_queue_size
    if len(parts) == 1:
        report.change_set_id = parts[0].change_set_id
        report.duplicate_batch = parts[0].duplicate_batch
        report.merge.change_set_id = parts[0].merge.change_set_id
    elif parts:
        report.duplicate_batch = all(part.duplicate_batch for part in parts)
    return report


def _import_legacy_records(
    session: Session,
    records: list[PredRecord],
    *,
    scope: KnowledgeScope,
    canonical_product_id: str,
    product_version_id: str,
    doc_roles: dict[str, str] | None,
    knowledge_ids: dict[str, str] | None,
    doc_titles: dict[str, str] | None,
    policy: MergePolicy | None,
    risk_of: dict[str, str] | None,
    created_by: str,
    source_revision: str | None,
) -> ImportReport:
    report = ImportReport(total_records=len(records))
    if not records:
        return report
    if any(
        evidence.lineage_status is not None
        for record in records
        for evidence in record.evidence
    ):
        raise ScopeViolation("source-aware evidence cannot use legacy replay")
    risk_map = risk_of or {}
    engine = MergeEngine(
        session,
        scope=scope,
        policy=policy,
        risk_of=lambda predicate: risk_map.get(predicate, "low"),
        created_by=created_by,
    )
    docs = sorted({record.doc for record in records})
    change_set, created = engine.open_change_set(
        source_kind="document",
        knowledge_ids=[(knowledge_ids or {}).get(doc, doc) for doc in docs],
        external_record_id=_batch_key(canonical_product_id, records),
        source_revision=source_revision,
    )
    report.change_set_id = change_set.id
    report.change_set_ids = [change_set.id]
    if not created:
        report.duplicate_batch = True
        return report
    proposals: list[ProposedClaim] = []
    for record in records:
        knowledge_id = (knowledge_ids or {}).get(record.doc, record.doc)
        doc_role = (doc_roles or {}).get(record.doc) or guess_doc_role(record.doc)
        if record.tri_state in ("present", "absent_explicitly") and not record.evidence:
            report.skipped_no_evidence += 1
            continue
        if _already_imported(session, scope, product_version_id, record, knowledge_id):
            report.skipped_duplicates += 1
            continue
        if record.tri_state == "unknown":
            report.unknown_placeholders += 1
        proposals.append(
            to_proposed_claim(
                record,
                scope=scope,
                product_version_id=product_version_id,
                knowledge_id=knowledge_id,
                doc_role=doc_role,
                doc_title=(doc_titles or {}).get(record.doc, record.doc),
            )
        )
        report.imported += 1
    report.merge = engine.apply_batch(change_set, proposals)
    report.judge_queue = list(engine.judge_queue)
    session.flush()
    return report


def import_pred_records(
    session: Session,
    records: list[PredRecord],
    *,
    scope: KnowledgeScope,
    product_id: str,
    product_version_id: str,
    doc_roles: dict[str, str] | None = None,
    knowledge_ids: dict[str, str] | None = None,
    doc_titles: dict[str, str] | None = None,
    policy: MergePolicy | None = None,
    risk_of: dict[str, str] | None = None,
    created_by: str = "pred-importer",
    source_revision: str | None = None,
    source_context: SourceImportContext | dict[str, Any] | None = None,
    legacy_replay: bool = False,
) -> ImportReport:
    """Import compiler output, source-aware by default and legacy only by opt-in."""
    require_current_scope(session, scope)
    canonical_product_id = _require_scoped_product_version(
        session,
        scope,
        product_id=product_id,
        product_version_id=product_version_id,
    )
    if legacy_replay:
        if source_context is not None:
            raise ScopeViolation("legacy replay cannot accept source context")
        return _import_legacy_records(
            session,
            records,
            scope=scope,
            canonical_product_id=canonical_product_id,
            product_version_id=product_version_id,
            doc_roles=doc_roles,
            knowledge_ids=knowledge_ids,
            doc_titles=doc_titles,
            policy=policy,
            risk_of=risk_of,
            created_by=created_by,
            source_revision=source_revision,
        )
    if knowledge_ids is not None or source_revision is not None:
        raise ScopeViolation("legacy source arguments require legacy replay")
    report = ImportReport(total_records=len(records))
    if not records:
        return report
    context = _validated_source_context(source_context, scope)
    partitions: dict[tuple[str, str], list[PredRecord]] = defaultdict(list)
    identities: dict[tuple[str, str], SourceImportIdentity] = {}
    for record in records:
        identity = context.documents.get(record.doc)
        if identity is None:
            raise ScopeViolation("source document identity missing")
        if identity.knowledge_id.strip() == record.doc.strip():
            raise ScopeViolation("filename placeholder is not a source identity")
        _validated_record_identity(record, identity)
        key = (identity.knowledge_id, identity.source_revision)
        existing_identity = identities.get(key)
        if existing_identity is not None and existing_identity != identity:
            raise ScopeViolation("source partition identity mismatch")
        identities[key] = identity
        partitions[key].append(record)
    keys = sorted(partitions)
    for key in keys:
        _reject_source_tombstone(session, scope, identities[key])
    source_states = {
        key: _existing_source_change_set(session, scope, identities[key]) for key in keys
    }
    with session.begin_nested():
        parts = [
            _apply_partition(
                session,
                partitions[key],
                scope=scope,
                product_version_id=product_version_id,
                identity=identities[key],
                doc_roles=doc_roles,
                doc_titles=doc_titles,
                policy=policy,
                risk_of=risk_of,
                created_by=created_by,
                existing_change_set=source_states[key][0],
                duplicate=source_states[key][1],
            )
            for key in keys
        ]
        session.flush()
    return _aggregate_partitions(report, parts)


def import_pred_jsonl(
    session: Session,
    path: Path,
    *,
    scope: KnowledgeScope,
    product_id: str,
    product_version_id: str,
    doc_roles: dict[str, str] | None = None,
    knowledge_ids: dict[str, str] | None = None,
    doc_titles: dict[str, str] | None = None,
    policy: MergePolicy | None = None,
    risk_of: dict[str, str] | None = None,
    created_by: str = "pred-importer",
    source_context: SourceImportContext | dict[str, Any] | None = None,
    legacy_replay: bool = False,
) -> ImportReport:
    """Import pred JSONL; file-content revision exists only in explicit replay mode."""
    require_current_scope(session, scope)
    raw = path.read_text(encoding="utf-8")
    source_revision = (
        hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        if legacy_replay
        else None
    )
    records = load_pred_records(path)
    return import_pred_records(
        session,
        records,
        scope=scope,
        product_id=product_id,
        product_version_id=product_version_id,
        doc_roles=doc_roles,
        knowledge_ids=knowledge_ids,
        doc_titles=doc_titles,
        policy=policy,
        risk_of=risk_of,
        created_by=created_by,
        source_revision=source_revision,
        source_context=source_context,
        legacy_replay=legacy_replay,
    )
