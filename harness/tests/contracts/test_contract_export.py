"""S3a acceptance: the exported contract is the only definition (blueprint §5, §8 G9).

Protected file: written by Claude. It pins the two public entry points and the
three-state invariants, then checks that what is on disk is byte-identical to
what the models produce. Nothing here reads the repository's own contracts/
directory or touches the network; every case builds its own destination.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from insurance_harness.contracts import CandidateBundle, Claim, Evidence, Locator
from insurance_harness.contracts.export import check, export

SHA = "a" * 64


def citation(**overrides: Any) -> Evidence:
    """A present-state citation on a PDF text span, with overridable pieces."""
    fields: dict[str, Any] = {
        "source_ref": "保险条款.pdf",
        "file_sha256": SHA,
        "locator": Locator(kind="PDF_TEXT_SPAN", page=3, start=10, end=18),
        "quote": "等待期为90日",
        "match": "EXACT",
        "access_scope": "internal",
    }
    fields.update(overrides)
    return Evidence(**fields)


def claim(**overrides: Any) -> Claim:
    """A minimal Claim; everything the test does not care about must default."""
    fields: dict[str, Any] = {
        "claim_id": "c-1",
        "logical_key": "596-1:waiting_period",
        "subject_ref": "product_version:596-1",
        "product_version_ref": "596-1",
        "predicate": "waiting_period",
        "state": "present",
        "value": "90日",
        "evidence": [citation()],
        "origin": "SOURCE_SUPPORTED",
    }
    fields.update(overrides)
    return Claim(**fields)


# ---- three-state invariants ---------------------------------------------------------------


def test_present_requires_a_value_and_verified_evidence() -> None:
    assert claim().state == "present"
    with pytest.raises(ValidationError):
        claim(value=None)
    with pytest.raises(ValidationError):
        claim(evidence=[])


def test_absent_explicitly_requires_empty_value_and_negative_evidence() -> None:
    absent = claim(
        state="absent_explicitly", value=None, evidence=[citation(quote="本产品不设等待期")]
    )
    assert absent.value is None
    with pytest.raises(ValidationError):
        claim(state="absent_explicitly", value="90日", evidence=[citation()])
    with pytest.raises(ValidationError):
        claim(state="absent_explicitly", value=None, evidence=[])


def test_unknown_carries_no_value_no_evidence_and_a_typed_reason() -> None:
    unknown = claim(state="unknown", value=None, evidence=[], unknown_reason="NOT_IN_MATERIAL")
    assert unknown.evidence == []
    with pytest.raises(ValidationError):
        claim(state="unknown", value=None, evidence=[citation()])
    with pytest.raises(ValidationError):
        claim(state="unknown", value=None, evidence=[])


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        claim(surprise="x")
    with pytest.raises(ValidationError):
        Locator(kind="PDF_TEXT_SPAN", page=1, start=0, end=1, surprise="x")


def test_bundle_declares_the_contract_version() -> None:
    bundle = CandidateBundle(
        contract_version="1",
        origin="compile",
        compiler_identity="harness/test",
        members=[],
        removals=[],
        review_plan=[],
    )
    assert bundle.contract_version == "1"


# ---- export and drift detection ------------------------------------------------------------


def test_export_is_deterministic_and_check_accepts_it(tmp_path: Path) -> None:
    first = export(tmp_path / "a")
    second = export(tmp_path / "b")
    assert first, "export must write at least one schema"
    assert [p.name for p in first] == [p.name for p in second]
    for left, right in zip(first, second, strict=True):
        assert left.read_bytes() == right.read_bytes(), f"{left.name} is not deterministic"
    assert check(tmp_path / "a") == []


def test_schemas_are_json_with_refs(tmp_path: Path) -> None:
    paths = export(tmp_path)
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["$schema"].startswith("https://json-schema.org/")
        assert "$defs" in document or "properties" in document
    bundle = next(p for p in paths if p.name == "candidate_bundle.schema.json")
    assert "$ref" in bundle.read_text(encoding="utf-8") or "members" in bundle.read_text(
        encoding="utf-8"
    )


def test_one_changed_byte_is_reported(tmp_path: Path) -> None:
    export(tmp_path)
    target = sorted(tmp_path.glob("*.schema.json"))[0]
    target.write_text(target.read_text(encoding="utf-8").replace(":", ": ", 1), encoding="utf-8")
    assert check(tmp_path) == [target.name]


def test_a_deleted_file_is_reported(tmp_path: Path) -> None:
    export(tmp_path)
    target = sorted(tmp_path.glob("*.schema.json"))[0]
    target.unlink()
    assert check(tmp_path) == [target.name]


def test_a_stray_schema_is_reported(tmp_path: Path) -> None:
    export(tmp_path)
    (tmp_path / "extra.schema.json").write_text("{}\n", encoding="utf-8")
    assert check(tmp_path) == ["extra.schema.json"]


def test_check_leaves_the_directory_alone(tmp_path: Path) -> None:
    export(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    check(tmp_path)
    after = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert before == after
