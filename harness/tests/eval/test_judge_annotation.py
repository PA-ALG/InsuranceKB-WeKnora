"""S2b acceptance (blueprint 1001 §7.7). Protected file: written by Claude.

Contract for building Golden with an offline judge model: blind prompts, budget
caps, fail-closed parsing, deterministic evidence verification against page
text, and calibration against an existing human-approved Golden.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import pytest

from insurance_harness.eval.catalog import load_catalog
from insurance_harness.eval.golden import GoldenEvidence, GoldenItem
from insurance_harness.eval.judge import (
    JudgeAnnotator,
    JudgeBudgetExceeded,
    JudgeProtocolError,
    JudgeRequest,
    calibrate,
)
from insurance_harness.eval.pdf_text import PageText

REPO = Path(__file__).resolve().parents[3]
CATALOG = REPO / "internal/handler/schema_pack_catalog_830_g3.generated.json"
PACK = "schemapack_medical_insurance"
SHA = "b" * 64
PAGES = [
    PageText(
        document="保险条款.pdf",
        document_sha256=SHA,
        page=3,
        text="等待期为90日，意外伤害无等待期。",
    ),
    PageText(document="保险条款.pdf", document_sha256=SHA, page=5, text="本合同为不保证续保合同。"),
]


class FakeJudge:
    """Returns canned JSON per call and records every request it receives."""

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self.requests: list[JudgeRequest] = []

    def complete(self, request: JudgeRequest) -> str:
        self.requests.append(request)
        return self._responses.pop(0)

    @property
    def model_id(self) -> str:
        return "fake-judge-1"


def answer(*fields: dict[str, object]) -> str:
    return json.dumps({"fields": list(fields)}, ensure_ascii=False)


def annotator(judge: FakeJudge, max_calls: int = 5, batch_size: int = 10) -> JudgeAnnotator:
    return JudgeAnnotator(judge, load_catalog(CATALOG), max_calls=max_calls, batch_size=batch_size)


WAITING: dict[str, object] = {
    "field_key": "waiting_period",
    "state": "present",
    "value": "90日，意外伤害无等待期",
    "components": [
        {"name": "时长", "accepted": ["90日"]},
        {"name": "意外例外", "accepted": ["意外伤害"]},
    ],
    "evidence": [{"document": "保险条款.pdf", "page": 3, "quote": "等待期为90日"}],
}


# ---- Blind prompt -------------------------------------------------------------------------


def test_prompt_carries_field_definitions_and_pages_but_no_candidate_values() -> None:
    judge = FakeJudge([answer(WAITING)])
    annotator(judge).annotate("596", PACK, ["waiting_period"], PAGES)
    request = judge.requests[0]
    assert "waiting_period" in request.user
    assert "等待期为90日" in request.user  # page text is provided
    assert "[page 3]" in request.user or "page=3" in request.user  # page markers are explicit
    for forbidden in ("prediction", "candidate", "epoch"):
        assert forbidden not in request.user.lower()


def test_catalog_exposes_source_extractable_fields_and_definitions() -> None:
    catalog = load_catalog(CATALOG)
    fields = catalog.source_extractable_fields(PACK)
    assert "waiting_period" in fields
    assert "product_type" not in fields  # 外部映射: not derivable from documents
    definition = catalog.field_definition(PACK, "waiting_period")
    assert definition.short_title == "等待期"
    assert definition.description


# ---- Evidence verification and three-state rules -----------------------------------------


def test_verified_present_becomes_model_judged_golden_item() -> None:
    result = annotator(FakeJudge([answer(WAITING)])).annotate(
        "596", PACK, ["waiting_period"], PAGES
    )
    assert [i.field_key for i in result.items] == ["waiting_period"]
    item = result.items[0]
    assert item.state == "present"
    assert item.judged_by == "model:fake-judge-1"
    assert item.evidence == [
        GoldenEvidence(document="保险条款.pdf", document_sha256=SHA, page=3, quote="等待期为90日")
    ]
    assert [c.name for c in item.components] == ["时长", "意外例外"]


def test_quote_not_on_stated_page_is_rejected_not_kept() -> None:
    wrong_page = dict(
        WAITING, evidence=[{"document": "保险条款.pdf", "page": 5, "quote": "等待期为90日"}]
    )
    result = annotator(FakeJudge([answer(wrong_page)])).annotate(
        "596", PACK, ["waiting_period"], PAGES
    )
    assert result.items == []
    assert result.rejected == {"waiting_period": "evidence_not_verified"}


def test_absent_explicitly_needs_verified_negative_quote_and_no_value() -> None:
    absent: dict[str, object] = {
        "field_key": "guaranteed_renewal_status",
        "state": "absent_explicitly",
        "value": None,
        "evidence": [{"document": "保险条款.pdf", "page": 5, "quote": "本合同为不保证续保合同。"}],
    }
    result = annotator(FakeJudge([answer(absent)])).annotate(
        "596", PACK, ["guaranteed_renewal_status"], PAGES
    )
    assert result.items[0].state == "absent_explicitly"
    assert result.items[0].value is None


def test_unknown_is_kept_without_evidence() -> None:
    unknown: dict[str, object] = {"field_key": "deductible_rules", "state": "unknown", "value": None, "evidence": []}
    result = annotator(FakeJudge([answer(unknown)])).annotate(
        "596", PACK, ["deductible_rules"], PAGES
    )
    assert result.items[0].state == "unknown"
    assert result.items[0].evidence == []


# ---- Fail closed --------------------------------------------------------------------------


def test_missing_requested_field_is_protocol_error() -> None:
    with pytest.raises(JudgeProtocolError, match="deductible_rules"):
        annotator(FakeJudge([answer(WAITING)])).annotate(
            "596", PACK, ["waiting_period", "deductible_rules"], PAGES
        )


def test_unrequested_or_duplicate_field_is_protocol_error() -> None:
    with pytest.raises(JudgeProtocolError):
        annotator(FakeJudge([answer(WAITING, WAITING)])).annotate(
            "596", PACK, ["waiting_period"], PAGES
        )
    extra = dict(WAITING, field_key="coverage_period")
    with pytest.raises(JudgeProtocolError):
        annotator(FakeJudge([answer(WAITING, extra)])).annotate(
            "596", PACK, ["waiting_period"], PAGES
        )


def test_unparseable_response_is_protocol_error_not_unknown() -> None:
    with pytest.raises(JudgeProtocolError):
        annotator(FakeJudge(["抱歉，我无法回答"])).annotate("596", PACK, ["waiting_period"], PAGES)


def test_fenced_json_is_accepted() -> None:
    fenced = "```json\n" + answer(WAITING) + "\n```"
    result = annotator(FakeJudge([fenced])).annotate("596", PACK, ["waiting_period"], PAGES)
    assert len(result.items) == 1


def test_budget_is_checked_before_each_call() -> None:
    keys = ["waiting_period", "deductible_rules"]
    judge = FakeJudge([answer(WAITING)])
    with pytest.raises(JudgeBudgetExceeded):
        annotator(judge, max_calls=1, batch_size=1).annotate("596", PACK, keys, PAGES)
    assert len(judge.requests) == 1  # the second call was never sent


def test_result_records_calls_and_model() -> None:
    result = annotator(FakeJudge([answer(WAITING)])).annotate(
        "596", PACK, ["waiting_period"], PAGES
    )
    assert result.calls == 1
    assert result.model_id == "fake-judge-1"


# ---- Calibration ----------------------------------------------------------------------------


StateName = Literal["present", "absent_explicitly", "unknown"]


def _item(field: str, state: StateName, value: str | None, judged_by: str) -> GoldenItem:
    evidence = (
        []
        if state == "unknown"
        else [GoldenEvidence(document="保险条款.pdf", document_sha256=SHA, page=3, quote="q")]
    )
    return GoldenItem(
        pack_id=PACK,
        product_id="596",
        field_key=field,
        state=state,
        value=value,
        evidence=evidence,
        judged_by=judged_by,
    )


def test_calibration_compares_judge_against_reference_golden() -> None:
    reference = [
        _item("waiting_period", "present", "90日", "legacy:gs"),
        _item("cooling_off_period", "present", "15日", "legacy:gs"),
        _item("deductible_rules", "unknown", None, "legacy:gs"),
        _item("coverage_period", "present", "1年", "legacy:gs"),
    ]
    judged = [
        _item("waiting_period", "present", "90 日", "model:j"),
        _item("cooling_off_period", "present", "10日", "model:j"),
        _item("deductible_rules", "present", "1万", "model:j"),
    ]
    report = calibrate(judged, reference)
    assert report.compared == 3  # coverage_period was not judged
    assert report.not_judged == ["coverage_period"]
    assert report.state_agreement == 2
    assert report.present_value_agreement == 1
    assert report.disagreements == {"cooling_off_period": "value", "deductible_rules": "state"}
