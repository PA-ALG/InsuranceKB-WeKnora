"""S3e-3 acceptance: concept inputs, the strict output shape and the deterministic checks (§4.1).

Protected file: written by Claude. User ruling 2026-10-18: a cross-product summary may state product
facts only as references to published claims whose values hold its numbers; the general text
names no product. A concept is a field two or more products state; unknown claims are left out.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from insurance_harness.bundle.client import Release
from insurance_harness.compilers.concepts.checks import check_concept
from insurance_harness.compilers.concepts.synthesis import (
    ConceptDraft,
    ConceptOutputError,
    build_request,
    concept_inputs,
    parse_concepts,
)

NAMES = {"甲产品", "乙产品", "丙产品", "P1", "P2", "P3"}
A, B, C = "P1/cooling_off_period", "P2/cooling_off_period", "P3/cooling_off_period"


def test_concepts_are_fields_two_products_state_with_their_facts(release: Release) -> None:
    inputs = {concept.key: concept for concept in concept_inputs(release)}
    assert list(inputs) == ["cooling_off_period", "premium_grace_period"]
    cooling = inputs["cooling_off_period"]
    assert cooling.title == "犹豫期"
    assert cooling.description.startswith("投保人收到合同后")
    assert [(f.entity_id, f.name, f.group, f.state, f.slug, f.digest) for f in cooling.facts] == [
        ("P1", "甲产品", "医疗险", "present", A, "a" * 64),
        ("P2", "乙产品", "医疗险", "present", B, "b" * 64),
        ("P3", "丙产品", "重疾险", "present", C, "c" * 64),
    ]
    grace = inputs["premium_grace_period"]
    assert [(f.entity_id, f.state, f.value) for f in grace.facts] == [
        ("P1", "present", "60日。"),
        ("P3", "absent_explicitly", None),
    ]


def test_the_request_carries_the_facts_and_nothing_of_the_compile(release: Release) -> None:
    system, user = build_request(concept_inputs(release)[:1])
    assert "statements" in system and "refs" in system
    data = json.loads(user)
    [concept] = data["concepts"]
    assert concept["key"] == "cooling_off_period" and concept["title"] == "犹豫期"
    assert [fact["slug"] for fact in concept["facts"]] == [A, B, C]
    assert concept["facts"][2]["value"] == "自签收本合同之日起２０日。"
    assert "原文" not in user  # evidence quotes are not review input


def answer(*concepts: dict[str, Any]) -> str:
    return json.dumps({"concepts": list(concepts)}, ensure_ascii=False)


def drafted(key: str = "cooling_off_period", **changes: Any) -> dict[str, Any]:
    return {
        "key": key,
        "definition": "投保人签收合同后可以无损失解除合同的期间。",
        "explanation": "犹豫期是签收合同后的冷静期，期间解除合同可退还已交保费。",
        "statements": [{"text": "甲产品与乙产品的犹豫期为15日。", "refs": [A, B]}],
        **changes,
    }


def test_a_valid_output_parses_into_one_draft_per_concept(release: Release) -> None:
    batch = concept_inputs(release)
    drafts = parse_concepts(answer(drafted(), drafted("premium_grace_period")), batch)
    assert set(drafts) == {"cooling_off_period", "premium_grace_period"}
    assert drafts["cooling_off_period"].statements[0].refs == (A, B)


@pytest.mark.parametrize(
    "text",
    [
        "不是 JSON",
        answer(drafted()),  # one concept of the batch is missing
        answer(drafted(), drafted("premium_grace_period"), drafted("waiting_period")),
        answer(drafted(), drafted()),
        answer(drafted(statements="一句话"), drafted("premium_grace_period")),
        answer(drafted(definition=3), drafted("premium_grace_period")),
        '{"concepts": [], "concepts": []}',
    ],
    ids=[
        "not json",
        "missing",
        "extra",
        "twice",
        "statements shape",
        "definition type",
        "dup member",
    ],
)
def test_any_other_output_is_refused_whole(release: Release, text: str) -> None:
    with pytest.raises(ConceptOutputError) as refused:
        parse_concepts(text, concept_inputs(release))
    assert refused.value.code == "CONCEPT_OUTPUT_INVALID"


def check(release: Release, **changes: Any) -> list[str]:
    cooling = concept_inputs(release)[0]
    draft = parse_concepts(
        answer(drafted(**changes), drafted("premium_grace_period")), concept_inputs(release)
    )
    return check_concept(draft["cooling_off_period"], cooling, NAMES)


def statement(text: str, *refs: str) -> dict[str, Any]:
    return {"text": text, "refs": list(refs)}


def test_a_well_founded_draft_passes(release: Release) -> None:
    statements = [
        statement("多数产品为15日，丙产品为20日。", A, B, C),
        statement("各产品在犹豫期内解除合同均可退还保费。", A, B, C),
        statement("乙产品犹豫期为１５日。", B),
    ]
    assert check(release, statements=statements) == []


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"definition": "定" * 121}, "DEFINITION_LENGTH"),
        ({"explanation": "解" * 401}, "EXPLANATION_LENGTH"),
        ({"statements": [statement("句" * 201, A)]}, "STATEMENT_LENGTH"),
        ({"explanation": "甲产品的犹豫期较长。"}, "PRODUCT_NAMED"),
        ({"definition": "P3 所称的犹豫期。"}, "PRODUCT_NAMED"),
        ({"statements": [statement("犹豫期为15日。", "P9/cooling_off_period")]}, "REF_UNKNOWN"),
        ({"statements": [statement("甲产品犹豫期为30日。", A)]}, "NUMBER_UNSUPPORTED"),
        ({"statements": [statement("两款产品均为15日。", A, C)]}, "NUMBER_UNMATCHED_REF"),
        ({"statements": []}, "STATEMENT_COUNT"),
        ({"statements": [statement("各产品可退保。", A)] * 7}, "STATEMENT_COUNT"),
    ],
    ids=[
        "long definition",
        "long explanation",
        "long statement",
        "named in explanation",
        "code in definition",
        "unknown ref",
        "number not in claims",
        "ref without the number",
        "no statement",
        "too many statements",
    ],
)
def test_each_check_reports_its_code(release: Release, changes: dict[str, Any], code: str) -> None:
    assert code in check(release, **changes)


def test_a_draft_is_a_plain_record() -> None:
    assert ConceptDraft.__dataclass_fields__  # frozen dataclass, built only by parse_concepts
