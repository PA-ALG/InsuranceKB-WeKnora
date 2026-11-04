"""Additional SK-5 implementation controls: registry aliases, legacy requests and mixed removals."""

from pathlib import Path
from typing import Any

import pytest

from insurance_harness.catalog.method_cards import load_method_cards
from insurance_harness.catalog.review_policy import load_review_policy
from insurance_harness.changes.types import Verdict
from insurance_harness.compilers.methods.compile import compile_methods
from insurance_harness.compilers.methods.responses import LedgerAnswers
from insurance_harness.compilers.methods.review import claim_route
from insurance_harness.compilers.methods.values import method_values
from insurance_harness.contracts.enums import ReviewMode, UnknownReason
from tests.compilers.methods.helpers import (
    METHOD_A,
    METHOD_C,
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
from tests.compilers.methods.values_helpers import FakeProvider, install, stage_config
from tests.ingest.method_helpers import nursing_entry


@pytest.mark.parametrize(
    ("alias", "value", "flagged"),
    [
        ("晨曦", "请说明（晨曦）", True),
        ("晨曦", "晨曦式访谈法", False),
        ("安心长护计划", "说明安心 长护计划", True),
    ],
)
def test_compile_reads_all_approved_names_from_registry(
    alias: str, value: str, flagged: bool
) -> None:
    world = World()
    product = nursing_entry()
    world.registry.products = {
        "p-nursing": product.model_copy(update={"names": [*product.names, alias]})
    }

    def answer(payload: dict[str, Any]) -> dict[str, Any]:
        data = full_answer(payload)
        data["predicates"][0]["items"][0]["text"] = value
        return data

    run = compiled(
        world,
        [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))],
        FakeModel({METHOD_A: answer}),
    )
    summary = next(c for c in claims_of(run.bundle).values() if c.predicate == "method_summary")
    assert (summary.review.mode == ReviewMode.HUMAN) is flagged
    assert summary.value == value
    assert run.report["methods"][0]["product_info"] is flagged


def test_previous_card_version_saved_request_replays_after_rule_only_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World()
    candidates = candidates_of(world, [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))])
    old = load_method_cards().model_copy(
        update={"version": "2026-11-01.1", "product_info_terms": ()}
    )
    provider = FakeProvider({METHOD_A: full_answer})
    install(monkeypatch, provider)
    method_values(
        world.registry,
        candidates,
        pages=world.reader,
        root=tmp_path,
        config=stage_config(),
        max_sent=1,
        cards=old,
    )
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    created = install(monkeypatch, None)
    run = compile_methods(
        world.registry, candidates, pages=world.reader, port=LedgerAnswers(tmp_path), active=None
    )
    assert len(claims_of(run.bundle)) == 5 and created == [] and len(provider.calls) == 1
    assert all(c.review.mode == ReviewMode.MACHINE for c in claims_of(run.bundle).values())
    assert {
        p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    } == before


@pytest.mark.parametrize(
    "fault", ["empty_evidence", "unlinked_source", "not_method", "bad_unknown"]
)
def test_admission_refuses_incomplete_or_out_of_scope_support(fault: str) -> None:
    world = World()
    run = compiled(
        world,
        [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))],
        FakeModel({METHOD_A: full_answer}),
    )
    claim = next(iter(claims_of(run.bundle).values()))
    if fault == "empty_evidence":
        claim = claim.model_copy(update={"evidence": []})
    elif fault == "not_method":
        claim = claim.model_copy(update={"predicate": "waiting_period"})
    elif fault == "bad_unknown":
        claim = claim.model_copy(update={"unknown_reason": UnknownReason.NOT_IN_MATERIAL})
    links = () if fault == "unlinked_source" else run.registry.methods[0].links
    route = claim_route(
        claim,
        cards=load_method_cards(),
        policy=load_review_policy(),
        links=links,
        verdict=Verdict.ADD,
        signals=(),
    )
    assert route.mode == ReviewMode.HUMAN and "SOURCE_SUPPORT_INVALID" in route.reasons


def test_all_live_rejects_machine_claims_mixed_with_human_retirements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    world = World()
    old = compiled(
        world,
        [candidate(METHOD_C, world.raw_c, world.hits("k-deck-c"))],
        FakeModel({METHOD_C: unknown_answer}),
    )
    assert old.bundle is not None
    active = release_from(old.bundle)
    world.registry.methods = [
        m.model_copy(update={"suppressed": True}) for m in world.registry.methods
    ]
    live = Live(tmp_path, monkeypatch, world, active)
    before = live.registry.read_bytes()
    assert live.main(capsys) == (2, {"stopped": "REVIEW_SELECTION_REQUIRED"})
    assert live.registry.read_bytes() == before and live.platform.submitted == []
    assert not live.run_root.exists()
