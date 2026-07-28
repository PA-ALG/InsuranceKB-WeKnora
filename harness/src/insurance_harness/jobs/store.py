"""OpenSpec 035 P1 JobStore：任务状态与 lease 的唯一存储层写入口。

事务边界（tasks Contract Card）：enqueue、claim（維护 + 领取两个事务）、
heartbeat、单次状态转换、「完成 + 领域写 + outbox 追加」各为一个
PostgreSQL 事务。过期判定只用数据库时钟（P1.3，PostgreSQL 取
`clock_timestamp()` 语句时刻，锁等待不吞噬 lease 时长，review I3）；写
权威只看 lease generation。并发限额由执行 claim 的实例按其配置执行：全部
实例必须共享同一配置来源（review M18，见 `JobRuntimeConfig`）。SQLite 仅
deterministic 测试用，真实并发证据只来自 PG lane（P1.12）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import MetaData, Table, func, select, text
from sqlalchemy import insert as sa_insert
from sqlalchemy.exc import IntegrityError, NoSuchTableError
from sqlalchemy.orm import Session

from insurance_harness.jobs.errors import (
    DomainWriteViolationError,
    IllegalTransitionError,
    InvalidJobInputError,
    LeaseExpiredError,
    SpaceScopeError,
    StaleGenerationError,
)
from insurance_harness.jobs.models import (
    TERMINAL_STATES,
    ClaimedJob,
    ClaimOutcome,
    DecisionOutcome,
    DomainWriteSpec,
    EnqueueResult,
    ErrorClass,
    JobFailure,
    JobRuntimeConfig,
    JobSnapshot,
    JobState,
    NoClaimableJob,
    OutboxEventDraft,
    ReclaimReport,
    ensure_transition,
    route_failure,
)
from insurance_harness.jobs.tables import WikiJob

SessionFactory = Callable[[], Session]

_SQLITE_NOW = text("SELECT strftime('%Y-%m-%d %H:%M:%f', 'now')")
_POSTGRES_NOW = text("SELECT clock_timestamp()")
_ACTIVE_STATES = (JobState.LEASED.value, JobState.RUNNING.value)
# 稳定 64 位 claim 序列化锁键（pg_advisory_xact_lock；SQLite 单写者无需）。
_CLAIM_LOCK_KEY = int.from_bytes(b"ikb035cl", "big", signed=True)

# 输入合同上限与列宽一致；越界在存储层前置 typed 拒绝，不泄漏 DataError。
MAX_SPACE_ID_LENGTH = 36
MAX_JOB_ID_LENGTH = 36
MAX_JOB_TYPE_LENGTH = 64
MAX_IDEMPOTENCY_KEY_LENGTH = 255
MAX_WORKER_ID_LENGTH = 128


def database_now(session: Session) -> datetime:
    """读数据库时钟（UTC）；过期与调度判定不得使用 worker 本地时钟。

    PostgreSQL 用 `clock_timestamp()`（语句时刻）：在 advisory 锁等待之后
    读取的时刻仍然新鲜，签发的 lease 不会「出生即过期」（review I3）。
    """
    bind = session.get_bind()
    if bind.dialect.name == "sqlite":
        raw = session.execute(_SQLITE_NOW).scalar_one()
        return datetime.fromisoformat(str(raw)).replace(tzinfo=UTC)
    value = session.execute(_POSTGRES_NOW).scalar_one()
    assert isinstance(value, datetime)
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite 存储丢失 offset；所有列值均按 UTC 写入，读回补齐 tzinfo。"""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _snapshot(row: WikiJob) -> JobSnapshot:
    available_at = _aware(row.available_at)
    enqueued_at = _aware(row.enqueued_at)
    assert available_at is not None and enqueued_at is not None
    return JobSnapshot(
        id=row.id,
        space_id=row.space_id,
        job_type=row.job_type,
        idempotency_key=row.idempotency_key,
        payload=dict(row.payload),
        state=JobState(row.state),
        attempt=row.attempt,
        lease_generation=row.lease_generation,
        worker_id=row.worker_id,
        available_at=available_at,
        lease_expires_at=_aware(row.lease_expires_at),
        enqueued_at=enqueued_at,
        started_at=_aware(row.started_at),
        finished_at=_aware(row.finished_at),
        error_class=ErrorClass(row.error_class) if row.error_class else None,
        error_summary=row.error_summary,
    )


def _enqueue_result(row: WikiJob, *, deduplicated: bool) -> EnqueueResult:
    snapshot = _snapshot(row)
    return EnqueueResult(
        job=snapshot,
        deduplicated=deduplicated,
        terminal=snapshot.state in TERMINAL_STATES,
    )


def validated_text(value: str, name: str, *, max_length: int) -> str:
    """输入合同：非空、无 NUL、长度受限；违规 typed 拒绝（review I6/M16）。"""
    if not isinstance(value, str) or not value:
        raise InvalidJobInputError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise InvalidJobInputError(f"{name} must not contain NUL characters")
    if len(value) > max_length:
        raise InvalidJobInputError(f"{name} must be at most {max_length} characters")
    return value


def validated_limit(value: int, name: str) -> int:
    """只读入口的分页/批量上限校验（P1.9 读路径输入合同，D-2026-07-27-16）。

    `limit = 0` 会产生与"无事可做"完全不可区分的空结果，`limit < 0` 会泄漏
    原始驱动异常；两者一律 typed `invalid_input`。
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidJobInputError(f"{name} must be an integer")
    if value < 1:
        raise InvalidJobInputError(f"{name} must be >= 1")
    return value


def require_active_lease(session: Session, row: WikiJob, *, now: datetime | None = None) -> None:
    """写权威过期门（P1.3 写权威合同，D-2026-07-27-16）。

    写权威 = 当前 generation ∧ lease 未过期。本函数是**唯一**执法点，
    heartbeat/start/结果提交/失败上报/outbox 追加共用它——四条路径不得
    各自实现或省略过期判定，否则"被计入并发上限的集合"与"仍能写的集合"
    会不一致（C1 的窄计数 + 宽写权威即由此裂开）。判定只用数据库时钟。
    """
    current = database_now(session) if now is None else now
    expires_at = _aware(row.lease_expires_at)
    if expires_at is None or expires_at <= current:
        raise LeaseExpiredError(job_id=row.id)


def validated_payload(payload: Mapping[str, Any] | None, name: str = "payload") -> dict[str, Any]:
    """payload 必须是可 JSON 序列化的映射；违规 typed 拒绝（review I6）。"""
    materialized = dict(payload or {})
    try:
        json.dumps(materialized)
    except (TypeError, ValueError) as error:
        raise InvalidJobInputError(f"{name} must be JSON-serializable: {error}") from error
    return materialized


#: P1 自有的两张表（P1.5 领域写通道合同，D-2026-07-27-16）。**精确枚举**，
#: 不按 `wiki_` 前缀封杀：其他 `wiki_` 前缀表属别的交付项所有（如 P6a 的
#: `wiki_page_revisions`、P2b 的 `wiki_releases`），误拦它们会让那些窗口
#: 无法写自己的领域表（第二轮评审 N2）。
OWNED_TABLES: frozenset[str] = frozenset({"wiki_jobs", "wiki_outbox_events"})

MAX_TABLE_NAME_LENGTH = 63  # PostgreSQL 标识符上限

#: 领域写目标表只接受**裸标识符**（P1.5，D-2026-07-27-16 第三轮自攻修订）。
#: 形状收窄使"规范化后等于自有表"的各种变体无从构造：不允许点号（schema
#: 限定）、引号、空白、注释标记、非 ASCII（Unicode 同形/大小写折叠）。
_BARE_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


#: 领域写列值只接受**纯标量**（P1.5「收数据不收代码」，D-2026-07-27-16
#: 第三轮独立评审 A3 修订）。SQLAlchemy 表达式对象会被编译进 INSERT——实测
#: `select(...).select_from(table("wiki_jobs")).scalar_subquery()` 能把 P1
#: 自有表的行读出来写进领域表（跨已声明边界的信息泄漏），`func.current_database()`
#: 与 `literal_column("current_user")` 能拿环境信息。写侧虽被方言挡住，但
#: "收数据不收代码"这条冻结条款在 values 侧必须同样成立。
_SCALAR_VALUE_TYPES: tuple[type, ...] = (str, bytes, bool, int, float, datetime, date, Decimal)


def _validated_domain_value(key: str, value: Any) -> Any:
    """校验单个列值是纯数据：拒绝任何可编译成 SQL 的对象（P1.5）。"""
    if value is None or isinstance(value, _SCALAR_VALUE_TYPES):
        return value
    if isinstance(value, Mapping | list | tuple):
        # JSON 容器：递归确认其中不夹带表达式对象。
        items = value.values() if isinstance(value, Mapping) else value
        for item in items:
            _validated_domain_value(key, item)
        return value
    raise InvalidJobInputError(
        f"domain write value for {key!r} must be plain data, got "
        f"{type(value).__module__}.{type(value).__name__}; SQL expression objects are refused"
    )


def _validated_domain_values(values: Mapping[str, Any]) -> dict[str, Any]:
    """校验列名是裸标识符、列值是纯标量（P1.5）。列名同样是安全比较点。"""
    validated: dict[str, Any] = {}
    for key, value in values.items():
        if not isinstance(key, str):
            raise InvalidJobInputError("domain write value keys must be strings")
        column = key.strip().casefold()
        if not _BARE_IDENTIFIER.fullmatch(column):
            raise InvalidJobInputError(
                f"domain write column must be a bare lowercase identifier (got {key!r})"
            )
        validated[column] = _validated_domain_value(key, value)
    return validated


def _canonical_table(raw: str) -> str:
    """把表标识规范化为安全比较用的 canonical 形式（P1.5）。

    第三轮自攻的 BLOCKER：原实现用**原样字符串**比对 `OWNED_TABLES`，而
    `autoload_with` 在 SQLite 上大小写不敏感地解析——`table="WIKI_JOBS"` 过了
    校验却真的写进 `wiki_jobs`（伪造别的 Space 的行、任意 state 与
    `lease_generation`）。同一输入在 PostgreSQL 上是 `NoSuchTableError`，
    即护栏的正确性取决于方言，这不是护栏。安全比较点必须自己规范化，不能
    依赖底层解析恰好宽或恰好严（019 教训第 10 条）。
    """
    name = validated_text(raw, "domain write table", max_length=MAX_TABLE_NAME_LENGTH)
    canonical = name.strip().casefold()
    if not _BARE_IDENTIFIER.fullmatch(canonical):
        raise InvalidJobInputError(
            "domain write table must be a bare lowercase identifier "
            f"(got {raw!r}); schema-qualified, quoted, padded or non-ASCII forms are refused"
        )
    return canonical


def _execute_domain_writes(
    session: Session, specs: Sequence[DomainWriteSpec], *, job_id: str
) -> None:
    """在完成事务内执行声明式领域写（P1.5 领域写通道合同，D-2026-07-27-16）。

    存储层自己执行，调用方从不持有 Session/Connection/语句结果——因此
    "回调提交外层事务使领域行落库而任务仍 running" 在接口层面无法构造。

    目标表校验在**数据**上进行（比对表标识），不扫描 SQL 文本：后者既可被
    绕过（公共属性即可拿到活连接），又会误杀合法负载（同前缀的其他域自有表、
    含事务控制关键字的字符串字面量）。全部规格先校验、后执行：任一非法即在
    执行任何领域语句之前 typed 拒绝。
    """
    if not specs:
        return
    canonical_tables: list[str] = []
    canonical_values: list[dict[str, Any]] = []
    for spec in specs:
        table = _canonical_table(spec.table)
        if table in OWNED_TABLES:
            raise DomainWriteViolationError(
                f"domain write may not target P1-owned table {table!r}", job_id=job_id
            )
        if not spec.values:
            raise InvalidJobInputError("domain write values must not be empty")
        canonical_tables.append(table)
        canonical_values.append(_validated_domain_values(spec.values))
    metadata = MetaData()
    bind = session.get_bind()
    for table, values in zip(canonical_tables, canonical_values, strict=True):
        # 只用 canonical 名反射与执行：校验看到的名与实际打到的表必须是同一个。
        try:
            table_obj = Table(table, metadata, autoload_with=bind)
        except NoSuchTableError as error:
            raise InvalidJobInputError(f"domain write target table not found: {table!r}") from error
        # 列必须真实存在：未知列 typed 拒绝，而不是留给编译期抛
        # `CompileError`（P1.5 读路径/输入合同一致性）。
        unknown = sorted(set(values) - {column.name.casefold() for column in table_obj.columns})
        if unknown:
            raise InvalidJobInputError(
                f"domain write references unknown columns on {table!r}: {unknown}"
            )
        session.execute(sa_insert(table_obj).values(**values))


class JobStore:
    """P1 任务存储层单一入口；调用方不得绕过本类直接改行（P1.1）。

    per-Space/全局限额由本实例的 `JobRuntimeConfig` 执行；多实例配置不
    一致会弱化限额（review M18）——部署必须统一配置来源。
    """

    def __init__(self, session_factory: SessionFactory, config: JobRuntimeConfig) -> None:
        self._session_factory = session_factory
        self._config = config

    @property
    def config(self) -> JobRuntimeConfig:
        return self._config

    # --- P1.5 幂等 enqueue ---

    def enqueue(
        self,
        *,
        space_id: str,
        job_type: str,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
    ) -> EnqueueResult:
        """插入新任务或返回 typed dedup；键由消费方按批次/裁决铸造。

        dedup 命中终态行时 `terminal=True`：新一次授权处理必须铸新键
        （P1.5，review M17）。
        """
        validated_text(space_id, "space_id", max_length=MAX_SPACE_ID_LENGTH)
        validated_text(job_type, "job_type", max_length=MAX_JOB_TYPE_LENGTH)
        validated_text(
            idempotency_key, "idempotency_key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH
        )
        safe_payload = validated_payload(payload)
        with self._session_factory() as session:
            try:
                with session.begin():
                    now = database_now(session)
                    row = WikiJob(
                        space_id=space_id,
                        job_type=job_type,
                        idempotency_key=idempotency_key,
                        payload=safe_payload,
                        state=JobState.QUEUED.value,
                        attempt=0,
                        lease_generation=0,
                        available_at=now,
                        enqueued_at=now,
                    )
                    session.add(row)
                return _enqueue_result(row, deduplicated=False)
            except IntegrityError:
                with session.begin():
                    existing = session.execute(
                        select(WikiJob).where(
                            WikiJob.space_id == space_id,
                            WikiJob.job_type == job_type,
                            WikiJob.idempotency_key == idempotency_key,
                        )
                    ).scalar_one_or_none()
                    if existing is None:
                        raise
                    return _enqueue_result(existing, deduplicated=True)

    # --- P1.2 claim（FOR UPDATE SKIP LOCKED） ---

    def claim(self, *, space_ids: Sequence[str], worker_id: str) -> ClaimOutcome:
        """在声明 scope 内领取一个任务；无可领取返回 typed 空结果。

        事务 1（无串行化锁，review I4）：有界回收过期 lease + promote 到期
        retry_wait；事务 2（advisory 串行化）：计数 → 领取。

        并发计数包含**全部** `leased | running` 行，不按 lease 是否过期缩小
        分母（P1.8 限额会计合同，D-2026-07-27-16）：未被回收的过期行其持有者
        可能仍存活并消耗外部资源。为避免因此永久饥饿（review C1 的动机），
        饱和且存在过期行时先做一次 `maintenance_batch_size` 有界、无 Space
        过滤的回收再重算，仍饱和才返回 typed 拒绝。
        """
        if not space_ids:
            raise InvalidJobInputError("space_ids must not be empty")
        scope = tuple(
            dict.fromkeys(
                validated_text(space, "space_ids entry", max_length=MAX_SPACE_ID_LENGTH)
                for space in space_ids
            )
        )
        validated_text(worker_id, "worker_id", max_length=MAX_WORKER_ID_LENGTH)
        batch = self._config.maintenance_batch_size
        with self._session_factory() as session:
            with session.begin():
                now = database_now(session)
                # P1.2「或满足 P1.3 的过期回收条件」+ P1.1 第 5 条：回收与
                # backoff requeue 都仅限存储层，在领取前的独立事务内执行。
                self._reclaim_locked(session, scope, now, limit=batch)
                self._promote_due_retries(session, scope, now, limit=batch)
        with self._session_factory() as session:
            with session.begin():
                # 限额检查与领取必须原子；PostgreSQL 以事务级 advisory 锁
                # 串行化「计数 → 领取」，行级仍用 SKIP LOCKED 不互相阻塞。
                if session.get_bind().dialect.name == "postgresql":
                    session.execute(
                        text("SELECT pg_advisory_xact_lock(:key)"), {"key": _CLAIM_LOCK_KEY}
                    )
                # 锁后读钟：advisory 等待不吞噬 lease 时长（review I3）。
                now = database_now(session)
                global_active = self._count_active(session, scope=None)
                if global_active >= self._config.global_concurrency_limit:
                    # P1.8 限额会计合同（D-2026-07-27-16）：计数包含过期但未
                    # 回收的行——它们的持有者可能仍存活并消耗外部资源。为避免
                    # 因此永久饥饿（C1 的动机），饱和时先做一次无 Space 过滤
                    # 的有界回收（使过期行被 fenced）再重算，仍饱和才拒绝。
                    if self._reclaim_saturated(session, now):
                        global_active = self._count_active(session, scope=None)
                    if global_active >= self._config.global_concurrency_limit:
                        return NoClaimableJob(reason="global_concurrency_limit")
                active_by_space: dict[str, int] = {
                    row_space_id: int(row_count)
                    for row_space_id, row_count in session.execute(
                        select(WikiJob.space_id, func.count())
                        .where(
                            WikiJob.space_id.in_(scope),
                            WikiJob.state.in_(_ACTIVE_STATES),
                        )
                        .group_by(WikiJob.space_id)
                    ).tuples()
                }
                eligible = tuple(
                    space_id
                    for space_id in scope
                    if active_by_space.get(space_id, 0)
                    < self._config.per_space_concurrency_limit
                )
                if not eligible:
                    # per-Space 饱和同样先尝试有界回收再重算（同上合同）。
                    if self._reclaim_saturated(session, now):
                        active_by_space = {
                            row_space_id: int(row_count)
                            for row_space_id, row_count in session.execute(
                                select(WikiJob.space_id, func.count())
                                .where(
                                    WikiJob.space_id.in_(scope),
                                    WikiJob.state.in_(_ACTIVE_STATES),
                                )
                                .group_by(WikiJob.space_id)
                            ).tuples()
                        }
                        eligible = tuple(
                            space_id
                            for space_id in scope
                            if active_by_space.get(space_id, 0)
                            < self._config.per_space_concurrency_limit
                        )
                if not eligible:
                    # scope 内全部 Space 饱和：不是空队列（review I12）。
                    return NoClaimableJob(reason="per_space_concurrency_limit")
                candidate = session.execute(
                    select(WikiJob)
                    .where(
                        WikiJob.space_id.in_(eligible),
                        WikiJob.state == JobState.QUEUED.value,
                        WikiJob.available_at <= now,
                    )
                    .order_by(WikiJob.enqueued_at, WikiJob.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                ).scalar_one_or_none()
                if candidate is None:
                    return NoClaimableJob(reason="empty")
                ensure_transition(JobState.QUEUED, JobState.LEASED, candidate.id)
                candidate.state = JobState.LEASED.value
                candidate.worker_id = worker_id
                candidate.lease_generation += 1
                candidate.lease_expires_at = now + timedelta(
                    seconds=self._config.lease_seconds
                )
                claimed = _snapshot(candidate)
        return ClaimedJob(job=claimed)

    # --- P1.3 lease、heartbeat 与 fencing ---

    def verify_active_fence(
        self,
        *,
        space_id: str,
        job_id: str,
        generation: int,
        attempt: int,
    ) -> JobSnapshot:
        """只读确认当前 worker 仍可开始一次有外部副作用的动作。

        校验当前 Space/job、generation、`running`、attempt 与未过期 lease；
        使用数据库时钟，且不续租、不推进状态、不写 outbox。PostgreSQL 的
        共享行锁只覆盖本次短事务，返回前即释放，调用方不得跨 provider I/O
        持有数据库事务。
        """
        validated_text(space_id, "space_id", max_length=MAX_SPACE_ID_LENGTH)
        validated_text(job_id, "job_id", max_length=MAX_JOB_ID_LENGTH)
        with self._session_factory() as session:
            with session.begin():
                row = session.execute(
                    select(WikiJob)
                    .where(WikiJob.id == job_id, WikiJob.space_id == space_id)
                    .with_for_update(read=True)
                ).scalar_one_or_none()
                if row is None:
                    raise SpaceScopeError()
                self._check_generation(row, generation)
                state = JobState(row.state)
                if state is not JobState.RUNNING:
                    raise IllegalTransitionError(state, state, row.id)
                if attempt != row.attempt:
                    raise InvalidJobInputError(
                        f"attempt {attempt} does not match current attempt {row.attempt}"
                    )
                now = database_now(session)
                require_active_lease(session, row, now=now)
                return _snapshot(row)

    def heartbeat(self, *, space_id: str, job_id: str, generation: int) -> JobSnapshot:
        """延长 lease；仅当 generation 等于当前值且状态 leased|running。

        已按数据库时钟过期的 lease 不可复活（review M14）：typed
        `lease_expired` 拒绝，任务只能按 P1.1 第 10 条回收。
        """
        with self._session_factory() as session:
            with session.begin():
                row = self._locked_job(session, space_id, job_id)
                self._check_generation(row, generation)
                state = JobState(row.state)
                if state not in (JobState.LEASED, JobState.RUNNING):
                    raise IllegalTransitionError(state, state, row.id)
                now = database_now(session)
                require_active_lease(session, row, now=now)
                row.lease_expires_at = now + timedelta(seconds=self._config.lease_seconds)
                return _snapshot(row)

    def start(self, *, space_id: str, job_id: str, generation: int) -> JobSnapshot:
        """`leased → running`：同 generation 的 worker 开始执行，attempt +1。

        写权威 = 当前 generation ∧ lease 未过期（P1.3，D-2026-07-27-16）：
        lease 已过期的持有者即使 generation 未变也无权继续，typed
        `lease_expired` 拒绝并零变更；该任务只能经回收后由新 generation 继续。
        """
        with self._session_factory() as session:
            with session.begin():
                row = self._locked_job(session, space_id, job_id)
                self._check_generation(row, generation)
                ensure_transition(JobState(row.state), JobState.RUNNING, row.id)
                now = database_now(session)
                require_active_lease(session, row, now=now)
                row.state = JobState.RUNNING.value
                row.attempt += 1
                row.started_at = now
                return _snapshot(row)

    # --- P1.5/P1.6 完成事务与 P1.4 失败路由 ---

    def report_success(
        self,
        *,
        space_id: str,
        job_id: str,
        generation: int,
        events: Sequence[OutboxEventDraft] = (),
        domain_writes: Sequence[DomainWriteSpec] = (),
    ) -> JobSnapshot:
        """完成事务：领域写 + outbox 追加 + `running → succeeded` 同事务。

        本方法是任务领域结果的唯一写入口；fencing + 终态保证至多成功一
        次，重复完成 typed 拒绝且零领域写、零 outbox 追加（P1.5/P1.6）。

        领域写是**声明式**的（P1.5 领域写通道合同，D-2026-07-27-16）：完成
        事务收数据、不收代码，本方法自己执行 `domain_writes`，调用方从不持有
        Session/Connection/语句结果。因此"回调提交外层事务使领域行落库而任务
        仍 `running`、outbox 为空"这一状态在**接口层面无法构造**——上一版把
        可执行回调放进事务再试图进程内沙箱它，被证明不可完成（句柄逐层可达，
        公共属性即可拿到活连接）。成功时清空历史错误残留（review M15）。
        """
        from insurance_harness.jobs.outbox import append_job_event

        with self._session_factory() as session:
            with session.begin():
                row = self._locked_job(session, space_id, job_id)
                self._check_generation(row, generation)
                ensure_transition(JobState(row.state), JobState.SUCCEEDED, row.id)
                now = database_now(session)
                require_active_lease(session, row, now=now)
                _execute_domain_writes(session, domain_writes, job_id=job_id)
                for draft in events:
                    append_job_event(
                        session,
                        space_id=space_id,
                        job_id=job_id,
                        generation=generation,
                        draft=draft,
                        now=now,
                    )
                row.state = JobState.SUCCEEDED.value
                row.worker_id = None
                row.lease_expires_at = None
                row.finished_at = now
                row.error_class = None
                row.error_summary = None
                return _snapshot(row)

    def report_failure(
        self, *, space_id: str, job_id: str, generation: int, failure: JobFailure
    ) -> JobSnapshot:
        """按封闭错误分类确定性路由失败（P1.4）；同事务释放 lease。"""
        with self._session_factory() as session:
            with session.begin():
                row = self._locked_job(session, space_id, job_id)
                self._check_generation(row, generation)
                source = JobState(row.state)
                if source is not JobState.RUNNING:
                    # P1.1 storage-only 执法（D-2026-07-27-16）：持有有效 lease
                    # 但尚未 start 的 leased 行不得经调用方之手直接进入终态或
                    # 等待态——否则 `leased → dead_letter` 这对 storage-only
                    # 转换有调用方直达旁路，且 max_attempts 预算被作废。
                    # pre-start 失败一律由回收路径按 max_attempts 兜底。
                    raise IllegalTransitionError(source, source, row.id)
                now = database_now(session)
                require_active_lease(session, row, now=now)
                policy = self._config.policy_for(row.job_type)
                target = route_failure(
                    failure.error_class, attempt=row.attempt, max_attempts=policy.max_attempts
                )
                ensure_transition(source, target, row.id)
                row.state = target.value
                row.worker_id = None
                row.lease_expires_at = None
                row.error_class = failure.error_class.value
                row.error_summary = failure.summary
                if target is JobState.RETRY_WAIT:
                    row.available_at = now + timedelta(
                        seconds=policy.backoff_delay(attempt=row.attempt)
                    )
                if target in (JobState.DEAD_LETTER, JobState.BLOCKED):
                    row.finished_at = now
                return _snapshot(row)

    # --- P1.7 人工 Decision 幂等唤醒 ---

    def resume_after_decision(self, *, space_id: str, job_id: str) -> DecisionOutcome:
        """`awaiting_human → queued` 的唯一入口。

        当且仅当当前处于 awaiting_human 才 requeue；已被唤醒过的行返回
        typed `duplicate`，从未 awaiting 的行返回 typed `not_awaiting`
        （review I11）；二者零行变更。

        判据是**不可变的持久事实** `human_decision_resumed_at`（P1.7 判据
        不可变合同，D-2026-07-27-16）：首次唤醒成功时写入、此后不再修改。
        原实现用 `error_class == 'human_required'` 代理"是否曾经 awaiting"，
        而回收无条件写 `retryable`、`report_failure`/`report_success` 也会
        覆写它——于是重投的 Decision 在任务经历一次租约过期后收到错误的
        "从未等待人工"语义。
        """
        with self._session_factory() as session:
            with session.begin():
                row = self._locked_job(session, space_id, job_id)
                state = JobState(row.state)
                if state is not JobState.AWAITING_HUMAN:
                    resumed_before = row.human_decision_resumed_at is not None
                    return DecisionOutcome(
                        job_id=row.id,
                        status="duplicate" if resumed_before else "not_awaiting",
                    )
                ensure_transition(JobState.AWAITING_HUMAN, JobState.QUEUED, row.id)
                now = database_now(session)
                row.state = JobState.QUEUED.value
                row.available_at = now
                if row.human_decision_resumed_at is None:
                    row.human_decision_resumed_at = now
                return DecisionOutcome(job_id=row.id, status="resumed")

    # --- P1.1 第 10 条 / P1.10：过期 lease 回收 ---

    def reclaim_expired_leases(self, *, space_ids: Sequence[str]) -> ReclaimReport:
        """任何实例可执行的回收：只依赖 PostgreSQL 持久状态与数据库时钟。

        单次调用最多处理 `maintenance_batch_size` 行（review I4）；剩余
        过期 lease 由后续调用继续收敛。
        """
        if not space_ids:
            raise InvalidJobInputError("space_ids must not be empty")
        scope = tuple(
            dict.fromkeys(
                validated_text(space, "space_ids entry", max_length=MAX_SPACE_ID_LENGTH)
                for space in space_ids
            )
        )
        with self._session_factory() as session:
            with session.begin():
                now = database_now(session)
                return self._reclaim_locked(
                    session, scope, now, limit=self._config.maintenance_batch_size
                )

    def reclaim_expired_leases_all_spaces(self) -> ReclaimReport:
        """跨 Space 回收入口（P1.10 回收可达性合同，D-2026-07-27-16）。

        显式命名的全局入口，与 `global_job_metrics` 同形：回收不得依赖任何
        调用方对 Space 集合的枚举，否则最后一个 worker 崩溃的 Space 其过期
        行永不收敛（既不 requeue 也不 dead_letter）。单次调用同样受
        `maintenance_batch_size` 约束；剩余行由后续调用继续收敛。
        """
        with self._session_factory() as session:
            with session.begin():
                now = database_now(session)
                return self._reclaim_locked(
                    session, None, now, limit=self._config.maintenance_batch_size
                )

    @staticmethod
    def _count_active(session: Session, *, scope: tuple[str, ...] | None) -> int:
        """P1.8 限额分母：全部 `leased | running` 行，不按 lease 是否过期缩小。"""
        conditions = [WikiJob.state.in_(_ACTIVE_STATES)]
        if scope is not None:
            conditions.insert(0, WikiJob.space_id.in_(scope))
        return int(
            session.scalar(select(func.count()).select_from(WikiJob).where(*conditions)) or 0
        )

    def _reclaim_saturated(self, session: Session, now: datetime) -> bool:
        """限额饱和时的反饥饿动作：无 Space 过滤的一次有界回收。

        返回是否确实回收了行（决定调用方是否值得重算计数）。批量受
        `maintenance_batch_size` 约束，因此不会在串行段内产生无界工作。
        """
        report = self._reclaim_locked(
            session, None, now, limit=self._config.maintenance_batch_size
        )
        return bool(report.requeued_job_ids or report.dead_lettered_job_ids)

    def _reclaim_locked(
        self, session: Session, scope: tuple[str, ...] | None, now: datetime, *, limit: int
    ) -> ReclaimReport:
        """回收已过期 lease：记 `lease_expired` retryable 并按 `max_attempts`
        路由（P1.4）；每次回收使 generation 单调 +1，被逐出 worker 的写入立即
        stale（review C2）。行锁 SKIP LOCKED，批量受 `limit` 约束（review I4）。

        `scope=None` 表示**不带 Space 过滤**（P1.10 回收可达性合同，
        D-2026-07-27-16）：回收是存储层维护动作，不读写领域数据、不向调用方
        返回任何跨 Space 内容，因此不构成 P1.8 跨 Space fail-closed 的例外。
        """
        conditions = [
            WikiJob.state.in_(_ACTIVE_STATES),
            WikiJob.lease_expires_at <= now,
        ]
        if scope is not None:
            conditions.insert(0, WikiJob.space_id.in_(scope))
        expired_rows = (
            session.execute(
                select(WikiJob)
                .where(*conditions)
                .order_by(WikiJob.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        requeued: list[str] = []
        dead_lettered: list[str] = []
        for row in expired_rows:
            policy = self._config.policy_for(row.job_type)
            if JobState(row.state) is JobState.LEASED:
                # P1.1 第 10 条（D-2026-07-27-16）：本次投递从未进入 running，
                # worker 未能自报 start，attempt 必须由回收记入——否则
                # claim→start 之间崩溃的任务永不推进 attempt、无界重排队。
                # running 行的 attempt 已由 start 计入，不重复计数。
                row.attempt += 1
            target = (
                JobState.DEAD_LETTER if row.attempt >= policy.max_attempts else JobState.QUEUED
            )
            ensure_transition(JobState(row.state), target, row.id, storage_layer=True)
            row.state = target.value
            row.worker_id = None
            row.lease_expires_at = None
            row.lease_generation += 1
            row.error_class = ErrorClass.RETRYABLE.value
            row.error_summary = "lease_expired"
            if target is JobState.DEAD_LETTER:
                row.finished_at = now
                dead_lettered.append(row.id)
            else:
                row.available_at = now
                requeued.append(row.id)
        return ReclaimReport(
            requeued_job_ids=tuple(requeued), dead_lettered_job_ids=tuple(dead_lettered)
        )

    @staticmethod
    def _promote_due_retries(
        session: Session, scope: tuple[str, ...], now: datetime, *, limit: int
    ) -> None:
        """`retry_wait → queued`：仅当配置化 backoff 按数据库时钟已到期。"""
        due_rows = (
            session.execute(
                select(WikiJob)
                .where(
                    WikiJob.space_id.in_(scope),
                    WikiJob.state == JobState.RETRY_WAIT.value,
                    WikiJob.available_at <= now,
                )
                .order_by(WikiJob.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        for row in due_rows:
            ensure_transition(JobState(row.state), JobState.QUEUED, row.id, storage_layer=True)
            row.state = JobState.QUEUED.value

    # --- P1.8 scope 化读取 ---

    def get_job(self, *, space_id: str, job_id: str) -> JobSnapshot:
        """按声明 Space 读取任务；不一致或不存在一律 fail closed。"""
        with self._session_factory() as session:
            with session.begin():
                validated_text(space_id, "space_id", max_length=MAX_SPACE_ID_LENGTH)
                validated_text(job_id, "job_id", max_length=MAX_JOB_ID_LENGTH)
                row = session.execute(
                    select(WikiJob).where(WikiJob.id == job_id, WikiJob.space_id == space_id)
                ).scalar_one_or_none()
                if row is None:
                    raise SpaceScopeError()
                return _snapshot(row)

    # --- 内部：fenced write guard ---

    def _locked_job(self, session: Session, space_id: str, job_id: str) -> WikiJob:
        """FOR UPDATE 锁定并校验 scope；不一致/不存在 fail closed（P1.8）。"""
        validated_text(space_id, "space_id", max_length=MAX_SPACE_ID_LENGTH)
        validated_text(job_id, "job_id", max_length=MAX_JOB_ID_LENGTH)
        row = session.execute(
            select(WikiJob)
            .where(WikiJob.id == job_id, WikiJob.space_id == space_id)
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            raise SpaceScopeError()
        return row

    @staticmethod
    def _check_generation(row: WikiJob, generation: int) -> None:
        """generation 不等于当前值的写入一律 typed `stale_generation`。"""
        if generation != row.lease_generation:
            raise StaleGenerationError(
                expected=row.lease_generation, actual=generation, job_id=row.id
            )
