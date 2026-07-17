"""008 W1 并发合同：乐观并发 + 行锁的真实两会话验证（PR#15 阻断 3）。

- deterministic（sqlite）：版本/幂等/异决定的服务层状态机；
- integration_postgres：两个 PostgreSQL 会话同时对同一 ReviewItem 提交动作，
  ``SELECT … FOR UPDATE`` 序列化后只生效一次、另一方得到幂等或冲突，
  无 500、无重复 revision（串行重放≠并发测试——本文件补真并发）。
"""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from insurance_harness.db import models as _db_models  # noqa: F401
from insurance_harness.db.base import Base
from insurance_harness.db.scope import load_scope
from insurance_harness.knowledge import (
    ReviewDecisionConflict,
    ReviewStale,
    resolve_review,
)
from insurance_harness.knowledge.tables import Claim, ClaimRevision, ReviewItem
from tests.wbhelpers import (
    bound_space,
    open_review_key,
    seed_wb_product,
)

TEST_POSTGRES_URL = os.getenv("HARNESS_TEST_POSTGRES_URL")
FUTURE_TIMEOUT_S = 30


# ---------------------------------------------------------------------------
# deterministic：服务层版本/幂等状态机（sqlite；锁语义在 PG 用例验证）
# ---------------------------------------------------------------------------


def test_w1_4_service_stale_version_raises(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    key = open_review_key(session, space, vid)
    scope = load_scope(session, space)
    stale = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key)
    ).scalar_one().updated_at.isoformat()
    resolve_review(session, scope, key, "defer", actor="a")  # 版本前进
    with pytest.raises(ReviewStale):
        resolve_review(
            session, scope, key, "approve", actor="b", expected_version=stale
        )
    session.rollback()
    session.expire_all()
    item = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key)
    ).scalar_one()
    assert item.status == "open", "stale 提交不得生效"


def test_w1_4_service_decision_conflict_after_resolved(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    key = open_review_key(session, space, vid)
    scope = load_scope(session, space)
    resolve_review(session, scope, key, "approve", actor="a")
    session.commit()
    # 同决定幂等返回；异决定 ReviewDecisionConflict
    again = resolve_review(session, scope, key, "approve", actor="b")
    assert again.status == "resolved"
    with pytest.raises(ReviewDecisionConflict):
        resolve_review(session, scope, key, "reject", actor="b")
    session.rollback()


def test_w1_4_defer_then_actions_full_event_history(
    wb_env: tuple[Callable[[], Session], Session],
) -> None:
    """defer→approve 全事件史保序（含 request_id/expected_version 审计字段）。"""
    factory, session = wb_env
    space = bound_space(session, "a")
    vid = seed_wb_product(session, space)
    key = open_review_key(session, space, vid)
    scope = load_scope(session, space)
    resolve_review(
        session, scope, key, "defer", actor="alice", reason="先挂起",
        request_id="r1",
    )
    item = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key)
    ).scalar_one()
    fresh = item.updated_at.isoformat()
    resolve_review(
        session, scope, key, "approve", actor="bob", reason="补齐后通过",
        expected_version=fresh, request_id="r2",
    )
    session.commit()
    session.expire_all()
    item = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == key)
    ).scalar_one()
    events = (item.resolution or {}).get("events") or []
    assert [e["action"] for e in events] == ["defer", "approve"]
    assert [e["actor"] for e in events] == ["alice", "bob"]
    assert events[0]["request_id"] == "r1" and events[1]["request_id"] == "r2"
    assert events[1]["expected_version"] == fresh
    assert item.resolution is not None and item.resolution["action"] == "approve"


# ---------------------------------------------------------------------------
# integration_postgres：真实两会话并发（FOR UPDATE 序列化）
# ---------------------------------------------------------------------------


def _pg_connect_args(schema: str | None = None) -> dict[str, object]:
    options = ["-cstatement_timeout=20000", "-clock_timeout=15000"]
    if schema is not None:
        options.append(f"-csearch_path={schema},public")
    return {"connect_timeout": 10, "options": " ".join(options)}


@pytest.mark.integration_postgres
def test_w1_4_live_postgresql_two_sessions_single_apply() -> None:
    """两个会话同时 approve 同一 open ReviewItem：行锁序列化后恰好一次生效、
    另一方幂等；随后第三方异决定得到冲突；publish revision 恰 1，无 500。"""
    if not TEST_POSTGRES_URL:
        pytest.fail("HARNESS_TEST_POSTGRES_URL is required for integration_postgres")
    schema = f"wb008_concurrency_{uuid.uuid4().hex}"
    admin_engine = create_engine(
        TEST_POSTGRES_URL, future=True, connect_args=_pg_connect_args()
    )
    engine = None
    schema_created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        schema_created = True
        engine = create_engine(
            TEST_POSTGRES_URL, future=True, connect_args=_pg_connect_args(schema)
        )
        Base.metadata.create_all(engine, checkfirst=False)
        factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        with factory() as seed_session:
            space = bound_space(seed_session, "pg")
            vid = seed_wb_product(seed_session, space, code="PG-8", name="并发验证")
            key = open_review_key(seed_session, space, vid)

        first_locked = threading.Event()
        release_first = threading.Event()

        def _first() -> str:
            with factory() as s1:
                scope1 = load_scope(s1, space)
                resolve_review(s1, scope1, key, "approve", actor="alice")
                first_locked.set()  # 行锁在手、发布已执行、事务未提交
                assert release_first.wait(FUTURE_TIMEOUT_S)
                s1.commit()
                return "committed"

        def _second() -> str:
            assert first_locked.wait(FUTURE_TIMEOUT_S)
            with factory() as s2:
                scope2 = load_scope(s2, space)
                # 在 s1 持锁期间进入：FOR UPDATE 阻塞至 s1 提交，随后读到已决
                item = resolve_review(s2, scope2, key, "approve", actor="bob")
                s2.commit()
                return f"idempotent:{item.status}"

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_first)
            f2 = pool.submit(_second)
            assert first_locked.wait(FUTURE_TIMEOUT_S)
            # 稍候让 s2 实际阻塞在 FOR UPDATE 上，再放行 s1 提交
            threading.Event().wait(0.5)
            release_first.set()
            assert f1.result(timeout=FUTURE_TIMEOUT_S) == "committed"
            assert f2.result(timeout=FUTURE_TIMEOUT_S) == "idempotent:resolved"

        with factory() as check:
            published = check.execute(
                select(func.count()).select_from(Claim).where(
                    Claim.space_id == space, Claim.status == "published"
                )
            ).scalar_one()
            assert published == 1, "并发 approve 只生效一次"
            publish_revisions = check.execute(
                select(func.count()).select_from(ClaimRevision).where(
                    ClaimRevision.reason.is_(None)
                )
            ).scalar_one()
            assert publish_revisions == 1, "publish revision 恰 1（无重复应用）"
            item = check.execute(
                select(ReviewItem).where(ReviewItem.review_key == key)
            ).scalar_one()
            assert item.status == "resolved"
            assert item.resolution is not None
            assert item.resolution["actor"] == "alice", "先到者留痕，后到者幂等"
            scope3 = load_scope(check, space)
            with pytest.raises(ReviewDecisionConflict):
                resolve_review(check, scope3, key, "reject", actor="carol")
            check.rollback()
    finally:
        if engine is not None:
            engine.dispose()
        if schema_created:
            with admin_engine.begin() as connection:
                connection.execute(
                    text(f'DROP SCHEMA "{schema}" CASCADE')
                )
        admin_engine.dispose()
