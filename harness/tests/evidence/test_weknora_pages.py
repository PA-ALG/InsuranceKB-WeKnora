"""S4c-1 acceptance: Harness reads per-page source text from WeKnora (Spec §3.2).

Protected file: written by Claude. Pages arrive as a PageSet, are re-hashed one by one and
become the compiler's PageText verbatim, so code-point offsets agree with the platform's
character boxes. Failures are typed and never echo the response body.
"""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.weknora_pages import SourcePagesError, WeKnoraSourcePages

BASE = "https://weknora.example"
PATH = "/api/v1/enterprise/spaces/space-1/sources/k-1/attempts/2/pages"
FIRST = "1.4 等待期\r\n自本合同生效之日起90日内为等待期。𠮷"
SECOND = "1.5 保险期间\n本合同保险期间为一年。"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def page_set(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "knowledge_id": "k-1",
        "parse_attempt": 2,
        "document": "保险条款.pdf",
        "document_sha256": sha("pdf bytes"),
        "parser_identity_sha256": sha("pdfium"),
        "native_sha256": sha("native"),
        "pages": [
            {"page_number": 1, "text": FIRST, "page_text_sha256": sha(FIRST)},
            {"page_number": 2, "text": SECOND, "page_text_sha256": sha(SECOND)},
        ],
    }
    body.update(changes)
    return body


def reader(handler: httpx.MockTransport) -> WeKnoraSourcePages:
    return WeKnoraSourcePages(BASE, "key-123", transport=handler)


def serve(status: int, body: object, seen: list[httpx.Request] | None = None) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(respond)


def test_pages_become_page_text_verbatim() -> None:
    seen: list[httpx.Request] = []
    pages = reader(serve(200, page_set(), seen)).pages("space-1", "k-1", 2)
    assert seen[0].method == "GET" and seen[0].url.path == PATH
    assert seen[0].headers["X-API-Key"] == "key-123"
    assert pages == [
        PageText("保险条款.pdf", sha("pdf bytes"), 1, FIRST),
        PageText("保险条款.pdf", sha("pdf bytes"), 2, SECOND),
    ]


def test_segment_offsets_are_code_points_of_the_platform_page() -> None:
    pages = reader(serve(200, page_set())).pages("space-1", "k-1", 2)
    source = SegmentedSource(pages)
    quote = source.evidence(["D1P1S1"])[0]
    start = FIRST.index("1.4")
    assert quote.quote == FIRST[start : start + len(quote.quote)]
    assert "\r\n" in quote.quote, "line breaks stay exactly as the platform returned them"


@pytest.mark.parametrize(
    "changes",
    [
        {"pages": [{"page_number": 1, "text": FIRST, "page_text_sha256": sha(SECOND)}]},
        {"pages": [{"page_number": 2, "text": SECOND, "page_text_sha256": sha(SECOND)}]},
        {"pages": []},
        {"knowledge_id": "k-9"},
        {"parse_attempt": 3},
        {"document_sha256": "not-a-digest"},
    ],
)
def test_pages_that_do_not_verify_are_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(SourcePagesError):
        reader(serve(200, page_set(**changes))).pages("space-1", "k-1", 2)


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (404, "SOURCE_NOT_FOUND"),
        (409, "PARSE_ARTIFACT_NOT_CAPTURED"),
        (500, "PARSE_ARTIFACT_INTEGRITY"),
        (403, "RELEASE_ACCESS_DENIED"),
    ],
)
def test_platform_errors_are_typed_and_never_echo_the_body(status: int, code: str) -> None:
    body = {"success": False, "code": code, "error": "保险条款原文-SECRET"}
    with pytest.raises(SourcePagesError) as caught:
        reader(serve(status, body)).pages("space-1", "k-1", 2)
    assert caught.value.code == code
    assert "SECRET" not in str(caught.value)


def test_a_non_json_body_is_rejected_without_echoing_it() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="<html>SECRET</html>"))
    with pytest.raises(SourcePagesError) as caught:
        reader(transport).pages("space-1", "k-1", 2)
    assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize("knowledge_id", ["", "../k-1", "k 1"])
def test_identifiers_are_validated_before_any_request(knowledge_id: str) -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(SourcePagesError):
        reader(serve(200, page_set(), seen)).pages("space-1", knowledge_id, 2)
    assert seen == []


def test_the_body_is_parsed_as_strict_json() -> None:
    raw = json.dumps(page_set()).replace('"parse_attempt": 2', '"parse_attempt": 2, "parse_attempt": 2')
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=raw))
    with pytest.raises(SourcePagesError):
        reader(transport).pages("space-1", "k-1", 2)
