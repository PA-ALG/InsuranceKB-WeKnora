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
from .transformers import (
    NORMALIZER_VERSION,
    TRANSFORMER_REGISTRY_VERSION,
    TRANSFORMERS,
)

#: 候选映射草案目录名（I2：草案未经人工确认不得用于正式导入）。
DRAFTS_DIRNAME = "mapping-drafts"


class MappingRule(BaseModel):
    # extra="forbid"：拼错的键（如 transformre）必须 fail-fast，不得静默丢弃后
    # 悄悄回落到默认 identity 变换器（阻断6：配置驱动导入里 typo→默认转换是高风险）。
    model_config = ConfigDict(frozen=True, extra="forbid")

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
    basis: str = Field(min_length=1)  # 命中依据（exact/alias/contains）


class DraftAmbiguity(BaseModel):
    """同分多 field_id：不臆断决胜，显式记录候选交人工（阻断4）。"""

    model_config = ConfigDict(frozen=True)

    source_field: str = Field(min_length=1)
    candidates: tuple[str, ...]  # 并列最高分的 field_id（已排序，≥2）
    confidence: float = Field(ge=0.0, le=1.0)
    basis: str = Field(min_length=1)


class MappingDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    confirmed: bool = False
    rules: tuple[DraftRule, ...] = ()
    #: 歧义清单：字段名同分命中 ≥2 个不同 field_id 时落此，**不**产单一规则
    #: （阻断4：稳定地选错仍是错，且人工只看到单一高置信候选无从知情）。
    ambiguities: tuple[DraftAmbiguity, ...] = ()


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


def _match_field(
    key: str, fields: tuple[FieldSpec, ...]
) -> tuple[DraftRule | None, DraftAmbiguity | None]:
    """确定性单键匹配：exact 名/别名（不区分大小写）> 包含关系；仅字段名启发式。

    返回 ``(rule, ambiguity)``——最高分**唯一** field_id ⇒ 产 rule；最高分对应
    **≥2 个不同** field_id ⇒ 产 ambiguity 不产 rule（阻断4：不臆断决胜）；无命中 ⇒ 皆 None。
    """
    key_l = key.lower()
    hits: list[tuple[str, float, str]] = []  # (field_id, confidence, basis)
    for f in fields:
        names = {f.name.lower(), *(a.lower() for a in f.aliases)}
        if key_l in names:
            hits.append((f.field_id, 0.9, f"alias:{key}→{f.name}"))
        elif any(n and (n in key_l or key_l in n) for n in names):
            hits.append((f.field_id, 0.6, f"contains:{key}~{f.name}"))
    if not hits:
        return None, None
    top = max(h[1] for h in hits)
    top_ids = sorted({fid for fid, conf, _ in hits if conf == top})
    if len(top_ids) == 1:
        fid = top_ids[0]
        basis = next(b for f2, c, b in sorted(hits) if f2 == fid and c == top)
        return DraftRule(source_field=key, field_id=fid, confidence=top, basis=basis), None
    return None, DraftAmbiguity(
        source_field=key, candidates=tuple(top_ids), confidence=top,
        basis=f"同分歧义（{top}）：{top_ids}",
    )


def propose_mapping_draft(
    record: dict[str, Any],
    schema_registry: SchemaRegistry,
    *,
    line_key: str | None = None,
) -> MappingDraft:
    """对未知 JSON 结构生成候选映射草案（确定性：仅字段名启发式，I2）。

    ``line_key`` 指定目标产品线 ⇒ 候选限定到该线，消解跨线同名假歧义（阻断4）；
    不给则展平全部线。产物 ``confirmed=False``——落 ``mapping-drafts/`` 供人工确认；
    同名同分命中多个 field_id 时落 ``ambiguities`` 而非任选其一；未确认不得导入。
    """
    if line_key is not None:
        fields = tuple(schema_registry.line(line_key).fields)  # 未知线 → KeyError fail-fast
    else:
        fields = tuple(f for line in schema_registry.lines.values() for f in line.fields)
    rules: list[DraftRule] = []
    ambiguities: list[DraftAmbiguity] = []
    for key in sorted(record):  # 键排序保证确定性
        rule, amb = _match_field(key, fields)
        if rule is not None:
            rules.append(rule)
        elif amb is not None:
            ambiguities.append(amb)
    return MappingDraft(
        confirmed=False, rules=tuple(rules), ambiguities=tuple(ambiguities)
    )


def mapping_manifest(
    spec: MappingSpec, schema_registry: SchemaRegistry
) -> dict[str, Any]:
    """I4 manifest 四元组：{parsed_mapping, transformer/normalizer/schema 版本}。

    转换/规范化版本从**权威模块常量**读取、schema 版本从传入的 SchemaRegistry 读取
    ——调用方**不得**自由传版本字符串（阻断5：否则可对同一 parsed_mapping 伪造/传入
    陈旧 provenance，令 effective_mapping_version 与真实行为脱钩）。行为变更须 bump
    transformers.TRANSFORMER_REGISTRY_VERSION / NORMALIZER_VERSION（spec I4 纪律）。
    """
    return {
        "parsed_mapping": spec.model_dump(mode="json"),
        "transformer_registry_version": TRANSFORMER_REGISTRY_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "target_schema_version": schema_registry.version,
    }


def effective_mapping_version(manifest: dict[str, Any]) -> str:
    """SHA-256(canonical(manifest))：sorted-key、minified、UTF-8（I4——注释/键序无关）。"""
    canonical = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
