"""008 审核工作台——分任务红绿（测试名引用条款号 W1~W7）。

PR#15 评审返工版：主正向用例一律经 **真实 MergeEngine** 造数（tests/wbhelpers），
不再手写扁平 ``proposed``；翻案断言两阶段状态机；并发断言版本合同；W7 用真实
QualityGate 三类拒绝；矩阵断言 schema 全字段底图与缺口导出语义。
零模型调用；对 knowledge/ 只经服务层（W5.1 静态断言钉住）。
"""

from __future__ import annotations

import json as _json
import re as _re
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func as _func
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import load_scope
from insurance_harness.knowledge import MergePolicy
from insurance_harness.knowledge.tables import (
    ChangeSet,
    Claim,
    ReviewItem,
)
from tests.wbhelpers import (
    bound_space,
    current_version,
    make_client,
    open_review_key,
    post_action,
    prop,
    real_gate,
    run_merge,
    seed_parallel_open_review,
    seed_wb_product,
)

# ---------------------------------------------------------------------------
# T1 · W5.2/W6.1 鉴权与 Space fail-closed
# ---------------------------------------------------------------------------


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer tok-alice"}


def test_w5_2_no_token_401(wb_env: tuple[Callable[[], Session], Session]) -> None:
    factory, session = wb_env
    space_a = bound_space(session, "a")
    client = make_client(factory, space_a)
    assert client.get(f"/spaces/{space_a}/queue").status_code == 401


def test_w5_2_unknown_token_401(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space_a = bound_space(session, "a")
    client = make_client(factory, space_a)
    resp = client.get(
        f"/spaces/{space_a}/queue", headers={"Authorization": "Bearer nope"}
    )
    assert resp.status_code == 401


def test_w5_2_no_tokens_configured_denies_all_fail_closed(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """未配置任何 token = 拒绝一切（fail-closed 默认，非放行）。"""
    from fastapi.testclient import TestClient

    from insurance_harness.workbench.app import create_app
    from tests.wbhelpers import wb_registry

    factory, session = wb_env
    space_a = bound_space(session, "a")
    client = TestClient(
        create_app(
            session_factory=factory, tokens_config={}, schema_registry=wb_registry()
        )
    )
    resp = client.get(
        f"/spaces/{space_a}/queue", headers={"Authorization": "Bearer tok-alice"}
    )
    assert resp.status_code == 401


def test_w6_1_token_cannot_cross_space_403_zero_leak(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space_a = bound_space(session, "a")
    space_b = bound_space(session, "b")
    client = make_client(factory, space_a)
    resp = client.get(f"/spaces/{space_b}/queue", headers=_auth())
    assert resp.status_code == 403
    assert space_b not in resp.text, "403 响应不得回显目标 space 细节"


def test_w6_1_allowed_space_ok(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space_a = bound_space(session, "a")
    client = make_client(factory, space_a)
    resp = client.get(f"/spaces/{space_a}/queue", headers=_auth())
    assert resp.status_code == 200 and "审核队列" in resp.text


def test_w6_1_unbound_space_fail_closed_403(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """space 在允许集内但未绑定（016 语义）→ 同样 fail-closed。"""
    factory, session = wb_env
    row = KnowledgeSpace(name="未绑定", binding_status="unbound")
    session.add(row)
    session.commit()
    unbound = str(row.id)
    client = make_client(factory, unbound)
    resp = client.get(f"/spaces/{unbound}/queue", headers=_auth())
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# W5/W6 · 浏览器纵向闭环：login → cookie 会话 → 完成审核（阻断 4 反例）
# ---------------------------------------------------------------------------


def _login(client: TestClient, token: str = "tok-alice") -> None:
    page = client.get("/login")
    assert page.status_code == 200
    csrf = client.cookies.get("wb_csrf")
    assert csrf, "GET /login 必须下发 CSRF cookie"
    resp = client.post(
        "/login", data={"token": token, "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303, f"登录应 303，实得 {resp.status_code}"
    assert client.cookies.get("wb_session"), "登录必须签发会话 cookie"


def test_w5_browser_login_then_full_review_without_bearer(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """浏览器纵向流：login → 点击队列（不带 Authorization 头）→ 表单 approve 生效。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    key = open_review_key(session, space, vid)
    client = make_client(factory, space)
    _login(client)
    # 全程不手工塞 Authorization —— 链接点击与原生表单必须能工作
    queue = client.get(f"/spaces/{space}/queue")
    assert queue.status_code == 200
    assert key in queue.text and "90天" in queue.text, "队列须展示候选值"
    csrf = client.cookies.get("wb_csrf")
    # 版本与 request_id 从**页面 hidden 字段**取（与真实浏览器同源，不走 DB 捷径）
    version_m = _re.search(r'name="expected_version" value="([^"]+)"', queue.text)
    rid_m = _re.search(r'name="request_id" value="([^"]+)"', queue.text)
    assert version_m and rid_m, "页面必须渲染并发令牌 hidden 字段"
    resp = client.post(
        f"/spaces/{space}/queue/{key}/action",
        data={
            "action": "approve", "reason": "看过证据", "csrf_token": csrf,
            "expected_version": version_m.group(1),
            "request_id": rid_m.group(1),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303, "浏览器表单 POST 应 303 回队列"
    session.expire_all()
    item = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key)
    ).scalar_one()
    assert item.status == "resolved"
    assert item.resolution is not None and item.resolution["actor"] == "alice"
    published = session.execute(
        select(_func.count()).select_from(Claim).where(Claim.status == "published")
    ).scalar_one()
    assert published == 1, "浏览器流必须真实发布"


def test_w6_browser_session_csrf_required_on_writes(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """cookie 会话的写请求缺 CSRF → 403；Bearer 通道不受影响。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    key = open_review_key(session, space, vid)
    client = make_client(factory, space)
    _login(client)
    resp = post_action(client, session, space, key, "approve", csrf=None)
    assert resp.status_code == 403, "无 CSRF 的 cookie 写请求必须拒绝"
    session.expire_all()
    item = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key)
    ).scalar_one()
    assert item.status == "open", "被拒请求不得产生任何写"


def test_w6_browser_cookie_cannot_cross_space(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space_a = bound_space(session, "a")
    space_b = bound_space(session, "b")
    client = make_client(factory, space_a)
    _login(client)
    assert client.get(f"/spaces/{space_b}/queue").status_code == 403


def test_w5_logout_invalidates_browser_session(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = bound_space(session, "a")
    client = make_client(factory, space)
    _login(client)
    assert client.get(f"/spaces/{space}/queue").status_code == 200
    csrf = client.cookies.get("wb_csrf")
    assert client.post(
        "/logout", data={"csrf_token": csrf}, follow_redirects=False
    ).status_code == 303
    assert client.get(f"/spaces/{space}/queue").status_code == 401


def test_w5_htmx_vendored_and_loaded(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """HTMX 本地 vendor 并被页面加载（W5：不能只写 hx-* 却不加载运行库）。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    client = make_client(factory, space)
    js = client.get("/static/vendor/htmx.min.js")
    assert js.status_code == 200 and len(js.content) > 10_000
    page = client.get(f"/spaces/{space}/queue", headers=_auth())
    assert '/static/vendor/htmx.min.js' in page.text, "页面必须引用本地 htmx"


# ---------------------------------------------------------------------------
# T2/T3 · W1 队列（真实 MergeEngine 数据）与三动作
# ---------------------------------------------------------------------------


def test_w1_1_queue_shows_real_candidate_value_and_evidence(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """阻断 1 反例：真实合并造数后，队列必须展示候选值/证据/权威级/产品。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    key = open_review_key(session, space, vid)
    client = make_client(factory, space)
    body = client.get(f"/spaces/{space}/queue", headers=_auth()).text
    assert key in body
    assert "90天" in body, "候选值不得为 None（真实 proposed 形态解析）"
    assert "等待期为90天" in body, "证据引文"
    assert "权威2" in body, "权威等级"
    assert "P001" in body, "产品标识"
    assert "ChangeSet" in body, "关联 ChangeSet 链接"


def test_w1_1_queue_filters_and_pagination(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    open_review_key(session, space, vid, "waiting_period", risk="low")
    open_review_key(session, space, vid, "grace_period", value="60天", risk="high")
    open_review_key(session, space, vid, "coverage_scope", value="身故", risk="low")
    client = make_client(factory, space)
    high_only = client.get(
        f"/spaces/{space}/queue", params={"risk": "high"}, headers=_auth()
    ).text
    assert "grace_period" in high_only
    assert "coverage_scope" not in high_only
    paged = client.get(
        f"/spaces/{space}/queue", params={"limit": 2, "offset": 2}, headers=_auth()
    ).text
    assert "共 3 条" in paged


def test_w1_1_trigger_count_desc_is_default_order(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """W1.1 spec 原文「触发计数倒序默认」：同一审核项被重复触发排到最前。"""
    from insurance_harness.workbench.queries import list_review_queue

    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    open_review_key(session, space, vid, "grace_period", value="60天", risk="high")
    scope = load_scope(session, space)
    # waiting_period 触发三次（同内容 → 同 review_key 计数递增）
    for i in range(3):
        run_merge(
            session, space, [prop(scope, vid, "waiting_period")],
            external_id=f"retrigger-{i}",
        )
    page = list_review_queue(session, load_scope(session, space))
    assert page.items[0].predicate == "waiting_period", "触发计数倒序压过风险序"
    assert page.items[0].trigger_count == 3
    assert page.items[1].risk_level == "high"


def test_w1_3_approve_publishes_and_resolves(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    key = open_review_key(session, space, vid)
    client = make_client(factory, space)
    resp = post_action(
        client, session, space, key, "approve",
        reason="看过证据", headers=_auth(),
    )
    assert resp.status_code == 303
    session.expire_all()
    item = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key)
    ).scalar_one()
    assert item.status == "resolved"
    assert item.resolution is not None and item.resolution["action"] == "approve"
    published = session.execute(
        select(Claim).where(Claim.space_id == space, Claim.status == "published")
    ).scalars().all()
    assert len(published) == 1, "approve 经服务层真实发布"


def test_w1_3_defer_keeps_open_but_audits(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """阻断 3 反例：defer 保持 open，但必须写 actor/时间/理由 审计事件并推进版本。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    key = open_review_key(session, space, vid)
    before = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key)
    ).scalar_one().updated_at.isoformat()
    client = make_client(factory, space)
    assert post_action(
        client, session, space, key, "defer",
        reason="等补充材料", headers=_auth(),
    ).status_code == 303
    session.expire_all()
    item = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key)
    ).scalar_one()
    assert item.status == "open", "defer 保持 open"
    events = (item.resolution or {}).get("events") or []
    assert len(events) == 1
    assert events[0]["action"] == "defer" and events[0]["actor"] == "alice"
    assert events[0]["reason"] == "等补充材料" and events[0]["at"]
    assert item.updated_at.isoformat() != before, "defer 必须推进版本（乐观并发）"
    assert (item.resolution or {}).get("action") is None, "defer 不落最终决定"


def test_w1_4_stale_version_rejected_409(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """乐观并发（W1）：携带过期版本的提交被拒并提示刷新，不生效。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    key = open_review_key(session, space, vid)
    stale_version = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key)
    ).scalar_one().updated_at.isoformat()
    client = make_client(factory, space)
    # defer 推进版本 → 原版本过期
    assert post_action(
        client, session, space, key, "defer", headers=_auth()
    ).status_code == 303
    resp = post_action(
        client, session, space, key, "approve",
        headers=_auth(), expected_version=stale_version,
    )
    assert resp.status_code == 409, "stale 版本必须拒绝"
    session.expire_all()
    item = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key)
    ).scalar_one()
    assert item.status == "open", "stale 提交不得生效"
    # 带最新版本 → 生效
    assert post_action(
        client, session, space, key, "approve", headers=_auth()
    ).status_code == 303


def test_w1_4_same_action_resubmit_idempotent(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    key = open_review_key(session, space, vid)
    client = make_client(factory, space)
    assert post_action(
        client, session, space, key, "approve", headers=_auth()
    ).status_code == 303
    second = post_action(
        client, session, space, key, "approve", headers=_auth()
    )
    assert second.status_code == 303, "同决定重复提交幂等（W1.3）"
    session.expire_all()
    n_published = session.execute(
        select(_func.count()).select_from(Claim).where(
            Claim.space_id == space, Claim.status == "published"
        )
    ).scalar_one()
    assert n_published == 1, "重复提交不得重复生效"


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


def test_w1_4_conflicting_action_on_resolved_409(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    key = open_review_key(session, space, vid)
    client = make_client(factory, space)
    assert post_action(
        client, session, space, key, "approve", headers=_auth()
    ).status_code == 303
    conflict = post_action(
        client, session, space, key, "reject", headers=_auth()
    )
    assert conflict.status_code == 409, "异决定撞已决 → 409 提示刷新"


def test_w6_3_audit_actor_is_token_principal_not_client_field(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    key = open_review_key(session, space, vid)
    client = make_client(factory, space)
    resp = post_action(
        client, session, space, key, "approve", headers=_auth(),
        extra={"operator": "mallory"},  # 客户端自报必须被无视
    )
    assert resp.status_code == 303
    session.expire_all()
    item = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key)
    ).scalar_one()
    assert item.resolution is not None and item.resolution["actor"] == "alice"


def test_w1_3_batch_approve_versioned_excludes_high(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """批量逐项携带版本（阻断 3）；高风险排除显式提示；stale 项点名跳过。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    k_low = open_review_key(session, space, vid, "waiting_period")
    k_high = open_review_key(session, space, vid, "grace_period", value="60天", risk="high")
    k_stale = open_review_key(session, space, vid, "coverage_scope", value="身故")
    k_bare = open_review_key(session, space, vid, "never_extracted", value="占位")
    versions = {
        r.review_key: r.updated_at.isoformat()
        for r in session.execute(select(ReviewItem)).scalars()
    }
    client = make_client(factory, space)
    resp = client.post(
        f"/spaces/{space}/queue/batch-approve",
        headers=_auth(),
        data={
            "keys": [
                f"{k_low}@{versions[k_low]}",
                f"{k_high}@{versions[k_high]}",
                f"{k_stale}@1999-01-01T00:00:00+00:00",  # 过期版本
                k_bare,  # 裸 key（无 @version）→ malformed 显式拒绝（R2-P1）
                f"{k_bare}@",  # 空版本 → 同样拒绝，不降级为 None
            ],
            "request_id": "batch-1",
        },
    )
    assert resp.status_code == 200
    assert "批量通过 1 条" in resp.text
    assert k_high in resp.text, "高风险排除必须显式点名"
    assert k_stale in resp.text and "版本已过期" in resp.text, "stale 项点名"
    assert "格式错误" in resp.text, "裸 key/空版本必须显式拒绝，不得静默通过"
    session.expire_all()
    states = {
        r.review_key: r.status
        for r in session.execute(select(ReviewItem)).scalars()
    }
    assert states[k_low] == "resolved"
    assert states[k_high] == "open" and states[k_stale] == "open"
    assert states[k_bare] == "open", "malformed 项不得生效"


# ---------------------------------------------------------------------------
# T4 · W2 冲突与变更页 + 两阶段翻案 + G8 时间线
# ---------------------------------------------------------------------------


def test_w2_1_changes_page_lists_sets_with_counts(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    open_review_key(session, space, vid)
    client = make_client(factory, space)
    resp = client.get(f"/spaces/{space}/changes", headers=_auth())
    assert resp.status_code == 200
    assert "document" in resp.text and "add" in resp.text


def test_w2_2_detail_projects_real_merge_shapes(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """阻断 1 反例：真实 add/supersede(conflict)/enrich 形态在明细页可读——
    predicate/提案值不得为 None，冲突双方值+证据+裁决依据并排。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    scope = load_scope(session, space)
    # 批1 add → approve 发布 90天
    key = open_review_key(session, space, vid, external_id="doc-1")
    client = make_client(factory, space)
    assert post_action(
        client, session, space, key, "approve", headers=_auth()
    ).status_code == 303
    # 批2 同谓词更高权威 180天 → supersede needs_review + Conflict(open)
    report2 = run_merge(
        session, space,
        [prop(scope, vid, value="180天", doc_role="terms", authority=1,
              knowledge_id="doc-terms", quote="等待期为一百八十天")],
        external_id="doc-2",
    )
    assert report2.review_keys, "supersede 默认走审核"
    # 批3 同值 90天 追加证据 → enrich append_evidence…… 已 superseded？否：批2未批，
    # 现值仍 90天 published → 同值 → enrich append needs_review
    run_merge(
        session, space,
        [prop(scope, vid, value="90天", knowledge_id="doc-faq",
              doc_role="faq", authority=4, quote="产品等待期九十天")],
        external_id="doc-3",
    )
    sets = session.execute(
        select(ChangeSet).where(ChangeSet.space_id == space).order_by(ChangeSet.created_at)
    ).scalars().all()
    # 批2：supersede 明细
    body2 = client.get(
        f"/spaces/{space}/changes/{sets[1].id}", headers=_auth()
    ).text
    assert "waiting_period" in body2, "predicate 不得为 None（真实形态解析）"
    assert "180天" in body2 and "90天" in body2, "冲突双方值并排"
    assert "authority_cmp" in body2, "自动裁决依据（权威序比较）可见"
    assert "等待期为一百八十天" in body2, "候选证据引文"
    # 批3：enrich append 明细
    body3 = client.get(
        f"/spaces/{space}/changes/{sets[2].id}", headers=_auth()
    ).text
    assert "enrich" in body3 and "产品等待期九十天" in body3, "追加证据可读"


def test_w2_3_overturn_two_phase_via_http(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """W2.3 两阶段（阻断 2 反例）：翻案请求后旧事实原样、原 resolution 不变、
    新 ChangeSet pending、新审核项 open；批准新审核项后事实才变化。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    key = open_review_key(session, space, vid)
    client = make_client(factory, space)
    assert post_action(
        client, session, space, key, "approve", headers=_auth()
    ).status_code == 303
    # 缺 reason → 422/400（翻案必须留理由）
    assert client.post(
        f"/spaces/{space}/queue/{key}/overturn", headers=_auth(),
        data={"new_action": "reject"},
    ).status_code in (400, 422)
    resp = client.post(
        f"/spaces/{space}/queue/{key}/overturn", headers=_auth(),
        data={"new_action": "reject", "reason": "证据不足"},
    )
    assert resp.status_code == 200 and "原决定与当前事实未变更" in resp.text
    session.expire_all()
    original = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key)
    ).scalar_one()
    assert original.status == "resolved"
    assert original.resolution is not None
    assert original.resolution["action"] == "approve", "原 resolution 不得改写"
    published = session.execute(
        select(Claim).where(Claim.space_id == space, Claim.status == "published")
    ).scalars().all()
    assert len(published) == 1, "登记翻案后旧事实必须原样 published"
    manual = session.execute(
        select(ChangeSet).where(
            ChangeSet.space_id == space, ChangeSet.source_kind == "manual_edit"
        )
    ).scalar_one()
    assert manual.status == "pending", "复议 ChangeSet 走审核，不是即时 applied"
    overturn_item = session.execute(
        select(ReviewItem).where(ReviewItem.type == "overturn")
    ).scalar_one()
    assert overturn_item.status == "open" and overturn_item.risk_level == "high"
    # 重复请求幂等
    again = client.post(
        f"/spaces/{space}/queue/{key}/overturn", headers=_auth(),
        data={"new_action": "reject", "reason": "重复点击"},
    )
    assert again.status_code == 200 and "幂等" in again.text
    # ——批准翻案审核项 → 反向应用生效——
    assert post_action(
        client, session, space, overturn_item.review_key, "approve",
        reason="同意复议", headers=_auth(),
    ).status_code == 303
    session.expire_all()
    assert session.execute(
        select(_func.count()).select_from(Claim).where(
            Claim.space_id == space, Claim.status == "retracted"
        )
    ).scalar_one() == 1, "批准翻案后已采纳 Claim 撤回"
    original2 = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key)
    ).scalar_one()
    assert original2.resolution is not None
    assert original2.resolution["action"] == "approve", "历史裁决记录仍不可变"


def test_w2_4_timeline_human_readable_rows(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    key = open_review_key(session, space, vid)
    client = make_client(factory, space)
    assert post_action(
        client, session, space, key, "approve",
        reason="证据充分", headers=_auth(),
    ).status_code == 303
    body = client.get(f"/spaces/{space}/timeline", headers=_auth()).text
    assert "alice" in body and "P001" in body
    assert "waiting_period" in body and "90天" in body and "证据充分" in body


# ---------------------------------------------------------------------------
# T5 · W3 完整度矩阵：schema 全字段底图 + 五态下钻 + 缺口导出（阻断 5 反例）
# ---------------------------------------------------------------------------


def test_w3_1_matrix_full_schema_baseline_zero_claim_product(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """零 Claim 的产品仍有完整 schema 字段矩阵（全部 unknown）。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    seed_wb_product(session, space)
    client = make_client(factory, space)
    body = client.get(f"/spaces/{space}/matrix", headers=_auth()).text
    for field in ("waiting_period", "grace_period", "coverage_scope",
                  "premium_rate", "never_extracted"):
        assert field in body, f"schema 字段 {field} 必须出现在底图"
    assert body.count("state-unknown") >= 5, "未收录字段显示为 unknown"


def test_w3_1_matrix_five_states_from_real_merge(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    scope = load_scope(session, space)
    client = make_client(factory, space)
    # present：add → approve
    k1 = open_review_key(session, space, vid, "waiting_period")
    assert post_action(
        client, session, space, k1, "approve", headers=_auth()
    ).status_code == 303
    # pending_review：grace_period 待审
    open_review_key(session, space, vid, "grace_period", value="60天")
    # conflict_open：waiting_period 高风险同权威异值 → ⑤ conflict 审核
    run_merge(
        session, space,
        [prop(scope, vid, value="180天", knowledge_id="doc-2", quote="等待期180天")],
        external_id="doc-conflict",
        risk_of=lambda _p: "high",
    )
    body = client.get(f"/spaces/{space}/matrix", headers=_auth()).text
    assert "waiting_period:conflict_open" in body, "开放冲突优先于三态"
    assert "grace_period:pending_review" in body
    assert "never_extracted:unknown" in body


def test_w3_2_pending_and_conflict_drill_not_404(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """阻断 5 反例：待审/冲突格下钻必须可用（原实现只查 published → 404）。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    scope = load_scope(session, space)
    client = make_client(factory, space)
    open_review_key(session, space, vid, "grace_period", value="60天")
    pending = client.get(
        f"/spaces/{space}/matrix/{vid}/grace_period", headers=_auth()
    )
    assert pending.status_code == 200, "pending 下钻不得 404"
    assert "60天" in pending.text and "pending_review" in pending.text
    # conflict：先发布 waiting_period，再造高风险冲突
    k1 = open_review_key(session, space, vid, "waiting_period")
    post_action(client, session, space, k1, "approve", headers=_auth())
    run_merge(
        session, space,
        [prop(scope, vid, value="180天", knowledge_id="doc-2", quote="等待期180天")],
        external_id="doc-conflict", risk_of=lambda _p: "high",
    )
    conflict = client.get(
        f"/spaces/{space}/matrix/{vid}/waiting_period", headers=_auth()
    )
    assert conflict.status_code == 200, "conflict 下钻不得 404"
    assert "90天" in conflict.text and "180天" in conflict.text, "双方值并排"
    assert "conflict_open" in conflict.text


def test_w3_2_published_drill_and_unknown_drill(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    client = make_client(factory, space)
    key = open_review_key(session, space, vid)
    post_action(
        client, session, space, key, "approve", reason="ok", headers=_auth()
    )
    pub = client.get(
        f"/spaces/{space}/matrix/{vid}/waiting_period", headers=_auth()
    ).text
    assert "90天" in pub and "等待期为90天" in pub and "alice" in pub
    unknown = client.get(
        f"/spaces/{space}/matrix/{vid}/never_extracted", headers=_auth()
    )
    assert unknown.status_code == 200, "schema 内未收录字段下钻不得 404"
    assert "未收录 ≠ 不存在" in unknown.text
    assert "v1.1+wbtest" in unknown.text, "schema 来源标注"
    # 既无数据也不在 schema → 404
    assert client.get(
        f"/spaces/{space}/matrix/{vid}/no_such_field", headers=_auth()
    ).status_code == 404


def test_w3_3_gap_export_excludes_present_and_labels_sources(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """阻断 5 反例：缺口导出只含 unknown/pending/conflict；ticket_source 稳定标注。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    client = make_client(factory, space)
    k1 = open_review_key(session, space, vid, "waiting_period")
    post_action(client, session, space, k1, "approve", headers=_auth())
    open_review_key(session, space, vid, "grace_period", value="60天")
    jsonl = client.get(
        f"/spaces/{space}/matrix/export", headers=_auth(), params={"fmt": "jsonl"}
    )
    rows = [_json.loads(ln) for ln in jsonl.text.strip().splitlines()]
    states = {r["field"]: r for r in rows}
    assert "waiting_period" not in states, "present 不得出现在缺口清单"
    assert states["grace_period"]["state"] == "pending_review"
    assert states["grace_period"]["ticket_source"].startswith("review:rv-")
    assert states["never_extracted"]["state"] == "unknown"
    assert states["never_extracted"]["ticket_source"] == "schema:v1.1+wbtest"
    csv_resp = client.get(
        f"/spaces/{space}/matrix/export", headers=_auth(), params={"fmt": "csv"}
    )
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    lines = [ln for ln in csv_resp.text.strip().splitlines() if ln]
    assert lines[0].startswith("product_code,")
    assert not any(",present," in ln for ln in lines[1:]), "CSV 同语义"


# ---------------------------------------------------------------------------
# W7 · 质量闸门联动：真实 QualityGate 三类拒绝（阻断 6 反例）
# ---------------------------------------------------------------------------


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


def test_w7_gate_reason_rendered_in_queue(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    _gate_denied_review(session, space, vid, "threshold")
    client = make_client(factory, space)
    body = client.get(f"/spaces/{space}/queue", headers=_auth()).text
    assert "quality_gate" in body
    assert "指标未达阈值" in body, "gate 原因在队列可读（W7）"
    assert "wb-baseline" in body, "baseline 标识文本"


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


# ---------------------------------------------------------------------------
# T7 · 守卫钉：跨空间不可见 / 路由白名单 / 静态零写（回归销）
# ---------------------------------------------------------------------------


def test_w6_2_cross_space_same_business_key_invisible(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space_a = bound_space(session, "a")
    space_b = bound_space(session, "b")
    vid_a = seed_wb_product(session, space_a, code="P001", name="甲产品")
    vid_b = seed_wb_product(session, space_b, code="P001", name="乙产品")
    seed_parallel_open_review(
        session, space_a, vid_a, "waiting_period", key="same-key"
    )
    seed_parallel_open_review(
        session, space_b, vid_b, "waiting_period", key="same-key"
    )
    client = make_client(
        factory, space_a,
        extra={"tok-bob": {"principal": "bob", "space_ids": [space_b]}},
    )
    body_a = client.get(f"/spaces/{space_a}/queue", headers=_auth()).text
    body_b = client.get(
        f"/spaces/{space_b}/queue", headers={"Authorization": "Bearer tok-bob"}
    ).text
    assert "same-key" in body_a and "same-key" in body_b
    assert "乙产品" not in body_a and "甲产品" not in body_b


def test_w7_3_route_allowlist_no_bypass_endpoints(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """无任何绕过闸门的发布类端点（W7.3：无此按钮、无此端点）。"""
    from fastapi.routing import APIRoute

    from insurance_harness.workbench.app import create_app
    from tests.wbhelpers import wb_registry

    factory, _session = wb_env
    app = create_app(
        session_factory=factory, tokens_config={}, schema_registry=wb_registry()
    )
    paths = {
        (r.path, m)
        for r in app.routes
        if isinstance(r, APIRoute)
        for m in (r.methods or set())
        if m != "HEAD"
    }
    allowlist = {
        ("/login", "GET"),
        ("/login", "POST"),
        ("/logout", "POST"),
        ("/", "GET"),
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
    """gauntlet 对称路径：双空间授权 token 用 A 的 ChangeSet id 走 B 路径 → 404。"""
    factory, session = wb_env
    space_a = bound_space(session, "a")
    space_b = bound_space(session, "b")
    vid_a = seed_wb_product(session, space_a)
    open_review_key(session, space_a, vid_a)
    cs = session.execute(
        select(ChangeSet).where(ChangeSet.space_id == space_a)
    ).scalars().first()
    assert cs is not None
    client = make_client(
        factory, space_a,
        extra={"tok-both": {"principal": "carol", "space_ids": [space_a, space_b]}},
    )
    resp = client.get(
        f"/spaces/{space_b}/changes/{cs.id}",
        headers={"Authorization": "Bearer tok-both"},
    )
    assert resp.status_code == 404


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


def test_w5_1_queries_readonly_no_pending_writes(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    from insurance_harness.workbench.queries import (
        completeness_matrix,
        list_change_sets,
        list_review_queue,
    )
    from tests.wbhelpers import wb_registry

    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    open_review_key(session, space, vid)
    scope = load_scope(session, space)
    list_review_queue(session, scope)
    list_change_sets(session, scope)
    completeness_matrix(session, scope, wb_registry())
    assert not session.dirty and not session.new and not session.deleted, (
        "查询模块必须只读（W5.1）"
    )


# ---------------------------------------------------------------------------
# codex R2 验收：并发令牌强制（P1）/ SQL 成本预算（P1）/ 投影边界（P2）
# ---------------------------------------------------------------------------


def test_w1_4_missing_tokens_rejected_zero_write(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """R2-P1 反例固化:删掉 expected_version / request_id 隐藏字段不再是通道——
    路由层 422(FastAPI 必填校验,零写);空串同样拒绝。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    key = open_review_key(session, space, vid)
    client = make_client(factory, space)
    url = f"/spaces/{space}/queue/{key}/action"
    cases = (
        {"action": "approve"},  # 双缺
        {"action": "approve", "request_id": "r1"},  # 缺 expected_version
        {"action": "approve", "expected_version": current_version(session, space, key)},
        {"action": "approve", "expected_version": "", "request_id": "r1"},  # 空版本
        {"action": "defer"},  # defer 同样强制(重复 defer 需 request_id 幂等)
    )
    for data in cases:
        resp = client.post(url, headers=_auth(), data=data)
        assert resp.status_code == 422, f"data={data} 应 422,实得 {resp.status_code}"
    session.expire_all()
    item = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key)
    ).scalar_one()
    assert item.status == "open" and item.resolution is None, "被拒请求零写"
    published = session.execute(
        select(_func.count()).select_from(Claim).where(Claim.status == "published")
    ).scalar_one()
    assert published == 0


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


def test_w1_1_queue_sql_budget_constant_wrt_total(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """R2-P1 反例固化:limit=20 的队列查询量为常数(≤10 条 SQL),不随 space 内
    ReviewItem 总量增长(20 条与 200 条完全等量)——筛选/COUNT/排序/LIMIT 在
    SQL,当前页批量投影一次预取。"""
    from sqlalchemy import event as _event

    from insurance_harness.workbench.queries import list_review_queue

    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    scope = load_scope(session, space)

    def _seed(n_from: int, n_to: int) -> None:
        run_merge(
            session, space,
            [
                prop(scope, vid, f"field_{i:04d}", value=f"值{i}",
                     quote=f"证据{i}")
                for i in range(n_from, n_to)
            ],
            external_id=f"bulk-{n_from}-{n_to}",
        )

    engine = session.get_bind()

    def _count_queries(fn: Callable[[], object]) -> int:
        counter = {"n": 0}

        def _cb(*_args: object, **_kw: object) -> None:
            counter["n"] += 1

        _event.listen(engine, "before_cursor_execute", _cb)
        try:
            fn()
        finally:
            _event.remove(engine, "before_cursor_execute", _cb)
        return counter["n"]

    _seed(0, 20)
    q_small = _count_queries(
        lambda: list_review_queue(session, scope, limit=20)
    )
    _seed(20, 200)
    q_large = _count_queries(
        lambda: list_review_queue(session, scope, limit=20)
    )
    assert q_small == q_large, (
        f"查询量必须与总量无关:20 条时 {q_small},200 条时 {q_large}"
    )
    assert q_large <= 10, f"单页查询预算 ≤10 条 SQL,实得 {q_large}(N+1 回归)"
    page = list_review_queue(session, scope, limit=20)
    assert page.total == 200 and len(page.items) == 20, "分页语义仍正确"
    assert all(a.change_item is not None for a in page.items), "当前页投影完整"
    # 产品过滤走 SQL(subject.product_version_id):total 正确
    filtered = list_review_queue(session, scope, product_code="P001", limit=20)
    assert filtered.total == 200
    assert list_review_queue(
        session, scope, product_code="NO-SUCH", limit=20
    ).total == 0


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
