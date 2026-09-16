"""Project signed parser geometry without changing source blocks or inventing locations."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass

from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
    G3NativeCharacterBoxV1,
    G3NativePageProjectionV1,
)
from insurance_harness.product_ingestion.platform import DecodedSourceSnapshot, _object


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _validate_partial_coverage(native, page, markdown, intervals):
    """Validate declared geometry gaps even when a page isn't being expanded."""
    gaps = page.get("unavailable_ranges", [])
    if native.get("contract") != "builtin-pdfium-native-locators.v2":
        if gaps:
            raise ValueError("native gaps require partial locator contract")
        return
    start, end = page["global_codepoint_start"], page["global_codepoint_end"]
    dispositions = [(left, right) for left, right in intervals]
    previous = start
    for gap in gaps:
        if not isinstance(gap, dict) or set(gap) != {"global_codepoint_start", "global_codepoint_end", "reason"}:
            raise ValueError("native gap declaration malformed")
        left, right = gap["global_codepoint_start"], gap["global_codepoint_end"]
        if (
            type(left) is not int or type(right) is not int
            or not start <= left < right <= end or left < previous
            or gap["reason"] not in {"bbox_invalid", "bbox_unavailable", "character_mapping_unavailable", "page_rotation_unsupported"}
            or any(ch.isspace() for ch in markdown[left:right])
        ):
            raise ValueError("native gap range or reason invalid")
        dispositions.append((left, right))
        previous = right
    occupied = start
    for left, right in sorted(dispositions):
        if left < occupied or any(not ch.isspace() for ch in markdown[occupied:left]):
            raise ValueError("native gap coverage overlaps or is incomplete")
        occupied = right
    if any(not ch.isspace() for ch in markdown[occupied:end]):
        raise ValueError("native gap coverage is incomplete")


def _validated_native_pages(decoded: DecodedSourceSnapshot, *, selected_pages=None):
    body = decoded.snapshot
    markdown = body["markdown"]
    native = json.loads(decoded.native_bytes, object_pairs_hook=_object)
    if (
        native.get("source_sha256") != body["receipt"]["file_sha256"]
        or native.get("markdown_sha256") != _sha(markdown.encode())
        or native.get("parser_identity_sha256") != body["parser_identity_sha256"]
    ):
        raise ValueError("native page source identity mismatch")
    pages = {}
    previous_end = 0
    for page in native["pages"]:
        number = page["page_number"]
        start, end = page["global_codepoint_start"], page["global_codepoint_end"]
        width, height = float(page["width_points"]), float(page["height_points"])
        if (
            type(number) is not int
            or number != len(pages) + 1
            or type(start) is not int
            or type(end) is not int
            or not previous_end <= start <= end <= len(markdown)
            or page["page_text_sha256"] != _sha(markdown[start:end].encode())
            or not all(math.isfinite(value) and value > 0 for value in (width, height))
        ):
            raise ValueError("native page range, hash, or dimension mismatch")
        previous_end = end
        boxes = {}
        intervals = []
        expand = selected_pages is None or number in selected_pages
        for row in page.get("bboxes", []):
            begin, finish = (
                row.get("global_codepoint_start"),
                row.get("global_codepoint_end"),
            )
            bbox = row.get("bbox")
            if (
                type(begin) is not int
                or type(finish) is not int
                or not start <= begin < finish <= end
                or not isinstance(bbox, list)
                or len(bbox) != 4
                or any(type(value) is not int for value in bbox)
            ):
                raise ValueError("native page bbox range mismatch")
            x1, y1, x2, y2 = bbox
            if not 0 <= x1 < x2 <= 1_000_000 or not 0 <= y1 < y2 <= 1_000_000:
                raise ValueError("native page bbox coordinate mismatch")
            intervals.append((begin, finish))
            if not expand:
                continue
            for absolute in range(begin, finish):
                if markdown[absolute].isspace():
                    continue
                relative = absolute - start
                if relative in boxes:
                    raise ValueError("native page bbox overlap")
                boxes[relative] = G3NativeCharacterBoxV1(
                    index=relative,
                    x=width * x1 / 1_000_000,
                    y=height * y1 / 1_000_000,
                    width=width * (x2 - x1) / 1_000_000,
                    height=height * (y2 - y1) / 1_000_000,
                )
        # Unselected pages retain range/coordinate/overlap validation without
        # allocating one Pydantic object per visible character. Whitespace-only
        # overlap remains legal, exactly as in the full character projection.
        if not expand:
            occupied_end = start
            for begin, finish in sorted(intervals):
                if (
                    begin < occupied_end
                    and not markdown[begin : min(finish, occupied_end)].isspace()
                ):
                    raise ValueError("native page bbox overlap")
                occupied_end = max(occupied_end, finish)
        _validate_partial_coverage(native, page, markdown, intervals)
        pages[number] = (page, width, height, tuple(boxes[i] for i in sorted(boxes)))
    return pages


def project_native_pages(
    decoded: DecodedSourceSnapshot,
    *,
    material_id: str,
    selected_block_ids: Sequence[str] | None = None,
) -> tuple[G3NativePageProjectionV1, ...]:
    selected = None
    if selected_block_ids is not None:
        if isinstance(selected_block_ids, (str, bytes)):
            raise ValueError("native block selection must contain unique existing IDs")
        selected = set(selected_block_ids)
        available = {block.block_id for block in decoded.blocks}
        if len(selected) != len(selected_block_ids) or not selected <= available:
            raise ValueError("native block selection must contain unique existing IDs")
    selected_pages = {
        block.page_number
        for block in decoded.blocks
        if selected is None or block.block_id in selected
    }
    pages = _validated_native_pages(
        decoded, selected_pages=selected_pages if selected is not None else None
    )
    markdown = decoded.snapshot["markdown"]
    result = []
    for block in decoded.blocks:
        if block.page_number not in pages:
            raise ValueError("native page missing for exact source block")
        if selected is not None and block.block_id not in selected:
            continue
        page, width, height, boxes = pages[block.page_number]
        identity = json.dumps(
            {
                "material_id": material_id,
                "revision_id": block.revision_id,
                "block_id": block.block_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        result.append(
            G3NativePageProjectionV1(
                block_ref=_sha(b"g3-c-block-ref.830.v1\0" + identity),
                material_id=material_id,
                revision_id=block.revision_id,
                block_id=block.block_id,
                page_number=block.page_number,
                page_width=width,
                page_height=height,
                text=markdown[page["global_codepoint_start"] : page["global_codepoint_end"]],
                boxes=boxes,
            )
        )
    return tuple(result)


@dataclass(frozen=True)
class EvidenceLocationIndex:
    decoded: DecodedSourceSnapshot
    mappings: dict
    pages: dict


def prepare_evidence_locations(decoded: DecodedSourceSnapshot, evidences):
    """Validate/index each source once for the current evidence dependency set."""
    mappings = {r["chunk_id"]: r for r in decoded.snapshot["chunk_page_mappings"]}
    selected = set()
    for evidence in evidences:
        row = mappings.get(evidence.block_id)
        if row is None or row["status"] != "EXACT_BLOCK":
            continue
        start = row["block_global_start"] + evidence.start
        end = row["block_global_start"] + evidence.end
        selected.update(
            span["page_number"]
            for span in row["page_spans"]
            if span["global_codepoint_start"] < end and start < span["global_codepoint_end"]
        )
    return EvidenceLocationIndex(
        decoded, mappings, _validated_native_pages(decoded, selected_pages=selected)
    )


def project_evidence_locations(evidence, decoded: DecodedSourceSnapshot, *, page_index=None):
    """Project one unchanged quote into the existing multiple-citation representation.

    Physical page separators have no PDF glyphs. Preserve them explicitly in the
    mapping audit, while every non-whitespace code point belongs to an exact,
    fully located citation. Original evidence and source records are immutable.
    """
    from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
        Evidence,
        verify_evidence,
    )

    verify_evidence(evidence, decoded.blocks)
    if page_index is None:
        page_index = prepare_evidence_locations(decoded, (evidence,))
    if page_index.decoded is not decoded:
        raise ValueError("native index source identity mismatch")
    mapping = page_index.mappings.get(evidence.block_id)
    if mapping is None or mapping["status"] != "EXACT_BLOCK":
        raise ValueError("EVIDENCE_BLOCK_LOCATION_MISSING")
    origin = mapping["block_global_start"]
    start, end = origin + evidence.start, origin + evidence.end
    markdown = decoded.snapshot["markdown"]
    if markdown[start:end] != evidence.quote:
        raise ValueError("EVIDENCE_SOURCE_RANGE_MISMATCH")
    pages = page_index.pages
    pieces, gaps, audit = [], [], []
    cursor = start

    def gap(left, right):
        if left == right:
            return
        text = markdown[left:right]
        ranges = [row[0] for row in pages.values()]
        between_pages = any(
            a["global_codepoint_end"] <= left < right <= b["global_codepoint_start"]
            for a, b in zip(ranges, ranges[1:], strict=False)
        )
        if not text.isspace() or not between_pages:
            raise ValueError("EVIDENCE_UNLOCATED_CONTENT")
        gaps.append({"global_start": left, "global_end": right, "text": text})

    for number, (page, _width, _height, boxes) in pages.items():
        left = max(start, page["global_codepoint_start"])
        right = min(end, page["global_codepoint_end"])
        if left >= right:
            continue
        gap(cursor, left)
        quote = markdown[left:right]
        if not quote.strip():
            # A standalone whitespace page cannot form a useful evidence claim.
            raise ValueError("EVIDENCE_EMPTY_PAGE_FRAGMENT")
        located = {box.index for box in boxes}
        if any(
            left + i - page["global_codepoint_start"] not in located
            for i, char in enumerate(quote)
            if not char.isspace()
        ):
            raise ValueError("EVIDENCE_CHARACTER_LOCATION_MISSING")
        part = Evidence.model_validate(
            {
                **evidence.model_dump(),
                "start": left - origin,
                "end": right - origin,
                "quote": quote,
                "quote_hash": _sha(quote.encode()),
            }
        )
        verify_evidence(part, decoded.blocks)
        pieces.append(part)
        audit.append(
            {
                "actual_page_number": number,
                "global_start": left,
                "global_end": right,
                "start": part.start,
                "end": part.end,
                "quote_hash": part.quote_hash,
            }
        )
        cursor = right
    gap(cursor, end)
    if not pieces:
        raise ValueError("EVIDENCE_PAGE_LOCATION_MISSING")
    return tuple(pieces), {
        "original_quote_hash": evidence.quote_hash,
        "original_start": evidence.start,
        "original_end": evidence.end,
        "parts": audit,
        "gaps": gaps,
    }
