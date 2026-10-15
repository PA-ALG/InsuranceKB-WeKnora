"""S4d acceptance: selection scoring against Golden v2 (Spec §3.5).

Protected file: written by Claude. Golden v2 stores evidence as quotes, so it survives changes to
the segmentation rules; scoring maps every quote onto the current segments, ignoring whitespace.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pytest

from insurance_harness.compilers.schema_fields.engine import FieldResult
from insurance_harness.eval.segment_score import GoldenV2, load_golden_v2, score_selection
from insurance_harness.evidence.quote_verification import QuoteMatch, VerifiedQuote
from insurance_harness.evidence.segments import SegmentedSource

SHA = "d" * 64


class Page:
    def __init__(self, page: int, text: str) -> None:
        self.document, self.document_sha256, self.page, self.text = "保险条款.pdf", SHA, page, text


SOURCE = SegmentedSource(
    [
        Page(
            1,
            "1.4 等待期\n自本合同生效之日起90日内为等待期。\n"
            "因意外伤害发生保险事故的，无等待期。\n",
        ),
        Page(2, "1.5 保险期间\n本合同保险期间为一年。\n本合同不设宽限期。\n"),
    ]
)
# D1P1S1 等待期, D1P1S2 意外例外, D1P2S1 保险期间, D1P2S2 不设宽限期


def evidence(quote: str, page: int) -> dict[str, object]:
    return {
        "document": "保险条款.pdf",
        "document_sha256": SHA,
        "page": page,
        "quote": quote,
        "segment_id": None,
    }


GOLDEN = {
    "product_id": "1818",
    "cards_version": "test",
    "fields": [
        {
            "field_key": "waiting_period",
            "state": "present",
            "value": "90日；意外无等待期",
            "reason": "条款1.4",
            # whitespace differs from the page on purpose: the scorer must still map it
            "evidence": [
                evidence("1.4 等待期自本合同生效之日起90日内为等待期。", 1),
                evidence("因意外伤害发生保险事故的，无等待期。", 1),
            ],
        },
        {
            "field_key": "coverage_period",
            "state": "present",
            "value": "一年",
            "reason": "条款1.5",
            "evidence": [evidence("1.5 保险期间\n本合同保险期间为一年。", 2)],
        },
        {
            "field_key": "premium_grace_period",
            "state": "absent_explicitly",
            "value": None,
            "reason": "不设宽限期",
            "evidence": [evidence("本合同不设宽限期。", 2)],
        },
        {
            "field_key": "cooling_off_period",
            "state": "unknown",
            "value": None,
            "reason": "材料未提及",
            "evidence": [],
        },
    ],
}


State = Literal["present", "absent_explicitly", "unknown"]


def result(key: str, state: State, ids: list[str]) -> FieldResult:
    return FieldResult(
        field_key=key,
        state=state,
        value="x" if state == "present" else None,
        evidence=SOURCE.evidence(ids),
    )


@pytest.fixture()
def golden(tmp_path: Path) -> GoldenV2:
    path = tmp_path / "1818.json"
    path.write_text(json.dumps(GOLDEN, ensure_ascii=False), encoding="utf-8")
    return load_golden_v2(path)


def test_recall_precision_and_completeness_per_present_field(golden: GoldenV2) -> None:
    predicted = [
        result("waiting_period", "present", ["D1P1S1"]),  # recall 1/2, precision 1
        result("coverage_period", "present", ["D1P2S1", "D1P2S2"]),  # recall 1, precision 1/2
        result("premium_grace_period", "absent_explicitly", ["D1P2S2"]),
        result("cooling_off_period", "unknown", []),
    ]
    report = score_selection(SOURCE, golden, predicted)
    scores = {f.field_key: f for f in report.fields}
    assert (scores["waiting_period"].recall, scores["waiting_period"].precision) == (0.5, 1.0)
    assert (scores["coverage_period"].recall, scores["coverage_period"].precision) == (1.0, 0.5)
    assert report.recall_mean == pytest.approx(0.75) and report.precision_mean == pytest.approx(
        0.75
    )
    assert report.complete_at_08 == 1
    assert report.state_agreement == (4, 4)
    assert report.unmapped_golden_quotes == 0


def test_a_missing_or_non_present_prediction_scores_zero_recall(golden: GoldenV2) -> None:
    report = score_selection(SOURCE, golden, [result("coverage_period", "unknown", [])])
    scores = {f.field_key: f for f in report.fields}
    assert scores["waiting_period"].recall == 0.0 and scores["waiting_period"].precision is None
    assert scores["coverage_period"].recall == 0.0
    assert report.state_agreement == (1, 4), "only cooling_off_period (unknown vs missing) agrees"


def test_golden_quotes_that_no_longer_map_are_counted(tmp_path: Path) -> None:
    broken = json.loads(json.dumps(GOLDEN, ensure_ascii=False))
    broken["fields"][1]["evidence"] = [evidence("本合同保险期间为两年。", 2)]
    path = tmp_path / "1818.json"
    path.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
    report = score_selection(
        SOURCE, load_golden_v2(path), [result("coverage_period", "present", ["D1P2S1"])]
    )
    assert report.unmapped_golden_quotes == 1


@pytest.mark.parametrize(
    "change",
    [
        {"state": "present", "value": None},
        {"state": "unknown", "evidence": [evidence("本合同不设宽限期。", 2)]},
        {"state": "maybe"},
    ],
)
def test_malformed_golden_is_rejected(tmp_path: Path, change: dict[str, object]) -> None:
    bad = json.loads(json.dumps(GOLDEN, ensure_ascii=False))
    bad["fields"][2].update(change)
    path = tmp_path / "1818.json"
    path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        load_golden_v2(path)


def test_verified_quote_shape_is_unchanged() -> None:
    quote = SOURCE.evidence(["D1P2S2"])[0]
    assert isinstance(quote, VerifiedQuote) and quote.match is QuoteMatch.EXACT
