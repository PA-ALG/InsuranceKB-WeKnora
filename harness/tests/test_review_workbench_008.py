"""008 审核工作台——分任务红绿（测试名引用条款号 W1~W7）。

本文件按 tasks 顺序增量生长：T1（W5.2/W6.1 鉴权与 Space fail-closed）先行。
零模型调用；对 knowledge/ 只经服务层（W5.1 由静态断言钉住，见 T7 波次）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from insurance_harness.db.base import Base, make_engine, make_session_factory
from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import bind_space

# ---------------------------------------------------------------------------
# 夹具：文件型 sqlite（知识域表齐），app 与测试共享同一 engine
# ---------------------------------------------------------------------------


@pytest.fixture
def wb_env(tmp_path: Path) -> Iterator[tuple[Callable[[], Session], Session]]:
    from insurance_harness.db import models as _db_models  # noqa: F401
    from insurance_harness.knowledge import tables as _kb_tables  # noqa: F401

    engine = make_engine(f"sqlite:///{tmp_path}/wb.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    session = factory()
    yield factory, session
    session.close()
    engine.dispose()


def _bound_space(session: Session, name: str, sfx: str) -> str:
    row = KnowledgeSpace(name=name, binding_status="unbound")
    session.add(row)
    session.flush()
    bind_space(
        session, row.id,
        tenant_id=f"tenant-{sfx}", raw_kb_id=f"raw-{sfx}", wiki_kb_id=f"wiki-{sfx}",
    )
    session.commit()
    return str(row.id)


_TOKENS = {
    "tok-alice": {"principal": "alice", "space_ids": ["__A__"]},
}


def _client(
    factory: Callable[[], Session], space_a: str, extra: dict[str, object] | None = None
) -> TestClient:
    from insurance_harness.workbench.app import create_app

    tokens: dict[str, object] = {
        "tok-alice": {"principal": "alice", "space_ids": [space_a]},
    }
    if extra:
        tokens.update(extra)
    return TestClient(create_app(session_factory=factory, tokens_config=tokens))


# ---------------------------------------------------------------------------
# T1 · W5.2/W6.1 鉴权与 Space fail-closed
# ---------------------------------------------------------------------------


def test_w5_2_no_token_401(wb_env: tuple[Callable[[], Session], Session]) -> None:
    factory, session = wb_env
    space_a = _bound_space(session, "甲", "a")
    client = _client(factory, space_a)
    resp = client.get(f"/spaces/{space_a}/queue")
    assert resp.status_code == 401


def test_w5_2_unknown_token_401(wb_env: tuple[Callable[[], Session], Session]) -> None:
    factory, session = wb_env
    space_a = _bound_space(session, "甲", "a")
    client = _client(factory, space_a)
    resp = client.get(
        f"/spaces/{space_a}/queue", headers={"Authorization": "Bearer nope"}
    )
    assert resp.status_code == 401


def test_w5_2_no_tokens_configured_denies_all_fail_closed(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """未配置任何 token = 拒绝一切（fail-closed 默认，非放行）。"""
    from insurance_harness.workbench.app import create_app

    factory, session = wb_env
    space_a = _bound_space(session, "甲", "a")
    client = TestClient(create_app(session_factory=factory, tokens_config={}))
    resp = client.get(
        f"/spaces/{space_a}/queue", headers={"Authorization": "Bearer tok-alice"}
    )
    assert resp.status_code == 401


def test_w6_1_token_cannot_cross_space_403_zero_leak(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """token A 请求 Space B → 403 且响应零业务数据泄露（W6 Scenario）。"""
    factory, session = wb_env
    space_a = _bound_space(session, "甲", "a")
    space_b = _bound_space(session, "乙", "b")
    client = _client(factory, space_a)
    resp = client.get(
        f"/spaces/{space_b}/queue", headers={"Authorization": "Bearer tok-alice"}
    )
    assert resp.status_code == 403
    body = resp.text
    assert "乙" not in body and space_b not in body, "403 响应不得回显目标 space 细节"


def test_w6_1_allowed_space_ok(wb_env: tuple[Callable[[], Session], Session]) -> None:
    factory, session = wb_env
    space_a = _bound_space(session, "甲", "a")
    client = _client(factory, space_a)
    resp = client.get(
        f"/spaces/{space_a}/queue", headers={"Authorization": "Bearer tok-alice"}
    )
    assert resp.status_code == 200
    assert "审核队列" in resp.text


# ---------------------------------------------------------------------------
# T2 · W1.1/W2.1/W3.1 只读查询数据形状
# ---------------------------------------------------------------------------


def _seed_product(session: Session, space: str, code: str, name: str) -> str:
    from insurance_harness.db.models import InsuranceProduct, ProductVersion

    p = InsuranceProduct(
        space_id=space, product_code=code, canonical_name=name,
        category="t", status="在售",
    )
    session.add(p)
    session.flush()
    v = ProductVersion(space_id=space, product_id=p.id, version_label="V1")
    session.add(v)
    session.flush()
    return str(v.id)


def _seed_claim(
    session: Session, space: str, version_id: str, predicate: str,
    value_state: str = "present", status: str = "published",
) -> str:
    from insurance_harness.knowledge.tables import Claim

    c = Claim(
        space_id=space, product_version_id=version_id, predicate=predicate,
        value_state=value_state, value={"text": "90天"}, status=status,
    )
    session.add(c)
    session.flush()
    return str(c.id)


def _seed_review(
    session: Session, space: str, version_id: str, *,
    key: str, risk: str = "low", type_: str = "low_confidence",
    predicate: str = "waiting_period", status: str = "open",
    applyable: bool = False,
) -> str:
    """种子工单。``applyable=True`` 造全链（draft Claim+Evidence+claim_id），
    使 approve 能走真实 publish_claim（T3 动作用例）。"""
    from insurance_harness.knowledge.tables import (
        ChangeItem,
        ChangeSet,
        Claim,
        ClaimEvidence,
        ReviewItem,
    )

    claim_id: str | None = None
    if applyable:
        draft = Claim(
            space_id=space, product_version_id=version_id, predicate=predicate,
            value_state="present", value={"text": "90天"}, status="draft",
        )
        session.add(draft)
        session.flush()
        session.add(
            ClaimEvidence(
                claim_id=draft.id, knowledge_id="doc-1", quote="等待期为90天",
                page=1, authority_level=2, doc_role="clause",
            )
        )
        session.flush()
        claim_id = str(draft.id)
    cs = ChangeSet(space_id=space, source_kind="document", status="pending", created_by="t")
    session.add(cs)
    session.flush()
    item = ChangeItem(
        change_set_id=cs.id, action="add", claim_id=claim_id,
        proposed={"predicate": predicate, "product_version_id": version_id},
        decision="needs_review",
    )
    session.add(item)
    session.flush()
    r = ReviewItem(
        space_id=space, review_key=key, type=type_,
        subject={
            "change_item_id": item.id, "predicate": predicate,
            "new_claim_id": claim_id,
        },
        allowed_actions=["approve", "reject", "defer"], status=status, risk_level=risk,
    )
    session.add(r)
    session.commit()
    return key


def test_w1_1_queue_query_filters_sorts_paginates(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    from insurance_harness.db.scope import load_scope
    from insurance_harness.workbench.queries import list_review_queue

    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    vid = _seed_product(session, space, "P001", "测试终身寿")
    _seed_review(session, space, vid, key="k1", risk="low", type_="low_confidence")
    _seed_review(session, space, vid, key="k2", risk="high", type_="high_risk_change")
    _seed_review(session, space, vid, key="k3", risk="high", type_="quality_gate")
    _seed_review(session, space, vid, key="k4", risk="low", status="resolved")
    scope = load_scope(session, space)
    page = list_review_queue(session, scope)
    assert [i.risk_level for i in page.items[:2]] == ["high", "high"], "高风险默认排前"
    assert all(i.status == "open" for i in page.items), "默认只列 open"
    assert page.total == 3
    only_gate = list_review_queue(session, scope, type_="quality_gate")
    assert [i.review_key for i in only_gate.items] == ["k3"]
    paged = list_review_queue(session, scope, limit=2, offset=2)
    assert len(paged.items) == 1 and paged.total == 3


def test_w2_1_changeset_list_with_action_counts(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    from insurance_harness.db.scope import load_scope
    from insurance_harness.knowledge.tables import ChangeItem, ChangeSet
    from insurance_harness.workbench.queries import list_change_sets

    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    cs = ChangeSet(space_id=space, source_kind="document", status="applied", created_by="t")
    session.add(cs)
    session.flush()
    session.add_all([
        ChangeItem(change_set_id=cs.id, action="add", proposed={}, decision="auto_applied"),
        ChangeItem(change_set_id=cs.id, action="conflict", proposed={}, decision="needs_review"),
    ])
    session.commit()
    scope = load_scope(session, space)
    rows = list_change_sets(session, scope)
    assert rows[0].source_kind == "document" and rows[0].status == "applied"
    assert rows[0].action_counts == {"add": 1, "conflict": 1}


def test_w3_1_completeness_matrix_five_states(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """五态格：published present / absent / unknown / 冲突中 / 待审（W3.1）。"""
    from insurance_harness.db.scope import load_scope
    from insurance_harness.knowledge.tables import ChangeItem, ChangeSet, Conflict
    from insurance_harness.workbench.queries import completeness_matrix

    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    vid = _seed_product(session, space, "P001", "测试终身寿")
    _seed_claim(session, space, vid, "f_present", "present")
    _seed_claim(session, space, vid, "f_absent", "absent_explicitly")
    _seed_claim(session, space, vid, "f_unknown", "unknown")
    # 冲突中：open Conflict 挂 f_conflict
    cs = ChangeSet(space_id=space, source_kind="document", status="pending", created_by="t")
    session.add(cs)
    session.flush()
    ci = ChangeItem(
        change_set_id=cs.id, action="conflict",
        proposed={"predicate": "f_conflict", "product_version_id": vid},
        decision="needs_review",
    )
    session.add(ci)
    session.flush()
    session.add(Conflict(change_item_id=ci.id, proposed={"predicate": "f_conflict"}, status="open"))
    session.commit()
    # 待审：open ReviewItem 挂 f_review
    _seed_review(session, space, vid, key="kr", predicate="f_review")
    scope = load_scope(session, space)
    matrix = completeness_matrix(session, scope)
    row = next(r for r in matrix.rows if r.product_code == "P001")
    assert row.cells["f_present"] == "present"
    assert row.cells["f_absent"] == "absent_explicitly"
    assert row.cells["f_unknown"] == "unknown"
    assert row.cells["f_conflict"] == "conflict_open", "开放冲突优先于三态"
    assert row.cells["f_review"] == "pending_review"


def test_w5_1_queries_readonly_no_pending_writes(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    from insurance_harness.db.scope import load_scope
    from insurance_harness.workbench.queries import (
        completeness_matrix,
        list_change_sets,
        list_review_queue,
    )

    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    vid = _seed_product(session, space, "P001", "测试终身寿")
    _seed_review(session, space, vid, key="k1")
    scope = load_scope(session, space)
    list_review_queue(session, scope)
    list_change_sets(session, scope)
    completeness_matrix(session, scope)
    assert not session.dirty and not session.new and not session.deleted, (
        "查询模块必须只读（W5.1）"
    )


# ---------------------------------------------------------------------------
# T3 · W1 队列页与三动作（幂等/已决拒绝/审计归属）
# ---------------------------------------------------------------------------


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer tok-alice"}


def _review_status(
    session: Session, space: str, key: str
) -> tuple[str, dict[str, object] | None]:
    from sqlalchemy import select as _select

    from insurance_harness.knowledge.tables import ReviewItem

    session.expire_all()
    row = session.execute(
        _select(ReviewItem).where(
            ReviewItem.space_id == space, ReviewItem.review_key == key
        )
    ).scalar_one()
    return row.status, row.resolution


def test_w1_1_queue_page_renders_items_with_badges(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    vid = _seed_product(session, space, "P001", "测试终身寿")
    _seed_review(session, space, vid, key="kq1", risk="high", type_="quality_gate")
    _seed_review(session, space, vid, key="kq2", risk="low")
    client = _client(factory, space)
    resp = client.get(f"/spaces/{space}/queue", headers=_auth())
    assert resp.status_code == 200
    body = resp.text
    assert "kq1" in body and "kq2" in body
    assert "quality_gate" in body, "gate 工单正常展示且带类型徽标（W7.3）"
    assert "high" in body


def test_w1_3_approve_publishes_and_resolves(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    from sqlalchemy import select as _select

    from insurance_harness.knowledge.tables import Claim

    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    vid = _seed_product(session, space, "P001", "测试终身寿")
    _seed_review(session, space, vid, key="ka1", applyable=True)
    client = _client(factory, space)
    resp = client.post(
        f"/spaces/{space}/queue/ka1/action",
        headers=_auth(), data={"action": "approve", "reason": "看过证据"},
    )
    assert resp.status_code == 200
    status, resolution = _review_status(session, space, "ka1")
    assert status == "resolved" and resolution and resolution["action"] == "approve"
    session.expire_all()
    published = session.execute(
        _select(Claim).where(Claim.space_id == space, Claim.status == "published")
    ).scalars().all()
    assert len(published) == 1, "approve 经服务层真实发布 draft Claim"


def test_w1_3_reject_and_defer(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    vid = _seed_product(session, space, "P001", "测试终身寿")
    _seed_review(session, space, vid, key="kr1", applyable=True)
    _seed_review(session, space, vid, key="kd1", applyable=True)
    client = _client(factory, space)
    assert client.post(
        f"/spaces/{space}/queue/kr1/action", headers=_auth(), data={"action": "reject"}
    ).status_code == 200
    status, resolution = _review_status(session, space, "kr1")
    assert status == "resolved" and resolution and resolution["action"] == "reject"
    assert client.post(
        f"/spaces/{space}/queue/kd1/action", headers=_auth(), data={"action": "defer"}
    ).status_code == 200
    status, resolution = _review_status(session, space, "kd1")
    assert status == "open" and resolution is None, "defer 保持 open 不落 resolution"


def test_w1_4_same_action_resubmit_idempotent(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    from sqlalchemy import func as _func
    from sqlalchemy import select as _select

    from insurance_harness.knowledge.tables import Claim

    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    vid = _seed_product(session, space, "P001", "测试终身寿")
    _seed_review(session, space, vid, key="ki1", applyable=True)
    client = _client(factory, space)
    url = f"/spaces/{space}/queue/ki1/action"
    assert client.post(url, headers=_auth(), data={"action": "approve"}).status_code == 200
    second = client.post(url, headers=_auth(), data={"action": "approve"})
    assert second.status_code == 200, "同决定重复提交幂等（W1.3）"
    session.expire_all()
    n_published = session.execute(
        _select(_func.count()).select_from(Claim).where(
            Claim.space_id == space, Claim.status == "published"
        )
    ).scalar_one()
    assert n_published == 1, "重复提交不得重复生效"


def test_w1_4_conflicting_action_on_resolved_409(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    vid = _seed_product(session, space, "P001", "测试终身寿")
    _seed_review(session, space, vid, key="kc1", applyable=True)
    client = _client(factory, space)
    url = f"/spaces/{space}/queue/kc1/action"
    assert client.post(url, headers=_auth(), data={"action": "approve"}).status_code == 200
    conflict = client.post(url, headers=_auth(), data={"action": "reject"})
    assert conflict.status_code == 409, "异决定撞已决 → 409 提示刷新（乐观并发）"


def test_w6_3_audit_actor_is_token_principal_not_client_field(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    vid = _seed_product(session, space, "P001", "测试终身寿")
    _seed_review(session, space, vid, key="kp1", applyable=True)
    client = _client(factory, space)
    resp = client.post(
        f"/spaces/{space}/queue/kp1/action",
        headers=_auth(),
        data={"action": "approve", "operator": "mallory"},  # 客户端自报必须被无视
    )
    assert resp.status_code == 200
    _status, resolution = _review_status(session, space, "kp1")
    assert resolution and resolution["actor"] == "alice", (
        "审计 operator 只认 token principal（W6 Scenario：不可伪造）"
    )


def test_w1_3_batch_approve_excludes_high(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    vid = _seed_product(session, space, "P001", "测试终身寿")
    _seed_review(session, space, vid, key="kb-low", risk="low", applyable=True)
    _seed_review(
        session, space, vid, key="kb-high", risk="high",
        predicate="f2", applyable=True,
    )
    client = _client(factory, space)
    resp = client.post(
        f"/spaces/{space}/queue/batch-approve",
        headers=_auth(), data={"keys": ["kb-low", "kb-high"]},
    )
    assert resp.status_code == 200
    assert "kb-high" in resp.text, "被排除的高风险项显式提示（不得静默跳过）"
    low_status, _ = _review_status(session, space, "kb-low")
    high_status, _ = _review_status(session, space, "kb-high")
    assert low_status == "resolved" and high_status == "open", "批量仅非 high 生效"


# ---------------------------------------------------------------------------
# T4 · W2 冲突与变更页 + 翻案 + G8 时间线
# ---------------------------------------------------------------------------


def test_w2_1_changes_page_lists_sets_with_counts(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    from insurance_harness.knowledge.tables import ChangeItem, ChangeSet

    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    cs = ChangeSet(space_id=space, source_kind="document", status="applied", created_by="t")
    session.add(cs)
    session.flush()
    session.add_all([
        ChangeItem(change_set_id=cs.id, action="add", proposed={}, decision="auto_applied"),
        ChangeItem(change_set_id=cs.id, action="supersede", proposed={}, decision="approved"),
    ])
    session.commit()
    client = _client(factory, space)
    resp = client.get(f"/spaces/{space}/changes", headers=_auth())
    assert resp.status_code == 200
    assert str(cs.id) in resp.text and "document" in resp.text
    assert "add" in resp.text and "supersede" in resp.text, "动作计数用于分色展示"


def test_w2_2_detail_shows_conflict_both_sides_and_basis(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    from insurance_harness.knowledge.tables import ChangeItem, ChangeSet, Conflict

    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    vid = _seed_product(session, space, "P001", "测试终身寿")
    existing_id = _seed_claim(session, space, vid, "f_dispute", "present")  # 值=90天
    cs = ChangeSet(space_id=space, source_kind="document", status="pending", created_by="t")
    session.add(cs)
    session.flush()
    ci = ChangeItem(
        change_set_id=cs.id, action="conflict",
        proposed={
            "predicate": "f_dispute", "product_version_id": vid,
            "value": {"text": "180天"},
        },
        decision="needs_review",
    )
    session.add(ci)
    session.flush()
    session.add(
        Conflict(
            change_item_id=ci.id, existing_claim_id=existing_id,
            proposed={"value": {"text": "180天"}},
            decision_basis={"rule": "authority_order", "existing": 2, "proposed": 5},
            status="open",
        )
    )
    session.commit()
    client = _client(factory, space)
    resp = client.get(f"/spaces/{space}/changes/{cs.id}", headers=_auth())
    assert resp.status_code == 200
    body = resp.text
    assert "90天" in body and "180天" in body, "冲突双方值并排展示（W2.2）"
    assert "authority_order" in body, "自动裁决依据（权威序比较）可见"
    assert "action-conflict" in body, "动作分色标记"


def test_w2_3_overturn_creates_new_changeset_history_intact(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    from sqlalchemy import select as _select

    from insurance_harness.knowledge.tables import ChangeItem, ChangeSet, Claim

    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    vid = _seed_product(session, space, "P001", "测试终身寿")
    _seed_review(session, space, vid, key="ko1", applyable=True)
    client = _client(factory, space)
    assert client.post(
        f"/spaces/{space}/queue/ko1/action", headers=_auth(), data={"action": "approve"}
    ).status_code == 200
    # 缺 reason → 400（翻案必须留理由）
    assert client.post(
        f"/spaces/{space}/queue/ko1/overturn", headers=_auth(),
        data={"new_action": "reject"},
    ).status_code in (400, 422)
    resp = client.post(
        f"/spaces/{space}/queue/ko1/overturn", headers=_auth(),
        data={"new_action": "reject", "reason": "证据不足"},
    )
    assert resp.status_code == 200
    session.expire_all()
    manual_sets = session.execute(
        _select(ChangeSet).where(
            ChangeSet.space_id == space, ChangeSet.source_kind == "manual_edit"
        )
    ).scalars().all()
    assert len(manual_sets) == 1, "翻案 = 新 ChangeSet（W2.3）"
    assert str(manual_sets[0].id) in resp.text
    original_items = session.execute(
        _select(ChangeItem).where(ChangeItem.action == "add")
    ).scalars().all()
    assert all(i.decision == "approved" for i in original_items), "原决定不改写"
    retracted = session.execute(
        _select(Claim).where(Claim.space_id == space, Claim.status == "retracted")
    ).scalars().all()
    assert len(retracted) == 1, "翻案 reject → 已采纳 Claim 撤回"


def test_w2_4_timeline_human_readable_rows(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """G8：谁/何时/什么字段/旧值→新值/原因（按产品聚合）。"""
    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    vid = _seed_product(session, space, "P001", "测试终身寿")
    _seed_review(session, space, vid, key="kt1", applyable=True)
    client = _client(factory, space)
    assert client.post(
        f"/spaces/{space}/queue/kt1/action",
        headers=_auth(), data={"action": "approve", "reason": "证据充分"},
    ).status_code == 200
    resp = client.get(f"/spaces/{space}/timeline", headers=_auth())
    assert resp.status_code == 200
    body = resp.text
    assert "alice" in body, "谁"
    assert "P001" in body, "按产品聚合"
    assert "waiting_period" in body, "什么字段"
    assert "90天" in body, "新值"
    assert "证据充分" in body, "原因"


# ---------------------------------------------------------------------------
# T5 · W3 完整度矩阵页 + 下钻 + 导出
# ---------------------------------------------------------------------------


def _seed_matrix_env(session: Session, space: str) -> str:
    vid = _seed_product(session, space, "P001", "测试终身寿")
    _seed_claim(session, space, vid, "f_present", "present")
    _seed_claim(session, space, vid, "f_unknown", "unknown")
    _seed_review(session, space, vid, key="km1", predicate="f_review")
    return vid


def test_w3_1_matrix_page_renders_state_cells(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    _seed_matrix_env(session, space)
    client = _client(factory, space)
    resp = client.get(f"/spaces/{space}/matrix", headers=_auth())
    assert resp.status_code == 200
    body = resp.text
    assert "P001" in body and "测试终身寿" in body
    assert "state-present" in body and "state-unknown" in body
    assert "state-pending_review" in body, "待审格分色（W3.1）"


def test_w3_2_cell_drilldown_shows_claim_evidence_history(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    vid = _seed_product(session, space, "P001", "测试终身寿")
    _seed_review(session, space, vid, key="kd2", applyable=True)
    client = _client(factory, space)
    assert client.post(
        f"/spaces/{space}/queue/kd2/action",
        headers=_auth(), data={"action": "approve", "reason": "ok"},
    ).status_code == 200
    resp = client.get(
        f"/spaces/{space}/matrix/{vid}/waiting_period", headers=_auth()
    )
    assert resp.status_code == 200
    body = resp.text
    assert "90天" in body, "Claim 值"
    assert "等待期为90天" in body, "证据引文（W3.2 下钻）"
    assert "alice" in body, "版本历史（修订链）"


def test_w3_3_export_csv_and_jsonl(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    import json as _json

    factory, session = wb_env
    space = _bound_space(session, "甲", "a")
    _seed_matrix_env(session, space)
    client = _client(factory, space)
    csv_resp = client.get(
        f"/spaces/{space}/matrix/export", headers=_auth(), params={"fmt": "csv"}
    )
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    lines = [ln for ln in csv_resp.text.strip().splitlines() if ln]
    assert lines[0].startswith("product_code,"), "CSV 表头"
    assert any("f_present" in ln and "present" in ln for ln in lines[1:])
    jsonl_resp = client.get(
        f"/spaces/{space}/matrix/export", headers=_auth(), params={"fmt": "jsonl"}
    )
    assert jsonl_resp.status_code == 200
    rows = [_json.loads(ln) for ln in jsonl_resp.text.strip().splitlines()]
    review_rows = [r for r in rows if r["field"] == "f_review"]
    assert review_rows and review_rows[0]["state"] == "pending_review"
    assert "ticket_source" in rows[0], "工单来源标注列（011/015 前允许为空，W3.3）"


# ---------------------------------------------------------------------------
# T7 · 守卫钉：跨空间不可见 / 路由白名单 / 静态零写（回归销）
# ---------------------------------------------------------------------------


def test_w6_2_cross_space_same_business_key_invisible(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space_a = _bound_space(session, "甲", "a")
    space_b = _bound_space(session, "乙", "b")
    vid_a = _seed_product(session, space_a, "P001", "甲产品")
    vid_b = _seed_product(session, space_b, "P001", "乙产品")
    _seed_review(session, space_a, vid_a, key="same-key")
    _seed_review(session, space_b, vid_b, key="same-key")
    client = _client(
        factory, space_a,
        extra={"tok-bob": {"principal": "bob", "space_ids": [space_b]}},
    )
    body_a = client.get(f"/spaces/{space_a}/queue", headers=_auth()).text
    body_b = client.get(
        f"/spaces/{space_b}/queue", headers={"Authorization": "Bearer tok-bob"}
    ).text
    assert "same-key" in body_a and "same-key" in body_b
    assert "乙产品" not in body_a and "甲产品" not in body_b, "同业务键跨 space 互不可见"


def test_w7_3_route_allowlist_no_bypass_endpoints(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """无任何绕过闸门的发布类端点（W7.3：无此按钮、无此端点）。"""
    from fastapi.routing import APIRoute

    from insurance_harness.workbench.app import create_app

    factory, _session = wb_env
    app = create_app(session_factory=factory, tokens_config={})
    paths = {
        (r.path, m)
        for r in app.routes
        if isinstance(r, APIRoute)
        for m in (r.methods or set())
        if m != "HEAD"
    }
    allowlist = {
        ("/spaces/{space_id}/queue", "GET"),
        ("/spaces/{space_id}/queue/{review_key}/action", "POST"),
        ("/spaces/{space_id}/queue/{review_key}/overturn", "POST"),
        ("/spaces/{space_id}/queue/batch-approve", "POST"),
        ("/spaces/{space_id}/changes", "GET"),
        ("/spaces/{space_id}/changes/{change_set_id}", "GET"),
        ("/spaces/{space_id}/timeline", "GET"),
        ("/spaces/{space_id}/matrix", "GET"),
        ("/spaces/{space_id}/matrix/export", "GET"),
        ("/spaces/{space_id}/matrix/{version_id}/{predicate}", "GET"),
    }
    assert paths == allowlist, f"路由表漂移：{paths ^ allowlist}"
    forbidden_words = ("publish", "force", "rollback", "release")
    assert not [p for p, _ in paths if any(w in p for w in forbidden_words)]


def test_w6_2_cross_space_object_id_probe_404_not_leak(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """gauntlet 对称路径：持双空间授权的 token，用 A 的 ChangeSet id 走 B 路径
    → 404（对象归属校验独立于 token 授权，不泄露存在性）。"""
    from insurance_harness.knowledge.tables import ChangeSet

    factory, session = wb_env
    space_a = _bound_space(session, "甲", "a")
    space_b = _bound_space(session, "乙", "b")
    cs = ChangeSet(space_id=space_a, source_kind="document", status="applied", created_by="t")
    session.add(cs)
    session.commit()
    client = _client(
        factory, space_a,
        extra={"tok-both": {"principal": "carol", "space_ids": [space_a, space_b]}},
    )
    resp = client.get(
        f"/spaces/{space_b}/changes/{cs.id}",
        headers={"Authorization": "Bearer tok-both"},
    )
    assert resp.status_code == 404, "A 的对象在 B 路径下必须 404（越权探测不可用）"


def test_w5_1_static_no_direct_sql_writes_in_workbench() -> None:
    """静态零写扫描：workbench 包不得出现直接写库调用（写只经服务层）。"""
    import insurance_harness.workbench as wb

    pkg_dir = Path(wb.__file__).parent
    forbidden = ("session.add(", "session.add_all(", ".delete(", "insert(", "update(")
    hits: list[str] = []
    for py in pkg_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for pattern in forbidden:
            if pattern in text:
                hits.append(f"{py.name}:{pattern}")
    assert not hits, f"W5.1 违例（直接 SQL 写）：{hits}"


def test_w6_1_unbound_space_fail_closed_403(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """space 在允许集内但未绑定（016 语义）→ 同样 fail-closed，不落任何查询。"""
    factory, session = wb_env
    row = KnowledgeSpace(name="未绑定", binding_status="unbound")
    session.add(row)
    session.commit()
    unbound = str(row.id)
    client = _client(
        factory, unbound,
    )
    resp = client.get(
        f"/spaces/{unbound}/queue", headers={"Authorization": "Bearer tok-alice"}
    )
    assert resp.status_code == 403
