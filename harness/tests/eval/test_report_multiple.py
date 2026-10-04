"""Multi-file Golden reports retain per-source provenance and pack-specific misses."""

import hashlib
import json
from pathlib import Path

from insurance_harness.eval.report import main


def test_multiple_golden_files_keep_hashes_and_rank_missed_fields(tmp_path: Path) -> None:
    paths = []
    for pack in ("pack-a", "pack-b"):
        path = tmp_path / f"{pack}.jsonl"
        row = {
            "pack_id": pack, "product_id": pack, "field_key": "term", "state": "present",
            "value": "90日", "judged_by": "human:test", "evidence": [{
                "document": "terms.pdf", "document_sha256": "a" * 64, "page": 1, "quote": "90日",
            }],
        }
        path.write_text(json.dumps(row) + "\n")
        paths.append(path)
    (tmp_path / "manifest.json").write_text(json.dumps({"files": {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }}))
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({
        "request": {"entity_bindings": [
            {"entity_id": pack, "display_name": pack, "schema_pack_id": pack}
            for pack in ("pack-a", "pack-b")
        ]}, "compile_result": {"output": {"fields": [
            {"entity_id": "pack-a", "field_key": "term", "state": "present", "value": "90日"},
            {"entity_id": "pack-b", "field_key": "term", "state": "unknown", "value": None},
        ]}},
    }))
    mapping = tmp_path / "products.json"
    mapping.write_text(json.dumps({"pack-a": "pack-a", "pack-b": "pack-b"}))
    args = [
        "--candidate", str(candidate), "--product-map", str(mapping),
        "--out", str(tmp_path / "report"),
        "--golden", str(paths[0]), "--golden", str(paths[1]),
    ]
    assert main(args) == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["golden_items"] == 2
    assert report["gates"]["pack-a"]["passed"] is True
    assert report["gates"]["pack-b"]["passed"] is False
    assert len(report["provenance"]["golden_files"]) == 2
    assert all(row["manifest"]["golden_digest_verified"]
               for row in report["provenance"]["golden_files"])
    assert report["top_missed_fields"]["pack-b"] == [{"field_key": "term", "missed": 1}]
    assert report["top_missed_fields"]["pack-a"] == []
    assert "Top missed fields" in (tmp_path / "report.md").read_text()
