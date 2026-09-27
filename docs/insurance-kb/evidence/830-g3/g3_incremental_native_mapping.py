"""Native block mapping reused by manifest-driven G3 source preparation.

The mapping functions are preserved from the previous validated source builder;
no provider, upload or serving-state effect occurs in this module.
"""
from __future__ import annotations
import hashlib
import json
import math
import re
import unicodedata
from typing import Any
from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_json_bytes_830_g3
from insurance_harness.knowledge_compiler.batch_entity_resolution_830_g3 import SourceBlock, Evidence
from insurance_harness.knowledge_compiler.g3_bounded_model_execution import G3NativeCharacterBoxV1, G3NativePageProjectionV1
TENANT_ID=10003
SPACE_ID="a8751a40-83ce-55c8-a160-079b283483ca"
RAW_KB_ID="b1f1764c-443d-46b8-98e3-d5aa5e55eb42"
def canonical(value: object) -> bytes:
    def validate(item: object, *, object_key: bool = False) -> None:
        if isinstance(item, str):
            if unicodedata.normalize("NFC", item) != item or any(
                    ord(char) == 0x7f
                    or (ord(char) < 0x20 and (object_key or char not in "\t\n\r"))
                    for char in item):
                raise RuntimeError("JSON text is not canonical NFC or contains a control")
        elif isinstance(item, dict):
            for key, child in item.items():
                validate(key, object_key=True)
                validate(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                validate(child)

    validate(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()

def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def _page_boxes(page: dict[str, Any], markdown: str) -> tuple[G3NativeCharacterBoxV1, ...]:
    start, end = page["global_codepoint_start"], page["global_codepoint_end"]
    width, height = float(page["width_points"]), float(page["height_points"])
    if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
        raise RuntimeError("native page dimension drift")
    boxes: dict[int, G3NativeCharacterBoxV1] = {}
    for row in page.get("bboxes", []):
        begin, finish = row.get("global_codepoint_start"), row.get("global_codepoint_end")
        bbox = row.get("bbox")
        if type(begin) is not int or type(finish) is not int or not start <= begin < finish <= end \
                or not isinstance(bbox, list) or len(bbox) != 4:
            raise RuntimeError("native bbox drift")
        x1, y1, x2, y2 = bbox
        if any(type(value) is not int for value in bbox) or not 0 <= x1 < x2 <= 1_000_000 \
                or not 0 <= y1 < y2 <= 1_000_000:
            raise RuntimeError("native bbox coordinate drift")
        for absolute in range(begin, finish):
            relative = absolute - start
            if markdown[absolute].isspace():
                continue
            if relative in boxes:
                raise RuntimeError("native bbox overlap")
            boxes[relative] = G3NativeCharacterBoxV1(
                index=relative, x=float(width * x1 / 1_000_000),
                y=float(height * y1 / 1_000_000),
                width=float(width * (x2 - x1) / 1_000_000),
                height=float(height * (y2 - y1) / 1_000_000),
            )
    return tuple(boxes[index] for index in sorted(boxes))

def _native_evidence(source: SourceBlock, projection: G3NativePageProjectionV1,
                     start: int, end: int) -> Evidence | None:
    if projection.revision_id != source.revision_id or projection.block_id != source.block_id:
        raise RuntimeError("native projection/source block identity drift")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source.text):
        raise RuntimeError("W1 evidence span drift")
    quote = source.text[start:end]
    if not quote or projection.text.count(quote) != 1:
        return None
    at = projection.text.find(quote)
    covered = {box.index for box in projection.boxes}
    visible = {index for index, char in enumerate(quote, start=at) if not char.isspace()}
    if not visible or not visible <= covered:
        return None
    return Evidence(**source.model_dump(exclude={"text"}), start=start, end=end,
                    quote=quote, quote_hash=sha256(quote.encode()))

def _mapped_blocks(material_id: str, chunks: list[dict[str, Any]], receipt: dict[str, Any],
                   _descriptor: dict[str, Any], file_sha256: str, native: dict[str, Any],
                   pages: list[dict[str, Any]]) -> tuple[
                   list[SourceBlock], list[G3NativePageProjectionV1], dict[str, Evidence]
                   ]:
    markdown = native["__markdown"]
    parser_sha = native.get("parser_identity_sha256")
    if not isinstance(parser_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", parser_sha):
        raise RuntimeError("native parser identity drift")
    page_boxes = {page["page_number"]: _page_boxes(page, markdown) for page in pages}
    covered_by_page = {
        page_number: {box.index for box in boxes}
        for page_number, boxes in page_boxes.items()
    }
    blocks, projections, evidence_by_hash = [], [], {}
    for chunk in chunks:
        text = chunk.get("content")
        block_id = chunk.get("id")
        if not isinstance(text, str) or not text or not isinstance(block_id, str) or not block_id:
            raise RuntimeError("actual W1 block drift")
        candidates = []
        cursor = 0
        for physical in text.splitlines(keepends=True):
            quote = physical.strip()
            begin = cursor + len(physical) - len(physical.lstrip())
            cursor += len(physical)
            if sum(not char.isspace() for char in quote) < 8:
                continue
            for page in pages:
                page_text = markdown[page["global_codepoint_start"]:page["global_codepoint_end"]]
                if page_text.count(quote) != 1:
                    continue
                at = page_text.find(quote)
                covered = covered_by_page[page["page_number"]]
                visible = {index for index, char in enumerate(quote, start=at)
                           if not char.isspace()}
                if visible <= covered:
                    candidates.append((-sum(not char.isspace() for char in quote), begin,
                                       page["page_number"], sha256(quote.encode()), page))
        if not candidates:
            continue
        _length, _begin, page_number, _quote_sha, page = sorted(candidates, key=lambda row: row[:4])[0]
        source = SourceBlock(
            tenant_id=TENANT_ID, space_id=SPACE_ID, raw_kb_id=RAW_KB_ID,
            knowledge_id=receipt["knowledge_id"], parse_attempt=receipt["parse_attempt"],
            revision_id=receipt["revision_source_id"], source_hash=file_sha256,
            parse_hash=receipt["manifest_digest"], parser_identity=parser_sha,
            block_id=block_id, page_number=page_number, text=text, source_type="DOCUMENT",
        )
        block_ref = sha256(b"g3-c-block-ref.830.v1\0" + canonical({
            "material_id": material_id, "revision_id": source.revision_id,
            "block_id": source.block_id,
        }))
        projection = G3NativePageProjectionV1(
            block_ref=block_ref, material_id=material_id,
            revision_id=source.revision_id, block_id=source.block_id,
            page_number=page_number, page_width=float(page["width_points"]),
            page_height=float(page["height_points"]),
            text=markdown[page["global_codepoint_start"]:page["global_codepoint_end"]],
            boxes=page_boxes[page_number],
        )
        for match in re.finditer(r"[^\r\n]+", text):
            quote = match.group(0).strip()
            if len(quote) < 1:
                continue
            start = match.start() + len(match.group(0)) - len(match.group(0).lstrip())
            evidence = _native_evidence(source, projection, start, start + len(quote))
            if evidence is not None:
                evidence_by_hash[sha256(batch_json_bytes_830_g3(evidence))] = evidence
        blocks.append(source)
        projections.append(projection)
    if not blocks:
        raise RuntimeError(f"material lacks a unique native mapped W1 block: {material_id}")
    return blocks, projections, evidence_by_hash
