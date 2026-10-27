"""S5b-3d-2b acceptance (protected, written by Claude): every question carries its material's
platform source reference, so an administrator can open the original file. An open item asked
before the reference existed is the same question: kept as it is and settled as usual, never
closed or asked again just to add the reference (round 2 ruling).

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
from tests.ingest.confirmation_scenarios import BASE, UPLOADS, asked, products, run
from tests.ingest.upload_helpers import SPACE


def _pending(current: ProductRegistry, kid: str) -> PendingEntry:
    return next(p for p in current.pending if p.knowledge_id == kid)


def _question(current: ProductRegistry, kid: str) -> ConfirmationInput:
    return question_of(_pending(current, kid), current, head=UPLOADS[kid][1])


def _legacy(platform: FakePlatform, question: ConfirmationInput, **changed: str) -> str:
    """The question as a Harness before S5b-3d-2b pushed it: without a source reference."""
    return platform.put(question.model_dump(exclude={"source_ref"}) | changed)


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


def test_an_open_item_asked_without_the_reference_is_kept_as_the_same_question() -> None:
    current = asked(products(), "k-new")
    platform = FakePlatform()
    legacy = _legacy(platform, _question(current, "k-new"))

    dry, saves = run(current, platform, write=False)
    assert (platform.writes, saves, dry.registry) == ([], [], current)

    first, _ = run(current, platform)
    assert platform.writes == [], "neither asked again nor closed to add the reference"
    assert [i["id"] for i in platform.find("material:k-new")] == [legacy]
    assert "source_ref" not in platform.view(legacy)
    assert (first.registry, first.report.obsoleted) == (current, [])

    again, _ = run(first.registry, platform)
    assert (platform.writes, again.report.obsoleted) == ([], [])


def test_an_answer_on_an_item_asked_without_the_reference_is_applied_as_usual() -> None:
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
    assert all(path.endswith("/closure") for path in platform.writes)


def test_a_question_that_really_changed_still_replaces_an_unsourced_item() -> None:
    current = asked(products(), "k-new")
    platform = FakePlatform()
    old = _legacy(platform, _question(current, "k-new"), title="「旧文案」需要确认")

    result, _ = run(current, platform)
    items = platform.find("material:k-new")
    assert [i["id"] for i in items][0] == old and len(items) == 2
    assert items[1]["source_ref"] == "source:v1:k-new:1:" + "f" * 64
    assert platform.closed == [(old, "obsolete", None)]
    assert result.report.obsoleted == ["k-new"]


@pytest.mark.parametrize(
    ("attempt", "accepted"),
    [("9223372036854775807", True), ("9223372036854775808", False), ("0", False)],
)
def test_the_platform_parses_the_attempt_as_a_signed_64_bit_integer(
    attempt: str, accepted: bool
) -> None:
    question = _question(asked(products(), "k-new"), "k-new")
    ref = f"source:v1:k-new:{attempt}:" + "f" * 64
    platform = FakePlatform()
    client = PlatformClient(BASE, "key", transport=platform.transport())
    if accepted:
        [item] = client.submit_confirmations(
            SPACE, [question.model_copy(update={"source_ref": ref})]
        )
        assert item.source_ref == ref
        return
    with pytest.raises(PlatformError) as refused:
        client.submit_confirmations(SPACE, [question.model_copy(update={"source_ref": ref})])
    assert refused.value.code == "CONFIRMATION_INVALID"
    assert platform.items == {}
