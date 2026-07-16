"""010 来源登记表（I3）：通道二的准入合同——未登记来源任何落库前拒绝。

骨架（T3 转绿）：模型与接口就位，RED 落在行为断言。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .errors import RegistryLoadError, SourceNotRegisteredError


class SourceEntry(BaseModel):
    """一个可信业务源的登记条目（I3）。

    领域约束在模型上（21 号第 3 行/019 领域类型教训）：构造期即不可入，
    loader 只补"定位到条目"的错误语境（第二层，非唯一防线）。
    """

    model_config = ConfigDict(frozen=True)

    source_system: str
    authority_level: int = Field(ge=1, le=6)  # 03 §6.1 数值序，越小越权威
    data_steward: str
    mapping_ref: str  # 映射规则引用（文件名/键）

    @field_validator("source_system", "data_steward", "mapping_ref")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("标识/责任人/映射引用不得为空白（019：空白不成为身份）")
        return v


class SourceRegistry(BaseModel):
    model_config = ConfigDict(frozen=True)

    entries: tuple[SourceEntry, ...] = ()


def load_source_registry(path: Path) -> SourceRegistry:
    """加载来源登记 YAML，fail-fast：重复 source_system / 权威域越界(1..6) /
    缺 data_steward 或 mapping_ref —— 报错并定位到条目（I3）。"""
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), list):
        raise RegistryLoadError(f"{path.name}: 顶层须为 {{sources: [...]}} 结构")
    entries: list[SourceEntry] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw["sources"]):
        where = f"{path.name} sources[{idx}]"
        try:
            entry = SourceEntry.model_validate(item)
        except ValidationError as exc:
            raise RegistryLoadError(f"{where}: 条目字段缺失/非法——{exc}") from exc
        if not entry.data_steward.strip() or not entry.mapping_ref.strip():
            raise RegistryLoadError(f"{where}: data_steward/mapping_ref 不得为空")
        if not 1 <= entry.authority_level <= 6:
            raise RegistryLoadError(
                f"{where}: authority_level（权威等级）须在 1..6（03 §6.1），"
                f"得到 {entry.authority_level}"
            )
        if entry.source_system in seen:
            raise RegistryLoadError(f"{where}: source_system 重复：{entry.source_system!r}")
        seen.add(entry.source_system)
        entries.append(entry)
    return SourceRegistry(entries=tuple(entries))


def resolve_source(registry: SourceRegistry, source_system: str) -> SourceEntry:
    """解析来源；未登记 → SourceNotRegisteredError（I1 fail-closed）。"""
    entry = next(
        (e for e in registry.entries if e.source_system == source_system), None
    )
    if entry is None:
        raise SourceNotRegisteredError(f"来源未登记：{source_system!r}（I1/I3）")
    return entry
