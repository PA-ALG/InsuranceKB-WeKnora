"""Read the generated Catalog without guessing pack or field identities."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

Text = Annotated[str, StringConstraints(min_length=1)]


class _CatalogRecord(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    @field_validator("*", mode="after")
    @classmethod
    def reject_blank_text(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("catalog identifiers must not be blank")
        return value


class FieldDefinition(_CatalogRecord):
    short_title: Text
    field_key: Text
    description: str = ""
    source_guidance: str = ""
    value_spec: str | None = None
    formation_method: str = ""


class _Pack(_CatalogRecord):
    display_name: Text
    schema_pack_id: Text
    fields: list[FieldDefinition]


class _Entry(_CatalogRecord):
    pack: _Pack


class _CatalogDocument(_CatalogRecord):
    entries: list[_Entry]


@dataclass(frozen=True)
class Catalog:
    """Validated pack-scoped names; unknown titles remain explicitly unmapped."""

    _pack_ids: dict[str, str]
    _fields: dict[str, dict[str, str]]
    _definitions: dict[str, dict[str, FieldDefinition]]

    def pack_id(self, display_name: str) -> str:
        try:
            return self._pack_ids[display_name]
        except KeyError as exc:
            raise ValueError(f"unknown catalog pack: {display_name}") from exc

    def field_key(self, pack_id: str, title: str) -> str | None:
        return self._pack_fields(pack_id).get(title)

    def fields(self, pack_id: str) -> tuple[str, ...]:
        return tuple(self._pack_fields(pack_id).values())

    def field_definition(self, pack_id: str, field_key: str) -> FieldDefinition:
        self._pack_fields(pack_id)
        try:
            return self._definitions[pack_id][field_key].model_copy(deep=True)
        except KeyError as exc:
            raise ValueError(f"unknown catalog field: {field_key}") from exc

    def source_extractable_fields(self, pack_id: str) -> tuple[str, ...]:
        return tuple(
            key for key in self.fields(pack_id)
            if "原文抽取" in self.field_definition(pack_id, key).formation_method
        )

    def _pack_fields(self, pack_id: str) -> dict[str, str]:
        try:
            return self._fields[pack_id]
        except KeyError as exc:
            raise ValueError(f"unknown catalog pack_id: {pack_id}") from exc


def load_catalog(path: str | Path) -> Catalog:
    """Load entries[].pack and fail closed on duplicate names or identifiers."""
    document = _CatalogDocument.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    pack_ids: dict[str, str] = {}
    fields: dict[str, dict[str, str]] = {}
    definitions: dict[str, dict[str, FieldDefinition]] = {}
    for entry in document.entries:
        pack = entry.pack
        if pack.display_name in pack_ids or pack.schema_pack_id in fields:
            raise ValueError(f"duplicate catalog pack: {pack.display_name}")
        by_title: dict[str, str] = {}
        keys: set[str] = set()
        for field in pack.fields:
            if field.short_title in by_title or field.field_key in keys:
                raise ValueError(f"duplicate catalog field in {pack.schema_pack_id}")
            by_title[field.short_title] = field.field_key
            keys.add(field.field_key)
        pack_ids[pack.display_name] = pack.schema_pack_id
        fields[pack.schema_pack_id] = by_title
        definitions[pack.schema_pack_id] = {field.field_key: field for field in pack.fields}
    return Catalog(pack_ids, fields, definitions)
