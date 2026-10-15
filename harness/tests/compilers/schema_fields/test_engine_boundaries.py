"""Adversarial completions and distinct source structures through the public engine.

S4d: the engine speaks the two-step pointer protocol; quotes are cut from page text by
code, so the adversarial cases target refs, row shapes and evidence provenance.
"""

import json
from dataclasses import dataclass

import pytest

from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.engine import (
    CompileBudgetExceeded,
    CompileError,
    SchemaFieldsCompiler,
    to_candidate,
)


@dataclass(frozen=True)
class Page:
    document: str = "条款.pdf"
    document_sha256: str = "a" * 64
    page: int = 1
    text: str = "等待期为90日。\n未提供贷款。"  # D1P1S1, D1P1S2


class Replay:
    model = "offline-fixture"

    def __init__(self, *responses: str) -> None:
        self.responses = iter(responses)
        self.calls = 0

    def complete(self, *, system: str, user: str) -> str:
        self.calls += 1
        return next(self.responses)


def definition(key: str = "term", ordinal: int = 0) -> FieldDefinition:
    return FieldDefinition(
        field_key=key, short_title="期限", description="实际期限", ordinal=ordinal
    )


def row(**changes: object) -> dict[str, object]:
    return {
        "ordinal": 0,
        "field_key": "term",
        "state": "present",
        "segments": ["D1P1S1"],
        **changes,
    }


def value(**changes: object) -> dict[str, object]:
    return {"ordinal": 0, "field_key": "term", "value": "90日", **changes}


def response(*rows: dict[str, object]) -> str:
    return json.dumps({"fields": rows}, ensure_ascii=False)


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "invented"},
        {"state": "unknown"},
        {"state": "absent_explicitly", "segments": []},
        {"segments": []},
        {"segments": "D1P1S1"},
        {"ordinal": False},
        {"ordinal": "0"},
        {"ordinal": 0.0},
        {"extra": "ignored?"},
        {"value": "90日"},
        {"evidence": []},
    ],
)
def test_malformed_selection_rows_fail_the_entire_batch(changes: dict[str, object]) -> None:
    with pytest.raises(CompileError):
        SchemaFieldsCompiler(Replay(response(row(**changes)))).compile(
            "entity", [definition()], [Page()]
        )


@pytest.mark.parametrize(
    "rows",
    [
        [value(value="  ")],
        [value(value=90)],
        [value(value=["90日"])],
        [value(ordinal=1)],
        [value(extra=1)],
        [value(), value()],
        [value(), value(field_key="other")],
    ],
)
def test_malformed_value_rows_fail_the_batch(rows: list[dict[str, object]]) -> None:
    with pytest.raises(CompileError):
        SchemaFieldsCompiler(Replay(response(row()), response(*rows))).compile(
            "entity", [definition()], [Page()]
        )


@pytest.mark.parametrize(
    "raw",
    [
        "```json\n{}\n```",
        '{"fields":[],"fields":[]}',
        '{"fields":NaN}',
        '{"fields":[],"extra":null}',
        '{"fields":{}}',
        "null",
        "[]",
    ],
)
def test_json_envelope_is_closed(raw: str) -> None:
    with pytest.raises(CompileError):
        SchemaFieldsCompiler(Replay(raw)).compile("entity", [definition()], [Page()])


@pytest.mark.parametrize("bad_ref", ["D2P1S1", "D1P2S1", "D1P1S9", "D1P1S2-D1P1S1", 3])
def test_refs_that_name_no_segment_are_dropped_not_guessed(bad_ref: object) -> None:
    kept = SchemaFieldsCompiler(
        Replay(response(row(segments=["D1P1S1", bad_ref])), response(value()))
    ).compile("entity", [definition()], [Page()])
    assert [q.quote for q in kept.fields[0].evidence] == ["等待期为90日。"]
    assert kept.dropped_refs == 1
    lost = SchemaFieldsCompiler(Replay(response(row(segments=[bad_ref])))).compile(
        "entity", [definition()], [Page()]
    )
    assert lost.fields == [] and lost.dropped_fields == ["term"]


def test_evidence_is_never_joined_across_pages() -> None:
    pages = [Page(text="等待期为"), Page(page=2, text="90日")]
    output = SchemaFieldsCompiler(
        Replay(response(row(segments=["D1P1S1", "D1P2S1"])), response(value()))
    ).compile("entity", [definition()], pages)
    assert [(q.page, q.quote) for q in output.fields[0].evidence] == [(1, "等待期为"), (2, "90日")]


def test_absent_and_table_evidence_are_exact_slices_with_provenance() -> None:
    absent = SchemaFieldsCompiler(
        Replay(response(row(state="absent_explicitly", segments=["D1P1S2"])))
    ).compile("one", [definition()], [Page()])
    assert absent.fields[0].state == "absent_explicitly" and absent.fields[0].value is None
    quote = absent.fields[0].evidence[0]
    assert (quote.document, quote.document_sha256, quote.page, quote.quote) == (
        "条款.pdf",
        "a" * 64,
        1,
        "未提供贷款。",
    )
    table_page = Page(text="项目\t限额\n５０,０００元")
    table = SchemaFieldsCompiler(Replay(response(row()), response(value(value="50000元")))).compile(
        "two", [definition()], [table_page]
    )
    assert table.fields[0].evidence[0].quote == "项目\t限额\n５０,０００元"
    assert table.fields[0].evidence[0].match == "EXACT"


def test_each_call_checks_budget_and_building_does_not_spend_it() -> None:
    port = Replay(response(row()))
    engine = SchemaFieldsCompiler(port, batch_size=1, max_calls=1)
    fields = [definition(), definition("second", 1)]
    for _ in range(2):
        assert len(engine.build_requests("entity", fields, [Page()])) == 2
    with pytest.raises(CompileBudgetExceeded):
        engine.compile("entity", fields, [Page()])
    assert port.calls == 1


def test_zero_budget_sends_nothing() -> None:
    port = Replay()
    with pytest.raises(CompileBudgetExceeded):
        SchemaFieldsCompiler(port, max_calls=0).compile("entity", [definition()], [Page()])
    assert port.calls == 0


def test_late_malformed_response_cannot_be_hidden_by_an_earlier_success() -> None:
    port = Replay(response(row()), "not JSON")
    with pytest.raises(CompileError):
        SchemaFieldsCompiler(port, batch_size=1).compile(
            "entity",
            [definition(), definition("second", 1)],
            [Page()],
        )
    assert port.calls == 2


def test_duplicate_page_identity_is_rejected_before_calling() -> None:
    port = Replay()
    with pytest.raises(CompileError):
        SchemaFieldsCompiler(port).compile("entity", [definition()], [Page(), Page(text="other")])
    assert port.calls == 0


@pytest.mark.parametrize(
    "fields", [[definition(), definition()], [definition("one", 1), definition()]]
)
def test_duplicate_or_unordered_targets_fail_before_calling(fields: list[FieldDefinition]) -> None:
    port = Replay()
    with pytest.raises(CompileError):
        SchemaFieldsCompiler(port).compile("entity", fields, [Page()])
    assert port.calls == 0


def test_pack_identity_is_carried_and_cannot_be_relabelled() -> None:
    field = definition().model_copy(update={"pack_id": "test-pack"})
    output = SchemaFieldsCompiler(Replay(response(row()), response(value()))).compile(
        "entity", [field], [Page()]
    )
    assert output.pack_id == "test-pack"
    with pytest.raises(CompileError):
        to_candidate(output, display_name="展示名", schema_pack_id="other-pack")
