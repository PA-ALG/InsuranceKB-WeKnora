"""金标 release：不可变版本目录 + manifest（spec G3）。"""

from collections import Counter
from pathlib import Path

from .records import GoldenRecord
from .runner import dump_json, write_jsonl


def build_release(
    records: list[GoldenRecord],
    out_dir: Path,
    *,
    dataset_root: str = "dataset/shouxian_product",
) -> dict[str, object]:
    """写 per-product JSONL + manifest.json + disputed.jsonl；目录已存在则拒绝（G3.2）。"""
    if out_dir.exists():
        raise FileExistsError(
            f"金标 release 目录已存在：{out_dir}——release 不可变，请使用新版本号目录"
        )
    if not records:
        raise ValueError("没有可发布的金标记录")
    out_dir.mkdir(parents=True)

    by_product: dict[str, list[GoldenRecord]] = {}
    for r in records:
        by_product.setdefault(r.product_id, []).append(r)
    for product_id, recs in sorted(by_product.items()):
        write_jsonl(recs, out_dir / f"{product_id}.jsonl")

    disputed = [r for r in records if r.disputed]
    write_jsonl(disputed, out_dir / "disputed.jsonl")

    tri_counts = Counter(r.tri_state for r in records)
    disputed_reasons = Counter(r.disputed_reason for r in disputed if r.disputed_reason)
    manifest: dict[str, object] = {
        "schema_version": records[0].schema_version,
        "annotator_model": records[0].annotator_model,
        "dataset_root": dataset_root,
        "products": {
            pid: {
                "product_name": recs[0].product_name,
                "records": len(recs),
                "disputed": sum(1 for r in recs if r.disputed),
                "docs": sorted({r.doc for r in recs}),
            }
            for pid, recs in sorted(by_product.items())
        },
        "totals": {
            "records": len(records),
            "products": len(by_product),
            "tri_state": dict(tri_counts),
            "disputed": len(disputed),
            "disputed_reasons": dict(disputed_reasons),
        },
    }
    dump_json(manifest, out_dir / "manifest.json")
    return manifest
