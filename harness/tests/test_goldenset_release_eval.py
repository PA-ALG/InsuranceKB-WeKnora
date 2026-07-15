"""spec G3 / G4：release 不可变管理与 eval runner。"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from insurance_harness.goldenset import (
    Evidence,
    GoldenRecord,
    build_release,
    evaluate,
    load_release,
    render_report,
    write_jsonl,
)
from insurance_harness.goldenset.eval import main as eval_main

CREATED = datetime(2026, 7, 11, tzinfo=UTC)


def _rec(
    product: str,
    field_id: str,
    value: str | None,
    tri: str = "present",
    *,
    disputed: bool = False,
) -> GoldenRecord:
    return GoldenRecord(
        product_id=product,
        product_name=f"产品{product}",
        doc="保险条款.pdf",
        field_id=field_id,
        field_name=field_id,
        value=value,
        tri_state=tri,  # type: ignore[arg-type]
        evidence=[Evidence(page=1, quote=value)] if value else [],
        disputed=disputed,
        disputed_reason="quote_mismatch" if disputed else None,
        annotator_model="claude-test",
        schema_version="v1.1+testtesttest",
        created_at=CREATED,
    )


GOLDEN = [
    _rec("P1", "hesitation_period", "20日"),
    _rec("P1", "waiting_period", "90天"),
    _rec("P1", "maturity_benefit", None, "absent_explicitly"),
    _rec("P2", "hesitation_period", "15日"),
    _rec("P2", "waiting_period", None, "unknown"),
    _rec("P2", "maturity_benefit", "满期给付", disputed=True),  # disputed → 评估时排除
]


def test_g3_release_manifest_and_immutability(tmp_path: Path) -> None:
    out = tmp_path / "gs-v0.1"
    manifest = build_release(GOLDEN, out)
    assert (out / "P1.jsonl").exists() and (out / "P2.jsonl").exists()
    assert (out / "manifest.json").exists() and (out / "disputed.jsonl").exists()
    totals = manifest["totals"]
    assert isinstance(totals, dict)
    assert totals["records"] == 6 and totals["products"] == 2 and totals["disputed"] == 1
    disputed_lines = (out / "disputed.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(disputed_lines) == 1
    with pytest.raises(FileExistsError, match="不可变"):  # G3.2
        build_release(GOLDEN, out)


def test_g4_3_self_consistency(tmp_path: Path) -> None:
    out = tmp_path / "gs"
    build_release(GOLDEN, out)
    golden = load_release(out)
    usable = [g for g in golden if not g.disputed]
    result = evaluate(golden, usable)
    assert result.micro.f1 == 1.0 and result.macro_f1 == 1.0
    assert result.hallucination_rate == 0.0
    assert result.golden_disputed_excluded == 1
    # 混淆矩阵全对角
    assert all(g == p for (g, p), n in result.confusion.items() if n)


def test_g4_2_error_types_and_metrics() -> None:
    golden = [g for g in GOLDEN if not g.disputed]
    pred = [
        _rec("P1", "hesitation_period", "20天"),  # 值不等价 → value_mismatch
        _rec("P1", "waiting_period", None, "unknown"),  # 漏抽 → missed
        _rec("P1", "maturity_benefit", "有满期金"),  # 金标明确无 → 幻觉 false_present
        _rec("P2", "hesitation_period", "15 日"),  # 归一化后等价 → TP
        _rec("P2", "waiting_period", None, "absent_explicitly"),  # 三态错位（非 present）
    ]
    result = evaluate(golden, pred)
    kinds = {(e.field_id, e.kind) for e in result.errors}
    assert ("hesitation_period", "value_mismatch") in kinds
    assert ("waiting_period", "missed") in kinds
    assert ("maturity_benefit", "false_present") in kinds
    assert ("waiting_period", "tri_state") in kinds
    assert result.micro.tp == 1
    assert result.hallucination_rate == pytest.approx(1 / 3)  # present 预测 3 个，1 个幻觉
    report = render_report(result, high_risk_field_ids={"waiting_period"})
    assert "三态混淆矩阵" in report and "value_mismatch" in report and "高风险字段" in report


def test_g4_pred_only_present_counts_as_hallucination() -> None:
    """四轮红队 #1：预测多出的、金标覆盖面之外的 present 字段也是幻觉，必须计入幻觉率**分子**
    （否则伪造大量出界字段会把 hallucination_rate 稀释下降，让 Q4.6 幻觉护栏形同虚设）。"""
    golden = [_rec("P1", "waiting_period", "30天")]
    clean = evaluate(golden, [_rec("P1", "waiting_period", "30天")])
    fabricating = evaluate(golden, [
        _rec("P1", "waiting_period", "30天"),
        _rec("P1", "made_up_a", "X"), _rec("P1", "made_up_b", "Y"),  # 金标没有的字段
    ])
    assert clean.hallucination_rate == 0.0
    assert fabricating.hallucination_rate > 0.0  # 伪造字段抬高幻觉率，而非稀释


def test_g4_1_cli_end_to_end(tmp_path: Path) -> None:
    golden_dir = tmp_path / "gs"
    build_release(GOLDEN, golden_dir)
    pred_path = tmp_path / "pred.jsonl"
    write_jsonl([g for g in GOLDEN if not g.disputed], pred_path)
    report_path = tmp_path / "report.md"
    code = eval_main(
        ["--golden", str(golden_dir), "--pred", str(pred_path), "--report", str(report_path)]
    )
    assert code == 0
    text = report_path.read_text(encoding="utf-8")
    assert "micro Precision / Recall / F1：**1.0000 / 1.0000 / 1.0000**" in text


def test_g4_pred_only_keys_count_as_fp(tmp_path: Path) -> None:
    golden = [_rec("P1", "hesitation_period", "20日")]
    pred = [
        _rec("P1", "hesitation_period", "20日"),
        _rec("P9", "hesitation_period", "10日"),  # 金标外多余预测
    ]
    result = evaluate(golden, pred)
    assert result.pred_only_keys == 1 and result.micro.fp == 1


def test_manifest_is_valid_json(tmp_path: Path) -> None:
    out = tmp_path / "gs"
    build_release(GOLDEN, out)
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["schema_versions"] == ["v1.1+testtesttest"]
    assert data["annotator_models"] == ["claude-test"]
