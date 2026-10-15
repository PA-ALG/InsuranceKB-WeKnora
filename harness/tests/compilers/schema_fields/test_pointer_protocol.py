"""S4d acceptance: the two-step pointer protocol of the field compiler (Spec §3.2–§3.3).

Protected file: written by Claude. Step one returns segment ids per field; step two writes
values from only the selected segments; evidence is always cut from page text by code.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.engine import (
    CompileBudgetExceeded,
    CompileError,
    CompileOutput,
    SchemaFieldsCompiler,
)

SHA = "c" * 64


class Page:
    def __init__(self, document: str, page: int, text: str) -> None:
        self.document, self.document_sha256, self.page, self.text = document, SHA, page, text


PAGES = [
    Page(
        "保险条款.pdf",
        1,
        "1.4 等待期\n自本合同生效之日起90日内为等待期。\n因意外伤害发生保险事故的，无等待期。\n"
        "1.5 保险期间\n本合同保险期间为一年。\n",
    ),
    Page("产品说明书.pdf", 2, "本产品不设宽限期。\n"),
]
# Segments: D1P1S1 "1.4 等待期" + 90日, D1P1S2 意外例外,
#           D1P1S3 "1.5 保险期间" + 一年, D2P2S1 不设宽限期


def fields() -> list[FieldDefinition]:
    keys = [
        ("waiting_period", "等待期"),
        ("coverage_period", "保障期间"),
        ("premium_grace_period", "宽限期"),
    ]
    return [
        FieldDefinition(field_key=k, short_title=t, description=t, ordinal=n)
        for n, (k, t) in enumerate(keys)
    ]


class Completion:
    def __init__(self, payloads: Sequence[str]) -> None:
        self._payloads = list(payloads)
        self.seen: list[tuple[str, str]] = []

    @property
    def model(self) -> str:
        return "recorded-offline"

    def complete(self, *, system: str, user: str) -> str:
        self.seen.append((system, user))
        return self._payloads.pop(0)


def selection(*rows: tuple[int, str, str, list[object]]) -> str:
    return json.dumps(
        {
            "fields": [
                {"ordinal": o, "field_key": k, "state": s, "segments": g} for o, k, s, g in rows
            ]
        },
        ensure_ascii=False,
    )


def values(*rows: tuple[int, str, str]) -> str:
    return json.dumps(
        {"fields": [{"ordinal": o, "field_key": k, "value": v} for o, k, v in rows]},
        ensure_ascii=False,
    )


SELECT = selection(
    (0, "waiting_period", "present", ["D1P1S1-D1P1S2"]),
    (1, "coverage_period", "present", ["D1P1S3"]),
    (2, "premium_grace_period", "absent_explicitly", ["D2P2S1"]),
)
VALUES = values((0, "waiting_period", "90日；意外伤害无等待期"), (1, "coverage_period", "一年"))


def compile_with(*payloads: str, **options: int) -> tuple[Completion, CompileOutput]:
    completion = Completion(payloads)
    output = SchemaFieldsCompiler(completion, **options).compile("1818", fields(), PAGES)
    return completion, output


def test_two_steps_produce_values_with_evidence_cut_from_page_text() -> None:
    completion, output = compile_with(SELECT, VALUES)
    by_key = {f.field_key: f for f in output.fields}
    waiting = by_key["waiting_period"]
    assert waiting.state == "present" and waiting.value == "90日；意外伤害无等待期"
    assert [q.quote for q in waiting.evidence] == [
        "1.4 等待期\n自本合同生效之日起90日内为等待期。\n因意外伤害发生保险事故的，无等待期。"
    ]
    assert [q.quote for q in by_key["coverage_period"].evidence] == [
        "1.5 保险期间\n本合同保险期间为一年。"
    ]
    grace = by_key["premium_grace_period"]
    assert grace.state == "absent_explicitly" and grace.value is None
    assert [q.quote for q in grace.evidence] == ["本产品不设宽限期。"]
    assert output.calls == 2 and len(completion.seen) == 2


def test_selection_request_lists_segments_and_never_asks_for_quotes() -> None:
    completion, _ = compile_with(SELECT, VALUES)
    system, user = completion.seen[0]
    assert "D1P1S1" in user and "D2P2S1 本产品不设宽限期。" in user
    assert "quote" not in system and "quote" not in user


def test_value_request_carries_only_the_selected_segments() -> None:
    completion, _ = compile_with(SELECT, VALUES)
    _, user = completion.seen[1]
    assert "本合同保险期间为一年。" in user and "自本合同生效之日起90日内为等待期。" in user
    assert "本产品不设宽限期。" not in user, "absent fields need no value step"
    assert "premium_grace_period" not in user


def test_no_present_field_means_no_value_call() -> None:
    only_absent = selection(
        (0, "waiting_period", "unknown", []),
        (1, "coverage_period", "unknown", []),
        (2, "premium_grace_period", "absent_explicitly", ["D2P2S1"]),
    )
    completion, output = compile_with(only_absent)
    assert output.calls == 1 and len(completion.seen) == 1
    assert [f.state for f in output.fields] == ["unknown", "unknown", "absent_explicitly"]
    assert output.fields[0].evidence == []


def test_invalid_refs_are_dropped_and_a_present_field_left_without_segments_is_dropped() -> None:
    bad = selection(
        (0, "waiting_period", "present", ["D1P1S1", "D7P7S7"]),
        (1, "coverage_period", "present", ["D9P9S9"]),
        (2, "premium_grace_period", "unknown", []),
    )
    _, output = compile_with(bad, values((0, "waiting_period", "90日")))
    assert [f.field_key for f in output.fields if f.state != "unknown"] == ["waiting_period"]
    assert output.dropped_refs == 2
    assert output.dropped_fields == ["coverage_period"]


@pytest.mark.parametrize(
    "row",
    [
        (0, "waiting_period", "unknown", ["D1P1S1"]),
        (0, "waiting_period", "present", []),
        (0, "waiting_period", "absent_explicitly", []),
        (0, "waiting_period", "maybe", ["D1P1S1"]),
    ],
)
def test_state_and_segments_must_agree_or_the_batch_fails(
    row: tuple[int, str, str, list[object]],
) -> None:
    payload = selection(
        row, (1, "coverage_period", "unknown", []), (2, "premium_grace_period", "unknown", [])
    )
    with pytest.raises(CompileError):
        compile_with(payload)


def test_selection_rows_must_match_the_requested_fields_exactly() -> None:
    missing = selection((0, "waiting_period", "unknown", []), (1, "coverage_period", "unknown", []))
    with pytest.raises(CompileError):
        compile_with(missing)


def test_a_missing_value_row_drops_only_that_field() -> None:
    _, output = compile_with(SELECT, values((0, "waiting_period", "90日")))
    assert {f.field_key for f in output.fields} == {"waiting_period", "premium_grace_period"}
    assert output.dropped_fields == ["coverage_period"]


@pytest.mark.parametrize(
    "payload",
    [
        values((0, "waiting_period", "90日"), (1, "coverage_period", "一年"), (2, "invented", "x")),
        values((0, "waiting_period", "90日"), (0, "waiting_period", "90日")),
        values((0, "waiting_period", "")),
        "不是 JSON",
    ],
)
def test_unexpected_duplicate_or_malformed_value_rows_fail_the_batch(payload: str) -> None:
    with pytest.raises(CompileError):
        compile_with(SELECT, payload)


def test_value_step_batches_by_selected_text_size() -> None:
    completion, output = compile_with(
        SELECT,
        values((0, "waiting_period", "90日")),
        values((1, "coverage_period", "一年")),
        value_batch_chars=20,
    )
    assert output.calls == 3 and len(completion.seen) == 3
    assert (
        "waiting_period" in completion.seen[1][1] and "coverage_period" not in completion.seen[1][1]
    )


def test_budget_covers_both_steps() -> None:
    completion = Completion([SELECT, VALUES])
    with pytest.raises(CompileBudgetExceeded):
        SchemaFieldsCompiler(completion, max_calls=1).compile("1818", fields(), PAGES)
    assert len(completion.seen) == 1, "the value call must never be sent"
