"""SK-2b Spec §6, §9.3 (RED, written by Claude): withdrawing one method."""

from typing import Any

import pytest

from insurance_harness.bundle.client import Release
from insurance_harness.compilers.methods.withdraw import WithdrawError, withdraw_method
from insurance_harness.contracts.enums import Origin, ReviewMode
from tests.compilers.methods.helpers import (
    METHOD_A,
    METHOD_C,
    FakeModel,
    World,
    candidate,
    compiled,
    full_answer,
    release_from,
    unknown_answer,
)
from tests.ingest.method_helpers import v1

CARDS = ("method_summary", "method_steps", "key_phrases", "applicable_scenario", "cautions")


def published(world: World, answer: Any = full_answer) -> Release:
    """Deck A's and deck C's methods compiled and activated."""
    items = [
        candidate(METHOD_A, world.raw_a, world.hits("k-deck-a")),
        candidate(METHOD_C, world.raw_c, world.hits("k-deck-c")),
    ]
    run = compiled(world, items, FakeModel({METHOD_A: answer, METHOD_C: unknown_answer}))
    assert run.bundle is not None
    return release_from(run.bundle)


def method_id(world: World, name: str) -> str:
    return next(m.method_id for m in world.registry.methods if m.names[0] == name)


@pytest.mark.parametrize("answer", [full_answer, unknown_answer])
def test_withdrawing_removes_only_that_methods_members(answer: Any) -> None:
    world = World()
    active = published(world, answer)
    target, other = method_id(world, METHOD_A), method_id(world, METHOD_C)
    before = world.registry.model_dump_json()
    result = withdraw_method(world.registry, target, active)
    assert world.registry.model_dump_json() == before  # the given registry is not changed
    assert result.bundle is not None and result.bundle.members == []
    assert result.bundle.removals == sorted(
        [*(f"{target}/{card}" for card in CARDS), f"entity/{target}"]
    )
    assert not any(other in slug for slug in result.bundle.removals)
    assert [(p.mode, p.policy_ref) for p in result.bundle.review_plan] == [(ReviewMode.HUMAN, None)]
    assert result.bundle.origin == Origin.COMPILE
    assert result.bundle.base_release_id == active.id
    assert result.bundle.compiler_identity.startswith("sales_methods@")
    entries = {m.method_id: m for m in result.registry.methods}
    assert entries[target].suppressed is True and entries[other].suppressed is False
    kept = entries[target].model_copy(update={"suppressed": False})
    assert kept == next(m for m in world.registry.methods if m.method_id == target)


def test_withdrawing_a_method_without_published_members_only_suppresses_it() -> None:
    world = World()
    published(world)
    result = withdraw_method(world.registry, method_id(world, METHOD_A), None)
    assert result.bundle is None
    assert next(m for m in result.registry.methods if m.names[0] == METHOD_A).suppressed


def test_withdrawing_again_changes_nothing_more() -> None:
    world = World()
    active = published(world)
    target = method_id(world, METHOD_A)
    once = withdraw_method(world.registry, target, active)
    twice = withdraw_method(once.registry, target, active)
    assert twice.registry == once.registry
    assert twice.bundle is not None and once.bundle is not None
    assert twice.bundle.removals == once.bundle.removals


def test_an_unknown_method_or_a_v1_registry_is_refused() -> None:
    world = World()
    active = published(world)
    with pytest.raises(WithdrawError) as raised:
        withdraw_method(world.registry, "sm-" + "0" * 24, active)
    assert raised.value.code == "METHOD_UNKNOWN"
    with pytest.raises(WithdrawError) as raised:
        withdraw_method(v1(), "sm-" + "0" * 24, None)
    assert raised.value.code == "REGISTRY_NOT_V2"


def test_a_withdrawn_method_stays_out_of_later_compiles() -> None:
    world = World()
    active = published(world)
    target = method_id(world, METHOD_A)
    world.registry = withdraw_method(world.registry, target, active).registry
    model = FakeModel({METHOD_A: full_answer, METHOD_C: unknown_answer})
    run = compiled(world, [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))], model, active)
    assert [p["method"]["name"] for p in model.requests] == [METHOD_C]
    statuses = {m["method_id"]: m["status"] for m in run.report["methods"]}
    assert statuses[target] == "retired"
