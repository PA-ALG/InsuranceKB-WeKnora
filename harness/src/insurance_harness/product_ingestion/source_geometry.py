"""Project signed parser geometry without changing source blocks or inventing locations."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence

from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
    G3NativeCharacterBoxV1,
    G3NativePageProjectionV1,
)
from insurance_harness.product_ingestion.platform import DecodedSourceSnapshot, _object


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


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
        expand = selected is None or number in selected_pages
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
        pages[number] = (page, width, height, tuple(boxes[i] for i in sorted(boxes)))
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
