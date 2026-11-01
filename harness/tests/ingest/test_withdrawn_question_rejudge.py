"""S5b-9 acceptance (written by Claude): a question whose item was withdrawn is judged again.

Spec docs/design/slices/S5b-9-撤回后的问题重判.md §2. S5b-7 keeps a question asked under an
older policy as it was asked, because a person may be answering it. Once every item asked for that
material revision is closed as obsolete — the answer withdrawn, nothing applied — there is nothing
left to protect: `uploads run` judges it again under the current policy and records the new
verdict, and the withdrawn answer never becomes a person's decision. When the platform's items
cannot be read the question is kept and the run says so.
"""

import json
from pathlib import Path

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient
from insurance_harness.identity.attribution import Attribution, load_attribution_policy
from insurance_harness.ingest.raw_sources import RawSource
from insurance_harness.ingest.registry import (
    PendingEntry,
    ProductEntry,
    ProductRegistry,
    load_registry,
    save_registry,
)
from insurance_harness.ingest.uploads import attribute_uploads, main
from insurance_harness.ingest.withdrawn_questions import read_question_states
from tests.ingest.confirmation_platform import PREFIX, FakePlatform
from tests.ingest.confirmation_scenarios import BASE, run
from tests.ingest.upload_helpers import RAW_KB, SPACE, Pages

OLD = "attribution-policy@2026-10-31.1"
DECK = RawSource(knowledge_id="k-deck", parse_attempt=1, file_name="产品学习.pptx", sha256="c" * 64)
BRANDED = "平安e生保\r\n产品亮点\r\n续保与理赔"  # still a brand question under the current policy
UNANCHORED = "培训手册\r\n讲解步骤\r\n讲解关键句"  # no brand, no title: quarantined today


def current_policy() -> str:
    return load_attribution_policy().policy_ref


def asked_registry() -> ProductRegistry:
    """A deck asked under an older policy: which e生保 product it belongs to."""
    return ProductRegistry(
        contract="product-registry.v1",
        space_id=SPACE,
        raw_kb_id=RAW_KB,
        products={
            "sc-esb": ProductEntry(
                names=["平安e生保（悦享版）医疗保险"],
                clause_codes=["平安人寿〔2025〕医疗保险201号"],
                schema_pack_id="schemapack_medical_insurance",
                origin="created",
                materials=[],
            ),
        },
        pending=[
            PendingEntry(
                knowledge_id=DECK.knowledge_id,
                parse_attempt=DECK.parse_attempt,
                sha256=DECK.sha256,
                file_name=DECK.file_name,
                attribution=Attribution.model_validate({
                    "policy_ref": OLD,
                    "outcome": "NEEDS_CONFIRM",
                    "reason": "brand_candidates",
                    "candidates": ("sc-esb",),
                }),
            )
        ],
        decisions=[],
    )


def reader(head: str) -> Pages:
    return Pages(heads={DECK.knowledge_id: head}, sources=[DECK])


def client(platform: FakePlatform) -> PlatformClient:
    return PlatformClient(BASE, "key", transport=platform.transport())


def asked_on(platform: FakePlatform, head: str) -> tuple[ProductRegistry, str]:
    """`uploads confirm` pushes the old question; the item id it got."""
    first, _ = run(asked_registry(), platform, reader=reader(head))
    [item] = platform.find("material:k-deck")
    return first.registry, item["id"]


def withdraw(platform: FakePlatform, item_id: str, *, answered: bool = True) -> None:
    """A person answered, then the answer was withdrawn by decision: closed as obsolete."""
    if answered:
        platform.answer(item_id, platform.view(item_id)["options"][0]["key"])
    client(platform).close_confirmation(SPACE, item_id, "obsolete")


def judged(current: ProductRegistry, platform: FakePlatform, head: str) -> tuple[
    ProductRegistry, list[str], list[str]
]:
    states = read_question_states(client(platform), current, current_policy())
    result = attribute_uploads(
        current, [DECK], reader(head), withdrawn=states.withdrawn, unknown=states.unknown
    )
    return (
        result.registry,
        result.report.withdrawn_rejudged,
        result.report.question_state_unknown,
    )


def deck_entry(current: ProductRegistry) -> PendingEntry:
    [entry] = [p for p in current.pending if p.knowledge_id == DECK.knowledge_id]
    return entry


def test_a_withdrawn_question_is_judged_again_and_its_new_verdict_recorded() -> None:
    platform = FakePlatform(uploads={DECK.knowledge_id: (UNANCHORED, DECK.sha256)})
    asked, item_id = asked_on(platform, UNANCHORED)
    withdraw(platform, item_id)
    after, rejudged, unknown = judged(asked, platform, UNANCHORED)
    entry = deck_entry(after)
    assert (entry.attribution.outcome, entry.attribution.reason) == (
        "QUARANTINE", "no_product_anchor"
    )
    assert entry.attribution.policy_ref == current_policy()
    assert (rejudged, unknown) == (["k-deck"], [])
    assert all(d.confirmation is None for d in after.decisions), "never a person's decision"

    second, _ = run(after, platform, reader=reader(UNANCHORED))
    items = platform.find("material:k-deck")
    assert len(items) == 2, "the new verdict is asked as a new question"
    old = next(i for i in items if i["id"] == item_id)
    assert old["closure"]["reason"] == "obsolete", "the withdrawn item is not reopened"
    assert [w.knowledge_id for w in second.report.answers_withdrawn] == ["k-deck"]
    assert all(d.confirmation is None for d in second.registry.decisions)


def test_a_withdrawn_question_with_the_same_conclusion_is_recorded_under_the_current_policy() -> (
    None
):
    platform = FakePlatform(uploads={DECK.knowledge_id: (BRANDED, DECK.sha256)})
    asked, item_id = asked_on(platform, BRANDED)
    withdraw(platform, item_id, answered=False)
    after, rejudged, _ = judged(asked, platform, BRANDED)
    entry = deck_entry(after)
    assert entry.attribution.outcome == "NEEDS_CONFIRM"
    assert entry.attribution.policy_ref == current_policy(), "a new question identity"
    assert rejudged == ["k-deck"]


def test_an_open_unanswered_question_is_kept_as_asked() -> None:
    platform = FakePlatform(uploads={DECK.knowledge_id: (UNANCHORED, DECK.sha256)})
    asked, _ = asked_on(platform, UNANCHORED)
    after, rejudged, unknown = judged(asked, platform, UNANCHORED)
    assert after.pending == asked.pending and after.decisions == asked.decisions
    assert (rejudged, unknown) == ([], [])


def test_an_open_answered_question_is_kept_and_then_applied() -> None:
    platform = FakePlatform(uploads={DECK.knowledge_id: (BRANDED, DECK.sha256)})
    asked, item_id = asked_on(platform, BRANDED)
    choice = next(o["key"] for o in platform.view(item_id)["options"] if "sc-esb" in o["key"])
    platform.answer(item_id, choice)
    after, rejudged, _ = judged(asked, platform, BRANDED)
    assert after.pending == asked.pending and rejudged == []
    second, _ = run(after, platform, reader=reader(BRANDED))
    assert second.report.applied == ["k-deck"]
    [decided] = [d for d in second.registry.decisions if d.knowledge_id == "k-deck"]
    assert decided.confirmation is not None and decided.confirmation.item_id == item_id


def test_an_item_closed_as_applied_is_not_a_withdrawal() -> None:
    platform = FakePlatform(uploads={DECK.knowledge_id: (UNANCHORED, DECK.sha256)})
    asked, item_id = asked_on(platform, UNANCHORED)
    answer = platform.answer(item_id, platform.view(item_id)["options"][0]["key"])
    client(platform).close_confirmation(SPACE, item_id, "applied", answer)
    after, rejudged, _ = judged(asked, platform, UNANCHORED)
    assert after.pending == asked.pending and rejudged == []


def test_an_item_of_another_revision_does_not_withdraw_this_one() -> None:
    platform = FakePlatform(uploads={DECK.knowledge_id: (UNANCHORED, DECK.sha256)})
    asked, item_id = asked_on(platform, UNANCHORED)
    withdraw(platform, item_id)
    moved = asked.model_copy(deep=True)
    moved.pending = [deck_entry(moved).model_copy(update={"parse_attempt": 2})]
    states = read_question_states(client(platform), moved, current_policy())
    assert states.withdrawn == frozenset(), "never asked at this revision: a person still answers"


def test_an_unreadable_platform_state_keeps_the_question_and_reports_it() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"success": False, "code": "SERVICE_UNAVAILABLE"})

    asked = asked_registry()
    failing = PlatformClient(BASE, "key", transport=httpx.MockTransport(refuse))
    states = read_question_states(failing, asked, current_policy())
    assert (states.withdrawn, states.unknown) == (frozenset(), frozenset({"k-deck"}))
    result = attribute_uploads(
        asked, [DECK], reader(UNANCHORED), withdrawn=states.withdrawn, unknown=states.unknown
    )
    assert result.registry.pending == asked.pending
    assert result.report.question_state_unknown == ["k-deck"]


# The `uploads run` command ----------------------------------------------------------------------


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARNESS_WEKNORA_BASE_URL", BASE)
    monkeypatch.setenv("HARNESS_WEKNORA_API_KEY", "key")


def command_transport(platform: FakePlatform, seen: list[str]) -> httpx.MockTransport:
    listing = [{
        "id": DECK.knowledge_id, "parse_status": "completed", "current_parse_attempt": 1,
        "file_name": DECK.file_name, "file_sha256": DECK.sha256,
    }]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == f"/api/v1/knowledge-bases/{RAW_KB}/knowledge":
            page = int(request.url.params["page"])
            chunk = listing[(page - 1) * 100 : page * 100]
            return httpx.Response(200, json={"success": True, "data": chunk, "total": 1})
        return platform.handle(request)

    return httpx.MockTransport(handler)


def test_the_run_command_judges_a_withdrawn_question_again(
    tmp_path: Path, environment: None, capsys: pytest.CaptureFixture[str]
) -> None:
    platform = FakePlatform(uploads={DECK.knowledge_id: (UNANCHORED, DECK.sha256)})
    asked, item_id = asked_on(platform, UNANCHORED)
    withdraw(platform, item_id)
    path = tmp_path / "registry.json"
    save_registry(asked, path)
    seen: list[str] = []
    assert main(["run", "--registry", str(path)], transport=command_transport(platform, seen)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["withdrawn_rejudged"] == ["k-deck"]
    assert deck_entry(load_registry(path)).attribution.outcome == "QUARANTINE"
    assert not any(path_.endswith("/closure") for path_ in seen), "a run never closes items"


def test_the_run_command_does_not_read_items_when_no_old_question_waits(
    tmp_path: Path, environment: None
) -> None:
    current = asked_registry()
    current.pending = []
    path = tmp_path / "registry.json"
    save_registry(current, path)
    seen: list[str] = []
    platform = FakePlatform(uploads={DECK.knowledge_id: (UNANCHORED, DECK.sha256)})
    assert main(["run", "--registry", str(path)], transport=command_transport(platform, seen)) == 0
    assert PREFIX not in seen, "no confirmation item is read"
