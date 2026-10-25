"""S5b-3c-2 acceptance (protected, written by Claude): the settlement a waiting material carries
between deciding to close its item and executing the decision (Spec §3.5).
"""

import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.identity.attribution import Upload
from insurance_harness.identity.confirmation import conclude
from insurance_harness.ingest.registry import (
    ConfirmationRef,
    ProductRegistry,
    RegistryError,
    Settlement,
    load_registry,
    record,
    save_registry,
)
from tests.ingest.confirmation_scenarios import UPLOADS, asked, products

REF = ConfirmationRef(
    item_id="item-1", answer_id="answer-1", option_key="replace", answerer="user:alice"
)
REVISION = "a" * 32


def bound(**fields: Any) -> dict[str, Any]:
    """The material version and question a k-new settlement is made for (Spec §3.5)."""
    source = UPLOADS["k-new"][0]
    return {
        "knowledge_id": source.knowledge_id,
        "parse_attempt": source.parse_attempt,
        "sha256": source.sha256,
        "revision": REVISION,
        **fields,
    }


def waiting_with(settlement: Settlement | None) -> ProductRegistry:
    current = asked(products(), "k-new", "k-orphan", "k-scan")
    for index, entry in enumerate(current.pending):
        if entry.knowledge_id == "k-new":
            current.pending[index] = entry.model_copy(update={"settlement": settlement})
    return current


def replace_conclusion() -> Settlement:
    current = asked(products(), "k-new")
    [entry] = current.pending
    source, head = UPLOADS["k-new"]
    upload = Upload(
        knowledge_id=source.knowledge_id,
        file_name=source.file_name,
        sha256=source.sha256,
        head=head,
    )
    conclusion = conclude(entry.attribution, "replace", upload, current.registered())
    return Settlement(
        **bound(item_id="item-1", reason="applied", confirmation=REF, conclusion=conclusion)
    )


def written(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def test_a_settlement_round_trips_and_an_older_file_has_none(tmp_path: Path) -> None:
    current = waiting_with(replace_conclusion())
    save_registry(current, tmp_path / "registry.json")
    assert load_registry(tmp_path / "registry.json") == current
    document = json.loads(waiting_with(None).model_dump_json())
    for entry in document["pending"]:
        entry.pop("settlement", None)
    loaded = load_registry(written(tmp_path, document))
    assert [p.settlement for p in loaded.pending] == [None, None, None]


def broken(breakage: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(waiting_with(replace_conclusion()).model_dump_json())
    new = next(p for p in document["pending"] if p["knowledge_id"] == "k-new")
    orphan = next(p for p in document["pending"] if p["knowledge_id"] == "k-orphan")
    if breakage == "on_quarantine":
        orphan["settlement"] = new["settlement"]
    elif breakage == "applied_without_answer":
        new["settlement"]["confirmation"] = None
    elif breakage == "applied_without_conclusion":
        new["settlement"]["conclusion"] = None
    elif breakage == "obsolete_with_conclusion":
        new["settlement"]["reason"] = "obsolete"
    elif breakage == "answer_recorded":
        document["decisions"][0]["confirmation"] = new["settlement"]["confirmation"]
    elif breakage == "item_mismatch":  # review R9
        new["settlement"]["confirmation"]["item_id"] = "item-2"
    elif breakage == "source_mismatch":
        new["parse_attempt"] = 2
    elif breakage in {"item_twice", "answer_twice"}:
        scan = next(p for p in document["pending"] if p["knowledge_id"] == "k-scan")
        twin = json.loads(json.dumps(new["settlement"]))
        twin |= {k: scan[k] for k in ("knowledge_id", "parse_attempt", "sha256")}
        if breakage == "answer_twice":
            twin["item_id"] = twin["confirmation"]["item_id"] = "item-2"
        scan["settlement"] = twin
    return document


@pytest.mark.parametrize(
    "breakage",
    [
        "on_quarantine",
        "applied_without_answer",
        "applied_without_conclusion",
        "obsolete_with_conclusion",
        "answer_recorded",
        "item_mismatch",
        "source_mismatch",
        "item_twice",
        "answer_twice",
    ],
)
def test_a_settlement_breaking_its_rules_is_refused(tmp_path: Path, breakage: str) -> None:
    with pytest.raises(RegistryError) as failure:
        load_registry(written(tmp_path, broken(breakage)))
    assert failure.value.code == "REGISTRY_INVALID"


def test_an_obsolete_settlement_names_no_answer_or_conclusion() -> None:
    settlement = Settlement(
        **bound(item_id="item-1", reason="obsolete", confirmation=None, conclusion=None)
    )
    assert [
        p.settlement for p in waiting_with(settlement).pending if p.knowledge_id == "k-new"
    ] == [settlement]


def test_recording_the_settled_conclusion_removes_the_settlement_with_its_entry() -> None:
    settlement = replace_conclusion()
    current = waiting_with(settlement)
    assert settlement.conclusion is not None and settlement.confirmation is not None
    record(current, UPLOADS["k-new"][0], settlement.conclusion, settlement.confirmation)
    assert [p.knowledge_id for p in current.pending] == ["k-orphan", "k-scan"]
    assert current.decisions[-1].confirmation == REF


@pytest.mark.parametrize("reason", ["applied", "obsolete"])
def test_a_settlement_for_an_item_already_recorded_is_refused(tmp_path: Path, reason: str) -> None:
    """Review R9: an item closes once, so a recorded item cannot be settled again."""
    document: dict[str, Any] = json.loads(waiting_with(replace_conclusion()).model_dump_json())
    new = next(p for p in document["pending"] if p["knowledge_id"] == "k-new")
    if reason == "obsolete":
        new["settlement"] |= {"reason": "obsolete", "confirmation": None, "conclusion": None}
    document["decisions"][0]["confirmation"] = REF.model_dump() | {"answer_id": "answer-9"}
    with pytest.raises(RegistryError) as failure:
        load_registry(written(tmp_path, document))
    assert failure.value.code == "REGISTRY_INVALID"
