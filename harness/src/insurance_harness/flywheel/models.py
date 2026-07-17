"""飞轮数据形态（F1）：归一化的 Langfuse 问答 trace + 信号类型 + 识别配置。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: 四类知识缺口信号（F1.2）。
SignalType = Literal[
    "no_citation",  # 有实质回答但零引用 → 疑似编造/知识缺失
    "low_confidence_refusal",  # 拒答话术 或 score 低于阈值
    "negative_feedback",  # Langfuse score/annotation 负反馈
    "empty_knowledge",  # 问题实体对齐后查无 published Claim
]

ALL_SIGNALS: tuple[SignalType, ...] = (
    "no_citation",
    "low_confidence_refusal",
    "negative_feedback",
    "empty_knowledge",
)


class Trace(BaseModel):
    """一条归一化问答 trace（从 Langfuse trace 投影出识别器所需字段）。"""

    model_config = ConfigDict(frozen=True)

    trace_id: str = Field(min_length=1)
    timestamp: str = Field(min_length=1)  # ISO8601，用于增量游标严格排序
    question: str = ""
    answer: str = ""
    source_refs: tuple[str, ...] = ()  # 引用/chunk 标识
    score: float | None = None  # Langfuse 数值评分（越低越差）
    annotation: str | None = None  # 用户反馈标签（如 thumbs_down）
    aligned_entity: str | None = None  # F2 对齐后回填；F1 空知识识别据此查 Claim


class SignalConfig(BaseModel):
    """识别器启停（F1.2 可配置）+ 阈值。"""

    model_config = ConfigDict(frozen=True)

    no_citation: bool = True
    low_confidence_refusal: bool = True
    negative_feedback: bool = True
    empty_knowledge: bool = True
    #: 低于此分视作低置信（None=不启用分数阈值，仅靠话术模式）。
    low_score_threshold: float | None = 0.5
    #: 负反馈分数上界（≤ 视作负反馈）。
    negative_score_max: float = 0.0
