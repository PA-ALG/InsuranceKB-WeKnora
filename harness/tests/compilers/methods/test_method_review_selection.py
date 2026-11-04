"""SK-5 frozen RED: real compile/CLI selection, preserved Active facts and staged handoff."""

import json
from pathlib import Path
from typing import Any, cast

import pytest

from insurance_harness.compilers.methods import cli
from insurance_harness.compilers.methods.compile import MethodRun, compile_methods
from insurance_harness.contracts.enums import ReviewMode
from insurance_harness.contracts.knowledge import Entity
from tests.compilers.methods.helpers import (
    METHOD_A,
    FakeModel,
    World,
    candidate,
    candidates_of,
    claims_of,
    compiled,
    full_answer,
    release_from,
    unknown_answer,
)
from tests.compilers.methods.test_method_compile_live import Live
from tests.compilers.methods.test_method_product_notice import NAME, first, report


def mixed(payload: dict[str, Any]) -> dict[str, Any]:
    answer = full_answer(payload)
    answer["predicates"][0]["items"][0]["text"] = "不能承诺理赔"
    return answer


def select(world: World, route: str, active: Any = None, answer: Any = mixed) -> MethodRun:
    result: MethodRun = cast(Any, compile_methods)(
        world.registry,
        candidates_of(world, [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))]),
        pages=world.reader,
        port=FakeModel({METHOD_A: answer}),
        active=active,
        review_route=route,
    )
    world.registry = result.registry
    return result


def test_mixed_plan_routes_points_not_the_whole_methods_claims_to_people() -> None:
    world = World()
    run = compiled(
        world,
        [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))],
        FakeModel({METHOD_A: mixed}),
    )
    claims = {c.predicate: c for c in claims_of(run.bundle).values()}
    assert claims.pop("method_summary").review.mode == ReviewMode.HUMAN
    assert all(c.review.mode == ReviewMode.MACHINE for c in claims.values())
    assert run.bundle is not None and run.bundle.review_plan[0].mode == ReviewMode.HUMAN
    assert report(run)["product_info"] is True


def test_machine_then_human_is_disjoint_and_projects_only_the_selected_facts() -> None:
    world = World()
    machine = select(world, "machine")
    assert machine.bundle is not None and len(claims_of(machine.bundle)) == 4
    assert all(c.predicate != "method_summary" for c in claims_of(machine.bundle).values())
    (entity,) = [
        Entity.model_validate(m.payload) for m in machine.bundle.members if m.kind == "entity"
    ]
    assert entity.identifiers == {}  # excluded human fact is not published yet
    assert report(machine)["product_info"] is False
    assert machine.report["review_route"] == "machine"
    active = release_from(machine.bundle)
    human = select(world, "human", active)
    assert human.bundle is not None and human.bundle.base_release_id == active.id
    assert [c.predicate for c in claims_of(human.bundle).values()] == ["method_summary"]
    assert human.bundle.review_plan[0].mode == ReviewMode.HUMAN
    assert report(human)["product_info"] is True
    (entity,) = [
        Entity.model_validate(m.payload) for m in human.bundle.members if m.kind == "entity"
    ]
    assert entity.identifiers == {"notice": "product_info"}
    assert set(claims_of(machine.bundle)).isdisjoint(claims_of(human.bundle))
    published = release_from(human.bundle, active, 2)
    assert select(world, "all", published).bundle is None


def test_human_selection_on_a_clean_method_does_not_create_a_metadata_only_package() -> None:
    world = World()
    assert select(world, "human", answer=full_answer).bundle is None


def test_machine_selection_keeps_notice_of_an_existing_product_fact() -> None:
    world = World()
    active = first(world)

    # A new field can be machine-eligible while a KEEP leaves another field's old notice intact.
    def changed(payload: dict[str, Any]) -> dict[str, Any]:
        answer = unknown_answer(payload)
        first_ref = payload["paragraphs"].splitlines()[0].split(" ", 1)[0]
        answer["predicates"][0] = {
            "predicate": "method_summary",
            "state": "present",
            "items": [{"text": "先听客户表达", "refs": [first_ref]}],
        }
        return answer

    run: MethodRun = cast(Any, compile_methods)(
        world.registry,
        candidates_of(world, []),
        pages=world.reader,
        port=FakeModel({NAME: changed}),
        active=active,
        review_route="machine",
    )
    assert run.bundle is not None and len(claims_of(run.bundle)) == 1
    assert report(run)["counts"]["keep"] == 1 and report(run)["product_info"] is True
    projected = release_from(run.bundle, active, 2)
    entity = next(Entity.model_validate(m.payload) for m in projected.members if m.kind == "entity")
    assert entity.identifiers == {"notice": "product_info"}


def test_retirements_are_human_and_leave_machine_selection_empty() -> None:
    world = World()
    original = select(world, "all", answer=full_answer)
    assert original.bundle is not None
    active = release_from(original.bundle)
    world.registry.methods = [
        m.model_copy(update={"suppressed": True}) for m in world.registry.methods
    ]
    assert select(world, "machine", active, full_answer).bundle is None
    human = select(world, "human", active, full_answer)
    assert human.bundle is not None and len(human.bundle.removals) == 6
    assert human.bundle.members == []


def test_old_fact_to_unknown_upgrade_still_requires_people() -> None:
    world = World()
    original = select(world, "all", answer=full_answer)
    assert original.bundle is not None
    active = release_from(original.bundle)
    members = []
    for member in active.members:
        payload = dict(member.payload)
        if member.kind == "claim":
            payload["provenance"] = dict(payload["provenance"], compiler_version="older")
        members.append(member.model_copy(update={"payload": payload}))
    active = active.model_copy(update={"members": members})
    assert select(world, "machine", active, unknown_answer).bundle is None
    human = select(world, "human", active, unknown_answer)
    assert len(claims_of(human.bundle)) == 5
    assert report(human)["counts"]["upgrade"] == 5


def test_mixed_live_is_rejected_before_plan_registry_or_submit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    live = Live(tmp_path, monkeypatch, World(), answers={METHOD_A: mixed})
    before = live.registry.read_bytes()
    status, summary = live.main(capsys)
    assert (status, summary) == (2, {"stopped": "REVIEW_SELECTION_REQUIRED"})
    assert live.registry.read_bytes() == before and live.platform.submitted == []
    assert not (live.run_root / "report.json").exists()


def test_cli_selection_reuses_verified_answers_without_sending_and_only_submits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    live = Live(tmp_path, monkeypatch, World(), answers={METHOD_A: mixed})
    answers = {p.name: p.read_bytes() for p in live.responses.iterdir() if p.is_file()}
    argv = [
        "compile",
        "--registry",
        str(live.registry),
        "--candidates",
        str(live.candidates),
        "--responses",
        str(live.responses),
        "--run-root",
        str(live.run_root),
        "--review-route",
        "machine",
        "--live",
    ]
    assert cli.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["submitted"] == "new"
    assert len(claims_of(live.platform.submitted[0])) == 4
    assert live.order == [(True, True)]
    assert cli.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["submitted"] == "already"
    assert len(live.platform.submitted) == 1
    assert {p.name: p.read_bytes() for p in live.responses.iterdir() if p.is_file()} == answers
