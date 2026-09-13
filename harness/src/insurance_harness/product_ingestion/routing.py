"""First-page product routing with exact original evidence; no model or I/O."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    Evidence,
    SourceBlock,
    evidence_for,
)
from insurance_harness.knowledge_compiler.g3_title_routing import (
    FormalTitleRouteV1,
    route_formal_title,
)
from insurance_harness.knowledge_compiler.schema_pack_catalog_830_g3 import SchemaPackCatalogV1

# Whole heading lines only. Never infer a title from a filename or a paragraph.
_KINDS = (
    "重大疾病保险",
    "养老年金保险",
    "补充养老保险",
    "两全保险",
    "终身寿险",
    "定期寿险",
    "年金保险",
    "医疗保险",
    "护理保险",
    "失能收入损失保险",
    "意外伤害保险",
    "意外伤害医疗保险",
    "疾病保险",
)
_TITLE = re.compile(
    r"^[ \t]*(?P<title>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9（）()· \t-]{1,100}?"
    r"(?:\r?\n[ \t]*)?(?:" + "|".join(_KINDS) + r")"
    r"(?:[（(](?:分红型|万能型|投资连结型)[）)])?)"
    r"[ \t]*(?:保险条款|条款|产品说明书|费率表)?[ \t\r]*$",
    re.MULTILINE,
)
_ROLES = {"terms": ("保险条款", "条款"), "brochure": ("产品说明书",), "rate_table": ("费率表",)}
_ANCHORS = {
    "product_code": re.compile(r"(?:产品代码|条款编码|产品编号)[：:\s]*([A-Za-z0-9_-]{2,64})"),
    "filing": re.compile(r"([\u4e00-\u9fff]{2,20}[〔\[]\d{4}[〕\]][\u4e00-\u9fff]{1,20}\d{1,6}号)"),
}


@dataclass(frozen=True)
class RoutedMaterial:
    material_id: str
    file_name: str
    material_type: str | None
    product_name: str | None
    title_evidence: tuple[Evidence, ...]
    reason: str | None
    identity_anchors: tuple[tuple[str, str, Evidence], ...] = ()


@dataclass(frozen=True)
class ProductRouting:
    status: Literal["matched", "needs_confirmation"]
    product_name: str | None
    route: FormalTitleRouteV1 | None
    materials: tuple[RoutedMaterial, ...]
    reason: str | None = None


def _identity(name: str) -> str:
    # Only the identity is normalized. Evidence is always the original substring.
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", name)).translate(
        str.maketrans({"(": "（", ")": "）"})
    )


def _material_role(file_name: str, first_pages: Sequence[str]) -> tuple[str | None, str | None]:
    filename_roles = {
        role for role, labels in _ROLES.items() if any(x in file_name for x in labels)
    }
    heading_roles = set()
    for text in first_pages:
        # Long paragraphs mentioning other materials are not role headings.
        for line in text.splitlines()[:20]:
            if len(line.strip()) <= 120:
                for role, labels in _ROLES.items():
                    heading = line.strip()
                    if any(heading == label for label in labels) or (
                        _TITLE.fullmatch(heading) is not None
                        and any(heading.endswith(label) for label in labels)
                    ):
                        heading_roles.add(role)
    roles = filename_roles | heading_roles
    if len(roles) > 1:
        return None, "MATERIAL_TYPE_CONFLICT"
    if not roles:
        return None, "MATERIAL_TYPE_UNAVAILABLE"
    return roles.pop(), None


def _first_page_slices(item, blocks):
    ranges = item.get("first_page_ranges")
    slices = []
    for block in blocks:
        if block.page_number != 1:
            continue
        # Native snapshot page spans take precedence over a block's start page.
        # Missing mapping in a mapped snapshot never grants the whole block.
        spans = [(0, len(block.text))] if ranges is None else ranges.get(block.block_id, [])
        previous_end = 0
        for start, end in spans:
            if (
                type(start) is not int
                or type(end) is not int
                or start < previous_end
                or end <= start
                or end > len(block.text)
            ):
                raise ValueError("FIRST_PAGE_RANGE_INVALID")
            slices.append((block, start, block.text[start:end]))
            previous_end = end
    return slices


def route_product_materials(
    materials: Sequence[Mapping[str, Any]],
    *,
    catalog: SchemaPackCatalogV1,
) -> ProductRouting:
    """Route one upload group, or return an explicit identity/role conflict.

    The input is native source blocks already sealed by the source adapter. Page
    one is mandatory for each material; filename hints only material type. A
    later integration may split independent products into separate runs, but this
    function will never combine unlike names inside one product candidate.
    """
    if not materials:
        raise ValueError("MATERIALS_REQUIRED")
    ids = [item["material_id"] for item in materials]
    if any(not isinstance(mid, str) or not mid for mid in ids) or len(set(ids)) != len(ids):
        raise ValueError("MATERIAL_IDENTITY_INVALID")
    scope = None
    routed = []
    for item in materials:
        blocks = tuple(item["blocks"])
        if not blocks or any(not isinstance(block, SourceBlock) for block in blocks):
            raise ValueError("SOURCE_BLOCKS_REQUIRED")
        knowledge_ids = {block.knowledge_id for block in blocks}
        revision_keys = {
            (
                block.parse_attempt,
                block.revision_id,
                block.source_hash,
                block.parse_hash,
                block.parser_identity,
            )
            for block in blocks
        }
        if len(knowledge_ids) != 1 or len(revision_keys) != 1:
            raise ValueError("SOURCE_REVISION_CONFLICT")
        for block in blocks:
            current = (block.tenant_id, block.space_id, block.raw_kb_id)
            if scope is not None and scope != current:
                raise ValueError("SOURCE_SCOPE_MISMATCH")
            scope = current
        first_pages = _first_page_slices(item, blocks)
        role, role_error = _material_role(item["file_name"], [text for _, _, text in first_pages])
        names: dict[str, list[Evidence]] = {}
        anchors = []
        for block, offset, text in first_pages:
            for kind, pattern in _ANCHORS.items():
                for match in pattern.finditer(text):
                    anchors.append(
                        (
                            kind,
                            _identity(match.group(1)),
                            evidence_for(block, offset + match.start(1), offset + match.end(1)),
                        )
                    )
            for match in _TITLE.finditer(text):
                title = _identity(match.group("title"))
                names.setdefault(title, []).append(
                    evidence_for(block, offset + match.start("title"), offset + match.end("title"))
                )
        name = next(iter(names)) if len(names) == 1 else None
        error = role_error or (
            "FIRST_PAGE_PRODUCT_NAME_UNAVAILABLE"
            if not names
            else "MULTIPLE_FIRST_PAGE_PRODUCT_NAMES"
            if len(names) > 1
            else None
        )
        routed.append(
            RoutedMaterial(
                material_id=item["material_id"],
                file_name=item["file_name"],
                material_type=role,
                product_name=name,
                title_evidence=tuple(e for values in names.values() for e in values),
                reason=error,
                identity_anchors=tuple(anchors),
            )
        )
    rows = tuple(routed)
    error = next((row.reason for row in rows if row.reason), None)
    if error:
        return ProductRouting("needs_confirmation", None, None, rows, error)
    names = {row.product_name for row in rows}
    anchor_conflict = any(
        len({value for row in rows for key, value, _ in row.identity_anchors if key == kind}) > 1
        for kind in _ANCHORS
    )
    if len(names) != 1 or anchor_conflict:
        return ProductRouting(
            "needs_confirmation", None, None, rows, "PRODUCT_IDENTITY_OR_VERSION_CONFLICT"
        )
    name = next(iter(names))
    assert name is not None
    route = route_formal_title(name, catalog=catalog)
    if route.classification_status != "KNOWN":
        return ProductRouting("needs_confirmation", name, route, rows, "SCHEMA_MATCH_UNRESOLVED")
    return ProductRouting("matched", name, route, rows)
