"""S11f acceptance (protected, written by Claude): the upload report says why a material is unread.

Spec docs/design/slices/S11f-未采集材料带类型原因.md §2.2, §3.4. RED until S11f: SourcePagesError has no
reason, RawSources has no listing() and the report has no unreadable_reasons / unfinished.
"""

import json
from pathlib import Path

import httpx
import pytest

from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.weknora_pages import SourcePagesError, WeKnoraSourcePages
from insurance_harness.ingest.raw_sources import RawSources, UnfinishedSource
from insurance_harness.ingest.registry import save_registry
from insurance_harness.ingest.uploads import UnreadableMaterial, attribute_uploads, main
from tests.ingest.upload_helpers import (
    RAW_KB,
    SPACE,
    Pages,
    entry,
    knowledge_id,
    material,
    raw,
    registry,
)

NOT_CAPTURED = "PARSE_ARTIFACT_NOT_CAPTURED"
SECRET = "raw parser diagnostic: page 3 of /data/files/private.pdf is scanned"


# 1. The error keeps only a typed reason --------------------------------------------------------


def test_a_not_captured_error_keeps_a_known_reason_and_a_strict_page() -> None:
    error = SourcePagesError(NOT_CAPTURED, "SCANNED_PAGE", 3)
    assert (error.code, error.reason, error.page) == (NOT_CAPTURED, "SCANNED_PAGE", 3)
    for reason in ("OFFICE_STRUCTURE_UNREADABLE", "UNSUPPORTED_FORMAT", "CAPTURE_NOT_RECORDED"):
        error = SourcePagesError(NOT_CAPTURED, reason, 3)
        assert (error.reason, error.page) == (reason, None), "only a scanned page has a page"
    for page in (True, 0, -1, "3", 3.0, 2**31, None):
        assert SourcePagesError(NOT_CAPTURED, "SCANNED_PAGE", page).page is None, page
    for reason in ("SOMETHING_ELSE", "", None, 7, "scanned_page"):
        assert SourcePagesError(NOT_CAPTURED, reason, 3).reason is None, reason
    other = SourcePagesError("PARSE_ARTIFACT_INTEGRITY", "SCANNED_PAGE", 3)
    assert (other.reason, other.page) == (None, None), "a reason belongs to NOT_CAPTURED only"
    assert str(SourcePagesError(NOT_CAPTURED, "SCANNED_PAGE", 3)) == NOT_CAPTURED
    assert SourcePagesError("SOURCE_UNAVAILABLE").reason is None


def test_the_page_reader_carries_the_platform_reason_and_nothing_else() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={
            "success": False, "code": NOT_CAPTURED, "error": SECRET,
            "reason": "SCANNED_PAGE", "page_number": 4,
        })

    reader = WeKnoraSourcePages("http://weknora.test", "key", transport=httpx.MockTransport(handler))
    with pytest.raises(SourcePagesError) as caught:
        reader.pages(SPACE, "k-1", 1)
    assert (caught.value.code, caught.value.reason, caught.value.page) == (NOT_CAPTURED, "SCANNED_PAGE", 4)
    assert SECRET not in repr(caught.value) and SECRET not in str(caught.value)


# 2. The listing also names unfinished materials ------------------------------------------------


def item(kid: str, status: str, **extra: object) -> dict[str, object]:
    return {"id": kid, "parse_status": status, "current_parse_attempt": 1, "file_name": kid + ".pdf",
            "file_sha256": "a" * 64, **extra}


def listing(items: list[dict[str, object]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/v1/knowledge-bases/{RAW_KB}/knowledge"
        page = int(request.url.params["page"])
        chunk = items[(page - 1) * 100 : page * 100]
        return httpx.Response(200, json={"success": True, "data": chunk, "total": len(items)})

    return httpx.MockTransport(handler)


def test_the_listing_maps_parse_states_without_reading_error_messages() -> None:
    items = [
        item("k-done", "completed"), item("k-failed", "failed", error_message=SECRET),
        item("k-cancelled", "cancelled"), item("k-pending", "pending"), item("k-running", "processing"),
        item("k-final", "finalizing"), item("k-deleting", "deleting"), item("k-odd", "archived"),
    ]
    sources = RawSources("http://weknora.test", "key", transport=listing(items))
    read = sources.listing(RAW_KB)
    assert [s.knowledge_id for s in read.completed] == ["k-done"]
    assert read.unfinished == [
        UnfinishedSource(knowledge_id="k-failed", file_name="k-failed.pdf", state="PARSE_FAILED"),
        UnfinishedSource(knowledge_id="k-cancelled", file_name="k-cancelled.pdf", state="PARSE_CANCELLED"),
        UnfinishedSource(knowledge_id="k-pending", file_name="k-pending.pdf", state="NOT_CAPTURED_YET"),
        UnfinishedSource(knowledge_id="k-running", file_name="k-running.pdf", state="NOT_CAPTURED_YET"),
        UnfinishedSource(knowledge_id="k-final", file_name="k-final.pdf", state="NOT_CAPTURED_YET"),
        UnfinishedSource(knowledge_id="k-odd", file_name="k-odd.pdf", state="PARSE_STATE_UNKNOWN"),
    ]
    assert SECRET not in json.dumps([u.model_dump() for u in read.unfinished])
    assert sources.completed(RAW_KB) == read.completed, "completed() is unchanged"


# 3. The report -----------------------------------------------------------------------------------


class ScannedPages(Pages):
    def __init__(self, scanned: str) -> None:
        super().__init__()
        self.scanned = scanned

    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]:
        if knowledge_id == self.scanned:
            raise SourcePagesError(NOT_CAPTURED, "SCANNED_PAGE", 2)
        return super().pages(space_id, knowledge_id, attempt)


def test_the_report_names_the_reason_and_keeps_the_old_list() -> None:
    scanned = knowledge_id("1814", "brochure")
    unfinished = [UnfinishedSource(knowledge_id="k-x", file_name="x.pdf", state="PARSE_FAILED")]
    run = attribute_uploads(
        registry(p1814=entry("1814", "terms"), p1828=entry("1828", "terms")),
        [raw("1814", "brochure"), raw("1828", "brochure")],
        ScannedPages(scanned),
        unfinished=unfinished,
    )
    assert run.report.unreadable == [scanned]
    assert run.report.unreadable_reasons == [UnreadableMaterial(
        knowledge_id=scanned, file_name=material("1814", "brochure")["file_name"],
        code=NOT_CAPTURED, reason="SCANNED_PAGE", page=2,
    )]
    assert run.report.unfinished == unfinished
    assert run.report.affected_products == ["1828"]

    failing = attribute_uploads(
        registry(p1814=entry("1814", "terms")), [raw("1814", "brochure")],
        Pages(failing=(knowledge_id("1814", "brochure"),)),
    )
    assert [(m.code, m.reason, m.page) for m in failing.report.unreadable_reasons] == [
        ("SOURCE_UNAVAILABLE", None, None)
    ]
    assert failing.report.unfinished == []


def test_the_command_prints_reasons_and_unfinished_without_platform_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HARNESS_WEKNORA_BASE_URL", "http://weknora.test")
    monkeypatch.setenv("HARNESS_WEKNORA_API_KEY", "key")
    path = tmp_path / "registry.json"
    save_registry(registry(p1828=entry("1828", "terms")), path)
    scanned = knowledge_id("1828", "brochure")
    m = material("1828", "brochure")
    items = [
        {"id": scanned, "parse_status": "completed", "current_parse_attempt": 1,
         "file_name": m["file_name"], "file_sha256": m["sha256"]},
        item("k-broken", "failed", error_message=SECRET),
    ]
    pages_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "/sources/" not in request.url.path:
            return listing(items).handle_request(request)
        pages_seen.append(request.url.path)
        return httpx.Response(409, json={
            "success": False, "code": NOT_CAPTURED, "error": SECRET,
            "reason": "SCANNED_PAGE", "page_number": 3,
        })

    assert main(["run", "--registry", str(path), "--dry-run"], transport=httpx.MockTransport(handler)) == 0
    out = capsys.readouterr().out
    report = json.loads(out)
    assert report["unreadable"] == [scanned]
    assert report["unreadable_reasons"] == [{
        "knowledge_id": scanned, "file_name": m["file_name"], "code": NOT_CAPTURED,
        "reason": "SCANNED_PAGE", "page": 3,
    }]
    assert report["unfinished"] == [
        {"knowledge_id": "k-broken", "file_name": "k-broken.pdf", "state": "PARSE_FAILED"}
    ]
    assert SECRET not in out
    assert len(pages_seen) == 1
