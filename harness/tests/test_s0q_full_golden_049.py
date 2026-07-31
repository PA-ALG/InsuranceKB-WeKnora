"""OpenSpec 049: freeze one reviewed 60-field S0-Q Golden release."""

from __future__ import annotations

import copy
import errno
import hashlib
import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "harness" / "scripts" / "freeze_s0q_full_golden_049.py"
PASS_IDS = {
    "candidate": "049-blind-candidate-a",
    "review": "049-blind-review-b",
}
MANDATORY = {
    "regulatory_filing_no",
    "clause_version",
    "clause_effective_date",
    "exclusions_official",
    "pre_existing_conditions",
    "discontinuation_renewal",
}
SOURCE_ROWS = [
    {
        "name": "保险条款.pdf",
        "path": "dataset/shouxian_product/平安e生保（尊享版）医疗保险/保险条款.pdf",
        "size": 1_047_811,
        "sha256": "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
    },
    {
        "name": "产品说明书.pdf",
        "path": "dataset/shouxian_product/平安e生保（尊享版）医疗保险/产品说明书.pdf",
        "size": 492_101,
        "sha256": "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
    },
    {
        "name": "费率表.pdf",
        "path": "dataset/shouxian_product/平安e生保（尊享版）医疗保险/费率表.pdf",
        "size": 51_961,
        "sha256": "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
    },
]

@pytest.fixture(scope="module")
def mod() -> ModuleType:
    spec = importlib.util.spec_from_file_location("freeze_s0q_full_golden_049", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def _sha(value: object) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(raw).hexdigest()

def _inputs(module: ModuleType) -> Any:
    return module.load_inputs()

def _quote(inputs: Any) -> str:
    text = inputs.pages["保险条款.pdf"][1]
    result = next(part for part in text.splitlines() if len(part.strip()) >= 8)
    return cast(str, result.strip())

def _rows(inputs: Any, *, changed: str | None = None) -> list[dict[str, object]]:
    quote = _quote(inputs)
    rows: list[dict[str, object]] = []
    for field_id, field_name in inputs.fields.items():
        value = f"value-{field_id}" + ("-review" if field_id == changed else "")
        rows.append(
            {
                "field_id": field_id,
                "field_name": field_name,
                "value": value,
                "tri_state": "present",
                "evidence": [
                    {"doc": "保险条款.pdf", "page": 1, "quote": quote}
                ],
                "reasoning": "blind evidence",
                "annotator_model": "gpt-5.6-sol",
            }
        )
    return rows

def _contract_preimage(inputs: Any, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    refs = [
        f"schema:{inputs.schema_authority_sha256}",
        "product:596",
        "product-version:596-1",
        *(f"pdf:{row['sha256']}" for row in SOURCE_ROWS),
    ]
    prompt = {
        "mission": "049-s0q-full-golden-freeze",
        "pass_id": PASS_IDS[role],
        "model": "gpt-5.6-sol",
        "field_ids": sorted(inputs.fields),
        "input_refs": refs,
        "rules": [
            "exact60",
            "tri-state",
            "exact-pdf-evidence",
            "no-prior-answers",
        ],
    }
    payload = {
        "schema_version": inputs.schema_version,
        "fields": [
            {"field_id": key, "field_name": inputs.fields[key]}
            for key in sorted(inputs.fields)
        ],
        "sources": SOURCE_ROWS,
    }
    return prompt, payload

def _run(inputs: Any, role: str, rows: list[dict[str, object]]) -> dict[str, Any]:
    prompt, payload = _contract_preimage(inputs, role)
    return {
        "pass_id": PASS_IDS[role],
        "model": "gpt-5.6-sol",
        "batch_count": 6,
        "parse_retries": 0,
        "prompt_sha256": _sha(prompt),
        "input_sha256": _sha(payload),
        "output_sha256": _sha(rows),
        "input_refs": prompt["input_refs"],
    }

def _review(module: ModuleType, *, changed: str | None = None) -> dict[str, object]:
    inputs = _inputs(module)
    candidate, review = _rows(inputs), _rows(inputs, changed=changed)
    return cast(dict[str, object], module.build_review(
        candidate,
        review,
        _run(inputs, "candidate", candidate),
        _run(inputs, "review", review),
    ))

def _decisions(report: dict[str, object]) -> dict[str, object]:
    required = report["required_human_fields"]
    assert isinstance(required, list)
    return {
        "review_hash": report["review_hash"],
        "decisions": [
            {"field_id": field_id, "choice": "candidate", "reason": "checked"}
            for field_id in required
        ],
    }

def _receipt(resolved: dict[str, object]) -> dict[str, object]:
    return {
        "receipt_type": "total-control-human-approval.v1",
        "issued_by": "total-control",
        "actor_type": "human",
        "approved_by": "named-reviewer",
        "action": "approve",
        "reason": "exact 60-field subject approved",
        "approved_at": "2026-07-31T02:00:00Z",
        "subject_sha256": resolved["approval_subject"],
        "release_hash": resolved["release_hash"],
        "artifact_hash": resolved["artifact_hash"],
        "source_thread_id": "019fa5ea-2507-73a2-acb8-d49030bad2f0",
        "conversation_id": "019fa5ea-2507-73a2-acb8-d49030bad2f0",
        "user_approval_ref": "user-message:explicit-049-row-approval",
    }

def test_schema_sources(mod: ModuleType) -> None:
    inputs = _inputs(mod)
    assert len(inputs.fields) == 60
    assert inputs.authority_counts == {
        "workbook_authoritative": 49,
        "v1_1_extensions": 11,
    }
    assert inputs.sources == SOURCE_ROWS
    assert mod.load_inputs() is inputs

def test_blind_identity(mod: ModuleType) -> None:
    inputs = _inputs(mod)
    candidate, review = _rows(inputs), _rows(inputs)
    for role in PASS_IDS:
        prompt, payload = _contract_preimage(inputs, role)
        assert mod.blind_contract(role) == {
            "pass_id": PASS_IDS[role],
            "model": "gpt-5.6-sol",
            "batch_count": 6,
            "prompt_sha256": _sha(prompt),
            "input_sha256": _sha(payload),
            "input_refs": prompt["input_refs"],
        }
    valid_a, valid_b = _run(inputs, "candidate", candidate), _run(inputs, "review", review)
    mutations: list[
        tuple[str, Callable[[dict[str, Any], dict[str, Any]], object]]
    ] = [
        ("same pass", lambda a, b: a.update(pass_id=b["pass_id"])),
        ("retry", lambda a, b: (a.update(parse_retries=2), b.update(parse_retries=1))),
        ("prompt", lambda a, _b: a.update(prompt_sha256="0" * 64)),
        ("input", lambda a, _b: a.update(input_sha256="0" * 64)),
        ("output", lambda a, _b: a.update(output_sha256="0" * 64)),
        ("forbidden", lambda a, _b: a["input_refs"].append("golden:old.jsonl")),
    ]
    for _label, mutate in mutations:
        run_a, run_b = copy.deepcopy(valid_a), copy.deepcopy(valid_b)
        mutate(run_a, run_b)
        with pytest.raises(mod.FreezeContractError):
            mod.build_review(candidate, review, run_a, run_b)

def test_bijection_evidence(mod: ModuleType) -> None:
    inputs = _inputs(mod)
    valid = _rows(inputs)
    for mutation in ("duplicate", "missing", "quote", "unknown-evidence"):
        candidate = copy.deepcopy(valid)
        if mutation == "duplicate":
            candidate.append(copy.deepcopy(candidate[0]))
        elif mutation == "missing":
            candidate.pop()
        elif mutation == "quote":
            candidate[0]["evidence"][0]["quote"] = "not in source"  # type: ignore[index]
        else:
            candidate[0]["tri_state"] = "unknown"
            candidate[0]["value"] = None
        with pytest.raises(mod.FreezeContractError):
            mod.build_review(
                candidate,
                valid,
                _run(inputs, "candidate", candidate),
                _run(inputs, "review", valid),
            )

def test_review_set(mod: ModuleType) -> None:
    inputs = _inputs(mod)
    changed = next(iter(inputs.fields))
    report = _review(mod, changed=changed)
    differences = cast(list[str], report["differences"])
    mandatory = cast(list[str], report["mandatory_review_fields"])
    sample = cast(list[str], report["fixed_sample_fields"])
    required = cast(list[str], report["required_human_fields"])
    assert report["status"] == "PENDING_HUMAN_REVIEW"
    assert set(differences) == {changed}
    assert set(mandatory) == MANDATORY
    assert len(sample) == 3
    assert set(required) == {changed} | MANDATORY | set(sample)

def test_custom_adjudication(mod: ModuleType) -> None:
    report = _review(mod, changed="regulatory_filing_no")
    decisions = _decisions(report)
    decision_rows = cast(list[dict[str, Any]], decisions["decisions"])
    candidate_rows = cast(list[dict[str, Any]], report["candidate_records"])
    target = decision_rows[0]
    custom = copy.deepcopy(
        next(
            row
            for row in candidate_rows
            if row["field_id"] == target["field_id"]
        )
    )
    custom["value"] = "human corrected"
    target.update(choice="custom", reason="exact evidence checked", record=custom)
    resolved = mod.resolve_review(report, decisions)
    assert any(row["value"] == "human corrected" for row in resolved["final_records"])
    for mutation in ("identity", "evidence"):
        bad = copy.deepcopy(decisions)
        bad_rows = cast(list[dict[str, Any]], bad["decisions"])
        record = cast(dict[str, Any], bad_rows[0]["record"])
        if mutation == "identity":
            record["field_name"] = "wrong"
        else:
            record["evidence"][0]["quote"] = "wrong"
        with pytest.raises(mod.FreezeContractError):
            mod.resolve_review(report, bad)

def test_approval_boundary(mod: ModuleType, tmp_path: Path) -> None:
    report, out = _review(mod), tmp_path / "release"
    decisions = _decisions(report)
    resolved = mod.resolve_review(report, decisions)
    bad_receipts: list[object] = [
        None,
        {**_receipt(resolved), "issued_by": "self"},
        {**_receipt(resolved), "user_approval_ref": "PLACEHOLDER"},
        {**_receipt(resolved), "artifact_hash": "0" * 64},
    ]
    for receipt in bad_receipts:
        with pytest.raises(mod.FreezeContractError):
            mod.freeze_release(report, decisions, receipt, out)
        assert not out.exists()

def test_freeze_artifacts(
    mod: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, decisions = _review(mod), None
    decisions = _decisions(report)
    resolved = mod.resolve_review(report, decisions)
    receipt, out = _receipt(resolved), tmp_path / "release"
    mod.freeze_release(report, decisions, receipt, out)
    assert sorted(path.name for path in out.iterdir()) == [
        "596.jsonl",
        "disputed.jsonl",
        "manifest.json",
        "review-and-approval.json",
    ]
    assert len((out / "596.jsonl").read_text(encoding="utf-8").splitlines()) == 60
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "S0_Q_FROZEN_FULL_GOLDEN_AVAILABLE"
    assert manifest["release_hash"] == resolved["release_hash"]
    assert manifest["artifact_hash"] == resolved["artifact_hash"]
    assert manifest["approval_subject"] == resolved["approval_subject"]
    assert manifest["source_documents"] == SOURCE_ROWS
    names = ("596.jsonl", "disputed.jsonl", "review-and-approval.json")
    assert manifest["files"] == {
        name: hashlib.sha256((out / name).read_bytes()).hexdigest() for name in names
    }
    with pytest.raises(FileExistsError):
        mod.freeze_release(report, decisions, receipt, out)
    raced_out, original_build = tmp_path / "raced-release", mod.build_release
    race_identity: dict[str, int] = {}

    def raced_build(records: list[Any], staging: Path, *, dataset_root: str) -> object:
        manifest = original_build(records, staging, dataset_root=dataset_root)
        raced_out.mkdir()
        race_identity["inode"] = raced_out.stat().st_ino
        return manifest

    monkeypatch.setattr(mod, "build_release", raced_build)
    with pytest.raises(FileExistsError):
        mod.freeze_release(report, decisions, receipt, raced_out)
    assert raced_out.stat().st_ino == race_identity["inode"] and not list(raced_out.iterdir())
    unsupported, target = tmp_path / "unsupported", tmp_path / "unsupported-target"
    unsupported.mkdir()
    monkeypatch.setattr(mod.sys, "platform", "unsupported")
    with pytest.raises(OSError, match="unsupported") as caught:
        mod._publish_no_replace(unsupported, target)
    assert caught.value.errno == errno.ENOTSUP and unsupported.is_dir() and not target.exists()
