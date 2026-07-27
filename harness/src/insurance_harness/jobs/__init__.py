"""OpenSpec 035 P1 Job + Outbox 存储层公共入口。

单一领域不变量：at-least-once 任务执行在 PostgreSQL 权威下收敛为恰好
一次领域提交。全部任务状态与 outbox 写只经本包的存储层入口。
"""

from insurance_harness.jobs.errors import (
    CapacityBlockedJobError,
    DomainWriteViolationError,
    DuplicateEventError,
    HumanRequiredJobError,
    IllegalTransitionError,
    InvalidJobInputError,
    JobStoreError,
    LeaseExpiredError,
    NonRetryableJobError,
    RetryableJobError,
    SpaceScopeError,
    StaleGenerationError,
    TypedJobError,
)
from insurance_harness.jobs.metrics import (
    GlobalJobMetrics,
    SpaceJobMetrics,
    global_job_metrics,
    space_job_metrics,
)
from insurance_harness.jobs.models import (
    LEGAL_TRANSITIONS,
    STORAGE_ONLY_TRANSITIONS,
    TERMINAL_STATES,
    ClaimedJob,
    ClaimOutcome,
    DecisionOutcome,
    DispatchReport,
    DomainWriteSpec,
    EnqueueResult,
    ErrorClass,
    JobFailure,
    JobRuntimeConfig,
    JobSnapshot,
    JobState,
    JobTypePolicy,
    NoClaimableJob,
    OutboxEventDraft,
    OutboxEventView,
    ReclaimReport,
    classify_failure,
    ensure_transition,
    route_failure,
)

# `append_job_event` 刻意不在公共出口（P1.6 事件追加边界合同，
# D-2026-07-27-16）：事件只能在完成事务内追加，即只经 `report_success`。
# 调用方自有事务内的追加会让"领域写 + 事件已提交而任务未完成"成为可能，
# 重放时新铸随机 event_id，消费端幂等去重无法折叠。
from insurance_harness.jobs.outbox import OutboxDispatcher

# `DomainWriteHandle` 已删除（P1.5 领域写通道合同，D-2026-07-27-16）：完成
# 事务收数据不收代码，调用方不再持有任何数据库句柄。领域写用 `DomainWriteSpec`。
from insurance_harness.jobs.store import OWNED_TABLES, JobStore, database_now

__all__ = [
    "LEGAL_TRANSITIONS",
    "STORAGE_ONLY_TRANSITIONS",
    "TERMINAL_STATES",
    "CapacityBlockedJobError",
    "ClaimOutcome",
    "ClaimedJob",
    "DecisionOutcome",
    "DispatchReport",
    "DomainWriteSpec",
    "OWNED_TABLES",
    "DomainWriteViolationError",
    "DuplicateEventError",
    "EnqueueResult",
    "ErrorClass",
    "GlobalJobMetrics",
    "HumanRequiredJobError",
    "IllegalTransitionError",
    "InvalidJobInputError",
    "JobFailure",
    "JobRuntimeConfig",
    "JobSnapshot",
    "JobState",
    "JobStore",
    "JobStoreError",
    "JobTypePolicy",
    "LeaseExpiredError",
    "NoClaimableJob",
    "NonRetryableJobError",
    "OutboxDispatcher",
    "OutboxEventDraft",
    "OutboxEventView",
    "ReclaimReport",
    "RetryableJobError",
    "SpaceJobMetrics",
    "SpaceScopeError",
    "StaleGenerationError",
    "TypedJobError",
    "classify_failure",
    "database_now",
    "ensure_transition",
    "global_job_metrics",
    "route_failure",
    "space_job_metrics",
]
