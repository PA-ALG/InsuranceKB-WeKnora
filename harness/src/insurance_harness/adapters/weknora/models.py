"""WeKnora REST 响应的模型对象。

只声明我们消费的字段；``extra="allow"`` 宽容解析，降低上游小版本变化的破坏面
（设计 001 §2）。字段名与上游 JSON 对齐（internal/types 已核实）。
"""

import re
from pathlib import Path
from typing import Any

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

StrictIdentity = StrictStr | StrictInt
_MD5_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_KNOWLEDGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def normalize_safe_knowledge_id(value: object) -> str | None:
    """Normalize an upstream identity only when it is safe as one URL segment."""
    if isinstance(value, str):
        normalized = value
    elif type(value) is int and value >= 0:
        normalized = str(value)
    else:
        return None
    if _KNOWLEDGE_ID_RE.fullmatch(normalized) is None:
        return None
    return normalized


def is_safe_knowledge_id(value: object) -> bool:
    """Return whether an ID has a safe canonical WeKnora path representation."""
    return normalize_safe_knowledge_id(value) is not None


class _LenientModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class WeKnoraKnowledge(_LenientModel):
    id: StrictIdentity
    tenant_id: StrictIdentity | None = None
    knowledge_base_id: StrictIdentity | None = None
    title: str = ""
    file_name: str = ""
    file_type: str = ""
    file_size: StrictInt | None = None
    file_hash: StrictStr = ""
    processed_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    parse_status: str = ""
    error_message: str = ""

    @field_validator("file_size")
    @classmethod
    def _non_negative_file_size(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("file_size must be non-negative")
        return value

    @field_validator("file_hash")
    @classmethod
    def _valid_file_hash(cls, value: str) -> str:
        if value and _MD5_RE.fullmatch(value) is None:
            raise ValueError("file_hash must be a 32-character MD5 hex digest")
        return value.lower()


class WeKnoraChunk(_LenientModel):
    id: StrictIdentity
    tenant_id: StrictIdentity | None = None
    knowledge_id: StrictIdentity | None = None
    knowledge_base_id: StrictIdentity | None = None
    content: str = ""
    chunk_index: StrictInt | None = None
    start_at: StrictInt | None = None
    end_at: StrictInt | None = None
    metadata: dict[str, Any] | None = None
    content_hash: str = ""

    @field_validator("chunk_index", "start_at", "end_at")
    @classmethod
    def _non_negative_offsets(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("chunk offsets must be non-negative")
        return value

    @model_validator(mode="after")
    def _ordered_offsets(self) -> "WeKnoraChunk":
        if (
            self.start_at is not None
            and self.end_at is not None
            and self.start_at > self.end_at
        ):
            raise ValueError("start_at must not exceed end_at")
        return self


class DownloadedKnowledge(BaseModel):
    """已校验原件的运行时描述；path 仅在 client context 内有效。"""

    model_config = ConfigDict(frozen=True)

    path: Path
    byte_count: int
    upstream_md5: str
    original_digest: str


class WeKnoraWikiPage(_LenientModel):
    id: str = ""
    knowledge_base_id: str = ""
    slug: str
    title: str = ""
    page_type: str = ""
    status: str = ""
    content: str = ""
    summary: str = ""
    aliases: list[str] = Field(default_factory=list)
    parent_slug: str = ""
    folder_id: str = ""
    category_path: list[str] = Field(default_factory=list)
    wiki_path: str = ""
    source_refs: list[str] = Field(default_factory=list)
    chunk_refs: list[str] = Field(default_factory=list)
    in_links: list[str] = Field(default_factory=list)
    out_links: list[str] = Field(default_factory=list)
    page_metadata: dict[str, Any] | None = None
    version: int = 1

    @field_validator("in_links", "out_links", mode="before")
    @classmethod
    def normalize_null_links(cls, value: object) -> object:
        """WeKnora serializes an empty link relation as either null or []."""
        return [] if value is None else value


class WeKnoraWikiFolder(_LenientModel):
    id: str = ""
    knowledge_base_id: str = ""
    parent_id: str = ""
    name: str
