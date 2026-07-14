"""K6：端到端两批材料故事（proposal「验收」段）。

第一批（产品说明书，official_desc/权威2）导入→审核→发布；
第二批（条款，terms/权威1）导入→补全/冲突自动裁决采信条款/高风险进审核→再发布→回滚快照1。
全程零真实模型调用、零真实 WeKnora 调用（respx mock 断言调用序列）。
"""

import json

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.knowledge import (
    MergePolicy,
    current_snapshot_id,
    import_pred_records,
    publish_product_version,
    resolve_review,
    rollback_to_snapshot,
)
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    Conflict,
    ReviewItem,
)
from tests.conftest import BASE_URL
from tests.kbhelpers import BROCHURE, TERMS, pred, seed_bound_scope, seed_product

KB = "kb-wiki"
WIKI = f"{BASE_URL}/api/v1/knowledgebase/{KB}/wiki"

RISK = {"exclusion_clause": "high"}  # 免责条款为高风险字段（03 §6.2）
FIELD_NAMES = {
    "waiting_period": "等待期",
    "grace_period": "宽限期",
    "death_benefit": "身故保险金",
    "exclusion_clause": "责任免除",
}


def _scope(session: Session) -> KnowledgeScope:
    return seed_bound_scope(
        session,
        tenant_id="tenant-e2e",
        raw_kb_id="raw-e2e",
        wiki_kb_id=KB,
    )


def _approve_all_open(session: Session, scope: KnowledgeScope) -> int:
    count = 0
    for item in session.execute(
        select(ReviewItem).where(
            ReviewItem.space_id == scope.space_id,
            ReviewItem.status == "open",
        )
    ).scalars().all():
        resolve_review(
            session,
            scope,
            item.review_key,
            "approve",
            actor="strong-model-agent",
        )
        count += 1
    return count


def _echo(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200, json={"data": {**json.loads(request.content), "id": "p-1"}, "success": True}
    )


@respx.mock
async def test_k6_two_batch_story(kb_session: Session, client: WeKnoraClient) -> None:
    scope = _scope(kb_session)
    product, version = seed_product(kb_session, scope=scope)
    slug = f"product/{product.product_code}/{version.version_label}/overview"

    page_get = respx.get(f"{WIKI}/pages/{slug}")
    page_get.mock(return_value=httpx.Response(404, text="not found"))
    create = respx.post(f"{WIKI}/pages").mock(side_effect=_echo)
    update = respx.put(f"{WIKI}/pages/{slug}").mock(side_effect=_echo)

    # ---- K6.1 第一批：产品说明书（official_desc，权威 2） ----
    batch1 = [
        pred("waiting_period", value="90天", doc=BROCHURE, page=3, quote="等待期为90天",
             field_name="等待期"),
        pred("grace_period", value=None, tri_state="unknown", doc=BROCHURE,
             field_name="宽限期"),  # 空字段，等第二批补全
        pred("exclusion_clause", value="八项免责", doc=BROCHURE, page=9,
             quote="责任免除共八项", field_name="责任免除"),
    ]
    report1 = import_pred_records(
        kb_session, batch1, scope=scope, product_id=product.product_code,
        product_version_id=version.id, risk_of=RISK, legacy_replay=True,
    )
    assert report1.imported == 3 and report1.unknown_placeholders == 1
    approved = _approve_all_open(kb_session, scope)  # 默认保守：全走审核
    assert approved == 2  # unknown 占位不产生审核项

    first = await publish_product_version(
        kb_session, client, scope, product_version_id=version.id, label="r1",
        field_names=FIELD_NAMES, doc_titles={BROCHURE: "产品说明书"},
    )
    assert create.call_count == 1  # 首发 create
    body1 = json.loads(create.calls[0].request.content)
    assert "**等待期**：90天[^" in body1["content"]
    assert "宽限期" not in body1["content"]  # unknown 不得发布为"无"
    assert current_snapshot_id(kb_session, scope) == first.snapshot_id

    # ---- K6.2 第二批：条款（terms，权威 1，权威更高） ----
    batch2 = [
        # 补全空字段（对 unknown 占位做 enrich）
        pred("grace_period", value="60天", doc=TERMS, page=12, quote="宽限期为60日",
             field_name="宽限期"),
        # 新增字段（add）
        pred("death_benefit", value="已交保费与现金价值较大者", doc=TERMS, page=6,
             quote="身故保险金为……", field_name="身故保险金"),
        # 与说明书矛盾的低风险字段 → 权威序①自动裁决采信条款
        pred("waiting_period", value="180天", doc=TERMS, page=5, quote="等待期为180天",
             field_name="等待期"),
        # 与说明书矛盾的高风险字段 → 跳过④直接⑤审核
        pred("exclusion_clause", value="十项免责", doc=TERMS, page=10,
             quote="责任免除共十项", field_name="责任免除"),
    ]
    report2 = import_pred_records(
        kb_session, batch2, scope=scope, product_id=product.product_code,
        product_version_id=version.id, risk_of=RISK, legacy_replay=True,
        # 019 Q4.1：故事断言低风险 supersede 自动裁决，显式开启（无 gate=legacy 布尔位）。
        policy=MergePolicy(auto_apply_supersede_low_risk=True),
    )
    assert report2.imported == 4
    assert report2.merge.actions.get("enrich") == 1  # 补全
    assert report2.merge.actions.get("add") == 1
    # 两个矛盾字段权威序均判条款胜：低风险自动应用、高风险停审核（各留 Conflict 记录）
    assert report2.merge.actions.get("supersede") == 2
    assert report2.judge_queue == []  # 零模型调用：本故事未触发④

    # 低风险矛盾：conflict 留痕 + 权威序自动裁决为条款值，旧 Claim superseded
    waiting_claims = {
        c.status: c
        for c in kb_session.execute(
            select(Claim).where(
                Claim.space_id == scope.space_id,
                Claim.predicate == "waiting_period",
            )
        ).scalars()
    }
    assert waiting_claims["published"].value == {"text": "180天"}
    assert waiting_claims["superseded"].superseded_by == waiting_claims["published"].id
    auto_conflict = kb_session.execute(
        select(Conflict)
        .join(ChangeItem, ChangeItem.id == Conflict.change_item_id)
        .join(ChangeSet, ChangeSet.id == ChangeItem.change_set_id)
        .where(
            ChangeSet.space_id == scope.space_id,
            Conflict.status == "resolved",
        )
    ).scalar_one()
    assert auto_conflict.decision_basis is not None
    assert "proposed=1 existing=2" in auto_conflict.decision_basis["authority_cmp"]
    assert "proposed 胜" in auto_conflict.decision_basis["authority_cmp"]  # 留痕

    # 高风险矛盾：旧值保持 published、新值 candidate、ReviewItem 待审
    exclusion_open = kb_session.execute(
        select(Conflict)
        .join(ChangeItem, ChangeItem.id == Conflict.change_item_id)
        .join(ChangeSet, ChangeSet.id == ChangeItem.change_set_id)
        .where(
            ChangeSet.space_id == scope.space_id,
            Conflict.status == "open",
        )
    ).scalar_one()
    assert exclusion_open.decision_basis is not None
    published_exclusion = kb_session.execute(
        select(Claim).where(
            Claim.space_id == scope.space_id,
            Claim.predicate == "exclusion_clause",
            Claim.status == "published",
        )
    ).scalar_one()
    assert published_exclusion.value == {"text": "八项免责"}  # 冲突未决生产不中断

    # 审核流：approve 补全/新增/高风险采信条款
    assert _approve_all_open(kb_session, scope) == 3
    kb_session.refresh(published_exclusion)
    assert published_exclusion.status == "superseded"

    # ---- K6.3 再发布：update 调用，内容含条款新值 ----
    page_get.mock(return_value=_echo(create.calls[0].request))  # 页面已存在
    second = await publish_product_version(
        kb_session, client, scope, product_version_id=version.id, label="r2",
        field_names=FIELD_NAMES,
        doc_titles={BROCHURE: "产品说明书", TERMS: "保险条款"},
    )
    assert update.call_count == 1  # 二发 update（同 slug 不再 create）
    body2 = json.loads(update.calls[0].request.content)
    assert "**等待期**：180天[^" in body2["content"]  # 采信条款值
    assert "**宽限期**：60天[^" in body2["content"]  # 空字段被补全
    assert "**责任免除**：十项免责[^" in body2["content"]
    assert current_snapshot_id(kb_session, scope) == second.snapshot_id

    # ---- K6.4 回滚到快照1：内容逐字一致恢复 + 指针回切 + rollback 留痕 ----
    rollback = await rollback_to_snapshot(
        kb_session, client, scope, snapshot_id=first.snapshot_id, actor="operator"
    )
    assert update.call_count == 2
    body3 = json.loads(update.calls[1].request.content)
    assert body3["content"] == body1["content"]  # 与首次发布逐字一致
    assert body3["page_metadata"]["snapshot_id"] == first.snapshot_id
    assert current_snapshot_id(kb_session, scope) == first.snapshot_id
    assert rollback.change_set_id
    rollback_set = kb_session.get(ChangeSet, rollback.change_set_id)
    assert rollback_set is not None and rollback_set.source_kind == "rollback"

    # ---- K6.5 调用序列：1 create + 2 update，无其他真实调用 ----
    assert create.call_count == 1 and update.call_count == 2
