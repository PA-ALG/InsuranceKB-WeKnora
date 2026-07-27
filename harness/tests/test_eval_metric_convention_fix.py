"""度量约定修复（D-2026-07-27-13 · G0-probe 失败模式 #6）：带值 absent 不算幻觉。

约定（G0a 冻结幻觉率 ≤0.10 的前置修复）：

- **幻觉** = pred=present 而金标**无任何值依据**（金标无值文本，或键在金标覆盖面之外）；
- 金标 absent_explicitly **带值文本**（如「不支持」）而 pred=present（如「不支持加保」）：
  模型找到的是同一底层事实、只是三态标注不同 → 归**三态混淆**（absent→present 错位），
  仍计入三态混淆矩阵与 precision 错误（FP），但**不计幻觉率分子**；
- 配对护栏（024 教训：放松误报的同时必须锁死真报警）：金标无值依据的 present 预测
  仍判幻觉，语义不得随本修复放松。

依据：docs/insurance-kb/probes/2026-07-27-g0-probe-report.md §3 模式 #6；
docs/insurance-kb/23-mvp-control-board.md D-2026-07-27-13。
"""

from datetime import UTC, datetime

from insurance_harness.goldenset import Evidence, GoldenRecord, evaluate
from insurance_harness.goldenset.eval import CATEGORY_HALLUCINATION, CATEGORY_TRI_STATE

_AT = datetime(2026, 7, 27, tzinfo=UTC)


def _rec(product: str, field_id: str, value: str | None, tri: str = "present") -> GoldenRecord:
    return GoldenRecord(
        product_id=product, product_name=f"产品{product}", doc="保险条款.pdf",
        field_id=field_id, field_name=field_id, value=value, tri_state=tri,  # type: ignore[arg-type]
        evidence=[Evidence(page=1, quote=value)] if value else [],
        annotator_model="claude-test", schema_version="v1.1+testtesttest", created_at=_AT,
    )


def test_absent_with_value_vs_similar_present_is_state_confusion_not_hallucination() -> None:
    """探针实测样例：是否可加保 金标=absent(不支持) vs 预测=present(不支持加保)。"""
    golden = [_rec("P1", "add_coverage_option", "不支持", "absent_explicitly")]
    pred = [_rec("P1", "add_coverage_option", "不支持加保", "present")]
    result = evaluate(golden, pred)

    # 三态混淆矩阵照常计入 absent→present 错位
    assert result.confusion[("absent_explicitly", "present")] == 1
    # precision 错误保留：仍是 FP（重分类不放松 P/R）
    assert result.micro.fp == 1 and result.micro.tp == 0
    # 但不是幻觉：金标带值依据（「不支持」），模型找到同一事实、仅三态标注不同
    assert result.hallucination_rate == 0.0
    (err,) = result.errors
    assert err.kind == "false_present"
    assert err.category == CATEGORY_TRI_STATE
    assert result.category_counts.get(CATEGORY_HALLUCINATION, 0) == 0


def test_true_hallucination_with_no_golden_basis_stays_hallucination() -> None:
    """配对护栏：金标无值依据（unknown / 无值 absent / 空白值）→ 仍判幻觉，一个不放。"""
    golden = [
        _rec("P1", "grace_period", None, "unknown"),  # 金标一无所知
        _rec("P1", "maturity_benefit", None, "absent_explicitly"),  # 明确无、且无值文本
        _rec("P1", "surrender_value", "  ", "absent_explicitly"),  # 空白值不构成值依据
    ]
    pred = [
        _rec("P1", "grace_period", "60日"),
        _rec("P1", "maturity_benefit", "有满期金"),
        _rec("P1", "surrender_value", "有现金价值"),
    ]
    result = evaluate(golden, pred)

    assert result.hallucination_rate == 1.0  # 3/3
    assert {(e.field_id, e.kind, e.category) for e in result.errors} == {
        ("grace_period", "false_present", CATEGORY_HALLUCINATION),
        ("maturity_benefit", "false_present", CATEGORY_HALLUCINATION),
        ("surrender_value", "false_present", CATEGORY_HALLUCINATION),
    }
    assert result.category_counts[CATEGORY_HALLUCINATION] == 3


def test_pred_only_out_of_coverage_present_stays_hallucination() -> None:
    """配对护栏（覆盖面外）：金标完全没有该键 → 幻觉，不受带值 absent 约定影响。"""
    golden = [_rec("P1", "waiting_period", "90天")]
    pred = [
        _rec("P1", "waiting_period", "90天"),
        _rec("P1", "made_up_field", "编造值"),  # 金标覆盖面之外
    ]
    result = evaluate(golden, pred)
    assert result.hallucination_rate == 0.5  # 2 个 present 预测里 1 个幻觉
