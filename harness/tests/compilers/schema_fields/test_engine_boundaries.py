"""Adversarial completions and two distinct source structures through the public engine."""

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
    text: str = "等待期为90日。未提供贷款。"


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


def evidence(**changes: object) -> dict[str, object]:
    return {
        "document": "条款.pdf",
        "document_sha256": "a" * 64,
        "page": 1,
        "quote": "等待期为90日",
        **changes,
    }


def row(**changes: object) -> dict[str, object]:
    return {
        "ordinal": 0,
        "field_key": "term",
        "state": "present",
        "value": "90日",
        "evidence": [evidence()],
        **changes,
    }


def response(*rows: dict[str, object]) -> str:
    return json.dumps({"fields": rows}, ensure_ascii=False)


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "absent_explicitly", "value": "没有"},
        {"state": "absent_explicitly", "value": None, "evidence": []},
        {"state": "unknown", "value": None},
        {"state": "unknown", "evidence": []},
        {"state": "invented"},
        {"value": "  "},
        {"value": 90},
        {"value": ["90日"]},
        {"ordinal": False},
        {"ordinal": "0"},
        {"ordinal": 0.0},
        {"extra": "ignored?"},
        {"evidence": "not a list"},
        {"evidence": []},
        {"evidence": [evidence(page=True)]},
        {"evidence": [evidence(page=0)]},
        {"evidence": [evidence(document_sha256="bad")]},
        {"evidence": [evidence(quote="")]},
        {"evidence": [evidence(extra=1)]},
    ],
)
def test_malformed_rows_fail_the_entire_batch(changes: dict[str, object]) -> None:
    with pytest.raises(CompileError):
        SchemaFieldsCompiler(Replay(response(row(**changes)))).compile(
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


@pytest.mark.parametrize(
    "bad_evidence",
    [
        evidence(document="别的条款.pdf"),
        evidence(document_sha256="b" * 64),
        evidence(page=2),
        evidence(quote="等待期为180日"),
    ],
)
def test_any_unverified_reference_rejects_the_field(bad_evidence: dict[str, object]) -> None:
    output = SchemaFieldsCompiler(
        Replay(response(row(evidence=[evidence(), bad_evidence])))
    ).compile(
        "entity",
        [definition()],
        [Page()],
    )
    assert output.fields == []


def test_no_cross_page_join_or_search_for_a_replacement_page() -> None:
    pages = [Page(text="等待期为"), Page(page=2, text="90日"), Page(page=3)]
    output = SchemaFieldsCompiler(Replay(response(row()))).compile("entity", [definition()], pages)
    assert output.fields == []


def test_absent_and_normalized_table_evidence_keep_their_provenance() -> None:
    completion = Replay(
        response(
            row(
                state="absent_explicitly",
                value=None,
                evidence=[evidence(quote="未提供贷款")],
            )
        ),
        response(row(value="50000元", evidence=[evidence(quote="限额50000元")])),
    )
    compiler = SchemaFieldsCompiler(completion)
    absent = compiler.compile("one", [definition()], [Page()])
    table = compiler.compile("two", [definition()], [Page(text="项目\t限额\n５０,０００元")])
    assert absent.fields[0].state == "absent_explicitly"
    # Punctuation is not erased: the comma in the source cannot be invented away.
    assert table.fields == []
    table = SchemaFieldsCompiler(
        Replay(
            response(
                row(
                    value="50000元",
                    evidence=[evidence(quote="限额50,000元")],
                )
            )
        )
    ).compile("two", [definition()], [Page(text="项目\t限额\n５０,０００元")])
    assert table.fields[0].evidence[0].match == "NORMALIZED"
    assert table.fields[0].evidence[0].quote == "限额50,000元"


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
    output = SchemaFieldsCompiler(Replay(response(row()))).compile("entity", [field], [Page()])
    assert output.pack_id == "test-pack"
    with pytest.raises(CompileError):
        to_candidate(output, display_name="展示名", schema_pack_id="other-pack")
