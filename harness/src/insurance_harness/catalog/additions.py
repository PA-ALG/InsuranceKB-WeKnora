"""Effective SchemaPacks: apply adjudicated additions to an immutable workbook snapshot."""

import hashlib
import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from insurance_harness.catalog import SCHEMA_PACK_CATALOG

SIDE_FILE = "schema_pack_additions.json"
BASE_SHA256 = "0d5ed6a5789362f1c72ebad5bbc47a64e1d71bc122890da96d976ec01256a3f9"
SHIPPED_BASE = Path(__file__).with_name(Path(SCHEMA_PACK_CATALOG).name)
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
Ruling = Annotated[
    str,
    StringConstraints(
        pattern=r"^https://github\.com/PA-ALG/InsuranceKB-WeKnora/issues/[1-9][0-9]*#issuecomment-[1-9][0-9]*$"
    ),
]


class _Closed(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class _Field(_Closed):
    field_key: Identifier
    short_title: Text
    description: Text
    schema_category: Text
    source_guidance: Text
    formation_method: Literal["原文抽取"]
    knowledge_role: Text


class _Display(_Closed):
    section_key: Text
    short_title: Text


class _Addition(_Closed):
    pack_id: Identifier
    field_key: Identifier
    display: _Display
    ruling: Ruling


class CatalogAdditions(_Closed):
    version: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}\.\d+$")
    base_sha256: Literal["0d5ed6a5789362f1c72ebad5bbc47a64e1d71bc122890da96d976ec01256a3f9"]
    field_definitions: list[_Field] = Field(min_length=1)
    additions: list[_Addition] = Field(min_length=1)

    @model_validator(mode="after")
    def defined_fields(self) -> Self:
        keys = {field.field_key for field in self.field_definitions}
        if len(keys) != len(self.field_definitions) or keys != {
            a.field_key for a in self.additions
        }:
            raise ValueError("catalog additions must use uniquely defined fields")
        return self


def _sha(value: object) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _append(entry: dict[str, Any], row: _Addition, definition: _Field) -> None:
    fields = entry["pack"]["fields"]
    sections = entry["profile"]["sections"]
    if any(
        f["field_key"] == row.field_key or f["short_title"] == definition.short_title
        for f in fields
    ):
        raise ValueError("catalog addition would replace a field or duplicate a title")
    matching = [s for s in sections if s["section_key"] == row.display.section_key]
    if (
        len(matching) != 1
        or row.display.short_title != definition.short_title
        or any(
            f["field_key"] == row.field_key or f["short_title"] == row.display.short_title
            for section in sections
            for f in section["fields"]
        )
    ):
        raise ValueError("catalog addition has an invalid presentation item")
    field = definition.model_dump()
    fields.append({**field, "semantic_sha256": _sha(field), "ruling": row.ruling})
    matching[0]["fields"].append(
        {"field_key": row.field_key, "short_title": row.display.short_title}
    )


def effective_catalog(path: str | Path) -> dict[str, Any]:
    """Read a current catalog. Standalone, self-contained custom catalogs remain supported."""
    source = Path(path)
    raw = source.read_bytes()
    base = json.loads(raw)
    if not isinstance(base, dict):
        raise ValueError("catalog must be an object")
    side = source.with_name(SIDE_FILE)
    if not side.exists() and base.get("catalog_id") != "schema_catalog_insurance_product":
        if source.resolve() != SHIPPED_BASE.resolve():
            return base
    if not side.is_file() or hashlib.sha256(raw).hexdigest() != BASE_SHA256:
        raise ValueError("missing catalog additions or mismatched base")
    overlay = CatalogAdditions.model_validate_json(side.read_bytes())
    by_pack = {e["pack"]["schema_pack_id"]: e for e in base["entries"]}
    definitions = {f.field_key: f for f in overlay.field_definitions}
    changed = set()
    for row in overlay.additions:
        if row.pack_id not in by_pack:
            raise ValueError("catalog addition targets an unknown pack")
        _append(by_pack[row.pack_id], row, definitions[row.field_key])
        changed.add(row.pack_id)
    for pack_id in changed:
        entry = by_pack[pack_id]
        pack, profile = entry["pack"], entry["profile"]
        version = f"{profile['profile_version']}+{overlay.version}"
        pack["presentation_profile_ref"]["profile_version"] = version
        pack["schema_version"] += "+" + overlay.version
        # The pre-overlay pack/profile SHA in each input binds its workbook parent.
        pack["schema_pack_sha256"] = _sha(pack)
        pack["catalog_revision"] = pack["schema_pack_sha256"]
        profile.update(
            profile_version=version,
            schema_version=pack["schema_version"],
            schema_pack_sha256=pack["schema_pack_sha256"],
        )
        profile["profile_sha256"] = _sha(profile)
    names = [{f["short_title"] for f in e["pack"]["fields"]} for e in base["entries"]]
    base["field_name_intersection_count"] = len(set.intersection(*names))
    base["field_name_union_count"] = len(set.union(*names))
    base["catalog_version"] += "+" + overlay.version
    base["catalog_sha256"] = _sha(base)
    return base


@lru_cache(maxsize=1)
def shipped_revisions() -> Mapping[str, str]:
    """The installed registry planner has no caller-supplied catalog."""
    revisions = {}
    for entry in effective_catalog(SHIPPED_BASE)["entries"]:
        pack = entry["pack"]
        if "catalog_revision" in pack:
            revisions[pack["schema_pack_id"]] = pack["catalog_revision"]
    return MappingProxyType(revisions)
