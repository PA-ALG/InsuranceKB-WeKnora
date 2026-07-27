"""OpenSpec 035 P1 状态机纯函数核、frozen DTO 与运行时配置。

P1.1 封闭 8 状态枚举与唯一合法转换表；P1.4 封闭错误分类与确定性路由；
所有可调参数（lease/heartbeat/max_attempts/backoff/并发上限）只来自
`JobRuntimeConfig`，转换代码零硬编码。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.jobs.errors import (
    CapacityBlockedJobError,
    HumanRequiredJobError,
    IllegalTransitionError,
    NonRetryableJobError,
    RetryableJobError,
)


class JobState(StrEnum):
    """P1.1 封闭任务状态枚举；系统不得定义其他状态。"""

    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRY_WAIT = "retry_wait"
    AWAITING_HUMAN = "awaiting_human"
    BLOCKED = "blocked"
    DEAD_LETTER = "dead_letter"


class ErrorClass(StrEnum):
    """P1.4 封闭失败分类枚举。"""

    RETRYABLE = "retryable"
    NON_RETRYABLE = "non_retryable"
    CAPACITY_BLOCKED = "capacity_blocked"
    HUMAN_REQUIRED = "human_required"


TERMINAL_STATES: frozenset[JobState] = frozenset(
    {JobState.SUCCEEDED, JobState.BLOCKED, JobState.DEAD_LETTER}
)

#: P1.1 列出的全部合法转换；此外一律 typed `illegal_transition` 拒绝。
LEGAL_TRANSITIONS: frozenset[tuple[JobState, JobState]] = frozenset(
    {
        (JobState.QUEUED, JobState.LEASED),
        (JobState.LEASED, JobState.RUNNING),
        (JobState.RUNNING, JobState.SUCCEEDED),
        (JobState.RUNNING, JobState.RETRY_WAIT),
        (JobState.RETRY_WAIT, JobState.QUEUED),
        (JobState.RUNNING, JobState.AWAITING_HUMAN),
        (JobState.AWAITING_HUMAN, JobState.QUEUED),
        (JobState.RUNNING, JobState.BLOCKED),
        (JobState.RUNNING, JobState.DEAD_LETTER),
        (JobState.LEASED, JobState.QUEUED),
        (JobState.LEASED, JobState.DEAD_LETTER),
        (JobState.RUNNING, JobState.QUEUED),
    }
)

#: 仅限存储层在数据库时钟校验后执行的转换（P1.1 第 5/10 条）：
#: backoff 到期 requeue 与 lease 过期回收；调用方没有直接入口。
STORAGE_ONLY_TRANSITIONS: frozenset[tuple[JobState, JobState]] = frozenset(
    {
        (JobState.RETRY_WAIT, JobState.QUEUED),
        (JobState.LEASED, JobState.QUEUED),
        (JobState.LEASED, JobState.DEAD_LETTER),
        (JobState.RUNNING, JobState.QUEUED),
    }
)


def ensure_transition(source: JobState, target: JobState, job_id: str | None = None) -> None:
    """转换合法性唯一入口：非法即抛 typed `illegal_transition`（P1.1）。"""
    if (source, target) not in LEGAL_TRANSITIONS:
        raise IllegalTransitionError(source, target, job_id)


def route_failure(error_class: ErrorClass, *, attempt: int, max_attempts: int) -> JobState:
    """P1.4 确定性失败路由；`retryable` 达 max_attempts 转 dead_letter。"""
    if error_class is ErrorClass.RETRYABLE:
        return JobState.DEAD_LETTER if attempt >= max_attempts else JobState.RETRY_WAIT
    if error_class is ErrorClass.NON_RETRYABLE:
        return JobState.DEAD_LETTER
    if error_class is ErrorClass.CAPACITY_BLOCKED:
        return JobState.BLOCKED
    return JobState.AWAITING_HUMAN


@dataclass(frozen=True, slots=True)
class JobFailure:
    """一次执行失败的封闭分类与错误摘要（P1.4）。"""

    error_class: ErrorClass
    summary: str


_ERROR_CLASS_BY_TYPE: tuple[tuple[type[Exception], ErrorClass], ...] = (
    (RetryableJobError, ErrorClass.RETRYABLE),
    (NonRetryableJobError, ErrorClass.NON_RETRYABLE),
    (CapacityBlockedJobError, ErrorClass.CAPACITY_BLOCKED),
    (HumanRequiredJobError, ErrorClass.HUMAN_REQUIRED),
)


def classify_failure(error: BaseException) -> JobFailure:
    """异常 → 封闭分类；未分类异常记 `retryable` 并保留摘要，不静默（P1.4）。"""
    for error_type, error_class in _ERROR_CLASS_BY_TYPE:
        if isinstance(error, error_type):
            return JobFailure(error_class=error_class, summary=f"{type(error).__name__}: {error}")
    return JobFailure(error_class=ErrorClass.RETRYABLE, summary=f"{type(error).__name__}: {error}")


class JobTypePolicy(BaseModel):
    """按 job_type 生效的重试策略；数值只来自配置（P1.4）。"""

    model_config = ConfigDict(frozen=True)

    max_attempts: int = Field(ge=1)
    backoff_seconds: tuple[float, ...] = Field(min_length=1)

    def backoff_delay(self, *, attempt: int) -> float:
        """第 attempt 次失败后的等待秒数；超出序列长度取最后一档。"""
        if attempt < 1:
            raise ValueError("attempt must be >= 1")
        index = min(attempt, len(self.backoff_seconds)) - 1
        delay = self.backoff_seconds[index]
        if delay < 0:
            raise ValueError("backoff delay must be >= 0")
        return delay


class JobRuntimeConfig(BaseModel):
    """P1 运行时配置：lease/heartbeat/重试/并发上限全部来自这里。

    限额由**执行 claim 的实例**按其配置执行：多实例配置不一致会弱化限额
    （宽配置实例可超越紧配置实例的意图，review M18）。部署必须让全部
    worker 实例共享同一配置来源；数据库支撑的集中限额策略是显式后续项，
    不在 P1 交付。
    """

    model_config = ConfigDict(frozen=True)

    lease_seconds: float = Field(ge=0)
    heartbeat_interval_seconds: float = Field(gt=0)
    max_attempts: int = Field(ge=1)
    backoff_seconds: tuple[float, ...] = Field(min_length=1)
    job_type_policies: Mapping[str, JobTypePolicy] = Field(default_factory=dict)
    per_space_concurrency_limit: int = Field(ge=1)
    global_concurrency_limit: int = Field(ge=1)
    #: 单次 claim/reclaim 附带维护（回收/promote）处理的最大行数（review I4）。
    maintenance_batch_size: int = Field(default=128, ge=1)

    def model_post_init(self, _context: Any) -> None:
        if any(delay < 0 for delay in self.backoff_seconds):
            raise ValueError("backoff_seconds entries must be >= 0")

    def policy_for(self, job_type: str) -> JobTypePolicy:
        """job_type 覆盖优先，否则用全局默认（P1.4 可按 job_type 覆盖）。"""
        override = self.job_type_policies.get(job_type)
        if override is not None:
            return override
        return JobTypePolicy(max_attempts=self.max_attempts, backoff_seconds=self.backoff_seconds)


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    """任务行的只读快照；时间戳均为持久化值（P1.9）。"""

    id: str
    space_id: str
    job_type: str
    idempotency_key: str
    payload: dict[str, Any]
    state: JobState
    attempt: int
    lease_generation: int
    worker_id: str | None
    available_at: datetime
    lease_expires_at: datetime | None
    enqueued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_class: ErrorClass | None
    error_summary: str | None


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    """enqueue 结果；重复幂等键返回既有任务并标记 dedup（P1.5）。

    `terminal=True` 表示 dedup 命中的既有行已处于终态：同一逻辑工作的
    新一次授权处理必须铸造**新**幂等键，而不是等待该行（review M17）。
    """

    job: JobSnapshot
    deduplicated: bool
    terminal: bool


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    """claim 成功：该 lease generation 的唯一领取者（P1.2）。"""

    job: JobSnapshot


@dataclass(frozen=True, slots=True)
class NoClaimableJob:
    """claim 的 typed 空结果：空队列或限额饱和（P1.2/P1.8，review I12）。"""

    reason: Literal["empty", "global_concurrency_limit", "per_space_concurrency_limit"]


ClaimOutcome = ClaimedJob | NoClaimableJob


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    """人工 Decision 唤醒结果（P1.7）。

    `duplicate` = 该任务已被 Decision 唤醒过（重复提交）；`not_awaiting` =
    目标行从未处于 awaiting_human（review I11）。二者均零行变更。
    """

    job_id: str
    status: Literal["resumed", "duplicate", "not_awaiting"]


@dataclass(frozen=True, slots=True)
class ReclaimReport:
    """一次过期 lease 回收的结果（P1.1 第 10 条 / P1.10）。"""

    requeued_job_ids: tuple[str, ...]
    dead_lettered_job_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OutboxEventDraft:
    """完成事务内追加的事件草稿；event_id 缺省由存储层铸造（P1.6）。"""

    event_type: str
    payload: dict[str, Any]
    event_id: str | None = None


@dataclass(frozen=True, slots=True)
class OutboxEventView:
    """outbox 行只读视图；id 只表示分配顺序，不承诺跨事务投递顺序。"""

    id: int
    event_id: str
    space_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
    dispatched_at: datetime | None
    dispatch_attempts: int


@dataclass(frozen=True, slots=True)
class DispatchReport:
    """一轮 dispatcher 扫描的 at-least-once 投递结果（P1.6）。

    失败事件不再阻塞本轮后续事件；`parked_event_ids` 是本轮达到投递
    尝试上限、被移出扫描窗口待人工处置的毒性事件（review I10）。
    """

    delivered_event_ids: tuple[str, ...]
    failed_event_ids: tuple[str, ...]
    parked_event_ids: tuple[str, ...]
