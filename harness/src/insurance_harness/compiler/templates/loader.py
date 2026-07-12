"""模板注册表加载器（006 T4；spec F1.2/F1.3；机制对齐 schemas/loader.py G1）。

数据源：`dataset/templates/` 下的模板 YAML（一文件一模板，归纳产出 + 人工审核后发布）。
加载期任何结构问题 fail fast 并指明文件/字段（F1.2）。
"""

import hashlib
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import ValidationError

from .models import ExtractionTemplate, TemplateRegistry

SEMANTIC_VERSION = "tpl-v1"


class TemplateLoadError(Exception):
    """模板加载失败：消息中必须包含文件与字段定位（F1.2）。"""


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TemplateLoadError(f"{path.name}: YAML 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise TemplateLoadError(
            f"{path.name}: 顶层结构应为 mapping，实为 {type(data).__name__}"
        )
    return cast(dict[str, Any], data)


def parse_template(data: dict[str, Any], source: str) -> ExtractionTemplate:
    """单个模板 mapping → 模型（含 pydantic 校验与追加约束；F1.2）。"""
    try:
        template = ExtractionTemplate.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        raise TemplateLoadError(f"{source}: 字段 {loc}: {first['msg']}") from exc
    seen: set[str] = set()
    for f in template.fields:
        if f.field_id in seen:
            raise TemplateLoadError(f"{source}: field_id {f.field_id!r} 重复")
        seen.add(f.field_id)
        a = f.anchors
        if a.table_columns is None and a.regex is None:
            raise TemplateLoadError(
                f"{source}: 字段 {f.field_id!r} 无可执行锚点（table_columns/regex 至少其一）"
            )
        if a.table_columns is not None and a.table_columns.op == "cell" and (
            a.table_columns.row_label is None or a.table_columns.column is None
        ):
            raise TemplateLoadError(
                f"{source}: 字段 {f.field_id!r} 的 table_columns op=cell "
                f"必须给出 row_label 与 column"
            )
    if not template.doc.endswith(".pdf"):
        raise TemplateLoadError(f"{source}: doc 应为 PDF 文件名，实得 {template.doc!r}")
    return template


def load_template_registry(templates_dir: Path | None) -> TemplateRegistry:
    """加载目录下全部模板 YAML；空/缺目录 → 空注册表（fast path 整体旁路，F1.3）。"""
    if templates_dir is None or not templates_dir.is_dir():
        return TemplateRegistry(version=f"{SEMANTIC_VERSION}+empty", templates=())
    yaml_paths = sorted(templates_dir.glob("*.yaml"))
    if not yaml_paths:
        return TemplateRegistry(version=f"{SEMANTIC_VERSION}+empty", templates=())

    content_hash = hashlib.sha256()
    templates: list[ExtractionTemplate] = []
    ids: set[str] = set()
    for path in yaml_paths:
        content_hash.update(path.name.encode("utf-8"))
        content_hash.update(path.read_bytes())
        template = parse_template(_load_yaml(path), path.name)
        if template.template_id in ids:
            raise TemplateLoadError(f"{path.name}: template_id {template.template_id!r} 重复")
        ids.add(template.template_id)
        templates.append(template)
    return TemplateRegistry(
        version=f"{SEMANTIC_VERSION}+{content_hash.hexdigest()[:12]}",
        templates=tuple(templates),
    )


def dump_template_yaml(template: ExtractionTemplate) -> str:
    """模板 → YAML 文本（归纳器落盘草案用；F2.4 自产自验由 parse_template 保证）。"""
    data = template.model_dump(mode="json")
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
