"""可移植的金标 release 汇总器（019 spec Q1.1/Q1.2）。

把 WIP `assemble_release.py` 的开发机脚本逻辑收进可测试模块 + CLI：
- workspace / dataset-root / output / schema-dir 全部显式参数，无开发机绝对路径（Q1.1）；
- per-record 保留 golden.jsonl 各自的 annotator_model/created_at（Q1.2），
  混合标注不被全局常量覆盖；仅当源记录缺省时才用 default_annotator/now 补齐。

真实 13 产品运行由 020 用同一 API 产出 artifacts；本模块只做确定性汇总，供小 fixture 做 TDD。
"""

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from ..schemas import SchemaRegistry, load_schema_registry
from .pdf import extract_pages
from .records import Evidence, GoldenRecord
from .release import build_release
from .runner import dump_json
from .verify import compare_with_meta, load_product_meta, verify_quotes


class ProductPlan(BaseModel):
    """workspace 里一个产品的汇总计划：目录名 + 险种 line_key。"""

    product: str
    line_key: str


class ProductAssembly(BaseModel):
    """单产品汇总结果（进 AssembleReport；未解决项显式保留，不省略）。"""

    product: str
    product_id: str
    records: int
    missing_fields: int
    bad_lines: int
    disputed: int
    annotator_models: list[str]
    status: str = "ok"


class AssembleReport(BaseModel):
    """一次汇总的确定性报告（软件验收用；不代表真实数据运行完成）。"""

    products: list[ProductAssembly]
    total_records: int
    annotator_models: list[str]


def load_product_plans(workspace: Path) -> list[ProductPlan]:
    """从 workspace/manifest.json 读取产品→line_key 计划。"""
    raw = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
    return [
        ProductPlan(product=p["product"], line_key=p["line_key"])
        for p in raw["products"]
    ]


def _record_from_line(
    line: str,
    *,
    product_id: str,
    product_name: str,
    valid_field_ids: set[str],
    field_name_of: dict[str, str],
    default_annotator: str | None,
    default_schema_version: str,
    default_created_at: datetime,
) -> GoldenRecord | None:
    """把一行 WIP JSONL 转 GoldenRecord；无效/不在 schema 内返回 None（计 bad_lines）。"""
    text = line.strip().rstrip(",")
    if not text or text in ("[", "]"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    field_id = payload.get("field_id", "")
    if field_id not in valid_field_ids:
        return None
    # Q1.2：annotator/created_at/schema 优先取源记录，缺省才补默认——绝不用全局常量覆盖已有值。
    annotator = payload.get("annotator_model") or default_annotator
    if not annotator:
        raise ValueError(
            f"记录缺 annotator_model 且未提供 default_annotator：{product_name}/{field_id}"
        )
    created_raw = payload.get("created_at")
    created_at = (
        datetime.fromisoformat(created_raw) if created_raw else default_created_at
    )
    return GoldenRecord(
        product_id=product_id,
        product_name=product_name,
        doc=payload.get("doc") or "保险条款.pdf",
        field_id=field_id,
        field_name=payload.get("field_name") or field_name_of[field_id],
        value=payload.get("value"),
        tri_state=payload.get("tri_state", "unknown"),
        evidence=[
            Evidence(page=e["page"], quote=e["quote"])
            for e in payload.get("evidence") or []
            if e.get("quote")
        ],
        reasoning=payload.get("reasoning"),
        annotator_model=annotator,
        schema_version=payload.get("schema_version") or default_schema_version,
        created_at=created_at,
    )


def assemble_records(
    workspace: Path,
    registry: SchemaRegistry,
    plans: Sequence[ProductPlan],
    *,
    dataset_root: Path | None = None,
    default_annotator: str | None = None,
) -> tuple[list[GoldenRecord], list[ProductAssembly]]:
    """读 workspace 的 per-product golden.jsonl，回验（有 dataset_root 时）并汇总。"""
    all_records: list[GoldenRecord] = []
    report: list[ProductAssembly] = []
    now = datetime.now(UTC)

    for plan in plans:
        wdir = workspace / plan.product
        golden = wdir / "golden.jsonl"
        line = registry.line(plan.line_key)
        valid_ids = {f.field_id for f in line.fields}
        field_name_of = {f.field_id: f.name for f in line.fields}

        # product_id 优先取源目录 product_meta（有 dataset_root 时），否则用产品名。
        product_id = plan.product
        meta: dict[str, object] | None = None
        if dataset_root is not None and (dataset_root / plan.product).exists():
            meta = load_product_meta(dataset_root / plan.product)
            product_id = str(meta.get("planCode") or plan.product).strip()

        if not golden.exists():
            report.append(
                ProductAssembly(
                    product=plan.product,
                    product_id=product_id,
                    records=0,
                    missing_fields=len(valid_ids),
                    bad_lines=0,
                    disputed=0,
                    annotator_models=[],
                    status="missing_golden",
                )
            )
            continue

        records: list[GoldenRecord] = []
        bad_lines = 0
        for raw_line in golden.read_text(encoding="utf-8").splitlines():
            record = _record_from_line(
                raw_line,
                product_id=product_id,
                product_name=plan.product,
                valid_field_ids=valid_ids,
                field_name_of=field_name_of,
                default_annotator=default_annotator,
                default_schema_version=registry.version,
                default_created_at=now,
            )
            if record is None:
                if raw_line.strip().rstrip(",") not in ("", "[", "]"):
                    bad_lines += 1
                continue
            records.append(record)

        if dataset_root is not None:
            _verify_product_records(records, dataset_root / plan.product, meta)

        report.append(
            ProductAssembly(
                product=plan.product,
                product_id=product_id,
                records=len(records),
                missing_fields=len(valid_ids) - len({r.field_id for r in records}),
                bad_lines=bad_lines,
                disputed=sum(r.disputed for r in records),
                annotator_models=sorted({r.annotator_model for r in records}),
            )
        )
        all_records.extend(records)

    return all_records, report


def _verify_product_records(
    records: list[GoldenRecord],
    product_dir: Path,
    meta: dict[str, object] | None,
) -> None:
    """逐文档引文回验 + meta 比对；缺 PDF 的记录标 disputed（quote_mismatch）。"""
    by_doc: dict[str, list[GoldenRecord]] = {}
    for record in records:
        by_doc.setdefault(record.doc, []).append(record)
    for doc, recs in by_doc.items():
        pdf = product_dir / doc
        if pdf.exists():
            verify_quotes(recs, extract_pages(pdf))
        else:
            for record in recs:
                record.disputed = True
                record.disputed_reason = "quote_mismatch"
    if meta is not None:
        compare_with_meta(records, meta)


def assemble_release(
    workspace: Path,
    out_dir: Path,
    *,
    schema_dir: Path,
    dataset_root: Path | None = None,
    plans: Sequence[ProductPlan] | None = None,
    default_annotator: str | None = None,
) -> AssembleReport:
    """汇总 workspace → 不可变 release 目录（含 per-product JSONL + manifest）。"""
    registry = load_schema_registry(schema_dir)
    resolved_plans = list(plans) if plans is not None else load_product_plans(workspace)
    records, product_reports = assemble_records(
        workspace,
        registry,
        resolved_plans,
        dataset_root=dataset_root,
        default_annotator=default_annotator,
    )
    build_release(
        records,
        out_dir,
        dataset_root=str(dataset_root) if dataset_root is not None else "",
    )
    return AssembleReport(
        products=product_reports,
        total_records=len(records),
        annotator_models=sorted({r.annotator_model for r in records}),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="金标 release 汇总器（019 Q1）")
    parser.add_argument("--workspace", required=True, type=Path, help="WIP 工作目录")
    parser.add_argument("--out", required=True, type=Path, help="release 输出目录（不可变）")
    parser.add_argument("--schema-dir", required=True, type=Path, help="schema 基线目录")
    parser.add_argument(
        "--dataset-root", type=Path, default=None, help="原始 PDF 根目录（引文回验，可选）"
    )
    parser.add_argument(
        "--default-annotator", type=str, default=None,
        help="源记录缺 annotator_model 时的兜底标注者（不覆盖已有值）",
    )
    args = parser.parse_args(argv)
    report = assemble_release(
        args.workspace,
        args.out,
        schema_dir=args.schema_dir,
        dataset_root=args.dataset_root,
        default_annotator=args.default_annotator,
    )
    dump_json(report.model_dump(mode="json"), args.out / "assemble-report.json")
    print(
        f"assembled {report.total_records} records / {len(report.products)} products "
        f"annotators={report.annotator_models} → {args.out}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
