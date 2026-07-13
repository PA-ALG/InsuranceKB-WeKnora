"""Schema 注册表运行时模型（spec G1；口径见 docs/insurance-kb/07 §1-§2）。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

ValueType = Literal["short", "long", "enum", "number", "date", "table"]
RiskLevel = Literal["low", "medium", "high"]


class FieldSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    field_id: str
    value_type: ValueType = "short"
    extractable: bool = True
    allowed_sources: tuple[str, ...] = ()
    risk_level: RiskLevel = "low"
    aliases: tuple[str, ...] = ()
    evidence_required: bool = False
    description: str = ""
    source_sheet: str = ""


class GlossaryTerm(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    definition: str


class ProductLineSchema(BaseModel):
    """一个险种的完整字段集 = 基础字段 + 险种字段 + 已确认扩展（v1.1）。"""

    model_config = ConfigDict(frozen=True)

    line_key: str  # 文件 stem，如 critical-illness
    sheet_name: str  # 原 Excel sheet 名，如 疾病保险（重疾险）
    fields: tuple[FieldSpec, ...]

    def field_by_id(self, field_id: str) -> FieldSpec:
        for f in self.fields:
            if f.field_id == field_id:
                return f
        raise KeyError(f"字段 {field_id!r} 不在险种 {self.line_key} 的 schema 中")

    @property
    def extractable_fields(self) -> tuple[FieldSpec, ...]:
        return tuple(f for f in self.fields if f.extractable)


class SchemaRegistry(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str  # 形如 "v1.1+3f2a9c1b04de"（语义版本 + 内容 hash 前 12 位，G1.3）
    lines: dict[str, ProductLineSchema]
    glossary: tuple[GlossaryTerm, ...]

    def line(self, line_key: str) -> ProductLineSchema:
        if line_key not in self.lines:
            raise KeyError(
                f"未知险种 {line_key!r}；可用：{sorted(self.lines)}"
            )
        return self.lines[line_key]

    def risk_level_of(self, field_id: str) -> RiskLevel:
        for line in self.lines.values():
            for f in line.fields:
                if f.field_id == field_id:
                    return f.risk_level
        return "low"
