"""019 spec Q3/Q4.6：QualityProfile 指标、指纹 staleness、阈值判定与回归检查。

严格 TDD（先红后绿）；覆盖：Q3.1 每字段指标（含混淆矩阵/幻觉/证据精度）、
Q3.2 四维 staleness（且非四维不触发）、Q3.3 逐条失败列举、Q4.6 回归检查各分支。
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from insurance_harness.goldenset import (
    AutomationThresholds,
    Evidence,
    GoldenRecord,
    QualityProfile,
    RunFingerprint,
    build_profile,
    compare_baselines,
)
from insurance_harness.goldenset.eval import evaluate
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
    # 无 dataset_root 无法回验引文 → evidence 记 None（未回验，区别于测得 0%；四轮红队 #3）。
    assert m.evidence_accuracy is None
    assert m.tri_state_confusion == {"present>present": 10}
    assert profile.profile_version == "1"


def test_q3_1_evidence_verified_with_dataset_root(tmp_path: object) -> None:
    """有 dataset_root 且引文可回验时 evidence 才可能 1.0（本用例 PDF 不存在 → None 未回验）。"""
    golden = _golden("f1", 3)
    profile = _bp(golden, golden, dataset_root=Path(str(tmp_path)))
    m = profile.field("f1")
    assert m is not None and m.evidence_accuracy is None  # PDF 不存在 → 无法回验（None，非 0%）


def test_q4_3_zero_observation_field_is_not_eligible() -> None:
    """codex #4：10 条金标但 0 条 present 预测 → 不得零分母默认满分而获自动资格。"""
    golden = _golden("f1", 10)
    pred: list[GoldenRecord] = []  # 模型什么都没抽到
    m = _bp(golden, pred).field("f1")
    assert m is not None
    assert m.support == 10
    assert m.value_accuracy == 0.0  # 无配对 → 0.0，不是 1.0
    assert m.evidence_accuracy is None  # 无 present 预测 → 无引文可回验 → 未回验
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
    assert m.evidence_accuracy is None  # 无 dataset_root：证据未回验（None）
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


# ---- 五轮提交前红队自测：非有限指标（NaN/±inf）不得构造 ----
# NaN 让 `value<阈值` / `base-cand>0` 恒 False → 绕过全部数值门槛；inf 让下界比较恒真。
# 让非法状态无法构造：在模型构造期即拒绝非有限值（与 #1/#3 同一"不可构造"哲学）。

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_q4_3_field_metrics_reject_non_finite(bad: float) -> None:
    with pytest.raises(ValidationError):
        FieldMetrics(field_id="f1", support=12, value_accuracy=bad,
                     hallucination_rate=0.0, evidence_accuracy=1.0, tri_state_confusion={})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_q4_3_field_metrics_reject_non_finite_hallucination(bad: float) -> None:
    with pytest.raises(ValidationError):
        FieldMetrics(field_id="f1", support=12, value_accuracy=1.0,
                     hallucination_rate=bad, evidence_accuracy=1.0, tri_state_confusion={})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_q4_3_global_metrics_reject_non_finite(bad: float) -> None:
    with pytest.raises(ValidationError):
        GlobalMetrics(micro_f1=bad, macro_f1=1.0, hallucination_rate=0.0, evidence_accuracy=1.0)


@pytest.mark.parametrize("bad", [2.0, -0.1, 1.5])
def test_q4_3_field_metrics_reject_out_of_range_rate(bad: float) -> None:
    """codex 五轮 #2：比率越界 [0,1] 应无法构造——否则 value_accuracy=2.0 恒过阈值。"""
    with pytest.raises(ValidationError):
        FieldMetrics(field_id="f1", support=12, value_accuracy=bad,
                     hallucination_rate=0.0, evidence_accuracy=1.0, tri_state_confusion={})


def test_q4_3_field_metrics_reject_negative_support() -> None:
    with pytest.raises(ValidationError):
        FieldMetrics(field_id="f1", support=-1, value_accuracy=1.0,
                     hallucination_rate=0.0, evidence_accuracy=1.0, tri_state_confusion={})


def test_q4_3_out_of_range_metrics_cannot_reach_eligible() -> None:
    """端到端：越界指标无法构造 → 无法产出"看似达标"画像给 gate（不再是 field_verdict 放行）。"""
    with pytest.raises(ValidationError):
        FieldMetrics(field_id="f1", support=12, value_accuracy=2.0,
                     hallucination_rate=-1.0, evidence_accuracy=2.0, tri_state_confusion={})


# ---- 五轮红队自测（profile/regression 组）：幻觉稀释 / 证据语义 ----

def test_q3_1_pred_only_fabrication_shows_in_field_metrics() -> None:
    """codex 五轮 #1：本字段的 pred-only 伪造必须体现在字段幻觉率/F1 上，字段 gate 才拦得住
    （此前全局已算对但字段画像为 0.0，在线 gate 只看字段指标会误放）。"""
    golden = [_rec(f"P{i}", "f1", f"v{i}") for i in range(10)]
    pred = ([_rec(f"P{i}", "f1", f"v{i}") for i in range(10)]
            + [_rec(f"Q{i}", "f1", "伪造") for i in range(10)])  # 10 条覆盖面之外的 f1 伪造
    prof = _bp(golden, pred)
    m = prof.field("f1")
    assert m is not None
    assert m.support == 10               # support 仍只数金标观测
    assert m.hallucination_rate == 0.5   # 20 present 预测里 10 条伪造
    assert m.f1 < 1.0
    verdict = prof.field_verdict("f1")
    assert not verdict.eligible
    assert any("hallucination_rate" in f for f in verdict.failures)  # 字段 gate 因幻觉拦下


def test_q4_6_fabricated_fields_raise_global_hallucination_and_flag_regression() -> None:
    """红队 #1：候选伪造大量出界字段 → 全局幻觉率必须上升（计入分子）并被回归拦下，
    而非被稀释下降让 Q4.6 幻觉护栏失效。"""
    golden = [_rec("P0", "f1", "A")]
    approved = _bp(golden, [_rec("P0", "f1", "A")])
    fabricating = _bp(golden, [_rec("P0", "f1", "A"),
                               _rec("P0", "f8", "X"), _rec("P0", "f9", "Y")])
    assert (fabricating.global_metrics.hallucination_rate
            > approved.global_metrics.hallucination_rate)
    result = compare_baselines(approved, fabricating)
    assert not result.eligible
    assert any("hallucination" in f.metric for f in result.failures)


def test_q4_6_unmeasured_evidence_not_falsely_flagged() -> None:
    """红队 #3：基线已回验(1.0)、候选未回验(None) → evidence 维不参与回归（不误报）。
    候选证据的绝对达标由 gate 的 field_verdict 兜底，与回归分层。"""
    base = _profile_of(_passing_metrics(evidence_accuracy=1.0))
    cand = _profile_of(_passing_metrics(evidence_accuracy=None))
    result = compare_baselines(base, cand)
    assert not any("evidence" in f.metric for f in result.failures)


def test_q4_3_unmeasured_evidence_field_is_not_eligible() -> None:
    """红队 #3：未回验（evidence=None）对自动资格 fail-closed——不得当作达标。"""
    verdict = _profile_of(_passing_metrics(evidence_accuracy=None)).field_verdict("f1")
    assert not verdict.eligible
    assert any("evidence 未回验" in f for f in verdict.failures)


def test_q3_1_per_field_evidence_is_per_quote(monkeypatch: object, tmp_path: object) -> None:
    """红队 #2：每字段证据用 per-quote 口径（与 evaluate 一致），非 per-record all-or-nothing——
    2 条引文命中 1 → 0.5，而非旧的 0.0。"""
    from insurance_harness.goldenset import pdf as pdfmod

    class _Pg:
        def __init__(self, n: int, t: str) -> None:
            self.page_no = n
            self.text = t

    monkeypatch.setattr(pdfmod, "extract_pages", lambda _p: [_Pg(1, "GOODQUOTE 命中")])  # type: ignore[attr-defined]
    root = Path(str(tmp_path))
    (root / "产品P0").mkdir(parents=True)
    (root / "产品P0" / "d.pdf").write_text("x", encoding="utf-8")
    golden = [_rec("P0", "f1", "V")]
    pred = [GoldenRecord(
        product_id="P0", product_name="产品P0", doc="d.pdf", field_id="f1", field_name="f1",
        value="V", tri_state="present",
        evidence=[Evidence(page=1, quote="GOODQUOTE"), Evidence(page=1, quote="缺失引文")],
        annotator_model="m", schema_version="v1.1+x", created_at=_AT,
    )]
    m = _bp(golden, pred, dataset_root=root).field("f1")
    assert m is not None and m.evidence_accuracy == 0.5  # per-quote：2 命中 1


# ------------------------- Q3.1 全局指标与 evaluate 语义严格一致（四轮 #4）

def test_q3_1_global_micro_f1_matches_evaluator_with_pred_only_fields() -> None:
    """四轮 #4：预测多出的字段必须计入全局 micro FP，与 evaluate 完全一致——
    否则产生多余字段的模型会被画像误判满分（最危险的漂移）。"""
    golden = [_rec("P0", "f1", "值0")]
    pred = [_rec("P0", "f1", "值0"), _rec("P0", "f2", "多余")]  # f2 金标没有
    gm = _bp(golden, pred).global_metrics
    ev = evaluate(golden, pred)
    assert gm.micro_f1 == ev.micro.f1
    assert gm.micro_f1 < 1.0  # 有多余字段 → 不该满分


def test_q3_1_global_micro_f1_matches_evaluator_absent_only() -> None:
    """四轮 #4：全 absent 的空分母口径与 evaluate 一致（1.0，非 build_profile 旧的 0.0）。"""
    golden = [_rec("P0", "f1", None, "absent_explicitly")]
    pred = [_rec("P0", "f1", None, "absent_explicitly")]
    gm = _bp(golden, pred).global_metrics
    ev = evaluate(golden, pred)
    assert gm.micro_f1 == ev.micro.f1 == 1.0
    assert gm.macro_f1 == ev.macro_f1 == 1.0


def test_q3_1_global_metrics_match_evaluator_mixed() -> None:
    """四轮 #4：混合场景（值对/值错/幻觉/absent/多余字段）全局三指标逐一对齐 evaluate。"""
    golden = [_rec("P0", "f1", "A"), _rec("P1", "f1", "B"),
              _rec("P2", "f2", None, "absent_explicitly"), _rec("P3", "f2", "C")]
    pred = [_rec("P0", "f1", "A"), _rec("P1", "f1", "错"), _rec("P2", "f2", "编造"),
            _rec("P3", "f2", "C"), _rec("P9", "f9", "多余")]
    gm = _bp(golden, pred).global_metrics
    ev = evaluate(golden, pred)
    assert gm.micro_f1 == ev.micro.f1
    assert gm.macro_f1 == ev.macro_f1
    assert gm.hallucination_rate == ev.hallucination_rate


def test_q3_1_per_field_prf_match_evaluator() -> None:
    """四轮 #4：每字段 P/R/F1 也取自 evaluate（不再重复实现一套统计）。"""
    golden = [_rec("P0", "f1", "A"), _rec("P1", "f1", "B"), _rec("P2", "f1", "C")]
    pred = [_rec("P0", "f1", "A"), _rec("P1", "f1", "错"), _rec("P2", "f1", "C")]
    m = _bp(golden, pred).field("f1")
    ev_field = evaluate(golden, pred).per_field["f1"]
    assert m is not None
    assert m.precision == ev_field.precision
    assert m.recall == ev_field.recall
    assert m.f1 == ev_field.f1


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
    # 预测无证据 → 未回验（None）→ 证据维仍失格（fail-closed），失败信息含"evidence"。
    assert any("evidence" in f for f in verdict.failures)


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


def test_q4_6_per_field_drop_caught_even_when_global_faked_perfect() -> None:
    """四轮加固：候选把 global_metrics 伪装成满分，但某字段 value_accuracy 退化——
    compare_baselines 仍按 per-field 拦下（全局数字不能掩盖字段回归）。"""
    def _p(va: float) -> QualityProfile:
        return QualityProfile(
            profile_version="1", artifact_sha256=_ART, baseline_approval_sha256="",
            fingerprint=_fp(), fields={"f1": _passing_metrics("f1", value_accuracy=va)},
            global_metrics=GlobalMetrics(micro_f1=1.0, macro_f1=1.0,
                                         hallucination_rate=0.0, evidence_accuracy=1.0),
        )
    result = compare_baselines(_p(1.0), _p(0.5))
    assert not result.eligible
    assert any("f1.value_accuracy" in f.metric for f in result.failures)


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
