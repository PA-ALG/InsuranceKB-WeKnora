"""L3 provenance and failure boundaries, with synthetic verdicts only."""

import pytest
from pydantic import ValidationError

from insurance_harness.eval.equivalence import (
    Adjudication,
    EquivalenceQuestion,
    EquivalenceReport,
    apply_adjudications,
    build_equivalence_requests,
    compare_equivalence,
)
from insurance_harness.eval.judge import JudgeRequest


class NoCalls:
    model_id = "unused"

    def complete(self, request: JudgeRequest) -> str:
        raise AssertionError("must reject before calling the judge")


def test_legacy_request_bytes_stay_frozen_across_prompt_revisions() -> None:
    question = EquivalenceQuestion(field_key="duration", reference="90日", judged="期限为90日")
    request = build_equivalence_requests([question], product_id="sample", prompt_version="1")[0]
    # Recorded from the v1 implementation before versioned prompts were added.
    assert request.sha256 == "1f93eb4363138f71eb5d67214e81faecd99352ac5569f7bad8fe0d33eb77d7eb"


def test_unknown_version_fails_even_with_no_questions_or_call_budget() -> None:
    with pytest.raises(ValueError, match="future"):
        compare_equivalence(NoCalls(), [], max_calls=0, prompt_version="future")


def ruling(field: str, to: str = "equivalent") -> Adjudication:
    return Adjudication.model_validate({
        "field_key": field, "from": "contradicted", "to": to,
        "reason": "source section establishes the condition", "by": "reviewer", "on": "2026-10-06",
    })


def test_adjudication_snapshots_survive_successive_calls_without_mutating_input() -> None:
    raw = EquivalenceReport(
        compared=4, equivalent=1, contradicted={"a": "wrong scope", "b": "wrong time"},
        insufficient=["c"], insufficient_reasons={"c": "missing condition"},
    )
    original = raw.model_dump()
    first = apply_adjudications(raw, [ruling("a")])
    second = apply_adjudications(first, [ruling("b", "insufficient")])
    assert raw.model_dump() == original
    assert first.contradicted == {"b": "wrong time"}
    assert second.raw_contradicted == raw.contradicted
    assert second.raw_insufficient == ["c"]
    assert second.equivalent == 2 and second.rate == 0.5
    assert second.insufficient == ["c", "b"]
    assert second.insufficient_reasons == {
        "c": "missing condition", "b": "source section establishes the condition",
    }
    assert second.adjudicated == {
        "a": "contradicted->equivalent", "b": "contradicted->insufficient",
    }
    assert [entry.field_key for entry in second.adjudication_details] == ["a", "b"]
    with pytest.raises(ValueError, match="a"):
        apply_adjudications(first, [ruling("a")])


def test_duplicate_or_mismatched_rulings_fail_without_partial_mutation() -> None:
    report = EquivalenceReport(compared=2, contradicted={"a": "scope"}, insufficient=["b"])
    original = report.model_dump()
    for entries in ([ruling("a"), ruling("a")], [ruling("a"), ruling("b")]):
        with pytest.raises(ValueError):
            apply_adjudications(report, entries)
        assert report.model_dump() == original
    wrong_from = ruling("a").model_dump(by_alias=True) | {
        "from": "insufficient", "to": "insufficient",
    }
    with pytest.raises(ValueError, match="a"):
        apply_adjudications(report, [Adjudication.model_validate(wrong_from)])


@pytest.mark.parametrize("field", ["field_key", "from", "to", "reason", "by", "on"])
def test_adjudication_rejects_whitespace_in_every_required_field(field: str) -> None:
    payload = ruling("a").model_dump(by_alias=True) | {field: " \t"}
    with pytest.raises(ValidationError):
        Adjudication.model_validate(payload)


def test_adjudication_is_frozen() -> None:
    entry = ruling("a")
    with pytest.raises(ValidationError):
        entry.reason = "changed"
