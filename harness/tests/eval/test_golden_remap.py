"""S4i acceptance: Golden evidence follows a segmentation change by page position (Spec §3.4).

Protected file: written by Claude after review R5 on #200, extended after review R1/R2 on #203. A
Golden quote is taken by the segment it was labelled on under the previous rules; the current
segments that overlap that range by a positive length replace it. Every quote, including those on
excluded materials, is first checked against the current snapshot of the product's pages: file
fingerprint, page text and the old range's exact slice. Evidence on non-evidence materials is
removed, a field left without evidence becomes unknown, any mismatch stops the remap before anything
is written, and a failed write leaves the previous files in place.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

import pytest

from insurance_harness.eval import product_sources
from insurance_harness.eval.golden_remap import (
    PreviousSegment,
    PreviousSegmentation,
    ProductRemap,
    RemapError,
    main,
    remap_golden,
)
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.eval.segment_score import GoldenV2, GoldenV2Evidence, GoldenV2Field
from insurance_harness.evidence.segments import SegmentedSource

TERMS, RATES = "保险条款.pdf", "费率表.pdf"
SHA_T, SHA_R = "a" * 64, "b" * 64
TEXT = "阅读指引。 第一句。 第二句。\n第三句在这里\n继续。\n"
RATE_TEXT = "年交费率表\n0 岁 408 元\n"
REASON = "仅费率表列示，费率表不作证据（测试）"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def span(text: str, part: str) -> tuple[int, int]:
    start = text.index(part)
    return start, start + len(part)


def old(sid: str, start: int, end: int, document: str = TERMS) -> PreviousSegment:
    text, sha = (TEXT, SHA_T) if document == TERMS else (RATE_TEXT, SHA_R)
    return PreviousSegment(
        id=sid,
        document=document,
        document_sha256=sha,
        page=1,
        start=start,
        end=end,
        text=text[start:end],
    )


FIRST_TWO = span(TEXT, "第一句。 第二句。")
PREVIOUS = PreviousSegmentation(
    pages={(TERMS, 1): digest(TEXT), (RATES, 1): digest(RATE_TEXT)},
    segments={
        s.id: s
        for s in [
            old("O1", *FIRST_TWO),  # the old rules kept the inline break in one segment
            old("O2", span(TEXT, "第一句")[0], span(TEXT, "第一句")[1]),  # an old mid-sentence cut
            old("O3", span(TEXT, "第一句。")[0], span(TEXT, "第一句。")[1] + 1),  # ends on the gap
            old("O4", *span(TEXT, "第三句在这里\n继续。")),
            old("R1", *span(RATE_TEXT, "年交费率表"), document=RATES),
        ]
    },
)
MATERIALS = [PageText(TERMS, SHA_T, 1, TEXT), PageText(RATES, SHA_R, 1, RATE_TEXT)]
CURRENT = SegmentedSource(MATERIALS[:1])  # what the snapshot leaves once rate tables are out


def quote(sid: str) -> GoldenV2Evidence:
    segment = PREVIOUS.segments[sid]
    return GoldenV2Evidence(
        document=segment.document,
        document_sha256=segment.document_sha256,
        page=1,
        quote=segment.text,
        segment_id=sid,
    )


State = Literal["present", "absent_explicitly", "unknown"]


def field(key: str, *sids: str, state: State = "present") -> GoldenV2Field:
    return GoldenV2Field(
        field_key=key,
        state=state,
        value="取值" if state == "present" else None,
        reason="原理由",
        evidence=tuple(quote(sid) for sid in sids),
    )


def golden(*fields: GoldenV2Field) -> GoldenV2:
    return GoldenV2(product_id="p1", cards_version="cards-x", fields=fields)


def ids(result: GoldenV2, key: str) -> list[str | None]:
    found = next(f for f in result.fields if f.field_key == key)
    return [q.segment_id for q in found.evidence]


def remap(*fields: GoldenV2Field) -> tuple[GoldenV2, ProductRemap]:
    return remap_golden(
        golden(*fields), PREVIOUS, MATERIALS, excluded={RATES}, emptied_reason=REASON
    )


def test_an_old_segment_maps_to_every_current_segment_it_overlaps_in_reading_order() -> None:
    result, report = remap(field("a", "O4", "O1"))
    assert [s.text for s in CURRENT.segments] == [
        "阅读指引。",
        "第一句。",
        "第二句。",
        "第三句在这里\n继续。",
    ]
    assert ids(result, "a") == ["D1P1S2", "D1P1S3", "D1P1S4"]
    assert [q.quote for q in result.fields[0].evidence][:2] == ["第一句。", "第二句。"]
    assert report.quotes_split == 1


def test_touching_ends_do_not_overlap_and_duplicates_collapse() -> None:
    result, _ = remap(field("b", "O3", "O1"))
    assert ids(result, "b") == ["D1P1S2", "D1P1S3"]


def test_a_current_segment_reaching_past_the_old_range_is_recorded_as_widened() -> None:
    result, report = remap(field("c", "O2"))
    assert ids(result, "c") == ["D1P1S2"]
    assert report.quotes_widened == (("c", "D1P1S2"),)


def test_evidence_on_excluded_materials_is_removed_and_an_emptied_field_becomes_unknown() -> None:
    result, report = remap(field("d", "R1"), field("e", "R1", "O4"), field("f", state="unknown"))
    d, e, f = result.fields
    assert (d.state, d.value, d.evidence, d.reason) == ("unknown", None, (), REASON)
    assert e.state == "present" and ids(result, "e") == ["D1P1S4"]
    assert f.state == "unknown" and f.reason == "原理由"
    assert report.excluded_quotes_removed == 2
    assert report.to_unknown == ("d",)
    assert report.cited_excluded == ("d", "e")
    assert report.fields == ("d", "e")


def test_a_field_keeps_everything_but_its_new_segment_ids() -> None:
    result, report = remap(field("g", "O4"))
    assert result.fields[0] == field("g", "O4").model_copy(
        update={"evidence": (quote("O4").model_copy(update={"segment_id": "D1P1S4"}),)}
    )
    assert report.fields == ("g",)  # a new id is a change


def moved(sid: str, start: int, end: int) -> PreviousSegmentation:
    """The same id and text, at another range of the page."""
    segment = PREVIOUS.segments[sid].model_copy(update={"start": start, "end": end})
    return PreviousSegmentation(pages=PREVIOUS.pages, segments={**PREVIOUS.segments, sid: segment})


def refingerprinted(document: str) -> list[PageText]:
    """The same page text under another file fingerprint."""
    return [
        PageText(p.document, "c" * 64, p.page, p.text) if p.document == document else p
        for p in MATERIALS
    ]


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("page", "PAGE_TEXT_CHANGED"),
        ("id", "SEGMENT_ID_UNKNOWN"),
        ("quote", "QUOTE_MISMATCH"),
        ("moved", "SEGMENT_RANGE_INVALID"),
        ("past_end", "SEGMENT_RANGE_INVALID"),
        ("file", "SOURCE_FINGERPRINT_CHANGED"),
        ("excluded_file", "SOURCE_FINGERPRINT_CHANGED"),
        ("excluded_moved", "SEGMENT_RANGE_INVALID"),
    ],
)
def test_any_mismatch_stops_the_remap(change: str, code: str) -> None:
    previous, materials, item = PREVIOUS, MATERIALS, field("h", "O4")
    if change == "page":
        previous = PreviousSegmentation(
            pages={**PREVIOUS.pages, (TERMS, 1): "0" * 64}, segments=PREVIOUS.segments
        )
    if change == "id":
        item = item.model_copy(
            update={"evidence": (item.evidence[0].model_copy(update={"segment_id": "O9"}),)}
        )
    if change == "quote":
        item = item.model_copy(
            update={"evidence": (item.evidence[0].model_copy(update={"quote": "别的文字"}),)}
        )
    if change == "moved":  # coordinates point at other text while the recorded text is unchanged
        previous = moved("O4", *span(TEXT, "第一句。"))
    if change == "past_end":
        previous = moved("O4", span(TEXT, "第三句在这里")[0], len(TEXT) + 5)
    if change == "file":  # same page text, another file
        materials = refingerprinted(TERMS)
    if change == "excluded_file":  # evidence on a rate table is checked before it is removed
        item, materials = field("h", "R1"), refingerprinted(RATES)
    if change == "excluded_moved":
        item, previous = field("h", "R1"), moved("R1", 0, 2)
    with pytest.raises(RemapError) as stopped:
        remap_golden(golden(item), previous, materials, excluded={RATES}, emptied_reason=REASON)
    assert stopped.value.code == code


# The command: every product converts before anything is written.
@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    folder = root / "dataset/shouxian_product/产品一"
    folder.mkdir(parents=True)
    (folder / "product_meta.json").write_text(
        json.dumps({"planCode": "p1", "clauseName": "产品一"}), encoding="utf-8"
    )
    (folder / TERMS).write_bytes(b"terms")
    (folder / RATES).write_bytes(b"rates")
    texts = {TERMS: (SHA_T, TEXT), RATES: (SHA_R, RATE_TEXT)}

    def read_pdf(path: Path) -> list[PageText]:
        sha, text = texts[path.name]
        return [PageText(path.name, sha, 1, text)]

    monkeypatch.setattr(product_sources, "read_pdf", read_pdf)
    item = golden(field("a", "O1"), field("d", "R1"))
    gold = root / "dataset/golden/v2"
    gold.mkdir(parents=True)
    raw = item.model_dump_json(indent=2) + "\n"
    (gold / "p1.json").write_text(raw, encoding="utf-8")
    manifest = {
        "products": {"p1": {"fields": 2, "states": {"present": 2}, "pack_id": "pack"}},
        "files": {"p1.json": digest(raw)},
        "revisions": [],
    }
    (gold / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    export = {
        "baseline": "f" * 40,
        "pages": [
            {"document": d, "page": p, "text_sha256": sha} for (d, p), sha in PREVIOUS.pages.items()
        ],
        "segments": [s.__dict__ for s in PREVIOUS.segments.values()],
    }
    (tmp_path / "previous").mkdir()
    (tmp_path / "previous" / "p1.json").write_text(json.dumps(export), encoding="utf-8")
    return root


def run(repo: Path, *extra: str) -> int:
    return main(
        [
            "--repo", str(repo),
            "--previous", str(repo.parent / "previous"),
            "--products", "p1",
            "--cards-version", "cards-new",
            "--basis", "测试重映射",
            "--emptied-reason", REASON,
            *extra,
        ]
    )  # fmt: skip


def snapshot(repo: Path) -> dict[str, bytes]:
    gold = repo / "dataset/golden/v2"
    return {path.name: path.read_bytes() for path in sorted(gold.iterdir())}


def test_the_command_rewrites_golden_and_records_the_remap(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(repo) == 0
    gold = repo / "dataset/golden/v2"
    manifest = json.loads((gold / "manifest.json").read_text(encoding="utf-8"))
    raw = (gold / "p1.json").read_bytes()
    assert manifest["files"]["p1.json"] == hashlib.sha256(raw).hexdigest()
    assert manifest["products"]["p1"]["states"] == {"present": 1, "unknown": 1}
    assert manifest["pending_semantic_review"] == {"p1": ["d"]}
    revision = manifest["revisions"][-1]
    assert revision["method"] == "deterministic-remap" and revision["baseline"] == "f" * 40
    assert revision["cards_version"] == "cards-new"
    entry = revision["products"]["p1"]
    assert entry["fields"] == ["a", "d"] and entry["to_unknown"] == ["d"]
    assert entry["rate_table_quotes_removed"] == 1 and entry["quotes_split"] == 1
    assert json.loads(capsys.readouterr().out.strip())["products"] == {"p1": 2}


def test_a_stop_writes_nothing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    export = repo.parent / "previous" / "p1.json"
    data = json.loads(export.read_text(encoding="utf-8"))
    data["pages"][0]["text_sha256"] = "0" * 64
    export.write_text(json.dumps(data), encoding="utf-8")
    before = snapshot(repo)
    assert run(repo) == 2
    assert json.loads(capsys.readouterr().out.strip()) == {
        "stopped": "PAGE_TEXT_CHANGED",
        "product": "p1",
    }
    assert snapshot(repo) == before


def test_a_manifest_without_the_product_stops_before_writing(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = repo / "dataset/golden/v2/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    del manifest["products"]["p1"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    before = snapshot(repo)
    assert run(repo) == 2
    assert json.loads(capsys.readouterr().out.strip())["stopped"] == "MANIFEST_INVALID"
    assert snapshot(repo) == before


@pytest.mark.parametrize("failing", ["p1.json", "manifest.json"])  # the middle and the last write
def test_a_failed_write_restores_every_file_and_leaves_no_temporary_file(
    repo: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    failing: str,
) -> None:
    replace = os.replace

    def flaky(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if Path(str(target)).name == failing:
            raise OSError("disk full")
        replace(source, target)

    monkeypatch.setattr(os, "replace", flaky)  # the command replaces files through os.replace
    before = snapshot(repo)
    assert run(repo) == 2
    assert json.loads(capsys.readouterr().out.strip()) == {"stopped": "OUTPUT_FAILED"}
    assert snapshot(repo) == before
