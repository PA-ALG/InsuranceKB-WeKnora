"""CAP0 CapacityProfile 合同模型（OpenSpec 036，033 §5.1/§16 CAP0 行）：八项输入
全部必填、无默认数值；内容寻址复用 C0；float 拒绝；除 C0 安全整数域无数量级上限。"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Final, Literal, Self

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from insurance_harness.canonical import canonical_hash

CAPACITY_PROFILE_OBJECT_TYPE: Final[str] = "capacity-profile"
CANONICAL_MAX_SAFE_INT: Final[int] = 2**53 - 1
_ID_PATTERN: Final[str] = r"^[a-z0-9][a-z0-9._-]{0,63}$"


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError('禁用 binary float（C0.3）：请改写为十进制字符串（如 "3.5"）或整数')
    return value


_NoFloat = BeforeValidator(_reject_float)
Count = Annotated[int, _NoFloat, Field(ge=0, le=CANONICAL_MAX_SAFE_INT)]
PositiveCount = Annotated[int, _NoFloat, Field(ge=1, le=CANONICAL_MAX_SAFE_INT)]
Ratio = Annotated[Decimal, _NoFloat, Field(ge=0)]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class SpaceSourceScaleV1(_FrozenModel):
    space_count: PositiveCount
    active_sources_per_space: Count
    retained_sources_per_space: Count
    peak_source_revisions_per_day_per_space: Count


class DocumentShapeV1(_FrozenModel):
    avg_document_bytes: Count
    p95_document_bytes: Count
    avg_chunks_per_document: Ratio
    p95_chunks_per_document: Ratio

    @model_validator(mode="after")
    def _check_p95_not_below_avg(self) -> Self:
        if (self.p95_document_bytes < self.avg_document_bytes
                or self.p95_chunks_per_document < self.avg_chunks_per_document):
            raise ValueError("p95 值不得小于对应平均值（document_bytes / chunks_per_document）")
        return self


class RevisionAmplificationV1(_FrozenModel):
    claims_per_source_revision: Ratio
    relations_per_source_revision: Ratio
    provenance_anchors_per_source_revision: Ratio


class EvidenceFragmentLimitsV1(_FrozenModel):
    max_logical_bytes_per_fragment: PositiveCount
    max_postgres_inline_bytes_per_fragment: Count

    @model_validator(mode="after")
    def _check_inline_not_above_logical(self) -> Self:
        if self.max_postgres_inline_bytes_per_fragment > self.max_logical_bytes_per_fragment:
            raise ValueError("max_postgres_inline_bytes_per_fragment 不得超过逻辑字节上限")
        return self


class ReleaseRetentionV1(_FrozenModel):
    retained_release_count: Count
    pages_per_release: Count
    blocks_per_page: Count
    release_retention_days: PositiveCount
    artifact_retention_days: PositiveCount


class CandidateReviewV1(_FrozenModel):
    changed_claims_per_candidate: Count
    changed_pages_per_candidate: Count
    changed_bytes_per_candidate: Count
    max_manifest_bytes: PositiveCount
    review_queue_slo_hours: PositiveCount


class ActiveQueryV1(_FrozenModel):
    sustained_qps: Ratio
    burst_qps: Ratio
    p95_response_bytes: Count
    p95_latency_ms: PositiveCount

    @model_validator(mode="after")
    def _check_burst_not_below_sustained(self) -> Self:
        if self.burst_qps < self.sustained_qps:
            raise ValueError("burst_qps 不得小于 sustained_qps")
        return self


class WorkerProviderV1(_FrozenModel):
    worker_concurrency: PositiveCount
    provider_concurrency: PositiveCount
    max_queue_backlog: Count
    recovery_sla_hours: PositiveCount


# 033 §5.1 上线输入清单的八项 typed 必填维度；字段与清单条目的逐项映射见 spec CAP0.2。
class CapacityInputsV1(_FrozenModel):
    space_sources: SpaceSourceScaleV1
    document_shape: DocumentShapeV1
    revision_amplification: RevisionAmplificationV1
    evidence_fragment_limits: EvidenceFragmentLimitsV1
    release_retention: ReleaseRetentionV1
    candidate_review: CandidateReviewV1
    active_query: ActiveQueryV1
    worker_provider: WorkerProviderV1


# 存量回填（2026-07-27 裁决）：只做非负/一致性校验、无数量级上限——数千份 PDF/PPT
# 文档 + 几十万文本片段（口头申报口径）直接表达；新原型以 CapacityWorkloadsV1 显式字段扩展。
class StockBackfillWorkloadV1(_FrozenModel):
    document_count: Count
    total_text_fragments: Count
    total_bytes: Count
    target_completion_window_days: PositiveCount
    review_throughput_docs_per_day: Count

    @model_validator(mode="after")
    def _check_plan_feasible(self) -> Self:
        reviewable = self.review_throughput_docs_per_day * self.target_completion_window_days
        if self.document_count > 0 and reviewable < self.document_count:
            raise ValueError("不可行的存量回填计划：审核吞吐 × 完成窗口 小于 document_count")
        return self


class CapacityWorkloadsV1(_FrozenModel):
    stock_backfill: StockBackfillWorkloadV1 | None = None


# 缺失字段显式继承部署级数值（CAP0.7 per-Space override）。
class CapacitySpaceOverrideV1(_FrozenModel):
    space_sources: SpaceSourceScaleV1 | None = None
    document_shape: DocumentShapeV1 | None = None
    revision_amplification: RevisionAmplificationV1 | None = None
    evidence_fragment_limits: EvidenceFragmentLimitsV1 | None = None
    release_retention: ReleaseRetentionV1 | None = None
    candidate_review: CandidateReviewV1 | None = None
    active_query: ActiveQueryV1 | None = None
    worker_provider: WorkerProviderV1 | None = None
    stock_backfill: StockBackfillWorkloadV1 | None = None

    @model_validator(mode="after")
    def _check_not_empty(self) -> Self:
        if all(getattr(self, name) is None for name in type(self).model_fields):
            raise ValueError("space override 不得为空：至少覆盖一个维度或 stock_backfill")
        return self


class CapacityEvidenceTierV1(_FrozenModel):
    inputs: CapacityInputsV1
    workloads: CapacityWorkloadsV1
    source_kind: Literal["declared", "measured"]
    source_ref: str
    measured_at: AwareDatetime
    applicable_release_profile: str
    space_overrides: dict[str, CapacitySpaceOverrideV1] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_attribution(self) -> Self:
        if not self.source_ref.strip():
            raise ValueError("source_ref 不得为空：必须记录输入来源出处")
        if not self.applicable_release_profile.strip():
            raise ValueError("applicable_release_profile 不得为空")
        for space_id in self.space_overrides:
            if not re.fullmatch(_ID_PATTERN, space_id):
                raise ValueError(f"space_overrides key {space_id!r} 必须匹配 {_ID_PATTERN}")
        return self


# 部署级版本化 CapacityProfile；内容修改必须铸造新版本与新 hash（CAP0.1/CAP0.7）。
class CapacityProfileV1(_FrozenModel):
    contract: Literal["cap0-capacity-profile/v1"]
    profile_version: PositiveCount
    deployment_id: str = Field(pattern=_ID_PATTERN)
    launch: CapacityEvidenceTierV1 | None = None
    contracted_forecast: CapacityEvidenceTierV1 | None = None
    stress_breakpoint: CapacityEvidenceTierV1 | None = None

    @model_validator(mode="after")
    def _check_tier_rules(self) -> Self:
        if self.launch is not None and self.launch.workloads.stock_backfill is None:
            raise ValueError("launch 档必须申报 stock_backfill：零回填以显式 0 申报（缺失≠零）")
        if self.stress_breakpoint is not None and self.stress_breakpoint.source_kind != "measured":
            raise ValueError("stress_breakpoint 只受理 measured：申报式即无工作负载假设")
        return self


# CapacityProfile 内容寻址：C0 domain-separated SHA-256（64 位小写 hex）。
def capacity_profile_hash(profile: CapacityProfileV1) -> str:
    return canonical_hash(CAPACITY_PROFILE_OBJECT_TYPE, profile.model_dump(mode="python"))
