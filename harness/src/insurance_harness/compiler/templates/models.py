"""模板 schema 运行时模型（006 T4；spec F1；设计 11 §1.2——模板是数据不是代码）。

模板 = YAML 数据（字段→锚点），归纳产出（F2）、人工只审核；运行时按
(family_id, doc) 命中 published 模板走 fast path（F3）。
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

TemplateStatus = Literal["draft", "published"]
TableOp = Literal["join_headers", "cell"]

_FAMILY_ID_RE = re.compile(r"^fam-[0-9a-f]{12}$")


class TableAnchor(BaseModel):
    """表格列名锚点（12 #1）：join_headers=列名枚举直取；cell=数字列定位直取。"""

    model_config = ConfigDict(frozen=True)

    op: TableOp = "join_headers"
    header_contains: str  # 表头行识别特征（该行含此列名）
    join: str = "、"  # op=join_headers 的列名连接符
    row_label: str | None = None  # op=cell 的行键（如投保年龄）
    column: str | None = None  # op=cell 的列名（如 3年）


class FieldAnchors(BaseModel):
    """字段锚点集合：章节标题模式 / 页位置 / 表格列名 / 正则（F1.1 四类）。"""

    model_config = ConfigDict(frozen=True)

    section_title: str | None = None  # 章节标题模式（正则）
    pages: tuple[int, ...] = ()  # 页位置提示（±1 容忍解析分页差）
    table_columns: TableAnchor | None = None
    regex: str | None = None  # 恰含一个捕获组的正则

    @field_validator("regex")
    @classmethod
    def _regex_one_group(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            compiled = re.compile(v)
        except re.error as exc:
            raise ValueError(f"regex 锚点编译失败：{exc}") from exc
        if compiled.groups != 1:
            raise ValueError(f"regex 锚点必须恰含 1 个捕获组，实得 {compiled.groups}")
        return v

    @field_validator("section_title")
    @classmethod
    def _section_title_compiles(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                re.compile(v)
            except re.error as exc:
                raise ValueError(f"section_title 模式编译失败：{exc}") from exc
        return v


class FewShot(BaseModel):
    """金标真实示例（11 §1.2 few_shots 来自金标副产品；LLM 润色/审核参考用）。"""

    model_config = ConfigDict(frozen=True)

    product: str
    page: int
    quote: str
    value: str


class TemplateField(BaseModel):
    model_config = ConfigDict(frozen=True)

    field_id: str
    field_name: str
    anchors: FieldAnchors
    few_shots: tuple[FewShot, ...] = ()


class InducedFrom(BaseModel):
    """归纳来源留痕（可追溯：模板 ← 金标产品，10 §5 质量清单）。"""

    model_config = ConfigDict(frozen=True)

    products: tuple[str, ...] = ()
    golden_release: str = ""


class ExtractionTemplate(BaseModel):
    model_config = ConfigDict(frozen=True)

    template_id: str
    family_id: str
    doc: str  # 文档文件名（如 费率表.pdf）
    template_version: str = "v1"
    status: TemplateStatus = "draft"
    induced_from: InducedFrom = InducedFrom()
    fields: tuple[TemplateField, ...] = ()

    @field_validator("family_id")
    @classmethod
    def _family_id_format(cls, v: str) -> str:
        if not _FAMILY_ID_RE.match(v):
            raise ValueError(f"family_id 格式非法：{v!r}（应为 fam-<12位十六进制>）")
        return v


class TemplateRegistry(BaseModel):
    """模板注册表（F1.3）：机制对齐 schemas 注册表（版本 = 语义版本+内容 hash）。"""

    model_config = ConfigDict(frozen=True)

    version: str
    templates: tuple[ExtractionTemplate, ...] = ()

    def find(self, family_id: str, doc: str) -> ExtractionTemplate | None:
        """运行时命中：只认 status=published 的模板（F1.3）。"""
        for t in self.templates:
            if t.status == "published" and t.family_id == family_id and t.doc == doc:
                return t
        return None
