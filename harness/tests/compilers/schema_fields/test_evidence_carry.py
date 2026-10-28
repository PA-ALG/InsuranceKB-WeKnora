"""S12c-4 acceptance (protected, written by Claude): a recompile hands step two the segments a
published, reviewed claim cites, and they become evidence only when step two used them
(Spec docs/design/slices/S12c-4-复用已审证据段.md §2.2–§2.3). Offline: completions are fakes.
"""

from __future__ import annotations

import json

from insurance_harness.compilers.schema_fields.carry import CarriedQuote
from insurance_harness.compilers.schema_fields.claims import claims_from
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.engine import CompileOutput, SchemaFieldsCompiler
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision

DOCUMENT = "条款.pdf"
LINES = [
    "本合同等待期为90日。",  # D1P1S1
    "因意外伤害发生的不受等待期限制。",  # D1P1S2
    "宽限期为60日。",  # D1P1S3
    "等待期内确诊的不承担责任。",  # D1P1S4
    "犹豫期为15日。",  # D1P1S5
    "犹豫期为15日。",  # D1P1S6, a repeat: its quote occurs twice on the page
]


class Page:
    document, document_sha256, page = DOCUMENT, "e" * 64, 1
    text = "\n".join(LINES) + "\n"


class Completion:
    model = "recorded-offline"

    def __init__(self, *answers: object) -> None:
        self._answers = [json.dumps(a, ensure_ascii=False) for a in answers]
        self.users: list[dict[str, object]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.users.append(json.loads(user))
        return self._answers.pop(0)


WAITING = FieldDefinition(
    field_key="waiting_period", short_title="等待期", description="等待期", value_spec="文本",
    ordinal=0,
)


def selection(state: str, segments: list[str]) -> dict[str, object]:
    return {"fields": [
        {"ordinal": 0, "field_key": "waiting_period", "state": state, "segments": segments},
    ]}


def value(**extra: object) -> dict[str, object]:
    row = {"ordinal": 0, "field_key": "waiting_period", "value": "等待期90日", **extra}
    return {"fields": [row]}


def carried(*quotes: str) -> dict[str, list[CarriedQuote]]:
    return {"waiting_period": [CarriedQuote(DOCUMENT, 1, quote) for quote in quotes]}


def run(*answers: object, carry: object = None) -> tuple[CompileOutput, Completion]:
    completion = Completion(*answers)
    output = SchemaFieldsCompiler(completion, batch_size=10, max_calls=5).compile(
        "product", [WAITING], [Page()], carry=carry,  # type: ignore[arg-type]
    )
    return output, completion


def step_two_segments(completion: Completion) -> str:
    fields = completion.users[1]["schema_fields"]
    assert isinstance(fields, list)
    return str(fields[0]["segments"])


def test_a_carried_segment_reaches_step_two_and_becomes_evidence_when_used() -> None:
    output, completion = run(
        selection("present", ["D1P1S1"]),
        value(used_segments=["D1P1S1", "D1P1S2"]),
        carry=carried(LINES[1]),
    )
    assert "D1P1S1" in step_two_segments(completion)
    assert "D1P1S2" in step_two_segments(completion), "the reviewed segment is in step two's input"
    field = output.fields[0]
    assert field.segment_ids == ["D1P1S1"], "segment_ids stays this run's step-one selection"
    assert field.carried_segment_ids == ["D1P1S2"]
    assert [quote.quote for quote in field.evidence] == ["\n".join(LINES[:2])]


def test_a_carried_segment_step_two_did_not_use_is_not_evidence() -> None:
    output, _ = run(
        selection("present", ["D1P1S1"]),
        value(used_segments=["D1P1S1"]),
        carry=carried(LINES[1]),
    )
    field = output.fields[0]
    assert field.carried_segment_ids == []
    assert [quote.quote for quote in field.evidence] == [LINES[0]]


def test_without_valid_used_segments_every_carried_segment_is_evidence() -> None:
    for answer in (value(), value(used_segments=[]), value(used_segments=["D9P9S9"])):
        output, _ = run(selection("present", ["D1P1S1"]), answer, carry=carried(LINES[3]))
        field = output.fields[0]
        assert field.segment_ids == ["D1P1S1"]
        assert field.carried_segment_ids == ["D1P1S4"]
        assert [quote.quote for quote in field.evidence] == [LINES[0], LINES[3]]


def test_unresolvable_repeated_and_already_selected_quotes_carry_nothing() -> None:
    output, completion = run(
        selection("present", ["D1P1S1"]),
        value(),
        carry=carried("材料中没有的一句话。", LINES[4], LINES[0]),
    )
    segments = step_two_segments(completion)
    assert "D1P1S5" not in segments and "D1P1S6" not in segments, "a repeated quote is ambiguous"
    assert segments.count("D1P1S1") == 1, "a selected segment is not handed over twice"
    field = output.fields[0]
    assert field.carried_segment_ids == []
    assert field.segment_ids == ["D1P1S1"]


def test_a_step_one_unknown_takes_no_carry_and_sends_nothing_more() -> None:
    output, completion = run(selection("unknown", []), carry=carried(LINES[0]))
    assert len(completion.users) == 1, "no step two for a field step one found nothing for"
    field = output.fields[0]
    assert (field.state, field.carried_segment_ids, field.evidence) == ("unknown", [], [])


def test_no_carry_keeps_the_previous_behaviour() -> None:
    plain, _ = run(selection("present", ["D1P1S1"]), value())
    empty, _ = run(selection("present", ["D1P1S1"]), value(), carry={})
    for output in (plain, empty):
        field = output.fields[0]
        assert (field.segment_ids, field.carried_segment_ids) == (["D1P1S1"], [])


def test_claims_cut_evidence_from_the_selection_and_the_carried_segments() -> None:
    output, _ = run(
        selection("present", ["D1P1S1"]),
        value(used_segments=["D1P1S4"]),
        carry=carried(LINES[3]),
    )
    claim = claims_from(output, SegmentedSource([Page()]), {DOCUMENT: SourceRevision("k", 1)})[0]
    assert [item.quote for item in claim.evidence] == [LINES[0], LINES[3]]
    assert [item.locator.page for item in claim.evidence] == [1, 1]
