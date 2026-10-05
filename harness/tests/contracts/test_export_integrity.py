"""Independent checks of portable schemas and the read-only export command."""

import json
import subprocess
import sys
from pathlib import Path

# jsonschema ships no py.typed; match the existing schema-validation tests.
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from insurance_harness.contracts.export import check, export


def test_exports_all_blueprint_contracts_in_name_order(tmp_path: Path) -> None:
    paths = export(tmp_path / "nested" / "contracts")
    assert [path.name for path in paths] == sorted(
        f"{name}.schema.json"
        for name in (
            "evidence", "locator", "entity", "claim", "relation", "qa_item",
            "expert_revision", "schema_snapshot", "page_text", "compile_task",
            "compile_result", "gap_task", "review_item", "candidate_bundle",
            "bundle_member", "review_plan",
        )
    )


def test_generated_readme_and_bundle_agree_on_version(tmp_path: Path) -> None:
    export(tmp_path)
    bundle = json.loads((tmp_path / "candidate_bundle.schema.json").read_text(encoding="utf-8"))
    version = bundle["properties"]["contract_version"]["const"]
    assert f'contract_version: "{version}"' in (tmp_path / "README.md").read_text(encoding="utf-8")


def test_exported_schemas_have_resolvable_local_refs(tmp_path: Path) -> None:
    for path in export(tmp_path):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["$id"] == (
            "https://pa-alg.github.io/InsuranceKB-WeKnora/contracts/" + path.name
        )
        for ref in local_refs(schema):
            assert ref.startswith("#/$defs/")
            assert ref.removeprefix("#/$defs/") in schema["$defs"]


def local_refs(value: object) -> list[str]:
    if isinstance(value, dict):
        refs = [value["$ref"]] if "$ref" in value else []
        return refs + [ref for nested in value.values() for ref in local_refs(nested)]
    if isinstance(value, list):
        return [ref for nested in value for ref in local_refs(nested)]
    return []


def test_check_missing_directory_does_not_create_it(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    expected = export(tmp_path / "reference")
    assert check(missing) == [path.name for path in expected]
    assert not missing.exists()


def test_export_does_not_overwrite_a_symlink_target(tmp_path: Path) -> None:
    destination = tmp_path / "contracts"
    destination.mkdir()
    outside = tmp_path / "source.txt"
    outside.write_text("keep this source intact\n", encoding="utf-8")
    (destination / "claim.schema.json").symlink_to(outside)
    export(destination)
    assert outside.read_text(encoding="utf-8") == "keep this source intact\n"
    assert not (destination / "claim.schema.json").is_symlink()
    assert check(destination) == []


def test_check_aggregates_drift_and_ignores_other_documents(tmp_path: Path) -> None:
    paths = export(tmp_path)
    paths[0].write_bytes(paths[0].read_bytes() + b" ")
    paths[1].unlink()
    (tmp_path / "stray.schema.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("contract notes\n", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert check(tmp_path) == sorted([paths[0].name, paths[1].name, "stray.schema.json"])
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_cli_reports_drift_without_writing(tmp_path: Path) -> None:
    command = [
        sys.executable, "-m", "insurance_harness.contracts.export",
        "--destination", str(tmp_path),
    ]
    written = subprocess.run(command, capture_output=True, text=True, check=False)
    assert written.returncode == 0, written.stderr
    clean = subprocess.run([*command, "--check"], capture_output=True, text=True, check=False)
    assert clean.returncode == 0, clean.stderr
    target = tmp_path / "claim.schema.json"
    target.write_bytes(target.read_bytes() + b" ")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    drift = subprocess.run([*command, "--check"], capture_output=True, text=True, check=False)
    assert drift.returncode == 1, drift.stderr
    assert drift.stdout.splitlines() == [target.name]
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
