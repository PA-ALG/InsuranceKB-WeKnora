"""Code-owned medical Schema67 pack and initial 596-1 entity authority."""

from __future__ import annotations

from typing import Final

from insurance_harness.knowledge_compiler.schema_first_contracts import (
    APPROVED_ORDERED_FIELD_IDS,
    APPROVED_PRODUCT_VERSION_ID,
    APPROVED_SCHEMA_ID,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import (
    EntityIdentityV1,
    EntityVersionV1,
    KnowledgeDomainV1,
    SchemaPackV1,
    SchemaSectionV1,
    SchemaWikiContractError,
    TaxonomyNodeV1,
    TaxonomySnapshotV1,
    schema_wiki_sha256,
    validate_schema_pack,
    validate_taxonomy_snapshot,
)

MEDICAL_DOMAIN_ID: Final[str] = "medical-insurance"
MEDICAL_ENTITY_ID: Final[str] = "ping-an-e-sheng-bao"
MEDICAL_VERSION_ID: Final[str] = "ping-an-e-sheng-bao@596-1"
MEDICAL_TAXONOMY_VERSION: Final[str] = "medical-insurance-taxonomy.v1"

MEDICAL_SECTION_IDS: Final[tuple[str, ...]] = (
    "product-overview",
    "application-and-contract",
    "renewal-and-pricing",
    "coverage-and-exclusions",
    "claims-and-reimbursement",
    "services-and-benefits",
    "sales-support",
)
MEDICAL_SECTION_FIELD_COUNTS: Final[tuple[int, ...]] = (16, 15, 6, 11, 9, 5, 5)
_MEDICAL_SECTION_DISPLAY_NAMES: Final[tuple[str, ...]] = (
    "产品概览",
    "投保与合同",
    "续保与费率",
    "保障与除外",
    "理赔与报销",
    "服务与权益",
    "销售支持",
)


class MedicalSchemaPackError(ValueError):
    """Stable fail-closed error for the one registered medical pack."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _section_fields() -> tuple[tuple[str, ...], ...]:
    sections: list[tuple[str, ...]] = []
    cursor = 0
    for count in MEDICAL_SECTION_FIELD_COUNTS:
        sections.append(APPROVED_ORDERED_FIELD_IDS[cursor : cursor + count])
        cursor += count
    if cursor != len(APPROVED_ORDERED_FIELD_IDS):
        raise AssertionError("medical Schema67 section partition is incomplete")
    return tuple(sections)


def make_medical_schema_pack_596_1() -> SchemaPackV1:
    sections = tuple(
        SchemaSectionV1(
            section_id=section_id,
            display_name=display_name,
            ordered_field_ids=field_ids,
        )
        for section_id, display_name, field_ids in zip(
            MEDICAL_SECTION_IDS,
            _MEDICAL_SECTION_DISPLAY_NAMES,
            _section_fields(),
            strict=True,
        )
    )
    payload = {
        "contract": "schema-pack.v1",
        "schema_pack_id": APPROVED_SCHEMA_ID,
        "schema_version": "v1",
        "domain_id": MEDICAL_DOMAIN_ID,
        "ordered_field_ids": APPROVED_ORDERED_FIELD_IDS,
        "sections": sections,
    }
    return SchemaPackV1.model_validate(
        {
            **payload,
            "schema_pack_sha256": schema_wiki_sha256("schema-pack.v1", payload),
        }
    )


def make_initial_medical_domain_596_1() -> KnowledgeDomainV1:
    payload = {
        "contract": "knowledge-domain.v1",
        "domain_id": MEDICAL_DOMAIN_ID,
        "display_name": "医疗险",
    }
    return KnowledgeDomainV1.model_validate(
        {
            **payload,
            "domain_sha256": schema_wiki_sha256("knowledge-domain.v1", payload),
        }
    )


def make_initial_medical_entity_596_1() -> EntityIdentityV1:
    return EntityIdentityV1(
        domain_id=MEDICAL_DOMAIN_ID,
        entity_id=MEDICAL_ENTITY_ID,
    )


def make_initial_medical_entity_version_596_1() -> EntityVersionV1:
    return EntityVersionV1(
        entity_id=MEDICAL_ENTITY_ID,
        version_id=MEDICAL_VERSION_ID,
        product_version_id=APPROVED_PRODUCT_VERSION_ID,
    )


def make_initial_medical_taxonomy_596_1() -> TaxonomySnapshotV1:
    nodes = (
        TaxonomyNodeV1(
            node_id="medical-products",
            parent_node_id=None,
            node_kind="category",
            slug="medical-products",
            stable_entity_id=None,
            position=0,
        ),
        TaxonomyNodeV1(
            node_id=MEDICAL_ENTITY_ID,
            parent_node_id="medical-products",
            node_kind="entity",
            slug=MEDICAL_ENTITY_ID,
            stable_entity_id=MEDICAL_ENTITY_ID,
            position=0,
        ),
    )
    payload = {
        "contract": "taxonomy-snapshot.v1",
        "domain_id": MEDICAL_DOMAIN_ID,
        "taxonomy_version": MEDICAL_TAXONOMY_VERSION,
        "previous_snapshot_sha256": None,
        "nodes": nodes,
        "redirects": (),
    }
    return TaxonomySnapshotV1.model_validate(
        {
            **payload,
            "taxonomy_sha256": schema_wiki_sha256("taxonomy-snapshot.v1", payload),
        }
    )


def validate_medical_schema_pack_596_1(pack: SchemaPackV1) -> SchemaPackV1:
    try:
        current = validate_schema_pack(pack)
    except (SchemaWikiContractError, TypeError, ValueError):
        raise MedicalSchemaPackError("MEDICAL_SCHEMA_PACK_INVALID") from None
    if current != make_medical_schema_pack_596_1():
        raise MedicalSchemaPackError("MEDICAL_SCHEMA_PACK_INVALID")
    return pack


def validate_initial_medical_authority_596_1(
    *,
    domain: KnowledgeDomainV1,
    entity: EntityIdentityV1,
    entity_version: EntityVersionV1,
    taxonomy: TaxonomySnapshotV1,
) -> tuple[
    KnowledgeDomainV1,
    EntityIdentityV1,
    EntityVersionV1,
    TaxonomySnapshotV1,
]:
    expected = (
        make_initial_medical_domain_596_1(),
        make_initial_medical_entity_596_1(),
        make_initial_medical_entity_version_596_1(),
        make_initial_medical_taxonomy_596_1(),
    )
    try:
        current = (
            KnowledgeDomainV1.model_validate(domain.model_dump(mode="python")),
            EntityIdentityV1.model_validate(entity.model_dump(mode="python")),
            EntityVersionV1.model_validate(entity_version.model_dump(mode="python")),
            validate_taxonomy_snapshot(taxonomy),
        )
    except (SchemaWikiContractError, TypeError, ValueError):
        raise MedicalSchemaPackError("MEDICAL_AUTHORITY_INVALID") from None
    if current != expected:
        raise MedicalSchemaPackError("MEDICAL_AUTHORITY_INVALID")
    return domain, entity, entity_version, taxonomy


__all__ = [
    "MEDICAL_DOMAIN_ID",
    "MEDICAL_ENTITY_ID",
    "MEDICAL_SECTION_FIELD_COUNTS",
    "MEDICAL_SECTION_IDS",
    "MEDICAL_VERSION_ID",
    "MedicalSchemaPackError",
    "make_initial_medical_domain_596_1",
    "make_initial_medical_entity_596_1",
    "make_initial_medical_entity_version_596_1",
    "make_initial_medical_taxonomy_596_1",
    "make_medical_schema_pack_596_1",
    "validate_initial_medical_authority_596_1",
    "validate_medical_schema_pack_596_1",
]
