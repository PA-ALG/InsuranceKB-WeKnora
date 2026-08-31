#!/usr/bin/env python3
"""Recompute the B0 evidence identities without starting services or Docker."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET


FORMAL_BASE = "99205db986eae2a9fa4bc956c053b94298d0b114"
EVIDENCE_BASE = "9fcf3386833d822a31f2de13fdf76c3eb6b13795"
EVIDENCE_TREE = "7314d1c9bc82dc7efb114affb6f2450d0dbd36ae"
WORKBOOK_SHA256 = "8feb33a1e7dc55fad1719a151737822e62bfac815f4b0969441e38744f0204ec"
WORKBOOK_SIZE = 112185
ALLOWED_DISPOSITIONS = {"KEEP", "REWIRE", "FREEZE", "SUPERSEDE"}
EXPECTED_DISPOSITIONS = {"KEEP": 4, "REWIRE": 3, "FREEZE": 2, "SUPERSEDE": 4}
ALLOWED_CHANGED_EXACT = {
    "AGENTS.md",
    "HANDOFF.md",
    "jlx_enterprise_llm_wiki_technical_blueprint_830.md",
    "docs/insurance-kb/28-development-execution-charter-830.md",
    "docs/insurance-kb/29-goal-cards-830.md",
}
ALLOWED_CHANGED_PREFIX = "docs/insurance-kb/evidence/830-b0/"


def run(*args: str, check: bool = True) -> str:
    result = subprocess.run(args, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and result.returncode != 0:
        raise AssertionError(f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr}")
    return result.stdout.rstrip("\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def canonical_json_sha(payload: dict) -> str:
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def assert_receipt_self_hash(path: Path, mode: str) -> None:
    payload = load_json(path)
    expected = payload["self_sha256"]
    if mode == "delete":
        payload.pop("self_sha256")
    elif mode == "null":
        payload["self_sha256"] = None
    else:
        raise AssertionError(f"unknown self-hash mode: {mode}")
    assert canonical_json_sha(payload) == expected, f"receipt self-hash mismatch: {path}"


def column_number(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref).group(0)
    value = 0
    for letter in letters:
        value = value * 26 + ord(letter) - ord("A") + 1
    return value


def workbook_rows(path: Path) -> tuple[list[str], dict[str, list[dict[int, object]]]]:
    ns_main = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    ns_rel = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    rid_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("x:si", ns_main):
                shared.append("".join(node.text or "" for node in item.iterfind(".//x:t", ns_main)))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in relationships.findall("r:Relationship", ns_rel)}
        sheet_defs = [(sheet.attrib["name"], rel_targets[sheet.attrib[rid_attr]]) for sheet in workbook.findall("x:sheets/x:sheet", ns_main)]
        parsed: dict[str, list[dict[int, object]]] = {}
        for name, target in sheet_defs:
            target_path = target.lstrip("/")
            if not target_path.startswith("xl/"):
                target_path = f"xl/{target_path}"
            sheet_root = ET.fromstring(archive.read(target_path))
            rows: list[dict[int, object]] = []
            for row in sheet_root.findall("x:sheetData/x:row", ns_main):
                values: dict[int, object] = {}
                for cell in row.findall("x:c", ns_main):
                    ref = cell.attrib["r"]
                    kind = cell.attrib.get("t")
                    value_node = cell.find("x:v", ns_main)
                    inline_node = cell.find("x:is/x:t", ns_main)
                    raw = value_node.text if value_node is not None else (inline_node.text if inline_node is not None else None)
                    value: object = raw
                    if raw is not None and kind == "s":
                        value = shared[int(raw)]
                    elif raw is not None and kind not in {"str", "inlineStr"}:
                        try:
                            numeric = float(raw)
                            value = int(numeric) if numeric.is_integer() else numeric
                        except ValueError:
                            value = raw
                    values[column_number(ref)] = value
                rows.append(values)
            parsed[name] = rows
    return [name for name, _ in sheet_defs], parsed


def verify_workbook(root: Path, audit: dict) -> None:
    path = root / "inputs" / audit["audit_copy_path"]
    assert path.stat().st_size == WORKBOOK_SIZE == audit["audit_copy_size_bytes"]
    assert sha256(path) == WORKBOOK_SHA256 == audit["audit_copy_sha256"]
    names, sheets = workbook_rows(path)
    assert names == audit["sheet_names"]
    assert len(names) == 12 and len(names[1:]) == 11
    summary = sheets["汇总表"]
    field_rows = summary[3:-1]
    assert len(field_rows) == 154
    shared_by_all = sum(all(row.get(column) == 1 for column in range(3, 14)) for row in field_rows)
    assert shared_by_all == 47
    total_row = summary[-1]
    expected_counts = [int(total_row[column]) for column in range(3, 14)]
    assert len(names[1:]) == len(expected_counts)
    for name, expected_count in zip(names[1:], expected_counts):
        data_rows = [row for row in sheets[name][5:] if row.get(2) not in (None, "")]
        field_names = [row[2] for row in data_rows]
        english_names = [row.get(4) for row in data_rows]
        assert len(data_rows) == expected_count, f"field count mismatch: {name}"
        assert all(value not in (None, "") for value in english_names), f"blank English name: {name}"
        assert len(field_names) == len(set(field_names)), f"duplicate field name: {name}"
        assert len(english_names) == len(set(english_names)), f"duplicate English name: {name}"


def nearest_rank(samples: list[int], percentile: float) -> int:
    ordered = sorted(samples)
    return ordered[math.ceil(percentile * len(ordered)) - 1]


def verify_validation(validation: dict) -> None:
    assert validation["validation_level"] == "D0"
    assert validation["docker_action"] == "SKIP"
    levels = {item["level"]: item for item in validation["levels"]}
    assert set(levels) == {"D0", "D1", "D2", "D3"}
    assert levels["D0"]["measurement_status"] == "NOT_MEASURED"
    assert levels["D2"]["measurement_status"] == "NOT_MEASURED"
    assert levels["D3"]["measurement_status"] == "NOT_MEASURED"
    for aggregate in levels["D1"]["aggregates"].values():
        samples = aggregate["samples_seconds"]
        assert aggregate["sample_count"] == len(samples)
        assert aggregate["p50_seconds"] == nearest_rank(samples, 0.50)
        assert aggregate["p95_seconds"] == nearest_rank(samples, 0.95)


def verify_hash_recalculation(root: Path, recalculation: dict) -> None:
    assert recalculation["status"] == "PASS"
    for item in recalculation["artifacts"]:
        path = root / item["path"]
        actual = sha256(path)
        assert actual == item["expected_sha256"] == item["actual_sha256"], item["path"]
        assert path.stat().st_size == item["size_bytes"]


def verify_origin_main_diff(repo: Path, integration: dict) -> None:
    source = integration["authority_source_commit"]
    imported = integration["selective_import_commit"]
    assert integration["formal_base"] == FORMAL_BASE
    assert run("git", "merge-base", FORMAL_BASE, source) == integration["merge_base"]
    left, right = [int(value) for value in run("git", "rev-list", "--left-right", "--count", f"{FORMAL_BASE}...{source}").split()]
    assert left == integration["formal_base_unique_commits"]
    assert right == integration["source_unique_commits"]
    source_paths = run("git", "-c", "core.quotePath=false", "diff", "--name-only", f"{FORMAL_BASE}..{source}").splitlines()
    assert len(source_paths) == integration["source_changed_path_count"]
    assert integration["whole_branch_merged"] is False
    for item in integration["selected_authority_blobs"]:
        source_blob = run("git", "rev-parse", f"{source}:{item['path']}")
        imported_blob = run("git", "rev-parse", f"{imported}:{item['path']}")
        assert source_blob == imported_blob == item["blob"]


def verify_closure(closure: dict, head: str, manifest_observed: str) -> None:
    assert closure["goal_id"] == "B0"
    assert closure["branch"] == "codex/830-b0-asset-baseline"
    assert closure["formal_base"] == FORMAL_BASE
    candidate = closure["evidence_candidate_head"]
    assert candidate == manifest_observed
    run("git", "merge-base", "--is-ancestor", candidate, head)
    assert_authorized_paths(
        run("git", "-c", "core.quotePath=false", "diff", "--name-only", f"{candidate}..{head}").splitlines()
    )
    assert_compliant_commits(f"{candidate}..{head}")
    assert closure["product_code_changed_paths"] == 0
    assert closure["openspec_changed_paths"] == 0
    assert closure["refs_deleted"] == 0 and closure["worktrees_removed"] == 0
    assert closure["services_started"] == 0 and closure["images_built"] == 0
    assert closure["final_head_binding"] == "VERIFIER_RUNTIME_OUTPUT_AND_CONTROLLER_REVIEW"


def verify_dispositions(dispositions: dict) -> None:
    items = dispositions["items"]
    ids = [item["id"] for item in items]
    assert len(ids) == len(set(ids)), "duplicate candidate item id"
    states = [item.get("disposition") for item in items]
    assert all(state in ALLOWED_DISPOSITIONS for state in states), "unclassified or invalid disposition"
    paths = [path for item in items for path in item["paths"]]
    assert len(paths) == len(set(paths)), "candidate path/semantic asset classified by more than one item"
    for item in items:
        if item["disposition"] in {"KEEP", "REWIRE"}:
            assert item.get("target_goal"), f"missing target Goal: {item['id']}"
    actual = Counter(states)
    assert dict(actual) == EXPECTED_DISPOSITIONS
    declared = dispositions["counts"]
    assert declared["total"] == len(items) == 13
    assert all(declared[state] == count for state, count in EXPECTED_DISPOSITIONS.items())
    assert declared["unclassified"] == 0 and declared["multi_classified"] == 0


def assert_authorized_paths(paths: list[str]) -> None:
    assert all(path in ALLOWED_CHANGED_EXACT or path.startswith(ALLOWED_CHANGED_PREFIX) for path in paths), paths


def assert_compliant_commits(revision_range: str) -> None:
    messages = run("git", "log", "--format=%B%x00", revision_range).split("\x00")
    for message in [value for value in messages if value.strip()]:
        assert "B0" in message and "NEXT_PHYSICAL_RESULT=" in message, message


def verify_branch_manifest(branch_manifest: dict, head: str) -> None:
    counts = branch_manifest["counts"]
    refs = branch_manifest["refs"]
    worktrees = branch_manifest["worktrees"]
    assert counts["refs"] == len(refs)
    assert counts["worktrees"] == len(worktrees)
    assert counts["candidate_refs"] + counts["index_only_refs"] == len(refs)
    assert counts["candidate_worktrees"] + counts["index_only_worktrees"] == len(worktrees)
    assert counts["deleted_refs"] == 0 and counts["removed_worktrees"] == 0
    for item in [*refs, *worktrees]:
        if item["review_scope"] == "FINITE_CANDIDATE":
            assert item["disposition"] in ALLOWED_DISPOSITIONS
            if item["disposition"] in {"KEEP", "REWIRE"}:
                assert item.get("target_goal")
        else:
            assert item["review_scope"] == "INDEX_ONLY/OUT_OF_SCOPE"
            assert item.get("disposition") is None
    assert branch_manifest["observed_branch"] == "codex/830-b0-asset-baseline"
    observed = branch_manifest["observed_head_before_evidence_commit"]
    current = next(item for item in refs if item["ref"] == "refs/heads/codex/830-b0-asset-baseline")
    assert current["head"] == observed, "current ref record must equal the generation-time observed head"
    run("git", "merge-base", "--is-ancestor", observed, head)
    intervening_paths = run(
        "git", "-c", "core.quotePath=false", "diff", "--name-only", f"{observed}..{head}"
    ).splitlines()
    assert_authorized_paths(intervening_paths)
    assert_compliant_commits(f"{observed}..{head}")


def verify_repo_scope(repo: Path, allow_dirty: bool) -> tuple[str, list[str]]:
    assert run("git", "branch", "--show-current") == "codex/830-b0-asset-baseline"
    head = run("git", "rev-parse", "HEAD")
    assert run("git", "merge-base", FORMAL_BASE, head) == FORMAL_BASE
    assert run("git", "rev-parse", f"{EVIDENCE_BASE}^{{tree}}") == EVIDENCE_TREE
    changed = run(
        "git", "-c", "core.quotePath=false", "diff", "--name-only", f"{FORMAL_BASE}..{head}"
    ).splitlines()
    assert_authorized_paths(changed)
    assert not any(path.startswith(("internal/", "frontend/", "harness/", "migrations/")) for path in changed)
    assert not any(path.startswith("openspec/changes/") for path in changed)
    assert_compliant_commits(f"{FORMAL_BASE}..{head}")
    dirty = run("git", "status", "--porcelain=v1").splitlines()
    if not allow_dirty:
        assert not dirty, f"worktree is not clean: {dirty}"
    return head, changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-dirty", action="store_true", help="permit staged/untracked pack files before the final commit")
    args = parser.parse_args()

    repo = Path(run("git", "rev-parse", "--show-toplevel"))
    root = repo / "docs/insurance-kb/evidence/830-b0"
    head, changed = verify_repo_scope(repo, args.allow_dirty)

    baseline = load_json(root / "baseline/815-flow-baseline.json")
    assert baseline["flow_status"] == "PASS"
    assert baseline["schema67_quality_status"] == "DEFERRED"
    assert baseline["integration"]["815_evidence_commit"] == EVIDENCE_BASE
    assert baseline["integration"]["815_evidence_tree"] == EVIDENCE_TREE
    assert baseline["release"]["current_pass"] is True
    assert baseline["release"]["explicit_pinned_no_fallback_pass"] is True
    assert baseline["schema_wiki"]["sections"] == 7
    assert baseline["schema_wiki"]["fields"] == 67
    assert baseline["schema_wiki"]["citations"] == 17

    receipts = root / "receipts"
    visible = receipts / "c7-ui-visible-terminal.json"
    correction = receipts / "c7-ui-cache-corrected-terminal-20260831.json"
    assert sha256(visible) == baseline["receipt_authority"]["frozen_input_external_sha256"]
    assert sha256(correction) == baseline["receipt_authority"]["ui_cache_correction_external_sha256"]
    assert_receipt_self_hash(visible, "delete")
    assert_receipt_self_hash(correction, "null")
    evidence_hashes = {
        "c7-server-base.json": baseline["evidence_copies"]["c7_server_base_external_sha256"],
        "c7-server-corrected.json": baseline["evidence_copies"]["c7_server_corrected_external_sha256"],
        "c7-terminal.json": baseline["evidence_copies"]["c7_terminal_external_sha256"],
        "readonly-baseline.json": baseline["evidence_copies"]["readonly_baseline_external_sha256"],
        "c7-original-chunk-predicate.json": baseline["evidence_copies"]["original_chunk_predicate_external_sha256"],
    }
    for name, expected in evidence_hashes.items():
        assert sha256(receipts / name) == expected

    index_path = root / "runtime/c7-server-reopen-index.json"
    assert sha256(index_path) == baseline["pdf_bundle"]["citation_page_quote_index_external_sha256"]
    index = load_json(index_path)
    assert index["release_id"] == baseline["release"]["release_id"]
    assert index["activation_epoch"] == baseline["release"]["activation_epoch"]
    assert index["field_count"] == len(index["fields"]) == 67
    assert index["citation_count"] == len(index["citations"]) == 17
    for citation in index["citations"]:
        assert citation["page_number"] >= 1
        assert re.fullmatch(r"[0-9a-f]{64}", citation["quote_sha256"])
        assert re.fullmatch(r"[0-9a-f]{64}", citation["file_sha256"])
        assert citation["preview_http_status"] == citation["content_http_status"] == 200
        assert citation["projection_identity_pass"] is True
        assert citation["quote_domain_pass"] is True
        assert citation["content_matches_frozen_file"] is True
        assert citation["bbox"]["coordinate_system"] == "normalized_0_1e6"

    server_corrected = load_json(receipts / "c7-server-corrected.json")
    assert server_corrected["release_id"] == baseline["release"]["release_id"]
    assert server_corrected["activation_epoch"] == baseline["release"]["activation_epoch"]
    assert all(server_corrected["checks"].values())
    terminal = load_json(receipts / "c7-terminal.json")
    assert terminal["server_reopen"]["sections"] == 7
    assert terminal["server_reopen"]["fields"] == 67
    assert terminal["server_reopen"]["citations"] == 17
    assert terminal["runtime"]["binary_sha256"] == baseline["runtime"]["backend_binary_sha256"]

    verify_workbook(root, load_json(root / "inputs/workbook-audit.json"))
    verify_hash_recalculation(root, load_json(root / "baseline/hash-recalculation.json"))
    verify_origin_main_diff(repo, load_json(root / "integration/origin-main-diff.json"))
    verify_dispositions(load_json(root / "assets/finite-candidate-disposition.json"))
    verify_validation(load_json(root / "validation/validation-baseline.json"))
    image = load_json(root / "image-impact/image-change-impact.json")
    assert image["docker_action"] == "SKIP" and image["builds_executed"] == 0
    assert all(service["b0_affected"] is False for service in image["services"])
    branch_manifest = load_json(root / "branch-worktree/branch-worktree-manifest.json")
    verify_branch_manifest(branch_manifest, head)
    verify_closure(
        load_json(root / "closure/worktree-closure.json"),
        head,
        branch_manifest["observed_head_before_evidence_commit"],
    )
    review = (root / "review/controller-review.md").read_text(encoding="utf-8")
    assert "INDEPENDENT_REVIEW=WAITING_FOR_CONTROLLER" in review
    assert "B0_FINAL_ROUTE_DECISION=NOT_DECLARED_BY_EXECUTOR" in review

    result = {
        "contract": "weknora.830.b0-verification-result.v1",
        "status": "PASS",
        "head": head,
        "changed_paths": changed,
        "flow_status": "PASS",
        "schema67_quality_status": "DEFERRED",
        "finite_candidate_counts": EXPECTED_DISPOSITIONS,
        "finite_candidate_unclassified": 0,
        "docker_action": "SKIP",
        "services_started": 0,
        "images_built": 0,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as error:
        print(json.dumps({"contract": "weknora.830.b0-verification-result.v1", "status": "FAIL", "reason": str(error)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1)
