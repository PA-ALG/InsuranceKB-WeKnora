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
from insurance_harness.goldenset.baseline import (
    ApprovalRecord,
    BaselineArtifact,
    approve_baseline,
    build_product_artifacts,
)
from insurance_harness.goldenset.profile import (
    AutomationThresholds,
    FieldMetrics,
    GlobalMetrics,
    QualityProfile,
)
from insurance_harness.knowledge import MergeEngine, MergePolicy
from insurance_harness.knowledge.models import ProposedClaim, ProposedEvidence
from insurance_harness.knowledge.quality_gate import GateDecision, QualityGate
from insurance_harness.knowledge.tables import Claim, ReviewItem
from tests.kbhelpers import seed_bound_scope, seed_product

_AT = datetime(2026, 7, 14, tzinfo=UTC)
_FIELD = "waiting_period"
_HEX = "a" * 64


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
        hallucination_rate=0.0, evidence_accuracy=1.0,
        precision=1.0, recall=1.0, f1=1.0, tri_state_confusion={},
    )
    base.update(overrides)
    return FieldMetrics(**base)  # type: ignore[arg-type]


def _artifact(fp: RunFingerprint, *, baseline_id: str = "b1") -> BaselineArtifact:
    shas = {k: _HEX for k in (
        "run_manifest", "pred", "dead_letter", "judge_queue", "judgements",
        "keypoints", "eval_report",
    )}
    product = build_product_artifacts("P1", shas=shas, pred_count=12)
    return BaselineArtifact(baseline_id=baseline_id, fingerprint=fp, products=(product,))


def _candidate(
    metrics: FieldMetrics | None, fp: RunFingerprint, art_hash: str
) -> QualityProfile:
    fields = {} if metrics is None else {metrics.field_id: metrics}
    return QualityProfile(
        profile_version="1", artifact_sha256=art_hash, baseline_approval_sha256="",
        fingerprint=fp, fields=fields,
        global_metrics=GlobalMetrics(
            micro_f1=1.0, macro_f1=1.0, hallucination_rate=0.0, evidence_accuracy=1.0,
        ),
    )


def _approved(
    metrics: FieldMetrics | None, fp: RunFingerprint, *, baseline_id: str = "b1"
) -> tuple[QualityProfile, ApprovalRecord]:
    """一条完整链：valid artifact → 候选画像 → approve → 已批准画像。"""
    artifact = _artifact(fp, baseline_id=baseline_id)
    candidate = _candidate(metrics, fp, artifact.sha256())
    approval = approve_baseline(artifact, candidate, approved_by="claude", approved_at=_AT)
    return candidate.with_approval(approval), approval


def _gate(
    metrics: FieldMetrics | None = None,
    *,
    approval: ApprovalRecord | None | str = "auto",
    fp: RunFingerprint | None = None,
    thresholds: AutomationThresholds | None = None,
) -> QualityGate:
    """approval='auto' 生成绑定该画像的批准；None=未批准；显式记录=用于错绑测试。"""
    fp = fp or _fp()
    approved_profile, real_approval = _approved(
        metrics if metrics is not None else _metrics(), fp
    )
    appr = real_approval if approval == "auto" else approval
    assert not isinstance(appr, str)
    return QualityGate(approved_profile, approval=appr, thresholds=thresholds)


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


def test_q4_3_unapproved_candidate_profile_denied() -> None:
    """候选画像（baseline_approval_sha256=""）配真实批准 → 未回链，拒绝。"""
    fp = _fp()
    artifact = _artifact(fp)
    candidate = _candidate(_metrics(), fp, artifact.sha256())  # 未 with_approval
    approval = approve_baseline(artifact, candidate, approved_by="claude", approved_at=_AT)
    decision = QualityGate(candidate, approval=approval).decide(_FIELD, "low", "add", fp)
    assert not decision.eligible and "未绑定该批准" in decision.reason


def test_q4_3_cross_approval_binding_denied() -> None:
    """复审 #1：画像回链的是批准 A，却拿批准 B 去过闸 → 拒绝（内容哈希绑定，不可错绑）。"""
    fp = _fp()
    approved_a, _approval_a = _approved(_metrics(), fp, baseline_id="A")
    _approved_b, approval_b = _approved(_metrics(), fp, baseline_id="B")
    decision = QualityGate(approved_a, approval=approval_b).decide(_FIELD, "low", "add", fp)
    assert not decision.eligible and ("未绑定该批准" in decision.reason
                                      or "artifact 不一致" in decision.reason)


def test_q4_2_old_approval_cannot_authorize_new_model_profile() -> None:
    """四轮 #2：旧 model 的 approval 不能授权一份新 model 指纹的"完美"画像。

    构造 model-1 的 artifact/approval，再伪造一份指纹=model-2、复制其公开哈希的达标画像，
    当前 run 也设为 model-2（绕过 stale）——gate 必须因指纹/内容不符拒绝。
    """
    fp1 = _fp(model_id="m1")
    _approved_1, approval_1 = _approved(_metrics(), fp1)
    fp2 = _fp(model_id="m2")
    forged = QualityProfile(
        profile_version="1", artifact_sha256=approval_1.artifact_sha256,
        baseline_approval_sha256=approval_1.sha256(), fingerprint=fp2,
        fields={_FIELD: _metrics()},
        global_metrics=GlobalMetrics(micro_f1=1.0, macro_f1=1.0,
                                     hallucination_rate=0.0, evidence_accuracy=1.0),
    )
    decision = QualityGate(forged, approval=approval_1).decide(_FIELD, "low", "add", fp2)
    assert not decision.eligible


def test_q4_3_forged_profile_content_denied_at_gate() -> None:
    """四轮 #1（gate 层）：拿真实 approval，却把画像指标偷换（仍达阈值、复制回链哈希）。

    value_accuracy=0.99 仍过 0.98 阈值 → field_verdict 仍 eligible；唯一能拒它的是
    "批准提交的是画像内容哈希" 这条绑定——证明拒绝来自内容绑定而非阈值。
    """
    fp = _fp()
    approved, approval = _approved(_metrics(value_accuracy=1.0), fp)
    forged = approved.model_copy(update={"fields": {_FIELD: _metrics(value_accuracy=0.99)}})
    decision = QualityGate(forged, approval=approval).decide(_FIELD, "low", "add", fp)
    assert not decision.eligible and "内容" in decision.reason


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

def _passing_gate(field_id: str, fp: RunFingerprint) -> QualityGate:
    """一条完整达标已批准链上的 gate（供 merge 接入测试）。"""
    metrics = FieldMetrics(
        field_id=field_id, support=12, value_accuracy=1.0, hallucination_rate=0.0,
        evidence_accuracy=1.0, precision=1.0, recall=1.0, f1=1.0, tri_state_confusion={},
    )
    approved_profile, approval = _approved(metrics, fp)
    return QualityGate(approved_profile, approval=approval)


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
    gate = _passing_gate("waiting_period", fp)
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
