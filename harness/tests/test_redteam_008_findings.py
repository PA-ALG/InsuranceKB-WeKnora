"""008 gauntlet 回归钉：服务层异常经工作台边界的正确 HTTP 语义。

源起红队（fresh-eyes agent + F1 自查）在 T1~T5/T7 波次后发现:工作台写路由
只预期 ValueError,但服务层真实异常谱系为 {ScopeViolation(ValueError),
MergeError(RuntimeError)}——过窄(MergeError→500)且对 ScopeViolation 过宽
(子类被 except ValueError 吞成 400 泄露)。本文件把当时的"缺陷复现"转为
"修复后正确行为"的回归断言。测试名引用条款号。

种子（PR#15 返工）：并行摄入竞态经 ``seed_parallel_open_review``——真实嵌套
``proposed={"claim": …}`` 形态（顺序 MergeEngine 无法造出同字段双 open add，
该形态正是两条并行会话互不可见时的真实落库产物）。
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import func as _func
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.knowledge.tables import Claim
from tests.wbhelpers import (
    bound_space,
    make_client,
    seed_parallel_open_review,
    seed_wb_product,
)


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer tok-alice"}


# ---------------------------------------------------------------------------
# W1 域冲突：同一 (version, predicate) 的第二个 approve → 服务层 MergeError。
# 修复后正确行为：干净的 409（而非未处理 500），且响应体为常量、不泄露内部 id。
# ---------------------------------------------------------------------------


def test_w1_double_approve_same_field_clean_409_not_500(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    from insurance_harness.workbench.app import _CONFLICT_BODY

    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    seed_parallel_open_review(session, space, vid, "waiting_period", key="dup1")
    seed_parallel_open_review(session, space, vid, "waiting_period", key="dup2")
    client = make_client(factory, space, raise_server_exceptions=False)

    r1 = client.post(
        f"/spaces/{space}/queue/dup1/action", headers=_auth(),
        data={"action": "approve"}, follow_redirects=False,
    )
    assert r1.status_code == 303, "第一个 approve 正常发布"

    r2 = client.post(
        f"/spaces/{space}/queue/dup2/action", headers=_auth(),
        data={"action": "approve"},
    )
    assert r2.status_code == 409, f"域冲突应干净拒绝为 409，实得 {r2.status_code}"
    # 零泄露:常量体,不得回显 MergeError 内含的 version_id / 他项 claim id。
    assert r2.text == _CONFLICT_BODY, "409 必须是常量体"
    assert vid not in r2.text, "响应体不得泄露 product_version_id（W6 零泄露）"


def test_w1_batch_approve_collision_partial_success_no_full_rollback(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """W1「其余低风险条目正常生效」:批量中一条域冲突只跳过该条,
    先成功的发布不被整批回滚丢弃(savepoint 部分成功)。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    seed_parallel_open_review(session, space, vid, "waiting_period", key="b1")
    seed_parallel_open_review(session, space, vid, "waiting_period", key="b2")
    client = make_client(factory, space, raise_server_exceptions=False)
    resp = client.post(
        f"/spaces/{space}/queue/batch-approve",
        headers=_auth(), data={"keys": ["b1", "b2"]},
    )
    assert resp.status_code == 200, f"批量整体应 200(部分成功),实得 {resp.status_code}"
    session.expire_all()
    n_pub = session.execute(
        select(_func.count()).select_from(Claim).where(
            Claim.space_id == space, Claim.status == "published"
        )
    ).scalar_one()
    assert n_pub == 1, f"b1 的发布必须保留(部分成功),published={n_pub}"
    assert "批量通过 1 条" in resp.text, "须报告成功条数"
    assert "跳过" in resp.text or "冲突" in resp.text, "被跳过的冲突项须显式点名,不静默"


def test_w1_approve_evidence_less_candidate_clean_409_not_500(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """无证据候选发布被服务层拒为 MergeError → 工作台干净 409,非 500。"""
    from insurance_harness.workbench.app import _CONFLICT_BODY

    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    seed_parallel_open_review(
        session, space, vid, "waiting_period", key="noev", with_evidence=False
    )
    client = make_client(factory, space, raise_server_exceptions=False)
    resp = client.post(
        f"/spaces/{space}/queue/noev/action", headers=_auth(),
        data={"action": "approve"},
    )
    assert resp.status_code == 409, f"无证据应干净 409,实得 {resp.status_code}"
    assert resp.text == _CONFLICT_BODY, "409 常量体"


# ---------------------------------------------------------------------------
# F1（W6.1 零泄露）:overturn 越权/不存在 → 404 对称（预检），不泄 scope 原因。
# ---------------------------------------------------------------------------


def test_w6_1_overturn_foreign_key_404_not_400_scope_leak(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space_a = bound_space(session, "a")
    space_b = bound_space(session, "b")
    client = make_client(
        factory, space_a,
        extra={"tok-both": {"principal": "carol", "space_ids": [space_a, space_b]}},
        raise_server_exceptions=False,
    )
    # 持双空间授权,用 B 路径翻案一个不存在/外空间的 key。
    resp = client.post(
        f"/spaces/{space_b}/queue/foreign-key/overturn",
        headers={"Authorization": "Bearer tok-both"},
        data={"new_action": "approve", "reason": "probe"},
    )
    assert resp.status_code == 404, f"外键翻案应 404(与 action/读一致),实得 {resp.status_code}"
    assert "scope mismatch" not in resp.text, "不得泄露 scope 失配原因(F1)"


def test_w6_1_action_foreign_key_404(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """回归护栏:action 写路径外键仍 404(get_review_item 预检)。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    client = make_client(factory, space, raise_server_exceptions=False)
    resp = client.post(
        f"/spaces/{space}/queue/nope/action", headers=_auth(),
        data={"action": "approve"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 诚实对照:确认几个"打不穿"的类别(若这些失败,说明判断错了)。
# ---------------------------------------------------------------------------


def test_control_empty_bearer_still_401(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = bound_space(session, "a")
    client = make_client(factory, space)
    for hdr in ("", "Bearer ", "bearer tok-alice", "Basic tok-alice", "tok-alice"):
        resp = client.get(f"/spaces/{space}/queue", headers={"Authorization": hdr})
        assert resp.status_code == 401, f"header={hdr!r} 应 401,实得 {resp.status_code}"


def test_control_malformed_id_no_500(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """String(36) 主键:畸形 id 不触发 DataError;返回 404 而非 500。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    client = make_client(factory, space, raise_server_exceptions=False)
    for bad in ("'; DROP TABLE claims;--", "../../etc", "null", "%00", "🙃" * 50):
        resp = client.get(f"/spaces/{space}/changes/{bad}", headers=_auth())
        assert resp.status_code == 404, f"id={bad!r} → {resp.status_code}"


def test_control_string_space_ids_config_fails_closed() -> None:
    """space_ids 传字符串(config 脚枪)→ 构造期报错或拒绝访问,绝不放行。"""
    from insurance_harness.workbench.auth import parse_tokens_config

    try:
        grants = parse_tokens_config({"t": {"principal": "p", "space_ids": "spaceA"}})
    except Exception:
        return  # 构造期即拒 = fail-closed,可接受
    assert "spaceA" not in grants["t"].space_ids, (
        "字符串被逐字符拆分或原样接受 → 可能放行错误 space"
    )


def test_control_forged_session_cookie_rejected(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """伪造/篡改会话 cookie(错误签名)→ 401,绝不放行。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    client = make_client(factory, space)
    client.cookies.set("wb_session", "eyJmYWtlIjogMX0.deadbeef")
    assert client.get(f"/spaces/{space}/queue").status_code == 401