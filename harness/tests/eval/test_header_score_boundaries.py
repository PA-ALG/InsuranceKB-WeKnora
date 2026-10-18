"""Restricted headers cannot earn direct or word-for-word copy credit for another field."""

import pytest

from insurance_harness.compilers.schema_fields.engine import FieldResult
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.eval.segment_score import (
    GoldenV2,
    GoldenV2Evidence,
    GoldenV2Field,
    score_selection,
)
from insurance_harness.evidence.segments import SegmentedSource

TEXT = "被保险人投保年龄范围为出生满三十日至六十五周岁。"
SOURCE = SegmentedSource(
    [PageText("terms.pdf", "a" * 64, 1, TEXT)],
    table_headers={"rate_table": [PageText("rates.pdf", "b" * 64, 1, TEXT + "\n0 999\n")]},
)


def golden(field: str, sid: str) -> GoldenV2:
    segment = SOURCE.ordered([sid])[0]
    quote = GoldenV2Evidence(
        document=segment.document,
        document_sha256=segment.document_sha256,
        page=1,
        quote=segment.text,
        segment_id=sid,
    )
    return GoldenV2(
        product_id="p",
        cards_version="v",
        fields=(
            GoldenV2Field(
                field_key=field,
                state="present",
                value="取值",
                reason="证据",
                evidence=(quote,),
            ),
        ),
    )


def prediction(field: str, sid: str, recorded: bool) -> FieldResult:
    return FieldResult(
        field_key=field,
        state="present",
        value="取值",
        evidence=SOURCE.evidence([sid]),
        segment_ids=[sid] if recorded else [],
    )


@pytest.mark.parametrize("recorded", [False, True])
def test_an_untrusted_header_copy_is_unmapped_in_both_prediction_paths(recorded: bool) -> None:
    report = score_selection(
        SOURCE,
        golden("entry_age_range", "D1P1S1"),
        [prediction("entry_age_range", "D2P1S1", recorded)],
    )
    assert report.recall_mean == 0 and report.precision_mean is None
    assert report.copy_credits == (0, 0) and report.unmapped_predicted_quotes == 1


def test_untrusted_golden_header_is_unmapped_even_if_terms_repeat_it() -> None:
    report = score_selection(
        SOURCE, golden("entry_age_range", "D2P1S1"), [prediction("entry_age_range", "D1P1S1", True)]
    )
    assert report.unmapped_golden_quotes == 1 and report.recall_mean is None
    assert report.copy_credits == (0, 0)


@pytest.mark.parametrize("recorded", [False, True])
def test_a_trusted_header_retains_full_direct_and_copy_credit(recorded: bool) -> None:
    for gold in ("D1P1S1", "D2P1S1"):
        report = score_selection(
            SOURCE,
            golden("premium_payment_term", gold),
            [prediction("premium_payment_term", "D2P1S1", recorded)],
        )
        assert report.recall_mean == report.precision_mean == 1
        assert report.unmapped_golden_quotes == report.unmapped_predicted_quotes == 0
