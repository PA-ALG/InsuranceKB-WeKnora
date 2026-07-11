"""T8 汇总管线：agent 标注 JSONL → GoldenRecord → 引文回验 → meta 比对 → gs-v0.1 release。

用法：uv run python <this> [--dry-run]
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from insurance_harness.goldenset.pdf import extract_pages
from insurance_harness.goldenset.records import Evidence, GoldenRecord
from insurance_harness.goldenset.release import build_release
from insurance_harness.goldenset.verify import compare_with_meta, load_product_meta, verify_quotes
from insurance_harness.schemas.loader import load_schema_registry

ROOT = Path("/Users/houjing/code/kb_LLMwiki/InsuranceKB-WeKnora")
WORK = Path(__file__).parent
ANNOTATOR = "claude-fable-5 (session agents, gs-v0.1)"


def main() -> None:
    dry = "--dry-run" in sys.argv
    reg = load_schema_registry(ROOT / "docs/insurance-kb/schema-baseline")
    manifest = json.loads((WORK / "manifest.json").read_text())
    all_records: list[GoldenRecord] = []
    report: list[dict[str, object]] = []
    now = datetime.now(UTC)

    for prod in manifest["products"]:
        name = prod["product"]
        pdir_src = ROOT / "dataset/shouxian_product" / name
        wdir = WORK / name
        golden = wdir / "golden.jsonl"
        if not golden.exists():
            report.append({"product": name, "status": "MISSING golden.jsonl"})
            continue
        meta = load_product_meta(pdir_src)
        product_id = str(meta.get("planCode") or name)
        line = reg.line(prod["line_key"])
        valid_ids = {f.field_id for f in line.fields}

        records: list[GoldenRecord] = []
        bad_lines = 0
        for ln in golden.read_text().splitlines():
            ln = ln.strip().rstrip(",")
            if not ln or ln in ("[", "]"):
                continue
            try:
                d = json.loads(ln)
            except json.JSONDecodeError:
                bad_lines += 1
                continue
            fid = d.get("field_id", "")
            if fid not in valid_ids:
                bad_lines += 1
                continue
            tri = d.get("tri_state", "unknown")
            records.append(
                GoldenRecord(
                    product_id=product_id,
                    product_name=name,
                    doc=d.get("doc") or "保险条款.pdf",
                    field_id=fid,
                    field_name=d.get("field_name") or line.field_by_id(fid).name,
                    value=d.get("value"),
                    tri_state=tri,
                    evidence=[
                        Evidence(page=e["page"], quote=e["quote"])
                        for e in d.get("evidence") or []
                        if e.get("quote")
                    ],
                    reasoning=d.get("reasoning"),
                    annotator_model=ANNOTATOR,
                    schema_version=reg.version,
                    created_at=now,
                )
            )

        # 逐文档回验（按 doc 分组，页文本来自原 PDF）
        by_doc: dict[str, list[GoldenRecord]] = {}
        for r in records:
            by_doc.setdefault(r.doc, []).append(r)
        for doc, recs in by_doc.items():
            pdf = pdir_src / doc
            if pdf.exists():
                verify_quotes(recs, extract_pages(pdf))
            else:
                for r in recs:
                    r.disputed = True
                    r.disputed_reason = "quote_mismatch"
        compare_with_meta(records, meta)

        n_disputed = sum(r.disputed for r in records)
        tri_counts = {t: sum(r.tri_state == t for r in records) for t in ("present", "absent_explicitly", "unknown")}
        missing = len(valid_ids) - len({r.field_id for r in records})
        report.append(
            {
                "product": name,
                "records": len(records),
                "missing_fields": missing,
                "bad_lines": bad_lines,
                **tri_counts,
                "disputed": n_disputed,
                "disputed_rate": round(n_disputed / max(len(records), 1), 3),
            }
        )
        all_records.extend(records)

    print(json.dumps(report, ensure_ascii=False, indent=1))
    if dry:
        return
    out = ROOT / "dataset/goldenset/gs-v0.1"
    stats = build_release(all_records, out)
    print("RELEASE:", json.dumps(stats, ensure_ascii=False, default=str)[:600])


if __name__ == "__main__":
    main()
