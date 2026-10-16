"""Compile output records the field card version its requests were built from (S4g §2.2)."""

from __future__ import annotations

import json

from insurance_harness.compilers.schema_fields.cards import cards_version
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.engine import CompileOutput, SchemaFieldsCompiler


class Page:
    document, document_sha256, page, text = "条款.pdf", "e" * 64, 1, "本合同等待期为90日。\n"


class Completion:
    model = "recorded-offline"

    def __init__(self, *answers: object) -> None:
        self._answers = [json.dumps(a, ensure_ascii=False) for a in answers]

    def complete(self, *, system: str, user: str) -> str:
        return self._answers.pop(0)


def test_the_output_records_the_card_version_it_was_compiled_with() -> None:
    definition = FieldDefinition(
        field_key="waiting_period",
        short_title="等待期",
        description="等待期",
        value_spec="文本",
        ordinal=0,
    )
    selection = {
        "fields": [
            {
                "ordinal": 0,
                "field_key": "waiting_period",
                "state": "present",
                "segments": ["D1P1S1"],
            }
        ]
    }
    values = {"fields": [{"ordinal": 0, "field_key": "waiting_period", "value": "90日"}]}
    output = SchemaFieldsCompiler(
        Completion(selection, values), batch_size=10, max_calls=5
    ).compile("product", [definition], [Page()])
    assert output.cards_version == cards_version()
    raw = output.model_dump(mode="json")
    del raw["cards_version"]
    assert CompileOutput.model_validate(raw).cards_version is None, (
        "outputs written before S4g still load"
    )
