"""产品级标注编排：险种推断、断点续跑缓存、逐文档标注+自检（spec G2.4/G2.5）。"""

import json
from datetime import UTC, datetime
from pathlib import Path

from ..schemas import SchemaRegistry
from .annotator import GoldenAnnotator
from .pdf import extract_pages
from .records import GoldenRecord
from .verify import compare_with_meta, load_product_meta, verify_quotes

# 产品目录名关键词 → 险种 line_key（顺序即优先级：先匹配更具体的）
_LINE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("失能收入", "disability-income"),
    ("护理保险", "long-term-care"),
    ("意外伤害", "accident"),
    ("意外医疗", "accident-medical"),
    ("长期医疗", "medical"),
    ("医疗保险", "medical"),
    ("重大疾病", "critical-illness"),
    ("重疾", "critical-illness"),
    ("两全保险", "endowment"),
    ("终身寿险", "whole-life"),
    ("定期寿险", "term-life"),
    ("养老年金", "annuity"),
    ("年金保险", "annuity"),
    ("补充养老", "supplementary-pension"),
)


class UnknownProductLineError(Exception):
    """无法从产品名推断险种；正确归属优先于自动化（master plan §1.2），报错交人工。"""


def infer_line_key(product_name: str) -> str:
    for keyword, line_key in _LINE_KEYWORDS:
        if keyword in product_name:
            return line_key
    raise UnknownProductLineError(
        f"无法从产品名推断险种：{product_name!r}——请在 _LINE_KEYWORDS 登记或人工指定"
    )


def _cache_path(cache_dir: Path, product: str, doc: str, schema_version: str) -> Path:
    schema_hash = schema_version.split("+")[-1]
    return cache_dir / product / f"{doc}.{schema_hash}.jsonl"


def _read_cache(path: Path) -> list[GoldenRecord]:
    return [
        GoldenRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_cache(path: Path, records: list[GoldenRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(r.model_dump_json() for r in records) + "\n", encoding="utf-8"
    )


async def annotate_product(
    product_dir: Path,
    registry: SchemaRegistry,
    annotator: GoldenAnnotator,
    cache_dir: Path,
    line_key: str | None = None,
) -> list[GoldenRecord]:
    """标注一个产品目录（PDF×N + product_meta），带断点续跑缓存。"""
    product_name = product_dir.name
    meta = load_product_meta(product_dir)
    product_id = str(meta.get("planCode") or product_name).strip()
    line = registry.line(line_key or infer_line_key(product_name))

    all_records: list[GoldenRecord] = []
    for pdf_path in sorted(product_dir.glob("*.pdf")):
        cache = _cache_path(cache_dir, product_name, pdf_path.name, registry.version)
        if cache.exists():  # G2.5：schema 版本未变则跳过
            all_records.extend(_read_cache(cache))
            continue
        pages = extract_pages(pdf_path)
        records = await annotator.annotate_document(
            product_id=product_id,
            product_name=product_name,
            doc_name=pdf_path.name,
            pages=pages,
            line=line,
            created_at=datetime.now(UTC),
        )
        verify_quotes(records, pages)
        compare_with_meta(records, meta)
        _write_cache(cache, records)
        all_records.extend(records)
    return all_records


def write_jsonl(records: list[GoldenRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(r.model_dump_json() for r in records) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[GoldenRecord]:
    return [
        GoldenRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_release(release_dir: Path) -> list[GoldenRecord]:
    """读一个金标 release 目录的全部记录（不含 disputed.jsonl，那是复核清单副本）。"""
    records: list[GoldenRecord] = []
    for p in sorted(release_dir.glob("*.jsonl")):
        if p.name == "disputed.jsonl":
            continue
        records.extend(read_jsonl(p))
    if not records:
        raise FileNotFoundError(f"{release_dir} 中没有金标记录")
    return records


def _json_default(obj: object) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"无法序列化 {type(obj).__name__}")


def dump_json(data: object, path: Path) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
