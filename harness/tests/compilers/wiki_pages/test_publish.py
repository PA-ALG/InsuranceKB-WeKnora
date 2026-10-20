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
     "content": "见 [[concept/kuan-xian-qi]]。", "aliases": None, "chunk_refs": ["c1"]},
    {"slug": "concept/kuan-xian-qi", "title": "宽限期", "page_type": "concept",
     "content": "宽限期。", "aliases": ["缓交期"], "chunk_refs": []},
    {"slug": "summary/x", "title": "摘要", "page_type": "summary", "content": "摘要。"},
]  # fmt: skip


def transport(pages: list[dict[str, Any]], status: int = 200) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "key"
        if status != 200:
            return httpx.Response(status, json={})
        if request.url.path.endswith("/wiki/pages"):
            page = int(request.url.params["page"])
            batch = pages[(page - 1) : page]  # one page per request: exercise paging
            return httpx.Response(200, json={"pages": batch, "total_pages": len(pages)})
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


def test_reader_failure_is_a_stable_code() -> None:
    with pytest.raises(NativeWikiError) as caught:
        NativeWikiReader("http://wiki.test", "key", transport(PAGES, 503)).pages("kb-1")
    assert caught.value.code == "NATIVE_WIKI_UNAVAILABLE"


class Page:
    def __init__(self, page: int, text: str) -> None:
        self.document, self.document_sha256, self.page, self.text = "条款.pdf", SHA, page, text


def run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], active: Any
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
            pages=lambda kb: NativeWikiReader("http://wiki.test", "key", transport(PAGES)).pages(kb)
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


def member(kind: str, slug: str) -> SimpleNamespace:
    return SimpleNamespace(kind=kind, logical_slug=slug)


def test_publish_builds_a_wiki_only_candidate_and_removes_stale_pages(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    active = SimpleNamespace(
        head=None,
        members=[
            member("wiki_page", "wiki/1828/concept/old"),
            member("wiki_page", "wiki/1828/concept/kuan-xian-qi"),
            member("wiki_page", "wiki/9999/concept/old"),
            member("claim", "1828/waiting_period"),
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
    assert first["content"] == "见 [[wiki/1828/concept/kuan-xian-qi|宽限期]]。"
    assert first["evidence"][0]["quote"] == "等待期为90日。"


def test_publish_stops_with_a_code_on_bad_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--product", "../x"]) == 2
    assert json.loads(capsys.readouterr().out) == {"stopped": "INVALID_ARGUMENTS"}
