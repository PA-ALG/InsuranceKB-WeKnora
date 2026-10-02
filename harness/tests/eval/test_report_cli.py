"""Exercise the offline report command at its file boundary."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


def _write(path: Path, data: Any) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _golden(pack: str, product: str, key: str, state: str = "present") -> dict[str, Any]:
    return {
        "pack_id": pack, "product_id": product, "field_key": key, "state": state,
        "value": "expected" if state == "present" else None, "judged_by": "human:tester",
        "evidence": [] if state == "unknown" else [{
            "document": "terms.pdf", "document_sha256": "a" * 64, "page": 1, "quote": "text",
        }],
    }


@pytest.fixture
def inputs(tmp_path: Path) -> dict[str, Path]:
    golden = tmp_path / "golden.jsonl"
    rows = [
        _golden("pack-a", "product-a", "shared"),
        _golden("pack-a", "product-a", "miss"),
        _golden("pack-a", "product-a", "no-row"),
        _golden("pack-b", "product-b", "shared", "unknown"),
        _golden("pack-b", "product-b", "negative", "absent_explicitly"),
    ]
    golden.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    candidate = {
        "request": {"entity_bindings": [
            {"entity_id": "a", "display_name": "Product A", "schema_pack_id": "pack-a"},
            {"entity_id": "b", "display_name": "Product B", "schema_pack_id": "pack-b"},
        ]},
        "compile_result": {"execution": {
            "implementation": "archived.compiler", "model_id": "supplied-model",
            "api_key": "secret-do-not-copy", "raw_output": "private-raw-output",
        }, "output": {"fields": [
            {"entity_id": "a", "field_key": "shared", "state": "present", "value": "expected"},
            {"entity_id": "a", "field_key": "miss", "state": "unknown", "value": None},
            {"entity_id": "b", "field_key": "shared", "state": "unknown", "value": None},
            {"entity_id": "b", "field_key": "negative", "state": "present", "value": "wrong"},
            {"entity_id": "b", "field_key": "outside", "state": "present", "value": "unscored"},
        ]}},
    }
    return {
        "golden": golden,
        "candidate": _write(tmp_path / "candidate.json", candidate),
        "product-map": _write(tmp_path / "products.json", {
            "Product A": "product-a", "Product B": "product-b",
        }),
    }


def _run(inputs: dict[str, Path], out: Path) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, "-m", "insurance_harness.eval.report", "--out", str(out)]
    for option, path in inputs.items():
        args.extend([f"--{option}", str(path)])
    return subprocess.run(args, text=True, capture_output=True, check=False)


def test_report_counters_pack_gates_and_scoped_rows(
    inputs: dict[str, Path], tmp_path: Path,
) -> None:
    out = tmp_path / "result"
    result = _run(inputs, out)
    assert result.returncode == 0, result.stderr  # Gate failure still writes a usable report.
    data = json.loads(out.with_suffix(".json").read_text())
    assert data["report"]["micro"] == {
        "tp": 1, "fp": 1, "fn": 2, "hallucinations": 0,
        "precision": 0.5, "recall": 1 / 3,
    }
    assert data["counts"]["missed"] == 2
    assert data["counts"]["missing_predictions"] == 1
    assert data["counts"]["contradictions"] == 1
    assert data["counts"]["correct_non_present"] == 1
    assert data["counts"]["unscored_predictions"] == 1
    assert len(data["scored_items"]) == 5
    assert len(data["report"]["outcomes"]) == 6
    shared = [row for row in data["scored_items"] if row["field_key"] == "shared"]
    assert {(row["pack_id"], row["product_id"]) for row in shared} == {
        ("pack-a", "product-a"), ("pack-b", "product-b"),
    }
    assert data["gates"]["pack-a"]["reasons"] == ["recall_below"]
    assert data["gates"]["pack-b"]["reasons"] == ["precision_below", "recall_undefined"]
    markdown = out.with_suffix(".md").read_text()
    assert "| outside |" not in markdown
    assert "no-row" in markdown and "pack-b" in markdown
    assert "missing_predictions: 1" in markdown and "missed: 2" in markdown
    assert "TP / (TP + FP)" in markdown and "TP / (TP + FN)" in markdown


def test_provenance_hashes_metadata_and_determinism(
    inputs: dict[str, Path], tmp_path: Path,
) -> None:
    manifest = _write(tmp_path / "manifest.json", {
        "dataset_version": "test-v1", "files": {
            "golden.jsonl": hashlib.sha256(inputs["golden"].read_bytes()).hexdigest(),
        }, "private_path": "/private/do-not-copy",
    })
    assert _run(inputs, tmp_path / "first").returncode == 0
    assert _run(inputs, tmp_path / "second").returncode == 0
    for suffix in (".json", ".md"):
        assert (tmp_path / f"first{suffix}").read_bytes() == (
            tmp_path / f"second{suffix}"
        ).read_bytes()
    text = (tmp_path / "first.json").read_text()
    data = json.loads(text)
    for name, path in inputs.items():
        assert data["provenance"][name]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    metadata = data["provenance"]["manifest"]
    assert metadata["sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert metadata["supplied_dataset_version"] == "test-v1"
    assert metadata["golden_digest_verified"] is True
    assert data["provenance"]["supplied_candidate_metadata"]["compile_result"] == {
        "implementation": "archived.compiler", "model_id": "supplied-model",
    }
    for secret in ("secret-do-not-copy", "private-raw-output", "/private/do-not-copy"):
        assert secret not in text
    assert "offline" in data["scope"].lower()


def test_unknown_only_has_undefined_ratios(inputs: dict[str, Path], tmp_path: Path) -> None:
    inputs["golden"].write_text(json.dumps(_golden("pack-b", "product-b", "shared", "unknown")))
    assert _run(inputs, tmp_path / "out").returncode == 0
    data = json.loads((tmp_path / "out.json").read_text())
    assert data["report"]["micro"]["precision"] is None
    assert data["report"]["micro"]["recall"] is None
    assert data["scored_items"][0]["precision"] is None
    assert data["gates"]["pack-b"]["reasons"] == ["precision_undefined", "recall_undefined"]
    assert "—" in (tmp_path / "out.md").read_text()


@pytest.mark.parametrize("invalid", ["empty", "json", "shape", "map", "unknown", "manifest"])
def test_invalid_input_writes_nothing(
    inputs: dict[str, Path], tmp_path: Path, invalid: str,
) -> None:
    if invalid == "empty":
        inputs["golden"].write_text("\n")
    elif invalid == "json":
        inputs["candidate"].write_text('{"password":"private-value",')
    elif invalid == "shape":
        _write(inputs["candidate"], [])
    elif invalid == "map":
        _write(inputs["product-map"], [])
    elif invalid == "unknown":
        _write(inputs["product-map"], {"Product A": "product-a"})
    else:
        _write(tmp_path / "manifest.json", {"files": {"golden.jsonl": "0" * 64}})
    result = _run(inputs, tmp_path / "out")
    assert result.returncode == 2
    assert "private-value" not in result.stderr and str(tmp_path) not in result.stderr
    assert not (tmp_path / "out.json").exists()
    assert not (tmp_path / "out.md").exists()


@pytest.mark.parametrize("collision", ["candidate", "mapping", "manifest", "symlink", "hardlink"])
def test_output_collision_never_changes_inputs(
    inputs: dict[str, Path], tmp_path: Path, collision: str,
) -> None:
    out = tmp_path / "out"
    if collision == "candidate":
        out = tmp_path / "candidate"
    elif collision == "mapping":
        out = tmp_path / "products"
    elif collision == "manifest":
        _write(tmp_path / "manifest.json", {"dataset_version": "v1"})
        out = tmp_path / "manifest"
    elif collision == "symlink":
        (tmp_path / "out.md").symlink_to(inputs["golden"])
    else:
        (tmp_path / "out.md").hardlink_to(inputs["golden"])
    before = {path: path.read_bytes() for path in inputs.values()}
    assert _run(inputs, out).returncode == 2
    assert all(path.read_bytes() == content for path, content in before.items())
    if collision in ("symlink", "hardlink"):
        assert not (tmp_path / "out.json").exists()


def test_markdown_escapes_untrusted_identifiers(inputs: dict[str, Path], tmp_path: Path) -> None:
    row = _golden("pack-a", "product-a", "pipe|<script>\nnext")
    inputs["golden"].write_text(json.dumps(row))
    assert _run(inputs, tmp_path / "out").returncode == 0
    markdown = (tmp_path / "out.md").read_text()
    assert "pipe\\|&lt;script&gt;<br>next" in markdown
    assert "<script>" not in markdown


def test_output_within_repository_is_rejected(inputs: dict[str, Path]) -> None:
    # An unwritten path in the actual repository: the command must not create it.
    out = Path(__file__).resolve().parents[2] / "forbidden-eval-output"
    result = _run(inputs, out)
    assert result.returncode == 2
    assert not Path(f"{out}.json").exists()
    assert not Path(f"{out}.md").exists()
