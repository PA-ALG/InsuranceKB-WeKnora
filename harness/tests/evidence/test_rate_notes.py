"""S12c-12b RED: page-bounded rate notes; private products never enter these fixtures."""

import pytest

from insurance_harness.catalog.trust_policy import load_trust_policy
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.segments import SegmentedSource, header_block

HEADER = "合成保险费率表\n交费期间10年\n"
ROWS = "0 999\n1 888\n"
NOTE = "注：本产品交费方式为年交。"


def source(tail: str, role: str = "rate_table", *, prefix: str = HEADER + ROWS) -> SegmentedSource:
    return SegmentedSource(
        [], table_headers={role: [PageText("synthetic.pdf", "a" * 64, 1, prefix + tail)]}
    )


def test_header_and_notes_are_separate_policy_grants() -> None:
    policy = load_trust_policy()
    assert policy.version == "2026-11-05.1"
    assert policy.header_fields("rate_table") == frozenset({"premium_payment_term"})
    assert policy.note_fields("rate_table") == frozenset(
        {"premium_payment_term", "premium_payment_frequency"}
    )
    assert policy.note_fields("terms") == frozenset()


@pytest.mark.parametrize(
    "note",
    [
        NOTE,
        "说明：本产品交费方式为年交，\n每份保险费为100元。",
        "注释：本产品交费方式为年交。\n  适用于所有计划。",
        "注：\n1、交费方式为年交。\n2、每份保险费为100元。",
        "注1：交费方式为年交。\r\n  适用于所有计划。",
    ],
)
def test_contiguous_marked_notes_keep_exact_page_slices(note: str) -> None:
    src = source(note)
    notes = [s for s in src.segments if s.start >= len(HEADER + ROWS)]
    assert notes and "年交" in "".join(s.text for s in notes)
    for s in notes:
        assert src.pages[0].text[s.start : s.end] == s.text
        assert src.permits("premium_payment_frequency", s.id)
        assert src.permits("premium_payment_term", s.id)
        assert not src.permits("entry_age_range", s.id)
    assert not any("999" in s.text or "888" in s.text for s in src.segments)


@pytest.mark.parametrize(
    "tail,prefix",
    [
        ("本产品交费方式为年交。", HEADER + ROWS),
        ("注释。", HEADER + ROWS),
        ("\n" + NOTE, HEADER + ROWS),
        ("其他正文。\n" + NOTE, HEADER + ROWS),
        (NOTE, HEADER),
    ],
)
def test_a_marker_without_immediate_numeric_table_context_is_not_a_note(
    tail: str, prefix: str
) -> None:
    src = source(tail, prefix=prefix)
    assert not any(s.start >= len(prefix) for s in src.segments)


@pytest.mark.parametrize(
    "following",
    [
        "\n\n另一段正文。",
        "\n另一产品保险条款\n新增内容。",
        "\n第二章 其他内容\n新增内容。",
        "\n2 777\n注：这是第二张表的注释。",
        "\n这是一段没有注释标记的正文。",
    ],
)
def test_notes_stop_before_other_content(following: str) -> None:
    src = source(NOTE + following)
    after = len(HEADER + ROWS + NOTE)
    notes = [s for s in src.segments if s.start >= len(HEADER + ROWS)]
    assert notes and all(s.end <= after for s in notes)


def test_page_boundary_cannot_supply_the_missing_table_context() -> None:
    src = SegmentedSource(
        [],
        table_headers={
            "rate_table": [
                PageText("synthetic.pdf", "a" * 64, 1, HEADER + ROWS),
                PageText("synthetic.pdf", "a" * 64, 2, NOTE),
            ]
        },
    )
    assert all(s.page == 1 for s in src.segments)


def test_other_restricted_role_does_not_gain_note_permission() -> None:
    src = source(NOTE, role="unconfigured")
    assert not any(s.start >= len(HEADER + ROWS) for s in src.segments)


def test_adjacent_ids_must_not_join_across_the_discarded_numeric_rows() -> None:
    src = source(NOTE)
    assert len(src.segments) == 2
    spans = src.spans([s.id for s in src.segments])
    assert len(spans) == 2
    assert not any("999" in s.quote or "888" in s.quote for s in spans)
    assert header_block(src.pages[0].text) == (0, len(HEADER.rstrip()))
    assert not src.locate("synthetic.pdf", 1, "1 888\n" + NOTE)
    assert not src.locate("synthetic.pdf", 1, src.pages[0].text)


def test_frequency_still_cannot_use_the_header() -> None:
    src = source(NOTE)
    header = src.segments[0]
    assert src.permits("premium_payment_term", header.id)
    assert not src.permits("premium_payment_frequency", header.id)
