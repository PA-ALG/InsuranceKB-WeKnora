"""Positional header restoration: a short old label adopts the whole header, never rows."""

import hashlib
import json
from pathlib import Path

import pytest

from insurance_harness.eval import product_sources
from insurance_harness.eval.golden_remap import (
    PreviousSegment,
    PreviousSegmentation,
    RemapError,
    main,
    remap_golden,
)
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.eval.segment_score import GoldenV2, GoldenV2Evidence, GoldenV2Field
from insurance_harness.evidence.segments import SegmentedSource

RATE = PageText(
    "费率表.pdf", "b" * 64, 1, "\n  年交费率表。\n交费期间\n10年交 20年交\n0 100 90\n注释。\n"
)
TERMS = PageText("保险条款.pdf", "a" * 64, 1, "阅读指引。\n保障约定。")
TERM = "premium_payment_term"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def case(key: str, text: str) -> tuple[GoldenV2, PreviousSegmentation]:
    start = RATE.text.index(text)
    old = PreviousSegment(
        id="old",
        document=RATE.document,
        document_sha256=RATE.document_sha256,
        page=1,
        start=start,
        end=start + len(text),
        text=text,
    )
    evidence = GoldenV2Evidence(
        document=old.document,
        document_sha256=old.document_sha256,
        page=1,
        quote=text,
        segment_id=old.id,
    )
    field = GoldenV2Field(
        field_key=key, state="present", value="10年、20年", reason="原标注", evidence=(evidence,)
    )
    golden = GoldenV2(product_id="p", cards_version="old", fields=(field,))
    previous = PreviousSegmentation(
        pages={(RATE.document, 1): sha(RATE.text)}, segments={old.id: old}
    )
    return golden, previous


def test_even_a_short_header_overlap_maps_to_all_header_segments() -> None:
    golden, previous = case(TERM, "年交费率表。")
    source = SegmentedSource([TERMS], table_headers={"rate_table": [RATE]})
    result, report = remap_golden(
        golden,
        previous,
        [TERMS, RATE],
        excluded={RATE.document},
        emptied_reason="费率正文不采信",
        table_headers={"rate_table": [RATE]},
    )
    expected = [s for s in source.segments if s.document == RATE.document]
    assert len(expected) == 2
    assert [q.segment_id for q in result.fields[0].evidence] == [s.id for s in expected]
    assert result.fields[0].value == golden.fields[0].value
    assert report.restored == (TERM,)
    assert not any("100" in q.quote or "注释" in q.quote for q in result.fields[0].evidence)


@pytest.mark.parametrize(("key", "text"), [(TERM, "0 100 90"), ("entry_age_range", "年交费率表。")])
def test_body_only_and_untrusted_field_quotes_stay_excluded(key: str, text: str) -> None:
    golden, previous = case(key, text)
    result, report = remap_golden(
        golden,
        previous,
        [TERMS, RATE],
        excluded={RATE.document},
        emptied_reason="费率正文不采信",
        table_headers={"rate_table": [RATE]},
    )
    assert result.fields[0].state == "unknown" and not result.fields[0].evidence
    assert report.restored == () and report.excluded_quotes_removed == 1


def test_header_input_cannot_substitute_another_page_text_for_the_verified_snapshot() -> None:
    golden, previous = case(TERM, "年交费率表。")
    changed = PageText(
        RATE.document, RATE.document_sha256, RATE.page, RATE.text.replace("10年交", "99年交")
    )
    with pytest.raises(RemapError, match="PAGE_TEXT_CHANGED"):
        remap_golden(
            golden,
            previous,
            [TERMS, RATE],
            excluded={RATE.document},
            emptied_reason="不采信",
            table_headers={"rate_table": [changed]},
        )


def test_command_reads_original_labels_separately_and_preserves_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    directory = root / "dataset/shouxian_product/example"
    directory.mkdir(parents=True)
    (directory / "product_meta.json").write_text(json.dumps({"planCode": "p"}))
    for page in (TERMS, RATE):
        (directory / page.document).write_bytes(b"pdf")
    monkeypatch.setattr(
        product_sources, "read_pdf", lambda p: [TERMS if p.name == TERMS.document else RATE]
    )
    golden, previous = case(TERM, "年交费率表。")
    old = tmp_path / "old"
    old.mkdir()
    (old / "p.json").write_text(golden.model_dump_json())
    gold = root / "dataset/golden/v2"
    gold.mkdir(parents=True)
    unknown = golden.model_copy(
        update={
            "fields": (
                GoldenV2Field(
                    field_key=TERM,
                    state="unknown",
                    value=None,
                    reason="费率表不作证据",
                    evidence=(),
                ),
            )
        }
    )
    (gold / "p.json").write_text(unknown.model_dump_json())
    history = {"cards_version": "s4i", "products": {"p": {"to_unknown": [TERM]}}}
    manifest = {
        "products": {"p": {}},
        "files": {},
        "revisions": [history],
        "pending_semantic_review": {"p": ["entry_age_range", TERM]},
    }
    (gold / "manifest.json").write_text(json.dumps(manifest))
    exports = tmp_path / "previous"
    exports.mkdir()
    (exports / "p.json").write_text(
        json.dumps(
            {
                "baseline": "f" * 40,
                "pages": [{"document": RATE.document, "page": 1, "text_sha256": sha(RATE.text)}],
                "segments": [s.model_dump() for s in previous.segments.values()],
            }
        )
    )
    argv = [
        "--repo",
        str(root),
        "--golden-from",
        str(old),
        "--previous",
        str(exports),
        "--products",
        "p",
        "--cards-version",
        "new",
        "--basis",
        "表头恢复",
        "--emptied-reason",
        "费率表不作证据",
    ]
    assert main(argv) == 0
    after = json.loads((gold / "manifest.json").read_text())
    assert after["revisions"][0] == history
    assert after["revisions"][-1]["products"]["p"]["restored"] == [TERM]
    assert after["pending_semantic_review"] == {"p": ["entry_age_range"]}
    assert json.loads((gold / "p.json").read_text())["cards_version"] == "new"
    first = {p.name: p.read_bytes() for p in gold.iterdir()}
    assert main(argv) == 0
    assert {p.name: p.read_bytes() for p in gold.iterdir()} == first
