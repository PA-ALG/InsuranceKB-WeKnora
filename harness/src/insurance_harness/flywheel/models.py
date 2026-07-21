"""飞轮数据形态（F1）：归一化问答 trace + 信号类型 + 识别配置。

F1.3：PII 脱敏是 **Trace 构造边界**（before-validator）——任何入口（离线 JSONL、
直接构造、未来直连适配器）产出的 question 已脱敏，不依赖某个 adapter 的调用约定
（codex PR#18 阻断5）。timestamp 构造期校验可解析 ISO8601（fail-fast，不让垃圾
时间戳进游标比较）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .redact import redact_pii

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
    score: float | None = None  # 数值评分（越低越差）
    annotation: str | None = None  # 用户反馈标签（如 thumbs_down）
    aligned_entity: str | None = None  # F2 对齐后回填；F1 空知识识别据此查 Claim

    @field_validator("question", mode="before")
    @classmethod
    def _redact_question(cls, v: object) -> str:
        # F1.3 构造边界脱敏：所有入口一致，Trace 从不承载原始 PII
        return redact_pii(str(v)) if v else ""

    @field_validator("timestamp")
    @classmethod
    def _parseable_iso(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"timestamp 须为可解析 ISO8601：{v!r}") from exc
        return v


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
