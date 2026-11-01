"""SK-2b Spec §3, §7 (RED, written by Claude): the discovery calls over the platform's REST API.

All requests go to a mock transport; nothing leaves the test process.
"""

import json
from collections.abc import Callable

import httpx
import pytest

from insurance_harness.compilers.methods.platform import MaterialPlatform, PlatformCallError
from insurance_harness.compilers.wiki_pages.native import NativeWikiReader

BASE = "https://platform.invalid"
Handler = Callable[[httpx.Request], httpx.Response]


def platform(handler: Handler, max_bytes: int = 1024) -> MaterialPlatform:
    return MaterialPlatform(
        BASE, "test-only", transport=httpx.MockTransport(handler), max_bytes=max_bytes
    )


def test_a_download_returns_the_file_bytes() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"file bytes")

    assert platform(handler).download("k-deck-a") == b"file bytes"
    (request,) = seen
    assert (request.method, request.url.path) == ("GET", "/api/v1/knowledge/k-deck-a/download")
    assert request.headers["X-API-Key"] == "test-only"


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(404), "SOURCE_UNAVAILABLE"),
        (httpx.Response(200, content=b"x" * 2048), "SOURCE_TOO_LARGE"),
        (httpx.Response(200, headers={"Content-Length": "4096"}, content=b"x"), "SOURCE_TOO_LARGE"),
    ],
)
def test_a_download_that_cannot_be_used_is_refused(response: httpx.Response, code: str) -> None:
    with pytest.raises(PlatformCallError) as raised:
        platform(lambda _: response).download("k-deck-a")
    assert raised.value.code == code


def test_an_upload_posts_the_file_and_returns_the_new_copy() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"success": True, "data": {"id": "copy-1"}})

    assert platform(handler).upload("kb-methods", "需求销售方法.pptx", b"bytes") == ("copy-1", True)
    (request,) = seen
    assert (request.method, request.url.path) == (
        "POST",
        "/api/v1/knowledge-bases/kb-methods/knowledge/file",
    )
    body = request.read()
    assert b"bytes" in body and "需求销售方法.pptx".encode() in body


def test_a_duplicate_upload_names_the_existing_copy() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = {"success": False, "code": "duplicate_file", "data": {"id": "copy-0"}}
        return httpx.Response(409, json=body)

    assert platform(handler).upload("kb-methods", "a.pptx", b"bytes") == ("copy-0", False)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, json={"success": True, "data": {}}),
        httpx.Response(200, content=b"not json"),
        httpx.Response(409, json={"success": False, "code": "other", "data": {"id": "copy-0"}}),
    ],
)
def test_an_upload_that_fails_is_refused(response: httpx.Response) -> None:
    with pytest.raises(PlatformCallError) as raised:
        platform(lambda _: response).upload("kb-methods", "a.pptx", b"bytes")
    assert raised.value.code == "UPLOAD_FAILED"


def test_a_delete_names_one_knowledge_item() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"success": True})

    platform(handler).delete("copy-1")
    assert [(r.method, r.url.path) for r in seen] == [("DELETE", "/api/v1/knowledge/copy-1")]
    with pytest.raises(PlatformCallError) as raised:
        platform(lambda _: httpx.Response(500)).delete("copy-1")
    assert raised.value.code == "DELETE_FAILED"


def test_the_listing_reads_the_discovery_base() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/knowledge-bases/kb-methods/knowledge"
        item = {
            "id": "copy-1",
            "parse_status": "completed",
            "current_parse_attempt": 1,
            "file_name": "a.pptx",
            "file_sha256": "a" * 64,
        }
        return httpx.Response(200, json={"success": True, "data": [item], "total": 1})

    listing = platform(handler).listing("kb-methods")
    assert [(s.knowledge_id, s.sha256) for s in listing.completed] == [("copy-1", "a" * 64)]
    with pytest.raises(PlatformCallError) as raised:
        platform(lambda _: httpx.Response(503)).listing("kb-methods")
    assert raised.value.code == "RAW_LISTING_UNAVAILABLE"


@pytest.mark.parametrize("bad", ["../k", "k/1", ""])
def test_identifiers_are_checked_before_any_request(bad: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may be sent")

    client = platform(handler)
    for call in (
        lambda: client.download(bad),
        lambda: client.delete(bad),
        lambda: client.upload(bad, "a.pptx", b"x"),
    ):
        with pytest.raises(PlatformCallError) as raised:
            call()
        assert raised.value.code == "INVALID_REQUEST"


def test_native_pages_name_the_knowledge_item_of_each_cited_chunk() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/wiki/pages"):
            row = {"slug": "entity/a", "title": "方法", "page_type": "entity",
                   "content": "正文", "chunk_refs": ["chunk-1", "chunk-2"]}
            body = {"pages": [row], "total": 1, "page": 1, "page_size": 100, "total_pages": 1}
            return httpx.Response(200, json=body)
        data = {"content": "块", "knowledge_id": "copy-1"}
        if request.url.path.endswith("chunk-2"):
            data = {"content": "块"}  # an older platform without the field
        return httpx.Response(200, content=json.dumps({"data": data}).encode())

    reader = NativeWikiReader(BASE, "test-only", transport=httpx.MockTransport(handler))
    (native,) = reader.pages("kb-methods")
    assert [c.knowledge_id for c in native.chunks] == ["copy-1", ""]
