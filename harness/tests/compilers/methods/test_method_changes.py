"""SK-2 Spec §5, §10.5 (RED, written by Claude): change decisions, routing and retired methods."""

from typing import Any

import pytest

from insurance_harness.bundle.client import Release
from insurance_harness.contracts.enums import ReviewKind, ReviewMode
from insurance_harness.ingest.registry import registry_document
from tests.compilers.methods.helpers import (
    METHOD_A,
    METHOD_C,
    FakeModel,
    World,
    candidate,
    claims_of,
    compiled,
    full_answer,
    paragraph_ref,
    release_from,
    unknown_answer,
)

CARDS = ("method_summary", "method_steps", "key_phrases", "applicable_scenario", "cautions")


def published(world: World, answer: Any = full_answer, *items: dict[str, Any]) -> Release:
    """The first run on deck A (and `items`), activated as release 1."""
    first = [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a")), *items]
    run = compiled(world, first, FakeModel({METHOD_A: answer}))
    assert run.bundle is not None
    return release_from(run.bundle)


def method_report(run: Any) -> dict[str, Any]:
    (report,) = run.report["methods"]
    return report  # type: ignore[no-any-return]


def test_the_first_publish_adds_every_claim_and_goes_to_people() -> None:
    world = World()
    run = compiled(
        world,
        [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))],
        FakeModel({METHOD_A: full_answer}),
    )
    report = method_report(run)
    assert report["counts"]["add"] == 5 and report["status"] == "compiled"
    assert run.bundle is not None and run.bundle.base_release_id is None
    assert [(p.mode, p.policy_ref) for p in run.bundle.review_plan] == [(ReviewMode.HUMAN, None)]
    assert all(c.review.mode == ReviewMode.HUMAN for c in claims_of(run.bundle).values())
    assert "PACK_NOT_ADMITTED" in report["reasons"]
    assert run.bundle.compiler_identity.startswith("sales_methods@")


def test_the_same_input_again_changes_nothing() -> None:
    world = World()
    active = published(world)
    before = registry_document(world.registry)
    item = candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))
    run = compiled(world, [item], FakeModel({METHOD_A: full_answer}), active)
    assert run.bundle is None and run.report["no_changes"] is True
    assert method_report(run)["counts"]["unchanged"] == 5
    assert registry_document(run.registry) == before


def test_a_new_material_with_another_value_is_a_conflict_for_people() -> None:
    world = World()
    active = published(world)

    def from_both(payload: dict[str, Any]) -> dict[str, Any]:
        answered = full_answer(payload)
        steps = {"text": "对比新旧保障差异", "refs": [paragraph_ref(payload, "讲解步骤：", "M2")]}
        answered["predicates"][1] = {"predicate": "method_steps", "state": "present",
                                     "items": [steps]}
        return answered

    deck_c = candidate(METHOD_A, world.raw_c, world.hits("k-deck-c"))
    run = compiled(world, [deck_c], FakeModel({METHOD_A: from_both}), active)
    method_id = world.registry.methods[0].method_id
    slug = f"{method_id}/method_steps"
    assert method_report(run)["conflicts"] == [slug]
    assert slug not in claims_of(run.bundle)
    conflicts = [item for item in run.review_items if item.kind == ReviewKind.CONFLICT]
    assert [item.target for item in conflicts] == [slug]


def test_a_withdrawn_source_with_another_link_supersedes() -> None:
    world = World()
    active = published(world, full_answer, candidate(METHOD_A, world.raw_c, world.hits("k-deck-c")))
    world.set_use("k-deck-a", state="invalidated", invalidated_reason="withdrawn")

    def from_c(payload: dict[str, Any]) -> dict[str, Any]:
        steps = {"text": "对比新旧保障差异", "refs": [paragraph_ref(payload, "讲解步骤：", "M1")]}
        answered = unknown_answer(payload)
        answered["predicates"][1] = {"predicate": "method_steps", "state": "present",
                                     "items": [steps]}
        return answered

    run = compiled(world, [], FakeModel({METHOD_A: from_c}), active)
    method_id = world.registry.methods[0].method_id
    assert method_report(run)["counts"]["supersede"] == 5
    claims = claims_of(run.bundle)
    assert claims[f"{method_id}/method_steps"].value == ["对比新旧保障差异"]
    assert all("k-deck-a" not in e.source_ref for c in claims.values() for e in c.evidence)


@pytest.mark.parametrize("answer", [full_answer, unknown_answer])
@pytest.mark.parametrize("why", ["withdrawn", "suppressed"])
def test_a_retired_method_leaves_with_all_its_claims_and_its_entity(why: str, answer: Any) -> None:
    world = World()
    active = published(world, answer)
    method = world.registry.methods[0]
    if why == "withdrawn":  # SK-1 invalidates the record; the method has no valid link left
        world.set_use("k-deck-a", state="invalidated", invalidated_reason="withdrawn")
    else:
        world.registry.methods = [method.model_copy(update={"suppressed": True})]
    model = FakeModel({METHOD_A: answer})
    run = compiled(world, [], model, active)
    assert model.requests == []  # a retired method is not compiled
    assert run.bundle is not None and run.bundle.members == []
    assert run.bundle.removals == sorted(
        [*(f"{method.method_id}/{card}" for card in CARDS), f"entity/{method.method_id}"]
    )
    assert run.bundle.base_release_id == active.id
    assert method_report(run)["status"] == "retired"
    assert [m.method_id for m in run.registry.methods] == [method.method_id]  # the entry stays


def test_a_retired_method_without_published_content_changes_nothing() -> None:
    world = World()
    published(world)
    world.registry.methods = [world.registry.methods[0].model_copy(update={"suppressed": True})]
    run = compiled(world, [], FakeModel({}), None)
    assert run.bundle is None and method_report(run)["status"] == "retired"


def test_another_methods_content_is_never_removed() -> None:
    world = World()
    active = published(world)
    deck_c = candidate(METHOD_C, world.raw_c, world.hits("k-deck-c"))
    second = compiled(world, [deck_c], FakeModel({METHOD_C: unknown_answer}), active)
    assert second.bundle is not None
    both = release_from(second.bundle, active, 2)
    retired = next(m.method_id for m in world.registry.methods if m.names[0] == METHOD_A)
    world.registry.methods = [
        m.model_copy(update={"suppressed": m.method_id == retired}) for m in world.registry.methods
    ]
    run = compiled(world, [], FakeModel({METHOD_C: unknown_answer}), both)
    assert run.bundle is not None and run.bundle.members == []
    assert run.bundle.removals == sorted(
        [*(f"{retired}/{card}" for card in CARDS), f"entity/{retired}"]
    )
