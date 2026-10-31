"""JobStore（PostgreSQL）：分发去重、过期租约无写权、全局回收与领域写入守卫。"""

from __future__ import annotations

import threading
import time
import uuid

import pytest
from sqlalchemy import func, select

from insurance_harness.jobs import (
    OWNED_TABLES,
    ClaimedJob,
    DomainWriteSpec,
    DomainWriteViolationError,
    ErrorClass,
    InvalidJobInputError,
    JobFailure,
    JobState,
    LeaseExpiredError,
    OutboxDispatcher,
    OutboxEventDraft,
)

# `append_job_event` 已不在公共出口（P1.6 事件追加边界，D-2026-07-27-16）：
# 只能在完成事务内追加。测试直接引内部模块以验证该内部合同。
from insurance_harness.jobs.outbox import append_job_event
from insurance_harness.jobs.tables import WikiJob, WikiOutboxEvent
from tests.jobs.job_store_postgres.helpers import (
    FUTURE_TIMEOUT_S,
    PostgresRuntime,
    _config,
    _force_expire,
    _outbox_count,
    _space,
    _start_running,
    _store,
)

# --- M19：并发 dispatcher 行级锁互斥，正常路径零重复投递 ---


@pytest.mark.integration_postgres
def test_m19_concurrent_dispatchers_do_not_double_deliver(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("dupdisp")
    store = _store(postgres_runtime)
    for index in range(6):
        job_id, generation = _start_running(store, space_id, f"job-{index}", "worker-a")
        store.report_success(
            space_id=space_id,
            job_id=job_id,
            generation=generation,
            events=(OutboxEventDraft(event_type="job.succeeded", payload={"i": index}),),
        )

    seen: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def run_dispatcher() -> None:
        dispatcher = OutboxDispatcher(postgres_runtime.factory, _config())
        barrier.wait(timeout=10)

        def deliver(event: object) -> None:
            time.sleep(0.05)
            with lock:
                seen.append(event.event_id)  # type: ignore[attr-defined]

        dispatcher.dispatch_pending(space_id=space_id, deliver=deliver)

    threads = [threading.Thread(target=run_dispatcher) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=FUTURE_TIMEOUT_S)

    assert len(seen) == 6
    assert len(set(seen)) == 6  # 行级 SKIP LOCKED：无双投递
    dispatcher = OutboxDispatcher(postgres_runtime.factory, _config())
    assert dispatcher.read_pending(space_id=space_id) == ()


# --- D-2026-07-27-16 边界冻结：PostgreSQL 侧强制验收节点 ---


@pytest.mark.integration_postgres
def test_q15_expired_lease_holder_has_no_write_authority_on_postgres(
    postgres_runtime: PostgresRuntime,
) -> None:
    """P1.3 写权威合同：过期未回收的持有者四条写路径全部 typed 拒绝、零变更。"""
    space_id = _space("authority")
    store = _store(postgres_runtime)
    job_id, generation = _start_running(store, space_id, "job-1", "worker-a")
    _force_expire(postgres_runtime, job_id)

    with pytest.raises(LeaseExpiredError):
        store.report_success(
            space_id=space_id,
            job_id=job_id,
            generation=generation,
            events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
        )
    with pytest.raises(LeaseExpiredError):
        store.report_failure(
            space_id=space_id,
            job_id=job_id,
            generation=generation,
            failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="late"),
        )
    with pytest.raises(LeaseExpiredError):
        store.heartbeat(space_id=space_id, job_id=job_id, generation=generation)
    with pytest.raises(LeaseExpiredError):
        with postgres_runtime.factory() as session:
            with session.begin():
                append_job_event(
                    session,
                    space_id=space_id,
                    job_id=job_id,
                    generation=generation,
                    draft=OutboxEventDraft(event_type="job.progress", payload={}),
                )

    current = store.get_job(space_id=space_id, job_id=job_id)
    assert current.state is JobState.RUNNING
    assert current.lease_generation == generation
    assert _outbox_count(postgres_runtime, space_id) == 0


@pytest.mark.integration_postgres
def test_q16_stalled_expired_leases_never_exceed_limits_on_postgres(
    isolated_postgres_runtime: PostgresRuntime,
) -> None:
    """P1.8 限额会计：停滞的过期 lease 不得抬高 leased|running 行数上限。"""
    runtime = isolated_postgres_runtime
    store = _store(runtime, per_space_concurrency_limit=1, global_concurrency_limit=2)
    spaces = [_space(f"stall-{index}") for index in range(6)]
    for space_id in spaces:
        store.enqueue(space_id=space_id, job_type="compile", idempotency_key="job")

    for space_id in spaces:
        outcome = store.claim(space_ids=(space_id,), worker_id=f"worker-{space_id}")
        if isinstance(outcome, ClaimedJob):
            _force_expire(runtime, outcome.job.id)
        with runtime.factory() as session:
            active = int(
                session.scalar(
                    select(func.count())
                    .select_from(WikiJob)
                    .where(
                        WikiJob.state.in_(
                            (JobState.LEASED.value, JobState.RUNNING.value)
                        )
                    )
                )
                or 0
            )
        assert active <= 2, f"越限：{active} > 2"


@pytest.mark.integration_postgres
def test_q17_unenumerated_space_converges_via_global_reclaim_on_postgres(
    postgres_runtime: PostgresRuntime,
) -> None:
    """P1.10 回收可达性：无人枚举的 Space 经显式全局入口收敛。"""
    space_id = _space("orphan")
    store = _store(postgres_runtime, max_attempts=1)
    store.enqueue(space_id=space_id, job_type="compile", idempotency_key="job")
    outcome = store.claim(space_ids=(space_id,), worker_id="worker-gone")
    assert isinstance(outcome, ClaimedJob)
    _force_expire(postgres_runtime, outcome.job.id)

    report = store.reclaim_expired_leases_all_spaces()

    assert outcome.job.id in report.dead_lettered_job_ids
    dead = store.get_job(space_id=space_id, job_id=outcome.job.id)
    assert dead.state is JobState.DEAD_LETTER
    assert dead.error_summary == "lease_expired"


@pytest.mark.integration_postgres
def test_q19_declarative_domain_write_channel_on_postgres(
    postgres_runtime: PostgresRuntime,
) -> None:
    """P1.5 领域写通道（D-2026-07-27-16 第二轮修订）在真实 PG 上的合同。

    上一版把可执行回调放进完成事务再试图进程内沙箱它，被第二轮评审以公共
    属性 `Result.connection` 一行击破（领域行落库 + 任务仍 running + outbox
    空 ⇒ 重放产生第二份领域结果）。通道已改为声明式：调用方交表标识 + 列值，
    存储层自己执行，没有任何句柄可泄漏。本节点断言三件事：① 自有表被拒；
    ② 同前缀的其他域表不被误拦；③ 合法声明式写与状态、outbox 同事务原子。
    """
    space_id = _space("channel")
    domain_table = f"domain_{uuid.uuid4().hex[:12]}"
    foreign_wiki_table = f"wiki_page_revisions_{uuid.uuid4().hex[:8]}"
    with postgres_runtime.engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE TABLE "{domain_table}" (job_id TEXT PRIMARY KEY)')
        connection.exec_driver_sql(
            f'CREATE TABLE "{foreign_wiki_table}" (id TEXT PRIMARY KEY, note TEXT)'
        )
    store = _store(postgres_runtime)
    job_id, generation = _start_running(store, space_id, "job-1", "worker-a")

    # ① P1 自有表：在执行任何领域语句之前 typed 拒绝，整个完成事务回滚。
    for owned in sorted(OWNED_TABLES):
        with pytest.raises(DomainWriteViolationError):
            store.report_success(
                space_id=space_id,
                job_id=job_id,
                generation=generation,
                domain_writes=(
                    DomainWriteSpec(table=domain_table, values={"job_id": job_id}),
                    DomainWriteSpec(table=owned, values={"space_id": space_id}),
                ),
            )
    with postgres_runtime.engine.begin() as connection:
        leaked = connection.exec_driver_sql(
            f'SELECT count(*) FROM "{domain_table}"'
        ).scalar_one()
    assert leaked == 0, "被拒绝的完成事务不得留下领域行"
    current = store.get_job(space_id=space_id, job_id=job_id)
    assert current.state is JobState.RUNNING
    assert current.lease_generation == generation
    assert _outbox_count(postgres_runtime, space_id) == 0

    # ②③ 同前缀的其他域表不被误拦；含事务控制关键字的字面量同样不被误拦。
    done = store.report_success(
        space_id=space_id,
        job_id=job_id,
        generation=generation,
        events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
        domain_writes=(
            DomainWriteSpec(table=domain_table, values={"job_id": job_id}),
            DomainWriteSpec(
                table=foreign_wiki_table,
                values={"id": job_id, "note": "do not touch; call center; period begin"},
            ),
        ),
    )
    assert done.state is JobState.SUCCEEDED
    with postgres_runtime.engine.begin() as connection:
        assert (
            connection.exec_driver_sql(f'SELECT count(*) FROM "{domain_table}"').scalar_one() == 1
        )
        assert (
            connection.exec_driver_sql(
                f'SELECT count(*) FROM "{foreign_wiki_table}"'
            ).scalar_one()
            == 1
        )
    assert _outbox_count(postgres_runtime, space_id) == 1


@pytest.mark.integration_postgres
def test_q30_owned_table_check_is_normalized_on_postgres(
    postgres_runtime: PostgresRuntime,
) -> None:
    """P1.5：自有表校验的规范化在真实 PG 上同样成立（第三轮自攻 BLOCKER）。

    SQLite 上 `table="WIKI_JOBS"` 曾过校验并真的写进 `wiki_jobs`；PG 上同一
    输入是 `NoSuchTableError`。护栏的正确性**不得取决于方言**——两条 lane 都
    必须给出同一族 typed 拒绝，且零自有表变更。
    """
    space_id = _space("norm")
    store = _store(postgres_runtime)
    job_id, generation = _start_running(store, space_id, "job-1", "worker-a")
    variants = (
        "WIKI_JOBS",
        "Wiki_Jobs",
        "WIKI_OUTBOX_EVENTS",
        "public.wiki_jobs",
        '"wiki_jobs"',
        " wiki_jobs",
        "wiki_jobs--x",
    )

    with postgres_runtime.factory() as session:
        before = int(
            session.scalar(select(func.count()).select_from(WikiJob)) or 0
        )

    for variant in variants:
        with pytest.raises((DomainWriteViolationError, InvalidJobInputError)):
            store.report_success(
                space_id=space_id,
                job_id=job_id,
                generation=generation,
                domain_writes=(
                    DomainWriteSpec(table=variant, values={"space_id": "other"}),
                ),
            )

    with postgres_runtime.factory() as session:
        after = int(session.scalar(select(func.count()).select_from(WikiJob)) or 0)
    assert after == before, "规范化变体写进了 P1 自有表"
    current = store.get_job(space_id=space_id, job_id=job_id)
    assert current.state is JobState.RUNNING
    assert current.lease_generation == generation


@pytest.mark.integration_postgres
def test_q31_values_may_not_smuggle_sql_on_postgres(
    postgres_runtime: PostgresRuntime,
) -> None:
    """P1.5「收数据不收代码」在 `values` 侧的 PG 证据（独立评审 A3）。

    修复前 `scalar_subquery()` 能把 `wiki_jobs` 的行读出来写进领域表——跨已
    声明边界的信息泄漏；`func.current_database()` 能拿环境信息。写侧虽被方言
    挡住（堆叠语句抛错、自有表零变更），读侧泄漏是真实的。
    """
    import sqlalchemy as sa

    space_id = _space("smuggle")
    domain_table = f"domain_{uuid.uuid4().hex[:12]}"
    with postgres_runtime.engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE TABLE "{domain_table}" (body TEXT)')
    store = _store(postgres_runtime)
    job_id, generation = _start_running(store, space_id, "job-1", "worker-a")

    hostile = (
        sa.select(sa.text("string_agg(id, ',')"))
        .select_from(sa.table("wiki_jobs"))
        .scalar_subquery()
    )
    with pytest.raises(InvalidJobInputError):
        store.report_success(
            space_id=space_id,
            job_id=job_id,
            generation=generation,
            domain_writes=(DomainWriteSpec(table=domain_table, values={"body": hostile}),),
        )
    with pytest.raises(InvalidJobInputError):
        store.report_success(
            space_id=space_id,
            job_id=job_id,
            generation=generation,
            domain_writes=(
                DomainWriteSpec(
                    table=domain_table, values={"body": sa.func.current_database()}
                ),
            ),
        )

    with postgres_runtime.engine.begin() as connection:
        leaked = connection.exec_driver_sql(
            f'SELECT count(*) FROM "{domain_table}"'
        ).scalar_one()
    assert leaked == 0, "自有表内容被泄漏进领域表"
    assert store.get_job(space_id=space_id, job_id=job_id).state is JobState.RUNNING

    # 接受侧：纯标量（含含关键字的字面量）仍正常写入。
    done = store.report_success(
        space_id=space_id,
        job_id=job_id,
        generation=generation,
        domain_writes=(
            DomainWriteSpec(
                table=domain_table, values={"body": "do not touch; call center; begin"}
            ),
        ),
    )
    assert done.state is JobState.SUCCEEDED
    with postgres_runtime.engine.begin() as connection:
        assert (
            connection.exec_driver_sql(f'SELECT count(*) FROM "{domain_table}"').scalar_one() == 1
        )


@pytest.mark.integration_postgres
def test_q25_delivered_but_unmarked_crash_converges_on_postgres(
    postgres_runtime: PostgresRuntime,
) -> None:
    """P1.6 at-least-once（Contract Card 清单第 11 项的 (PG) 覆盖）。

    投递成功但标记前崩溃 ⇒ 该行下一轮被重投，消费端以 event_id 幂等去重
    收敛为恰好一次可观测效果，且最终被持久标记。
    """
    space_id = _space("atleastonce")
    store = _store(postgres_runtime)
    job_id, generation = _start_running(store, space_id, "job-1", "worker-a")
    store.report_success(
        space_id=space_id,
        job_id=job_id,
        generation=generation,
        events=(OutboxEventDraft(event_type="job.succeeded", payload={}, event_id="evt-1"),),
    )
    # 本节点隔离的是 at-least-once 重投语义，不是退避：显式零退避使重投立即
    # 可见（模型默认已改为非零，见 D-2026-07-27-16 后的 B-finding-2 修复）。
    dispatcher = OutboxDispatcher(
        postgres_runtime.factory, _config(dispatch_backoff_seconds=(0.0,))
    )
    seen: list[str] = []

    def deliver_then_crash(event: object) -> None:
        seen.append(event.event_id)  # type: ignore[attr-defined]
        raise RuntimeError("crash after delivery, before marking")

    first = dispatcher.dispatch_pending(space_id=space_id, deliver=deliver_then_crash)
    assert first.delivered_event_ids == ()
    assert first.failed_event_ids == ("evt-1",)
    with postgres_runtime.factory() as session:
        undispatched = session.scalar(
            select(func.count())
            .select_from(WikiOutboxEvent)
            .where(
                WikiOutboxEvent.space_id == space_id,
                WikiOutboxEvent.dispatched_at.is_(None),
            )
        )
    assert undispatched == 1  # 未标记 ⇒ 仍待投递，不丢

    def deliver(event: object) -> None:
        seen.append(event.event_id)  # type: ignore[attr-defined]

    second = dispatcher.dispatch_pending(space_id=space_id, deliver=deliver)
    assert second.delivered_event_ids == ("evt-1",)
    assert seen == ["evt-1", "evt-1"]  # at-least-once：两次投递
    assert len(set(seen)) == 1  # 同一 event_id：消费端幂等可折叠
    assert dispatcher.read_pending(space_id=space_id) == ()
