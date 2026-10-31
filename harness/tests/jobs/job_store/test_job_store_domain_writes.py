"""JobStore（SQLite）：声明式领域写入通道及其表名 / 取值守卫。"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, func, select, text

from insurance_harness.jobs import (
    DomainWriteSpec,
    DomainWriteViolationError,
    InvalidJobInputError,
    JobSnapshot,
    JobState,
    JobStore,
    OutboxEventDraft,
)
from insurance_harness.jobs.tables import WikiJob, WikiOutboxEvent
from tests.jobs.job_store.helpers import SessionFactory, _claimed, make_store


def _job_row_count(factory: SessionFactory) -> int:
    with factory() as session:
        return int(session.scalar(select(func.count()).select_from(WikiJob)) or 0)


def _domain_table(job_engine: Engine) -> None:
    with job_engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS demo_domain (job_id TEXT)"))


def _running_for_domain_write(store: JobStore, key: str = "job-1") -> JobSnapshot:
    """领域写通道用例的 running 任务（与存量 `_running_job` 签名区分）。"""
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key=key)
    claimed = _claimed(store, "space-a", worker_id=f"w-{key}")
    return store.start(space_id="space-a", job_id=claimed.id, generation=claimed.lease_generation)


def test_q19a_completion_entry_takes_data_not_code(factory: SessionFactory) -> None:
    """P1.5（第二轮修订）：完成事务不接受可执行回调,也不交出数据库句柄。

    这是**接口层面**的断言,不是"先构造攻击再拦截":只要有第三方代码在完成
    事务内运行并持有任一 DB 句柄,它就能提交外层事务(Session → Connection →
    语句结果 → …逐层可达),隐藏属性或扫描 SQL 文本只能把泄漏点推深一层。
    """
    import inspect

    import insurance_harness.jobs as jobs_package

    signature = inspect.signature(JobStore.report_success)
    assert "domain_write" not in signature.parameters, "可执行回调入口必须不存在"
    assert "domain_writes" in signature.parameters
    annotation = str(signature.parameters["domain_writes"].annotation)
    assert "Callable" not in annotation, f"领域写参数不得是可调用对象: {annotation}"
    assert "DomainWriteSpec" in annotation

    # 交出句柄的旧类型必须从公共出口消失。
    assert "DomainWriteHandle" not in jobs_package.__all__
    assert not hasattr(jobs_package, "DomainWriteHandle")

    # 声明式规格不得携带任何可执行/句柄字段。
    spec = DomainWriteSpec(table="demo_domain", values={"job_id": "j1"})
    for name in dir(spec):
        if name.startswith("_"):
            continue
        assert not callable(getattr(spec, name)), f"DomainWriteSpec.{name} 不应可调用"


@pytest.mark.parametrize("owned_table", ["wiki_jobs", "wiki_outbox_events"])
def test_q19b_domain_write_cannot_target_p1_owned_tables(
    factory: SessionFactory, job_engine: Engine, owned_table: str
) -> None:
    """P1.5：目标表是 P1 自有表时,在执行任何领域语句之前 typed 拒绝。"""
    _domain_table(job_engine)
    store = make_store(factory)
    running = _running_for_domain_write(store, key=f"owned-{owned_table}")
    victim = store.enqueue(space_id="space-z", job_type="compile", idempotency_key="victim").job

    with pytest.raises(DomainWriteViolationError):
        store.report_success(
            space_id="space-a",
            job_id=running.id,
            generation=running.lease_generation,
            domain_writes=(
                DomainWriteSpec(table="demo_domain", values={"job_id": running.id}),
                DomainWriteSpec(table=owned_table, values={"space_id": "space-z"}),
            ),
        )

    untouched = store.get_job(space_id="space-z", job_id=victim.id)
    assert untouched.state is JobState.QUEUED
    assert untouched.lease_generation == 0
    with factory() as session:
        assert session.execute(text("SELECT count(*) FROM demo_domain")).scalar_one() == 0
        assert int(session.scalar(select(func.count()).select_from(WikiOutboxEvent)) or 0) == 0
    assert store.get_job(space_id="space-a", job_id=running.id).state is JobState.RUNNING


def test_q19c_other_domains_wiki_prefixed_tables_are_not_blocked(
    factory: SessionFactory, job_engine: Engine
) -> None:
    """P1.5：`wiki_` 前缀但非 P1 自有的表(别的交付项所有)不得被误拦。

    旧的 SQL 文本扫描把整个 `wiki_` 前缀封死,连 P6a 的 `wiki_page_revisions`
    与 P2b 的 `wiki_releases` 都写不了;校验改为比对表标识后该误杀消失。
    """
    with job_engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE IF NOT EXISTS wiki_page_revisions (id TEXT, note TEXT)")
        )
    store = make_store(factory)
    running = _running_for_domain_write(store, key="foreign-wiki")

    done = store.report_success(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        domain_writes=(
            # 列值里的字面量恰好含事务控制关键字,同样不得被误拦。
            DomainWriteSpec(
                table="wiki_page_revisions",
                values={"id": running.id, "note": "do not touch; call center; period begin"},
            ),
        ),
    )

    assert done.state is JobState.SUCCEEDED
    with factory() as session:
        assert session.execute(text("SELECT count(*) FROM wiki_page_revisions")).scalar_one() == 1


@pytest.mark.parametrize(
    "variant",
    [
        "WIKI_JOBS",
        "Wiki_Jobs",
        "wiki_JOBS",
        "WIKI_OUTBOX_EVENTS",
        "public.wiki_jobs",
        '"wiki_jobs"',
        " wiki_jobs",
        "wiki_jobs ",
        "\twiki_jobs",
        "wiki_jobs--x",
        "wiki_\uff4aobs",
    ],
)
def test_q30_owned_table_check_is_normalized_and_shape_restricted(
    factory: SessionFactory, job_engine: Engine, variant: str
) -> None:
    """P1.5：自有表校验必须**二次规范化**，且表标识必须是裸标识符。

    第三轮自攻发现的 BLOCKER：原实现用**原样字符串**比对 `OWNED_TABLES`，
    而 `autoload_with` 在 SQLite 上大小写不敏感地解析——`table="WIKI_JOBS"`
    过了校验却真的写进 `wiki_jobs`（别的 Space、任意 state/lease_generation）。
    在 PostgreSQL 上同一输入是 `NoSuchTableError`，即**护栏的正确性取决于
    方言**，这不是护栏。安全比较点必须规范化（019 教训第 10 条），并把形状
    收窄到裸标识符使变体无从构造。
    """
    store = make_store(factory)
    running = _running_for_domain_write(store, key=f"norm-{abs(hash(variant)) % 9973}")
    before = _job_row_count(factory)

    with pytest.raises((DomainWriteViolationError, InvalidJobInputError)):
        store.report_success(
            space_id="space-a",
            job_id=running.id,
            generation=running.lease_generation,
            domain_writes=(DomainWriteSpec(table=variant, values={"space_id": "other"}),),
        )

    assert _job_row_count(factory) == before, f"{variant!r} 写进了 P1 自有表"
    assert store.get_job(space_id="space-a", job_id=running.id).state is JobState.RUNNING


def test_q31_values_may_not_carry_sql_expressions(
    factory: SessionFactory, job_engine: Engine
) -> None:
    """P1.5「收数据不收代码」在 `values` 侧同样成立（独立评审 A3 发现）。

    修复前 `values` 接受任意 SQLAlchemy 表达式对象并编译进 INSERT：
    `sa.select(...).select_from(sa.table("wiki_jobs")).scalar_subquery()` 成功
    把 P1 自有表的行 ID **读出来写进领域表**——跨已声明边界的信息泄漏；
    `sa.func.current_database()` / `sa.literal_column("current_user")` 亦可
    拿到环境信息。写侧虽被方言挡住（堆叠语句抛错、自有表零变更），但"收数据
    不收代码"这条冻结条款在 values 侧被违反。
    """
    import sqlalchemy as sa

    _domain_table(job_engine)
    store = make_store(factory)
    hostile_values: list[tuple[str, dict[str, object]]] = [
        ("text", {"job_id": sa.text("'plain'")}),
        ("func", {"job_id": sa.func.lower("X")}),
        ("literal_column", {"job_id": sa.literal_column("'lc'")}),
        (
            "scalar_subquery",
            {
                "job_id": sa.select(sa.text("count(*)"))
                .select_from(sa.table("wiki_jobs"))
                .scalar_subquery()
            },
        ),
        ("column", {"job_id": sa.column("job_id")}),
    ]

    for label, values in hostile_values:
        running = _running_for_domain_write(store, key=f"expr-{label}")
        with pytest.raises(InvalidJobInputError):
            store.report_success(
                space_id="space-a",
                job_id=running.id,
                generation=running.lease_generation,
                domain_writes=(DomainWriteSpec(table="demo_domain", values=values),),
            )
        assert store.get_job(space_id="space-a", job_id=running.id).state is JobState.RUNNING

    with factory() as session:
        assert session.execute(text("SELECT count(*) FROM demo_domain")).scalar_one() == 0


def test_q31_values_keys_must_be_plain_identifiers(
    factory: SessionFactory, job_engine: Engine
) -> None:
    """列名同样是安全比较点：非裸标识符的键 typed 拒绝。"""
    _domain_table(job_engine)
    store = make_store(factory)

    for bad_key in ("job_id; DROP TABLE x", "job id", '"job_id"', "__class__", ""):
        running = _running_for_domain_write(store, key=f"key-{abs(hash(bad_key)) % 9973}")
        with pytest.raises(InvalidJobInputError):
            store.report_success(
                space_id="space-a",
                job_id=running.id,
                generation=running.lease_generation,
                domain_writes=(DomainWriteSpec(table="demo_domain", values={bad_key: "x"}),),
            )


def test_q31_plain_scalar_values_still_accepted(
    factory: SessionFactory, job_engine: Engine
) -> None:
    """接受侧：纯标量（含 None、bool、数值、datetime、JSON 容器）不被误杀。"""
    from datetime import UTC, datetime

    with job_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS scalar_domain "
                "(txt TEXT, num INTEGER, flag BOOLEAN, ts TIMESTAMP, blob_col TEXT)"
            )
        )
    store = make_store(factory)
    running = _running_for_domain_write(store, key="scalars")

    done = store.report_success(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        domain_writes=(
            DomainWriteSpec(
                table="scalar_domain",
                values={
                    "txt": "do not touch; call center; begin",
                    "num": 42,
                    "flag": True,
                    "ts": datetime(2026, 1, 1, tzinfo=UTC),
                    "blob_col": None,
                },
            ),
        ),
    )

    assert done.state is JobState.SUCCEEDED
    with factory() as session:
        assert session.execute(text("SELECT count(*) FROM scalar_domain")).scalar_one() == 1


def test_q30_unknown_table_is_typed_not_raw_driver_error(
    factory: SessionFactory, job_engine: Engine
) -> None:
    """目标表不存在时必须 typed 拒绝，不得泄漏原始反射异常。"""
    store = make_store(factory)
    running = _running_for_domain_write(store, key="unknown-table")

    with pytest.raises(InvalidJobInputError):
        store.report_success(
            space_id="space-a",
            job_id=running.id,
            generation=running.lease_generation,
            domain_writes=(DomainWriteSpec(table="no_such_domain_table", values={"x": 1}),),
        )


def test_q30_legitimate_lowercase_domain_tables_still_work(
    factory: SessionFactory, job_engine: Engine
) -> None:
    """接受侧：合法裸标识符（含同前缀的其他域表）不被形状收窄误杀。"""
    with job_engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE IF NOT EXISTS wiki_page_revisions (id TEXT, note TEXT)")
        )
    _domain_table(job_engine)
    store = make_store(factory)
    running = _running_for_domain_write(store, key="accept-shape")

    done = store.report_success(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        domain_writes=(
            DomainWriteSpec(table="demo_domain", values={"job_id": running.id}),
            DomainWriteSpec(table="wiki_page_revisions", values={"id": running.id, "note": "ok"}),
        ),
    )

    assert done.state is JobState.SUCCEEDED


def test_q19d_declared_domain_writes_commit_atomically(
    factory: SessionFactory, job_engine: Engine
) -> None:
    """接受侧：声明式领域写与状态、outbox 同事务原子提交。"""
    _domain_table(job_engine)
    store = make_store(factory)
    running = _running_for_domain_write(store)

    done = store.report_success(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
        domain_writes=(DomainWriteSpec(table="demo_domain", values={"job_id": running.id}),),
    )

    assert done.state is JobState.SUCCEEDED
    with factory() as session:
        assert session.execute(text("SELECT count(*) FROM demo_domain")).scalar_one() == 1
        assert int(session.scalar(select(func.count()).select_from(WikiOutboxEvent)) or 0) == 1
