"""抽取管道数据模型（004；口径见 docs/insurance-kb/03/04）。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..goldenset.pdf import PageText
from ..goldenset.records import Evidence, GoldenRecord, TriState
from .llm import CallStats
from .sections import DocSection

Confidence = Literal["high", "medium", "low"]

# unknown 的机器可读原因（绝不静默丢弃，04 §2.1）
UnknownReason = Literal[
    "parse_failed",  # 输出解析失败（重试后）E3.1
    "quote_mismatch",  # 引文回验失败（打回后仍失败）E3.2
    "validation_failed",  # Pydantic/类型校验失败（打回后仍失败）E3.4
    "placeholder",  # 占位值清洗命中 E3.3
    "no_candidate_sections",  # 补漏检索无候选章节 E4.1
    "not_found",  # 所有候选章节均"未提及" E4.1
    "dead_letter",  # 传输级失败超重试上限 E1.2
    "missing_in_response",  # 模型未返回该字段
]

CandidateOrigin = Literal["extract", "gapfill", "vote", "judge"]


class FieldCandidate(BaseModel):
    """单字段候选值：管道内部流转单元（合并前，每 (doc, field) 可有多个）。"""

    field_id: str
    field_name: str
    group: str
    doc: str
    value: str | None = None
    tri_state: TriState = "unknown"
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: Confidence = "low"
    origin: CandidateOrigin = "extract"
    unknown_reason: UnknownReason | None = None
    source_pointer: str | None = None  # "详见费率表"类指针（补漏 pass 消解）
    pending_judge: bool = False  # claude-session 裁决队列在途（08 选型更新）
    vote_agreement: int | None = None  # 3=全票 2=多数 1=三票三样
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeadLetter(BaseModel):
    """节点/调用失败超重试上限的死信（E1.2）：不中断其他字段组，可重放。"""

    product: str
    doc: str
    group: str
    window_ref: str  # 章节窗口标识（section_id 区间）
    field_ids: list[str]
    error: str
    attempts: int


class JudgeRequest(BaseModel):
    """claude-session 裁决请求（judge-queue.jsonl 行格式；主会话 Claude 批处理）。"""

    product_id: str
    product_name: str
    doc: str
    field_id: str
    field_name: str
    reason: Literal["vote_disagreement", "quote_mismatch_high_risk"]
    candidates: list[dict[str, Any]]  # [{value, evidence?, note?}]
    context_excerpt: str


class Judgement(BaseModel):
    """裁决回写行格式（apply-judgements CLI 输入）。"""

    product_id: str
    field_id: str
    value: str | None = None
    tri_state: TriState = "present"
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: Confidence = "medium"
    reasoning: str | None = None


class DocManifestEntry(BaseModel):
    doc: str
    doc_pages: int
    sections: int
    family_id: str  # 章节标题序列结构指纹（11 §1.1）
    routed_pairs: int
    total_pairs: int
    compression_ratio: float


class RunManifest(BaseModel):
    """run manifest（E1.3）：schema 版本、模型、prompt 版本、耗时、调用与 token 统计。"""

    run_id: str
    product_dir: str
    product_id: str = ""
    product_name: str = ""
    line_key: str = ""
    schema_version: str = ""
    model_id: str = ""
    judge_mode: str = "claude-session"
    prompt_version: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_s: float | None = None
    stats: CallStats = Field(default_factory=CallStats)
    docs: list[DocManifestEntry] = Field(default_factory=list)
    dead_letters: list[DeadLetter] = Field(default_factory=list)
    pending_judge_count: int = 0


class DocPayload(BaseModel):
    """单文档的管道中间产物（入 LangGraph state，JSON 可序列化）。"""

    doc: str
    pages: list[PageText]
    sections: list[DocSection] = Field(default_factory=list)
    by_group: dict[str, list[str]] = Field(default_factory=dict)
    family_id: str = ""


class PredRecord(GoldenRecord):
    """pred JSONL 行格式：GoldenRecord 对齐 + confidence 扩展（E5.1，eval 忽略未知字段）。"""

    confidence: Confidence = "low"
    pending_judge: bool = False
    unknown_reason: UnknownReason | None = None
