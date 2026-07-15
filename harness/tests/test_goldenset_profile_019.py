"""019 spec Q3/Q4.6：QualityProfile 指标、指纹 staleness、阈值判定与回归检查。

严格 TDD（先红后绿）；覆盖：Q3.1 每字段指标（含混淆矩阵/幻觉/证据精度）、
Q3.2 四维 staleness（且非四维不触发）、Q3.3 逐条失败列举、Q4.6 回归检查各分支。
"""

from datetime import UTC, datetime
from pathlib import Path

from insurance_harness.goldenset import (
    AutomationThresholds,
    Evidence,
    GoldenRecord,
    QualityProfile,
    RunFingerprint,
    build_profile,
    compare_baselines,
)
from insurance_harness.goldenset.profile import (
    FieldMetrics,
    GlobalMetrics,
    RegressionThresholds,
)

_AT = datetime(2026, 7, 14, tzinfo=UTC)
_ART = "a" * 64


def _fp(**overrides: str) -> RunFingerprint:
    base = dict(
        git_sha="abc", schema_version="v1.1+x", model_id="m1", prompt_version="p1",
        template_profile="t1", source_profile="s1", golden_release_hash="rh1",
    )
    base.update(overrides)
    return RunFingerprint(**base)


def _bp(
    golden: list[GoldenRecord], pred: list[GoldenRecord],
    fp: RunFingerprint | None = None, *, dataset_root: Path | None = None,
) -> QualityProfile:
    """build_profile 的测试包装：补一个 artifact_sha256（派生绑定见 baseline 测试）。"""
    return build_profile(golden, pred, fp or _fp(), artifact_sha256=_ART, dataset_root=dataset_root)


def _passing_metrics(field_id: str = "f1", **ov: object) -> FieldMetrics:
    """一份达标指标；verdict 测试直接构造指标（不经 build_profile 的证据回验）。"""
    base: dict[str, object] = dict(
        field_id=field_id, support=12, value_accuracy=1.0,
        hallucination_rate=0.0, evidence_accuracy=1.0, tri_state_confusion={},
    )
    base.update(ov)
    return FieldMetrics(**base)  # type: ignore[arg-type]


def _profile_of(*metrics: FieldMetrics, fp: RunFingerprint | None = None) -> QualityProfile:
    return QualityProfile(
        profile_version="1", artifact_sha256=_ART, baseline_approval_sha256="",
        fingerprint=fp or _fp(), fields={m.field_id: m for m in metrics},
    )


def _rec(
    product: str, field_id: str, value: str | None, tri: str = "present",
    *, with_evidence: bool = True,
) -> GoldenRecord:
    return GoldenRecord(
        product_id=product, product_name=f"产品{product}", doc="d.pdf",
        field_id=field_id, field_name=field_id, value=value, tri_state=tri,  # type: ignore[arg-type]
        evidence=[Evidence(page=1, quote=value)] if (value and with_evidence) else [],
        annotator_model="m", schema_version="v1.1+x", created_at=_AT,
    )


def _golden(field_id: str, n: int = 10) -> list[GoldenRecord]:
    return [_rec(f"P{i}", field_id, f"值{i}") for i in range(n)]


# ------------------------------------------------------------------ Q3.1 指标

def test_q3_1_field_metrics_perfect_replay() -> None:
    golden = _golden("f1", 10)
    profile = _bp(golden, golden)
    m = profile.field("f1")
    assert m is not None
    assert m.support == 10
    assert m.value_accuracy == 1.0
    assert m.hallucination_rate == 0.0
    # 无 dataset_root 无法回验引文 → evidence 不可信记 0.0（codex #4：不给 CI 代理满分）。
    assert m.evidence_accuracy == 0.0
    assert m.tri_state_confusion == {"present>present": 10}
    assert profile.profile_version == "1"


def test_q3_1_evidence_verified_with_dataset_root(tmp_path: object) -> None:
    """有 dataset_root 且引文可回验时 evidence_accuracy 才可能为 1.0（本用例无 PDF → 仍 0.0）。"""
    golden = _golden("f1", 3)
    profile = _bp(golden, golden, dataset_root=Path(str(tmp_path)))
    m = profile.field("f1")
    assert m is not None and m.evidence_accuracy == 0.0  # PDF 不存在 → 回验失败


def test_q4_3_zero_observation_field_is_not_eligible() -> None:
    """codex #4：10 条金标但 0 条 present 预测 → 不得零分母默认满分而获自动资格。"""
    golden = _golden("f1", 10)
    pred: list[GoldenRecord] = []  # 模型什么都没抽到
    m = _bp(golden, pred).field("f1")
    assert m is not None
    assert m.support == 10
    assert m.value_accuracy == 0.0  # 无配对 → 0.0，不是 1.0
    assert m.evidence_accuracy == 0.0
    verdict = _profile_of(m).field_verdict("f1")
    assert not verdict.eligible


def test_q3_1_partial_value_accuracy_is_fraction() -> None:
    golden = _golden("f1", 4)
    pred = [_rec(f"P{i}", "f1", "错值" if i < 1 else f"值{i}") for i in range(4)]
    m = _bp(golden, pred).field("f1")
    assert m is not None
    assert m.value_accuracy == 0.75  # 3/4 值对


def test_q3_1_hallucination_and_missing_evidence_lower_metrics() -> None:
    golden = [_rec("PX", "f1", None, "absent_explicitly"), *_golden("f1", 3)]
    pred = [
        _rec("PX", "f1", "编造值"),  # 金标 absent → 幻觉
        *[_rec(f"P{i}", "f1", f"值{i}", with_evidence=(i != 1)) for i in range(3)],
    ]
    m = _bp(golden, pred).field("f1")
    assert m is not None
    assert m.support == 4
    assert m.hallucination_rate == 0.25  # 4 present 预测里 1 个幻觉
    assert m.evidence_accuracy == 0.0  # 无 dataset_root：证据全不可回验
    assert m.tri_state_confusion["absent_explicitly>present"] == 1


def test_q3_1_missing_pred_counts_as_unknown_in_confusion() -> None:
    golden = _golden("f1", 2)
    pred = [_rec("P0", "f1", "值0")]  # P1 无预测
    m = _bp(golden, pred).field("f1")
    assert m is not None
    assert m.tri_state_confusion["present>unknown"] == 1
    assert m.value_accuracy == 1.0  # 唯一 present 预测值对


def test_q3_1_disputed_golden_excluded_from_support() -> None:
    golden = _golden("f1", 3)
    golden[0].disputed = True
    m = _bp(golden, _golden("f1", 3)).field("f1")
    assert m is not None and m.support == 2  # disputed 金标不计


def test_q3_1_unknown_field_returns_none() -> None:
    profile = _bp(_golden("f1", 2), _golden("f1", 2))
    assert profile.field("nope") is None


# ------------------------------------------------------------- Q3.2 staleness

def test_q3_2_staleness_on_each_of_six_dims() -> None:
    profile = _bp(_golden("f1"), _golden("f1"))
    assert not profile.is_stale(_fp())
    assert profile.is_stale(_fp(golden_release_hash="rh2"))
    assert profile.is_stale(_fp(schema_version="v9"))
    assert profile.is_stale(_fp(model_id="m2"))
    assert profile.is_stale(_fp(prompt_version="p2"))
    assert profile.is_stale(_fp(template_profile="t9"))
    assert profile.is_stale(_fp(source_profile="s9"))


def test_q3_2_staleness_includes_template_and_source() -> None:
    # design.md:13 —— template/source profile 变化必须 stale（codex #5）。
    profile = _bp(_golden("f1"), _golden("f1"))
    assert profile.is_stale(_fp(template_profile="t9"))
    assert profile.is_stale(_fp(source_profile="s9"))


def test_q3_2_git_sha_is_not_a_staleness_dim() -> None:
    # git_sha 属溯源信息、非数据/模型维（design.md:13）→ 不判 stale。
    profile = _bp(_golden("f1"), _golden("f1"))
    assert not profile.is_stale(_fp(git_sha="zzz"))


# --------------------------------------------------------- Q3.3 field verdict

def test_q3_3_low_support_field_lists_failure() -> None:
    profile = _bp(_golden("f1", 3), _golden("f1", 3))
    verdict = profile.field_verdict("f1")
    assert not verdict.eligible
    assert any("support=3<10" in f for f in verdict.failures)


def test_q3_3_value_accuracy_failure_listed() -> None:
    golden = _golden("f1", 12)
    pred = [_rec(f"P{i}", "f1", "错值" if i < 2 else f"值{i}") for i in range(12)]
    verdict = _bp(golden, pred).field_verdict("f1")
    assert not verdict.eligible
    assert any("value_accuracy" in f for f in verdict.failures)


def test_q3_3_hallucination_and_evidence_failures_listed() -> None:
    golden = [_rec(f"P{i}", "f1", None, "absent_explicitly") for i in range(12)]
    pred = [_rec(f"P{i}", "f1", "编造", with_evidence=False) for i in range(12)]
    verdict = _bp(golden, pred).field_verdict("f1")
    assert not verdict.eligible
    assert any("hallucination_rate" in f for f in verdict.failures)
    assert any("evidence_accuracy" in f for f in verdict.failures)


def test_q3_3_passing_field_is_eligible() -> None:
    profile = _profile_of(_passing_metrics())
    verdict = profile.field_verdict("f1", AutomationThresholds())
    assert verdict.eligible and verdict.failures == ()


def test_q3_3_custom_thresholds_relax_support() -> None:
    profile = _profile_of(_passing_metrics(support=3))
    verdict = profile.field_verdict("f1", AutomationThresholds(support_min=2))
    assert verdict.eligible


def test_q3_missing_field_verdict_not_eligible() -> None:
    profile = QualityProfile(
        profile_version="1", artifact_sha256=_ART, baseline_approval_sha256="",
        fingerprint=_fp(), fields={},
    )
    verdict = profile.field_verdict("nope")
    assert not verdict.eligible and "无该字段画像" in verdict.failures[0]


# ---------------------------------------------------------- Q4.6 regression

def test_q4_6_regression_flags_accuracy_drop() -> None:
    approved = _bp(_golden("f1", 12), _golden("f1", 12))
    golden = _golden("f1", 12)
    pred = [_rec(f"P{i}", "f1", "错值" if i < 6 else f"值{i}") for i in range(12)]
    candidate = _bp(golden, pred, _fp(model_id="m2"))
    result = compare_baselines(approved, candidate)
    assert not result.eligible
    metrics = {f.metric for f in result.failures}
    assert "f1.value_accuracy" in metrics and "global.micro_f1" in metrics
    # 结构化：每条给出 baseline/candidate/allowed
    f = next(f for f in result.failures if f.metric == "f1.value_accuracy")
    assert f.baseline == 1.0 and f.candidate == 0.5 and f.allowed == 1.0


def test_q4_6_regression_flags_evidence_drop() -> None:
    """复审 #4：已批准 evidence 高、候选 evidence 掉 → 必须判回归（此前被漏检）。"""
    approved = _profile_of(_passing_metrics(evidence_accuracy=1.0))
    approved = approved.model_copy(update={
        "global_metrics": approved.global_metrics.model_copy(update={
            "evidence_accuracy": 1.0, "micro_f1": 1.0, "macro_f1": 1.0})})
    candidate = _profile_of(_passing_metrics(evidence_accuracy=0.0), fp=_fp(model_id="m2"))
    result = compare_baselines(approved, candidate)
    assert not result.eligible
    assert any(f.metric == "f1.evidence_accuracy" for f in result.failures)


def test_q4_6_regression_flags_unresolved_increase() -> None:
    approved = _profile_of(_passing_metrics())
    candidate = _profile_of(_passing_metrics(), fp=_fp(model_id="m2")).model_copy(update={
        "global_metrics": GlobalMetrics(unresolved_count=3)})
    result = compare_baselines(approved, candidate)
    assert any(f.metric == "global.unresolved_count" for f in result.failures)


def test_q4_6_regression_flags_missing_candidate_field() -> None:
    approved = _bp(_golden("f1", 12), _golden("f1", 12))
    candidate = _bp(_golden("f2", 12), _golden("f2", 12), _fp(model_id="m2"))
    result = compare_baselines(approved, candidate)
    assert not result.eligible
    assert any(f.metric == "f1.missing" for f in result.failures)


def test_q4_6_no_regression_is_eligible() -> None:
    approved = _bp(_golden("f1", 12), _golden("f1", 12))
    candidate = _bp(_golden("f1", 12), _golden("f1", 12), _fp(model_id="m2"))
    result = compare_baselines(approved, candidate)
    assert result.eligible and result.failures == ()


def test_q4_3_content_hash_is_stable_and_sensitive() -> None:
    """codex #2：内容哈希稳定且对任一指标敏感——批准记录据此绑定画像。"""
    a = _profile_of(_passing_metrics())
    assert a.content_hash() == _profile_of(_passing_metrics()).content_hash()
    assert a.content_hash() != _profile_of(_passing_metrics(support=11)).content_hash()
    assert a.content_hash() != _profile_of(_passing_metrics(), fp=_fp(model_id="m2")).content_hash()


def test_q4_6_tolerance_absorbs_small_drop() -> None:
    approved = _bp(_golden("f1", 12), _golden("f1", 12))
    golden = _golden("f1", 12)
    pred = [_rec(f"P{i}", "f1", "错值" if i < 1 else f"值{i}") for i in range(12)]
    candidate = _bp(golden, pred, _fp(model_id="m2"))  # 1/12 掉点
    lenient = RegressionThresholds(
        max_field_value_accuracy_drop=0.2, max_micro_f1_drop=0.2, max_macro_f1_drop=0.2,
    )
    assert compare_baselines(approved, candidate, lenient).eligible
