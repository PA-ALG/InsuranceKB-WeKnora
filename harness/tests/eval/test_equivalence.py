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

from insurance_harness.eval.equivalence import (
    EquivalenceQuestion,
    EquivalenceReport,
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
