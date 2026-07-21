"""015 数据飞轮 F1 信号提取——分任务红绿（测试名引用条款号 F1.x）。

T1：4 类识别器（可配置）+ PII 脱敏 + 增量游标；零模型调用。
"""

from __future__ import annotations

from insurance_harness.flywheel.cursor import new_traces, next_cursor
from insurance_harness.flywheel.models import SignalConfig, Trace
from insurance_harness.flywheel.redact import redact_pii
from insurance_harness.flywheel.signals import detect_signals


def _trace(**kw: object) -> Trace:
    base: dict[str, object] = {"trace_id": "t1", "timestamp": "2026-07-17T00:00:00Z"}
    base.update(kw)
    return Trace(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# F1.2 无引用回答：有实质回答但零引用 → no_citation（拒答不算，它有别的信号）
# ---------------------------------------------------------------------------


def test_f1_2_no_citation_substantive_answer_without_refs() -> None:
    t = _trace(answer="等待期为 90 天，自合同生效起算。", source_refs=())
    assert "no_citation" in detect_signals(t)


def test_f1_2_no_citation_not_flagged_when_refs_present() -> None:
    t = _trace(answer="等待期为 90 天。", source_refs=("chunk-1",))
    assert "no_citation" not in detect_signals(t)


def test_f1_2_refusal_is_not_no_citation() -> None:
    """拒答天然无引用，但应归 low_confidence_refusal 而非 no_citation（不误报编造）。"""
    t = _trace(answer="抱歉，没有找到相关信息。", source_refs=())
    sig = detect_signals(t)
    assert "low_confidence_refusal" in sig
    assert "no_citation" not in sig


# ---------------------------------------------------------------------------
# F1.2 低置信/拒答：话术模式 或 score 低于阈值
# ---------------------------------------------------------------------------


def test_f1_2_low_confidence_by_refusal_phrase() -> None:
    assert "low_confidence_refusal" in detect_signals(_trace(answer="我无法回答这个问题。"))


def test_f1_2_low_confidence_by_score_threshold() -> None:
    t = _trace(answer="等待期为 90 天。", source_refs=("c1",), score=0.3)
    assert "low_confidence_refusal" in detect_signals(t)


def test_f1_2_normal_answer_no_low_confidence() -> None:
    t = _trace(answer="等待期为 90 天。", source_refs=("c1",), score=0.9)
    assert "low_confidence_refusal" not in detect_signals(t)


# ---------------------------------------------------------------------------
# F1.2 负反馈：score ≤ 负反馈上界 或 annotation 负标
# ---------------------------------------------------------------------------


def test_f1_2_negative_feedback_by_annotation() -> None:
    assert "negative_feedback" in detect_signals(
        _trace(answer="x", source_refs=("c1",), annotation="thumbs_down")
    )


def test_f1_2_negative_feedback_by_score() -> None:
    assert "negative_feedback" in detect_signals(
        _trace(answer="x", source_refs=("c1",), score=0.0)
    )


# ---------------------------------------------------------------------------
# F1.2 空知识命中：aligned_entity 查无 published Claim（注入 claim_lookup）
# ---------------------------------------------------------------------------


def test_f1_2_empty_knowledge_when_aligned_but_no_claim() -> None:
    t = _trace(answer="等待期为 90 天。", source_refs=("c1",), aligned_entity="P001/等待期")
    sig = detect_signals(t, claim_lookup=lambda e: False)
    assert "empty_knowledge" in sig


def test_f1_2_no_empty_knowledge_when_claim_exists() -> None:
    t = _trace(answer="x", source_refs=("c1",), aligned_entity="P001/等待期")
    assert "empty_knowledge" not in detect_signals(t, claim_lookup=lambda e: True)


def test_f1_2_no_empty_knowledge_without_lookup_or_entity() -> None:
    # 无 claim_lookup 或无对齐实体 → 该信号跳过（不误报）
    assert "empty_knowledge" not in detect_signals(_trace(aligned_entity="P001/等待期"))
    assert "empty_knowledge" not in detect_signals(
        _trace(answer="x", source_refs=("c1",)), claim_lookup=lambda e: False
    )


# ---------------------------------------------------------------------------
# F1.2 可配置启停：关掉的识别器即使命中也不产出
# ---------------------------------------------------------------------------


def test_f1_2_disabled_recognizer_suppressed() -> None:
    cfg = SignalConfig(no_citation=False)
    t = _trace(answer="等待期为 90 天，自合同生效起算。", source_refs=())
    assert "no_citation" not in detect_signals(t, cfg)


# ---------------------------------------------------------------------------
# F1.3 PII 脱敏：手机/证件/保单号遮蔽，非 PII 保留；脱敏是**构造边界**
# ---------------------------------------------------------------------------


def test_f1_3_redact_masks_phone() -> None:
    out = redact_pii("请问投保人 13800138000 的等待期")
    assert "13800138000" not in out
    assert "等待期" in out  # 非 PII 保留


def test_f1_3_trace_question_redacted_at_construction() -> None:
    """F1.3：脱敏在 Trace 构造边界——任何入口（直接构造/JSONL）都不承载原始 PII。"""
    direct = Trace(
        trace_id="t1", timestamp="2026-07-01T00:00:00Z",
        question="手机号13800138000的保单等待期",
    )
    assert "13800138000" not in direct.question
    assert "等待期" in direct.question
    via_json = Trace.model_validate_json(
        '{"trace_id":"t2","timestamp":"2026-07-01T00:00:00Z",'
        '"question":"证件号 11010119900307123X 的犹豫期"}'
    )
    assert "11010119900307123X" not in via_json.question
    assert "犹豫期" in via_json.question


def test_f1_3_redact_masks_id_card() -> None:
    out = redact_pii("证件号 11010119900307123X 的保单")
    assert "11010119900307123X" not in out


def test_f1_3_redact_preserves_non_pii_numbers() -> None:
    # 90 天、5.3 条这类业务数字不得被误遮
    out = redact_pii("等待期为 90 天，见第 5.3 条")
    assert "90" in out and "5.3" in out


# ---------------------------------------------------------------------------
# F1.1 增量游标：只取 cursor 之后的 trace，同 timestamp 以 trace_id 决胜
# ---------------------------------------------------------------------------


def _t(tid: str, ts: str) -> Trace:
    return Trace(trace_id=tid, timestamp=ts)


def test_f1_1_new_traces_filters_by_cursor() -> None:
    traces = [
        _t("a", "2026-07-17T01:00:00Z"),
        _t("b", "2026-07-17T02:00:00Z"),
        _t("c", "2026-07-17T03:00:00Z"),
    ]
    got = new_traces(traces, cursor="2026-07-17T02:00:00Z|b")
    assert [t.trace_id for t in got] == ["c"]


def test_f1_1_new_traces_tiebreak_by_trace_id() -> None:
    traces = [_t("a", "2026-07-17T01:00:00Z"), _t("b", "2026-07-17T01:00:00Z")]
    # 游标停在 a（同 timestamp）→ 只 b 是新的
    got = new_traces(traces, cursor="2026-07-17T01:00:00Z|a")
    assert [t.trace_id for t in got] == ["b"]


def test_f1_1_next_cursor_is_max() -> None:
    traces = [_t("a", "2026-07-17T01:00:00Z"), _t("c", "2026-07-17T03:00:00Z")]
    assert next_cursor(traces) == "2026-07-17T03:00:00Z|c"


def test_f1_1_rerun_processes_nothing_new() -> None:
    traces = [_t("a", "2026-07-17T01:00:00Z"), _t("b", "2026-07-17T02:00:00Z")]
    cur = next_cursor(traces)
    assert new_traces(traces, cur) == []  # 重跑同批 → 零新增（幂等）


# ---------------------------------------------------------------------------
# F1.1a 时序语义与批内去重（codex PR#18 复审收口）
# ---------------------------------------------------------------------------


def test_f1_1a_mixed_timezone_ordered_by_utc_instant() -> None:
    """时序按 UTC 实际时刻，不按裸字符串——"+08:00 的 09:00" 早于 "Z 的 02:00"。"""
    early = _t("early", "2026-07-17T09:00:00+08:00")  # = 01:00Z
    late = _t("late", "2026-07-17T02:00:00Z")
    got = new_traces([late, early], None)
    assert [t.trace_id for t in got] == ["early", "late"]
    # 游标编码为 UTC 归一化：以 early 为界 → 只 late 是新的
    cur = next_cursor([early])
    assert cur is not None and cur.startswith("2026-07-17T01:00:00")
    assert [t.trace_id for t in new_traces([late, early], cur)] == ["late"]


def test_f1_1a_same_trace_id_deduped_in_batch() -> None:
    """同批内同 trace_id 去重（保留最新时间戳一条），杜绝重复计数入口。"""
    a1 = _t("a", "2026-07-17T01:00:00Z")
    a2 = _t("a", "2026-07-17T02:00:00Z")  # 同 trace 更新版
    got = new_traces([a1, a2, a1], None)
    assert len(got) == 1
    assert got[0].timestamp == "2026-07-17T02:00:00Z"


def test_f1_1a_garbage_timestamp_rejected_at_construction() -> None:
    """timestamp 须可解析 ISO8601——垃圾时间戳构造期即拒（fail-fast，不进游标比较）。"""
    import pytest as _pytest
    from pydantic import ValidationError

    with _pytest.raises(ValidationError):
        Trace(trace_id="t", timestamp="not-a-time")
