"""Converter boundaries use independent synthetic packs and document fixtures."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.eval.catalog import load_catalog
from insurance_harness.eval.convert import golden_from_legacy, predictions_from_candidate


def catalog_data() -> dict[str, Any]:
    return {"entries": [
        {"pack": {"display_name": "甲险", "schema_pack_id": "pack-a", "fields": [
            {"short_title": "等待期", "field_key": "waiting"},
            {"short_title": "续保", "field_key": "renewal"},
        ]}},
        {"pack": {"display_name": "乙险", "schema_pack_id": "pack-b", "fields": [
            {"short_title": "等待期", "field_key": "delay"},
        ]}},
    ]}


def write_catalog(tmp_path: Path, data: Any = None) -> Path:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog_data() if data is None else data), encoding="utf-8")
    return path


def legacy_row(**changes: Any) -> dict[str, Any]:
    return dict({
        "product_id": "p1", "product_name": "甲产品", "doc": "条款.pdf",
        "field_name": "等待期", "tri_state": "present", "value": "90天",
        "evidence": [{"page": 2, "quote": "等待期90天"}], "reasoning": "原说明",
    }, **changes)


def write_legacy(tmp_path: Path, rows: list[dict[str, Any]]) -> tuple[Path, Path]:
    source = tmp_path / "legacy-source"
    source.mkdir(exist_ok=True)
    path = source / "records.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    root = tmp_path / "dataset"
    for name in ("甲产品", "乙产品"):
        (root / name).mkdir(parents=True, exist_ok=True)
        (root / name / "条款.pdf").write_bytes(name.encode())
    return path, root


def candidate_data() -> dict[str, Any]:
    return {
        "request": {"entity_bindings": [
            {"entity_id": "e1", "display_name": "甲 产\t品", "schema_pack_id": "pack-a"},
            {"entity_id": "e2", "display_name": "乙产品", "schema_pack_id": "pack-b"},
        ]},
        "compile_result": {"output": {"fields": [
            {"entity_id": "e1", "field_key": "waiting", "state": "present", "value": "90天"},
            {"entity_id": "e2", "field_key": "delay", "state": "unknown", "value": None},
        ]}},
    }


def test_catalog_preserves_pack_scope_and_exact_titles(tmp_path: Path) -> None:
    catalog = load_catalog(write_catalog(tmp_path))
    assert catalog.pack_id("甲险") == "pack-a"
    assert catalog.field_key("pack-a", "等待期") == "waiting"
    assert catalog.field_key("pack-b", "等待期") == "delay"
    assert catalog.field_key("pack-a", "等待 期") is None
    assert catalog.fields("pack-a") == ("waiting", "renewal")
    with pytest.raises(ValueError):
        catalog.pack_id("甲 险")
    with pytest.raises(ValueError):
        catalog.fields("missing")


@pytest.mark.parametrize("mutation", ["pack_name", "pack_id", "field_name", "field_key"])
def test_catalog_rejects_ambiguous_identifiers(tmp_path: Path, mutation: str) -> None:
    data = catalog_data()
    first, second = [entry["pack"] for entry in data["entries"]]
    if mutation.startswith("pack_"):
        key = "display_name" if mutation == "pack_name" else "schema_pack_id"
        second[key] = first[key]
    else:
        key = "short_title" if mutation == "field_name" else "field_key"
        first["fields"][1][key] = first["fields"][0][key]
    with pytest.raises(ValueError):
        load_catalog(write_catalog(tmp_path, data))


@pytest.mark.parametrize("data", [{}, {"entries": {}}, {"entries": [None]},
                                   {"entries": [{"pack": {}}]}])
def test_catalog_rejects_malformed_structure(tmp_path: Path, data: Any) -> None:
    with pytest.raises(ValueError):
        load_catalog(write_catalog(tmp_path, data))


def test_legacy_hashes_documents_preserves_notes_and_reports_unmapped(tmp_path: Path) -> None:
    rows = [legacy_row(), legacy_row(product_id="p2", product_name="乙产品",
                                    field_name="续保", tri_state="absent_explicitly",
                                    value="不保证续保"),
            legacy_row(field_name="等待 期")]
    path, root = write_legacy(tmp_path, rows)
    result = golden_from_legacy(path, load_catalog(write_catalog(tmp_path)), "甲险", root)
    assert len(result.items) == 2
    assert result.unmapped == ["等待 期"]
    first, absent = result.items
    assert first.identity == ("pack-a", "p1", "waiting")
    assert first.evidence[0].document_sha256 == hashlib.sha256("甲产品".encode()).hexdigest()
    assert absent.evidence[0].document_sha256 == hashlib.sha256("乙产品".encode()).hexdigest()
    assert first.judged_by == "legacy:legacy-source"
    assert absent.value is None and absent.state == "absent_explicitly"
    assert absent.note and "不保证续保" in absent.note and "原说明" in absent.note


def test_legacy_unknown_does_not_require_document_on_disk(tmp_path: Path) -> None:
    path, root = write_legacy(tmp_path, [legacy_row(
        tri_state="unknown", value=None, evidence=[], doc="missing.pdf")])
    result = golden_from_legacy(path, load_catalog(write_catalog(tmp_path)), "乙险", root)
    assert result.items[0].identity == ("pack-b", "p1", "delay")
    assert result.items[0].evidence == []


@pytest.mark.parametrize("changes", [
    {"tri_state": "unknown", "value": "invented", "evidence": []},
    {"tri_state": "unknown", "value": None},
    {"value": None}, {"evidence": []}, {"evidence": {}},
    {"evidence": [{"page": 0, "quote": "text"}]},
    {"tri_state": "other"}, {"product_id": ""},
])
def test_legacy_rejects_invalid_records(tmp_path: Path, changes: dict[str, Any]) -> None:
    path, root = write_legacy(tmp_path, [legacy_row(**changes)])
    with pytest.raises(ValueError):
        golden_from_legacy(path, load_catalog(write_catalog(tmp_path)), "甲险", root)


@pytest.mark.parametrize("component", ["doc", "product_name"])
def test_legacy_rejects_path_escape(tmp_path: Path, component: str) -> None:
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"private")
    path, root = write_legacy(tmp_path, [legacy_row(**{component: str(outside)})])
    with pytest.raises(ValueError, match="path|outside|relative"):
        golden_from_legacy(path, load_catalog(write_catalog(tmp_path)), "甲险", root)


def test_legacy_rejects_symlink_escape(tmp_path: Path) -> None:
    path, root = write_legacy(tmp_path, [legacy_row(doc="escape.pdf")])
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"private")
    (root / "甲产品" / "escape.pdf").symlink_to(outside)
    with pytest.raises(ValueError, match="path|outside"):
        golden_from_legacy(path, load_catalog(write_catalog(tmp_path)), "甲险", root)


def test_legacy_rejects_duplicate_identity(tmp_path: Path) -> None:
    path, root = write_legacy(tmp_path, [legacy_row(), legacy_row()])
    with pytest.raises(ValueError, match="duplicate"):
        golden_from_legacy(path, load_catalog(write_catalog(tmp_path)), "甲险", root)


def test_candidate_maps_all_products_with_whitespace_normalization() -> None:
    predictions = predictions_from_candidate(candidate_data(), {"甲产品": "p1", "乙 产 品": "p2"})
    assert [p.identity for p in predictions] == [("pack-a", "p1", "waiting"),
                                                ("pack-b", "p2", "delay")]
    assert predictions[1].value is None


def test_candidate_reports_all_unknown_even_unused_bindings() -> None:
    candidate = candidate_data()
    candidate["compile_result"]["output"]["fields"] = []
    with pytest.raises(ValueError) as exc:
        predictions_from_candidate(candidate, {})
    assert "甲" in str(exc.value) and "乙产品" in str(exc.value)


def test_candidate_canonicalizes_legacy_absent_value() -> None:
    candidate = candidate_data()
    candidate["compile_result"]["output"]["fields"][0].update(
        state="absent_explicitly", value="不保证续保")
    predictions = predictions_from_candidate(candidate, {"甲产品": "p1", "乙产品": "p2"})
    assert predictions[0].state == "absent_explicitly" and predictions[0].value is None


@pytest.mark.parametrize("mutation", ["unknown_entity", "duplicate_field", "duplicate_entity",
                                       "duplicate_name", "unknown_value", "unknown_evidence",
                                       "present_empty", "fields_dict", "bindings_dict"])
def test_candidate_rejects_ambiguous_or_malformed_inputs(mutation: str) -> None:
    candidate = candidate_data()
    bindings = candidate["request"]["entity_bindings"]
    fields = candidate["compile_result"]["output"]["fields"]
    if mutation == "unknown_entity":
        fields[0]["entity_id"] = "missing"
    elif mutation == "duplicate_field":
        fields.append(fields[0].copy())
    elif mutation == "duplicate_entity":
        bindings[1]["entity_id"] = "e1"
    elif mutation == "duplicate_name":
        bindings[1]["display_name"] = "甲产品"
    elif mutation == "unknown_value":
        fields[1]["value"] = "invented"
    elif mutation == "unknown_evidence":
        fields[1]["evidence"] = [{"page_number": 1, "quote": "invented"}]
    elif mutation == "present_empty":
        fields[0]["value"] = ""
    elif mutation == "fields_dict":
        candidate["compile_result"]["output"]["fields"] = {}
    else:
        candidate["request"]["entity_bindings"] = {}
    with pytest.raises(ValueError):
        predictions_from_candidate(candidate, {"甲产品": "p1", "乙产品": "p2"})


def test_candidate_rejects_conflicting_normalized_registration() -> None:
    with pytest.raises(ValueError):
        predictions_from_candidate(candidate_data(),
                                   {"甲产品": "p1", "甲 产品": "conflict", "乙产品": "p2"})
