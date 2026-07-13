"""WeKnora REST 响应的模型对象。

只声明我们消费的字段；``extra="allow"`` 宽容解析，降低上游小版本变化的破坏面
（设计 001 §2）。字段名与上游 JSON 对齐（internal/types 已核实）。
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _LenientModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class WeKnoraKnowledge(_LenientModel):
    id: str
    knowledge_base_id: str = ""
    title: str = ""
    parse_status: str = ""
    error_message: str = ""


class WeKnoraChunk(_LenientModel):
    id: str
    knowledge_id: str = ""
    knowledge_base_id: str = ""
    content: str = ""
    chunk_index: int | None = None


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


class WeKnoraWikiFolder(_LenientModel):
    id: str = ""
    knowledge_base_id: str = ""
    parent_id: str = ""
    name: str
