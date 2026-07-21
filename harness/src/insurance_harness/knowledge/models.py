"""知识域流转模型（change 007；口径见 docs/insurance-kb/03 与 specs/mainchain.md）。"""

import hashlib
import re
from collections.abc import Mapping
from datetime import date
from types import MappingProxyType
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from insurance_harness.adapters.weknora.models import normalize_safe_knowledge_id
from insurance_harness.sources.models import (
    SourceOrdering,
    SourceRevision,
    source_ordering_identity_token,
)

ValueState = Literal["present", "absent_explicitly", "unknown"]
ReviewAction = Literal["approve", "reject", "defer"]
LineageStatus = Literal["linked", "page_only", "ambiguous"]
ImportLifecycleDecision = Literal[
    "accepted_create",
    "accepted_advance",
    "accepted_reactivate",
    "idempotent",
    "stale",
    "blocked_deleted",
]

#: 受限动作集（K4.2）：ReviewItem 只允许这三个动作，动作集外拒绝执行。
ALLOWED_REVIEW_ACTIONS: tuple[str, ...] = ("approve", "reject", "defer")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_MD5_OR_SHA256_HEX = re.compile(r"^(?:[0-9a-f]{32}|[0-9a-f]{64})$")


def _non_empty(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("source identity values must not be empty")
    return normalized


class SourceImportIdentity(BaseModel):
    """Trusted source identity for one compiler document at import time."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
    )

    knowledge_id: str
    raw_kb_id: str
    source_revision: str
    ordering: SourceOrdering
    file_hash: str
    original_digest: str
    parser_version: str

    _validate_non_empty = field_validator("raw_kb_id", "parser_version")(_non_empty)

    @field_validator("knowledge_id")
    @classmethod
    def _validate_knowledge_id(cls, value: str) -> str:
        normalized = normalize_safe_knowledge_id(value)
        if normalized is None:
            raise ValueError("knowledge ID violates the WeKnora source identity contract")
        return normalized

    @field_validator("source_revision", "original_digest")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        normalized = value.lower()
        if _SHA256_HEX.fullmatch(normalized) is None:
            raise ValueError("source revision and original digest must be SHA-256")
        return normalized

    @field_validator("file_hash")
    @classmethod
    def _validate_file_hash(cls, value: str) -> str:
        normalized = value.lower()
        if _MD5_OR_SHA256_HEX.fullmatch(normalized) is None:
            raise ValueError("file hash must be MD5 or SHA-256")
        return normalized

    @model_validator(mode="after")
    def _validate_revision_identity(self) -> "SourceImportIdentity":
        SourceRevision(
            file_hash=self.file_hash,
            ordering=self.ordering,
            parser_fingerprint=self.parser_version,
            value=self.source_revision,
        )
        return self


class SourceImportContext(BaseModel):
    """Scope-attested document-to-source mapping; filenames are lookup keys only."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
    )

    space_id: str
    tenant_id: str
    raw_kb_id: str
    documents: Mapping[str, SourceImportIdentity]

    _validate_non_empty = field_validator("space_id", "tenant_id", "raw_kb_id")(
        _non_empty
    )

    @field_validator("documents")
    @classmethod
    def _validate_documents(
        cls, value: Mapping[str, SourceImportIdentity]
    ) -> Mapping[str, SourceImportIdentity]:
        if not value:
            raise ValueError("source context requires at least one document")
        normalized: dict[str, SourceImportIdentity] = {}
        sources: dict[str, SourceImportIdentity] = {}
        for doc, identity in value.items():
            key = doc.strip()
            if not key or key in normalized:
                raise ValueError("source document names must be unique and non-empty")
            previous = sources.get(identity.knowledge_id)
            if previous is not None:
                if previous.ordering.kind != identity.ordering.kind:
                    raise ValueError("source ordering kind cannot change")
                if (
                    source_ordering_identity_token(previous.ordering)
                    == source_ordering_identity_token(identity.ordering)
                    and previous.source_revision != identity.source_revision
                ):
                    raise ValueError(
                        "source ordering collision maps to different revisions"
                    )
                if (
                    previous.source_revision == identity.source_revision
                    and previous.ordering != identity.ordering
                ):
                    raise ValueError(
                        "source revision cannot map to different ordering values"
                    )
                raise ValueError(
                    "source knowledge identities must map to exactly one document"
                )
            sources[identity.knowledge_id] = identity
            normalized[key] = identity
        return MappingProxyType(normalized)

    @field_serializer("documents")
    def _serialize_documents(
        self, value: Mapping[str, SourceImportIdentity]
    ) -> dict[str, SourceImportIdentity]:
        return dict(value)


def normalize_value(value: str | None) -> str:
    """值等价判定用的归一化：压缩空白；None → 空串。"""
    return " ".join(value.split()) if value else ""


def value_hash(value_state: str, value: str | None) -> str:
    """记录级幂等键的 value_hash 分量（K2.3）：三态 + 归一化值。"""
    payload = f"{value_state}|{normalize_value(value)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class ProposedEvidence(BaseModel):
    """待入库证据（03 §2.4 子集：pred 证据只有页码与引文）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    knowledge_id: str
    doc_title: str = ""
    chunk_id: str | None = None
    quote: str
    page: int | None = None
    doc_role: str = "external"
    authority_level: int = 6
    extraction_method: str = "llm"
    raw_kb_id: str | None = None
    source_revision: str | None = None
    file_hash: str | None = None
    original_digest: str | None = None
    parser_version: str | None = None
    chunk_hash: str | None = None
    lineage_status: LineageStatus | None = None
    stale_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _validate_source_audit(self) -> "ProposedEvidence":
        if not self.knowledge_id.strip():
            raise ValueError("knowledge identity must not be empty")
        audit = (
            self.raw_kb_id,
            self.source_revision,
            self.file_hash,
            self.original_digest,
            self.parser_version,
            self.chunk_hash,
            self.lineage_status,
            self.stale_at,
        )
        if self.lineage_status is None:
            if any(value is not None for value in audit[:-2]) or self.stale_at is not None:
                raise ValueError("source-aware evidence requires lineage status")
            return self
        required = (
            self.raw_kb_id,
            self.source_revision,
            self.file_hash,
            self.original_digest,
            self.parser_version,
        )
        if any(value is None for value in required):
            raise ValueError("source-aware evidence audit must be complete")
        assert self.raw_kb_id is not None
        assert self.source_revision is not None
        assert self.file_hash is not None
        assert self.original_digest is not None
        assert self.parser_version is not None
        if normalize_safe_knowledge_id(self.knowledge_id) is None:
            raise ValueError("knowledge ID violates the WeKnora source identity contract")
        if not self.raw_kb_id.strip() or not self.parser_version.strip():
            raise ValueError("source-aware evidence audit must be complete")
        if (
            _SHA256_HEX.fullmatch(self.source_revision.lower()) is None
            or _MD5_OR_SHA256_HEX.fullmatch(self.file_hash.lower()) is None
            or _SHA256_HEX.fullmatch(self.original_digest.lower()) is None
        ):
            raise ValueError("source-aware evidence audit digest is invalid")
        if self.lineage_status == "linked":
            if (
                self.chunk_id is None
                or not self.chunk_id.strip()
                or self.chunk_hash is None
                or _SHA256_HEX.fullmatch(self.chunk_hash.lower()) is None
            ):
                raise ValueError("linked evidence requires chunk id and SHA-256 hash")
        elif self.chunk_id is not None or self.chunk_hash is not None:
            raise ValueError("non-linked evidence cannot carry chunk identity")
        return self


class ProposedClaim(BaseModel):
    """一条待合并的事实提案（导入器产出、合并引擎输入）。"""

    space_id: str
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
    # 019 Q4.1：默认关闭低风险 supersede 自动应用（保守）；开启后仍须过 QualityGate。
    # 权威序①②分出胜负后的低风险 supersede（03 §2.5/§6.2：高风险一律进审核）。
    auto_apply_supersede_low_risk: bool = False


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
    partitions: list["ImportPartitionReport"] = Field(default_factory=list)
    change_set_ids: list[str] = Field(default_factory=list)


class ImportPartitionReport(BaseModel):
    """Lossless result for one `(knowledge_id, source_revision)` partition."""

    knowledge_id: str
    source_revision: str
    lifecycle_decision: ImportLifecycleDecision
    source_kind: str | None
    change_set_id: str | None
    duplicate_batch: bool = False
    total_records: int = 0
    imported: int = 0
    skipped_duplicates: int = 0
    skipped_no_evidence: int = 0
    unknown_placeholders: int = 0
    merge: MergeReport = Field(default_factory=MergeReport)
    judge_queue: list[ConflictJudgeRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_lifecycle_aggregate_shape(self) -> "ImportPartitionReport":
        audit_only = self.lifecycle_decision in ("stale", "blocked_deleted")
        has_aggregate = (
            self.source_kind is not None and self.change_set_id is not None
        )
        if (self.source_kind is None) != (self.change_set_id is None):
            raise ValueError("import lifecycle aggregate shape is invalid")
        if audit_only == has_aggregate:
            raise ValueError("import lifecycle aggregate shape is invalid")
        return self
