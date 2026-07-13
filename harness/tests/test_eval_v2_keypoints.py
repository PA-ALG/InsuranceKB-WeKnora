"""005 spec V1/V2/V3/V4/V7.3：要点清单机制 + eval v2 关键要点匹配 + 错误归因 + judge 队列。"""

import json
from datetime import UTC, datetime
from pathlib import Path

from insurance_harness.goldenset import (
    Evidence,
    GoldenRecord,
    KeypointEntry,
    build_release,
    evaluate,
    load_keypoints,
    load_release,
    render_report,
    score_keypoints,
    split_keypoints,
    value_sha,
    write_keypoints,
)
from insurance_harness.goldenset.eval import (
    CATEGORY_EVIDENCE,
    CATEGORY_HALLUCINATION,
    CATEGORY_MISSED,
    CATEGORY_TRI_STATE,
    CATEGORY_VALUE,
)
from insurance_harness.goldenset.eval import (
    main as eval_main,
)
from insurance_harness.goldenset.keypoints import EvalJudgeRequest

CREATED = datetime(2026, 7, 12, tzinfo=UTC)

LONG_GOLDEN = (
    "因下列情形之一导致被保险人身故的，我们不承担给付身故保险金的责任："
    "1.投保人对被保险人的故意杀害、故意伤害；2.被保险人故意犯罪；"
    "3.被保险人自本合同成立之日起2年内自杀；4.被保险人服用、吸食或注射毒品；"
    "5.战争、军事冲突、暴乱或武装叛乱。"
)


def _rec(
    product: str,
    field_id: str,
    value: str | None,
    tri: str = "present",
    *,
    evidence: list[Evidence] | None = None,
    disputed: bool = False,
) -> GoldenRecord:
    if evidence is None:
        evidence = [Evidence(page=1, quote=value[:20])] if value else []
    return GoldenRecord(
        product_id=product,
        product_name=f"产品{product}",
        doc="保险条款.pdf",
        field_id=field_id,
        field_name=field_id,
        value=value,
        tri_state=tri,  # type: ignore[arg-type]
        evidence=evidence,
        disputed=disputed,
        disputed_reason="quote_mismatch" if disputed else None,
        annotator_model="claude-test",
        schema_version="v1.1+testtesttest",
        created_at=CREATED,
    )


def _entry(product: str, field_id: str, golden_value: str, **kw: object) -> KeypointEntry:
    return KeypointEntry(
        product_id=product,
        field_id=field_id,
        keypoints=split_keypoints(golden_value),
        golden_value_sha=value_sha(golden_value),
        **kw,  # type: ignore[arg-type]
    )


# --- V1.3 规则切分 ---


def test_v1_3_split_keypoints_on_semicolons_and_enumerators() -> None:
    kps = split_keypoints(LONG_GOLDEN)
    assert len(kps) == 6  # 引导句 + 5 项
    assert any("故意杀害" in k for k in kps)
    assert any("战争" in k for k in kps)
    # 枚举前缀被剥掉；小数序号（如"3.3效力中止"）不误切
    assert not any(k.startswith("1.") for k in kps)
    decimal_ref = "详见3.3效力中止与恢复条款约定内容"
    assert split_keypoints(decimal_ref) == [decimal_ref]


def test_v1_3_split_drops_short_fragments_and_dedupes() -> None:
    kps = split_keypoints("等待期90天；等待期90天；无；1.等待期90天")
    assert kps == ["等待期90天"]  # 去重 + "无"（<4 字）丢弃


# --- V2.2/V2.3/V2.4 覆盖判定与计分 ---


def test_v2_2_coverage_substring_and_bigram_tolerance() -> None:
    entry = _entry("P1", "exclusions_official", LONG_GOLDEN)
    # 预测：覆盖全部要点但措辞轻度差异（酒驾项缺失以外全部保留）
    pred = LONG_GOLDEN.replace("我们不承担给付身故保险金的责任", "不承担给付身故保险金责任")
    score = score_keypoints(pred, entry)
    assert score.coverage == 1.0 and score.matched


def test_v2_3_below_threshold_is_mismatch_with_partial_coverage() -> None:
    entry = _entry("P1", "exclusions_official", LONG_GOLDEN)
    pred = "1.投保人对被保险人的故意杀害、故意伤害；2.被保险人故意犯罪。"
    score = score_keypoints(pred, entry)
    assert 0 < score.coverage < 0.8 and not score.matched
    assert score.missing  # 缺失要点可列出（工单/judge 线索）


def test_v2_4_contradiction_vetoes_even_full_coverage() -> None:
    entry = KeypointEntry(
        product_id="P1",
        field_id="waiting_period",
        keypoints=["等待期90天"],
        contradictions=["无等待期"],
        golden_value_sha=value_sha("等待期90天"),
    )
    score = score_keypoints("等待期90天，但续保后无等待期", entry)
    assert score.coverage == 1.0 and score.contradicted and not score.matched


# --- V2.1/V2.6/V2.7 evaluate 集成 ---


def _kp_map(*entries: KeypointEntry) -> dict[tuple[str, str], KeypointEntry]:
    return {(e.product_id, e.field_id): e for e in entries}


def test_v2_1_v2_7_metric_switch_long_field_scored_by_keypoints() -> None:
    golden = [_rec("P1", "exclusions_official", LONG_GOLDEN)]
    # 预测覆盖 6 要点中的 5 个（≥80%），但整体字符串与金标不同 → v1 判错、v2 判对
    pred_value = LONG_GOLDEN.replace("5.战争、军事冲突、暴乱或武装叛乱。", "")
    pred = [_rec("P1", "exclusions_official", pred_value)]
    keypoints = _kp_map(_entry("P1", "exclusions_official", LONG_GOLDEN))

    v1 = evaluate(golden, pred)  # 默认口径不变（V2.7）
    assert v1.metric == "v1" and v1.micro.tp == 0 and v1.micro.fp == 1

    v2 = evaluate(golden, pred, metric="v2", keypoints=keypoints)
    assert v2.micro.tp == 1 and v2.micro.fp == 0
    assert len(v2.partials) == 1  # V2.6 partial 覆盖率列
    assert 0.8 <= v2.partials[0].coverage < 1.0
    report = render_report(v2)
    assert "要点计分明细" in report and "metric=v2" in report


def test_v2_1_short_fields_fall_back_to_v1_rules() -> None:
    golden = [_rec("P1", "hesitation_period", "20日")]
    pred = [_rec("P1", "hesitation_period", "20 日")]
    v2 = evaluate(golden, pred, metric="v2", keypoints={})
    assert v2.micro.tp == 1 and not v2.partials  # 无要点条目 → 确定性归一化等价


def test_v2_5_stale_keypoints_fall_back_and_counted() -> None:
    golden = [_rec("P1", "exclusions_official", LONG_GOLDEN)]
    pred = [_rec("P1", "exclusions_official", "完全不同的预测值内容")]
    stale = KeypointEntry(
        product_id="P1",
        field_id="exclusions_official",
        keypoints=["完全不同的预测值内容"],  # 若被采用会判对——必须被 sha 拦截
        golden_value_sha=value_sha("金标已经改值了"),
    )
    v2 = evaluate(golden, pred, metric="v2", keypoints=_kp_map(stale))
    assert v2.stale_keypoints == 1
    assert v2.micro.tp == 0  # 回落 v1 判错，过期要点没有生效


def test_v7_3_self_consistency_perfect_under_both_metrics() -> None:
    golden = [
        _rec("P1", "exclusions_official", LONG_GOLDEN),
        _rec("P1", "hesitation_period", "20日"),
        _rec("P1", "maturity_benefit", None, "absent_explicitly"),
    ]
    keypoints = _kp_map(_entry("P1", "exclusions_official", LONG_GOLDEN))
    for kwargs in ({}, {"metric": "v2", "keypoints": keypoints}):
        result = evaluate(golden, golden, **kwargs)  # type: ignore[arg-type]
        assert result.micro.f1 == 1.0, kwargs


# --- V3 错误五类归因 ---


def test_v3_1_five_categories_assigned() -> None:
    golden = [
        _rec("P1", "f_value", "20日"),
        _rec("P1", "f_missed", "90天"),
        _rec("P1", "f_halluc", None, "unknown"),
        _rec("P1", "f_tri", None, "absent_explicitly"),
        _rec("P1", "f_tri2", "有豁免"),
        _rec("P1", "f_evidence", "60日", evidence=[Evidence(page=3, quote="宽限期60日")]),
    ]
    pred = [
        _rec("P1", "f_value", "15日"),  # 值粒度
        _rec("P1", "f_missed", None, "unknown"),  # 漏抽
        _rec("P1", "f_halluc", "编造值"),  # 幻觉
        _rec("P1", "f_tri", None, "unknown"),  # 三态混淆（absent↔unknown）
        _rec("P1", "f_tri2", None, "absent_explicitly"),  # 三态混淆（present→absent）
        _rec("P1", "f_evidence", "60日", evidence=[Evidence(page=9, quote="宽限期60日")]),
    ]
    result = evaluate(golden, pred)
    by_field = {e.field_id: e for e in result.errors}
    assert by_field["f_value"].category == CATEGORY_VALUE
    assert by_field["f_missed"].category == CATEGORY_MISSED
    assert by_field["f_halluc"].category == CATEGORY_HALLUCINATION
    assert by_field["f_tri"].category == CATEGORY_TRI_STATE
    assert by_field["f_tri2"].category == CATEGORY_TRI_STATE
    # 证据错位：值判对（TP 不受影响）但证据页相差 >1 → 单列
    assert by_field["f_evidence"].category == CATEGORY_EVIDENCE
    assert result.evidence_mismatch_count == 1
    assert result.per_field["f_evidence"].tp == 1  # 不改 F1
    assert set(result.category_counts) == {
        CATEGORY_VALUE, CATEGORY_MISSED, CATEGORY_HALLUCINATION,
        CATEGORY_TRI_STATE, CATEGORY_EVIDENCE,
    }


def test_v3_2_report_contains_distribution_and_tickets() -> None:
    golden = [_rec("P1", "f_missed", "90天")]
    pred = [_rec("P1", "f_missed", None, "unknown")]
    report = render_report(evaluate(golden, pred))
    assert "错误类型分布" in report and "错误工单明细" in report
    assert CATEGORY_MISSED in report and "recall_attribution" in report


# --- V4 eval-judge-queue ---


def test_v4_1_uncertain_band_enqueued_only_when_path_given(tmp_path: Path) -> None:
    golden = [_rec("P1", "exclusions_official", LONG_GOLDEN)]
    # 覆盖 6 要点中 4 个 → 覆盖率 ~0.67 ∈ [0.5, 0.8)：不确定带
    pred_value = (
        "因下列情形之一导致被保险人身故的，我们不承担给付身故保险金的责任："
        "1.投保人对被保险人的故意杀害、故意伤害；2.被保险人故意犯罪；"
        "3.被保险人自本合同成立之日起2年内自杀。"
    )
    pred = [_rec("P1", "exclusions_official", pred_value)]
    keypoints = _kp_map(_entry("P1", "exclusions_official", LONG_GOLDEN))

    # 默认关（V4.1）：只计数不落盘
    result = evaluate(golden, pred, metric="v2", keypoints=keypoints)
    assert result.judge_pending == 1
    assert "未裁决计数" in render_report(result)  # V4.3

    # 显式给路径才落盘
    queue_path = tmp_path / "eval-judge-queue.jsonl"
    result2 = evaluate(
        golden, pred, metric="v2", keypoints=keypoints, judge_queue_path=queue_path
    )
    assert result2.judge_pending == 1 and queue_path.exists()
    row = json.loads(queue_path.read_text(encoding="utf-8").splitlines()[0])
    assert row["field_id"] == "exclusions_official"
    assert row["reason"] == "keypoint_uncertain"
    assert len(row["candidates"]) == 2  # 金标值 + 预测值


def test_v4_2_queue_format_aligned_with_compiler_judge_request() -> None:
    """goldenset 不 import compiler 实现（05 §1.1）——用字段集合断言结构对齐。"""
    from insurance_harness.compiler.models import Judgement, JudgeRequest

    assert set(EvalJudgeRequest.model_fields) == set(JudgeRequest.model_fields)
    # 裁决回写行沿用 compiler Judgement 字段（复用 apply-judgements 批处理形态）
    assert {"product_id", "field_id", "value", "tri_state", "evidence", "confidence",
            "reasoning"} <= set(Judgement.model_fields)


# --- V1.1/V1.2 keypoints.jsonl 落盘与加载 ---


def test_v1_1_write_load_keypoints_release_and_wip_layout(tmp_path: Path) -> None:
    entry = _entry("P1", "exclusions_official", LONG_GOLDEN)
    # release 布局：顶层 keypoints.jsonl
    release = tmp_path / "gs-v0.2"
    release.mkdir()
    write_keypoints([entry], release / "keypoints.jsonl")
    # wip 布局：产品子目录
    wip = tmp_path / "wip"
    write_keypoints([entry], wip / "产品P1" / "keypoints.jsonl")
    for root in (release, wip):
        loaded = load_keypoints(root)
        assert loaded[("P1", "exclusions_official")].keypoints == entry.keypoints


def test_v1_2_load_release_skips_keypoints_jsonl(tmp_path: Path) -> None:
    golden = [_rec("P1", "hesitation_period", "20日")]
    release = tmp_path / "gs"
    build_release(golden, release)
    write_keypoints(
        [_entry("P1", "exclusions_official", LONG_GOLDEN)], release / "keypoints.jsonl"
    )
    records = load_release(release)  # keypoints.jsonl 不是金标记录，不得混入
    assert len(records) == 1 and records[0].field_id == "hesitation_period"


def test_v2_7_cli_metric_v2_end_to_end(tmp_path: Path) -> None:
    golden = [_rec("P1", "exclusions_official", LONG_GOLDEN)]
    release = tmp_path / "gs"
    build_release(golden, release)
    write_keypoints(
        [_entry("P1", "exclusions_official", LONG_GOLDEN)], release / "keypoints.jsonl"
    )
    pred_path = tmp_path / "pred.jsonl"
    pred_value = LONG_GOLDEN.replace("5.战争、军事冲突、暴乱或武装叛乱。", "")
    pred_path.write_text(
        _rec("P1", "exclusions_official", pred_value).model_dump_json() + "\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "report.md"
    code = eval_main(
        ["--golden", str(release), "--pred", str(pred_path), "--report", str(report_path),
         "--metric", "v2"]
    )
    assert code == 0
    text = report_path.read_text(encoding="utf-8")
    assert "metric=v2" in text
    assert "micro Precision / Recall / F1：**1.0000 / 1.0000 / 1.0000**" in text
