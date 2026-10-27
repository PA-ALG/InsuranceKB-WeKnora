"""RV6a acceptance: a value that only says nothing is stated is compiled as unknown (§1, §3).

Protected file: written by Claude. The step-two model cannot answer unknown, so it writes
"材料未提及……" for a field step one selected as present. The compiler records such a field
exactly as if step one had chosen unknown, so output, evaluation, scoring and publication agree.
"""

from __future__ import annotations

import json

from insurance_harness.catalog.non_mention_policy import load_non_mention_policy
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.engine import (
    CompileOutput,
    FieldResult,
    SchemaFieldsCompiler,
)


class Page:
    document, document_sha256, page = "条款.pdf", "e" * 64, 1
    text = "本合同等待期为90日。\n本公司提供健康咨询服务。\n"


class Completion:
    model = "recorded-offline"

    def __init__(self, *answers: object) -> None:
        self._answers = [json.dumps(a, ensure_ascii=False) for a in answers]

    def complete(self, *, system: str, user: str) -> str:
        return self._answers.pop(0)


def definition(key: str, ordinal: int) -> FieldDefinition:
    return FieldDefinition(
        field_key=key, short_title=key, description=key, value_spec="文本", ordinal=ordinal
    )


FIELDS = [definition("waiting_period", 0), definition("direct_billing", 1)]


def compile_with(direct_billing_value: str) -> CompileOutput:
    selection = {
        "fields": [
            {
                "ordinal": 0,
                "field_key": "waiting_period",
                "state": "present",
                "segments": ["D1P1S1"],
            },
            {
                "ordinal": 1,
                "field_key": "direct_billing",
                "state": "present",
                "segments": ["D1P1S2"],
            },
        ]
    }
    values = {
        "fields": [
            {"ordinal": 0, "field_key": "waiting_period", "value": "90日"},
            {"ordinal": 1, "field_key": "direct_billing", "value": direct_billing_value},
        ]
    }
    return SchemaFieldsCompiler(Completion(selection, values), batch_size=10, max_calls=5).compile(
        "product", FIELDS, [Page()]
    )


def test_a_value_that_only_says_nothing_is_stated_is_compiled_as_unknown() -> None:
    output = compile_with("材料未提及医疗费用直付或理赔款预付服务。")
    by_key = {field.field_key: field for field in output.fields}
    assert by_key["direct_billing"] == FieldResult(field_key="direct_billing", state="unknown"), (
        "the same result as step one choosing unknown: no value, evidence or segments"
    )
    assert by_key["waiting_period"].state == "present"
    assert by_key["waiting_period"].value == "90日"
    assert by_key["waiting_period"].segment_ids == ["D1P1S1"]
    assert output.dropped_fields == []


def test_a_value_with_content_stays_present() -> None:
    output = compile_with("1. 健康咨询：本公司提供健康咨询服务。2. 次数：材料未载明。")
    by_key = {field.field_key: field for field in output.fields}
    assert by_key["direct_billing"].state == "present"
    assert by_key["direct_billing"].segment_ids == ["D1P1S2"]


def test_the_output_records_the_rule_version_and_older_outputs_still_load() -> None:
    output = compile_with("材料未载明。")
    assert output.non_mention_version == load_non_mention_policy().version
    raw = output.model_dump(mode="json")
    del raw["non_mention_version"]
    assert CompileOutput.model_validate(raw).non_mention_version is None, (
        "outputs written before RV6a still load"
    )
