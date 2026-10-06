"""Minimal catalog projection, ported from V5 contracts.py / catalog.py.

The legacy originals retire in S7. No dependency on the preview runtime remains.
Pack identity and semantic digest travel with the definition so configuration
cannot accidentally apply to a different pack or a changed field meaning.
"""

import json
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonBlank = Annotated[str, StringConstraints(pattern=r"\S")]


class FieldDefinition(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    field_key: NonBlank
    short_title: NonBlank
    description: NonBlank
    source_guidance: str | None = None
    value_spec: str | None = None
    knowledge_role: str | None = None
    formation_method: str | None = None
    ordinal: int = Field(default=0, ge=0)
    # Ad-hoc callers may not have a catalog identity yet. Never infer a pack
    # from an entity identifier: to_candidate then requires the explicit pack.
    pack_id: str = ""
    semantic_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class _CatalogField(FieldDefinition):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)


class _Pack(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    schema_pack_id: NonBlank
    fields: list[_CatalogField]


class _Entry(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    pack: _Pack


class _Catalog(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    entries: list[_Entry]


def pack_definitions(
    catalog_path: str | Path,
    pack_id: str,
    *,
    only_source_extractable: bool = True,
) -> list[FieldDefinition]:
    """Read explicit catalog order, filter formation methods, then assign ordinals."""
    document = _Catalog.model_validate(json.loads(Path(catalog_path).read_text(encoding="utf-8")))
    packs: dict[str, _Pack] = {}
    for entry in document.entries:
        pack = entry.pack
        if pack.schema_pack_id in packs:
            raise ValueError(f"duplicate catalog pack: {pack.schema_pack_id}")
        keys = [field.field_key for field in pack.fields]
        if len(set(keys)) != len(keys):
            raise ValueError(f"duplicate catalog field in {pack.schema_pack_id}")
        packs[pack.schema_pack_id] = pack
    if pack_id not in packs:
        raise ValueError(f"unknown catalog pack: {pack_id}")
    fields = [
        field
        for field in packs[pack_id].fields
        if not only_source_extractable or "原文抽取" in (field.formation_method or "")
    ]
    return [
        FieldDefinition.model_validate({**field.model_dump(), "ordinal": index, "pack_id": pack_id})
        for index, field in enumerate(fields)
    ]
