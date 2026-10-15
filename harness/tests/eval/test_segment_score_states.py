"""State agreement compares the three states; only a missing prediction stands in for unknown."""

import json
from pathlib import Path

from insurance_harness.compilers.schema_fields.engine import FieldResult
from insurance_harness.eval.segment_score import load_golden_v2, score_selection
from insurance_harness.evidence.segments import SegmentedSource

SHA = "e" * 64


class Page:
    document, document_sha256, page, text = "条款.pdf", SHA, 1, "本合同不设宽限期。\n等待期为90日。"


SOURCE = SegmentedSource([Page()])


def golden(tmp_path: Path, state: str, ids: list[str]) -> Path:
    evidence = [
        {
            "document": "条款.pdf",
            "document_sha256": SHA,
            "page": 1,
            "quote": s.text,
            "segment_id": s.id,
        }
        for s in SOURCE.ordered(ids)
    ]
    field = {
        "field_key": "f",
        "state": state,
        "value": "x" if state == "present" else None,
        "reason": "r",
        "evidence": evidence,
    }
    path = tmp_path / "g.json"
    path.write_text(json.dumps({"product_id": "p", "cards_version": "t", "fields": [field]}))
    return path


def predicted(state: str, ids: list[str]) -> FieldResult:
    return FieldResult(
        field_key="f",
        state=state,  # type: ignore[arg-type]
        value="x" if state == "present" else None,
        evidence=SOURCE.evidence(ids),
    )


def test_present_against_absent_is_a_disagreement(tmp_path: Path) -> None:
    report = score_selection(
        SOURCE,
        load_golden_v2(golden(tmp_path, "present", ["D1P1S2"])),
        [predicted("absent_explicitly", ["D1P1S1"])],
    )
    assert report.state_agreement == (0, 1)


def test_absent_against_present_is_a_disagreement(tmp_path: Path) -> None:
    report = score_selection(
        SOURCE,
        load_golden_v2(golden(tmp_path, "absent_explicitly", ["D1P1S1"])),
        [predicted("present", ["D1P1S1"])],
    )
    assert report.state_agreement == (0, 1)


def test_identical_states_agree(tmp_path: Path) -> None:
    report = score_selection(
        SOURCE,
        load_golden_v2(golden(tmp_path, "absent_explicitly", ["D1P1S1"])),
        [predicted("absent_explicitly", ["D1P1S1"])],
    )
    assert report.state_agreement == (1, 1)
