"""SK-5 frozen RED: generic signals and source-supported admission, using synthetic inputs."""

import json
from dataclasses import replace
from typing import Any

import pytest
from pydantic import ValidationError

from insurance_harness.catalog.method_cards import load_method_cards, parse_method_cards
from insurance_harness.catalog.review_policy import ReviewPolicy, load_review_policy
from insurance_harness.compilers.methods import compile as compiler
from insurance_harness.compilers.methods.claims import method_content
from insurance_harness.compilers.methods.product_info import product_signals
from insurance_harness.contracts.enums import ReviewMode, SourceClass
from insurance_harness.contracts.knowledge import Claim
from tests.compilers.methods.helpers import (
    METHOD_A,
    FakeModel,
    World,
    candidate,
    candidates_of,
    claims_of,
    full_answer,
    unknown_answer,
)


@pytest.mark.parametrize("term", ["理赔", "赔付", "报销", "给付", "保额", "保费", "免赔", "等待期"])
def test_responsibility_terms_flag_even_negated_statements(term: str) -> None:
    assert "responsibility" in product_signals(f"不能承诺{term}", load_method_cards(), [])


@pytest.mark.parametrize(
    "text", ["智盈", "（智盈）", "比较 智盈 与其他方案", "ＡＢ，另议", "智\ue000盈"]
)
def test_registered_short_aliases_need_token_boundaries(text: str) -> None:
    assert product_signals(text, load_method_cards(), ["智盈", "AB"]) == {"product"}


@pytest.mark.parametrize("text", ["智盈话术", "超智盈", "x智盈", "智盈3", "_智盈", "ABCD", "智盈_"])
def test_short_aliases_never_match_inside_longer_tokens(text: str) -> None:
    assert product_signals(text, load_method_cards(), ["智盈", "AB"]) == set()


def test_existing_number_name_signals_coexist_without_changing_text() -> None:
    text = "恒安 长期保险：不得承诺３０岁后按１０％给付５０万元"
    assert product_signals(text, load_method_cards(), ["恒安长期保险"]) == {
        "product",
        "age",
        "percentage",
        "amount",
        "responsibility",
    }
    assert "不得" in text and "１０％" in text


def test_rules_are_versioned_data_and_do_not_enter_model_request() -> None:
    cards = load_method_cards()
    data = json.loads(cards.model_dump_json())
    assert data["version"] == "2026-11-04.1"
    assert set(data["product_info_terms"]) == {
        "理赔",
        "赔付",
        "报销",
        "给付",
        "保额",
        "保费",
        "免赔",
        "等待期",
    }
    custom = dict(data, product_info_terms=["通用责任演示词"])
    changed = parse_method_cards(json.dumps(custom))
    assert product_signals("通用责任演示词", changed, []) == {"responsibility"}
    world = World()
    candidates = candidates_of(world, [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))])
    models = [FakeModel({METHOD_A: full_answer}), FakeModel({METHOD_A: full_answer})]
    for model, card in zip(models, [cards, changed], strict=True):
        compiler.compile_methods(
            world.registry, candidates, pages=world.reader, port=model, active=None, cards=card
        )
    assert models[0].sent == models[1].sent


def test_only_current_methods_policy_has_source_supported_admission() -> None:
    policy = load_review_policy()
    assert policy.version == "4"
    assert policy.admitted_packs == ["methods_sales"] and policy.thresholds == {}
    assert policy.model_dump()["source_supported_packs"] == ["methods_sales"]
    old = ReviewPolicy(version="3")
    assert old.model_dump()["source_supported_packs"] == []
    for packs in [["other"], ["methods_sales", "methods_sales"]]:
        with pytest.raises(ValidationError):
            ReviewPolicy.model_validate(
                dict(version="4", admitted_packs=["methods_sales"], source_supported_packs=packs)
            )


@pytest.mark.parametrize("answer", [full_answer, unknown_answer])
def test_current_policy_routes_valid_present_and_unknown_without_fake_score(answer: Any) -> None:
    world = World()
    run = compiler.compile_methods(
        world.registry,
        candidates_of(world, [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))]),
        pages=world.reader,
        port=FakeModel({METHOD_A: answer}),
        active=None,
    )
    assert len(claims_of(run.bundle)) == 5
    for claim in claims_of(run.bundle).values():
        assert claim.review.mode == ReviewMode.MACHINE
        assert claim.review.reviewer == "review-policy@4"
        assert claim.review.score is None and claim.review.reviewed_at is None
    assert run.bundle is not None
    assert [(p.mode, p.policy_ref) for p in run.bundle.review_plan] == [
        (ReviewMode.MACHINE, "review-policy@4")
    ]


@pytest.mark.parametrize("override", ["old_policy", "unadmitted", "old_cards", "altered_policy"])
def test_stale_or_unadmitted_policy_and_cards_fail_closed(override: str) -> None:
    world, cards, policy = World(), load_method_cards(), load_review_policy()
    if override == "old_policy":
        policy = ReviewPolicy(version="3")
    elif override == "unadmitted":
        policy = policy.model_copy(update={"admitted_packs": []})
    elif override == "old_cards":
        cards = cards.model_copy(update={"version": "older"})
    else:
        policy = policy.model_copy(update={"source_supported_packs": []})
    run = compiler.compile_methods(
        world.registry,
        candidates_of(world, [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))]),
        pages=world.reader,
        port=FakeModel({METHOD_A: full_answer}),
        active=None,
        cards=cards,
        policy=policy,
    )
    assert all(c.review.mode == ReviewMode.HUMAN for c in claims_of(run.bundle).values())


@pytest.mark.parametrize("fault", ["origin", "locked", "hash", "other_revision", "list_count"])
def test_routing_does_not_admit_a_claim_with_invalid_source_support(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    # Boundary injection after normal original-text verification: routing must not trust a label.
    original = method_content

    def altered(*args: Any, **kwargs: Any) -> Any:
        content = original(*args, **kwargs)
        claims = list(content.claims)
        claim = claims[1]
        update: dict[str, Any] = {}
        if fault == "origin":
            update["origin"] = SourceClass.MODEL_GENERATED
        elif fault == "locked":
            update["expert_lock"] = True
        elif fault == "list_count":
            assert isinstance(claim.value, list)
            update["value"] = [*claim.value, "缺独立证据的项目"]
        else:
            evidence = list(claim.evidence)
            fields = (
                {"quote_sha256": "0" * 64}
                if fault == "hash"
                else {
                    "source_ref": evidence[0].source_ref.replace(":1:", ":99:"),
                }
            )
            evidence[0] = evidence[0].model_copy(update=fields)
            update["evidence"] = evidence
        claims[1] = Claim.model_validate(claim.model_copy(update=update).model_dump())
        return replace(content, claims=tuple(claims))

    monkeypatch.setattr(compiler, "method_content", altered)
    world = World()
    run = compiler.compile_methods(
        world.registry,
        candidates_of(world, [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))]),
        pages=world.reader,
        port=FakeModel({METHOD_A: full_answer}),
        active=None,
    )
    claims = {c.predicate: c for c in claims_of(run.bundle).values()}
    assert claims["method_steps"].review.mode == ReviewMode.HUMAN
    assert claims["method_summary"].review.mode == ReviewMode.MACHINE
