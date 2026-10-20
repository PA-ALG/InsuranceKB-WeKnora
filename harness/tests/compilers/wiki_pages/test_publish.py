"""S6c implementation tests: native REST reader and the publish command (Spec §3.3)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from insurance_harness.compilers.wiki_pages import publish as cli
from insurance_harness.compilers.wiki_pages.native import NativeWikiError, NativeWikiReader
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.ingest.source_map import API_KEY_ENV, BASE_URL_ENV

SHA = "a" * 64
PAGES: list[dict[str, Any]] = [
    {"slug": "concept/deng-dai-qi", "title": "等待期", "page_type": "concept", "summary": None,
     "content": "见 [[concept/kuan-xian-qi]]，另见 [[summary/x|摘要页]]。", "aliases": None,
     "chunk_refs": ["c1"]},
    {"slug": "concept/kuan-xian-qi", "title": "宽限期", "page_type": "concept",
     "content": "宽限期。", "aliases": ["缓交期"], "chunk_refs": []},
    {"slug": "summary/x", "title": "摘要", "page_type": "summary", "content": "摘要。"},
]  # fmt: skip


def listing(pages: list[Any], number: int, changes: dict[str, Any] | None = None) -> dict[str, Any]:
    """The native list response, one page per request to exercise paging."""
    body = {"pages": pages[(number - 1) : number], "total": len(pages), "page": number,
            "page_size": 1, "total_pages": len(pages)}  # fmt: skip
    return {**body, **(changes or {})}


def transport(
    pages: list[Any], status: int = 200, changes: dict[str, Any] | None = None
) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "key"
        if status != 200:
            return httpx.Response(status, json={})
        if request.url.path.endswith("/wiki/pages"):
            page = int(request.url.params["page"])
            return httpx.Response(200, json=listing(pages, page, changes))
        if request.url.path == "/api/v1/chunks/by-id/c1":
            return httpx.Response(200, json={"data": {"content": "等待期为90日。被保险人"}})
        return httpx.Response(404, json={})

    return httpx.MockTransport(handle)


def test_reader_pages_through_every_page_and_reads_cited_chunks() -> None:
    reader = NativeWikiReader("http://wiki.test", "key", transport(PAGES))
    pages = reader.pages("kb-1")
    assert [page.slug for page in pages] == [
        "concept/deng-dai-qi",
        "concept/kuan-xian-qi",
        "summary/x",
    ]
    assert pages[0].chunks[0].content == "等待期为90日。被保险人"
    assert (pages[0].aliases, pages[0].summary) == ([], "")


@pytest.mark.parametrize("kb", ["", "../x", "a b"])
def test_reader_refuses_bad_identifiers(kb: str) -> None:
    with pytest.raises(NativeWikiError) as caught:
        NativeWikiReader("http://wiki.test", "key", transport(PAGES)).pages(kb)
    assert caught.value.code == "INVALID_REQUEST"


@pytest.mark.parametrize(
    ("pages", "changes"),
    [
        ([None], {}),
        (PAGES[:1], {"total": 2}),
        (PAGES, {"total_pages": 2}),
        (PAGES, {"page": 1}),
        (PAGES, {"page_size": 0}),
        (PAGES, {"total": True}),
        ([PAGES[0], PAGES[0]], {}),
    ],
    ids=["not a page", "short export", "page count", "page echo", "page size", "bool count",
         "duplicate slug"],
)  # fmt: skip
def test_reader_refuses_an_incomplete_or_inconsistent_export(
    pages: list[Any], changes: dict[str, Any]
) -> None:
    with pytest.raises(NativeWikiError) as caught:
        NativeWikiReader("http://wiki.test", "key", transport(pages, changes=changes)).pages("kb-1")
    assert caught.value.code == "NATIVE_WIKI_UNREADABLE"


def test_reader_refuses_an_export_that_changed_while_read() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        grown = PAGES + [{**PAGES[0], "slug": "concept/new"}] if page > 1 else PAGES
        return httpx.Response(200, json=listing(grown, page))

    with pytest.raises(NativeWikiError) as caught:
        NativeWikiReader("http://wiki.test", "key", httpx.MockTransport(handle)).pages("kb-1")
    assert caught.value.code == "NATIVE_WIKI_UNREADABLE"


def test_reader_failure_is_a_stable_code() -> None:
    with pytest.raises(NativeWikiError) as caught:
        NativeWikiReader("http://wiki.test", "key", transport(PAGES, 503)).pages("kb-1")
    assert caught.value.code == "NATIVE_WIKI_UNAVAILABLE"


class Page:
    def __init__(self, page: int, text: str) -> None:
        self.document, self.document_sha256, self.page, self.text = "条款.pdf", SHA, page, text


def run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    active: Any,
    native: Any = None,
) -> tuple[int, Any, Any]:
    seen: dict[str, Any] = {}
    monkeypatch.setenv(BASE_URL_ENV, "http://wiki.test")
    monkeypatch.setenv(API_KEY_ENV, "key")
    monkeypatch.setattr(
        cli,
        "load_source_map",
        lambda path: SimpleNamespace(space_id="s1", entries=lambda product: ["entry"]),
    )
    monkeypatch.setattr(cli, "reader_from_env", lambda: object())
    monkeypatch.setattr(
        cli,
        "load_trusted_pages",
        lambda reader, space, entries: (
            SimpleNamespace(evidence=[Page(1, "等待期为90日。\n其他。")]),
            {"条款.pdf": SourceRevision(knowledge_id="k1", parse_attempt=1)},
        ),
    )
    monkeypatch.setattr(
        cli,
        "NativeWikiReader",
        lambda base, key: SimpleNamespace(
            pages=native
            or (lambda kb: NativeWikiReader("http://wiki.test", "key", transport(PAGES)).pages(kb))
        ),
    )
    monkeypatch.setattr(
        cli, "PlatformClient", lambda base, key: SimpleNamespace(active=lambda space: active)
    )

    def fake_publish(client: Any, space: str, bundle: Any, *, decision: Any, activate: bool) -> Any:
        seen.update(space=space, bundle=bundle, decision=decision, activate=activate)
        release = SimpleNamespace(id="rel-2", epoch=2)
        return SimpleNamespace(
            candidate=SimpleNamespace(id="cand-1"), release=release if activate else None
        )

    monkeypatch.setattr(cli, "publish", fake_publish)
    code = cli.main([
        "--discovery-kb", "kb-1", "--product", "1828", "--entity-id", "1828",
        "--source-map", "map.json", "--model", "deepseek-v4-flash",
        "--decide", "human", "--reason", "S6c 试点", "--activate",
    ])  # fmt: skip
    return code, json.loads(capsys.readouterr().out), seen


def member(kind: str, entity: str, key: str) -> SimpleNamespace:
    payload = {"page_key": key, "entity_refs": [entity]}
    slug = f"wiki/{entity}/{key}" if kind == "wiki_page" else f"{entity}/{key}"
    return SimpleNamespace(kind=kind, logical_slug=slug, payload=payload)


def test_publish_builds_a_wiki_only_candidate_and_removes_stale_pages(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    active = SimpleNamespace(
        head=None,
        members=[
            member("wiki_page", "1828", "concept/old"),
            member("wiki_page", "1828", "concept/kuan-xian-qi"),
            member("wiki_page", "9999", "concept/old"),
            # Another entity whose id extends this one's: its pages share the slug prefix only.
            member("wiki_page", "1828/variant", "concept/old"),
            SimpleNamespace(kind="wiki_page", logical_slug="wiki/1828/concept/bare", payload=None),
            member("claim", "1828", "waiting_period"),
        ],
    )
    code, out, seen = run(monkeypatch, capsys, active)
    assert code == 0
    assert out == {"product": "1828", "pages": 2, "with_evidence": 1, "evidence": 1, "removed": 1,
                   "candidate_id": "cand-1", "release_id": "rel-2", "epoch": 2}  # fmt: skip
    bundle = seen["bundle"]
    assert [m.logical_slug for m in bundle.members] == [
        "wiki/1828/concept/deng-dai-qi",
        "wiki/1828/concept/kuan-xian-qi",
    ]
    assert {m.kind for m in bundle.members} == {"wiki_page"}
    assert bundle.removals == ["wiki/1828/concept/old"]
    assert (seen["decision"].mode, seen["decision"].reason, seen["activate"]) == (
        "human",
        "S6c 试点",
        True,
    )
    first = bundle.members[0].payload
    # The summary page is not exported, so a link to it keeps only its text.
    assert first["content"] == "见 [[wiki/1828/concept/kuan-xian-qi|宽限期]]，另见 摘要页。"
    assert first["evidence"][0]["quote"] == "等待期为90日。"


def test_publish_stops_with_a_code_on_bad_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--product", "../x"]) == 2
    assert json.loads(capsys.readouterr().out) == {"stopped": "INVALID_ARGUMENTS"}


@pytest.mark.parametrize(
    ("native", "code"),
    [
        (lambda kb: (_ for _ in ()).throw(NativeWikiError("NATIVE_WIKI_UNREADABLE")),
         "NATIVE_WIKI_UNREADABLE"),
        (lambda kb: NativeWikiReader("http://wiki.test", "key", transport(PAGES[2:])).pages(kb),
         "NATIVE_WIKI_EMPTY"),
    ],
    ids=["unreadable export", "no page to publish"],
)  # fmt: skip
def test_a_failed_or_empty_export_submits_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], native: Any, code: str
) -> None:
    active = SimpleNamespace(head=None, members=[member("wiki_page", "1828", "concept/old")])
    code_, out, seen = run(monkeypatch, capsys, active, native)
    assert (code_, out, seen) == (2, {"stopped": code}, {})
