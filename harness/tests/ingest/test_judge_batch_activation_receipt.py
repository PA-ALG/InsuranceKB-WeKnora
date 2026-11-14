from typing import Any

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.ingest.test_judge_batch import publish, world  # noqa: F401
from tests.ingest.test_judge_batch_recovery import LedgerPlatform, ledger, ok, record  # noqa: F401


@pytest.mark.parametrize("mode", ["success", "lost", "unknown", "lookup-conflict", "bad-release"])
def test_judge_batch_receipt_path(ledger: dict[str, Any], mode: str) -> None:  # noqa: F811
    server: LedgerPlatform = ledger["server"]
    activations: list[str] = []
    lookups: list[tuple[str, str]] = []
    readbacks: list[str] = []
    receipts: dict[tuple[str, str], dict[str, Any]] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("/activations"):
            candidate = path.split("/")[-2]
            if req.method == "GET":
                key = (candidate, req.url.params["decision_id"])
                lookups.append(key)
                if mode == "lookup-conflict":
                    return httpx.Response(409, json={"success": False, "code": "NEEDS_REBASE"})
                if key not in receipts:
                    return httpx.Response(404, json={"success": False, "code": "RELEASE_NOT_FOUND"})
                return ok(receipts[key])
            activations.append(candidate)
            if req.url.params.get("response") != "receipt":
                return server(req)
            result = server(req)
            assert result.is_success
            released: dict[str, Any] = result.json()["data"]
            decision = next(iter(server.decisions))
            receipt = {k: released[k] for k in ("id", "epoch", "base_release_id", "candidate_id")}
            receipt.update(decision_id=decision, decision_digest="e" * 64)
            released["decision_digest"] = receipt["decision_digest"]
            server.releases[released["id"]] = server.active = released
            if mode != "unknown":
                receipts[(candidate, decision)] = receipt
            if mode in {"lost", "unknown", "lookup-conflict"}:
                next_head = {
                    **released,
                    "id": "rel_later",
                    "epoch": released["epoch"] + 1,
                    "candidate_id": "cand_other",
                }
                server.active = server.releases["rel_later"] = next_head
                return httpx.Response(503, json={"success": False, "code": "SERVICE_UNAVAILABLE"})
            return ok(receipt)
        if req.method == "GET" and "/releases/" in path and not path.endswith("/active"):
            released_id = path.split("/")[-1]
            readbacks.append(released_id)
            published = server.releases[released_id]
            if mode == "bad-release":
                published = {**published, "epoch": published["epoch"] + 1}
            return ok(published)
        return server(req)

    ledger["client"] = PlatformClient("https://platform.test", "key", httpx.MockTransport(handler))
    first = publish(ledger, live=True, activation_receipt=True)
    if mode == "success":
        assert first["stopped"] is None
    elif mode == "bad-release":
        assert first["stopped"]["code"] == "RELEASE_MISMATCH"
        assert server.samples == {}
        assert record(ledger)["pending"] == "read_back"
    else:
        assert first["stopped"]["code"] == "SERVICE_UNAVAILABLE"
        assert record(ledger)["pending"] == "activate"
        again = publish(ledger, live=True)  # the choice survives switch removal
        if mode in {"unknown", "lookup-conflict"}:
            expected_code = "RELEASE_NOT_FOUND" if mode == "unknown" else "NEEDS_REBASE"
            assert again["stopped"]["code"] == expected_code
            assert record(ledger)["pending"] == "activate"
            assert record(ledger)["status"] == "in_progress"
        else:
            assert again["stopped"] is None
            assert record(ledger)["release"] != server.active["id"]
        assert len(lookups) == 1

    assert len(activations) == 1
    if mode in {"unknown", "lookup-conflict"}:
        assert readbacks == []
    else:
        stored = record(ledger)
        expected = [stored["release"]]
        if mode == "lost":
            expected.append(stored["base_release"])  # resume loads the fixed sampling base
        assert readbacks == expected
