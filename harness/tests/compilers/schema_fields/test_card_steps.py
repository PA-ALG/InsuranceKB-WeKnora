"""Cards per step: clipped examples teach step one; step two gets the rules only.

Examples come from sibling products of the same type, so a full example value could be
copied into a value instead of the selected text; the value step therefore never sees one.
"""

import json

from insurance_harness.compilers.schema_fields.cards import (
    EXAMPLE_VALUE_CHARS,
    all_cards,
    card_payload,
)
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.prompt import build_value_request
from insurance_harness.evidence.segments import SegmentedSource

PACK = "schemapack_endowment_insurance"


def definition(key: str) -> FieldDefinition:
    return FieldDefinition(field_key=key, short_title=key, description=key, ordinal=0, pack_id=PACK)


def longest_example_field() -> str:
    def longest(key: str) -> int:
        values = [
            e.get("value") or ""
            for e in all_cards()[key].get("examples", [])
            if e["schema_pack_id"] == PACK
        ]
        return max(map(len, values), default=0)

    return max(all_cards(), key=longest)


def test_step_one_examples_are_clipped() -> None:
    key = longest_example_field()
    payload = card_payload(definition(key))
    assert payload is not None
    values = [e["value"] for e in payload["examples"] if e.get("value")]
    assert values and all(len(v) <= EXAMPLE_VALUE_CHARS + len("……（示例截断）") for v in values)
    assert any(v.endswith("……（示例截断）") for v in values)


def test_step_two_carries_rules_without_examples_or_illustrations() -> None:
    key = longest_example_field()
    payload = card_payload(definition(key), examples=False)
    assert payload is not None
    assert "examples" not in payload and "good" not in payload
    assert payload["definition"] == all_cards()[key]["definition"]


class Page:
    document, document_sha256, page, text = "条款.pdf", "a" * 64, 1, "本合同保险期间为一年。"


def test_value_request_never_contains_an_example_value() -> None:
    key = longest_example_field()
    examples = [e["value"] for e in all_cards()[key]["examples"] if e.get("value")]
    source = SegmentedSource([Page()])
    request = build_value_request("1826", [(definition(key), list(source.segments))])
    fields = json.loads(request.user)["schema_fields"]
    assert "examples" not in fields[0]["card"]
    assert not any(value[:40] in request.user for value in examples)
