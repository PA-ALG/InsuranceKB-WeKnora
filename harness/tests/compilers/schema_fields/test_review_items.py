"""RV2a acceptance: what the independent reviewer sees of one compile output (Spec §3.2, §4).

Protected file: written by Claude. Only fields with content (present, absent_explicitly) are
reviewed, in output order. Each carries its definition and its card rules, never card examples:
they name other products and their answers. Its key is the claim's logical key, and a reviewed
field without a definition stops the build.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from insurance_harness.compilers.schema_fields.cards import all_cards, card_payload
from insurance_harness.compilers.schema_fields.claims import claims_from
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.compilers.schema_fields.review_items import logical_key, review_items
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.review.scorer import ReviewItem


class Page:
    document, document_sha256, page = "条款.pdf", "ab" * 32, 1
    text = "第一条 甲为三十日。\n第二条 本合同不设乙。\n"


SOURCE = SegmentedSource([Page()])
# A real card that has examples, and a pack its examples come from.
CARD_KEY = next(key for key, card in all_cards().items() if card.get("examples"))
PACK = all_cards()[CARD_KEY]["examples"][0]["schema_pack_id"]
DEFINITIONS = {
    CARD_KEY: FieldDefinition(
        field_key=CARD_KEY,
        short_title="字段甲",
        description="字段甲的定义",
        value_spec="字段甲的取值规格",
        source_guidance="字段甲的来源指引",
        pack_id=PACK,
    ),
    "term_b": FieldDefinition(
        field_key="term_b", short_title="字段乙", description="字段乙的定义", pack_id=PACK
    ),
}
FIELDS = [
    FieldResult(
        field_key=CARD_KEY,
        state="present",
        value="三十日",
        evidence=SOURCE.evidence(["D1P1S1"]),
        segment_ids=["D1P1S1"],
    ),
    FieldResult(
        field_key="term_b",
        state="absent_explicitly",
        evidence=SOURCE.evidence(["D1P1S2"]),
        segment_ids=["D1P1S2"],
    ),
    # Unknown fields are not reviewed, so they need no definition.
    FieldResult(field_key="term_c", state="unknown"),
]
OUTPUT = CompileOutput(
    pack_id=PACK, entity_id="E1", model="m", fields=FIELDS, cards_version="cards-test"
)


def strings(node: object) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from strings(value)


def keys(node: object) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from keys(value)


def test_only_fields_with_content_are_reviewed_in_output_order() -> None:
    items = review_items(OUTPUT, DEFINITIONS)
    assert all(isinstance(entry, ReviewItem) for entry in items)
    assert [
        (entry.logical_key, entry.title, entry.state, entry.value, entry.quotes) for entry in items
    ] == [
        (
            f"E1/{CARD_KEY}",
            "字段甲",
            "present",
            "三十日",
            tuple(quote.quote for quote in FIELDS[0].evidence),
        ),
        (
            "E1/term_b",
            "字段乙",
            "absent_explicitly",
            None,
            tuple(quote.quote for quote in FIELDS[1].evidence),
        ),
    ]


def test_rules_carry_the_definition_and_card_rules_but_no_examples() -> None:
    first, second = review_items(OUTPUT, DEFINITIONS)
    rules = json.loads(first.rules)
    texts = set(strings(rules))
    assert {"字段甲", "字段甲的定义", "字段甲的取值规格", "字段甲的来源指引"} <= texts
    card = card_payload(DEFINITIONS[CARD_KEY], examples=False)
    assert card is not None
    assert card["definition"] in texts
    assert set(card["excludes"]) <= texts
    assert "examples" not in set(keys(rules))
    for example in all_cards()[CARD_KEY]["examples"]:
        for name in ("product", "value", "reason"):
            if example.get(name):
                assert example[name] not in first.rules
    # A field without a card still gets its definition.
    assert {"字段乙", "字段乙的定义"} <= set(strings(json.loads(second.rules)))
    # Stable text: the same output and definitions give the same request.
    assert [entry.rules for entry in review_items(OUTPUT, DEFINITIONS)] == [
        first.rules,
        second.rules,
    ]


def test_review_keys_are_the_claims_logical_keys() -> None:
    claims = claims_from(OUTPUT, SOURCE, {"条款.pdf": SourceRevision("k-1", 2)})
    by_predicate = {claim.predicate: claim.logical_key for claim in claims}
    items = review_items(OUTPUT, DEFINITIONS)
    assert [entry.logical_key for entry in items] == [
        by_predicate[CARD_KEY],
        by_predicate["term_b"],
    ]
    assert logical_key("E1", "term_b") == by_predicate["term_b"]


def test_a_reviewed_field_without_a_definition_stops_the_build() -> None:
    with pytest.raises(ValueError) as caught:
        review_items(OUTPUT, {CARD_KEY: DEFINITIONS[CARD_KEY]})
    assert str(caught.value) == "DEFINITION_MISSING"
