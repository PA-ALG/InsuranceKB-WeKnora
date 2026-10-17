"""008 审核工作台——分任务红绿（测试名引用条款号 W1~W7）。

PR#15 评审返工版：主正向用例一律经 **真实 MergeEngine** 造数（tests/wbhelpers），
不再手写扁平 ``proposed``；翻案断言两阶段状态机；并发断言版本合同；W7 用真实
QualityGate 三类拒绝；矩阵断言 schema 全字段底图与缺口导出语义。
零模型调用；对 knowledge/ 只经服务层（W5.1 静态断言钉住）。
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import func as _func
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.scope import load_scope
from insurance_harness.knowledge import MergePolicy
from insurance_harness.knowledge.tables import (
    Claim,
    ReviewItem,
)
from tests.wbhelpers import (
    bound_space,
    current_version,
    open_review_key,
    prop,
    real_gate,
    run_merge,
    seed_wb_product,
)


def test_w1_4_request_id_replay_does_not_duplicate(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """同 request_id 同动作重放（如浏览器重试）不重复记事件、不重复生效。"""
    from insurance_harness.knowledge import resolve_review

    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    key = open_review_key(session, space, vid)
    scope = load_scope(session, space)
    v1 = current_version(session, space, key)
    resolve_review(
        session, scope, key, "defer", actor="alice",
        expected_version=v1, request_id="req-1",
    )
    # 同 request_id 重放：连 stale 版本都不需要——重放判定先于前置校验
    resolve_review(
        session, scope, key, "defer", actor="alice",
        expected_version=v1, request_id="req-1",
    )
    resolve_review(
        session, scope, key, "defer", actor="alice",
        expected_version=current_version(session, space, key),
        request_id="req-2",
    )
    session.commit()
    item = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key)
    ).scalar_one()
    events = (item.resolution or {}).get("events") or []
    assert len(events) == 2, "req-1 重放不得重复记事件"


def _gate_denied_review(
    session: Session, space: str, vid: str, kind: str
) -> ReviewItem:
    gate, fp = real_gate(kind)
    scope = load_scope(session, space)
    run_merge(
        session, space, [prop(scope, vid)],
        external_id=f"gate-{kind}",
        policy=MergePolicy(auto_apply_add=True),
        quality_gate=gate, run_fingerprint=fp,
    )
    return session.execute(
        select(ReviewItem).where(ReviewItem.status == "open")
    ).scalar_one()


def test_w7_real_gate_denials_create_quality_gate_reviews(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """运营允许自动化但真实 QualityGate 拒绝（缺画像/stale/不达标）→
    type=quality_gate 且拒绝原因持久化（不再手工造 gate 工单）。"""
    factory, session = wb_env
    for i, (kind, reason_part) in enumerate(
        (("missing", "缺字段画像"),
         ("stale", "指纹不匹配"),
         ("threshold", "指标未达阈值")),
    ):
        space = bound_space(session, f"g{i}")
        vid = seed_wb_product(session, space, code=f"P00{i + 1}")
        item = _gate_denied_review(session, space, vid, kind)
        assert item.type == "quality_gate", f"{kind}: 真实 gate 拒绝须标 quality_gate"
        gate_meta = (item.subject or {}).get("gate") or {}
        if kind == "stale":
            assert "stale" in gate_meta.get("reason", "") or "指纹" in gate_meta.get(
                "reason", ""
            )
        else:
            assert reason_part in gate_meta.get("reason", ""), f"{kind} 原因持久化"
        if kind != "missing":
            assert gate_meta.get("profile_version") == "1", "画像标识"
            assert gate_meta.get("baseline_id") == "wb-baseline", "基线标识"
        # 清场：resolve 掉便于下一轮 scalar_one
        from tests.kbhelpers import resolve_with_version

        resolve_with_version(
            session, load_scope(session, space), item.review_key, "reject",
            actor="t",
        )
        session.commit()


def test_w7_policy_off_denial_is_not_quality_gate_type(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """运营策略未放行自动化（保守默认）→ 普通 low_confidence，不冒充 gate 拒绝。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    gate, fp = real_gate("passing")
    scope = load_scope(session, space)
    run_merge(
        session, space, [prop(scope, vid)], external_id="no-policy",
        quality_gate=gate, run_fingerprint=fp,  # policy 默认全审核
    )
    item = session.execute(
        select(ReviewItem).where(ReviewItem.status == "open")
    ).scalar_one()
    assert item.type == "low_confidence"
    assert "gate" not in (item.subject or {}), "未咨询 gate 不得伪造 gate 元数据"


def test_w7_passing_gate_with_policy_auto_publishes(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """对照组：真实 gate 达标 + 策略放行 → 自动发布（gate 语义未被破坏）。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    gate, fp = real_gate("passing")
    scope = load_scope(session, space)
    run_merge(
        session, space, [prop(scope, vid)], external_id="auto",
        policy=MergePolicy(auto_apply_add=True),
        quality_gate=gate, run_fingerprint=fp,
    )
    claim = session.execute(select(Claim)).scalar_one()
    assert claim.status == "published"
    assert session.execute(
        select(_func.count()).select_from(ReviewItem)
    ).scalar_one() == 0


def test_w1_4_service_layer_precondition_required(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """服务边界二次强制(不依赖路由):open 项缺任一令牌 → ReviewPreconditionRequired,零写。"""
    import pytest as _pytest

    from insurance_harness.knowledge import (
        ReviewPreconditionRequired,
        resolve_review,
    )

    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    key = open_review_key(session, space, vid)
    scope = load_scope(session, space)
    with _pytest.raises(ReviewPreconditionRequired) as exc1:
        resolve_review(session, scope, key, "approve", actor="a")
    assert exc1.value.missing == "expected_version"
    with _pytest.raises(ReviewPreconditionRequired) as exc2:
        resolve_review(
            session, scope, key, "approve", actor="a",
            expected_version=current_version(session, space, key),
        )
    assert exc2.value.missing == "request_id"
    with _pytest.raises(ReviewPreconditionRequired):
        resolve_review(
            session, scope, key, "defer", actor="a",
            expected_version="  ", request_id="r1",  # 空白版本≠有效令牌
        )
    session.rollback()
    session.expire_all()
    item = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key)
    ).scalar_one()
    assert item.status == "open" and item.resolution is None, "零写"


def test_w6_projection_rejects_foreign_orm_objects(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """R2-P2 反例固化:知识域公共投影入口对传入 ORM 对象校验归属 scope——
    跨 space 直接调用 → ScopeViolation,绝不返回 foreign DTO。"""
    import pytest as _pytest

    from insurance_harness.db.scope import ScopeViolation
    from insurance_harness.knowledge.projection import (
        load_review_aggregate,
        load_review_aggregates,
        project_change_item,
    )
    from insurance_harness.knowledge.tables import ChangeItem

    factory, session = wb_env
    space_a = bound_space(session, "a")
    space_b = bound_space(session, "b")
    vid_b = seed_wb_product(session, space_b, code="PB01", name="乙产品")
    key_b = open_review_key(session, space_b, vid_b)
    scope_a = load_scope(session, space_a)
    item_b = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key_b)
    ).scalar_one()
    with _pytest.raises(ScopeViolation):
        load_review_aggregate(session, scope_a, item_b)
    with _pytest.raises(ScopeViolation):
        load_review_aggregates(session, scope_a, (item_b,))
    change_item_b = session.execute(select(ChangeItem)).scalars().first()
    assert change_item_b is not None
    with _pytest.raises(ScopeViolation):
        project_change_item(session, scope_a, change_item_b)
    session.rollback()
