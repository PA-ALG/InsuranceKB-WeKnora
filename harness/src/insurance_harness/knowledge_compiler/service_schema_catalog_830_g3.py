"""Reviewed service schema subset; pure loading and G1 presentation adaptation.

This module defines structure, not a second enterprise Catalog or published facts.
It does not open source files, parse materials, call models, or create candidates.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from insurance_harness.knowledge_compiler.entity_page_graph_830_g1 import (
    PresentationProfileV1,
    PresentationSectionV1,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import schema_wiki_sha256

SOURCE_PATH = (
    "/Users/houjing/Documents/LLM_wiki/customized-llm-wiki/"
    "frontend/src/lib/insurance-schema-registry.ts"
)
SOURCE_SHA256 = "7c20729b0dcb6aaa4672a51d2f9158846da1ebe7ee21b0bde5891aed1c869f82"
Key = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]*$")]
Text = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=8192, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
Hash = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
EntityType = Literal["service_line", "service_line_version", "service_item"]

# Reviewed hashes cover exact original field order, names, labels, notes, importance.
# They bind the migration to the code definition, independently of an asset's own hash.
_DEFINITIONS = {
    "service_line": (
        "insurance.service.ServiceLine",
        "0e0160ab0aecdca1eb568847b620b6bd45b5e043ce641def70f55146ec9bf1a4",
        ("series_name", "scenario_name", "line_name"),
    ),
    "service_line_version": (
        "insurance.service.ServiceLineVersion",
        "656721e9f430f6b93add74fe570da2245d53b625e7361e9f8ba72915bc73f3e8",
        ("line_name", "version_name"),
    ),
    "service_item": (
        "insurance.service.ServiceItem",
        "9eca85641fe0ddb54290574bef4034c6cae815ef17c6a4c9a1d9e7db30fa2b2a",
        ("line_name", "version_name", "item_name"),
    ),
}


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


def _hash_matches(value: BaseModel, field: str) -> bool:
    body = value.model_dump(mode="json", exclude={field})
    actual = getattr(value, field)
    return isinstance(actual, str) and actual == schema_wiki_sha256(body["contract"], body)


class ServiceDefinitionSourceV1(_Frozen):
    kind: Literal["legacy_code_definition"]
    path: Text
    sha256: Hash

    @model_validator(mode="after")
    def reviewed_source(self) -> Self:
        if self.path != SOURCE_PATH or self.sha256 != SOURCE_SHA256:
            raise ValueError("service definition source does not match reviewed code")
        return self


class ServiceFieldDefinitionV1(_Frozen):
    field_key: Key
    short_title: Text
    description: Text
    importance: Literal["critical", "high_confidence", "recommended", "auto_derived"]
    source_field_name: Key

    @model_validator(mode="after")
    def original_name(self) -> Self:
        if self.source_field_name != self.field_key:
            raise ValueError("service field source name differs from original field key")
        return self


class ServiceSchemaDefinitionV1(_Frozen):
    contract: Literal["service-schema-definition.830.g3.v1"]
    schema_pack_id: Key
    schema_version: Literal["2026-09-14-v1"]
    entity_type: EntityType
    source_schema_key: Text
    source_fields_sha256: Hash
    display_name: Text
    purpose: Text
    identity_fields: tuple[Key, ...]
    fields: tuple[ServiceFieldDefinitionV1, ...]
    relation_hints: tuple[Text, ...]
    source_lint_rules: tuple[Text, ...]
    sections: tuple[PresentationSectionV1, ...]
    schema_sha256: Hash

    @model_validator(mode="after")
    def source_and_topology(self) -> Self:
        original_key, field_hash, identity_fields = _DEFINITIONS[self.entity_type]
        original_fields = [
            field.model_dump(mode="json", exclude={"source_field_name"}) for field in self.fields
        ]
        digest = hashlib.sha256(
            json.dumps(
                original_fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        field_titles = {field.field_key: field.short_title for field in self.fields}
        mapped = [field for section in self.sections for field in section.fields]
        if (
            self.source_schema_key != original_key
            or self.schema_pack_id != "schemapack_" + self.entity_type
            or self.source_fields_sha256 != field_hash
            or digest != field_hash
            or self.identity_fields != identity_fields
            or len(field_titles) != len(self.fields)
            or len(mapped) != len(self.fields)
            or len({field.field_key for field in mapped}) != len(mapped)
            or {field.field_key for field in mapped} != set(field_titles)
            or any(field.short_title != field_titles[field.field_key] for field in mapped)
            or not self.sections
            or len({section.section_key for section in self.sections}) != len(self.sections)
            or not _hash_matches(self, "schema_sha256")
        ):
            raise ValueError("service schema source, field mapping, identity, or hash mismatch")
        return self


class ServiceSchemaSubsetV1(_Frozen):
    contract: Literal["service-schema-subset.830.g3.v1"]
    content_status: Literal["STRUCTURE_ONLY_NOT_PUBLISHED"]
    source: ServiceDefinitionSourceV1
    entries: tuple[ServiceSchemaDefinitionV1, ...]
    deferred_entity_types: tuple[
        Literal["service_series"], Literal["service_scenario"], Literal["service_item_concept"]
    ]
    catalog_sha256: Hash

    @model_validator(mode="after")
    def subset_only(self) -> Self:
        if tuple(entry.entity_type for entry in self.entries) != tuple(
            _DEFINITIONS
        ) or not _hash_matches(self, "catalog_sha256"):
            raise ValueError(
                "service subset must contain the three reviewed definitions exactly once"
            )
        return self


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key in service schema asset")
        result[key] = value
    return result


def load_service_schema_catalog(
    asset_json: str | bytes, *, source_bytes: bytes | None = None
) -> ServiceSchemaSubsetV1:
    """Validate an asset without needing the original workstation path at runtime.

    Optional original code bytes verify custody during asset review. Deployed
    callers can rely on the reviewed source and exact original field hashes.
    """
    if source_bytes is not None and hashlib.sha256(source_bytes).hexdigest() != SOURCE_SHA256:
        raise ValueError("service definition source bytes mismatch")
    return ServiceSchemaSubsetV1.model_validate(
        json.loads(asset_json, object_pairs_hook=_unique_object)
    )


def presentation_profile(definition: ServiceSchemaDefinitionV1) -> PresentationProfileV1:
    """Adapt only presentation topology to the existing G1 profile contract."""
    definition = ServiceSchemaDefinitionV1.model_validate(definition)
    payload: dict[str, object] = {
        "contract": "presentation-profile.v1",
        "profile_id": "profile_" + definition.entity_type,
        "profile_version": definition.schema_version,
        "schema_pack_id": definition.schema_pack_id,
        "schema_version": definition.schema_version,
        "schema_pack_sha256": definition.schema_sha256,
        "sections": [section.model_dump(mode="json") for section in definition.sections],
    }
    return PresentationProfileV1.model_validate(
        {**payload, "profile_sha256": schema_wiki_sha256("presentation-profile.v1", payload)}
    )
