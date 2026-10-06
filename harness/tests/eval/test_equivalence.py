"""S2b acceptance: value comparison by semantic equivalence (blueprint §7.7).

Protected file: written by Claude. Pins §8.2 of the S2b spec.

Literal equality is the wrong measure against the legacy 596 reference: both a
verbatim judge (v1, 0/19) and a terse one (v2, 1/19) fail it. The equivalence
layer asks a second, independent judge session whether the reference wording
and the judged wording state the same facts. Contradictions are reported
separately, because a contradiction is a factual error rather than a wording
choice, and one of them already fails the gate.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import ValidationError

from insurance_harness.eval.equivalence import (
    EQUIVALENCE_PROMPT_VERSION,
    Adjudication,
    EquivalenceQuestion,
    EquivalenceReport,
    apply_adjudications,
    build_equivalence_requests,
    compare_equivalence,
)
from insurance_harness.eval.golden import ValueComponent
from insurance_harness.eval.judge import (
    AnnotationResult,
    JudgeAnnotator,
    JudgeBudgetExceeded,
    JudgeProtocolError,
    JudgeRequest,
)
from insurance_harness.eval.judge_files import FileJudgeClient, write_requests


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
        return "fake-equivalence-judge"


def answer(*rows: dict[str, object]) -> str:
    return json.dumps({"fields": list(rows)}, ensure_ascii=False)


def verdict(field: str, value: str, reason: str = "same facts") -> dict[str, object]:
    return {"field_key": field, "verdict": value, "reason": reason}


def question(
    field: str, reference: str, judged: str | None, accepted: Sequence[str] = ()
) -> EquivalenceQuestion:
    components = [ValueComponent(name="要素", accepted=tuple(accepted))] if accepted else []
    return EquivalenceQuestion(
        field_key=field, reference=reference, judged=judged, components=components
    )


def run(
    questions: Sequence[EquivalenceQuestion],
    judge: FakeJudge,
    *,
    batch_size: int = 25,
    max_calls: int = 2,
) -> EquivalenceReport:
    return compare_equivalence(judge, questions, max_calls=max_calls, batch_size=batch_size)


# ---- questions carried to the judge session ---------------------------------------------------


def test_question_carries_both_wordings_and_the_components() -> None:
    questions = [
        question("cooling_off_period", "自签收合同之日起15日", "15日", ["自签收本合同之日起"])
    ]
    requests = build_equivalence_requests(questions, product_id="596")
    assert len(requests) == 1
    payload = json.loads(requests[0].user.split("\n")[0])
    row = payload["fields"][0]
    assert row["field_key"] == "cooling_off_period"
    assert row["reference"] == "自签收合同之日起15日"
    assert row["judged"] == "15日"
    assert row["components"][0]["accepted"] == ["自签收本合同之日起"]


def test_question_never_carries_source_text_or_page_markers() -> None:
    questions = [question("waiting_period", "30日", "30日")]
    request = build_equivalence_requests(questions, product_id="596")[0]
    for token in ("[page", "page=", "document", "保险条款", "quote"):
        assert token not in request.user, token
        assert token not in request.system, token


def test_questions_are_batched_in_order() -> None:
    questions = [question(f"f{i}", "参考", "评委") for i in range(5)]
    requests = build_equivalence_requests(questions, product_id="596", batch_size=2)
    assert len(requests) == 3
    keys = [json.loads(r.user.split("\n")[0])["fields"][0]["field_key"] for r in requests]
    assert keys == ["f0", "f2", "f4"]


def test_request_hashing_is_deterministic() -> None:
    questions = [question("a", "参考", "评委")]
    first = build_equivalence_requests(questions, product_id="596")[0]
    second = build_equivalence_requests(questions, product_id="596")[0]
    assert first.sha256 == second.sha256


def test_a_judged_unknown_value_is_passed_through_as_null() -> None:
    request = build_equivalence_requests([question("a", "参考", None)], product_id="596")[0]
    assert json.loads(request.user.split("\n")[0])["fields"][0]["judged"] is None


# ---- verdict handling ------------------------------------------------------------------------


def test_equivalent_verdicts_raise_the_rate() -> None:
    questions = [
        question("a", "自签收合同之日起15日", "15日"),
        question("b", "计划一1万元；计划二0元", "计划一1万元，计划二0元"),
    ]
    judge = FakeJudge([answer(verdict("a", "equivalent"), verdict("b", "equivalent"))])
    report = run(questions, judge)
    assert report.compared == 2
    assert report.equivalent == 2
    assert report.contradicted == {}
    assert report.insufficient == []
    assert report.rate == 1.0


def test_contradiction_is_reported_with_its_reason_and_lowers_the_rate() -> None:
    questions = [question("a", "30日", "90日"), question("b", "一年", "一年")]
    judge = FakeJudge(
        [answer(verdict("a", "contradicted", "90日 与 30日 不符"), verdict("b", "equivalent"))]
    )
    report = run(questions, judge)
    assert report.compared == 2
    assert report.equivalent == 1
    assert report.contradicted == {"a": "90日 与 30日 不符"}
    assert report.rate == 0.5


def test_insufficient_counts_in_the_denominator_only() -> None:
    questions = [question("a", "参考", "评委"), question("b", "参考", "评委")]
    judge = FakeJudge(
        [answer(verdict("a", "equivalent"), verdict("b", "insufficient", "参考为空"))]
    )
    report = run(questions, judge)
    assert report.compared == 2
    assert report.equivalent == 1
    assert report.insufficient == ["b"]
    assert report.rate == 0.5


# ---- fail closed ----------------------------------------------------------------------------


def test_missing_verdict_is_a_protocol_error() -> None:
    questions = [question("a", "参考", "评委"), question("b", "参考", "评委")]
    judge = FakeJudge([answer(verdict("a", "equivalent"))])
    with pytest.raises(JudgeProtocolError, match="b"):
        run(questions, judge)


def test_unrequested_field_is_a_protocol_error() -> None:
    questions = [question("a", "参考", "评委")]
    judge = FakeJudge([answer(verdict("a", "equivalent"), verdict("b", "equivalent"))])
    with pytest.raises(JudgeProtocolError):
        run(questions, judge)


def test_duplicate_field_is_a_protocol_error() -> None:
    questions = [question("a", "参考", "评委")]
    judge = FakeJudge([answer(verdict("a", "equivalent"), verdict("a", "equivalent"))])
    with pytest.raises(JudgeProtocolError):
        run(questions, judge)


def test_unknown_verdict_token_is_a_protocol_error() -> None:
    questions = [question("a", "参考", "评委")]
    judge = FakeJudge([answer(verdict("a", "maybe"))])
    with pytest.raises(JudgeProtocolError):
        run(questions, judge)


def test_unparseable_response_is_a_protocol_error() -> None:
    questions = [question("a", "参考", "评委")]
    with pytest.raises(JudgeProtocolError):
        run(questions, FakeJudge(["抱歉，我无法判断"]))


def test_fenced_json_is_accepted() -> None:
    questions = [question("a", "参考", "评委")]
    fenced = "```json\n" + answer(verdict("a", "equivalent")) + "\n```"
    assert run(questions, FakeJudge([fenced])).equivalent == 1


def test_budget_is_checked_before_each_call() -> None:
    questions = [question(f"f{i}", "参考", "评委") for i in range(3)]
    judge = FakeJudge([answer(verdict("f0", "equivalent"))])
    with pytest.raises(JudgeBudgetExceeded):
        run(questions, judge, batch_size=1, max_calls=1)
    assert len(judge.requests) == 1  # the second call was never sent


# ---- gate -----------------------------------------------------------------------------------


def test_gate_requires_eighty_percent_equivalent_and_zero_contradictions() -> None:
    assert EquivalenceReport(compared=10, equivalent=8).passes() is True
    assert EquivalenceReport(compared=10, equivalent=7).passes() is False
    assert EquivalenceReport(compared=10, equivalent=10, contradicted={"a": "x"}).passes() is False


def test_gate_is_undefined_without_any_compared_field() -> None:
    assert EquivalenceReport().passes() is None


# ---- file exchange reuses the same protocol ---------------------------------------------------


def test_compare_equivalence_runs_through_the_file_exchange(tmp_path: Path) -> None:
    questions = [question("a", "自签收合同之日起15日", "15日")]
    write_requests(build_equivalence_requests(questions, product_id="596"), tmp_path)
    (tmp_path / "responses" / "001.json").write_text(
        answer(verdict("a", "equivalent")), encoding="utf-8"
    )
    client = FileJudgeClient(tmp_path, model_id="gpt-6-astra")
    report = compare_equivalence(client, questions, max_calls=2, batch_size=25)
    assert report.equivalent == 1
    assert client.unconsumed() == []


def test_equivalence_report_is_its_own_type() -> None:
    """The equivalence layer must not reuse the annotation result type."""
    assert not issubclass(EquivalenceReport, AnnotationResult)
    assert not issubclass(AnnotationResult, EquivalenceReport)
    assert JudgeAnnotator is not None


# ---- prompt v2: judging is one-directional (spec §8.4) ----------------------------------------
#
# 596's first equivalence pass (v1) showed the judge reading "the judged answer is MORE precise
# than the reference" as a contradiction. Both instances were verbatim source wording that the
# human-written reference summary had dropped. The rule below is what stops that from repeating
# across the four products, so these two lines are pinned word for word.

V2_RULE_LINES = (
    "判定单向：只问参考列出的核心事实是否被评委答案覆盖；评委答额外给出或更精确地给出参考未列的条件，",
    "而参考列出的事实仍成立时判 equivalent，不得判 contradicted。",
    "contradicted 只留给同一事实上的互斥：数值不同、范围不相交、条件互相排斥、责任方向相反。",
)


def test_current_prompt_version_is_two() -> None:
    assert EQUIVALENCE_PROMPT_VERSION == "2"


def test_default_requests_use_the_current_version() -> None:
    request = build_equivalence_requests([question("a", "参考", "评委")], product_id="596")[0]
    for line in V2_RULE_LINES:
        assert line in request.system, line


def test_version_one_system_text_is_frozen_and_still_reachable() -> None:
    """Re-answering an old run must rebuild its exact prompt, so v1 stays byte-identical."""
    request = build_equivalence_requests(
        [question("a", "参考", "评委")], product_id="596", prompt_version="1"
    )[0]
    assert "遗漏不得按措辞不同放过。" in request.system
    for line in V2_RULE_LINES:
        assert line not in request.system, line


def test_an_unknown_prompt_version_is_refused() -> None:
    with pytest.raises(ValueError, match="3"):
        build_equivalence_requests(
            [question("a", "参考", "评委")], product_id="596", prompt_version="3"
        )


def test_the_version_reaches_the_hashing_so_the_two_versions_differ() -> None:
    questions = [question("a", "参考", "评委")]
    one = build_equivalence_requests(questions, product_id="596", prompt_version="1")
    two = build_equivalence_requests(questions, product_id="596", prompt_version="2")
    assert one[0].sha256 != two[0].sha256


# ---- L3 adjudication (spec §8.5) --------------------------------------------------------------
#
# The equivalent/contradicted split is the judge's call and it can be wrong; the human ruling is
# final. What must stay visible is that a ruling happened: the raw verdicts are kept and the
# adjudicated ones are the only thing the gate reads.


def adjudication(
    field: str, *, from_verdict: str = "contradicted", to_verdict: str = "equivalent"
) -> Adjudication:
    return Adjudication(
        field_key=field,
        from_verdict=from_verdict,
        to_verdict=to_verdict,
        reason="评委答与原文逐字一致，参考漏了限定条件",
        by="Claude Code",
        on="2026-10-06",
    )


def contradicted_report() -> EquivalenceReport:
    questions = [question(f"f{i}", "参考", "评委") for i in range(4)]
    judge = FakeJudge([
        answer(
            verdict("f0", "equivalent"),
            verdict("f1", "equivalent"),
            verdict("f2", "contradicted", "条件不同"),
            verdict("f3", "insufficient", "参考为空"),
        )
    ])
    report = run(questions, judge)
    assert report.passes() is False
    return report


def test_adjudication_overrules_a_contradiction_and_recomputes_the_rate() -> None:
    report = apply_adjudications(contradicted_report(), [adjudication("f2")])
    assert report.compared == 4
    assert report.equivalent == 3
    assert report.contradicted == {}
    assert report.rate == 0.75


def test_adjudication_keeps_the_raw_verdict_for_diagnostics() -> None:
    report = apply_adjudications(contradicted_report(), [adjudication("f2")])
    assert report.raw_contradicted == {"f2": "条件不同"}
    assert report.raw_insufficient == ["f3"]
    assert report.adjudicated == {"f2": "contradicted->equivalent"}


def test_a_ruling_that_overrules_everything_is_not_enough() -> None:
    """Three of four equivalent still misses the bar: only a contradiction is overrulable."""
    report = apply_adjudications(contradicted_report(), [adjudication("f2")])
    assert report.rate is not None and report.rate < 0.8
    assert report.passes() is False


def test_an_adjudication_must_point_at_a_real_verdict_of_that_kind() -> None:
    report = contradicted_report()
    with pytest.raises(ValueError, match="f0"):
        apply_adjudications(report, [adjudication("f0")])
    with pytest.raises(ValueError, match="nope"):
        apply_adjudications(report, [adjudication("nope")])


def test_insufficient_cannot_be_ruled_up_to_equivalent() -> None:
    """A missing fact is a real gap; the ruling may not paper over it."""
    with pytest.raises(ValueError):
        adjudication("f3", from_verdict="insufficient", to_verdict="equivalent")


def test_an_adjudication_rejects_unknown_fields_and_blank_reasons() -> None:
    with pytest.raises(ValidationError):
        Adjudication(
            field_key="a", from_verdict="contradicted", to_verdict="equivalent",
            reason="", by="Claude Code", on="2026-10-06",
        )
    with pytest.raises(ValidationError):
        Adjudication(
            field_key="a", from_verdict="contradicted", to_verdict="equivalent",
            reason="说得通", by="Claude Code", on="2026-10-06", surprise="x",
        )


def test_the_596_ruling_moves_the_calibration_over_the_bar() -> None:
    """equivalent 16 / compared 19 = 84.2% with no contradiction left, after the two rulings."""
    report = EquivalenceReport(
        compared=19, equivalent=14,
        contradicted={
            "claim_application_deadline_and_documents": "起算条件不同",
            "reimbursement_rate_rules": "缩小了适用范围",
        },
        insufficient=["policyholder_rights", "insured_eligibility", "entry_age_range"],
    )
    assert report.passes() is False
    ruled = apply_adjudications(
        report,
        [
            adjudication("claim_application_deadline_and_documents"),
            adjudication("reimbursement_rate_rules"),
        ],
    )
    assert ruled.equivalent == 16
    assert ruled.compared == 19
    assert round(ruled.rate or 0, 4) == 0.8421
    assert ruled.contradicted == {}
    assert ruled.passes() is True
    assert len(ruled.insufficient) == 3
