"""OpenSpec 035 P1 Job + Outbox 存储层公共入口。

单一领域不变量：at-least-once 任务执行在 PostgreSQL 权威下收敛为恰好
一次领域提交。全部任务状态与 outbox 写只经本包的存储层入口。
"""

from insurance_harness.jobs.errors import (
    CapacityBlockedJobError,
    HumanRequiredJobError,
    IllegalTransitionError,
    JobStoreError,
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
from insurance_harness.jobs.outbox import OutboxDispatcher, append_job_event
from insurance_harness.jobs.store import JobStore, database_now

__all__ = [
    "LEGAL_TRANSITIONS",
    "STORAGE_ONLY_TRANSITIONS",
    "TERMINAL_STATES",
    "CapacityBlockedJobError",
    "ClaimOutcome",
    "ClaimedJob",
    "DecisionOutcome",
    "DispatchReport",
    "EnqueueResult",
    "ErrorClass",
    "GlobalJobMetrics",
    "HumanRequiredJobError",
    "IllegalTransitionError",
    "JobFailure",
    "JobRuntimeConfig",
    "JobSnapshot",
    "JobState",
    "JobStore",
    "JobStoreError",
    "JobTypePolicy",
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
    "append_job_event",
    "classify_failure",
    "database_now",
    "ensure_transition",
    "global_job_metrics",
    "route_failure",
    "space_job_metrics",
]
