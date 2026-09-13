from __future__ import annotations

# ruff: noqa: F811
import base64
import hashlib
import importlib
import json

import pytest

from tests.product_ingestion.test_platform import canonical, decode, snapshot  # noqa: F401


def module():
    try:
        return importlib.import_module("insurance_harness.product_ingestion.source_geometry")
    except ModuleNotFoundError:
        pytest.fail("platform native geometry projector is not implemented")


def native_snapshot(snapshot, *, invalid=False):
    scope, body, sign, keys = snapshot
    body = json.loads(json.dumps(body))
    markdown = body["markdown"]
    page_end = body["chunk_page_mappings"][0]["page_spans"][0]["global_codepoint_end"]
    pages = []
    for number, (left, right) in enumerate(((0, page_end), (page_end, len(markdown))), 1):
        pages.append(
            {
                "page_number": number,
                "global_codepoint_start": left,
                "global_codepoint_end": right,
                "page_text_sha256": hashlib.sha256(markdown[left:right].encode()).hexdigest(),
                "width_points": "100",
                "height_points": "200",
                "bboxes": [
                    {
                        "global_codepoint_start": i,
                        "global_codepoint_end": i + 1,
                        "bbox": [1000, 2000, 3000, 4000],
                    }
                    for i in range(left, right)
                    if not markdown[i].isspace()
                ],
            }
        )
    if invalid:
        pages[0]["page_text_sha256"] = "0" * 64
    native = {
        "source_sha256": body["receipt"]["file_sha256"],
        "markdown_sha256": hashlib.sha256(markdown.encode()).hexdigest(),
        "parser_identity_sha256": body["parser_identity_sha256"],
        "pages": pages,
    }
    raw = canonical(native)
    body["native"]["SanitizedJSON"] = base64.b64encode(raw).decode()
    body["native"]["SanitizedSHA256"] = body["native_capture_sha256"] = hashlib.sha256(
        raw
    ).hexdigest()
    return decode(snapshot, sign(body))


def test_geometry_uses_actual_page_offsets_and_boxes_without_rebuilding_source(snapshot):
    decoded = native_snapshot(snapshot)
    pages = module().project_native_pages(decoded, material_id="material")
    assert len(pages) == 1
    page = pages[0]
    assert page.page_number == 1 and page.page_width == 100.0 and page.page_height == 200.0
    assert page.text == decoded.snapshot["markdown"][: len("平安测试（2026）两全保险\n保险条款\n")]
    assert page.boxes[0].x == 0.1 and page.boxes[0].height == 0.4
    assert decoded.blocks[0].text.endswith("平安其他（2025）两全保险")
    assert decoded.unresolved_chunk_ids == ("unmapped",)


def test_signed_but_inconsistent_native_page_hash_is_refused(snapshot):
    with pytest.raises(ValueError, match="native page"):
        module().project_native_pages(
            native_snapshot(snapshot, invalid=True), material_id="material"
        )
