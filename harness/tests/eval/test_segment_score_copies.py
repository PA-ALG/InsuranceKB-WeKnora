"""S4e acceptance: Golden segment ids and word-for-word copies in selection scoring (Spec §3.2).

Protected file: written by Claude. Golden evidence is taken by its recorded segment id when that
segment still holds the quoted text; otherwise the quote is located as before. A selected segment
and a Golden segment that are copies of each other (``SegmentedSource.copies``) credit each other.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from insurance_harness.compilers.schema_fields.engine import FieldResult
from insurance_harness.eval.segment_score import (
    GoldenV2,
    SelectionReport,
    load_golden_v2,
    score_selection,
)
from insurance_harness.evidence.segments import SegmentedSource


class Page:
    def __init__(self, document: str, sha: str, text: str) -> None:
        self.document, self.document_sha256, self.page, self.text = document, sha, 1, text


SOURCE = SegmentedSource(
    [
        Page(
            "产品说明书.pdf",
            "a" * 64,
            "身故保险金\n"
            "被保险人身故的，我们按基本保险金额给付身故保险金，本合同终止。\n"
            "若被保险人在本合同生效前已发生某特定疾病，我们不承担保险责任。\n"
            "若被保险人以乘客身份乘坐私家车期间遭受意外伤害，我们给付私家车意外伤残保险金。\n"
            "本合同终止。\n"
            "若被保险人在本合同生效前已发生某特定疾病，我们不承担保险责任。\n",
        ),
        Page(
            "保险条款.pdf",
            "b" * 64,
            "1.2.1 身故保险金 被保险人身故的，我们按基本保险金额给付身故保险金，本合同终止。\n"
            "2.4 疾病限制 本合同生效前已发生的疾病：若被保险人在本合同生效前已发生某特定疾病，"
            "我们不承担保险责任。\n"
            "若被保险人以乘客身份乘坐私家车期间遭受意外伤害，我们给付私家车意外身故保险金。\n"
            "本合同终止。\n",
        ),
    ]
)
SEGMENTS = {s.id: s for s in SOURCE.segments}
State = Literal["present", "absent_explicitly", "unknown"]


def cite(segment_id: str, quote_of: str | None = None) -> dict[str, object]:
    """Golden evidence recorded against segment_id, quoting quote_of's text (default: its own)."""
    segment, quoted = SEGMENTS[segment_id], SEGMENTS[quote_of or segment_id]
    return {
        "document": quoted.document,
        "document_sha256": quoted.document_sha256,
        "page": quoted.page,
        "quote": quoted.text,
        "segment_id": segment.id,
    }


def golden(tmp_path: Path, fields: dict[str, list[dict[str, object]]]) -> GoldenV2:
    path = tmp_path / "1818.json"
    path.write_text(
        json.dumps(
            {
                "product_id": "1818",
                "cards_version": "test",
                "fields": [
                    {"field_key": k, "state": "present", "value": "x", "reason": "r", "evidence": v}
                    for k, v in fields.items()
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return load_golden_v2(path)


def selected(key: str, ids: list[str], state: State = "present") -> FieldResult:
    return FieldResult(
        field_key=key,
        state=state,
        value="x" if state == "present" else None,
        evidence=SOURCE.evidence(ids),
    )


def scores(report: SelectionReport) -> dict[str, tuple[float | None, float | None]]:
    return {f.field_key: (f.recall, f.precision) for f in report.fields}


def test_selecting_the_other_documents_copy_scores_as_the_golden_segment(tmp_path: Path) -> None:
    report = score_selection(
        SOURCE,
        golden(tmp_path, {"death_benefit_rules": [cite("D2P1S1")]}),
        [selected("death_benefit_rules", ["D1P1S1"])],
    )
    assert scores(report) == {"death_benefit_rules": (1.0, 1.0)}
    assert report.copy_credits == (1, 1)


def test_golden_listing_both_copies_needs_only_one_of_them(tmp_path: Path) -> None:
    report = score_selection(
        SOURCE,
        golden(tmp_path, {"exclusions": [cite("D1P1S2"), cite("D2P1S2")]}),
        [selected("exclusions", ["D2P1S2"])],
    )
    assert scores(report) == {"exclusions": (1.0, 1.0)}
    assert report.copy_credits == (1, 0)


def test_a_one_word_different_provision_earns_nothing(tmp_path: Path) -> None:
    report = score_selection(
        SOURCE,
        golden(tmp_path, {"additional_benefit_rules": [cite("D1P1S3")]}),
        [selected("additional_benefit_rules", ["D2P1S3"])],
    )
    assert scores(report) == {"additional_benefit_rules": (0.0, 0.0)}
    assert report.copy_credits == (0, 0)


def test_a_repeated_quote_is_scored_by_its_recorded_segment_id(tmp_path: Path) -> None:
    # D1P1S5 repeats D1P1S2 on the same page: locating the quote alone is ambiguous.
    report = score_selection(
        SOURCE,
        golden(tmp_path, {"exclusions": [cite("D1P1S5")]}),
        [selected("exclusions", ["D2P1S2"])],
    )
    assert report.unmapped_golden_quotes == 0
    assert scores(report) == {"exclusions": (1.0, 1.0)}


def test_a_stale_segment_id_falls_back_to_locating_the_quote(tmp_path: Path) -> None:
    # The id now names another segment, so the quote (D1P1S1's text) decides.
    report = score_selection(
        SOURCE,
        golden(tmp_path, {"death_benefit_rules": [cite("D1P1S3", quote_of="D1P1S1")]}),
        [selected("death_benefit_rules", ["D1P1S1"])],
    )
    assert report.unmapped_golden_quotes == 0
    assert scores(report) == {"death_benefit_rules": (1.0, 1.0)}
    assert report.copy_credits == (0, 0)


def test_an_ambiguous_predicted_quote_is_counted_not_guessed(tmp_path: Path) -> None:
    report = score_selection(
        SOURCE,
        golden(tmp_path, {"exclusions": [cite("D1P1S2")]}),
        [selected("exclusions", ["D1P1S5"])],
    )
    assert report.unmapped_predicted_quotes == 1
    assert scores(report) == {"exclusions": (0.0, None)}
