"""容量证据 evaluator（036 CAP0.4/CAP0.5，D-2026-07-26-1）：申报 launch 解锁设计；
实测 launch（+承诺画像的 forecast）解锁 P15；缺输入 INSUFFICIENT；breakpoint 只记录。"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from .models import CapacityProfileV1


class CapacityEvidenceState(StrEnum):
    SUFFICIENT_FOR_DESIGN = "SUFFICIENT_FOR_DESIGN"
    SUFFICIENT_FOR_LAUNCH = "SUFFICIENT_FOR_LAUNCH"
    INSUFFICIENT_CAPACITY_EVIDENCE = "INSUFFICIENT_CAPACITY_EVIDENCE"


EVALUATION_REASON_CODES: Final[frozenset[str]] = frozenset({
    "launch_tier_absent", "launch_release_profile_mismatch", "launch_declared_only",
    "contracted_forecast_missing", "contracted_forecast_release_profile_mismatch",
})


# 求值输入：发布画像必须显式声明是否包含客户增长承诺（无默认）。
class ReleaseProfileV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    declares_customer_growth_commitment: bool


# typed 求值结果；reasons 非空当且仅当未达 SUFFICIENT_FOR_LAUNCH。
class CapacityEvidenceEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: CapacityEvidenceState
    design_unblocked: bool
    launch_unblocked: bool
    reasons: tuple[str, ...]
    stress_breakpoint_recorded: bool


def evaluate_capacity_evidence(
    profile: CapacityProfileV1, release_profile: ReleaseProfileV1
) -> CapacityEvidenceEvaluation:
    reasons: list[str] = []
    launch = profile.launch
    design_ok = launch_measured = False
    if launch is None:
        reasons.append("launch_tier_absent")
    elif launch.applicable_release_profile != release_profile.name:
        reasons.append("launch_release_profile_mismatch")
    else:
        design_ok = True
        launch_measured = launch.source_kind == "measured"
        if not launch_measured:
            reasons.append("launch_declared_only")

    forecast_ok = True
    if release_profile.declares_customer_growth_commitment:
        forecast = profile.contracted_forecast
        if forecast is None:
            forecast_ok = False
            reasons.append("contracted_forecast_missing")
        elif forecast.applicable_release_profile != release_profile.name:
            forecast_ok = False
            reasons.append("contracted_forecast_release_profile_mismatch")

    if not design_ok:
        state = CapacityEvidenceState.INSUFFICIENT_CAPACITY_EVIDENCE
    elif launch_measured and forecast_ok:
        state = CapacityEvidenceState.SUFFICIENT_FOR_LAUNCH
    else:
        state = CapacityEvidenceState.SUFFICIENT_FOR_DESIGN

    stress = profile.stress_breakpoint
    return CapacityEvidenceEvaluation(
        state=state,
        design_unblocked=design_ok,
        launch_unblocked=state is CapacityEvidenceState.SUFFICIENT_FOR_LAUNCH,
        reasons=tuple(reasons),
        stress_breakpoint_recorded=stress is not None
        and stress.applicable_release_profile == release_profile.name,
    )
