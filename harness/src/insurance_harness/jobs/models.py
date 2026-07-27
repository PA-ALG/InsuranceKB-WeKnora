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
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.jobs.errors import (
    CapacityBlockedJobError,
    HumanRequiredJobError,
    IllegalTransitionError,
    NonRetryableJobError,
    RetryableJobError,
)

#: 退避档位上界（约 30 天）：超出即表达"实际别再重投"，那属消费方
#: reconciliation（proposal 非目标），不是本层能履行的退避语义。
MAX_DISPATCH_BACKOFF_SECONDS = 30 * 24 * 3600


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


def ensure_transition(
    source: JobState,
    target: JobState,
    job_id: str | None = None,
    *,
    storage_layer: bool = False,
) -> None:
    """转换合法性唯一入口：非法即抛 typed `illegal_transition`（P1.1）。

    `STORAGE_ONLY_TRANSITIONS` 是**可执行护栏**（P1.1 storage-only 执法合同，
    D-2026-07-27-16）：默认 `storage_layer=False` 时命中 storage-only 对即
    拒绝，只有回收与 backoff 提升路径显式传 `storage_layer=True`。仅把该
    常量记录在文档或测试断言里不构成执法。
    """
    if (source, target) not in LEGAL_TRANSITIONS:
        raise IllegalTransitionError(source, target, job_id)
    if not storage_layer and (source, target) in STORAGE_ONLY_TRANSITIONS:
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

    lease_seconds: float = Field(gt=0)
    heartbeat_interval_seconds: float = Field(gt=0)
    max_attempts: int = Field(ge=1)
    backoff_seconds: tuple[float, ...] = Field(min_length=1)
    job_type_policies: Mapping[str, JobTypePolicy] = Field(default_factory=dict)
    per_space_concurrency_limit: int = Field(ge=1)
    global_concurrency_limit: int = Field(ge=1)
    #: outbox 投递失败的持久退避序列（P1.6 投递可恢复性合同，
    #: D-2026-07-27-16）。取代原先硬编码在 dispatcher 构造函数的
    #: `max_dispatch_attempts` 硬上限——已提交行不得因失败计数被永久移出扫描
    #: 窗口；失败只让位不出局，超出序列长度取最后一档持续重投。
    #: 默认必须真的推迟（第四轮评审 B-finding-2）：模型层默认曾是 `(0.0,)`，
    #: 任何直接构造本模型的装配都拿到零退避（实测约 180 次/秒 CPU 空转），
    #: 与 `config.py` 自己声明的"不得默认为全 0"矛盾。
    dispatch_backoff_seconds: tuple[float, ...] = Field(default=(1.0,), min_length=1)
    #: 单次 claim/reclaim 附带维护（回收/promote）处理的最大行数（review I4）。
    maintenance_batch_size: int = Field(default=128, ge=1)

    def model_post_init(self, _context: Any) -> None:
        if any(delay < 0 for delay in self.backoff_seconds):
            raise ValueError("backoff_seconds entries must be >= 0")
        if self.lease_seconds <= self.heartbeat_interval_seconds:
            # P1.3（D-2026-07-27-16）：lease 必须长于 heartbeat 间隔，否则
            # 续租永远赶不上过期，所有 lease 实际上出生即死。
            raise ValueError("lease_seconds must be greater than heartbeat_interval_seconds")
        # P1.6（第四轮评审 B-finding-1）：只接受实现**能够履行**的档位。
        # 原先只校验 >= 0，于是 inf/nan/1e12 通过配置门，却在写入
        # `next_dispatch_at` 时抛裸 OverflowError——异常在 cursor 推进前逃出
        # dispatch_pending，每轮重撞同一队头事件使整个 Space 的 outbox 卡死，
        # 且 `dispatch_attempts += 1` 随回滚丢失。护栏必须只接受自己能履行的值。
        for delay in self.dispatch_backoff_seconds:
            if not isfinite(delay):
                raise ValueError("dispatch_backoff_seconds entries must be finite")
            if delay < 0:
                raise ValueError("dispatch_backoff_seconds entries must be >= 0")
            if delay > MAX_DISPATCH_BACKOFF_SECONDS:
                raise ValueError(
                    "dispatch_backoff_seconds entries must be <= "
                    f"{MAX_DISPATCH_BACKOFF_SECONDS} seconds"
                )

    def dispatch_backoff_delay(self, *, attempts: int) -> float:
        """第 attempts 次投递失败后的退避秒数；超出序列取最后一档。"""
        if attempts < 1:
            raise ValueError("attempts must be >= 1")
        index = min(attempts, len(self.dispatch_backoff_seconds)) - 1
        return self.dispatch_backoff_seconds[index]

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
class DomainWriteSpec:
    """完成事务内的**声明式**领域写（P1.5 领域写通道合同，D-2026-07-27-16）。

    完成事务收数据、不收代码：调用方交目标表标识 + 列值，由存储层在完成事务
    内执行。这样调用方从不持有 Session/Connection/语句结果，"回调提交外层
    事务使领域行落库而任务仍 running"这一状态在**接口层面**无法构造——不是
    先构造再检测。进程内沙箱化可执行回调是做不到的：句柄逐层可达，隐藏属性
    或扫描 SQL 文本只会把泄漏点推深一层（第二轮评审 N1 的 live 证据）。

    已知边界：不支持"完成事务内先读后写"。需要该形态的领域逻辑把读与计算移到
    完成事务之外，或由后续 PR 以显式合同新开入口，不得恢复可执行回调。
    """

    table: str
    values: Mapping[str, Any]


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
    #: 下一次可投递时刻（持久退避，P1.6）；失败只推迟不出局。
    next_dispatch_at: datetime


@dataclass(frozen=True, slots=True)
class DispatchReport:
    """一轮 dispatcher 扫描的 at-least-once 投递结果（P1.6）。

    失败事件不阻塞本轮后续事件（review I10 的队头阻塞修复保留）；失败行按
    持久退避推迟 `next_dispatch_at` 后**仍留在扫描集合内**，因此本 DTO 不再
    有 `parked_event_ids`——"永不再投"的终态违反 P1.6（D-2026-07-27-16）。
    运维视图见 `OutboxDispatcher.read_backed_off`。
    """

    delivered_event_ids: tuple[str, ...]
    failed_event_ids: tuple[str, ...]
