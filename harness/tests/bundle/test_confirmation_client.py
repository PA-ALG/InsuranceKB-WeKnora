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


# Review R5, R8: responses must match their requests; the body stays within the platform limit.


@pytest.mark.parametrize(
    "returned",
    [
        [ITEM, ITEM],
        [ITEM | {"space_id": "space-2"}],
        [ITEM | {"revision": "b" * 32}],
        [ITEM | {"title": "另一个问题"}],
        [ITEM | {"options": [{"key": "ignore", "label": "忽略"}]}],
        [ITEM | {"answer": ANSWER | {"item_id": "item-2"}}],
        [],
    ],
    ids=["count", "space", "revision", "title", "options", "answer_owner", "empty"],
)
def test_a_submission_response_that_does_not_match_the_request_is_refused(
    returned: list[object],
) -> None:
    with pytest.raises(PlatformError) as failure:
        client(lambda _: ok({"items": returned}, 201), []).submit_confirmations(SPACE, [QUESTION])
    assert failure.value.code == "INVALID_RESPONSE"


@pytest.mark.parametrize(
    "status, returned",
    [
        ("open", ITEM | {"closure": CLOSURE}),
        ("closed", ITEM),
        ("open", ITEM | {"space_id": "space-2"}),
        ("closed", ITEM | {"closure": CLOSURE, "answer": ANSWER | {"item_id": "item-2"}}),
    ],
    ids=["open_but_closed", "closed_but_open", "other_space", "answer_owner"],
)
def test_a_listing_that_does_not_match_its_status_or_space_is_refused(
    status: str, returned: object
) -> None:
    with pytest.raises(PlatformError) as failure:
        client(lambda _: ok({"items": [returned]}), []).confirmations(SPACE, status)  # type: ignore[arg-type]
    assert failure.value.code == "INVALID_RESPONSE"


@pytest.mark.parametrize(
    "reason, answer_id, receipt",
    [
        ("applied", "answer-1", CLOSURE | {"reason": "obsolete"}),
        ("applied", "answer-1", CLOSURE | {"answer_id": "answer-2"}),
        ("applied", "answer-1", {k: v for k, v in CLOSURE.items() if k != "answer_id"}),
        ("obsolete", None, CLOSURE | {"reason": "obsolete"}),
        ("obsolete", None, CLOSURE),
    ],
    ids=["reason", "other_answer", "no_answer", "obsolete_with_answer", "obsolete_got_applied"],
)
def test_a_closing_receipt_that_does_not_match_the_request_is_refused(
    reason: str, answer_id: str | None, receipt: dict[str, object]
) -> None:
    with pytest.raises(PlatformError) as failure:
        client(lambda _: ok({"closure": receipt}, 201), []).close_confirmation(
            SPACE,
            "item-1",
            reason,  # type: ignore[arg-type]
            answer_id,
        )
    assert failure.value.code == "INVALID_RESPONSE"


def test_a_submission_over_the_body_limit_is_refused_before_any_request() -> None:
    seen: list[httpx.Request] = []
    long = QUESTION.model_copy(update={"detail": "很长的说明" * 400})
    with pytest.raises(PlatformError) as failure:
        client(lambda _: ok({"items": []}), seen).submit_confirmations(SPACE, [long] * 100)
    assert failure.value.code == "INVALID_REQUEST"
    assert seen == []


@pytest.mark.parametrize(
    "returned",
    [
        ITEM | {"closure": CLOSURE, "answer": ANSWER | {"id": "answer-2"}},
        ITEM | {"closure": CLOSURE},
        ITEM | {"closure": CLOSURE | {"reason": "obsolete"}, "answer": ANSWER},
    ],
    ids=["applied_other_answer", "applied_without_answer", "obsolete_with_answer_id"],
)
def test_a_closed_item_whose_closure_contradicts_its_answer_is_refused(returned: object) -> None:
    """Review R5: a closed item cannot hold one latest answer and apply another."""
    with pytest.raises(PlatformError) as failure:
        client(lambda _: ok({"items": [returned]}), []).confirmations(SPACE, "closed")
    assert failure.value.code == "INVALID_RESPONSE"
