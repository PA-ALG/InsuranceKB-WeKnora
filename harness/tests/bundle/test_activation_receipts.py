import gzip

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient, PlatformError

ACTIVATION_TIMEOUT = "HARNESS_WEKNORA_ACTIVATION_READ_TIMEOUT_SECONDS"
RELEASE_LIMIT = "HARNESS_WEKNORA_RELEASE_MAX_RESPONSE_MIB"
DIGEST = "a" * 64
RECEIPT = {
    "id": "release-fixed",
    "epoch": 3,
    "base_release_id": "release-parent",
    "candidate_id": "candidate",
    "decision_id": "decision",
    "decision_digest": DIGEST,
}


def ok(data: object) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "data": data})


def test_budgets_are_selected_by_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ACTIVATION_TIMEOUT, "180")
    monkeypatch.setenv(RELEASE_LIMIT, "33")
    seen: list[tuple[str, float, float, float, float]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        timeout = request.extensions["timeout"]
        path = request.url.path
        seen.append(
            (
                path.split("/")[-1],
                *(
                    timeout[k]
                    for k in (
                        "read",
                        "connect",
                        "write",
                        "pool",
                    )
                ),
            )
        )
        if path.endswith("/activations"):
            return ok({k: v for k, v in RECEIPT.items() if k != "decision_id"} | {"members": []})
        if path.endswith("/active"):
            return httpx.Response(
                200,
                content=gzip.compress(
                    b'{"success":true,"data":{"id":"release-fixed","epoch":3}}' + b" " * (32 << 20)
                ),
                headers={"Content-Encoding": "gzip"},
            )
        return ok(
            {"id": "decision", "candidate_id": "candidate", "outcome": "approve", "digest": DIGEST}
        )

    client = PlatformClient("https://platform.test", "key", httpx.MockTransport(handler))
    client.activate("space", "candidate", "decision")
    assert client.active("space") is not None
    assert seen == [("activations", 180, 30, 30, 30), ("active", 30, 30, 30, 30)]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (ACTIVATION_TIMEOUT, "29"),
        (ACTIVATION_TIMEOUT, "181"),
        (ACTIVATION_TIMEOUT, "030"),
        (RELEASE_LIMIT, "31"),
        (RELEASE_LIMIT, "129"),
        (RELEASE_LIMIT, ""),
    ],
)
def test_bad_budget_fails_before_requests(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    value: str,
) -> None:
    monkeypatch.setenv(key, value)
    with pytest.raises(PlatformError, match="INVALID_REQUEST"):
        PlatformClient("https://platform.test", "key")


def test_oversize_activation_receipt_has_its_own_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RELEASE_LIMIT, "128")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        if request.method == "POST":
            assert request.url.params["response"] == "receipt"
            return httpx.Response(200, content=ok(RECEIPT).content + b" " * (64 << 10))
        return httpx.Response(404, json={"success": False, "code": "RELEASE_NOT_FOUND"})

    client = PlatformClient("https://platform.test", "key", httpx.MockTransport(handler))
    activate = getattr(client, "activate_receipt", None)
    assert callable(activate), "client needs the explicit bounded activation receipt request"
    with pytest.raises(PlatformError, match="INVALID_RESPONSE"):
        activate("space", "candidate", "decision", DIGEST)
    assert seen == ["POST"]
