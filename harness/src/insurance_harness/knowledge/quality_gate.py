"""统一在线质量闸门（019 spec Q4）。

纯逻辑：给定字段画像（QualityProfile）+ 批准状态 + 阈值，判定一个 (field, risk, action) 是否
有资格自动发布。add/enrich/supersede 三条自动路径都调用同一个 gate，不能各自绕过（Q4.2）。

- Q4.3 自动资格：risk=low、action 可自动化、画像存在且匹配当前 run 指纹且已批准、逐指标达阈值；
- Q4.4 默认阈值 support≥10 / value_accuracy≥0.98 / hallucination≤0.01 / evidence=1.0；
- Q4.5 risk=high 永不自动；画像缺失/stale/不达标 → 不资格（调用方据此走 ReviewItem，候选不丢弃）。
"""

from pydantic import BaseModel, ConfigDict

from insurance_harness.goldenset.baseline import ApprovalRecord, RunFingerprint
from insurance_harness.goldenset.profile import (
    AutomationThresholds,
    QualityProfile,
)

_AUTOMATABLE_ACTIONS = frozenset({"add", "enrich", "supersede"})


class GateDecision(BaseModel):
    """一次闸门判定；不资格时 reason 可读，字段/动作便于审计。"""

    model_config = ConfigDict(frozen=True)

    eligible: bool
    reason: str
    field_id: str
    action: str


class QualityGate:
    """自动发布资格的唯一权威（Q4.2）；MergePolicy 布尔位只表达运营是否允许自动化。"""

    def __init__(
        self,
        profile: QualityProfile | None,
        *,
        approval: ApprovalRecord | None,
        thresholds: AutomationThresholds | None = None,
    ) -> None:
        self.profile = profile
        # 批准以 ApprovalRecord 表达，且必须与画像内容哈希绑定——裸 bool 无法验证
        # "批的到底是不是这份画像"，会被任意临时画像冒充（Q4.3）。
        self.approval = approval
        self.thresholds = thresholds or AutomationThresholds()

    def decide(
        self,
        field_id: str,
        risk: str,
        action: str,
        run_fingerprint: RunFingerprint | None,
    ) -> GateDecision:
        def deny(reason: str) -> GateDecision:
            return GateDecision(
                eligible=False, reason=reason, field_id=field_id, action=action
            )

        if action not in _AUTOMATABLE_ACTIONS:
            return deny(f"动作 {action} 不可自动化")
        if risk == "high":
            return deny("高风险字段永不自动发布")
        if risk != "low":
            return deny(f"风险等级 {risk} 非 low，不自动发布")
        if self.profile is None:
            return deny("缺字段画像")
        if self.approval is None:
            return deny("画像未批准")
        # 内容绑定（实施计划 Task4 + 四轮 #1/#2）：画像必须回链到该批准记录、两者指向同一
        # artifact、**批准提交的画像内容哈希/指纹与本画像一致**——否则复制公开 approval 哈希
        # 就能把任意指标/新 model 指纹的画像伪装成"已批准"。
        if self.profile.baseline_approval_sha256 != self.approval.sha256():
            return deny("画像未绑定该批准记录（baseline_approval_sha256 不符）")
        if self.profile.artifact_sha256 != self.approval.artifact_sha256:
            return deny("画像与批准记录指向的 artifact 不一致")
        if self.approval.profile_content_sha256 != self.profile.content_hash():
            return deny("画像内容与批准记录提交的内容不符（画像被替换）")
        if self.approval.fingerprint != self.profile.fingerprint:
            return deny("画像指纹与批准记录指纹不一致（旧批准不能授权新 model 画像）")
        if run_fingerprint is None:
            return deny("缺当前 run 指纹，无法核对画像")
        if self.profile.is_stale(run_fingerprint):
            return deny("画像与当前 run 指纹不匹配（stale）")
        verdict = self.profile.field_verdict(field_id, self.thresholds)
        if not verdict.eligible:
            return deny("指标未达阈值：" + "；".join(verdict.failures))
        return GateDecision(
            eligible=True, reason="达标", field_id=field_id, action=action
        )
