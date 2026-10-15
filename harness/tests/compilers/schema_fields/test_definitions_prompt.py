"""Catalog data and material-only, reproducible request construction."""

import json
from pathlib import Path

import pytest

from insurance_harness.compilers.schema_fields.definitions import FieldDefinition, pack_definitions
from insurance_harness.compilers.schema_fields.engine import SchemaFieldsCompiler
from insurance_harness.compilers.schema_fields.profiles import field_extraction_profile
from insurance_harness.evidence.quote_verification import PageText

ROOT = Path(__file__).resolve().parents[4]
CATALOG = ROOT / "internal/handler/schema_pack_catalog_830_g3.generated.json"


class NeverCall:
    model = "offline"

    def complete(self, *, system: str, user: str) -> str:
        raise AssertionError("request construction called the completion port")


@pytest.mark.parametrize("pack_index", [0, 3])
def test_two_catalog_packs_keep_metadata_and_order(pack_index: int) -> None:
    pack = json.loads(CATALOG.read_text())["entries"][pack_index]["pack"]
    fields = pack_definitions(CATALOG, pack["schema_pack_id"], only_source_extractable=False)
    assert len(fields) == len(pack["fields"])
    assert [f.field_key for f in fields] == [f["field_key"] for f in pack["fields"]]
    assert all(f.pack_id == pack["schema_pack_id"] for f in fields)
    selected = pack_definitions(CATALOG, pack["schema_pack_id"])
    assert [f.field_key for f in selected] == [
        f["field_key"] for f in pack["fields"] if "原文抽取" in f["formation_method"]
    ]
    assert [f.ordinal for f in selected] == list(range(len(selected)))


def test_unknown_or_duplicate_catalog_identity_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="pack"):
        pack_definitions(CATALOG, "not-a-pack")
    catalog = json.loads(CATALOG.read_text())
    catalog["entries"].append(catalog["entries"][0])
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match="duplicate"):
        pack_definitions(path, catalog["entries"][0]["pack"]["schema_pack_id"])


def test_profiles_are_bound_to_pack_field_and_semantics() -> None:
    fields = pack_definitions(CATALOG, "schemapack_medical_insurance")
    field = next(f for f in fields if f.field_key == "waiting_period")
    profile = field_extraction_profile(field)
    assert profile.scan_all_materials and profile.exhaustive_items and profile.neighbor_pages == 1
    assert "起算点" in profile.instruction
    changed = field.model_copy(update={"semantic_sha256": "f" * 64})
    assert field_extraction_profile(changed).instruction == ""
    other_pack = field.model_copy(update={"pack_id": "other"})
    assert field_extraction_profile(other_pack).instruction == ""


def test_prompts_use_all_pages_and_hash_the_actual_request() -> None:
    field = FieldDefinition(field_key="feature", short_title="事项", description="完整定义")
    pages = [
        PageText(document="甲.pdf", document_sha256="a" * 64, page=i, text=f"第{i}页原文")
        for i in range(1, 40)
    ]
    pages.append(PageText(document="乙.pdf", document_sha256="b" * 64, page=1, text="末尾补充"))
    engine = SchemaFieldsCompiler(NeverCall())
    request = engine.build_requests("entity", [field], pages)[0]
    assert "[page 39]" in request.user and "末尾补充" in request.user
    assert "a" * 64 in request.user and "b" * 64 in request.user
    assert request == engine.build_requests("entity", [field], pages)[0]
    assert request.sha256 != engine.build_requests("other", [field], pages)[0].sha256
    assert request.sha256 != engine.build_requests("entity", [field], pages[:-1])[0].sha256
