"""S12c-1 acceptance (protected, written by Claude): step two may answer unknown, its answer
shape is strict, used segments never become evidence, outputs record the value protocol and
old outputs are not reused (Spec docs/design/slices/S12c-1-取值协议v2.md §2–§5). Offline:
every completion is a recorded fake.
"""

from __future__ import annotations

import json

import pytest

from insurance_harness.compilers.schema_fields.cards import cards_version
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.engine import (
    CompileError,
    CompileOutput,
    FieldResult,
    SchemaFieldsCompiler,
    reusable,
)
from insurance_harness.compilers.schema_fields.parse import parse_values
from insurance_harness.compilers.schema_fields.prompt import (
    VALUE_PROTOCOL_VERSION,
    build_value_request,
)
from insurance_harness.evidence.segments import SegmentedSource


class Page:
    document, document_sha256, page = "条款.pdf", "e" * 64, 1
    text = "本合同等待期为90日。\n宽限期为60日。\n"


class Completion:
    model = "recorded-offline"

    def __init__(self, *answers: object) -> None:
        self._answers = [json.dumps(a, ensure_ascii=False) for a in answers]

    def complete(self, *, system: str, user: str) -> str:
        return self._answers.pop(0)


def definition(key: str, title: str, ordinal: int) -> FieldDefinition:
    return FieldDefinition(
        field_key=key, short_title=title, description=title, value_spec="文本", ordinal=ordinal
    )


WAITING, GRACE = definition("waiting_period", "等待期", 0), definition("grace_period", "宽限期", 1)


def selected(*rows: tuple[int, str, str, list[str]]) -> dict[str, object]:
    return {
        "fields": [
            {"ordinal": o, "field_key": k, "state": s, "segments": segs} for o, k, s, segs in rows
        ]
    }


def compile_with(selection: object, values: object | None) -> CompileOutput:
    answers = [selection] if values is None else [selection, values]
    return SchemaFieldsCompiler(Completion(*answers), batch_size=10, max_calls=5).compile(
        "product", [WAITING, GRACE], [Page()]
    )


def test_a_step_two_unknown_is_exactly_a_step_one_unknown() -> None:
    both_present = selected(
        (0, "waiting_period", "present", ["D1P1S1"]), (1, "grace_period", "present", ["D1P1S2"])
    )
    answered = compile_with(
        both_present,
        {
            "fields": [
                {"ordinal": 0, "field_key": "waiting_period", "state": "unknown"},
                {"ordinal": 1, "field_key": "grace_period", "state": "present", "value": "60日"},
            ]
        },
    )
    by_key = {f.field_key: f for f in answered.fields}
    assert by_key["waiting_period"] == FieldResult(field_key="waiting_period", state="unknown")
    assert answered.dropped_fields == [], "an unknown answer is a result, not a loss"
    grace = by_key["grace_period"]
    assert (grace.state, grace.value, grace.segment_ids) == ("present", "60日", ["D1P1S2"])
    assert len(grace.evidence) == 1

    step_one_unknown = compile_with(
        selected(
            (0, "waiting_period", "unknown", []), (1, "grace_period", "present", ["D1P1S2"])
        ),
        {"fields": [{"ordinal": 1, "field_key": "grace_period", "value": "60日"}]},
    )
    same = {f.field_key: f for f in step_one_unknown.fields}["waiting_period"]
    assert same.model_dump() == by_key["waiting_period"].model_dump()


def test_used_segments_are_a_working_note_never_evidence() -> None:
    selection = selected(
        (0, "waiting_period", "present", ["D1P1S1", "D1P1S2"]), (1, "grace_period", "unknown", [])
    )

    def waiting(**extra: object) -> FieldResult:
        answer = {"ordinal": 0, "field_key": "waiting_period", "value": "90日", **extra}
        output = compile_with(selection, {"fields": [answer]})
        return {f.field_key: f for f in output.fields}["waiting_period"]

    noted = waiting(used_segments=["D1P1S1"])
    assert noted.segment_ids == ["D1P1S1", "D1P1S2"], "evidence stays the step-one selection"
    assert noted.evidence == waiting().evidence


def rows(*items: dict[str, object]) -> str:
    return json.dumps({"fields": list(items)}, ensure_ascii=False)


def row(**extra: object) -> dict[str, object]:
    return {"ordinal": 0, "field_key": "waiting_period", **extra}


def test_a_value_row_without_state_is_the_legacy_present_answer() -> None:
    assert parse_values(rows(row(value="90日")), [WAITING]) == {"waiting_period": "90日"}
    assert parse_values(rows(row(state="unknown")), [WAITING]) == {"waiting_period": None}
    assert parse_values(rows(row(state="present", value="90日", used_segments=[])), [WAITING]) == {
        "waiting_period": "90日"
    }


@pytest.mark.parametrize(
    "bad",
    [
        rows(row(state="unknown", value="材料未提及")),
        rows(row(state="unknown", value="")),
        rows(row(state="present")),
        rows(row(state="present", value="   ")),
        rows(row()),
        rows(row(state="maybe", value="90日")),
        rows(row(value="90日", note="extra")),
        rows(row(value="90日", used_segments="D1P1S1")),
        rows(row(value="90日"), row(state="unknown")),
    ],
    ids=["unknown-with-value", "unknown-with-empty-value", "present-without-value",
         "present-blank", "no-state-no-value", "bad-state", "unknown-key",
         "used-segments-not-a-list", "duplicate-row"],
)
def test_value_rows_are_strict(bad: str) -> None:
    with pytest.raises(CompileError):
        parse_values(bad, [WAITING])


# PR #394 review R1: an unknown row that carries the value key, even as null, breaks the format
# and rejects the batch; a legal unknown row still parses to None (above).
UNKNOWN_WITH_NULL = rows(row(state="unknown", value=None), {"ordinal": 1, "field_key":
                         "grace_period", "state": "present", "value": "60日"})


def test_an_unknown_row_carrying_a_null_value_rejects_the_batch() -> None:
    with pytest.raises(CompileError):
        parse_values(UNKNOWN_WITH_NULL, [WAITING, GRACE])
    compiler = SchemaFieldsCompiler(
        Completion(
            selected((0, "waiting_period", "present", ["D1P1S1"]),
                     (1, "grace_period", "present", ["D1P1S2"])),
            json.loads(UNKNOWN_WITH_NULL),
        ),
        batch_size=10, max_calls=5,
    )
    with pytest.raises(CompileError):
        compiler.compile("product", [WAITING, GRACE], [Page()])


# PR #394 review R2: used_segments members must be strings.
@pytest.mark.parametrize("member", [{}, None, 1, True, []], ids=["object", "null", "int", "bool",
                                                                   "list"])
def test_used_segments_members_must_be_strings(member: object) -> None:
    with pytest.raises(CompileError):
        parse_values(rows(row(value="90日", used_segments=[member])), [WAITING])


# PR #366 review counterexamples: sentences that state a fact next to a non-mention. The
# protocol removes no text by rule; a value the model writes stays as written.
MIXED = [
    "通知时限为10日：材料未载明诉讼时效。",
    "健康咨询免费提供：材料未提及预约限制。",
    "条款未约定的事项按保险法执行。",
    "原文未列明的医院均不属于定点医院。",
    "条款未约定事项遵照保险法处理。",
    "条款未约定或约定存在争议的事项十日内提交保险公司处理。",
    "材料未提及收费且明确免费提供健康咨询。",
    "材料未载明具体时限并承诺随时受理申请。",
    "给定材料没有说明续保限制且承诺保证续保。",
    "材料未载明事项另行协商解决。",
]


@pytest.mark.parametrize("value", MIXED)
def test_a_mixed_value_written_by_the_model_is_kept(value: str) -> None:
    output = compile_with(
        selected((0, "waiting_period", "present", ["D1P1S1"]), (1, "grace_period", "unknown", [])),
        {"fields": [{"ordinal": 0, "field_key": "waiting_period", "state": "present",
                     "value": value}]},
    )
    waiting = {f.field_key: f for f in output.fields}["waiting_period"]
    assert (waiting.state, waiting.value) == ("present", value)


def test_the_output_records_the_value_protocol() -> None:
    output = compile_with(
        selected((0, "waiting_period", "present", ["D1P1S1"]), (1, "grace_period", "unknown", [])),
        {"fields": [{"ordinal": 0, "field_key": "waiting_period", "value": "90日"}]},
    )
    assert VALUE_PROTOCOL_VERSION.strip()
    assert output.value_protocol == VALUE_PROTOCOL_VERSION
    raw = output.model_dump(mode="json")
    del raw["value_protocol"]
    assert CompileOutput.model_validate(raw).value_protocol is None, "older outputs still load"


def test_only_an_output_of_the_current_protocol_cards_and_materials_is_reusable() -> None:
    materials = ["k-1:1:" + "a" * 64]
    current = CompileOutput(
        pack_id="p", entity_id="product", model="m", materials=materials,
        cards_version=cards_version(), value_protocol=VALUE_PROTOCOL_VERSION,
    )
    assert reusable(current, materials)
    assert not reusable(current, ["k-2:1:" + "a" * 64])
    assert not reusable(current.model_copy(update={"cards_version": "old"}), materials)
    assert not reusable(current.model_copy(update={"value_protocol": None}), materials)
    assert not reusable(current.model_copy(update={"value_protocol": "older"}), materials)
    assert not reusable(current.model_copy(update={"materials": None}), materials)


def test_the_value_request_allows_and_shapes_an_unknown_answer() -> None:
    source = SegmentedSource([Page()])
    system = build_value_request("product", [(WAITING, source.ordered(["D1P1S1"]))]).system
    assert "unknown" in system and '"state"' in system
    assert "value 始终是一个非空字符串" not in system, "the v1 rule that forced a value is gone"
