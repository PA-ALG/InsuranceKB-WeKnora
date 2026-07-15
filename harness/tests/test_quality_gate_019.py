"""019 spec Q4：统一 QualityGate 判定 + merge 自动路径接入。

严格 TDD（先写本测试见红，再实现 quality_gate.py）。覆盖 decide 的全部分支：
可自动化动作、各拒绝原因、staleness 四维、四阈值各自边界、自定义阈值、字段回填，
以及 merge 三路径接入（Q4.2/Q4.5）。
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.goldenset import RunFingerprint
from insurance_harness.goldenset.baseline import ApprovalRecord
from insurance_harness.goldenset.profile import (
    AutomationThresholds,
    FieldMetrics,
    QualityProfile,
)
from insurance_harness.knowledge import MergeEngine, MergePolicy
from insurance_harness.knowledge.models import ProposedClaim, ProposedEvidence
from insurance_harness.knowledge.quality_gate import GateDecision, QualityGate
from insurance_harness.knowledge.tables import Claim, ReviewItem
from tests.kbhelpers import seed_bound_scope, seed_product

_AT = datetime(2026, 7, 14, tzinfo=UTC)
_FIELD = "waiting_period"


def _fp(**overrides: str) -> RunFingerprint:
    base = dict(
        git_sha="abc", schema_version="v1.1+x", model_id="m1", prompt_version="p1",
        template_profile="t1", source_profile="s1", golden_release_hash="rh1",
    )
    base.update(overrides)
    return RunFingerprint(**base)


def _metrics(**overrides: object) -> FieldMetrics:
    """默认一份达标指标；用 overrides 单独调某一维做边界测试。"""
    base: dict[str, object] = dict(
        field_id=_FIELD, support=10, value_accuracy=1.0,
        hallucination_rate=0.0, evidence_accuracy=1.0, tri_state_confusion={},
    )
    base.update(overrides)
    return FieldMetrics(**base)  # type: ignore[arg-type]


def _profile(
    metrics: FieldMetrics | None = None, fp: RunFingerprint | None = None
) -> QualityProfile:
    fields = {} if metrics is None else {metrics.field_id: metrics}
    return QualityProfile(profile_version=1, fingerprint=fp or _fp(), fields=fields)


def _approval_for(profile: QualityProfile, *, by: str = "claude") -> ApprovalRecord:
    """批准记录绑定被批准画像的内容哈希（Q4.3）。"""
    return ApprovalRecord(
        baseline_id="b1", version=1, approved_by=by, approved_at=_AT,
        fingerprint=profile.fingerprint, profile_hash=profile.content_hash(),
    )


def _gate(
    metrics: FieldMetrics | None = None,
    *,
    approval: ApprovalRecord | None | str = "auto",
    fp: RunFingerprint | None = None,
    thresholds: AutomationThresholds | None = None,
) -> QualityGate:
    """approval='auto' 生成与画像绑定的批准记录；None=未批准；显式记录=用于错绑测试。"""
    profile = _profile(metrics if metrics is not None else _metrics(), fp)
    appr = _approval_for(profile) if approval == "auto" else approval
    assert not isinstance(appr, str)
    return QualityGate(profile, approval=appr, thresholds=thresholds)


# --------------------------------------------------------- 达标 / 动作维度

@pytest.mark.parametrize("action", ["add", "enrich", "supersede"])
def test_q4_3_each_automatable_action_eligible_when_passing(action: str) -> None:
    fp = _fp()
    decision = _gate(fp=fp).decide(_FIELD, "low", action, fp)
    assert decision.eligible
    assert decision.reason == "达标"
    assert decision.field_id == _FIELD and decision.action == action


@pytest.mark.parametrize("action", ["conflict", "retract", "unknown", ""])
def test_q4_2_non_automatable_actions_denied(action: str) -> None:
    fp = _fp()
    decision = _gate(fp=fp).decide(_FIELD, "low", action, fp)
    assert not decision.eligible and "不可自动化" in decision.reason


# --------------------------------------------------------- 风险维度

@pytest.mark.parametrize("action", ["add", "enrich", "supersede"])
def test_q4_5_high_risk_never_eligible(action: str) -> None:
    fp = _fp()
    decision = _gate(fp=fp).decide(_FIELD, "high", action, fp)
    assert not decision.eligible and "永不自动" in decision.reason


def test_q4_3_medium_risk_denied() -> None:
    fp = _fp()
    decision = _gate(fp=fp).decide(_FIELD, "medium", "add", fp)
    assert not decision.eligible and "非 low" in decision.reason


# --------------------------------------------------------- 画像存在/批准/指纹

def test_q4_5_missing_profile_denied() -> None:
    gate = QualityGate(None, approval=None)
    decision = gate.decide(_FIELD, "low", "add", _fp())
    assert not decision.eligible and "缺字段画像" in decision.reason


def test_q4_5_field_absent_from_profile_denied() -> None:
    fp = _fp()
    gate = _gate(fp=fp)
    decision = gate.decide("other_field", "low", "add", fp)
    assert not decision.eligible and "无该字段画像" in decision.reason


def test_q4_3_unapproved_profile_denied() -> None:
    fp = _fp()
    decision = _gate(approval=None, fp=fp).decide(_FIELD, "low", "add", fp)
    assert not decision.eligible and "未批准" in decision.reason


def test_q4_3_approval_bound_to_other_profile_denied() -> None:
    """codex #2：批准记录必须与画像内容哈希匹配；拿别的画像（同指纹）的批准冒充 → 拒绝。"""
    fp = _fp()
    other_profile = _profile(_metrics(support=999), fp)  # 同指纹但不同内容 → 不同哈希
    stale_approval = _approval_for(other_profile)
    decision = _gate(approval=stale_approval, fp=fp).decide(_FIELD, "low", "add", fp)
    assert not decision.eligible and "内容不匹配" in decision.reason


def test_q4_3_approval_fingerprint_mismatch_denied() -> None:
    """codex 复审 #1：批准指纹与画像指纹不同（跨 baseline 错绑）→ gate 拒绝。"""
    fp = _fp()
    other_run = _profile(_metrics(), _fp(model_id="other-model"))  # 不同指纹的画像
    approval = _approval_for(other_run)  # 该批准绑到 other_run（指纹=other-model）
    decision = _gate(approval=approval, fp=fp).decide(_FIELD, "low", "add", fp)
    assert not decision.eligible and "指纹不匹配" in decision.reason


def test_q4_3_missing_run_fingerprint_denied() -> None:
    decision = _gate().decide(_FIELD, "low", "add", None)
    assert not decision.eligible and "指纹" in decision.reason


# --------------------------------------------------------- staleness 四维 + 反例

@pytest.mark.parametrize(
    "drift",
    [
        {"golden_release_hash": "rh2"},
        {"schema_version": "v9"},
        {"model_id": "m2"},
        {"prompt_version": "p2"},
        {"template_profile": "t9"},
        {"source_profile": "s9"},
    ],
)
def test_q4_5_stale_on_each_staleness_dim(drift: dict[str, str]) -> None:
    built_fp = _fp()
    gate = _gate(fp=built_fp)
    decision = gate.decide(_FIELD, "low", "add", _fp(**drift))
    assert not decision.eligible and "stale" in decision.reason


def test_q4_5_non_staleness_dim_does_not_stale() -> None:
    """git_sha 是溯源信息、非数据/模型维（design.md:13），差异不判 stale；
    但 template/source profile 变化必须 stale（见上一参数化用例）。"""
    built_fp = _fp()
    gate = _gate(fp=built_fp)
    decision = gate.decide(_FIELD, "low", "add", _fp(git_sha="zzz"))
    assert decision.eligible


# --------------------------------------------------------- 四阈值各自边界（Q4.4）

def test_q4_4_support_below_min_denied() -> None:
    fp = _fp()
    decision = _gate(_metrics(support=9), fp=fp).decide(_FIELD, "low", "add", fp)
    assert not decision.eligible and "support=9" in decision.reason


def test_q4_4_support_at_min_eligible() -> None:
    fp = _fp()
    assert _gate(_metrics(support=10), fp=fp).decide(_FIELD, "low", "add", fp).eligible


def test_q4_4_value_accuracy_below_min_denied() -> None:
    fp = _fp()
    decision = _gate(_metrics(value_accuracy=0.97), fp=fp).decide(_FIELD, "low", "add", fp)
    assert not decision.eligible and "value_accuracy" in decision.reason


def test_q4_4_hallucination_above_max_denied() -> None:
    fp = _fp()
    decision = _gate(_metrics(hallucination_rate=0.02), fp=fp).decide(_FIELD, "low", "add", fp)
    assert not decision.eligible and "hallucination_rate" in decision.reason


def test_q4_4_evidence_below_one_denied() -> None:
    fp = _fp()
    decision = _gate(_metrics(evidence_accuracy=0.99), fp=fp).decide(_FIELD, "low", "add", fp)
    assert not decision.eligible and "evidence_accuracy" in decision.reason


def test_q4_3_multiple_failures_all_listed() -> None:
    fp = _fp()
    metrics = _metrics(support=3, value_accuracy=0.5, hallucination_rate=0.2)
    decision = _gate(metrics, fp=fp).decide(_FIELD, "low", "add", fp)
    assert not decision.eligible
    assert "support=3" in decision.reason
    assert "value_accuracy" in decision.reason
    assert "hallucination_rate" in decision.reason


def test_q3_3_custom_thresholds_respected() -> None:
    fp = _fp()
    lenient = AutomationThresholds(support_min=3)
    decision = _gate(_metrics(support=3), fp=fp, thresholds=lenient).decide(
        _FIELD, "low", "add", fp
    )
    assert decision.eligible


def test_gate_decision_shape() -> None:
    fp = _fp()
    decision = _gate(fp=fp).decide(_FIELD, "low", "supersede", fp)
    assert isinstance(decision, GateDecision)
    assert decision.field_id == _FIELD and decision.action == "supersede"


# --------------------------------------------------------- Q4.1 默认

def test_q4_1_supersede_low_risk_default_off() -> None:
    assert MergePolicy().auto_apply_supersede_low_risk is False


# --------------------------------------------------------- merge 接入（Q4.2/Q4.5）

def _passing_profile(field_id: str, fp: RunFingerprint) -> QualityProfile:
    """直接构造一份达标画像（gate 逻辑测试关注判定，不关注指标派生）。"""
    metrics = FieldMetrics(
        field_id=field_id, support=12, value_accuracy=1.0,
        hallucination_rate=0.0, evidence_accuracy=1.0, tri_state_confusion={},
    )
    return QualityProfile(profile_version=1, fingerprint=fp, fields={field_id: metrics})


def _scope(session: Session) -> KnowledgeScope:
    return seed_bound_scope(
        session, tenant_id="t-gate", raw_kb_id="raw-gate", wiki_kb_id="wiki-gate"
    )


def _add_prop(scope: KnowledgeScope, version_id: str, predicate: str) -> ProposedClaim:
    return ProposedClaim(
        space_id=scope.space_id, product_version_id=version_id, predicate=predicate,
        field_name=predicate, value_state="present", value="X", confidence=0.9,
        evidence=[ProposedEvidence(
            knowledge_id="k1", doc_title="k1", quote="X 的证据", page=1,
            doc_role="official_desc", authority_level=2,
        )],
    )


def test_q4_2_gate_gates_auto_apply_per_field(kb_session: Session) -> None:
    """有达标画像的字段自动发布；无画像的字段即便 policy 允许也进审核（候选不丢弃）。"""
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    fp = _fp()
    profile = _passing_profile("waiting_period", fp)
    gate = QualityGate(profile, approval=_approval_for(profile))
    engine = MergeEngine(
        kb_session, scope=scope,
        policy=MergePolicy(auto_apply_add=True),
        quality_gate=gate, run_fingerprint=fp,
    )
    change_set, _ = engine.open_change_set(source_kind="document")
    engine.apply_batch(change_set, [
        _add_prop(scope, version.id, "waiting_period"),
        _add_prop(scope, version.id, "grace_period"),
    ])

    claims = {
        c.predicate: c
        for c in kb_session.execute(
            select(Claim).where(Claim.space_id == scope.space_id)
        ).scalars()
    }
    assert claims["waiting_period"].status == "published"
    assert claims["grace_period"].status == "candidate"
    reviews = list(
        kb_session.execute(
            select(ReviewItem).where(ReviewItem.space_id == scope.space_id)
        ).scalars()
    )
    assert any(claims["grace_period"].id in str(r.subject) for r in reviews)


def test_q4_2_no_gate_fails_closed(kb_session: Session) -> None:
    """codex #1 / design.md:17：无 gate（缺已批准画像）时**fail-closed**——policy 布尔位
    不能绕过 gate 自动发布；候选进 candidate + ReviewItem，不丢弃、不静默发布。"""
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    engine = MergeEngine(
        kb_session, scope=scope, policy=MergePolicy(auto_apply_add=True),
    )  # 无 quality_gate
    change_set, _ = engine.open_change_set(source_kind="document")
    engine.apply_batch(change_set, [_add_prop(scope, version.id, "waiting_period")])
    claim = kb_session.execute(
        select(Claim).where(Claim.space_id == scope.space_id)
    ).scalar_one()
    assert claim.status == "candidate"  # 无 gate → 不自动发布
    reviews = list(
        kb_session.execute(
            select(ReviewItem).where(ReviewItem.space_id == scope.space_id)
        ).scalars()
    )
    assert any(claim.id in str(r.subject) for r in reviews)  # 候选进审核，未丢弃
