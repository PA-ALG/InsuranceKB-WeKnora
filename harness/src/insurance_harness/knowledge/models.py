"""知识域流转模型（change 007；口径见 docs/insurance-kb/03 与 specs/mainchain.md）。"""

import hashlib
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

ValueState = Literal["present", "absent_explicitly", "unknown"]
ReviewAction = Literal["approve", "reject", "defer"]

#: 受限动作集（K4.2）：ReviewItem 只允许这三个动作，动作集外拒绝执行。
ALLOWED_REVIEW_ACTIONS: tuple[str, ...] = ("approve", "reject", "defer")


def normalize_value(value: str | None) -> str:
    """值等价判定用的归一化：压缩空白；None → 空串。"""
    return " ".join(value.split()) if value else ""


def value_hash(value_state: str, value: str | None) -> str:
    """记录级幂等键的 value_hash 分量（K2.3）：三态 + 归一化值。"""
    payload = f"{value_state}|{normalize_value(value)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class ProposedEvidence(BaseModel):
    """待入库证据（03 §2.4 子集：pred 证据只有页码与引文）。"""

    knowledge_id: str
    doc_title: str = ""
    chunk_id: str | None = None
    quote: str
    page: int | None = None
    doc_role: str = "external"
    authority_level: int = 6
    extraction_method: str = "llm"


class ProposedClaim(BaseModel):
    """一条待合并的事实提案（导入器产出、合并引擎输入）。"""

    product_version_id: str
    predicate: str
    field_name: str = ""
    value_state: ValueState = "unknown"
    value: str | None = None
    effective_from: date | None = None
    confidence: float = 0.3
    extraction_method: str = "llm"
    schema_version: str = ""
    pending_judge: bool = False
    evidence: list[ProposedEvidence] = Field(default_factory=list)

    @property
    def best_authority(self) -> int:
        """提案的权威等级 = 证据中最权威（数值最小）者（03 §6.2 ①）。"""
        return min((e.authority_level for e in self.evidence), default=6)

    @property
    def value_hash(self) -> str:
        return value_hash(self.value_state, self.value)


class MergePolicy(BaseModel):
    """审核门禁策略（K4.4）：默认关闭自动通过=全部走审核（保守）。"""

    auto_apply_add: bool = False
    auto_apply_enrich: bool = False
    enrich_auto_min_confidence: float = 0.8
    # 权威序①②分出胜负后的低风险 supersede 自动应用（03 §2.5/§6.2：高风险一律进审核）
    auto_apply_supersede_low_risk: bool = True


class ConflictJudgeRequest(BaseModel):
    """裁决序④占位（K3.2）：claude-session 队列行格式（复用 compiler judge-queue 形态，
    JSONL 落盘、离线批处理回写，零真实模型调用）。"""

    conflict_id: str
    product_version_id: str
    predicate: str
    field_name: str = ""
    reason: str = "adjudication_tie"
    existing: dict[str, Any] = Field(default_factory=dict)
    proposed: dict[str, Any] = Field(default_factory=dict)


class ConflictJudgement(BaseModel):
    """裁决回写行格式（apply_conflict_judgements 输入）。"""

    conflict_id: str
    winner: Literal["existing", "proposed"]
    reasoning: str


class MergeReport(BaseModel):
    """一次合并批的结果统计（含审核项与裁决队列，供验收断言）。"""

    change_set_id: str = ""
    actions: dict[str, int] = Field(default_factory=dict)
    review_keys: list[str] = Field(default_factory=list)
    judge_queue_size: int = 0

    def bump(self, action: str) -> None:
        self.actions[action] = self.actions.get(action, 0) + 1


class ImportReport(BaseModel):
    """导入器结果（K2）。"""

    change_set_id: str | None = None
    duplicate_batch: bool = False
    total_records: int = 0
    imported: int = 0
    skipped_duplicates: int = 0
    skipped_no_evidence: int = 0
    unknown_placeholders: int = 0
    merge: MergeReport = Field(default_factory=MergeReport)
    judge_queue: list[ConflictJudgeRequest] = Field(default_factory=list)
