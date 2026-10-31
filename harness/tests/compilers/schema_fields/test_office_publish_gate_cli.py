"""S11c review R1 on #479, end to end: an Office page set never reaches the platform as PDF text.

The real source-pages reader serves the publish command over a fake platform. A page that declares
`blocks: []` but carries text is refused with PARSE_ARTIFACT_INTEGRITY before any candidate is
sent; the only platform request is the Active read. The same text with legitimate blocks publishes
its evidence with the block's Office locator, which the platform verifies since S11d (S11d Spec §4;
this replaced the S11c gate test), and a PDF page publishes the same PDF_TEXT_SPAN as before.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient
from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.compilers.schema_fields import publish as command
from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.contracts import Locator
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.office_pages import OfficeBlock, OfficePageText
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.weknora_pages import WeKnoraSourcePages
from insurance_harness.ingest import source_map as source_map_module

DOCUMENT = "产品说明书.docx"
DOC_SHA = hashlib.sha256(b"docx bytes").hexdigest()
TITLE, BODY = "产品说明书", "等待期为90日。"
TEXT = f"{TITLE}\n\n{BODY}"
CATALOG_ENTRY = {
    "pack": {
        "schema_pack_id": "pack",
        "display_name": "演示险",
        "entity_type": "insurance_product",
        "applicable_classifications": ["demo_class"],
        "presentation_profile_ref": {"profile_id": "profile_pack", "profile_version": "1"},
        "fields": [{"field_key": "waiting_period", "short_title": "等待期", "description": "d"}],
    },
    "profile": {
        "profile_id": "profile_pack",
        "profile_version": "1",
        "profile_sha256": "cd" * 32,
        "schema_pack_id": "pack",
        "sections": [
            {
                "section_key": "contract",
                "display_name": "投保与合同",
                "fields": [{"field_key": "waiting_period", "short_title": "等待期"}],
            }
        ],
    },
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def page_set(blocks: list[dict[str, Any]] | None, document: str = DOCUMENT) -> dict[str, Any]:
    """Page 1 of k-1 attempt 2; a PDF page (blocks None) has no `blocks` key."""
    page: dict[str, Any] = {"page_number": 1, "text": TEXT, "page_text_sha256": sha(TEXT)}
    if blocks is not None:
        page["blocks"] = blocks
    return {
        "knowledge_id": "k-1",
        "parse_attempt": 2,
        "document": document,
        "document_sha256": DOC_SHA,
        "parser_identity_sha256": sha("ooxml"),
        "native_sha256": sha("native"),
        "pages": [page],
    }


LEGAL_BLOCKS = [
    {"block_id": "b0", "start": 0, "end": 5, "locator": {"kind": "DOCX_BLOCK", "block_index": 0}},
    {"block_id": "b1", "start": 7, "end": 15, "locator": {"kind": "DOCX_BLOCK", "block_index": 1}},
]


class Platform:
    """Answers like the platform: no Active, then a created candidate and its decision."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []
        self.candidate: dict[str, Any] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1/enterprise/spaces/space-1/")
        self.seen.append((request.method, path))
        if path == "releases/active":
            return httpx.Response(404, json={"success": False, "code": "RELEASE_NOT_FOUND"})
        if path == "candidates":
            self.candidate = json.loads(request.content)
            return ok({"id": "cand_1", "status": "created"}, 201)
        decision = {"id": "dec_1", "candidate_id": "cand_1", "outcome": "approve"}
        return ok({**decision, "digest": "e" * 64})


def ok(data: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"success": True, "data": data})


def output_citing(source: SegmentedSource, segment_id: str) -> CompileOutput:
    field = FieldResult(
        field_key="waiting_period",
        state="present",
        value="90日",
        evidence=source.evidence([segment_id]),
        segment_ids=[segment_id],
    )
    return CompileOutput(
        pack_id="pack", entity_id="1828", model="m", fields=[field], cards_version="cards-x"
    )


def publish_with(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    served: dict[str, Any],
    output: CompileOutput,
) -> tuple[int, dict[str, Any], Platform]:
    (tmp_path / "1828").mkdir()
    (tmp_path / "1828" / "output.json").write_text(output.model_dump_json(), encoding="utf-8")
    (tmp_path / "map.json").write_text(
        json.dumps(
            {"space_id": "space-1",
             "products": {"1828": [{"knowledge_id": "k-1", "parse_attempt": 2}]}}
        ),
        encoding="utf-8",
    )
    catalog = tmp_path / "repo" / SCHEMA_PACK_CATALOG
    catalog.parent.mkdir(parents=True)
    catalog.write_text(json.dumps({"entries": [CATALOG_ENTRY]}, ensure_ascii=False), "utf-8")
    product = tmp_path / "repo" / "dataset" / "shouxian_product" / "演示"
    product.mkdir(parents=True)
    (product / "product_meta.json").write_text(
        json.dumps({"planCode": "1828", "clauseName": "演示医疗保险"}, ensure_ascii=False), "utf-8"
    )
    monkeypatch.setenv(source_map_module.BASE_URL_ENV, "https://weknora.test")
    monkeypatch.setenv(source_map_module.API_KEY_ENV, "key-123")
    pages = httpx.MockTransport(lambda request: httpx.Response(200, json=served))
    monkeypatch.setattr(
        source_map_module,
        "WeKnoraSourcePages",
        lambda base, key: WeKnoraSourcePages(base, key, transport=pages),
    )
    server = Platform()
    monkeypatch.setattr(
        command,
        "PlatformClient",
        lambda base, key: PlatformClient(base, key, transport=httpx.MockTransport(server)),
    )
    code = command.main([
        "--run-root", str(tmp_path), "--product", "1828", "--source-map",
        str(tmp_path / "map.json"), "--repo", str(tmp_path / "repo"),
        "--decide", "human", "--reason", "checked",
    ])
    return code, json.loads(capsys.readouterr().out), server


def test_text_with_empty_blocks_stops_before_any_candidate_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Before R1 the reader returned this page as PDF text: segment it the same way.
    as_pdf = SegmentedSource([PageText(DOCUMENT, DOC_SHA, 1, TEXT)])
    code, summary, server = publish_with(
        tmp_path, monkeypatch, capsys, page_set([]), output_citing(as_pdf, "D1P1S1")
    )
    assert (code, summary) == (2, {"stopped": "PARSE_ARTIFACT_INTEGRITY"})
    assert server.seen == [("GET", "releases/active")]


def submitted_evidence(server: Platform) -> list[dict[str, Any]]:
    members = server.candidate["members"]
    return [item for m in members for item in m["payload"].get("evidence", [])]


def test_legitimate_office_evidence_publishes_with_its_block_locator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    office = OfficePageText(DOCUMENT, DOC_SHA, 1, TEXT, (
        OfficeBlock(0, 5, Locator(kind="DOCX_BLOCK", block_index=0)),
        OfficeBlock(7, 15, Locator(kind="DOCX_BLOCK", block_index=1)),
    ))
    source = SegmentedSource([office])
    assert source.segments[1].text == BODY
    code, summary, server = publish_with(
        tmp_path, monkeypatch, capsys, page_set(LEGAL_BLOCKS), output_citing(source, "D1P1S2")
    )
    assert code == 0, summary
    assert server.seen[:2] == [("GET", "releases/active"), ("POST", "candidates")]
    (evidence,) = submitted_evidence(server)
    assert {key: value for key, value in evidence["locator"].items() if value is not None} == {
        "kind": "DOCX_BLOCK", "block_index": 1, "page": 1, "start": 7, "end": 15,
    }
    assert (evidence["quote"], evidence["source_ref"], evidence["file_sha256"]) == (
        BODY, f"source:v1:k-1:2:{DOC_SHA}", DOC_SHA,
    )


def test_pdf_evidence_publishes_the_same_text_span_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    served = page_set(None, "产品说明书.pdf")
    pdf = SegmentedSource([PageText("产品说明书.pdf", DOC_SHA, 1, TEXT)])
    (segment,) = pdf.segments
    code, summary, server = publish_with(
        tmp_path, monkeypatch, capsys, served, output_citing(pdf, segment.id)
    )
    assert code == 0, summary
    (evidence,) = submitted_evidence(server)
    assert evidence["locator"] == Locator(
        kind="PDF_TEXT_SPAN", page=1, start=segment.start, end=segment.end
    ).model_dump(mode="json")
    assert evidence["quote"] == TEXT[segment.start : segment.end]
