"""PV-4a acceptance: version identity on the Entity contract (PV-4 Spec §1).

Protected file: written by Claude. `lifecycle` and `product_family` are optional and omitted from
the payload when empty, so every existing Entity keeps its bytes and digest; when present they are
validated at the boundary. The bundle origin gains `identity_refresh`, and `supersedes` relations
get a deterministic id from their two ends.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from insurance_harness.bundle.canonical import member_digest
from insurance_harness.contracts.enums import Origin
from insurance_harness.contracts.knowledge import (
    Entity,
    ProductFamily,
    ProductLifecycle,
    supersedes_relation_id,
)

COMMIT = "a" * 40


def entity(**extra: object) -> Entity:
    return Entity(
        entity_id="1828",
        entity_type="product",
        names=["演示产品"],
        identifiers={"product_code": "1828"},
        classification_labels=["demo"],
        owner_module="harness",
        **extra,  # type: ignore[arg-type]
    )


def test_an_entity_without_version_data_keeps_its_old_payload() -> None:
    payload = entity().model_dump(mode="json")
    assert set(payload) == {
        "entity_id",
        "entity_type",
        "names",
        "aliases",
        "identifiers",
        "classification_labels",
        "owner_module",
    }
    assert member_digest(payload) == member_digest(
        {
            "entity_id": "1828",
            "entity_type": "product",
            "names": ["演示产品"],
            "aliases": [],
            "identifiers": {"product_code": "1828"},
            "classification_labels": ["demo"],
            "owner_module": "harness",
        }
    )


def test_lifecycle_and_family_are_published_when_known() -> None:
    lifecycle = ProductLifecycle(
        sale_start="2024-04-23",
        sale_end="2024-09-01",
        source_status="discontinued",
        basis_commit=COMMIT,
        basis_date="2026-11-01",
    )
    family = ProductFamily(key="智盈倍护", display_name="智盈倍护")
    payload = entity(lifecycle=lifecycle, product_family=family).model_dump(mode="json")
    assert payload["lifecycle"] == {
        "sale_start": "2024-04-23",
        "sale_end": "2024-09-01",
        "source_status": "discontinued",
        "basis_commit": COMMIT,
        "basis_date": "2026-11-01",
    }
    assert payload["product_family"] == {"key": "智盈倍护", "display_name": "智盈倍护"}
    assert Entity.model_validate(payload) == entity(lifecycle=lifecycle, product_family=family)


def test_a_partial_lifecycle_is_allowed() -> None:
    assert ProductLifecycle(sale_start="2025-10-01").sale_end is None
    assert ProductLifecycle(source_status="on_sale").sale_start is None


@pytest.mark.parametrize(
    "fields",
    [
        {"sale_start": "2024-02-30"},
        {"sale_start": "2024/04/23"},
        {"sale_start": "2024-09-01", "sale_end": "2024-09-01"},
        {"sale_start": "2024-09-01", "sale_end": "2024-04-23"},
        {"source_status": "paused"},
        {"basis_commit": "abc"},
        {"basis_date": "yesterday"},
        {"unknown": "x"},
    ],
)
def test_an_invalid_lifecycle_is_refused(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ProductLifecycle(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "fields", [{"key": "", "display_name": "x"}, {"key": "x", "display_name": " "}]
)
def test_an_empty_family_is_refused(fields: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        ProductFamily(**fields)


def test_the_bundle_origin_names_identity_refresh() -> None:
    assert Origin("identity_refresh") == Origin.IDENTITY_REFRESH


def test_a_supersedes_relation_id_is_fixed_by_its_two_ends() -> None:
    assert supersedes_relation_id("sc-new", "1733") == "supersedes/sc-new/1733"
    with pytest.raises(ValueError):
        supersedes_relation_id("a", "a")
    with pytest.raises(ValueError):
        supersedes_relation_id("a/b", "c")
