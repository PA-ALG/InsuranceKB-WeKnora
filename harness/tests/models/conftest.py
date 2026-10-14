"""Model tests must never send to a real endpoint."""

import httpx
import pytest


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: object, **kwargs: object) -> None:
        raise AssertionError("model tests require MockTransport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", reject)
