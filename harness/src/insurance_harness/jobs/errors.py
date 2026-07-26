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
