"""010 映射规则与 manifest（I2/I4）：加载 fail-fast、草案生成、版本化。

骨架（T4 转绿）：接口与类型就位，RED 落在行为断言。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from insurance_harness.schemas import FieldSpec, SchemaRegistry

from .errors import DraftNotConfirmedError, MappingLoadError
from .transformers import TRANSFORMERS

#: 候选映射草案目录名（I2：草案未经人工确认不得用于正式导入）。
DRAFTS_DIRNAME = "mapping-drafts"


class MappingRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_field: str = Field(min_length=1)
    field_id: str = Field(min_length=1)
    transformer: str = "identity"


class MappingSpec(BaseModel):
    """已确认的映射规则集（parsed_mapping，I4 manifest 轴之一）。"""

    model_config = ConfigDict(frozen=True)

    mapping_id: str
    rules: tuple[MappingRule, ...]


class DraftRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_field: str = Field(min_length=1)
    field_id: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)  # 构造期界（019 Rate 教训）
    basis: str = Field(min_length=1)  # 命中依据（exact/alias/contains/type）


class MappingDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    confirmed: bool = False
    rules: tuple[DraftRule, ...] = ()


def _known_field_ids(schema_registry: SchemaRegistry) -> set[str]:
    return {
        f.field_id for line in schema_registry.lines.values() for f in line.fields
    }


def load_mapping(path: Path, schema_registry: SchemaRegistry) -> MappingSpec:
    """加载映射 YAML，fail-fast：未知 field_id / 未知变换器 / 重复 source_field
    —— 报错并定位（I2）；``confirmed`` 非 true（草案/缺省）→ DraftNotConfirmedError。"""
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise MappingLoadError(f"{path.name}: 顶层须为映射对象")
    if raw.get("confirmed") is not True:
        raise DraftNotConfirmedError(
            f"{path.name}: 未确认草案不得用于正式导入（confirmed 必须为 true，I2）"
        )
    rules_raw = raw.get("rules")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise MappingLoadError(f"{path.name}: rules 须为非空列表")
    known = _known_field_ids(schema_registry)
    rules: list[MappingRule] = []
    seen_src: set[str] = set()
    for idx, item in enumerate(rules_raw):
        where = f"{path.name} rules[{idx}]"
        try:
            rule = MappingRule.model_validate(item)
        except ValidationError as exc:
            raise MappingLoadError(f"{where}: 规则字段缺失/非法——{exc}") from exc
        if rule.field_id not in known:
            raise MappingLoadError(
                f"{where}: 未知 field_id {rule.field_id!r}（schema "
                f"{schema_registry.version} 中不存在）"
            )
        if rule.transformer not in TRANSFORMERS:
            raise MappingLoadError(f"{where}: 未知变换器 {rule.transformer!r}")
        if rule.source_field in seen_src:
            raise MappingLoadError(f"{where}: source_field 重复：{rule.source_field!r}")
        seen_src.add(rule.source_field)
        rules.append(rule)
    mapping_id = str(raw.get("mapping_id") or path.stem)
    return MappingSpec(mapping_id=mapping_id, rules=tuple(rules))


def _match_field(key: str, value: Any, fields: tuple[FieldSpec, ...]) -> DraftRule | None:
    """确定性单键匹配：exact 名/别名（不区分大小写）> 包含关系；含命中依据。"""
    key_l = key.lower()
    best: DraftRule | None = None
    for f in sorted(fields, key=lambda x: x.field_id):  # 排序保证确定性
        names = {f.name.lower(), *(a.lower() for a in f.aliases)}
        if key_l in names:
            cand = DraftRule(
                source_field=key, field_id=f.field_id, confidence=0.9,
                basis=f"alias:{key}→{f.name}",
            )
        elif any(n and (n in key_l or key_l in n) for n in names):
            cand = DraftRule(
                source_field=key, field_id=f.field_id, confidence=0.6,
                basis=f"contains:{key}~{f.name}",
            )
        else:
            continue
        if isinstance(value, str):  # 值类型佐证：schema 值域为文本，字符串值加分
            cand = cand.model_copy(update={"confidence": min(cand.confidence + 0.05, 1.0)})
        if best is None or cand.confidence > best.confidence:
            best = cand
    return best


def propose_mapping_draft(
    record: dict[str, Any], schema_registry: SchemaRegistry
) -> MappingDraft:
    """对未知 JSON 结构生成候选映射草案（确定性：字段名相似度+值类型推断，I2）。

    产物 ``confirmed=False``——落 ``mapping-drafts/`` 供人工确认；未确认不得导入。
    """
    fields = tuple(f for line in schema_registry.lines.values() for f in line.fields)
    rules: list[DraftRule] = []
    for key in sorted(record):  # 键排序保证确定性
        hit = _match_field(key, record[key], fields)
        if hit is not None:
            rules.append(hit)
    return MappingDraft(confirmed=False, rules=tuple(rules))


def mapping_manifest(
    spec: MappingSpec,
    *,
    transformer_registry_version: str,
    normalizer_version: str,
    target_schema_version: str,
) -> dict[str, Any]:
    """I4 manifest 四元组：{parsed_mapping, transformer/normalizer/schema 版本}。"""
    return {
        "parsed_mapping": spec.model_dump(mode="json"),
        "transformer_registry_version": transformer_registry_version,
        "normalizer_version": normalizer_version,
        "target_schema_version": target_schema_version,
    }


def effective_mapping_version(manifest: dict[str, Any]) -> str:
    """SHA-256(canonical(manifest))：sorted-key、minified、UTF-8（I4——注释/键序无关）。"""
    canonical = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
