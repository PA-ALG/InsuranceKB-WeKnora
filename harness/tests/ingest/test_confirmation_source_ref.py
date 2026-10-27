"""S5b-3d-2b acceptance (protected, written by Claude): every question carries its material's
platform source reference, so an administrator can open the original file; the items asked before
the reference existed are replaced once, and an answer given on one of them is not lost.

Spec docs/design/slices/S5b-3d-2b-Harness提交原文件引用.md §2, §4. The platform is the S5b-3a fake
with the S5b-3d-2 (migration 000012) source reference rules.
"""

import json

import httpx
import pytest

from insurance_harness.bundle.client import (
    ConfirmationInput,
    PlatformClient,
    PlatformError,
    confirmation_body,
)
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.ingest.confirmations import question_of
from insurance_harness.ingest.registry import PendingEntry, ProductRegistry
from tests.ingest.confirmation_platform import FakePlatform
from tests.ingest.confirmation_scenarios import BASE, UPLOADS, asked, pages, products, run
from tests.ingest.upload_helpers import SPACE


def _pending(current: ProductRegistry, kid: str) -> PendingEntry:
    return next(p for p in current.pending if p.knowledge_id == kid)


def _question(current: ProductRegistry, kid: str) -> ConfirmationInput:
    return question_of(_pending(current, kid), current, head=UPLOADS[kid][1])


def _legacy(platform: FakePlatform, question: ConfirmationInput) -> str:
    """The same question as a Harness before S5b-3d-2b pushed it: without a source reference."""
    return platform.put(question.model_dump(exclude={"source_ref"}))


def test_each_question_carries_its_materials_source_reference() -> None:
    current = asked(products(), "k-new")
    entry = _pending(current, "k-new")
    question = _question(current, "k-new")
    expected = SourceRevision(entry.knowledge_id, entry.parse_attempt).ref(entry.sha256)
    assert question.source_ref == expected == "source:v1:k-new:1:" + "f" * 64
    [sent] = json.loads(confirmation_body([question]))["items"]
    assert sent["source_ref"] == expected

    without = ConfirmationInput(
        subject=question.subject,
        revision=question.revision,
        title=question.title,
        detail=question.detail,
        options=question.options,
    )
    [plain] = json.loads(confirmation_body([without]))["items"]
    assert "source_ref" not in plain, "an older platform refuses any unknown key"


def test_the_client_refuses_a_stored_item_with_another_source_reference() -> None:
    current = asked(products(), "k-new")
    question = _question(current, "k-new")
    platform = FakePlatform()
    legacy = _legacy(platform, question)

    def handle(request: httpx.Request) -> httpx.Response:
        body = {"success": True, "data": {"items": [platform.view(legacy)]}}
        return httpx.Response(201, json=body)

    client = PlatformClient(BASE, "key", transport=httpx.MockTransport(handle))
    with pytest.raises(PlatformError) as refused:
        client.submit_confirmations(SPACE, [question])
    assert refused.value.code == "INVALID_RESPONSE"


def test_an_unanswered_item_from_before_is_replaced_once() -> None:
    current = asked(products(), "k-new")
    platform = FakePlatform()
    legacy = _legacy(platform, _question(current, "k-new"))

    first, _ = run(current, platform)
    items = platform.find("material:k-new")
    assert [i["id"] for i in items][0] == legacy and len(items) == 2
    new = items[1]
    assert new["source_ref"] == "source:v1:k-new:1:" + "f" * 64
    assert "closure" not in new
    assert platform.closed == [(legacy, "obsolete", None)]
    assert (first.report.pushed, first.report.obsoleted) == (["k-new"], ["k-new"])

    again, _ = run(first.registry, platform)
    assert len(platform.find("material:k-new")) == 2
    assert platform.closed == [(legacy, "obsolete", None)]
    assert (again.report.pushed, again.report.obsoleted) == (["k-new"], [])


def test_an_answer_given_before_the_reference_is_still_applied() -> None:
    current = asked(products(), "k-new")
    platform = FakePlatform()
    legacy = _legacy(platform, _question(current, "k-new"))
    answer_id = platform.answer(legacy, "replace", note="以新版为准")

    result, _ = run(current, platform)
    assert platform.closed == [(legacy, "applied", answer_id)]
    decision = result.registry.decisions[-1]
    assert decision.attribution.outcome == "REPLACE"
    assert decision.confirmation is not None
    assert (decision.confirmation.item_id, decision.confirmation.answer_id) == (legacy, answer_id)
    assert result.registry.pending == []
    assert [i["id"] for i in platform.find("material:k-new")] == [legacy], "nothing asked again"
    assert (result.report.applied, result.report.obsoleted) == (["k-new"], [])


def test_an_answered_item_from_before_stays_open_while_its_opening_cannot_be_read() -> None:
    current = asked(products(), "k-new")
    platform = FakePlatform()
    legacy = _legacy(platform, _question(current, "k-new"))
    platform.answer(legacy, "replace")

    result, _ = run(current, platform, reader=pages("k-new"))
    assert platform.closed == []
    assert [i["id"] for i in platform.find("material:k-new")] == [legacy]
    assert result.registry.pending == current.pending

    later, _ = run(result.registry, platform)
    assert [c[:2] for c in platform.closed] == [(legacy, "applied")]
    assert later.report.applied == ["k-new"]


def test_an_old_item_answered_again_while_being_settled_keeps_its_newer_answer() -> None:
    current = asked(products(), "k-new")
    platform = FakePlatform()
    legacy = _legacy(platform, _question(current, "k-new"))
    platform.answer(legacy, "replace")
    newer: list[str] = []

    def answer_again(item_id: str) -> None:
        if not newer:
            newer.append(platform.answer(item_id, "supplement", answerer="user:bob"))

    platform.before_close = answer_again
    result, _ = run(current, platform)
    assert platform.closed == [], "the stale answer is refused; the item stays open"
    assert result.report.skipped.get("ANSWER_STALE") == 1
    assert [i["id"] for i in platform.find("material:k-new")] == [legacy], "nothing asked again"

    platform.before_close = None
    later, _ = run(result.registry, platform)
    assert platform.closed == [(legacy, "applied", newer[0])]
    assert later.report.applied == ["k-new"]
