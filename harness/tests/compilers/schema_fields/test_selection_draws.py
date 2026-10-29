"""S12c-6 acceptance (protected, written by Claude): step one is sampled twice per batch; for a
field present in the first draw, the segments a later draw adds reach step two and become evidence
only when step two used them (Spec docs/design/slices/S12c-6-第一步双次选段.md §4, §7).
Offline: completions are fakes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.compilers.schema_fields import prompt
from insurance_harness.compilers.schema_fields.carry import CarriedQuote
from insurance_harness.compilers.schema_fields.claims import claims_from
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.engine import (
    SELECTION_DRAWS,
    CompileBudgetExceeded,
    CompileOutput,
    SchemaFieldsCompiler,
)
from insurance_harness.eval import compile_run
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision
from tests.eval.test_compile_materials import compile_at, repo

__all__ = ["repo"]  # the fixture is imported for pytest

DOCUMENT = "条款.pdf"
LINES = [
    "本合同等待期为90日。",  # D1P1S1
    "因意外伤害发生的不受等待期限制。",  # D1P1S2
    "宽限期为60日。",  # D1P1S3
    "等待期内确诊的不承担责任。",  # D1P1S4
]


class Page:
    document, document_sha256, page = DOCUMENT, "e" * 64, 1
    text = "\n".join(LINES) + "\n"


class Completion:
    model = "recorded-offline"

    def __init__(self, *answers: object) -> None:
        self._answers = [json.dumps(a, ensure_ascii=False) for a in answers]
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self._answers.pop(0)

    def user(self, index: int) -> dict[str, Any]:
        return json.loads(self.calls[index][1])  # type: ignore[no-any-return]


WAITING = FieldDefinition(
    field_key="waiting_period",
    short_title="等待期",
    description="等待期",
    value_spec="文本",
    ordinal=0,
)
GRACE = FieldDefinition(
    field_key="premium_grace_period",
    short_title="宽限期",
    description="宽限期",
    value_spec="文本",
    ordinal=1,
)


def row(key: str, state: str, segments: list[str], ordinal: int = 0) -> dict[str, object]:
    return {"ordinal": ordinal, "field_key": key, "state": state, "segments": segments}


def selection(*rows: dict[str, object]) -> dict[str, object]:
    return {"fields": list(rows)}


def value(key: str = "waiting_period", ordinal: int = 0, **extra: object) -> dict[str, object]:
    return {"fields": [{"ordinal": ordinal, "field_key": key, "value": "取值", **extra}]}


def run(
    *answers: object,
    draws: int = 2,
    fields: list[FieldDefinition] | None = None,
    max_calls: int = 6,
    carry: object = None,
) -> tuple[CompileOutput, Completion]:
    completion = Completion(*answers)
    output = SchemaFieldsCompiler(
        completion,
        batch_size=10,
        max_calls=max_calls,
        selection_draws=draws,
    ).compile("product", fields or [WAITING], [Page()], carry=carry)  # type: ignore[arg-type]
    return output, completion


def step_two_segments(completion: Completion, call: int, field: int = 0) -> str:
    fields = completion.user(call)["schema_fields"]
    return str(fields[field]["segments"])


def test_each_step_one_batch_is_sent_twice_with_the_same_bytes_before_step_two() -> None:
    _, completion = run(
        selection(row("waiting_period", "present", ["D1P1S1"])),
        selection(row("waiting_period", "present", ["D1P1S1"])),
        value(),
    )
    assert len(completion.calls) == 3
    assert completion.calls[0] == completion.calls[1], "the second draw resends the same request"
    assert "segments" in completion.user(2)["schema_fields"][0], "the third call is step two"


def test_a_field_present_in_both_draws_gets_the_second_draws_extra_segments() -> None:
    output, completion = run(
        selection(row("waiting_period", "present", ["D1P1S1"])),
        selection(row("waiting_period", "present", ["D1P1S1", "D1P1S2"])),
        value(used_segments=["D1P1S1", "D1P1S2"]),
    )
    assert "D1P1S2" in step_two_segments(completion, 2)
    field = output.fields[0]
    assert field.segment_ids == ["D1P1S1"], "segment_ids stays the first draw's selection"
    assert field.recalled_segment_ids == ["D1P1S2"]
    assert field.carried_segment_ids == []
    assert [quote.quote for quote in field.evidence] == ["\n".join(LINES[:2])]


def test_the_first_draw_decides_the_state() -> None:
    output, completion = run(
        selection(
            row("waiting_period", "unknown", []),
            row("premium_grace_period", "present", ["D1P1S3"], 1),
        ),
        selection(
            row("waiting_period", "present", ["D1P1S1"]),
            row("premium_grace_period", "unknown", [], 1),
        ),
        value("premium_grace_period", 1),
        fields=[WAITING, GRACE],
    )
    asked = [f["field_key"] for f in completion.user(2)["schema_fields"]]
    assert asked == ["premium_grace_period"], "a field the first draw found unknown is not written"
    waiting, grace = output.fields
    assert (waiting.state, waiting.evidence, waiting.recalled_segment_ids) == ("unknown", [], [])
    assert (grace.state, grace.segment_ids, grace.recalled_segment_ids) == (
        "present",
        ["D1P1S3"],
        [],
    )


def test_an_extra_segment_step_two_did_not_use_is_not_evidence() -> None:
    output, _ = run(
        selection(row("waiting_period", "present", ["D1P1S1"])),
        selection(row("waiting_period", "present", ["D1P1S1", "D1P1S4"])),
        value(used_segments=["D1P1S1"]),
    )
    field = output.fields[0]
    assert field.recalled_segment_ids == []
    assert [quote.quote for quote in field.evidence] == [LINES[0]]


def test_recalled_segments_never_overlap_the_selection_or_the_carry() -> None:
    output, completion = run(
        selection(row("waiting_period", "present", ["D1P1S1"])),
        selection(row("waiting_period", "present", ["D1P1S1", "D1P1S2", "D1P1S4"])),
        value(used_segments=["D1P1S1", "D1P1S2", "D1P1S4"]),
        carry={"waiting_period": [CarriedQuote(DOCUMENT, 1, LINES[1])]},
    )
    segments = step_two_segments(completion, 2)
    assert segments.count("D1P1S2") == 1, "a segment both carried and recalled is sent once"
    field = output.fields[0]
    assert field.carried_segment_ids == ["D1P1S2"], "carry wins when both add the same segment"
    assert field.recalled_segment_ids == ["D1P1S4"]
    assert not set(field.recalled_segment_ids) & {*field.segment_ids, *field.carried_segment_ids}


TERMS = PageText("保险条款.pdf", "a" * 64, 1, "阅读指引\n投保年龄为0周岁至55周岁。\n")
RATES = PageText(
    "费率表.pdf",
    "b" * 64,
    1,
    "《某某重大疾病保险》年交费率表\n交费期间\n投保年龄\n10年交 15年交 20年交 30年交\n"
    "0 408 275 222 157\n",
)
TERM = FieldDefinition(
    field_key="premium_payment_term", short_title="交费期间", description="交费期间", ordinal=0
)
AGE = FieldDefinition(
    field_key="entry_age_range", short_title="投保年龄", description="投保年龄", ordinal=1
)


def test_a_recalled_segment_passes_the_trust_policy() -> None:
    source = SegmentedSource([TERMS], table_headers={"rate_table": [RATES]})
    terms = next(s.id for s in source.segments if "投保年龄为" in s.text)
    header = next(s.id for s in source.segments if s.document == "费率表.pdf")
    completion = Completion(
        selection(
            row("premium_payment_term", "present", [terms]),
            row("entry_age_range", "present", [terms], 1),
        ),
        selection(
            row("premium_payment_term", "present", [terms, header]),
            row("entry_age_range", "present", [terms, header], 1),
        ),
        {
            "fields": [
                {
                    "ordinal": 0,
                    "field_key": "premium_payment_term",
                    "value": "10年交",
                    "used_segments": [terms, header],
                },
                {
                    "ordinal": 1,
                    "field_key": "entry_age_range",
                    "value": "0至55周岁",
                    "used_segments": [terms, header],
                },
            ]
        },
    )
    output = SchemaFieldsCompiler(
        completion, batch_size=10, max_calls=6, selection_draws=2
    ).compile(
        "product",
        [TERM, AGE],
        [TERMS],
        table_headers={"rate_table": [RATES]},
    )
    step_two = completion.user(2)["schema_fields"]
    assert header in str(step_two[0]["segments"])
    assert header not in str(step_two[1]["segments"]), "a header only its trusted field may use"
    term, age = output.fields
    assert term.recalled_segment_ids == [header]
    assert age.recalled_segment_ids == []


def test_the_second_draw_counts_against_the_call_budget() -> None:
    with pytest.raises(CompileBudgetExceeded):
        run(selection(row("waiting_period", "present", ["D1P1S1"])), max_calls=1)
    with pytest.raises(CompileBudgetExceeded):
        run(
            selection(row("waiting_period", "present", ["D1P1S1"])),
            selection(row("waiting_period", "present", ["D1P1S1"])),
            max_calls=2,
        )


def test_one_draw_keeps_the_previous_request_sequence() -> None:
    answers = (selection(row("waiting_period", "present", ["D1P1S1"])), value())
    default = Completion(*answers)
    SchemaFieldsCompiler(default, batch_size=10, max_calls=6).compile(
        "product",
        [WAITING],
        [Page()],
    )
    explicit, completion = run(*answers, draws=1)
    assert completion.calls == default.calls
    assert len(completion.calls) == 2
    assert explicit.fields[0].recalled_segment_ids == []


def test_claims_cite_the_recalled_segments() -> None:
    output, _ = run(
        selection(row("waiting_period", "present", ["D1P1S1"])),
        selection(row("waiting_period", "present", ["D1P1S1", "D1P1S4"])),
        value(used_segments=["D1P1S4"]),
    )
    claim = claims_from(output, SegmentedSource([Page()]), {DOCUMENT: SourceRevision("k", 1)})[0]
    assert [item.quote for item in claim.evidence] == [LINES[0], LINES[3]]


def test_the_protocol_version_and_production_draws() -> None:
    assert prompt.VALUE_PROTOCOL_VERSION == "2026-10-29.1"
    assert SELECTION_DRAWS == 2


def test_compile_run_builds_the_compiler_with_two_draws_and_their_budget(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[dict[str, Any]] = []
    real = SchemaFieldsCompiler

    def spy(*args: Any, **kwargs: Any) -> SchemaFieldsCompiler:
        built.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(compile_run, "SchemaFieldsCompiler", spy)
    sent: list[str] = []
    compile_at(repo, tmp_path / "run", sent)
    assert built[0]["selection_draws"] == SELECTION_DRAWS
    assert built[0]["max_calls"] == SELECTION_DRAWS * 1 + 1, "one batch of one field"
    assert len(sent) == 2 and sent[0] == sent[1], "the fake answers unknown: two step-one draws"
