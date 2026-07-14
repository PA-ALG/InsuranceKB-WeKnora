"""金标记录模型（spec G2.1）。"""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

TriState = Literal["present", "absent_explicitly", "unknown"]

DisputedReason = Literal[
    "parse_failed",  # 模型输出无法解析（重试后仍失败）
    "missing_in_response",  # 模型未返回请求的字段
    "quote_mismatch",  # 引文回验失败（G2.2）
    "no_evidence",  # present/absent_explicitly 但无证据（G2.2/G2.3）
    "meta_mismatch",  # 与 product_meta.json 不一致（G2.4）
]

_SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
_MD5_OR_SHA256_HEX = re.compile(r"^(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{64})$")


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    page: int  # 1-based 页码
    quote: str
    # 017 source-aware audit. Optional defaults preserve historical Golden/replay rows.
    knowledge_id: str | None = None
    raw_kb_id: str | None = None
    source_revision: str | None = None
    file_hash: str | None = None
    original_digest: str | None = None
    parser_version: str | None = None
    chunk_id: str | None = None
    chunk_hash: str | None = None
    lineage_status: Literal["linked", "page_only", "ambiguous"] | None = None

    @model_validator(mode="after")
    def _validate_lineage_audit(self) -> "Evidence":
        audit_values = (
            self.knowledge_id,
            self.raw_kb_id,
            self.source_revision,
            self.file_hash,
            self.original_digest,
            self.parser_version,
            self.chunk_id,
            self.chunk_hash,
        )
        if self.lineage_status is None:
            if any(value is not None for value in audit_values):
                raise ValueError("lineage status is required for source audit")
            return self

        complete_source_audit = (
            self.source_revision,
            self.file_hash,
            self.original_digest,
            self.parser_version,
        )
        if any(value is None for value in complete_source_audit):
            raise ValueError("lineage source audit must be complete")
        assert self.source_revision is not None
        assert self.file_hash is not None
        assert self.original_digest is not None
        assert self.parser_version is not None
        if _SHA256_HEX.fullmatch(self.source_revision) is None:
            raise ValueError("lineage source_revision must be a SHA-256 hex digest")
        if _MD5_OR_SHA256_HEX.fullmatch(self.file_hash) is None:
            raise ValueError("lineage file_hash must be an MD5 or SHA-256 hex digest")
        if _SHA256_HEX.fullmatch(self.original_digest) is None:
            raise ValueError("lineage original_digest must be a SHA-256 hex digest")
        if not self.parser_version.strip():
            raise ValueError("lineage parser_version must not be empty")

        if (self.knowledge_id is None) != (self.raw_kb_id is None):
            raise ValueError("lineage knowledge_id and raw_kb_id must be paired")
        scoped = self.knowledge_id is not None
        if scoped:
            assert self.knowledge_id is not None
            assert self.raw_kb_id is not None
            if not self.knowledge_id.strip() or not self.raw_kb_id.strip():
                raise ValueError("lineage source identity must not be empty")

        if self.lineage_status == "linked":
            if not scoped:
                raise ValueError("linked lineage requires complete document identity")
            if (
                self.chunk_id is None
                or not self.chunk_id.strip()
                or self.chunk_hash is None
                or _SHA256_HEX.fullmatch(self.chunk_hash) is None
            ):
                raise ValueError("linked lineage requires chunk id and SHA-256 hash")
        elif self.chunk_id is not None or self.chunk_hash is not None:
            raise ValueError("non-linked lineage cannot carry a chunk")
        return self


class GoldenRecord(BaseModel):
    product_id: str
    product_name: str
    doc: str  # 文档文件名，如 保险条款.pdf
    field_id: str
    field_name: str
    value: str | None
    tri_state: TriState
    evidence: list[Evidence] = []
    disputed: bool = False
    disputed_reason: DisputedReason | None = None
    reasoning: str | None = None
    annotator_model: str
    schema_version: str
    created_at: datetime
