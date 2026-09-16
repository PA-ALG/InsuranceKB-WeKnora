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


def test_geometry_uses_actual_page_offsets_and_boxes_without_rebuilding_source(
    snapshot,
):
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


@pytest.mark.parametrize("bad", [None, "missing", "overlap", "unknown", "duplicate"])
def test_partial_native_gap_contract_validated_on_unselected_pages(snapshot, bad):
    from dataclasses import replace

    decoded = native_snapshot(snapshot)
    native = json.loads(decoded.native_bytes)
    native["contract"] = "builtin-pdfium-native-locators.v2"
    page = native["pages"][1]
    row = page["bboxes"].pop()
    gap = {key: value for key, value in row.items() if key != "bbox"}
    gap["reason"] = "bbox_invalid"
    page["unavailable_ranges"] = [gap]
    if bad == "missing":
        page["unavailable_ranges"] = []
    elif bad == "overlap":
        page["bboxes"].append(row)
    elif bad == "unknown":
        gap["reason"] = "made_up"
    elif bad == "duplicate":
        page["unavailable_ranges"].append(dict(gap))
    changed = replace(decoded, native_bytes=canonical(native))
    if bad:
        with pytest.raises(ValueError, match="native.*(gap|coverage)"):
            module()._validated_native_pages(changed, selected_pages={1})
    else:
        pages = module()._validated_native_pages(changed, selected_pages={1})
        assert pages[1][3] and pages[2][0]["unavailable_ranges"] == [gap]


def bounded_identity_snapshot(snapshot):
    """Signed four-page source including overlapping chunks and a large late page."""
    scope, original, sign, keys = snapshot
    body = json.loads(json.dumps(original))
    texts = [
        "平安测试（2026）两全保险\n保险条款\n",
        "测试人寿保险股份有限公司\n",
        "其他人寿保险股份有限公司\n",
        "后页费率数据" * 700,
    ]
    markdown = "".join(texts)
    starts = [sum(map(len, texts[:index])) for index in range(4)]
    body["markdown"] = markdown
    body["receipt"].update(
        page_count=4, chunk_count=4, manifest_algorithm="weknora.chunk_manifest.v1"
    )
    body["chunks"] = []
    body["chunk_page_mappings"] = []
    specs = [("block", 0, 2), ("issuer", 1, 2), ("issuer3", 2, 3), ("late", 3, 4)]
    for index, (block_id, first, last) in enumerate(specs):
        left, right = starts[first], sum(map(len, texts[:last]))
        text = markdown[left:right]
        body["chunks"].append(
            {
                "id": block_id,
                "index": index,
                "content": text,
                "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
        )
        body["chunk_page_mappings"].append(
            {
                "chunk_id": block_id,
                "status": "EXACT_BLOCK",
                "source_page_number": first + 1,
                "block_global_start": left,
                "block_global_end": right,
                "page_spans": [
                    {
                        "page_number": page + 1,
                        "block_codepoint_start": starts[page] - left,
                        "block_codepoint_end": starts[page] + len(texts[page]) - left,
                        "global_codepoint_start": starts[page],
                        "global_codepoint_end": starts[page] + len(texts[page]),
                    }
                    for page in range(first, last)
                ],
            }
        )
    native = {
        "source_sha256": body["receipt"]["file_sha256"],
        "markdown_sha256": hashlib.sha256(markdown.encode()).hexdigest(),
        "parser_identity_sha256": body["parser_identity_sha256"],
        "pages": [
            {
                "page_number": page + 1,
                "global_codepoint_start": starts[page],
                "global_codepoint_end": starts[page] + len(text),
                "page_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "width_points": "100",
                "height_points": "200",
                "bboxes": [
                    {
                        "global_codepoint_start": starts[page] + offset,
                        "global_codepoint_end": starts[page] + offset + 1,
                        "bbox": [(page + 1) * 1000, 2000, (page + 2) * 1000, 4000],
                    }
                    for offset, char in enumerate(text)
                    if not char.isspace()
                ],
            }
            for page, text in enumerate(texts)
        ],
    }
    raw = canonical(native)
    body["native"]["SanitizedJSON"] = base64.b64encode(raw).decode()
    body["native"]["SanitizedSHA256"] = body["native_capture_sha256"] = hashlib.sha256(
        raw
    ).hexdigest()
    return decode(snapshot, sign(body))


def test_selected_geometry_avoids_unselected_character_objects_and_preserves_output(
    snapshot, monkeypatch
):
    decoded = bounded_identity_snapshot(snapshot)
    projector = module()
    original_body = canonical(decoded.snapshot)
    full = projector.project_native_pages(decoded, material_id="knowledge")
    assert {page.page_number for page in full} == {1, 2, 3, 4}
    constructed = []
    original = projector.G3NativeCharacterBoxV1

    def record(**values):
        constructed.append(values["x"])
        return original(**values)

    monkeypatch.setattr(projector, "G3NativeCharacterBoxV1", record)
    selected = projector.project_native_pages(
        decoded, material_id="knowledge", selected_block_ids=("block", "issuer")
    )
    assert selected == tuple(page for page in full if page.block_id in {"block", "issuer"})
    assert constructed and set(constructed) == {0.1, 0.2}
    assert canonical(decoded.snapshot) == original_body and len(decoded.blocks) == 4


@pytest.mark.parametrize("bad", ["hash", "range", "coordinate", "overlap"])
def test_selected_geometry_still_rejects_corrupt_unselected_native_page(snapshot, bad):
    from dataclasses import replace

    decoded = bounded_identity_snapshot(snapshot)
    native = json.loads(decoded.native_bytes)
    later = native["pages"][-1]
    if bad == "hash":
        later["page_text_sha256"] = "0" * 64
    elif bad == "range":
        later["global_codepoint_end"] += 1
    elif bad == "coordinate":
        later["bboxes"][0]["bbox"][2] = 1_000_001
    else:
        later["bboxes"].append(dict(later["bboxes"][0]))
    with pytest.raises(ValueError, match="native page"):
        module().project_native_pages(
            replace(decoded, native_bytes=canonical(native)),
            material_id="knowledge",
            selected_block_ids=("block", "issuer"),
        )


@pytest.mark.parametrize("selection", [("unknown",), ("block", "block")])
def test_selected_geometry_rejects_invalid_block_selection(snapshot, selection):
    with pytest.raises(ValueError, match="selection"):
        module().project_native_pages(
            bounded_identity_snapshot(snapshot),
            material_id="knowledge",
            selected_block_ids=selection,
        )
