"""Representative domain changes stay behind the Harness boundary (provider zero)."""

import hashlib
import json
import subprocess
from pathlib import Path
from xml.etree import ElementTree

from insurance_harness.knowledge_compiler.schema_pack_catalog_830_g3 import compile_catalog
from insurance_harness.product_ingestion.native_admission_contract import native_admission_prompt
from tests.test_schema_pack_catalog_830_g3 import (
    _CONFIG,
    _NS,
    _WORKBOOK,
    _cell,
    _config_for,
    _entry,
    _rewrite_medical_sheet,
)

ROOT = Path(__file__).parents[2]


def go_source_digest() -> str:
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "*.go", "go.mod", "go.sum"], cwd=ROOT
    ).split(b"\0")
    digest = hashlib.sha256()
    for raw in sorted(set(paths)):
        if not raw:
            continue
        path = ROOT / raw.decode()
        if path.is_file():
            digest.update(raw + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def test_schema_and_admission_changes_do_not_require_go_source_changes() -> None:
    before_go = go_source_digest()
    workbook = _WORKBOOK.read_bytes()
    config = json.loads(_CONFIG.read_bytes())
    original = compile_catalog(workbook, config)
    revised_description = "仅从合同约定的产品主数据核验，不接受模型推断的产品代码。"

    def revise_description(root: ElementTree.Element) -> None:
        cell = _cell(root, "E6")
        cell.set("t", "str")
        value = cell.find(f"{{{_NS}}}v")
        assert value is not None
        value.text = revised_description

    changed_workbook = _rewrite_medical_sheet(workbook, revise_description)
    revised = compile_catalog(changed_workbook, _config_for(changed_workbook, config))
    old_pack = _entry(original, "schemapack_medical_insurance").pack
    new_pack = _entry(revised, "schemapack_medical_insurance").pack
    assert new_pack.fields[0].description == revised_description
    assert new_pack.fields[0].semantic_sha256 != old_pack.fields[0].semantic_sha256
    assert new_pack.fields[1:] == old_pack.fields[1:]
    # Dependency-aware admission is selected inside the existing domain module;
    # it neither asks the platform to compile a rule nor opens a provider client.
    assert native_admission_prompt(None) != native_admission_prompt("candidate-dependencies.830.v1")
    assert go_source_digest() == before_go
