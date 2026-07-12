"""pred JSONL → Claim 导入器（change 007；specs K2）。

004 抽取管道的 pred.jsonl（compiler.models.PredRecord 行格式）→ ProposedClaim →
合并引擎。绑定 product_id / product_version_id；evidence 带页码；confidence 与
pending_judge 原样保留。幂等：
- 记录级：product+field+value_hash+source_doc（重导零新增）；
- 批级：change_sets(source_kind, external_record_id, source_revision)。
"""

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.compiler.models import PredRecord
from insurance_harness.knowledge.authority import (
    CONFIDENCE_TO_FLOAT,
    authority_of,
    guess_doc_role,
)
from insurance_harness.knowledge.merge import (
    MergeEngine,
    claim_value_text,
)
from insurance_harness.knowledge.models import (
    ImportReport,
    MergePolicy,
    ProposedClaim,
    ProposedEvidence,
    value_hash,
)
from insurance_harness.knowledge.tables import Claim, ClaimEvidence


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


def _already_imported(
    session: Session,
    product_version_id: str,
    record: PredRecord,
    knowledge_id: str,
) -> bool:
    """同 (product, field, value_hash, source_doc) 的事实已在库（任何非撤回状态）。"""
    target_hash = value_hash(record.tri_state, record.value)
    claims = session.execute(
        select(Claim).where(
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
        has_source = session.execute(
            select(ClaimEvidence.id).where(
                ClaimEvidence.claim_id == claim.id,
                ClaimEvidence.knowledge_id == knowledge_id,
            )
        ).first()
        if has_source is not None:
            return True
    return False


def to_proposed_claim(
    record: PredRecord,
    *,
    product_version_id: str,
    knowledge_id: str,
    doc_role: str,
    doc_title: str,
) -> ProposedClaim:
    """PredRecord → ProposedClaim（K2.1：confidence 离散→浮点，evidence 带页码）。"""
    authority = authority_of(doc_role)
    return ProposedClaim(
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
                knowledge_id=knowledge_id,
                doc_title=doc_title or record.doc,
                quote=e.quote,
                page=e.page,
                doc_role=doc_role,
                authority_level=authority,
            )
            for e in record.evidence
        ],
    )


def import_pred_records(
    session: Session,
    records: list[PredRecord],
    *,
    product_id: str,
    product_version_id: str,
    doc_roles: dict[str, str] | None = None,
    knowledge_ids: dict[str, str] | None = None,
    doc_titles: dict[str, str] | None = None,
    policy: MergePolicy | None = None,
    risk_of: dict[str, str] | None = None,
    created_by: str = "pred-importer",
    source_revision: str | None = None,
) -> ImportReport:
    """一批 pred 记录 → 一个 ChangeSet（03 §2.5）→ 合并引擎。

    - ``doc_roles``：doc 文件名 → doc_role（缺省按文件名猜，03 §6.1 映射权威级）；
    - ``knowledge_ids``：doc 文件名 → WeKnora knowledge_id（缺省用文件名占位）；
    - ``risk_of``：predicate → 风险级（缺省 low）。
    """
    report = ImportReport(total_records=len(records))
    if not records:
        return report
    risk_map = risk_of or {}
    engine = MergeEngine(
        session,
        policy=policy,
        risk_of=lambda predicate: risk_map.get(predicate, "low"),
        created_by=created_by,
    )
    docs = sorted({r.doc for r in records})
    change_set, created = engine.open_change_set(
        source_kind="document",
        knowledge_ids=[(knowledge_ids or {}).get(d, d) for d in docs],
        external_record_id=_batch_key(product_id, records),
        source_revision=source_revision,
    )
    if not created:
        report.duplicate_batch = True
        report.change_set_id = change_set.id
        return report
    report.change_set_id = change_set.id

    proposals: list[ProposedClaim] = []
    for record in records:
        knowledge_id = (knowledge_ids or {}).get(record.doc, record.doc)
        doc_role = (doc_roles or {}).get(record.doc) or guess_doc_role(record.doc)
        if record.tri_state in ("present", "absent_explicitly") and not record.evidence:
            report.skipped_no_evidence += 1  # K2.4：无证据拒绝入库（03 原则 2）
            continue
        if _already_imported(session, product_version_id, record, knowledge_id):
            report.skipped_duplicates += 1
            continue
        if record.tri_state == "unknown":
            report.unknown_placeholders += 1
        proposal = to_proposed_claim(
            record,
            product_version_id=product_version_id,
            knowledge_id=knowledge_id,
            doc_role=doc_role,
            doc_title=(doc_titles or {}).get(record.doc, record.doc),
        )
        proposals.append(proposal)
        report.imported += 1

    report.merge = engine.apply_batch(change_set, proposals)
    report.judge_queue = list(engine.judge_queue)
    session.flush()
    return report


def import_pred_jsonl(
    session: Session,
    path: Path,
    *,
    product_id: str,
    product_version_id: str,
    doc_roles: dict[str, str] | None = None,
    knowledge_ids: dict[str, str] | None = None,
    doc_titles: dict[str, str] | None = None,
    policy: MergePolicy | None = None,
    risk_of: dict[str, str] | None = None,
    created_by: str = "pred-importer",
) -> ImportReport:
    """pred.jsonl 文件入口：source_revision 取文件内容 sha 前缀（批级幂等的一部分）。"""
    raw = path.read_text(encoding="utf-8")
    source_revision = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    records = load_pred_records(path)
    return import_pred_records(
        session,
        records,
        product_id=product_id,
        product_version_id=product_version_id,
        doc_roles=doc_roles,
        knowledge_ids=knowledge_ids,
        doc_titles=doc_titles,
        policy=policy,
        risk_of=risk_of,
        created_by=created_by,
        source_revision=source_revision,
    )
