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
    loader 只补"定位到条目"的错误语境（第二层，非唯一防线）。extra="forbid"：
    拼错的键（如 recrod_schema_ref）fail-fast，不静默丢弃（阻断6）。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_system: str
    authority_level: int = Field(ge=1, le=6)  # 03 §6.1 数值序，越小越权威
    data_steward: str
    mapping_ref: str  # 映射规则引用（文件名/键）
    record_schema_ref: str  # 记录 schema 引用（I3 明列：来源须声明记录 schema）

    @field_validator("source_system", "data_steward", "mapping_ref", "record_schema_ref")
    @classmethod
    def _norm_identity(cls, v: str) -> str:
        # 去首尾空白**并返回规范化值**：身份在比较点已归一，避免 " a " 登记后以
        # "a" resolve 落空（阻断6a / 21 号"构造期校验器要在比较点二次规范化"）。
        s = v.strip()
        if not s:
            raise ValueError("标识/责任人/引用不得为空白（019：空白不成为身份）")
        return s


class SourceRegistry(BaseModel):
    model_config = ConfigDict(frozen=True)

    entries: tuple[SourceEntry, ...] = ()


def load_source_registry(path: Path) -> SourceRegistry:
    """加载来源登记 YAML，fail-fast：未知顶层键 / 条目字段缺失或拼错（extra=forbid）/
    权威域越界(1..6) / 规范化后 source_system 重复 —— 报错并定位到条目（I3/阻断6）。"""
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), list):
        raise RegistryLoadError(f"{path.name}: 顶层须为 {{sources: [...]}} 结构")
    if set(raw) - {"sources"}:  # 顶层严格：未知键 fail-fast，不手工抽取已知键
        raise RegistryLoadError(f"{path.name}: 未知顶层键 {sorted(set(raw) - {'sources'})}")
    entries: list[SourceEntry] = []
    seen: set[str] = set()  # 规范化(strip 后)身份去重
    for idx, item in enumerate(raw["sources"]):
        where = f"{path.name} sources[{idx}]"
        try:
            entry = SourceEntry.model_validate(item)  # 域约束+extra=forbid+身份规范化
        except ValidationError as exc:
            raise RegistryLoadError(f"{where}: 条目字段缺失/非法——{exc}") from exc
        if entry.source_system in seen:  # 比较点用已规范化身份
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
