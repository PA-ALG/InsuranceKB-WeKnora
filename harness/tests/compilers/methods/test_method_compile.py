"""SK-2 Spec §4, §10.3, §10.4 (RED, written by Claude): method values, evidence and labels."""

import json
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from insurance_harness.catalog.method_cards import load_method_cards
from insurance_harness.compilers.methods.prompt import METHOD_PROTOCOL_VERSION
from insurance_harness.contracts.enums import (
    ClaimState,
    LocatorKind,
    ReviewKind,
    ReviewMode,
    SourceClass,
    UnknownReason,
)
from insurance_harness.contracts.knowledge import Entity
from tests.compilers.methods.helpers import (
    METHOD_A,
    METHOD_C,
    SHA_A,
    SHA_B,
    FakeModel,
    World,
    candidate,
    claims_of,
    compiled,
    full_answer,
    paragraph_ref,
    unknown_answer,
)
from tests.ingest.method_helpers import ZYBH, nursing_entry

CARDS = ("method_summary", "method_steps", "key_phrases", "applicable_scenario", "cautions")


def entity_of(run: Any, method_id: str) -> Entity:
    member = next(m for m in run.bundle.members if m.logical_slug == f"entity/{method_id}")
    return Entity.model_validate(member.payload)


def report_of(run: Any, method_id: str) -> dict[str, Any]:
    return next(m for m in run.report["methods"] if m["method_id"] == method_id)


def answer(**predicates: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """An answer whose cards are `predicates` (functions of the payload); others unknown."""

    def build(payload: dict[str, Any]) -> dict[str, Any]:
        rows = []
        for card in CARDS:
            items = predicates[card](payload) if card in predicates else None
            rows.append(
                {"predicate": card, "state": "present", "items": items}
                if items is not None
                else {"predicate": card, "state": "unknown"}
            )
        labels = predicates["labels"](payload) if "labels" in predicates else []
        return {"predicates": rows, "labels": labels}

    return build


def deck_a(world: World) -> dict[str, Any]:
    return candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))


def test_an_office_method_compiles_with_list_evidence_aligned_item_by_item() -> None:
    world = World()
    run = compiled(world, [deck_a(world)], FakeModel({METHOD_A: full_answer}))
    method = run.registry.methods[0]
    claims = claims_of(run.bundle)
    assert sorted(claims) == sorted(f"{method.method_id}/{card}" for card in CARDS)
    steps = claims[f"{method.method_id}/method_steps"]
    assert steps.value == ["了解客户家庭结构", "分析家庭责任与缺口"]
    assert len(steps.evidence) == 2
    slide = world.decks["k-deck-a"][1]
    for item, evidence in zip(steps.value, steps.evidence, strict=True):
        assert item in evidence.quote
        assert evidence.locator.kind == LocatorKind.PPTX_SHAPE and evidence.locator.slide == 2
        assert evidence.locator.start is not None and evidence.locator.end is not None
        assert slide.text[evidence.locator.start : evidence.locator.end] == evidence.quote
        assert evidence.source_ref == f"source:v1:k-deck-a:1:{SHA_A}"
    cards = load_method_cards()
    for claim in claims.values():
        assert claim.claim_id == claim.logical_key and claim.subject_ref == method.method_id
        assert claim.product_version_ref is None
        assert claim.origin == SourceClass.SOURCE_SUPPORTED
        assert claim.provenance.compiler == "sales_methods"
        assert claim.provenance.compiler_version == (
            f"{cards.version}+method:{METHOD_PROTOCOL_VERSION}"
        )
        assert claim.provenance.model == "fake-model"
        assert claim.state == ClaimState.PRESENT
        assert all(item.access_scope == "space" for item in claim.evidence)
    assert run.bundle is not None
    assert all(member.access_scope == "space" for member in run.bundle.members)
    summary = claims[f"{method.method_id}/method_summary"]
    assert summary.value == "按家庭结构分析保障需求" and len(summary.evidence) == 1
    entity = entity_of(run, method.method_id)
    assert entity.entity_type == "sales_method" and entity.names == [METHOD_A]
    assert entity.owner_module == "harness/sales_methods" and entity.identifiers == {}
    assert entity.classification_labels == sorted(
        ["critical_illness_insurance", "medical_insurance", "sales_stage:needs_analysis"]
    )


def test_a_pdf_method_cites_text_spans_of_the_page() -> None:
    world = World()

    def ref(payload: dict[str, Any], needle: str) -> list[str]:
        return [paragraph_ref(payload, needle)]

    pdf_answer = answer(
        method_summary=lambda p: [{"text": "先了解家庭结构", "refs": ref(p, "讲解步骤一")}],
        method_steps=lambda p: [{"text": "了解客户家庭结构", "refs": ref(p, "讲解步骤一")}],
        key_phrases=lambda p: [{"text": "保障先于理财", "refs": ref(p, "讲解关键句")}],
        applicable_scenario=lambda p: [{"text": "重疾险客户", "refs": ref(p, "适用于")}],
    )
    pdf = candidate(METHOD_A, world.raw_p, world.hits("k-pdf-a"))
    run = compiled(world, [pdf], FakeModel({METHOD_A: pdf_answer}))
    method_id = run.registry.methods[0].method_id
    claims = claims_of(run.bundle)
    phrase = claims[f"{method_id}/key_phrases"]
    (evidence,) = phrase.evidence
    page = world.decks["k-pdf-a"][0]
    assert evidence.locator.kind == LocatorKind.PDF_TEXT_SPAN and evidence.locator.page == 1
    assert evidence.locator.start is not None and evidence.locator.end is not None
    assert page.text[evidence.locator.start : evidence.locator.end] == evidence.quote
    assert evidence.source_ref == f"source:v1:k-pdf-a:1:{SHA_B}"
    cautions = claims[f"{method_id}/cautions"]
    assert cautions.state == ClaimState.UNKNOWN
    assert cautions.unknown_reason == UnknownReason.NOT_IN_MATERIAL


def test_items_failing_their_checks_are_dropped_with_codes() -> None:
    world = World()

    def deck(payload: dict[str, Any], needle: str) -> str:
        return paragraph_ref(payload, needle, "M1")

    def pdf(payload: dict[str, Any], needle: str) -> str:
        return paragraph_ref(payload, needle, "M2")

    checked = answer(
        method_summary=lambda p: [
            {"text": "了解家庭", "refs": [deck(p, "讲解步骤一"), pdf(p, "讲解步骤一")]}
        ],
        method_steps=lambda p: [
            {"text": "了解客户家庭结构", "refs": [deck(p, "讲解步骤一")]},
            {"text": "不存在的步骤", "refs": ["M9P1S1"]},
            {"text": "跨材料的步骤", "refs": [deck(p, "讲解步骤一"), pdf(p, "讲解步骤一")]},
            {"text": "跨两个文本框", "refs": [deck(p, "讲解步骤一"), deck(p, "讲解步骤二")]},
        ],
        key_phrases=lambda p: [
            {"text": "保障先于理财", "refs": [pdf(p, "讲解关键句")]},
            {"text": "先管风险再理财", "refs": [deck(p, "讲解关键句")]},
        ],
        cautions=lambda p: [{"text": "不要承诺", "refs": ["M1P3S9"]}],
    )
    items = [deck_a(world), candidate(METHOD_A, world.raw_p, world.hits("k-pdf-a"))]
    run = compiled(world, items, FakeModel({METHOD_A: checked}))
    method_id = run.registry.methods[0].method_id
    claims = claims_of(run.bundle)
    assert claims[f"{method_id}/method_steps"].value == ["了解客户家庭结构"]
    phrase = claims[f"{method_id}/key_phrases"]
    assert phrase.value == ["保障先于理财"]
    assert phrase.evidence[0].source_ref == f"source:v1:k-pdf-a:1:{SHA_B}"
    for card in ("method_summary", "cautions"):
        assert claims[f"{method_id}/{card}"].unknown_reason == UnknownReason.EXTRACTION_FAILED
    scenario = claims[f"{method_id}/applicable_scenario"]
    assert scenario.unknown_reason == UnknownReason.NOT_IN_MATERIAL
    assert report_of(run, method_id)["dropped"] == {
        "ITEM_SPANS_MULTIPLE": 1,
        "PHRASE_NOT_VERBATIM": 1,
        "REFS_ACROSS_MATERIALS": 2,
        "REF_OUTSIDE_PARAGRAPHS": 2,
    }


def test_a_text_value_may_cite_paragraphs_apart() -> None:
    world = World()
    spread = answer(
        method_summary=lambda p: [
            {
                "text": "先了解再促成",
                "refs": [paragraph_ref(p, "讲解步骤一"), paragraph_ref(p, "促成")],
            }
        ]
    )
    run = compiled(world, [deck_a(world)], FakeModel({METHOD_A: spread}))
    method_id = run.registry.methods[0].method_id
    summary = claims_of(run.bundle)[f"{method_id}/method_summary"]
    assert [e.locator.slide for e in summary.evidence] == [2, 4]


def test_an_unknown_answer_publishes_no_value_and_the_record_labels() -> None:
    world = World()
    run = compiled(world, [deck_a(world)], FakeModel({METHOD_A: unknown_answer}))
    method_id = run.registry.methods[0].method_id
    claims = claims_of(run.bundle)
    assert {c.unknown_reason for c in claims.values()} == {UnknownReason.NOT_IN_MATERIAL}
    assert all(c.value is None and c.evidence == [] for c in claims.values())
    assert entity_of(run, method_id).classification_labels == [
        "critical_illness_insurance",
        "medical_insurance",
    ]


def test_evidence_only_ever_cites_the_original_source() -> None:
    world = World()
    run = compiled(world, [deck_a(world)], FakeModel({METHOD_A: full_answer}))
    assert run.bundle is not None
    text = run.bundle.model_dump_json()
    assert "copy-" not in text
    refs = [e.source_ref for c in claims_of(run.bundle).values() for e in c.evidence]
    assert refs and all(ref == f"source:v1:k-deck-a:1:{SHA_A}" for ref in refs)


def _drop_card(raw: dict[str, Any]) -> dict[str, Any]:
    return {**raw, "predicates": raw["predicates"][1:]}


def _swap_cards(raw: dict[str, Any]) -> dict[str, Any]:
    rows = raw["predicates"]
    return {**raw, "predicates": [rows[1], rows[0], *rows[2:]]}


def _extra_key(raw: dict[str, Any]) -> dict[str, Any]:
    return {**raw, "note": "x"}


def _two_texts(raw: dict[str, Any]) -> dict[str, Any]:
    rows = list(raw["predicates"])
    item = {"text": "转保", "refs": ["M1P1S1"]}
    rows[0] = {"predicate": "method_summary", "state": "present", "items": [item, item]}
    return {**raw, "predicates": rows}


def _present_without_items(raw: dict[str, Any]) -> dict[str, Any]:
    rows = list(raw["predicates"])
    rows[1] = {"predicate": "method_steps", "state": "present", "items": []}
    return {**raw, "predicates": rows}


def _unknown_with_items(raw: dict[str, Any]) -> dict[str, Any]:
    rows = list(raw["predicates"])
    item = {"text": "转保", "refs": ["M1P1S1"]}
    rows[1] = {"predicate": "method_steps", "state": "unknown", "items": [item]}
    return {**raw, "predicates": rows}


def _other_state(raw: dict[str, Any]) -> dict[str, Any]:
    rows = list(raw["predicates"])
    rows[1] = {"predicate": "method_steps", "state": "absent_explicitly"}
    return {**raw, "predicates": rows}


def _item_extra_key(raw: dict[str, Any]) -> dict[str, Any]:
    rows = list(raw["predicates"])
    item = {"text": "转保", "refs": ["M1P1S1"], "score": 1}
    rows[1] = {"predicate": "method_steps", "state": "present", "items": [item]}
    return {**raw, "predicates": rows}


def _labels_not_list(raw: dict[str, Any]) -> dict[str, Any]:
    return {**raw, "labels": "sales_stage:transfer"}


@pytest.mark.parametrize(
    "mutate",
    [
        None,
        _drop_card,
        _swap_cards,
        _extra_key,
        _two_texts,
        _present_without_items,
        _unknown_with_items,
        _other_state,
        _item_extra_key,
        _labels_not_list,
    ],
)
def test_a_malformed_answer_skips_only_its_method(
    mutate: Callable[[dict[str, Any]], dict[str, Any]] | None,
) -> None:
    world = World()
    answers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {METHOD_A: full_answer}
    if mutate is not None:
        broken = mutate
        answers[METHOD_C] = lambda payload: broken(unknown_answer(payload))
    items = [deck_a(world), candidate(METHOD_C, world.raw_c, world.hits("k-deck-c"))]
    run = compiled(world, items, FakeModel(answers))
    by_name = {m.names[0]: m.method_id for m in run.registry.methods}
    skipped = report_of(run, by_name[METHOD_C])
    assert (skipped["status"], skipped["code"]) == ("skipped", "VALUE_RESPONSE_INVALID")
    assert report_of(run, by_name[METHOD_A])["status"] == "compiled"
    slugs = [member.logical_slug for member in run.bundle.members] if run.bundle else []
    assert slugs and not any(by_name[METHOD_C] in slug for slug in slugs)


def test_labels_outside_the_offered_stages_or_paragraphs_are_dropped() -> None:
    world = World()

    def labels(payload: dict[str, Any]) -> list[dict[str, Any]]:
        step = paragraph_ref(payload, "讲解步骤一")
        return [
            {"label": "life_stage:family_growth", "refs": [step]},
            {"label": "medical_insurance", "refs": [step]},  # categories are the record's
            {"label": "sales_stage:unknown", "refs": [step]},
            {"label": "sales_stage:closing", "refs": ["M1P9S9"]},
        ]

    run = compiled(world, [deck_a(world)], FakeModel({METHOD_A: answer(labels=labels)}))
    method_id = run.registry.methods[0].method_id
    assert entity_of(run, method_id).classification_labels == [
        "critical_illness_insurance",
        "life_stage:family_growth",
        "medical_insurance",
    ]
    report = report_of(run, method_id)
    assert report["dropped"] == {"LABEL_INVALID": 3} and report["labels"] == 1


def test_the_request_names_the_method_cards_labels_and_only_its_paragraphs() -> None:
    world = World()
    one, two = world.block("k-deck-a", "讲解步骤一"), world.block("k-deck-a", "促成")
    model = FakeModel({})
    compiled(world, [candidate(METHOD_A, world.raw_a, [one, two])], model)
    (payload,) = model.requests
    assert payload["method"]["name"] == METHOD_A
    assert [card["predicate"] for card in payload["cards"]] == list(CARDS)
    assert payload["paragraphs"].splitlines() == [
        f"M1{one} 讲解步骤一：了解客户家庭结构",
        f"M1{two} 促成：约定下次见面时间",
    ]
    offered = [label["label"] for label in payload["labels"]]
    assert offered and all(label.startswith(("life_stage:", "sales_stage:")) for label in offered)
    assert "主讲人" not in json.dumps(payload, ensure_ascii=False)
    assert "copy-" not in json.dumps(payload, ensure_ascii=False)


SIGNALS: Mapping[str, str] = {
    "amount": "保额50万元起步",
    "percentage": "保费只占收入10%",
    "age": "适合30至45周岁客户",
    "product": ZYBH + "保障长期护理",
}


@pytest.mark.parametrize("signal", sorted(SIGNALS))
def test_product_information_routes_to_people_with_a_lint_item(signal: str) -> None:
    world = World()
    world.registry.products = {"p-nursing": nursing_entry()}
    phrase = SIGNALS[signal]
    name = "重疾险销售技巧"
    raw = world.add("k-deck-p", "重疾险话术.pptx", "9" * 64, [(name, "讲解关键句：" + phrase)])
    said = answer(
        key_phrases=lambda p: [{"text": phrase, "refs": [paragraph_ref(p, "讲解关键句")]}]
    )
    items = [candidate(name, raw, world.hits("k-deck-p"))]
    run = compiled(world, items, FakeModel({name: said}))
    method_id = run.registry.methods[0].method_id
    slug = f"{method_id}/key_phrases"
    assert claims_of(run.bundle)[slug].value == [phrase]  # kept verbatim, never edited
    assert entity_of(run, method_id).identifiers == {"notice": "product_info"}
    lint = [item for item in run.review_items if item.kind == ReviewKind.LINT]
    assert [item.target for item in lint] == [slug]
    report = report_of(run, method_id)
    assert report["product_info"] is True and "CONTAINS_PRODUCT_INFO" in report["reasons"]
    assert run.bundle is not None and run.bundle.review_plan[0].mode == ReviewMode.HUMAN


def test_a_method_without_product_information_has_no_notice() -> None:
    world = World()
    run = compiled(world, [deck_a(world)], FakeModel({METHOD_A: full_answer}))
    method_id = run.registry.methods[0].method_id
    assert entity_of(run, method_id).identifiers == {}
    assert not [item for item in run.review_items if item.kind == ReviewKind.LINT]
    report = report_of(run, method_id)
    assert report["product_info"] is False and "CONTAINS_PRODUCT_INFO" not in report["reasons"]
    assert "PACK_NOT_ADMITTED" in report["reasons"]
