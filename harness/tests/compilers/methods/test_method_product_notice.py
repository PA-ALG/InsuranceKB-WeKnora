"""#516 review R1 (written by Claude): the product-information notice follows the Claims in force.

The notice and its routing are decided on the Claims the method has after this run's change
decisions: a kept or conflicting old Claim stays in Active, and so does its notice.
"""

from typing import Any

from insurance_harness.bundle.client import Release
from insurance_harness.compilers.methods.compile import MethodRun
from insurance_harness.contracts.knowledge import Entity
from tests.compilers.methods.helpers import (
    FakeModel,
    World,
    candidate,
    compiled,
    paragraph_ref,
    release_from,
    unknown_answer,
)

NAME = "重疾险销售技巧"
AMOUNT = "保额50万元起步"
LISTEN = "先听客户怎么说"


def phrase(text: str, material: str) -> Any:
    def build(payload: dict[str, Any]) -> dict[str, Any]:
        answered = unknown_answer(payload)
        item = {"text": text, "refs": [paragraph_ref(payload, "讲解关键句", material)]}
        answered["predicates"][2] = {"predicate": "key_phrases", "state": "present",
                                     "items": [item]}
        return answered

    return build


def first(world: World) -> Release:
    raw = world.add("k-deck-p", "重疾险话术.pptx", "9" * 64, [(NAME, "讲解关键句：" + AMOUNT)])
    run = compiled(world, [candidate(NAME, raw, world.hits("k-deck-p"))],
                   FakeModel({NAME: phrase(AMOUNT, "M1")}))
    assert run.bundle is not None
    return release_from(run.bundle)


def entity_after(run: MethodRun, active: Release) -> Entity:
    projected = release_from(run.bundle, active, 2) if run.bundle else active
    (member,) = [m for m in projected.members if m.kind == "entity"]
    return Entity.model_validate(member.payload)


def report(run: MethodRun) -> dict[str, Any]:
    (method,) = [m for m in run.report["methods"] if m["status"] == "compiled"]
    return method  # type: ignore[no-any-return]


def test_a_kept_claim_keeps_its_notice() -> None:
    world = World()
    active = first(world)
    run = compiled(world, [], FakeModel({NAME: unknown_answer}), active)
    assert report(run)["counts"]["keep"] == 1
    assert entity_after(run, active).identifiers == {"notice": "product_info"}
    assert report(run)["product_info"] is True
    assert "CONTAINS_PRODUCT_INFO" in report(run)["reasons"]


def test_a_conflict_keeps_the_old_claim_and_its_notice() -> None:
    world = World()
    active = first(world)
    raw = world.add("k-deck-q", "重疾险话术二.pptx", "8" * 64, [(NAME, "讲解关键句：" + LISTEN)])
    run = compiled(world, [candidate(NAME, raw, world.hits("k-deck-q"))],
                   FakeModel({NAME: phrase(LISTEN, "M2")}), active)
    assert report(run)["counts"]["conflict"] == 1
    assert entity_after(run, active).identifiers == {"notice": "product_info"}
    assert report(run)["product_info"] is True


def test_a_replaced_claim_takes_the_notice_with_it() -> None:
    world = World()
    active = first(world)
    raw = world.add("k-deck-q", "重疾险话术二.pptx", "8" * 64, [(NAME, "讲解关键句：" + LISTEN)])
    world.set_use("k-deck-p", state="invalidated", invalidated_reason="withdrawn")
    run = compiled(world, [candidate(NAME, raw, world.hits("k-deck-q"))],
                   FakeModel({NAME: phrase(LISTEN, "M1")}), active)
    assert report(run)["counts"]["supersede"] == 1
    assert entity_after(run, active).identifiers == {}
    assert report(run)["product_info"] is False
