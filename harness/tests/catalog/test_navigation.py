"""S3e-1 acceptance: the shipped navigation lists the catalog's packs as product groups (Spec §2.1).

Protected file: written by Claude. User 2026-10-18: navigation follows the schema's pack classes,
not a coarser grouping, and domains beyond products (service benefits) come later as data. So the
product domain carries one group per catalog pack, with the pack's display name and labels, and a
service domain is already declared, empty until such entities are published.
"""

from __future__ import annotations

import json
from pathlib import Path

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.catalog.navigation import load_navigation

REPO = Path(__file__).resolve().parents[3]
CATALOG = REPO / SCHEMA_PACK_CATALOG


def test_the_product_domain_has_one_group_per_catalog_pack_in_catalog_order() -> None:
    navigation = load_navigation()
    assert navigation.navigation_id == "enterprise" and navigation.navigation_version
    product, service = navigation.domains
    assert (product.domain_key, product.display_name, product.entity_types) == (
        "product",
        "产品库",
        ["insurance_product"],
    )
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    expected = [
        (
            e["pack"]["schema_pack_id"],
            e["pack"]["display_name"],
            e["pack"]["applicable_classifications"],
        )
        for e in catalog["entries"]
    ]
    assert len(expected) == 11
    assert [
        (g.group_key, g.display_name, g.classification_labels) for g in product.groups
    ] == expected
    assert (service.domain_key, service.display_name, service.entity_types, service.groups) == (
        "service_benefit",
        "服务权益",
        ["service_benefit"],
        [],
    )
