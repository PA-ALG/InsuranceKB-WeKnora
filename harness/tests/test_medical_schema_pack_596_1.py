from __future__ import annotations

from typing import Any

import pytest

from insurance_harness.knowledge_compiler.medical_schema_pack_596_1 import (
    MEDICAL_DOMAIN_ID,
    MEDICAL_ENTITY_ID,
    MEDICAL_SECTION_FIELD_COUNTS,
    MEDICAL_SECTION_IDS,
    MEDICAL_VERSION_ID,
    MedicalSchemaPackError,
    make_initial_medical_domain_596_1,
    make_initial_medical_entity_596_1,
    make_initial_medical_entity_version_596_1,
    make_initial_medical_taxonomy_596_1,
    make_medical_schema_pack_596_1,
    validate_initial_medical_authority_596_1,
    validate_medical_schema_pack_596_1,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    APPROVED_ORDERED_FIELD_IDS,
    APPROVED_PRODUCT_VERSION_ID,
    APPROVED_SCHEMA_ID,
)


def _replace(value: Any, **updates: object) -> Any:
    if hasattr(value, "model_copy"):
        return value.model_copy(update=updates)
    raise AssertionError("canonical contract must be a frozen Pydantic model")


def test_medical_pack_code_owns_exact_seven_section_order_and_ordered67() -> None:
    pack = make_medical_schema_pack_596_1()

    assert pack.schema_pack_id == APPROVED_SCHEMA_ID
    assert pack.schema_version == "v1"
    assert tuple(section.section_id for section in pack.sections) == MEDICAL_SECTION_IDS
    assert tuple(len(section.ordered_field_ids) for section in pack.sections) == (
        16,
        15,
        6,
        11,
        9,
        5,
        5,
    )
    assert MEDICAL_SECTION_FIELD_COUNTS == (16, 15, 6, 11, 9, 5, 5)
    assert tuple(
        field_id
        for section in pack.sections
        for field_id in section.ordered_field_ids
    ) == APPROVED_ORDERED_FIELD_IDS
    assert validate_medical_schema_pack_596_1(pack) is pack


@pytest.mark.parametrize("mutation", ["reverse_sections", "duplicate_field", "foreign_id"])
def test_medical_pack_rejects_rehashed_topology_substitution(mutation: str) -> None:
    pack = make_medical_schema_pack_596_1()
    if mutation == "reverse_sections":
        forged = _replace(pack, sections=tuple(reversed(pack.sections)))
    elif mutation == "duplicate_field":
        first = pack.sections[0]
        forged_first = _replace(
            first,
            ordered_field_ids=(
                first.ordered_field_ids[0],
                *first.ordered_field_ids[:-1],
            ),
        )
        forged = _replace(pack, sections=(forged_first, *pack.sections[1:]))
    else:
        forged = _replace(pack, schema_pack_id="caller-selected-schema.v1")

    with pytest.raises(MedicalSchemaPackError):
        validate_medical_schema_pack_596_1(forged)


def test_initial_medical_taxonomy_and_entity_are_not_caller_selectable() -> None:
    domain = make_initial_medical_domain_596_1()
    entity = make_initial_medical_entity_596_1()
    version = make_initial_medical_entity_version_596_1()
    taxonomy = make_initial_medical_taxonomy_596_1()
    assert domain.domain_id == MEDICAL_DOMAIN_ID
    assert entity.entity_id == MEDICAL_ENTITY_ID
    assert version.entity_id == MEDICAL_ENTITY_ID
    assert version.version_id == MEDICAL_VERSION_ID
    assert version.product_version_id == APPROVED_PRODUCT_VERSION_ID
    assert (
        validate_initial_medical_authority_596_1(
            domain=domain,
            entity=entity,
            entity_version=version,
            taxonomy=taxonomy,
        )
        == (domain, entity, version, taxonomy)
    )

    for updates in (
        {"domain": _replace(domain, domain_id="caller-domain")},
        {"entity": _replace(entity, entity_id="caller-entity")},
        {"entity_version": _replace(version, product_version_id="596-2")},
        {"taxonomy": _replace(taxonomy, nodes=tuple(reversed(taxonomy.nodes)))},
    ):
        with pytest.raises(MedicalSchemaPackError):
            validate_initial_medical_authority_596_1(
                domain=updates.get("domain", domain),
                entity=updates.get("entity", entity),
                entity_version=updates.get("entity_version", version),
                taxonomy=updates.get("taxonomy", taxonomy),
            )
