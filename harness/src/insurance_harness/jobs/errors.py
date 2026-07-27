"""OpenSpec 035 P1 typed 错误（存储层拒绝 + worker 失败分类载体）。

存储层拒绝（P1.1/P1.3/P1.8）：非法转换、旧 generation、跨 Space 一律
typed 异常且零行变更；worker 失败分类（P1.4）经 `TypedJobError` 子类或
`classify_failure` 归入封闭枚举，未分类异常不得静默。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from insurance_harness.jobs.models import JobState


class JobStoreError(Exception):
    """存储层 typed 拒绝基类；抛出即保证目标行零字段变更。"""

    code = "job_store_error"


class IllegalTransitionError(JobStoreError):
    """P1.1：未列入合法转换表的状态转换请求。"""

    code = "illegal_transition"

    def __init__(self, source: JobState, target: JobState, job_id: str | None = None) -> None:
        self.source = source
        self.target = target
        self.job_id = job_id
        super().__init__(f"illegal transition {source.value} -> {target.value}")


class StaleGenerationError(JobStoreError):
    """P1.3：携带非当前 lease generation 的写入（fencing 拒绝）。"""

    code = "stale_generation"

    def __init__(self, *, expected: int, actual: int, job_id: str | None = None) -> None:
        self.expected = expected
        self.actual = actual
        self.job_id = job_id
        super().__init__(f"stale generation {actual}, current is {expected}")


class SpaceScopeError(JobStoreError):
    """P1.8：声明 scope 与目标行不一致（含不存在的行）fail closed。"""

    code = "space_scope_violation"

    def __init__(self, message: str = "job is not visible in this space scope") -> None:
        super().__init__(message)


class InvalidJobInputError(JobStoreError, ValueError):
    """输入合同违规（超长/NUL/不可序列化 payload 等）在存储层前置拒绝。

    兼容旧 ValueError 合同；两种方言（PostgreSQL/SQLite）行为一致，不再
    向调用方泄漏原始 DataError（review I6/M16）。
    """

    code = "invalid_input"


class LeaseExpiredError(JobStoreError):
    """P1.3：已过期 lease 不可经 heartbeat 复活，只能按第 10 条回收。"""

    code = "lease_expired"

    def __init__(self, *, job_id: str | None = None) -> None:
        self.job_id = job_id
        super().__init__("lease has expired; the job can only be reclaimed")


class DuplicateEventError(JobStoreError):
    """P1.6：同一 Space 内重复 event_id 的 outbox 追加 typed 拒绝。"""

    code = "duplicate_event_id"


class DomainWriteViolationError(JobStoreError):
    """P1.5 领域写通道合同（D-2026-07-27-16）：领域写越出其通道。

    两类越界：① 回调结束/提交/另起了完成事务（事务或保存点身份已变）——
    否则领域行落库而任务仍 `running`、outbox 为空，重放会产生第二份领域
    结果；② 回调触碰 P1 自有表（`wiki_` 前缀），可复活其他 Space 的终态
    行、伪造 `lease_generation` 或插入越域 outbox 行。仅隐藏
    `commit/rollback/close` 属性不构成执法，必须在语句面与提交点校验。
    """

    code = "domain_write_violation"

    def __init__(self, reason: str, *, job_id: str | None = None) -> None:
        self.job_id = job_id
        self.reason = reason
        super().__init__(f"domain write violated its channel: {reason}")


class TypedJobError(Exception):
    """worker 执行失败的显式分类载体基类（P1.4）。"""


class RetryableJobError(TypedJobError):
    """可重试失败 → retry_wait（达 max_attempts 转 dead_letter）。"""


class NonRetryableJobError(TypedJobError):
    """不可重试失败 → dead_letter。"""


class CapacityBlockedJobError(TypedJobError):
    """容量类合同性阻断（如 candidate_capacity_exceeded）→ blocked。"""


class HumanRequiredJobError(TypedJobError):
    """需要人工裁决 → awaiting_human（同事务释放 lease，P1.7）。"""
