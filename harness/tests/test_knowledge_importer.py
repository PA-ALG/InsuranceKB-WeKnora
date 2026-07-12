"""K2：pred JSONL → Claim 导入器（specs/mainchain.md）。"""

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from insurance_harness.knowledge import (
    MergePolicy,
    import_pred_jsonl,
    import_pred_records,
)
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    ClaimEvidence,
    ReviewItem,
)
from tests.kbhelpers import BROCHURE, TERMS, pred, seed_product


def _count(session: Session, table: type) -> int:
    return session.execute(select(func.count()).select_from(table)).scalar_one()


def test_k2_1_import_binds_product_and_evidence(kb_session: Session) -> None:
    _, version = seed_product(kb_session)
    records = [
        pred("waiting_period", value="90天", doc=BROCHURE, page=3, quote="等待期为90天"),
        pred(
            "grace_period", value="60天", doc=TERMS, page=8, quote="宽限期60日",
            confidence="medium",
        ),
    ]
    report = import_pred_records(
        kb_session, records, product_id="AXB001", product_version_id=version.id
    )
    assert report.imported == 2 and report.change_set_id

    claims = kb_session.execute(select(Claim)).scalars().all()
    assert {c.product_version_id for c in claims} == {version.id}
    by_pred = {c.predicate: c for c in claims}
    assert by_pred["waiting_period"].confidence == 0.9  # high → 0.9
    assert by_pred["grace_period"].confidence == 0.6  # medium → 0.6

    evidence = kb_session.execute(select(ClaimEvidence)).scalars().all()
    by_claim = {e.claim_id: e for e in evidence}
    brochure_ev = by_claim[by_pred["waiting_period"].id]
    assert brochure_ev.page == 3 and brochure_ev.quote == "等待期为90天"
    assert brochure_ev.doc_role == "official_desc" and brochure_ev.authority_level == 2
    terms_ev = by_claim[by_pred["grace_period"].id]
    assert terms_ev.doc_role == "terms" and terms_ev.authority_level == 1  # 03 §6.1 映射


def test_k2_1_pending_judge_preserved_and_never_auto(kb_session: Session) -> None:
    _, version = seed_product(kb_session)
    report = import_pred_records(
        kb_session,
        [pred("hesitation_period", value="15天", quote="犹豫期15天", pending_judge=True)],
        product_id="AXB001",
        product_version_id=version.id,
        policy=MergePolicy(auto_apply_add=True),  # 即便放开自动，也不许通过
    )
    claim = kb_session.execute(select(Claim)).scalar_one()
    assert claim.pending_judge is True
    assert claim.status == "candidate"  # 未被自动发布
    assert report.merge.review_keys  # 走审核


def test_k2_2_unknown_becomes_draft_placeholder(kb_session: Session) -> None:
    _, version = seed_product(kb_session)
    report = import_pred_records(
        kb_session,
        [pred("premium_waiver", value=None, tri_state="unknown")],
        product_id="AXB001",
        product_version_id=version.id,
    )
    assert report.unknown_placeholders == 1
    claim = kb_session.execute(select(Claim)).scalar_one()
    assert claim.status == "draft" and claim.value_state == "unknown"
    assert _count(kb_session, ReviewItem) == 0  # 不产生审核项


def test_k2_3_batch_idempotent(kb_session: Session, tmp_path: Path) -> None:
    _, version = seed_product(kb_session)
    lines = [
        pred("waiting_period", value="90天", quote="等待期为90天").model_dump_json(),
        pred("grace_period", value="60天", quote="宽限期60日").model_dump_json(),
    ]
    path = tmp_path / "pred.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    first = import_pred_jsonl(
        kb_session, path, product_id="AXB001", product_version_id=version.id
    )
    assert first.imported == 2
    claims_before = _count(kb_session, Claim)
    items_before = _count(kb_session, ChangeItem)
    evidence_before = _count(kb_session, ClaimEvidence)

    second = import_pred_jsonl(
        kb_session, path, product_id="AXB001", product_version_id=version.id
    )
    assert second.duplicate_batch is True
    assert second.change_set_id == first.change_set_id  # 批级幂等键命中
    assert _count(kb_session, Claim) == claims_before
    assert _count(kb_session, ChangeItem) == items_before
    assert _count(kb_session, ClaimEvidence) == evidence_before


def test_k2_3_record_level_idempotent(kb_session: Session) -> None:
    _, version = seed_product(kb_session)
    records = [pred("waiting_period", value="90天", quote="等待期为90天")]
    import_pred_records(
        kb_session, records, product_id="AXB001", product_version_id=version.id,
        source_revision="r1",
    )
    # 批内容相同但 source_revision 不同 → 新 ChangeSet，但记录级幂等键拦截
    report = import_pred_records(
        kb_session, records, product_id="AXB001", product_version_id=version.id,
        source_revision="r2",
    )
    assert report.duplicate_batch is False
    assert report.imported == 0 and report.skipped_duplicates == 1
    assert _count(kb_session, Claim) == 1
    assert _count(kb_session, ChangeSet) == 2  # 变更集本身留痕


def test_k2_4_present_without_evidence_rejected(kb_session: Session) -> None:
    _, version = seed_product(kb_session)
    report = import_pred_records(
        kb_session,
        [pred("waiting_period", value="90天", quote=None)],
        product_id="AXB001",
        product_version_id=version.id,
    )
    assert report.imported == 0 and report.skipped_no_evidence == 1
    assert _count(kb_session, Claim) == 0
