"""Schema 注册表加载器（spec G1）。

数据源：docs/insurance-kb/schema-baseline/ 下的基线 YAML（业务方 Excel 逐字段转换）
与 extensions-v1.1.yaml（业务方 2026-07-11 确认的 18 条扩展）。
加载期任何结构问题都 fail fast 并指明文件/字段（G1.2）。
"""

import hashlib
import re
from pathlib import Path
from typing import Any, cast

import yaml

from .models import (
    FieldSpec,
    GlossaryTerm,
    ProductLineSchema,
    Requiredness,
    RiskLevel,
    SchemaRegistry,
    ValueType,
)

SEMANTIC_VERSION = "v1.1"
_GLOSSARY_STEM = "glossary"
_EXTENSIONS_STEM = "extensions-v1.1"
_BASE_STEM = "base"

# extensions-v1.1.yaml 险种级 key → 基线文件 stem（一对多允许）
_EXTENSION_LINE_MAP: dict[str, tuple[str, ...]] = {
    "疾病保险（重疾险）": ("critical-illness",),
    "护理保险（新）": ("long-term-care",),
    "失能收入损失保险（新）": ("disability-income",),
    "医疗保险（医疗险）": ("medical",),
    "意外伤害保险（意外险）": ("accident",),
    "年金保险（年金险）与补充养老保险（新）": ("annuity", "supplementary-pension"),
    # 分红型跨险种：并入所有可能为分红型的长期储蓄型险种
    "分红型产品（跨险种）": (
        "whole-life",
        "term-life",
        "annuity",
        "endowment",
        "supplementary-pension",
    ),
}

# 取值来源含以下标记 → 不可从文档抽取（07 §2 extractable 映射规则）
_NON_EXTRACTABLE_MARKERS = ("人工填充", "人工填写", "官网同步")


class SchemaLoadError(Exception):
    """schema 基线加载失败：消息中必须包含文件与字段定位（G1.2）。"""


def _slugify_english(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug


def stable_field_id(cn_name: str, en_name: str = "") -> str:
    """确定性 field_id：英文名可用则 slug 化，否则以中文名 hash 生成稳定占位 id。

    占位 id 不可读但稳定；正式英文名补齐后由 schema 升版统一替换（07 §2）。
    """
    if en_name and _slugify_english(en_name):
        return _slugify_english(en_name)
    digest = hashlib.sha256(cn_name.strip().encode("utf-8")).hexdigest()[:10]
    return f"zh_{digest}"


def _as_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _parse_sources(raw: str) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(p for p in re.split(r"[/、，,]", raw) if p)


def _parse_requiredness(row: dict[str, Any], *, file: str, name: str) -> "Requiredness":
    """『必填』/requiredness 列（可选）：必填/required/是→required；可选/optional/否
    →optional；expected/期望→expected。**键缺失/显式空白才默认 expected**；键存在
    但值不在枚举 → 带定位抛 SchemaLoadError（fail-fast，codex R2 P2：拼写错误不得
    静默放大补漏人群与成本）。"""
    raw = _as_str(row.get("requiredness")) or _as_str(row.get("必填"))
    if not raw:
        return "expected"
    if raw in ("required", "必填", "是"):
        return "required"
    if raw in ("optional", "可选", "否"):
        return "optional"
    if raw in ("expected", "期望"):
        return "expected"
    raise SchemaLoadError(
        f"{file}: 字段 {name!r} 的 requiredness/必填 值不合法：{raw!r}"
        "（合法：required/必填/是、expected/期望、optional/可选/否）"
    )


def _field_from_baseline(row: dict[str, Any], sheet: str, file: str) -> FieldSpec:
    name = _as_str(row.get("字段名"))
    if not name:
        raise SchemaLoadError(f"{file}: 存在缺少『字段名』的行：{row!r}")
    sources_raw = _as_str(row.get("取值来源"))
    extractable = not any(m in sources_raw for m in _NON_EXTRACTABLE_MARKERS)
    return FieldSpec(
        name=name,
        field_id=stable_field_id(name, _as_str(row.get("英文名"))),
        extractable=extractable,
        allowed_sources=_parse_sources(sources_raw),
        requiredness=_parse_requiredness(row, file=file, name=name),
        description=_as_str(row.get("说明")) or _as_str(row.get("取值")),
        source_sheet=sheet,
    )


def _field_from_extension(row: dict[str, Any], file: str) -> FieldSpec:
    name = _as_str(row.get("字段名"))
    if not name:
        raise SchemaLoadError(f"{file}: 扩展字段缺少『字段名』：{row!r}")
    field_id = _as_str(row.get("field_id"))
    if not field_id:
        raise SchemaLoadError(f"{file}: 扩展字段 {name!r} 缺少 field_id")
    sources_raw = _as_str(row.get("取值来源"))
    raw_extractable = row.get("extractable")
    extractable = (
        bool(raw_extractable)
        if raw_extractable is not None
        else not any(m in sources_raw for m in _NON_EXTRACTABLE_MARKERS)
    )
    risk = cast(RiskLevel, _as_str(row.get("risk_level")) or "low")
    value_type = cast(ValueType, _as_str(row.get("value_type")) or "short")
    return FieldSpec(
        name=name,
        field_id=field_id,
        value_type=value_type,
        extractable=extractable,
        allowed_sources=_parse_sources(sources_raw),
        risk_level=risk,
        evidence_required=risk == "high",
        requiredness=_parse_requiredness(row, file=file, name=name),
        description=_as_str(row.get("说明")),
        source_sheet="extensions-v1.1",
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - 格式损坏罕见
        raise SchemaLoadError(f"{path.name}: YAML 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise SchemaLoadError(f"{path.name}: 顶层结构应为 mapping，实为 {type(data).__name__}")
    return cast(dict[str, Any], data)


def _baseline_fields(path: Path) -> tuple[str, list[FieldSpec]]:
    data = _load_yaml(path)
    sheet = _as_str(data.get("sheet")) or path.stem
    rows = data.get("fields")
    if not isinstance(rows, list):
        raise SchemaLoadError(f"{path.name}: 缺少 fields 列表")
    return sheet, [_field_from_baseline(cast(dict[str, Any], r), sheet, path.name) for r in rows]


def _check_duplicates(line_key: str, fields: list[FieldSpec]) -> None:
    names: set[str] = set()
    ids: set[str] = set()
    for f in fields:
        if f.name in names:
            raise SchemaLoadError(
                f"险种 {line_key}: 字段名 {f.name!r} 重复（来源 {f.source_sheet}）"
            )
        if f.field_id in ids:
            raise SchemaLoadError(
                f"险种 {line_key}: field_id {f.field_id!r} 重复"
                f"（字段 {f.name!r}，来源 {f.source_sheet}）"
            )
        names.add(f.name)
        ids.add(f.field_id)


def load_schema_registry(baseline_dir: Path) -> SchemaRegistry:
    """加载全部基线 + 扩展，返回运行时注册表（G1.1/G1.3）。"""
    if not baseline_dir.is_dir():
        raise SchemaLoadError(f"schema 基线目录不存在：{baseline_dir}")
    yaml_paths = sorted(baseline_dir.glob("*.yaml"))
    if not yaml_paths:
        raise SchemaLoadError(f"{baseline_dir} 下没有任何 YAML")

    content_hash = hashlib.sha256()
    for p in yaml_paths:
        content_hash.update(p.name.encode("utf-8"))
        content_hash.update(p.read_bytes())
    version = f"{SEMANTIC_VERSION}+{content_hash.hexdigest()[:12]}"

    base_fields: list[FieldSpec] = []
    line_fields: dict[str, tuple[str, list[FieldSpec]]] = {}
    glossary: list[GlossaryTerm] = []
    extensions_path: Path | None = None

    for path in yaml_paths:
        stem = path.stem
        if stem == _EXTENSIONS_STEM:
            extensions_path = path
            continue
        if stem == _GLOSSARY_STEM:
            data = _load_yaml(path)
            for row in data.get("fields") or []:
                r = cast(dict[str, Any], row)
                glossary.append(
                    GlossaryTerm(
                        name=_as_str(r.get("字段名")),
                        definition=_as_str(r.get("取值")) or _as_str(r.get("英文名")),
                    )
                )
            continue
        sheet, fields = _baseline_fields(path)
        if stem == _BASE_STEM:
            base_fields = fields
        else:
            line_fields[stem] = (sheet, fields)

    if not base_fields:
        raise SchemaLoadError("缺少 base.yaml（基础字段）")

    base_extensions: list[FieldSpec] = []
    line_extensions: dict[str, list[FieldSpec]] = {}
    if extensions_path is not None:
        ext = _load_yaml(extensions_path)
        ext_file = extensions_path.name
        for row in ext.get("基础字段扩展") or []:
            base_extensions.append(_field_from_extension(cast(dict[str, Any], row), ext_file))
        line_ext_raw = ext.get("险种级扩展") or {}
        if not isinstance(line_ext_raw, dict):
            raise SchemaLoadError(f"{extensions_path.name}: 险种级扩展应为 mapping")
        for group, rows in cast(dict[str, Any], line_ext_raw).items():
            targets = _EXTENSION_LINE_MAP.get(str(group))
            if targets is None:
                raise SchemaLoadError(
                    f"{extensions_path.name}: 未知险种级扩展分组 {group!r}——"
                    f"请在 _EXTENSION_LINE_MAP 登记映射"
                )
            specs = [_field_from_extension(cast(dict[str, Any], r), ext_file) for r in rows]
            for t in targets:
                line_extensions.setdefault(t, []).extend(specs)

    lines: dict[str, ProductLineSchema] = {}
    for line_key, (sheet, fields) in line_fields.items():
        merged = [*base_fields, *base_extensions, *fields, *line_extensions.get(line_key, [])]
        _check_duplicates(line_key, merged)
        lines[line_key] = ProductLineSchema(
            line_key=line_key, sheet_name=sheet, fields=tuple(merged)
        )

    unknown_ext = set(line_extensions) - set(lines)
    if unknown_ext:
        raise SchemaLoadError(f"扩展指向不存在的险种文件：{sorted(unknown_ext)}")

    return SchemaRegistry(version=version, lines=lines, glossary=tuple(glossary))
