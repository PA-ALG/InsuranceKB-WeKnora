"""S3e-1 acceptance: a product page's profile carries the pack name and field definitions (§2.2).

Protected file: written by Claude. The concept page shows a field's definition and groups related
concepts by schema category; both come from the catalog the page is built from, never from code.
"""

from __future__ import annotations

import json
from pathlib import Path

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.compilers.schema_fields.page import product_page

REPO = Path(__file__).resolve().parents[4]
CATALOG = REPO / SCHEMA_PACK_CATALOG
PACK = "schemapack_critical_illness_insurance"


def test_the_profile_names_the_pack_and_defines_each_field() -> None:
    page = product_page(CATALOG, PACK, entity_id="1828", name="演示")
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    pack = next(e["pack"] for e in catalog["entries"] if e["pack"]["schema_pack_id"] == PACK)
    assert page.profile.display_name == pack["display_name"] == "重疾险"
    definitions = {f["field_key"]: f for f in pack["fields"]}
    fields = [field for section in page.profile.sections for field in section.fields]
    assert fields
    for field in fields:
        assert field.description == definitions[field.field_key]["description"]
        assert field.schema_category == definitions[field.field_key]["schema_category"]
    cooling = next(field for field in fields if field.field_key == "cooling_off_period")
    assert cooling.description and cooling.schema_category
