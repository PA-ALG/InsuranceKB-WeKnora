"""019 spec Q1.1/Q1.2：可移植 release 汇总器 + 混合标注保留（严格 TDD，先红后绿）。"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from insurance_harness.goldenset import (
    ProductPlan,
    assemble_records,
)
from insurance_harness.goldenset.assemble import (
    load_product_plans,
)
from insurance_harness.goldenset.assemble import (
    main as assemble_main,
)
from insurance_harness.goldenset.release import build_release
from insurance_harness.schemas import (
    FieldSpec,
    ProductLineSchema,
    SchemaRegistry,
    load_schema_registry,
)
from tests.conftest import SCHEMA_BASELINE_DIR

_LINE = ProductLineSchema(
    line_key="t",
    sheet_name="测试",
    fields=(
        FieldSpec(name="犹豫期", field_id="hesitation_period", source_sheet="t"),
        FieldSpec(name="等待期", field_id="waiting_period", source_sheet="t"),
    ),
)
_REGISTRY = SchemaRegistry(
    version="v1.1+deadbeefcafe", lines={"t": _LINE}, glossary=()
)


def _write_golden(workspace: Path, product: str, rows: list[dict[str, object]]) -> None:
    pdir = workspace / product
    pdir.mkdir(parents=True)
    pdir.joinpath("golden.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )


def _row(field_id: str, value: str, annotator: str) -> dict[str, object]:
    return {
        "field_id": field_id,
        "value": value,
        "tri_state": "present",
        "evidence": [{"page": 1, "quote": value}],
        "annotator_model": annotator,
        "created_at": "2026-07-11T00:00:00+00:00",
    }


def _plans(*products: str) -> list[ProductPlan]:
    return [ProductPlan(product=p, line_key="t") for p in products]


# ------------------------------------------------------------- Q1.2 混合标注

def test_q1_2_mixed_annotators_are_not_overwritten(tmp_path: Path) -> None:
    ws = tmp_path / "wip"
    _write_golden(ws, "prodA", [_row("hesitation_period", "20日", "model-a")])
    _write_golden(ws, "prodB", [_row("waiting_period", "90天", "model-b")])
    records, report = assemble_records(
        ws, _REGISTRY, _plans("prodA", "prodB"),
        default_annotator="GLOBAL-SHOULD-NOT-WIN",
    )
    assert {r.product_name: r.annotator_model for r in records} == {
        "prodA": "model-a", "prodB": "model-b"
    }
    assert "GLOBAL-SHOULD-NOT-WIN" not in {r.annotator_model for r in records}
    assert sorted(p.annotator_models for p in report) == [["model-a"], ["model-b"]]


def test_q1_2_default_annotator_only_fills_missing(tmp_path: Path) -> None:
    ws = tmp_path / "wip"
    row: dict[str, object] = {
        "field_id": "hesitation_period", "value": "20日", "tri_state": "present",
        "evidence": [{"page": 1, "quote": "20日"}],
    }
    _write_golden(ws, "prodA", [row])
    records, _ = assemble_records(
        ws, _REGISTRY, _plans("prodA"), default_annotator="fallback-model"
    )
    assert records[0].annotator_model == "fallback-model"


def test_q1_2_missing_annotator_without_default_fails(tmp_path: Path) -> None:
    ws = tmp_path / "wip"
    row: dict[str, object] = {
        "field_id": "hesitation_period", "value": "20日", "tri_state": "present",
    }
    _write_golden(ws, "prodA", [row])
    with pytest.raises(ValueError, match="annotator_model"):
        assemble_records(ws, _REGISTRY, _plans("prodA"))


# ------------------------------------------------------------- Q1.2 字段透传

def test_q1_2_created_at_preserved_from_source(tmp_path: Path) -> None:
    ws = tmp_path / "wip"
    _write_golden(ws, "prodA", [_row("hesitation_period", "20日", "model-a")])
    records, _ = assemble_records(ws, _REGISTRY, _plans("prodA"))
    assert records[0].created_at == datetime(2026, 7, 11, tzinfo=UTC)


def test_q1_2_schema_version_falls_back_to_registry(tmp_path: Path) -> None:
    ws = tmp_path / "wip"
    row = _row("hesitation_period", "20日", "model-a")  # 无 schema_version
    _write_golden(ws, "prodA", [row])
    records, _ = assemble_records(ws, _REGISTRY, _plans("prodA"))
    assert records[0].schema_version == "v1.1+deadbeefcafe"


# ------------------------------------------------------------- 坏行/空行

def test_q1_bad_and_out_of_schema_lines_counted_not_kept(tmp_path: Path) -> None:
    ws = tmp_path / "wip"
    good = _row("hesitation_period", "20日", "model-a")
    bad_json = "{not json"
    out_of_schema = json.dumps(_row("no_such_field", "x", "model-a"))
    pdir = ws / "prodA"
    pdir.mkdir(parents=True)
    pdir.joinpath("golden.jsonl").write_text(
        json.dumps(good) + "\n" + bad_json + "\n" + out_of_schema + "\n",
        encoding="utf-8",
    )
    records, report = assemble_records(ws, _REGISTRY, _plans("prodA"))
    assert len(records) == 1
    assert report[0].bad_lines == 2


def test_q1_bracket_and_blank_lines_ignored_not_bad(tmp_path: Path) -> None:
    ws = tmp_path / "wip"
    pdir = ws / "prodA"
    pdir.mkdir(parents=True)
    body = "[\n" + json.dumps(_row("hesitation_period", "20日", "m")) + ",\n" + "\n]\n"
    pdir.joinpath("golden.jsonl").write_text(body, encoding="utf-8")
    records, report = assemble_records(ws, _REGISTRY, _plans("prodA"))
    assert len(records) == 1 and report[0].bad_lines == 0


# ------------------------------------------------------------- Q1.1 manifest / 缺失

def test_q1_1_manifest_aggregates_annotator_set(tmp_path: Path) -> None:
    ws = tmp_path / "wip"
    _write_golden(ws, "prodA", [_row("hesitation_period", "20日", "model-a")])
    _write_golden(ws, "prodB", [_row("waiting_period", "90天", "model-b")])
    out = tmp_path / "gs-v0.1"
    records, _ = assemble_records(ws, _REGISTRY, _plans("prodA", "prodB"))
    build_release(records, out, dataset_root="dataset/x")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["annotator_models"] == ["model-a", "model-b"]
    assert manifest["products"]["prodA"]["annotator_models"] == ["model-a"]


def test_q1_1_missing_golden_marked_not_dropped(tmp_path: Path) -> None:
    ws = tmp_path / "wip"
    _write_golden(ws, "prodA", [_row("hesitation_period", "20日", "model-a")])
    _, report = assemble_records(ws, _REGISTRY, _plans("prodA", "prodMissing"))
    missing = next(p for p in report if p.product == "prodMissing")
    assert missing.status == "missing_golden" and missing.records == 0
    assert missing.missing_fields == 2  # 两个 extractable 字段全缺


# ------------------------------------------------------------- load_product_plans

def test_q1_load_product_plans_reads_workspace_manifest(tmp_path: Path) -> None:
    ws = tmp_path / "wip"
    ws.mkdir()
    ws.joinpath("manifest.json").write_text(
        json.dumps({"products": [
            {"product": "prodA", "line_key": "whole-life"},
            {"product": "prodB", "line_key": "annuity"},
        ]}),
        encoding="utf-8",
    )
    plans = load_product_plans(ws)
    assert [(p.product, p.line_key) for p in plans] == [
        ("prodA", "whole-life"), ("prodB", "annuity")
    ]


# ------------------------------------------------------------- CLI（Q1.5）

def test_q1_5_cli_end_to_end_no_credentials(tmp_path: Path) -> None:
    registry = load_schema_registry(SCHEMA_BASELINE_DIR)
    fid = registry.line("whole-life").fields[0].field_id
    ws = tmp_path / "wip"
    _write_golden(ws, "prodA", [_row(fid, "示例值", "model-a")])
    ws.joinpath("manifest.json").write_text(
        json.dumps({"products": [{"product": "prodA", "line_key": "whole-life"}]}),
        encoding="utf-8",
    )
    out = tmp_path / "release"
    code = assemble_main(
        ["--workspace", str(ws), "--out", str(out),
         "--schema-dir", str(SCHEMA_BASELINE_DIR)]
    )
    assert code == 0
    assert (out / "manifest.json").exists()
    report = json.loads((out / "assemble-report.json").read_text(encoding="utf-8"))
    assert report["annotator_models"] == ["model-a"]
    assert report["total_records"] == 1
