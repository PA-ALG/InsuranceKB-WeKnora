"""S5b-3c-2 acceptance (protected, written by Claude): settlements written before closing, and the
reconciliation that completes them whatever step a run stopped at (Spec §2.2, §4 item 6; review
R1, R2, R5). A run is interrupted by a failing save, a lost closing receipt or a platform error.
"""

import json

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient, PlatformError
from insurance_harness.ingest.confirmations import sync
from insurance_harness.ingest.registry import ProductRegistry, Settlement
from insurance_harness.ingest.uploads import attribute_uploads
from tests.ingest.confirmation_platform import PREFIX, FakePlatform
from tests.ingest.confirmation_scenarios import (
    BASE,
    UPLOADS,
    Crash,
    Saves,
    asked,
    only_item,
    pages,
    products,
    run,
    waiting,
)
from tests.ingest.upload_helpers import PRODUCTS, Pages, material, raw

NEW_CODE = "平安人寿〔2026〕两全保险999号"


def settled_reasons(current: ProductRegistry) -> list[str]:
    return [p.settlement.reason for p in current.pending if p.settlement is not None]


def test_an_interrupted_applied_close_is_completed_from_its_settlement() -> None:
    first, _ = run(asked(products(), "k-new"), platform := FakePlatform())
    item_id = only_item(platform, "k-new")
    answer_id = platform.answer(item_id, "replace")
    crash = Crash(on_call=2)  # the settlement is saved, the close succeeds, the next save fails
    with pytest.raises(OSError):
        run(first.registry, platform, save=crash)
    [persisted] = crash.saved
    assert platform.closed == [(item_id, "applied", answer_id)]
    assert settled_reasons(persisted) == ["applied"]
    assert persisted.decisions == first.registry.decisions

    recovered, saves = run(persisted, platform)
    assert platform.closed == [(item_id, "applied", answer_id)]
    decision = recovered.registry.decisions[-1]
    assert decision.attribution.outcome == "REPLACE"
    assert decision.confirmation is not None and decision.confirmation.answer_id == answer_id
    assert (recovered.registry.pending, recovered.report.applied) == ([], ["k-new"])
    assert saves[-1] == recovered.registry


def test_an_interrupted_obsolete_close_still_reopens_the_material() -> None:
    first, _ = run(asked(products(), "k-new"), platform := FakePlatform())
    item_id = only_item(platform, "k-new")
    changed = first.registry.model_copy(deep=True)
    materials = changed.products["1818"].materials
    materials.pop(next(i for i, m in enumerate(materials) if m.role == "brochure"))
    platform.answer(item_id, "replace")
    crash = Crash(on_call=2)
    with pytest.raises(OSError):
        run(changed, platform, save=crash)
    [persisted] = crash.saved
    assert platform.closed == [(item_id, "obsolete", None)]
    assert settled_reasons(persisted) == ["obsolete"]

    recovered, _ = run(persisted, platform)
    assert platform.closed == [(item_id, "obsolete", None)]
    assert (recovered.registry.pending, recovered.report.reopened) == ([], ["k-new"])
    judged = attribute_uploads(recovered.registry, [UPLOADS["k-new"][0]], pages())
    assert judged.report.counts == {"SUPPLEMENT": 1}


def test_a_lost_closing_receipt_is_reconciled_without_closing_again() -> None:
    first, _ = run(asked(products(), "k-new"), platform := FakePlatform())
    item_id = only_item(platform, "k-new")
    answer_id = platform.answer(item_id, "supplement")
    platform.lose_closure_responses = 1
    saves = Saves()
    with pytest.raises(PlatformError) as failure:
        run(first.registry, platform, save=saves)
    assert failure.value.code == "SERVICE_UNAVAILABLE"
    assert settled_reasons(saves[-1]) == ["applied"]
    recovered, _ = run(saves[-1], platform)
    assert platform.closed == [(item_id, "applied", answer_id)]
    assert recovered.registry.decisions[-1].attribution.outcome == "SUPPLEMENT"


def test_a_settlement_left_before_closing_is_closed_on_the_next_run() -> None:
    first, _ = run(asked(products(), "k-new"), platform := FakePlatform())
    item_id = only_item(platform, "k-new")
    answer_id = platform.answer(item_id, "ignore")
    platform.fail_closures_after = 0
    saves = Saves()
    with pytest.raises(PlatformError):
        run(first.registry, platform, save=saves)
    assert (platform.closed, settled_reasons(saves[-1])) == ([], ["applied"])
    platform.fail_closures_after = None
    recovered, _ = run(saves[-1], platform)
    assert platform.closed == [(item_id, "applied", answer_id)]
    assert recovered.registry.decisions[-1].attribution.outcome == "IGNORED"


def test_a_new_answer_replaces_a_settlement_not_yet_closed() -> None:
    first, _ = run(asked(products(), "k-new"), platform := FakePlatform())
    item_id = only_item(platform, "k-new")
    platform.answer(item_id, "replace")
    platform.fail_closures_after = 0
    saves = Saves()
    with pytest.raises(PlatformError):
        run(first.registry, platform, save=saves)
    platform.fail_closures_after = None
    newer = platform.answer(item_id, "supplement")
    recovered, _ = run(saves[-1], platform)
    assert recovered.report.skipped == {}  # dropped before closing, not refused by the platform
    assert platform.closed == [(item_id, "applied", newer)]
    assert recovered.registry.decisions[-1].attribution.outcome == "SUPPLEMENT"
    assert recovered.registry.pending == []


def test_a_settled_replacement_overtaken_by_a_new_version_is_a_conflict() -> None:
    reissued = raw("1818", "terms", knowledge_id="k-reissued", sha256="e" * 64)
    head = material("1818", "terms")["head"]
    reader = Pages(heads={"k-reissued": head}, sources=[reissued])
    current = attribute_uploads(products(), [reissued], reader).registry
    [waits] = current.pending
    assert (waits.attribution.reason, waits.attribution.role) == ("same_role_differs", "terms")
    first, _ = run(current, platform := FakePlatform(), reader=reader)
    item_id = only_item(platform, "k-reissued")
    platform.answer(item_id, "replace")
    crash = Crash(on_call=2)
    with pytest.raises(OSError):
        run(first.registry, platform, reader=reader, save=crash)
    [persisted] = crash.saved

    # Meanwhile terms with a new code replace the same old terms.
    newer = raw("1818", "terms", knowledge_id="k-newer", sha256="9" * 64)
    newer_head = head.replace(PRODUCTS["1818"]["clause_code"], NEW_CODE, 1)
    both = Pages(heads={"k-reissued": head, "k-newer": newer_head}, sources=[reissued, newer])
    moved = attribute_uploads(persisted, [newer], both)
    assert moved.report.counts == {"NEW_VERSION": 1}

    result, saves = run(moved.registry, platform, reader=both)
    assert result.report.skipped == {"CONFIRMATION_CONFLICT": 1}
    assert (result.registry, saves) == (moved.registry, [])
    assert len(platform.closed) == 1
    assert waiting(result.registry) == ["k-reissued"]


def rewritten(platform: FakePlatform, edit: str) -> PlatformClient:
    """A client whose platform answers some calls wrongly (review R5)."""

    def handle(request: httpx.Request) -> httpx.Response:
        response = platform.handle(request)
        if request.method != "POST" or response.status_code >= 300:
            return response
        body = json.loads(response.content)
        if edit == "reorder" and request.url.path == PREFIX:
            body["data"]["items"].reverse()
        elif edit == "receipt" and request.url.path.endswith("/closure"):
            body["data"]["closure"] |= {"reason": "obsolete"}
            body["data"]["closure"].pop("answer_id", None)
        return httpx.Response(response.status_code, json=body)

    return PlatformClient(BASE, "key", transport=httpx.MockTransport(handle))


def test_a_submission_answered_out_of_order_is_refused_before_anything_is_closed() -> None:
    first, _ = run(asked(products(), "k-new", "k-scan"), platform := FakePlatform())
    platform.answer(only_item(platform, "k-new"), "supplement")
    platform.answer(only_item(platform, "k-scan"), "role:brochure")
    saves = Saves()
    with pytest.raises(PlatformError) as failure:
        sync(first.registry, rewritten(platform, "reorder"), pages(), write=True, save=saves)
    assert failure.value.code == "INVALID_RESPONSE"
    assert (platform.closed, saves) == ([], [])


def test_a_closing_receipt_that_does_not_match_is_not_taken_as_the_close() -> None:
    first, _ = run(asked(products(), "k-new"), platform := FakePlatform())
    item_id = only_item(platform, "k-new")
    answer_id = platform.answer(item_id, "supplement")
    saves = Saves()
    with pytest.raises(PlatformError) as failure:
        sync(first.registry, rewritten(platform, "receipt"), pages(), write=True, save=saves)
    assert failure.value.code == "INVALID_RESPONSE"
    assert saves[-1].decisions == first.registry.decisions
    assert settled_reasons(saves[-1]) == ["applied"]
    recovered, _ = run(saves[-1], platform)  # the platform did close it: reconcile from its state
    assert platform.closed == [(item_id, "applied", answer_id)]
    assert recovered.registry.decisions[-1].attribution.outcome == "SUPPLEMENT"


# Review R10, R9, R5 remainder ---------------------------------------------------------------------


def test_an_open_settlement_whose_conclusion_no_longer_applies_is_not_closed() -> None:
    reissued = raw("1818", "terms", knowledge_id="k-reissued", sha256="e" * 64)
    head = material("1818", "terms")["head"]
    reader = Pages(heads={"k-reissued": head}, sources=[reissued])
    first, _ = run(
        attribute_uploads(products(), [reissued], reader).registry,
        platform := FakePlatform(),
        reader=reader,
    )
    platform.answer(only_item(platform, "k-reissued"), "replace")
    platform.fail_closures_after = 0
    saves = Saves()
    with pytest.raises(PlatformError):
        run(first.registry, platform, reader=reader, save=saves)
    assert settled_reasons(saves[-1]) == ["applied"]
    newer = raw("1818", "terms", knowledge_id="k-newer", sha256="9" * 64)
    newer_head = head.replace(PRODUCTS["1818"]["clause_code"], NEW_CODE, 1)
    both = Pages(heads={"k-reissued": head, "k-newer": newer_head}, sources=[reissued, newer])
    moved = attribute_uploads(saves[-1], [newer], both)
    assert moved.report.counts == {"NEW_VERSION": 1}
    platform.fail_closures_after = None

    result, later = run(moved.registry, platform, reader=both)
    assert platform.closed == []  # the item stays open: a person can still answer again
    assert result.report.skipped == {"CONFIRMATION_CONFLICT": 1}
    assert (result.registry, later) == (moved.registry, [])


def test_a_closed_item_whose_answer_differs_from_the_settlement_is_not_executed() -> None:
    first, _ = run(asked(products(), "k-new"), platform := FakePlatform())
    item_id = only_item(platform, "k-new")
    platform.answer(item_id, "supplement")
    crash = Crash(on_call=2)
    with pytest.raises(OSError):
        run(first.registry, platform, save=crash)
    [persisted] = crash.saved
    platform.answers[item_id][-1]["option_key"] = "ignore"  # the same answer id, another choice
    result, saves = run(persisted, platform)
    assert result.report.skipped == {"SETTLEMENT_MISMATCH": 1}
    assert (result.registry, saves) == (persisted, [])


def test_a_settlement_naming_another_submitters_item_is_not_executed() -> None:
    current = asked(products(), "k-new")
    platform = FakePlatform()
    foreign = platform.add("other:item-1", "r1", "别的提交方", [{"key": "ignore", "label": "忽略"}])
    PlatformClient(BASE, "key", transport=platform.transport()).close_confirmation(
        "space-1", foreign, "obsolete"
    )
    [entry] = current.pending
    settlement = Settlement(
        item_id=foreign,
        knowledge_id=entry.knowledge_id,
        parse_attempt=entry.parse_attempt,
        sha256=entry.sha256,
        revision="r1",
        reason="obsolete",
        confirmation=None,
        conclusion=None,
    )
    current.pending[0] = entry.model_copy(update={"settlement": settlement})
    result, saves = run(current, platform)
    assert result.report.skipped == {"SETTLEMENT_MISMATCH": 1}
    assert result.report.reopened == []
    assert ([p.knowledge_id for p in result.registry.pending], saves) == (["k-new"], [])


def closed_by_someone_else(platform: FakePlatform, option: str | None) -> None:
    """Before our close lands, another submitter closes the item with its latest answer; the
    answer is then reported with another choice when `option` is given (review R5)."""

    def close_first(item_id: str) -> None:
        platform.before_close = None
        answer = platform.answers[item_id][-1]
        platform.closures[item_id] = {
            "reason": "applied",
            "answer_id": answer["id"],
            "closed_by": "service:other",
            "closed_at": "2026-10-25T11:00:00Z",
        }
        if option is not None:
            answer["option_key"] = option

    platform.before_close = close_first


def test_a_close_someone_else_made_with_the_same_answer_completes_once() -> None:
    first, _ = run(asked(products(), "k-new"), platform := FakePlatform())
    platform.answer(only_item(platform, "k-new"), "supplement")
    closed_by_someone_else(platform, None)
    result, _ = run(first.registry, platform)
    assert result.report.applied == ["k-new"]
    assert result.registry.decisions[-1].attribution.outcome == "SUPPLEMENT"


def test_a_close_someone_else_made_with_another_answer_is_not_executed() -> None:
    first, _ = run(asked(products(), "k-new"), platform := FakePlatform())
    platform.answer(only_item(platform, "k-new"), "supplement")
    closed_by_someone_else(platform, "ignore")
    result, saves = run(first.registry, platform)
    assert result.report.skipped == {"SETTLEMENT_MISMATCH": 1}
    assert result.registry.decisions == first.registry.decisions
    assert settled_reasons(result.registry) == ["applied"]
    assert saves and settled_reasons(saves[-1]) == ["applied"]


def test_a_reread_item_of_another_question_keeps_the_settlement_whatever_its_closure() -> None:
    """Review R5: identity is checked before a differing closure may clear the settlement."""
    first, _ = run(asked(products(), "k-new"), platform := FakePlatform())
    item_id = only_item(platform, "k-new")
    platform.answer(item_id, "supplement")

    def close_as_another_question(target: str) -> None:
        platform.before_close = None
        platform.items[target]["subject"] = "material:k-other"
        platform.closures[target] = {
            "reason": "obsolete",
            "closed_by": "service:other",
            "closed_at": "2026-10-25T11:00:00Z",
        }

    platform.before_close = close_as_another_question
    result, saves = run(first.registry, platform)
    assert result.report.skipped == {"SETTLEMENT_MISMATCH": 1}
    assert settled_reasons(result.registry) == ["applied"]
    assert saves and settled_reasons(saves[-1]) == ["applied"]
    assert result.registry.decisions == first.registry.decisions
