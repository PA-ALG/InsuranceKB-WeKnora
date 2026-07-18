"""F1.2 四类信号识别器（纯规则，可配置启停）。

无引用回答 / 低置信·拒答 / 负反馈 / 空知识命中；确定性，零模型。空知识识别用
注入式 ``claim_lookup``（DI）：给定 ``aligned_entity`` 返回是否已有 published Claim，
从而 F1 不硬依赖 knowledge 域（对齐在 F2 回填 ``aligned_entity``）。
"""

from __future__ import annotations

from collections.abc import Callable

from .models import SignalConfig, SignalType, Trace

#: 拒答话术模式（F1.2 低置信/拒答）。
REFUSAL_PATTERNS: tuple[str, ...] = (
    "无法回答",
    "没有找到",
    "未找到",
    "抱歉",
    "无法提供",
    "不清楚",
    "无法确定",
    "建议咨询",
)

#: claim_lookup(aligned_entity) -> True 表示该实体已有 published Claim。
ClaimLookup = Callable[[str], bool]

#: 负反馈标注（F1.2）。
NEGATIVE_ANNOTATIONS: tuple[str, ...] = ("thumbs_down", "downvote", "negative", "bad")

#: no_citation 的最短实质回答长度（低于此视作非实质回答，不判"有答无引"）。
_MIN_SUBSTANTIVE_LEN = 8

DEFAULT_CONFIG = SignalConfig()


def _is_refusal(answer: str) -> bool:
    return any(p in answer for p in REFUSAL_PATTERNS)


def detect_signals(
    trace: Trace,
    config: SignalConfig = DEFAULT_CONFIG,
    *,
    claim_lookup: ClaimLookup | None = None,
) -> set[SignalType]:
    """识别一条 trace 命中的信号集合（可空）；确定性、零模型。"""
    out: set[SignalType] = set()
    answer = trace.answer.strip()
    refusal = _is_refusal(answer)

    if config.low_confidence_refusal:
        low_score = (
            config.low_score_threshold is not None
            and trace.score is not None
            and trace.score < config.low_score_threshold
        )
        if refusal or low_score:
            out.add("low_confidence_refusal")

    # 有实质回答但零引用 → 疑似编造/缺失；拒答天然无引用，归上一类不算此类。
    if (
        config.no_citation
        and not refusal
        and len(answer) >= _MIN_SUBSTANTIVE_LEN
        and not trace.source_refs
    ):
        out.add("no_citation")

    if config.negative_feedback:
        neg_ann = trace.annotation is not None and trace.annotation in NEGATIVE_ANNOTATIONS
        neg_score = trace.score is not None and trace.score <= config.negative_score_max
        if neg_ann or neg_score:
            out.add("negative_feedback")

    # 空知识：仅在提供 claim_lookup 且已对齐实体时才判（F1 不硬依赖 knowledge）。
    if (
        config.empty_knowledge
        and claim_lookup is not None
        and trace.aligned_entity
        and not claim_lookup(trace.aligned_entity)
    ):
        out.add("empty_knowledge")

    return out
