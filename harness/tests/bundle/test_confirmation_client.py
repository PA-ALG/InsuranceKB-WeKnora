"""S5b-3c-2 acceptance (protected, written by Claude): the platform client's confirmation calls.

Spec docs/design/slices/S5b-3c-2-待确认材料的推送与应用.md §3.1: the S5b-3a API-key routes, their
bodies, the 200-item batch limit, caller-safe codes and strict response parsing.
"""

import json
from collections.abc import Callable

import httpx
import pytest

from insurance_harness.bundle.client import (
    ConfirmationInput,
    ConfirmationOption,
    PlatformClient,
    PlatformError,
)

BASE = "https://weknora.test"
SPACE = "space-1"
PATH = f"/api/v1/enterprise/spaces/{SPACE}/confirmations"
ITEM = {
    "id": "item-1",
    "space_id": SPACE,
    "subject": "material:k-1",
    "revision": "a" * 32,
    "content_digest": "d" * 64,
    "title": "「条款.pdf」需要确认",
    "detail": "说明",
    "options": [{"key": "replace", "label": "替换"}, {"key": "ignore", "label": "忽略"}],
    "created_by": "service:harness",
    "created_at": "2026-10-25T09:00:00Z",
}
ANSWER = {
    "id": "answer-1",
    "item_id": "item-1",
    "option_key": "replace",
    "note": "",
    "answerer": "user:alice",
    "answered_at": "2026-10-25T10:00:00Z",
}
CLOSURE = {
    "reason": "applied",
    "answer_id": "answer-1",
    "closed_by": "service:harness",
    "closed_at": "2026-10-25T11:00:00Z",
}
QUESTION = ConfirmationInput(
    subject="material:k-1",
    revision="a" * 32,
    title="「条款.pdf」需要确认",
    detail="说明",
    options=[
        ConfirmationOption(key="replace", label="替换"),
        ConfirmationOption(key="ignore", label="忽略"),
    ],
)


def client(
    handler: Callable[[httpx.Request], httpx.Response], seen: list[httpx.Request]
) -> PlatformClient:
    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return PlatformClient(BASE, "key-123", transport=httpx.MockTransport(record))


def ok(data: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"success": True, "data": data})


def test_submitting_posts_the_items_and_reads_back_what_the_platform_keeps() -> None:
    seen: list[httpx.Request] = []
    stored = ITEM | {"answer": ANSWER}
    items = client(lambda _: ok({"items": [stored]}, 201), seen).submit_confirmations(
        SPACE, [QUESTION]
    )
    [request] = seen
    assert (request.method, request.url.path, request.headers["X-API-Key"]) == (
        "POST",
        PATH,
        "key-123",
    )
    assert json.loads(request.content) == {"items": [QUESTION.model_dump()]}
    assert set(QUESTION.model_dump()) == {"subject", "revision", "title", "detail", "options"}
    [item] = items
    assert (item.id, item.subject, item.answer and item.answer.id, item.closure) == (
        "item-1",
        "material:k-1",
        "answer-1",
        None,
    )


def test_more_than_two_hundred_items_are_refused_before_any_request() -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(PlatformError) as failure:
        client(lambda _: ok({"items": []}), seen).submit_confirmations(SPACE, [QUESTION] * 201)
    assert failure.value.code == "INVALID_REQUEST"
    assert seen == []


def test_listing_passes_the_status_and_refuses_any_other() -> None:
    seen: list[httpx.Request] = []
    closed = ITEM | {"answer": ANSWER, "closure": CLOSURE}
    [item] = client(lambda _: ok({"items": [closed]}), seen).confirmations(SPACE, "closed")
    assert (seen[0].method, seen[0].url.path, dict(seen[0].url.params)) == (
        "GET",
        PATH,
        {"status": "closed"},
    )
    assert item.closure is not None and (item.closure.reason, item.closure.answer_id) == (
        "applied",
        "answer-1",
    )
    with pytest.raises(PlatformError) as failure:
        client(lambda _: ok({"items": []}), seen).confirmations(SPACE, "all")  # type: ignore[arg-type]
    assert failure.value.code == "INVALID_REQUEST"
    assert len(seen) == 1


def test_closing_sends_the_reason_and_only_an_applied_answer() -> None:
    seen: list[httpx.Request] = []
    closure = client(lambda _: ok({"closure": CLOSURE}, 201), seen).close_confirmation(
        SPACE, "item-1", "applied", "answer-1"
    )
    obsolete = CLOSURE | {"reason": "obsolete"}
    del obsolete["answer_id"]
    client(lambda _: ok({"closure": obsolete}, 201), seen).close_confirmation(
        SPACE, "item-1", "obsolete"
    )
    assert [r.url.path for r in seen] == [f"{PATH}/item-1/closure"] * 2
    assert [json.loads(r.content) for r in seen] == [
        {"reason": "applied", "answer_id": "answer-1"},
        {"reason": "obsolete"},
    ]
    assert (closure.reason, closure.answer_id) == ("applied", "answer-1")


@pytest.mark.parametrize(
    "status, code, expected",
    [
        (409, "ANSWER_STALE", "ANSWER_STALE"),
        (409, "CONFIRMATION_CLOSED", "CONFIRMATION_CLOSED"),
        (404, "CONFIRMATION_NOT_FOUND", "CONFIRMATION_NOT_FOUND"),
        (400, "CONFIRMATION_INVALID", "CONFIRMATION_INVALID"),
        (400, "ANSWER_INVALID", "ANSWER_INVALID"),
        (500, "SOMETHING_ELSE", "SERVICE_UNAVAILABLE"),
    ],
)
def test_refusals_become_caller_safe_codes(status: int, code: str, expected: str) -> None:
    def refuse(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, json={"success": False, "code": code, "error": "must not leak"}
        )

    with pytest.raises(PlatformError) as failure:
        client(refuse, []).close_confirmation(SPACE, "item-1", "applied", "answer-1")
    assert failure.value.code == expected
    assert "leak" not in str(failure.value)


@pytest.mark.parametrize(
    "body",
    [
        b'{"success": true, "data": {"items": [], "items": []}}',
        json.dumps({"success": True, "data": {"items": [ITEM | {"options": "replace"}]}}).encode(),
        json.dumps(
            {
                "success": True,
                "data": {"items": [{k: v for k, v in ITEM.items() if k != "subject"}]},
            }
        ).encode(),
    ],
    ids=["duplicate_key", "wrong_type", "missing_field"],
)
def test_responses_are_parsed_strictly(body: bytes) -> None:
    with pytest.raises(PlatformError) as failure:
        client(lambda _: httpx.Response(200, content=body), []).confirmations(SPACE, "open")
    assert failure.value.code == "INVALID_RESPONSE"


@pytest.mark.parametrize("item_id", ["item/1", "", "../x"])
def test_an_item_id_that_is_not_an_identifier_is_refused(item_id: str) -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(PlatformError) as failure:
        client(lambda _: ok({"closure": CLOSURE}), seen).close_confirmation(
            SPACE, item_id, "obsolete"
        )
    assert failure.value.code == "INVALID_REQUEST"
    assert seen == []
