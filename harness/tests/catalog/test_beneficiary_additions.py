"""S12c-13b: a ruling augments the effective catalog, never the historical workbook."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.compilers.schema_fields.cards import cards_version
from insurance_harness.compilers.schema_fields.definitions import pack_definitions
from insurance_harness.compilers.schema_fields.engine import CompileOutput, reusable
from insurance_harness.compilers.schema_fields.page import product_page
from insurance_harness.compilers.schema_fields.prompt import (
    VALUE_PROTOCOL_VERSION,
    build_selection_request,
    build_value_request,
)
from insurance_harness.eval.catalog import load_catalog
from insurance_harness.ingest.judge_batch.points import field_context

REPO = Path(__file__).resolve().parents[3]
BASE = REPO / SCHEMA_PACK_CATALOG
SIDE = BASE.with_name("schema_pack_additions.json")
ADDED = {
    "medical",
    "accident_medical",
    "accident",
    "critical_illness",
    "nursing_care",
    "disability_income",
}
FIELD = "beneficiary_rules"
MEDICAL = "schemapack_medical_insurance"


def test_explicit_workbook_still_reads_original_67_fields() -> None:
    assert hashlib.sha256(BASE.read_bytes()).hexdigest() == (
        "0d5ed6a5789362f1c72ebad5bbc47a64e1d71bc122890da96d976ec01256a3f9"
    )
    historical = load_catalog(BASE)
    assert len(historical.fields(MEDICAL)) == 67 and FIELD not in historical.fields(MEDICAL)


def test_all_six_add_one_extraction_and_display_field_five_keep_their_identity() -> None:
    from insurance_harness.catalog.additions import effective_catalog

    original = json.loads(BASE.read_bytes())
    effective = effective_catalog(BASE)
    assert effective["catalog_sha256"] != original["catalog_sha256"]
    assert effective["workbook_sha256"] == original["workbook_sha256"]
    assert len(effective["entries"]) == len(original["entries"]) == 11
    seen = set()
    for before, after in zip(original["entries"], effective["entries"], strict=True):
        pack, profile = after["pack"], after["profile"]
        pack_id = pack["schema_pack_id"]
        kind = pack_id.removeprefix("schemapack_").removesuffix("_insurance")
        if kind not in ADDED:
            assert before == after
            continue
        seen.add(kind)
        assert pack["fields"][:-1] == before["pack"]["fields"]
        field = pack["fields"][-1]
        assert field["field_key"] == FIELD and "source_row" not in field
        assert pack["schema_pack_sha256"] != before["pack"]["schema_pack_sha256"]
        assert profile["profile_sha256"] != before["profile"]["profile_sha256"]
        assert profile["profile_version"] == pack["presentation_profile_ref"]["profile_version"]
        page = product_page(BASE, pack_id, entity_id="synthetic", name="合成合同")
        section = next(s for s in page.profile.sections if s.section_key == "claims-benefits")
        assert section.fields[-1].field_key == FIELD
        assert section.fields[-1].short_title == field["short_title"]
    assert seen == ADDED


def test_review_and_both_compiler_steps_have_the_same_card_and_inventory() -> None:
    definitions = pack_definitions(BASE, MEDICAL)
    assert FIELD in {d.field_key for d in definitions}
    definition = next(d for d in definitions if d.field_key == FIELD)
    text = "保险金由指定受益人领取。遗产申请须提交继承关系证明。"
    select = json.loads(build_selection_request("synthetic", [definition], text).user)
    value = json.loads(build_value_request("synthetic", [(definition, [])]).user)
    first = select["schema_fields"][0]["card"]
    second = value["schema_fields"][0]["card"]
    assert field_context(REPO, MEDICAL, [FIELD])[FIELD]["card"] == second
    assert first["available_fields"] == second["available_fields"]
    assert {FIELD, "claim_application_deadline_and_documents"} <= set(first["available_fields"])
    assert first["definition"] == second["definition"]


def test_old_output_from_affected_pack_requires_new_catalog_identity() -> None:
    fields = pack_definitions(BASE, MEDICAL)
    old = CompileOutput(
        entity_id="synthetic",
        pack_id=MEDICAL,
        model="offline",
        cards_version=cards_version(),
        value_protocol=VALUE_PROTOCOL_VERSION,
        materials=["fixed"],
    )
    revision = getattr(fields[0], "catalog_revision", None)
    assert revision and all(f.catalog_revision == revision for f in fields)
    assert not reusable(old, ["fixed"], catalog_revision=revision)
    current = old.model_copy(update={"catalog_revision": revision})
    assert reusable(current, ["fixed"], catalog_revision=revision)
    assert not reusable(current, ["fixed"], catalog_revision="a" * 64)
    unchanged = pack_definitions(BASE, "schemapack_term_life_insurance")
    assert all(f.catalog_revision is None for f in unchanged)


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "duplicate",
        "existing",
        "title",
        "wrong_pack",
        "wrong_section",
        "no_ruling",
        "action",
        "base_bytes",
        "profile_title",
        "unknown_definition",
    ],
)
def test_invalid_overlay_fails_closed_before_exposing_fields(tmp_path: Path, damage: str) -> None:
    path = tmp_path / BASE.name
    path.write_bytes(BASE.read_bytes())
    overlay: dict[str, Any] = json.loads(SIDE.read_text())
    row = overlay["additions"][0]
    if damage == "duplicate":
        overlay["additions"].append(row.copy())
    elif damage == "existing":
        row["pack_id"] = "schemapack_term_life_insurance"
    elif damage == "wrong_pack":
        row["pack_id"] = "schemapack_no_such_pack"
    elif damage == "wrong_section":
        row["display"]["section_key"] = "no-such-section"
    elif damage == "no_ruling":
        row["ruling"] = "https://example.org/not-a-ruling"
    elif damage == "action":
        row["remove"] = True
    elif damage == "base_bytes":
        path.write_bytes(path.read_bytes() + b" ")
    elif damage == "title":
        overlay["field_definitions"][0]["short_title"] = row["display"]["short_title"] = "等待期"
    elif damage == "profile_title":
        row["display"]["short_title"] = "另一字段"
    elif damage == "unknown_definition":
        row["field_key"] = "missing_definition"
    if damage != "missing":
        path.with_name(SIDE.name).write_text(json.dumps(overlay))
    with pytest.raises(ValueError):
        pack_definitions(path, MEDICAL)
