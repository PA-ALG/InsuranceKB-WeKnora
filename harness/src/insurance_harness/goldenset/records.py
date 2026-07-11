"""金标记录模型（spec G2.1）。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

TriState = Literal["present", "absent_explicitly", "unknown"]

DisputedReason = Literal[
    "parse_failed",  # 模型输出无法解析（重试后仍失败）
    "missing_in_response",  # 模型未返回请求的字段
    "quote_mismatch",  # 引文回验失败（G2.2）
    "no_evidence",  # present/absent_explicitly 但无证据（G2.2/G2.3）
    "meta_mismatch",  # 与 product_meta.json 不一致（G2.4）
]


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    page: int  # 1-based 页码
    quote: str


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
