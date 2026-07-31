#!/usr/bin/env python3
"""OpenSpec 049 task command: review two blind passes, then freeze exact approval."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any, Literal, NamedTuple, cast

from insurance_harness.canonical import canonical_hash
from insurance_harness.goldenset import (
    Evidence,
    ExpectedProduct,
    GoldenRecord,
    build_release,
    extract_pages,
    release_hash,
    validate_release,
)
from insurance_harness.goldenset.normalize import quote_in_page
from insurance_harness.goldenset.runner import dump_json
from insurance_harness.schemas import SchemaRegistry, load_schema_registry

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "docs" / "insurance-kb" / "schema-baseline"
SCHEMA_AUTHORITY = ROOT / "docs/insurance-kb/schema-authority/产品知识库字段标签维度-20240205.xlsx"
SCHEMA_AUTHORITY_SHA256 = "5cd0ed8af0bc10fec488d0d83e8e28c7c0d64408c4fc25cca92b2a365355fdb6"
PRODUCT_ID, PRODUCT_VERSION = "596", "596-1"
PRODUCT_NAME, MODEL_ID = "平安e生保（尊享版）医疗保险", "gpt-5.6-sol"
DATASET_ROOT = ROOT / "dataset" / "shouxian_product"
PRODUCT_DIR = DATASET_ROOT / PRODUCT_NAME
PASS_IDS = {"candidate": "049-blind-candidate-a", "review": "049-blind-review-b"}
SOURCES = (
    ("保险条款.pdf", 1_047_811, "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"),
    ("产品说明书.pdf", 492_101, "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"),
    ("费率表.pdf", 51_961, "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb"),
)
MANDATORY = ("regulatory_filing_no", "clause_version", "clause_effective_date",
             "exclusions_official", "pre_existing_conditions", "discontinuation_renewal")
ROW_KEYS = frozenset({"field_id", "field_name", "value", "tri_state", "evidence",
                      "reasoning", "annotator_model"})
RUN_KEYS = frozenset(
    {"pass_id", "model", "batch_count", "parse_retries", "prompt_sha256", "input_sha256",
     "output_sha256", "input_refs"}
)
class FreezeContractError(ValueError):
    pass
def _publish_no_replace(source: Path, target: Path) -> None:
    libc, raw = ctypes.CDLL(None, use_errno=True), (os.fsencode(source), os.fsencode(target))
    if sys.platform == "darwin":
        rename, args = getattr(libc, "renamex_np", None), (*raw, 0x00000004)
    elif sys.platform == "linux":
        rename, args = getattr(libc, "renameat2", None), (-100, raw[0], -100, raw[1], 1)
    else:
        raise OSError(errno.ENOTSUP, "atomic no-replace publish is unsupported", target)
    if rename is None:
        raise OSError(errno.ENOTSUP, "atomic no-replace publish is unavailable", target)
    if rename(*args):
        if (code := ctypes.get_errno()) == errno.EEXIST:
            raise FileExistsError(code, os.strerror(code), target)
        raise OSError(code, os.strerror(code), target)
class FrozenInputs(NamedTuple):
    registry: SchemaRegistry
    schema_version: str
    schema_authority_sha256: str
    fields: dict[str, str]
    sources: list[dict[str, object]]
    pages: dict[str, dict[int, str]]
    authority_counts: dict[str, int]
def _sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()
def _exact(value: object, keys: frozenset[str], label: str) -> dict[str, object]:
    if type(value) is not dict or frozenset(cast(dict[str, object], value)) != keys:
        raise FreezeContractError(f"{label} has an invalid exact schema")
    return cast(dict[str, object], value)
@cache
def load_inputs() -> FrozenInputs:
    if hashlib.sha256(SCHEMA_AUTHORITY.read_bytes()).hexdigest() != SCHEMA_AUTHORITY_SHA256:
        raise FreezeContractError("schema authority bytes drift")
    registry = load_schema_registry(SCHEMA_DIR)
    specs = registry.line("medical").extractable_fields
    fields = {field.field_id: field.name for field in specs}
    if len(specs) != 60 or len(fields) != 60:
        raise FreezeContractError("medical schema is not an exact 60-field bijection")
    extension_count = sum(field.source_sheet == "extensions-v1.1" for field in specs)
    if extension_count != 11:
        raise FreezeContractError("schema authority split is not frozen 49+11")
    sources: list[dict[str, object]] = []
    pages: dict[str, dict[int, str]] = {}
    for name, size, digest in SOURCES:
        path = PRODUCT_DIR / name
        raw = path.read_bytes()
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise FreezeContractError(f"source identity drift: {name}")
        sources.append(
            {"name": name, "path": str(path.relative_to(ROOT)), "size": size, "sha256": digest}
        )
        pages[name] = {page.page_no: page.text for page in extract_pages(path)}
    counts = {"workbook_authoritative": 49, "v1_1_extensions": 11}
    return FrozenInputs(registry, registry.version, SCHEMA_AUTHORITY_SHA256, fields,
                        sources, pages, counts)
def blind_contract(role: Literal["candidate", "review"]) -> dict[str, object]:
    inputs = load_inputs()
    refs = [
        f"schema:{SCHEMA_AUTHORITY_SHA256}", "product:596", "product-version:596-1",
        *(f"pdf:{row['sha256']}" for row in inputs.sources),
    ]
    prompt = {
        "mission": "049-s0q-full-golden-freeze", "pass_id": PASS_IDS[role],
        "model": MODEL_ID, "field_ids": sorted(inputs.fields), "input_refs": refs,
        "rules": ["exact60", "tri-state", "exact-pdf-evidence", "no-prior-answers"],
    }
    payload = {
        "schema_version": inputs.schema_version,
        "fields": [{"field_id": key, "field_name": inputs.fields[key]}
                   for key in sorted(inputs.fields)],
        "sources": inputs.sources,
    }
    return {
        "pass_id": PASS_IDS[role], "model": MODEL_ID, "batch_count": 6,
        "prompt_sha256": _sha(prompt), "input_sha256": _sha(payload), "input_refs": refs,
    }
def _record(raw: object, expected_id: str, inputs: FrozenInputs) -> dict[str, object]:
    row = _exact(raw, ROW_KEYS, f"record {expected_id}")
    if row["field_id"] != expected_id or row["field_name"] != inputs.fields[expected_id]:
        raise FreezeContractError("record field identity drift")
    if row["annotator_model"] != MODEL_ID:
        raise FreezeContractError("blind record model must be gpt-5.6-sol")
    state, value, evidence = row["tri_state"], row["value"], row["evidence"]
    if state not in ("present", "absent_explicitly", "unknown"):
        raise FreezeContractError("invalid tri-state")
    if type(evidence) is not list:
        raise FreezeContractError("Evidence must be an exact list")
    if state == "unknown" and (value is not None or evidence):
        raise FreezeContractError("unknown requires null value and no Evidence")
    if state != "unknown" and (type(value) is not str or not evidence):
        raise FreezeContractError("known tri-state requires value and Evidence")
    for raw_evidence in cast(list[object], evidence):
        item = _exact(raw_evidence, frozenset({"doc", "page", "quote"}), "Evidence")
        doc, page, quote = item["doc"], item["page"], item["quote"]
        if (doc not in inputs.pages or type(page) is not int
                or page not in inputs.pages[doc]):
            raise FreezeContractError("Evidence source/page drift")
        page_text = inputs.pages[doc][page]
        if type(quote) is not str or not quote_in_page(quote, page_text):
            raise FreezeContractError("Evidence quote mismatch")
    return cast(dict[str, object], json.loads(json.dumps(row)))
def _pass(rows: object, inputs: FrozenInputs) -> list[dict[str, object]]:
    if type(rows) is not list:
        raise FreezeContractError("blind output must be a list")
    ids = [row.get("field_id") if type(row) is dict else None for row in rows]
    if len(ids) != 60 or len(set(ids)) != 60 or set(ids) != set(inputs.fields):
        raise FreezeContractError("blind output violates exact60 field-id bijection")
    return [_record(row, cast(str, row["field_id"]), inputs)
            for row in cast(list[dict[str, object]], rows)]
def _run(run: object, role: Literal["candidate", "review"], rows: object) -> dict[str, object]:
    value, expected = _exact(run, RUN_KEYS, f"{role} run"), blind_contract(role)
    for key in ("pass_id", "model", "batch_count", "prompt_sha256", "input_sha256", "input_refs"):
        if value[key] != expected[key]:
            raise FreezeContractError(f"{role} blind identity drift: {key}")
    retries = value["parse_retries"]
    if type(retries) is not int or not 0 <= retries <= 2:
        raise FreezeContractError("parse retry count is invalid")
    if value["output_sha256"] != _sha(rows):
        raise FreezeContractError(f"{role} output digest drift")
    return value
def build_review(
    candidate_rows: object, review_rows: object, candidate_run: object, review_run: object
) -> dict[str, object]:
    inputs = load_inputs()
    candidate, review = _pass(candidate_rows, inputs), _pass(review_rows, inputs)
    run_a, run_b = _run(candidate_run, "candidate", candidate_rows), _run(
        review_run, "review", review_rows
    )
    if run_a["pass_id"] == run_b["pass_id"]:
        raise FreezeContractError("blind pass_id values must be distinct")
    if cast(int, run_a["parse_retries"]) + cast(int, run_b["parse_retries"]) > 2:
        raise FreezeContractError("total parse retries exceed two")
    by_a = {cast(str, row["field_id"]): row for row in candidate}
    by_b = {cast(str, row["field_id"]): row for row in review}
    differences = sorted(key for key in by_a if by_a[key] != by_b[key])
    multi_doc = {
        key for key, row in (*by_a.items(), *by_b.items())
        if len({item["doc"] for item in cast(list[dict[str, object]], row["evidence"])}) > 1
    }
    sample = sorted(
        sorted(inputs.fields, key=lambda key: hashlib.sha256(
            f"openspec049|{PRODUCT_VERSION}|{key}".encode()
        ).digest())[:3]
    )
    report: dict[str, object] = {
        "status": "PENDING_HUMAN_REVIEW", "product_version": PRODUCT_VERSION,
        "schema_version": inputs.schema_version, "source_documents": inputs.sources,
        "candidate_records": sorted(candidate, key=lambda row: cast(str, row["field_id"])),
        "review_records": sorted(review, key=lambda row: cast(str, row["field_id"])),
        "candidate_run": run_a, "review_run": run_b, "differences": differences,
        "mandatory_review_fields": list(MANDATORY), "fixed_sample_fields": sample,
        "required_human_fields": sorted(
            set(differences) | set(MANDATORY) | set(sample) | multi_doc
        ),
        "authority_counts": inputs.authority_counts,
    }
    report["review_hash"] = canonical_hash("s0q-full-golden-review.v1", report)
    return report
def _golden(rows: list[dict[str, object]], created_at: datetime) -> list[GoldenRecord]:
    inputs, records = load_inputs(), []
    for row in rows:
        evidence = cast(list[dict[str, object]], row["evidence"])
        docs = {cast(str, item["doc"]) for item in evidence}
        if len(docs) > 1:
            raise FreezeContractError(f"{row['field_id']} requires a one-document custom record")
        records.append(GoldenRecord(
            product_id=PRODUCT_ID, product_name=PRODUCT_NAME,
            doc=next(iter(docs), "保险条款.pdf"), field_id=cast(str, row["field_id"]),
            field_name=cast(str, row["field_name"]), value=cast(str | None, row["value"]),
            tri_state=cast(Any, row["tri_state"]),
            evidence=[Evidence(page=cast(int, item["page"]), quote=cast(str, item["quote"]))
                      for item in evidence],
            disputed=False, disputed_reason=None, reasoning=cast(str | None, row["reasoning"]),
            annotator_model=MODEL_ID, schema_version=inputs.schema_version, created_at=created_at,
        ))
    return records
def resolve_review(review: object, adjudication: object) -> dict[str, object]:
    report = cast(dict[str, object], review)
    supplied = report.get("review_hash")
    body = {key: value for key, value in report.items() if key != "review_hash"}
    if supplied != canonical_hash("s0q-full-golden-review.v1", body):
        raise FreezeContractError("review hash drift")
    decision_set = _exact(adjudication, frozenset({"review_hash", "decisions"}), "adjudication")
    if decision_set["review_hash"] != supplied or type(decision_set["decisions"]) is not list:
        raise FreezeContractError("adjudication review identity drift")
    decisions: dict[str, dict[str, object]] = {}
    for raw in cast(list[object], decision_set["decisions"]):
        value = cast(dict[str, object], raw) if type(raw) is dict else {}
        keys = (frozenset({"field_id", "choice", "reason", "record"})
                if value.get("choice") == "custom"
                else frozenset({"field_id", "choice", "reason"}))
        value = _exact(raw, keys, "human decision")
        field_id, reason = value["field_id"], value["reason"]
        if (type(field_id) is not str or type(reason) is not str
                or not reason.strip() or field_id in decisions):
            raise FreezeContractError("human decision identity/reason is invalid")
        if value["choice"] not in ("candidate", "review", "custom"):
            raise FreezeContractError("human decision choice is invalid")
        decisions[field_id] = value
    required = set(cast(list[str], report["required_human_fields"]))
    if set(decisions) != required:
        raise FreezeContractError("human decisions do not close the exact review set")
    inputs = load_inputs()
    candidates = cast(list[dict[str, object]], report["candidate_records"])
    reviews = cast(list[dict[str, object]], report["review_records"])
    by_a = {row["field_id"]: row for row in candidates}
    by_b = {row["field_id"]: row for row in reviews}
    final: list[dict[str, object]] = []
    for field_id in sorted(inputs.fields):
        decision = decisions.get(field_id)
        if decision is None:
            if by_a[field_id] != by_b[field_id]:
                raise FreezeContractError("unreviewed pass difference")
            selected = by_a[field_id]
        elif decision["choice"] == "candidate":
            selected = by_a[field_id]
        elif decision["choice"] == "review":
            selected = by_b[field_id]
        else:
            selected = _record(decision["record"], field_id, inputs)
        final.append(_record(selected, field_id, inputs))
    golden = _golden(final, datetime(1970, 1, 1, tzinfo=UTC))
    release = release_hash(golden)
    artifact = canonical_hash("s0q-full-golden-artifact.v1", {
        "review_hash": supplied, "adjudication": decision_set, "final_records": final,
    })
    subject = canonical_hash("s0q-full-golden-approval-subject.v1", {
        "product_version": PRODUCT_VERSION, "release_hash": release, "artifact_hash": artifact,
    })
    return {"final_records": final, "release_hash": release,
            "artifact_hash": artifact, "approval_subject": subject}
def _approval(raw: object, resolved: dict[str, object]) -> dict[str, str]:
    keys = frozenset({"receipt_type", "issued_by", "actor_type", "approved_by", "action",
                      "reason", "approved_at", "subject_sha256", "release_hash", "artifact_hash",
                      "source_thread_id", "conversation_id", "user_approval_ref"})
    value = _exact(raw, keys, "external approval receipt")
    if (value["receipt_type"], value["issued_by"], value["actor_type"], value["action"]) != (
        "total-control-human-approval.v1", "total-control", "human", "approve"
    ):
        raise FreezeContractError("approval must be externally issued for a named human")
    for key in keys:
        if type(value[key]) is not str or not cast(str, value[key]).strip():
            raise FreezeContractError(f"approval {key} is empty")
    lowered = " ".join(cast(str, value[key]) for key in
                       ("approved_by", "reason", "source_thread_id", "conversation_id",
                        "user_approval_ref")).casefold()
    if any(token in lowered for token in ("placeholder", "todo", "unknown", "tbd")):
        raise FreezeContractError("approval provenance contains a placeholder")
    if not cast(str, value["source_thread_id"]).startswith("019") \
            or not cast(str, value["conversation_id"]).startswith("019") \
            or not cast(str, value["user_approval_ref"]).startswith("user-message:"):
        raise FreezeContractError("approval lacks conversation/user audit provenance")
    for key, expected in (("subject_sha256", resolved["approval_subject"]),
                          ("release_hash", resolved["release_hash"]),
                          ("artifact_hash", resolved["artifact_hash"])):
        if value[key] != expected:
            raise FreezeContractError(f"approval {key} drift")
    try:
        approved_at = datetime.fromisoformat(cast(str, value["approved_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise FreezeContractError("approval timestamp is not RFC3339") from exc
    if approved_at.tzinfo is None:
        raise FreezeContractError("approval timestamp lacks timezone")
    return {key: cast(str, value[key]) for key in keys}
def freeze_release(
    review: object, adjudication: object, approval_receipt: object, out_dir: Path
) -> None:
    resolved = resolve_review(review, adjudication)
    receipt = _approval(approval_receipt, resolved)
    records = _golden(
        cast(list[dict[str, object]], resolved["final_records"]),
        datetime.fromisoformat(receipt["approved_at"].replace("Z", "+00:00")),
    )
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    container = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.", dir=out_dir.parent))
    staging = container / "release"
    try:
        manifest = build_release(records, staging, dataset_root=str(DATASET_ROOT.relative_to(ROOT)))
        result = validate_release(
            staging, registry=load_inputs().registry,
            expected=[ExpectedProduct(product_id=PRODUCT_ID, line_key="medical")],
            dataset_root=DATASET_ROOT, max_disputed_rate=0, require_evidence=True,
        )
        if not result.passed:
            raise FreezeContractError(f"release validation failed: {result.failures()}")
        manifest.update({
            "status": "S0_Q_FROZEN_FULL_GOLDEN_AVAILABLE",
            "product_version": PRODUCT_VERSION, "release_hash": resolved["release_hash"],
            "artifact_hash": resolved["artifact_hash"],
            "approval_subject": resolved["approval_subject"],
            "authority_counts": load_inputs().authority_counts,
            "source_documents": cast(dict[str, object], review)["source_documents"],
            "scope": "S0-Q only; not production or machine_auto",
        })
        dump_json({"review": review, "adjudication": adjudication,
                   "approval_receipt": receipt}, staging / "review-and-approval.json")
        names = ("596.jsonl", "disputed.jsonl", "review-and-approval.json")
        manifest["files"] = {name: hashlib.sha256((staging / name).read_bytes()).hexdigest()
                             for name in names}
        dump_json(manifest, staging / "manifest.json")
        if {path.name for path in staging.iterdir()} != {
            "596.jsonl", "disputed.jsonl", "manifest.json", "review-and-approval.json"
        }:
            raise FreezeContractError("release artifact set drift")
        _publish_no_replace(staging, out_dir)
    except BaseException:
        shutil.rmtree(container, ignore_errors=True)
        raise
    shutil.rmtree(container, ignore_errors=True)
def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))
def _load_jsonl(path: Path) -> list[object]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-contract", choices=PASS_IDS)
    for name in ("candidate", "review", "candidate-run", "review-run", "decisions",
                 "approval-receipt", "out"):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args()
    if args.emit_contract:
        contract = blind_contract(cast(Any, args.emit_contract))
        print(json.dumps(contract, ensure_ascii=False, indent=2))
        return 0
    required = (args.candidate, args.review, args.candidate_run, args.review_run)
    if any(path is None for path in required):
        parser.error("candidate, review, and both run manifests are required")
    report = build_review(_load_jsonl(args.candidate), _load_jsonl(args.review),
                          _load_json(args.candidate_run), _load_json(args.review_run))
    if args.decisions is None:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    decisions = _load_json(args.decisions)
    if args.approval_receipt is None:
        print(json.dumps(resolve_review(report, decisions), ensure_ascii=False, indent=2))
        return 2
    if args.out is None:
        parser.error("--out is required with --approval-receipt")
    freeze_release(report, decisions, _load_json(args.approval_receipt), args.out)
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
