"""Versioned extraction data, ported from V5 field_profiles.py / llm_plugin.py.

Legacy originals retire in S7. Rules live in extraction_profiles.json, bound to
pack + field key + semantic digest; missing bindings use the generic defaults.
All source pages are supplied in this offline core. Recall/truncation is not
needed here, so scan/diversity/neighbor hints never exclude source material.
"""

from functools import lru_cache
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.compilers.schema_fields.definitions import FieldDefinition


class FieldExtractionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scan_all_materials: bool = True
    preserve_document_diversity: bool = True
    neighbor_pages: int = Field(default=0, ge=0)
    exhaustive_items: bool = False
    semantic_terms: tuple[str, ...] = ()
    instruction: str = ""
    preferred_document_terms: tuple[str, ...] = ()
    required_evidence_document_terms: tuple[str, ...] = ()


class _ProfileData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    source: str
    profiles: dict[str, FieldExtractionProfile]
    # Entries are pack_id, field_key, semantic_sha256, profile_id.
    bindings: list[tuple[str, str, str, str]]


@lru_cache(maxsize=1)
def _profiles() -> dict[tuple[str, str, str], FieldExtractionProfile]:
    resource = files(__package__).joinpath("extraction_profiles.json")
    data = _ProfileData.model_validate_json(resource.read_text(encoding="utf-8"))
    result: dict[tuple[str, str, str], FieldExtractionProfile] = {}
    for pack, field, semantic, profile in data.bindings:
        key = (pack, field, semantic)
        if key in result:
            raise ValueError("duplicate extraction profile binding")
        result[key] = data.profiles[profile]
    return result


def field_extraction_profile(definition: FieldDefinition) -> FieldExtractionProfile:
    """Configuration changes do not alter a field's semantic digest."""
    key = (definition.pack_id, definition.field_key, definition.semantic_sha256 or "")
    return _profiles().get(key, FieldExtractionProfile())
