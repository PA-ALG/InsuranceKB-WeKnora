import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path("/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation")
E = ROOT / "docs/insurance-kb/evidence/830-g3"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


inventory = json.loads((E / "native-capture-inventory-v2.json").read_text())
corpus = json.loads((E / "corpus-files-v4.json").read_text())
corpus_by_id = {row["inventory_id"]: row for row in corpus["entries"]}
docs = inventory["documents"]
assert len(docs) == 15
assert len({row["material_id"] for row in docs}) == 15
assert set(corpus_by_id) == {row["material_id"] for row in docs}
assert inventory["corpus_file_set_sha256"] == corpus["file_set_sha256"]

checks = []
for row in docs:
    material_id = row["material_id"]
    capture_path = ROOT / row["path"]
    capture_bytes = capture_path.read_bytes()
    assert hashlib.sha256(capture_bytes).hexdigest() == row["capture_file_sha256"]
    assert len(capture_bytes) == row["capture_bytes"]
    raw = gzip.decompress(capture_bytes)
    capture = json.loads(raw)
    metadata = capture["metadata"] if isinstance(capture.get("metadata"), dict) else json.loads(capture["raw_metadata"])
    sanitized = metadata["sanitized_json"]
    markdown = capture["markdown"]
    assert hashlib.sha256(canonical(sanitized)).hexdigest() == metadata["sanitized_sha256"] == row["native_sha256"]
    assert hashlib.sha256(markdown.encode()).hexdigest() == sanitized["markdown_sha256"] == row["markdown_sha256"]
    assert len(markdown.encode()) == row["markdown_utf8_bytes"]
    assert sanitized["source_sha256"] == metadata["source_sha256"] == row["file_sha256"]
    assert sanitized["parser_identity_sha256"] == row["parser_identity_sha256"]
    assert len(sanitized["pages"]) == row["pages"]
    corpus_row = corpus_by_id[material_id]
    source_path = ROOT / corpus_row["path"]
    assert sha(source_path) == corpus_row["file_sha256"] == row["file_sha256"]
    assert source_path.stat().st_size == corpus_row["size_bytes"]
    assert corpus_row["pages"] == row["pages"]
    checks.append({"material_id": material_id, "capture": "PASS", "source": "PASS", "markdown": "PASS", "native": "PASS", "pages": "PASS", "parser": "PASS"})

capture_set = [{"material_id": row["material_id"], "capture_file_sha256": row["capture_file_sha256"]} for row in sorted(docs, key=lambda row: row["material_id"])]
assert hashlib.sha256(canonical(capture_set)).hexdigest() == inventory["capture_set_sha256"]

preservation = json.loads((E / "existing-native-preservation.json").read_text())
preserved_by_id = {row["material_id"]: row for row in preservation["documents"]}
assert set(preserved_by_id) == {"g3-material-01", "g3-material-03", "g3-material-04"}
for material_id, prow in preserved_by_id.items():
    irow = next(row for row in docs if row["material_id"] == material_id)
    path = ROOT / prow["persisted_path"]
    raw = gzip.decompress(path.read_bytes())
    assert sha(path) == prow["gzip_sha256"] == irow["capture_file_sha256"]
    assert hashlib.sha256(raw).hexdigest() == prow["raw_capture_sha256"]
    assert len(raw) == prow["raw_bytes"]
    assert path.stat().st_size == prow["gzip_bytes"]
    for pkey, ikey in (("canonical_native_sha256", "native_sha256"), ("markdown_sha256", "markdown_sha256"), ("source_sha256", "file_sha256"), ("parser_identity_sha256", "parser_identity_sha256"), ("pages", "pages")):
        assert prow[pkey] == irow[ikey]
    receipt = ROOT / prow["historical_receipt"]
    assert sha(receipt) == prow["historical_receipt_sha256"]
    receipt_text = receipt.read_text()
    if prow["historical_raw_capture_digest_bound"]:
        assert prow["raw_capture_sha256"] in receipt_text
    else:
        assert prow["raw_capture_sha256"] not in receipt_text
        assert prow["canonical_native_sha256"] in receipt_text
        assert prow["source_sha256"] in receipt_text
        assert prow["parser_identity_sha256"] in receipt_text

supplement = json.loads((E / "native-02-supplement-result.json").read_text())
row02 = next(row for row in docs if row["material_id"] == "g3-material-02")
assert supplement["status"] == "PASS"
assert supplement["flow"] == "NOT RUN"
assert supplement["provider_calls"] == supplement["knowledge_uploads"] == supplement["knowledge_reparses"] == supplement["db_writes"] == 0
assert sha(E / "native_02_supplement.py") == supplement["script_sha256"]
assert sha(ROOT / supplement["capture_path"]) == supplement["capture_sha256"] == row02["capture_file_sha256"]
assert supplement["source_sha256"] == row02["file_sha256"]
assert supplement["canonical_native_sha256"] == row02["native_sha256"]
assert supplement["markdown_sha256"] == row02["markdown_sha256"]
assert supplement["parser_identity_sha256"] == row02["parser_identity_sha256"]
assert supplement["pages"] == row02["pages"] == 27

preflight = json.loads((E / "source-runtime-v3-actual-preflight-03.json").read_text())
assert preflight["contract"] == "830-g3-source-runtime-provision-preflight.v1"
assert all(value == 0 for value in preflight["effects"].values())
assert all(preflight["target_absence"].values())
assert sha(E / "source_runtime_provision_v3.py") == preflight["script_sha256"]
assert sha(E / "source-runtime-isolation-plan.md") == preflight["plan_sha256"]
for name, digest in preflight["frozen_evidence_sha256"].items():
    assert sha(E / name) == digest
assert len(preflight["source_snapshot"]["knowledge_file_references"]) == 4
assert len(preflight["source_snapshot"]["source_rows"]) == 3
ref_ids = {row["id"] for row in preflight["source_snapshot"]["knowledge_file_references"]}
source_ids = {row["knowledge_id"] for row in preflight["source_snapshot"]["source_rows"]}
assert ref_ids - source_ids == {"1265a343-c408-4620-8eed-c4f6a2adadc2"}
old_corpus = {row["file_sha256"]: row for row in corpus["entries"][:4]}
assert {row["sha256"] for row in preflight["files"]} == set(old_corpus)
for row in preflight["files"]:
    assert row["size"] == old_corpus[row["sha256"]]["size_bytes"]

print(json.dumps({
    "status": "PASS",
    "capture_count": len(checks),
    "capture_set_sha256": inventory["capture_set_sha256"],
    "documents": checks,
    "historical_raw_bound": sorted(k for k, v in preserved_by_id.items() if v["historical_raw_capture_digest_bound"]),
    "historical_canonical_only": sorted(k for k, v in preserved_by_id.items() if not v["historical_raw_capture_digest_bound"]),
    "supplement_02": "LOCAL_CAPTURE_ONLY_NOT_SOURCE_REVISION",
    "preflight": "PASS_ZERO_EFFECTS_TARGET_ABSENT",
    "missing_source_row_knowledge_id": sorted(ref_ids - source_ids),
}, ensure_ascii=False, indent=2))
