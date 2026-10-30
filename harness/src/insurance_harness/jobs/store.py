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

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from insurance_harness.jobs.admission import admit_spaces
from insurance_harness.jobs.domain_writes import execute_domain_writes
from insurance_harness.jobs.errors import (
    IllegalTransitionError,
    InvalidJobInputError,
    SpaceScopeError,
)
from insurance_harness.jobs.lease_reclaim import (
    promote_due_retries,
    reclaim_expired,
)
from insurance_harness.jobs.models import (
    ClaimedJob,
    ClaimOutcome,
    DecisionOutcome,
    DomainWriteSpec,
    EnqueueResult,
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
from insurance_harness.jobs.snapshots import enqueue_result, job_snapshot
from insurance_harness.jobs.store_rules import (
    MAX_IDEMPOTENCY_KEY_LENGTH,
    MAX_JOB_ID_LENGTH,
    MAX_JOB_TYPE_LENGTH,
    MAX_SPACE_ID_LENGTH,
    MAX_WORKER_ID_LENGTH,
    SessionFactory,
    check_generation,
    database_now,
    locked_job,
    require_active_lease,
    validated_payload,
    validated_text,
)
from insurance_harness.jobs.tables import WikiJob

# 稳定 64 位 claim 序列化锁键（pg_advisory_xact_lock；SQLite 单写者无需）。
_CLAIM_LOCK_KEY = int.from_bytes(b"ikb035cl", "big", signed=True)


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
        job_id: str | None = None,
        domain_writes: Sequence[DomainWriteSpec] = (),
    ) -> EnqueueResult:
        """插入新任务或返回 typed dedup；键由消费方按批次/裁决铸造。

        dedup 命中终态行时 `terminal=True`：新一次授权处理必须铸新键
        （P1.5，review M17）。
        """
        validated_text(space_id, "space_id", max_length=MAX_SPACE_ID_LENGTH)
        validated_text(job_type, "job_type", max_length=MAX_JOB_TYPE_LENGTH)
        validated_text(idempotency_key, "idempotency_key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
        safe_payload = validated_payload(payload)
        if job_id is not None:
            from uuid import UUID

            try:
                if str(UUID(job_id)) != job_id:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise InvalidJobInputError(
                    "explicit enqueue job id must be a canonical UUID"
                ) from None
        if domain_writes and job_id is None:
            raise InvalidJobInputError("atomic domain admission requires an explicit job id")
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
                    if job_id is not None:
                        row.id = job_id
                    session.add(row)
                    session.flush()
                    # Admission data and the claimable job become visible together.
                    # Reuse the existing declarative, protected-table write boundary.
                    execute_domain_writes(session, domain_writes, job_id=row.id)
                return enqueue_result(row, deduplicated=False)
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
                    if job_id is not None and (
                        existing.id != job_id or existing.payload != safe_payload
                    ):
                        raise InvalidJobInputError("atomic enqueue identity conflict") from None
                    return enqueue_result(existing, deduplicated=True)

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
                reclaim_expired(session, scope, now, limit=batch, config=self._config)
                promote_due_retries(session, scope, now, limit=batch)
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
                admitted = admit_spaces(session, scope, now, self._config)
                if isinstance(admitted, NoClaimableJob):
                    return admitted
                eligible = admitted
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
                candidate.lease_expires_at = now + timedelta(seconds=self._config.lease_seconds)
                claimed = job_snapshot(candidate)
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
                check_generation(row, generation)
                state = JobState(row.state)
                if state is not JobState.RUNNING:
                    raise IllegalTransitionError(state, state, row.id)
                if attempt != row.attempt:
                    raise InvalidJobInputError(
                        f"attempt {attempt} does not match current attempt {row.attempt}"
                    )
                now = database_now(session)
                require_active_lease(session, row, now=now)
                return job_snapshot(row)

    def heartbeat(self, *, space_id: str, job_id: str, generation: int) -> JobSnapshot:
        """延长 lease；仅当 generation 等于当前值且状态 leased|running。

        已按数据库时钟过期的 lease 不可复活（review M14）：typed
        `lease_expired` 拒绝，任务只能按 P1.1 第 10 条回收。
        """
        with self._session_factory() as session:
            with session.begin():
                row = locked_job(session, space_id, job_id)
                check_generation(row, generation)
                state = JobState(row.state)
                if state not in (JobState.LEASED, JobState.RUNNING):
                    raise IllegalTransitionError(state, state, row.id)
                now = database_now(session)
                require_active_lease(session, row, now=now)
                row.lease_expires_at = now + timedelta(seconds=self._config.lease_seconds)
                return job_snapshot(row)

    def start(self, *, space_id: str, job_id: str, generation: int) -> JobSnapshot:
        """`leased → running`：同 generation 的 worker 开始执行，attempt +1。

        写权威 = 当前 generation ∧ lease 未过期（P1.3，D-2026-07-27-16）：
        lease 已过期的持有者即使 generation 未变也无权继续，typed
        `lease_expired` 拒绝并零变更；该任务只能经回收后由新 generation 继续。
        """
        with self._session_factory() as session:
            with session.begin():
                row = locked_job(session, space_id, job_id)
                check_generation(row, generation)
                ensure_transition(JobState(row.state), JobState.RUNNING, row.id)
                now = database_now(session)
                require_active_lease(session, row, now=now)
                row.state = JobState.RUNNING.value
                row.attempt += 1
                row.started_at = now
                return job_snapshot(row)

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
                row = locked_job(session, space_id, job_id)
                check_generation(row, generation)
                ensure_transition(JobState(row.state), JobState.SUCCEEDED, row.id)
                now = database_now(session)
                require_active_lease(session, row, now=now)
                execute_domain_writes(session, domain_writes, job_id=job_id)
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
                return job_snapshot(row)

    def report_failure(
        self, *, space_id: str, job_id: str, generation: int, failure: JobFailure
    ) -> JobSnapshot:
        """按封闭错误分类确定性路由失败（P1.4）；同事务释放 lease。"""
        with self._session_factory() as session:
            with session.begin():
                row = locked_job(session, space_id, job_id)
                check_generation(row, generation)
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
                return job_snapshot(row)

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
                row = locked_job(session, space_id, job_id)
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
                return reclaim_expired(
                    session,
                    scope,
                    now,
                    limit=self._config.maintenance_batch_size,
                    config=self._config,
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
                return reclaim_expired(
                    session,
                    None,
                    now,
                    limit=self._config.maintenance_batch_size,
                    config=self._config,
                )

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
                return job_snapshot(row)
