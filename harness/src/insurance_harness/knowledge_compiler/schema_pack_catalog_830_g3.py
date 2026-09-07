"""Strict G3 catalog boundary for the frozen insurance schema workbook."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from io import BytesIO
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self, cast
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.knowledge_compiler.entity_page_graph_830_g1 import (
    PresentationFieldV1,
    PresentationProfileV1,
    PresentationSectionV1,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import schema_wiki_sha256

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=512, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
FieldKey = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=256, pattern=r"^[A-Za-z][A-Za-z0-9_]*$"),
]
CategoryCode = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9]{2}$")]
OriginalText = StrictStr
CellValue = str | int | None
type WorkbookRow = tuple[
    str,
    str,
    str | None,
    str,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    int,
    int,
]

FIELD_DEFINITION_CONTRACT = "schema-field-definition.830.g3.v1"
PACK_CONTRACT = "schema-pack-definition.830.g3.v1"
CATALOG_CONTRACT = "schema-pack-catalog.830.g3.v1"
_WORKBOOK_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_DOCUMENT_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_HEADERS = (
    "分类",
    "字段名",
    "取值",
    "英文名",
    "说明",
    "取值来源",
    "知识形成方式",
    "知识角色",
    "是否公共字段",
    "其它使用的险种",
    "字段使用频次",
)
_COLUMN_RE = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")


class SchemaPackCatalogError(ValueError):
    """Stable fail-closed error for workbook, mapping, or catalog drift."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


def _payload(model: BaseModel, hash_field: str) -> dict[str, object]:
    return model.model_dump(
        mode="python",
        round_trip=True,
        warnings=False,
        exclude={hash_field},
        exclude_computed_fields=True,
    )


def _field_semantic_payload(schema_pack_id: str, field: FieldDefinitionV1) -> dict[str, object]:
    metadata = field.model_dump(
        mode="python",
        round_trip=True,
        warnings=False,
        exclude={"semantic_sha256", "source_row"},
    )
    return {"schema_pack_id": schema_pack_id, "field": metadata}


class FieldDefinitionV1(_FrozenModel):
    field_key: FieldKey
    short_title: OriginalText
    schema_category: OriginalText
    value_spec: OriginalText | None
    description: OriginalText | None
    source_guidance: OriginalText | None
    formation_method: OriginalText | None
    knowledge_role: OriginalText | None
    common_field_marker: OriginalText | None
    other_applicable_products: OriginalText | None
    usage_frequency: StrictInt
    source_row: Annotated[StrictInt, Field(gt=5)]
    semantic_sha256: Sha256Hex


class PresentationProfileRefV1(_FrozenModel):
    profile_id: Identifier
    profile_version: Identifier


class SchemaPackDefinitionV1(_FrozenModel):
    contract: Literal["schema-pack-definition.830.g3.v1"]
    schema_pack_id: Identifier
    schema_version: Identifier
    display_name: OriginalText
    entity_type: Literal["insurance_product"]
    applicable_classifications: tuple[Identifier, ...]
    workbook_sha256: Sha256Hex
    workbook_sheet: OriginalText
    fields: tuple[FieldDefinitionV1, ...]
    presentation_profile_ref: PresentationProfileRefV1
    schema_pack_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_pack(self) -> Self:
        field_keys = tuple(field.field_key for field in self.fields)
        semantics_match = all(
            field.semantic_sha256
            == schema_wiki_sha256(
                FIELD_DEFINITION_CONTRACT,
                _field_semantic_payload(self.schema_pack_id, field),
            )
            for field in self.fields
        )
        if (
            self.display_name == ""
            or self.workbook_sheet == ""
            or len(self.applicable_classifications) != 1
            or not field_keys
            or len(field_keys) != len(set(field_keys))
            or not semantics_match
            or self.schema_pack_sha256
            != schema_wiki_sha256(self.contract, _payload(self, "schema_pack_sha256"))
        ):
            raise ValueError("schema pack topology or hash is invalid")
        return self


class SchemaPackCatalogEntryV1(_FrozenModel):
    pack: SchemaPackDefinitionV1
    profile: PresentationProfileV1
    profile_confirmation_status: Literal["PENDING_PRODUCT_OWNER_CONFIRMATION"]
    quality_status: Literal["REGISTERED_NOT_QUALITY_ADMITTED"]

    @model_validator(mode="after")
    def validate_entry_binding(self) -> Self:
        pack_keys = tuple(field.field_key for field in self.pack.fields)
        if (
            self.profile.profile_id != self.pack.presentation_profile_ref.profile_id
            or self.profile.profile_version != self.pack.presentation_profile_ref.profile_version
            or self.profile.schema_pack_id != self.pack.schema_pack_id
            or self.profile.schema_version != self.pack.schema_version
            or self.profile.schema_pack_sha256 != self.pack.schema_pack_sha256
            or len(self.profile.ordered_field_keys) != len(pack_keys)
            or set(self.profile.ordered_field_keys) != set(pack_keys)
        ):
            raise ValueError("catalog entry pack/profile binding is invalid")
        return self


class SchemaPackCatalogV1(_FrozenModel):
    contract: Literal["schema-pack-catalog.830.g3.v1"]
    catalog_id: Identifier
    catalog_version: Identifier
    workbook_sha256: Sha256Hex
    mapping_config_sha256: Sha256Hex
    entries: tuple[SchemaPackCatalogEntryV1, ...]
    field_name_union_count: Annotated[StrictInt, Field(gt=0)]
    field_name_intersection_count: Annotated[StrictInt, Field(gt=0)]
    catalog_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_catalog(self) -> Self:
        identities = tuple(
            (entry.pack.schema_pack_id, entry.pack.schema_version) for entry in self.entries
        )
        profile_ids = tuple(
            (entry.profile.profile_id, entry.profile.profile_version) for entry in self.entries
        )
        field_sets = tuple(
            {field.field_key for field in entry.pack.fields} for entry in self.entries
        )
        union_count = len(set().union(*field_sets)) if field_sets else 0
        intersection_count = len(set.intersection(*field_sets)) if field_sets else 0
        if (
            len(self.entries) != 11
            or len(identities) != len(set(identities))
            or len(profile_ids) != len(set(profile_ids))
            or any(entry.pack.workbook_sha256 != self.workbook_sha256 for entry in self.entries)
            or self.field_name_union_count != union_count
            or self.field_name_intersection_count != intersection_count
            or self.catalog_sha256
            != schema_wiki_sha256(self.contract, _payload(self, "catalog_sha256"))
        ):
            raise ValueError("catalog topology, statistics, or hash is invalid")
        return self


class _SectionMapping(_FrozenModel):
    section_key: Identifier
    display_name: OriginalText
    category_codes: tuple[CategoryCode, ...]
    field_keys: tuple[FieldKey, ...] | None = None

    @model_validator(mode="after")
    def validate_mapping(self) -> Self:
        if (
            self.display_name == ""
            or not self.category_codes
            or len(self.category_codes) != len(set(self.category_codes))
            or (self.field_keys is not None and len(self.field_keys) != len(set(self.field_keys)))
        ):
            raise ValueError("invalid section mapping")
        return self


class _PackMapping(_FrozenModel):
    workbook_sheet: OriginalText
    schema_pack_id: Identifier
    schema_version: Identifier
    display_name: OriginalText
    classification: Identifier
    profile_id: Identifier
    profile_version: Identifier
    expected_field_count: Annotated[StrictInt, Field(gt=0)]
    sections: tuple[_SectionMapping, ...]

    @model_validator(mode="after")
    def validate_unique_sections(self) -> Self:
        section_keys = tuple(section.section_key for section in self.sections)
        if not section_keys or len(section_keys) != len(set(section_keys)):
            raise ValueError("pack mapping sections must be a non-empty unique order")
        return self


class _MappingConfig(_FrozenModel):
    contract: Literal["schema-pack-profile-mapping.830.g3.v1"]
    mapping_version: Identifier
    workbook_sha256: Sha256Hex
    catalog_id: Identifier
    catalog_version: Identifier
    confirmation_status: Literal["PENDING_PRODUCT_OWNER_CONFIRMATION"]
    expected_field_name_union_count: Annotated[StrictInt, Field(gt=0)]
    expected_field_name_intersection_count: Annotated[StrictInt, Field(gt=0)]
    packs: tuple[_PackMapping, ...]

    @model_validator(mode="after")
    def validate_unique_pack_mappings(self) -> Self:
        pack_ids = tuple(pack.schema_pack_id for pack in self.packs)
        sheets = tuple(pack.workbook_sheet for pack in self.packs)
        profiles = tuple(pack.profile_id for pack in self.packs)
        if (
            len(self.packs) != 11
            or len(pack_ids) != len(set(pack_ids))
            or len(sheets) != len(set(sheets))
            or len(profiles) != len(set(profiles))
        ):
            raise ValueError("mapping must contain 11 unique packs, sheets, and profiles")
        return self


def _column_index(reference: str) -> int:
    match = _COLUMN_RE.fullmatch(reference)
    if match is None:
        raise SchemaPackCatalogError("INVALID_WORKBOOK_CELL_REFERENCE")
    index = 0
    for character in match.group(1):
        index = index * 26 + ord(character) - ord("A") + 1
    return index - 1


def _cell_value(cell: ElementTree.Element, shared_strings: tuple[str, ...]) -> CellValue:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        texts = cell.findall(f".//{{{_WORKBOOK_NS}}}t")
        return "".join(text.text or "" for text in texts)
    value = cell.find(f"{{{_WORKBOOK_NS}}}v")
    if value is None or value.text is None:
        return None
    if cell_type == "s":
        try:
            return shared_strings[int(value.text)]
        except (IndexError, ValueError) as exc:
            raise SchemaPackCatalogError("INVALID_WORKBOOK_SHARED_STRING") from exc
    if cell_type == "str":
        return value.text
    if cell_type is None:
        try:
            return int(value.text)
        except ValueError as exc:
            raise SchemaPackCatalogError("UNSUPPORTED_WORKBOOK_CELL") from exc
    raise SchemaPackCatalogError("UNSUPPORTED_WORKBOOK_CELL")


def _read_rows(
    sheet_xml: bytes,
    shared_strings: tuple[str, ...],
) -> tuple[tuple[CellValue, ...], ...]:
    try:
        root = ElementTree.fromstring(sheet_xml)
    except ElementTree.ParseError as exc:
        raise SchemaPackCatalogError("INVALID_WORKBOOK_XML") from exc
    rows: list[tuple[CellValue, ...]] = []
    source_rows: list[int] = []
    header_seen = False
    for row in root.findall(f".//{{{_WORKBOOK_NS}}}sheetData/{{{_WORKBOOK_NS}}}row"):
        try:
            row_number = int(row.attrib["r"])
        except (KeyError, ValueError) as exc:
            raise SchemaPackCatalogError("INVALID_WORKBOOK_ROW") from exc
        values: list[CellValue] = [None] * 11
        occupied: set[int] = set()
        for cell in row.findall(f"{{{_WORKBOOK_NS}}}c"):
            index = _column_index(cell.attrib.get("r", ""))
            value = _cell_value(cell, shared_strings)
            if index >= 11:
                if value not in (None, ""):
                    raise SchemaPackCatalogError("UNEXPECTED_WORKBOOK_COLUMN")
                continue
            if index in occupied:
                raise SchemaPackCatalogError("DUPLICATE_WORKBOOK_CELL")
            occupied.add(index)
            values[index] = value
        if row_number == 5:
            if tuple(values) != _HEADERS:
                raise SchemaPackCatalogError("WORKBOOK_HEADER_MISMATCH")
            header_seen = True
        elif row_number > 5 and any(value not in (None, "") for value in values):
            rows.append(tuple(values))
            source_rows.append(row_number)
    if not header_seen:
        raise SchemaPackCatalogError("WORKBOOK_HEADER_MISMATCH")
    if not rows:
        raise SchemaPackCatalogError("EMPTY_WORKBOOK_SHEET")
    return tuple(
        (*values, row_number) for values, row_number in zip(rows, source_rows, strict=True)
    )


def _read_workbook(
    workbook_bytes: bytes,
    wanted_sheets: set[str],
) -> dict[str, tuple[tuple[CellValue, ...], ...]]:
    try:
        with ZipFile(BytesIO(workbook_bytes)) as archive:
            workbook_root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            relationship_root = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            shared_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = tuple(
                "".join(text.text or "" for text in item.findall(f".//{{{_WORKBOOK_NS}}}t"))
                for item in shared_root.findall(f"{{{_WORKBOOK_NS}}}si")
            )
            relationships = {
                item.attrib["Id"]: item.attrib["Target"]
                for item in relationship_root.findall(f"{{{_REL_NS}}}Relationship")
            }
            sheets: dict[str, tuple[tuple[CellValue, ...], ...]] = {}
            for sheet in workbook_root.findall(f"{{{_WORKBOOK_NS}}}sheets/{{{_WORKBOOK_NS}}}sheet"):
                name = sheet.attrib["name"]
                if name not in wanted_sheets:
                    continue
                relationship_id = sheet.attrib[f"{{{_DOCUMENT_REL_NS}}}id"]
                target = PurePosixPath("xl") / relationships[relationship_id]
                if ".." in target.parts:
                    raise SchemaPackCatalogError("INVALID_WORKBOOK_RELATIONSHIP")
                sheets[name] = _read_rows(archive.read(str(target)), shared_strings)
            return sheets
    except SchemaPackCatalogError:
        raise
    except (BadZipFile, ElementTree.ParseError, KeyError, OSError) as exc:
        raise SchemaPackCatalogError("INVALID_WORKBOOK") from exc


def _require_row(row: tuple[CellValue, ...]) -> WorkbookRow:
    if (
        len(row) != 12
        or any(type(row[index]) is not str or row[index] == "" for index in (0, 1, 3))
        or type(row[10]) is not int
    ):
        raise SchemaPackCatalogError("INCOMPLETE_WORKBOOK_ROW")
    return cast(WorkbookRow, row)


def _compile_fields(
    rows: tuple[tuple[CellValue, ...], ...],
    schema_pack_id: str,
) -> tuple[FieldDefinitionV1, ...]:
    fields: list[FieldDefinitionV1] = []
    for raw_row in rows:
        (
            category,
            short_title,
            value_spec,
            field_key,
            description,
            source_guidance,
            formation_method,
            knowledge_role,
            common_field_marker,
            other_applicable_products,
            usage_frequency,
            source_row,
        ) = _require_row(raw_row)
        values: dict[str, object] = {
            "field_key": field_key,
            "short_title": short_title,
            "schema_category": category,
            "value_spec": value_spec,
            "description": description,
            "source_guidance": source_guidance,
            "formation_method": formation_method,
            "knowledge_role": knowledge_role,
            "common_field_marker": common_field_marker,
            "other_applicable_products": other_applicable_products,
            "usage_frequency": usage_frequency,
            "source_row": source_row,
        }
        semantic_payload = {
            "schema_pack_id": schema_pack_id,
            "field": {key: value for key, value in values.items() if key != "source_row"},
        }
        values["semantic_sha256"] = schema_wiki_sha256(
            FIELD_DEFINITION_CONTRACT,
            semantic_payload,
        )
        try:
            fields.append(FieldDefinitionV1.model_validate(values))
        except ValidationError as exc:
            raise SchemaPackCatalogError("INCOMPLETE_WORKBOOK_ROW") from exc
    keys = tuple(field.field_key for field in fields)
    if len(keys) != len(set(keys)):
        raise SchemaPackCatalogError("DUPLICATE_FIELD_KEY")
    return tuple(fields)


def _compile_profile_sections(
    fields: tuple[FieldDefinitionV1, ...],
    sections: tuple[_SectionMapping, ...],
) -> tuple[PresentationSectionV1, ...]:
    field_by_key = {field.field_key: field for field in fields}
    explicit_owners: dict[str, int] = {}
    for section_index, section in enumerate(sections):
        for field_key in section.field_keys or ():
            if field_key not in field_by_key:
                raise SchemaPackCatalogError("ORPHAN_PROFILE_FIELD")
            if field_key in explicit_owners:
                raise SchemaPackCatalogError("DUPLICATE_PROFILE_MAPPING")
            explicit_owners[field_key] = section_index
    owners: dict[str, list[int]] = {field.field_key: [] for field in fields}
    for field in fields:
        if field.field_key in explicit_owners:
            owners[field.field_key].append(explicit_owners[field.field_key])
            continue
        code = field.schema_category[:2]
        for section_index, section in enumerate(sections):
            if code in section.category_codes:
                owners[field.field_key].append(section_index)
    section_fields: list[list[FieldDefinitionV1]] = [[] for _ in sections]
    for field in fields:
        for section_index in owners[field.field_key]:
            section_fields[section_index].append(field)
    if any(not items for items in section_fields):
        raise SchemaPackCatalogError("EMPTY_PROFILE_SECTION")
    if any(len(indices) > 1 for indices in owners.values()):
        raise SchemaPackCatalogError("DUPLICATE_PROFILE_MAPPING")
    if any(not indices for indices in owners.values()):
        raise SchemaPackCatalogError("ORPHAN_PROFILE_FIELD")
    return tuple(
        PresentationSectionV1(
            section_key=section.section_key,
            display_name=section.display_name,
            fields=tuple(
                PresentationFieldV1(field_key=field.field_key, short_title=field.short_title)
                for field in section_fields[index]
            ),
        )
        for index, section in enumerate(sections)
    )


def _compile_entry(
    workbook_sha256: str,
    rows: tuple[tuple[CellValue, ...], ...],
    mapping: _PackMapping,
) -> SchemaPackCatalogEntryV1:
    fields = _compile_fields(rows, mapping.schema_pack_id)
    if len(fields) != mapping.expected_field_count:
        raise SchemaPackCatalogError("FIELD_COUNT_MISMATCH")
    profile_ref = PresentationProfileRefV1(
        profile_id=mapping.profile_id,
        profile_version=mapping.profile_version,
    )
    pack_values: dict[str, object] = {
        "contract": PACK_CONTRACT,
        "schema_pack_id": mapping.schema_pack_id,
        "schema_version": mapping.schema_version,
        "display_name": mapping.display_name,
        "entity_type": "insurance_product",
        "applicable_classifications": (mapping.classification,),
        "workbook_sha256": workbook_sha256,
        "workbook_sheet": mapping.workbook_sheet,
        "fields": fields,
        "presentation_profile_ref": profile_ref,
    }
    pack_values["schema_pack_sha256"] = schema_wiki_sha256(PACK_CONTRACT, pack_values)
    pack = SchemaPackDefinitionV1.model_validate(pack_values)
    profile_values: dict[str, object] = {
        "contract": "presentation-profile.v1",
        "profile_id": mapping.profile_id,
        "profile_version": mapping.profile_version,
        "schema_pack_id": mapping.schema_pack_id,
        "schema_version": mapping.schema_version,
        "schema_pack_sha256": pack.schema_pack_sha256,
        "sections": _compile_profile_sections(fields, mapping.sections),
    }
    profile_values["profile_sha256"] = schema_wiki_sha256(
        "presentation-profile.v1",
        profile_values,
    )
    profile = PresentationProfileV1.model_validate(profile_values)
    return SchemaPackCatalogEntryV1(
        pack=pack,
        profile=profile,
        profile_confirmation_status="PENDING_PRODUCT_OWNER_CONFIRMATION",
        quality_status="REGISTERED_NOT_QUALITY_ADMITTED",
    )


def compile_catalog(
    workbook_bytes: bytes,
    mapping_config: Mapping[str, object],
) -> SchemaPackCatalogV1:
    """Compile the exact XLSX bytes and mapping into a recomputable catalog."""

    if type(workbook_bytes) is not bytes or not isinstance(mapping_config, Mapping):
        raise SchemaPackCatalogError("INVALID_CATALOG_INPUT")
    try:
        config_sha256 = schema_wiki_sha256(cast(str, mapping_config["contract"]), mapping_config)
        config = _MappingConfig.model_validate(mapping_config)
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise SchemaPackCatalogError("MAPPING_CONFIG_INVALID") from exc
    workbook_sha256 = hashlib.sha256(workbook_bytes).hexdigest()
    if workbook_sha256 != config.workbook_sha256:
        raise SchemaPackCatalogError("WORKBOOK_SHA256_MISMATCH")
    workbook = _read_workbook(
        workbook_bytes,
        {mapping.workbook_sheet for mapping in config.packs},
    )
    entries: list[SchemaPackCatalogEntryV1] = []
    for mapping in config.packs:
        rows = workbook.get(mapping.workbook_sheet)
        if rows is None:
            raise SchemaPackCatalogError("WORKBOOK_SHEET_NOT_FOUND")
        try:
            entries.append(_compile_entry(workbook_sha256, rows, mapping))
        except ValidationError as exc:
            raise SchemaPackCatalogError("COMPILED_CATALOG_INVALID") from exc
    field_sets = tuple({field.field_key for field in entry.pack.fields} for entry in entries)
    union_count = len(set().union(*field_sets))
    intersection_count = len(set.intersection(*field_sets))
    if union_count != config.expected_field_name_union_count:
        raise SchemaPackCatalogError("FIELD_NAME_UNION_COUNT_MISMATCH")
    if intersection_count != config.expected_field_name_intersection_count:
        raise SchemaPackCatalogError("FIELD_NAME_INTERSECTION_COUNT_MISMATCH")
    catalog_values: dict[str, object] = {
        "contract": CATALOG_CONTRACT,
        "catalog_id": config.catalog_id,
        "catalog_version": config.catalog_version,
        "workbook_sha256": workbook_sha256,
        "mapping_config_sha256": config_sha256,
        "entries": tuple(entries),
        "field_name_union_count": union_count,
        "field_name_intersection_count": intersection_count,
    }
    catalog_values["catalog_sha256"] = schema_wiki_sha256(CATALOG_CONTRACT, catalog_values)
    try:
        return SchemaPackCatalogV1.model_validate(catalog_values)
    except ValidationError as exc:
        raise SchemaPackCatalogError("COMPILED_CATALOG_INVALID") from exc


def validate_catalog(catalog_json: str | bytes) -> SchemaPackCatalogV1:
    """Validate catalog JSON and recompute all nested semantic and content hashes."""

    if type(catalog_json) not in (str, bytes):
        raise SchemaPackCatalogError("CATALOG_VALIDATION_FAILED")
    try:
        return SchemaPackCatalogV1.model_validate_json(catalog_json)
    except (TypeError, ValueError, ValidationError) as exc:
        raise SchemaPackCatalogError("CATALOG_VALIDATION_FAILED") from exc


def get_catalog_entry(
    catalog: SchemaPackCatalogV1,
    *,
    schema_pack_id: str,
    schema_version: str,
) -> SchemaPackCatalogEntryV1:
    """Return the one entry matching the exact pack identity."""

    matches = tuple(
        entry
        for entry in catalog.entries
        if entry.pack.schema_pack_id == schema_pack_id
        and entry.pack.schema_version == schema_version
    )
    if len(matches) != 1:
        raise SchemaPackCatalogError("CATALOG_ENTRY_NOT_FOUND")
    return matches[0]


__all__ = [
    "CATALOG_CONTRACT",
    "FIELD_DEFINITION_CONTRACT",
    "PACK_CONTRACT",
    "FieldDefinitionV1",
    "PresentationProfileRefV1",
    "SchemaPackCatalogEntryV1",
    "SchemaPackCatalogError",
    "SchemaPackCatalogV1",
    "SchemaPackDefinitionV1",
    "compile_catalog",
    "get_catalog_entry",
    "validate_catalog",
]
