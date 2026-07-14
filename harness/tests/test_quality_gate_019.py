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
from insurance_harness.goldenset import (
    Evidence,
    GoldenRecord,
    RunFingerprint,
    build_profile,
)
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


def _gate(
    metrics: FieldMetrics | None = None,
    *,
    approved: bool = True,
    fp: RunFingerprint | None = None,
    thresholds: AutomationThresholds | None = None,
) -> QualityGate:
    return QualityGate(
        _profile(metrics if metrics is not None else _metrics(), fp),
        approved=approved,
        thresholds=thresholds,
    )


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
    gate = QualityGate(None, approved=True)
    decision = gate.decide(_FIELD, "low", "add", _fp())
    assert not decision.eligible and "缺字段画像" in decision.reason


def test_q4_5_field_absent_from_profile_denied() -> None:
    fp = _fp()
    gate = _gate(fp=fp)
    decision = gate.decide("other_field", "low", "add", fp)
    assert not decision.eligible and "无该字段画像" in decision.reason


def test_q4_3_unapproved_profile_denied() -> None:
    fp = _fp()
    decision = _gate(approved=False, fp=fp).decide(_FIELD, "low", "add", fp)
    assert not decision.eligible and "未批准" in decision.reason


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
    ],
)
def test_q4_5_stale_on_each_staleness_dim(drift: dict[str, str]) -> None:
    built_fp = _fp()
    gate = _gate(fp=built_fp)
    decision = gate.decide(_FIELD, "low", "add", _fp(**drift))
    assert not decision.eligible and "stale" in decision.reason


def test_q4_5_non_staleness_dim_does_not_stale() -> None:
    """git_sha/template/source 不在 Q3.2 staleness 维度内，差异不应判 stale。"""
    built_fp = _fp()
    gate = _gate(fp=built_fp)
    decision = gate.decide(_FIELD, "low", "add", _fp(git_sha="zzz", template_profile="t9"))
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

def _passing_profile_from_records(field_id: str, fp: RunFingerprint) -> QualityProfile:
    golden = [
        GoldenRecord(
            product_id=f"P{i}", product_name=f"产品{i}", doc="d.pdf",
            field_id=field_id, field_name=field_id, value=f"值{i}", tri_state="present",
            evidence=[Evidence(page=1, quote=f"值{i}")],
            annotator_model="m", schema_version="v1.1+x", created_at=_AT,
        )
        for i in range(12)
    ]
    return build_profile(golden, golden, fp)


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
    gate = QualityGate(_passing_profile_from_records("waiting_period", fp), approved=True)
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


def test_q4_2_no_gate_falls_back_to_policy_flags(kb_session: Session) -> None:
    """未注入 gate = 在线治理未启用：policy 布尔位单独决定（legacy 兼容）。"""
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
    assert claim.status == "published"  # 无 gate 时 flag 直接放行
