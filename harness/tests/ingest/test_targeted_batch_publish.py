"""Public Judge Batch path over a fixed-version offline transport."""

import json
from typing import Any

import httpx
import pytest

from insurance_harness.bundle.canonical import member_digest
from insurance_harness.bundle.client import PlatformClient
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.ingest.test_judge_batch import publish, world  # noqa: F401
from tests.ingest.test_judge_batch_recovery import LedgerPlatform, ledger, ok, record  # noqa: F401


def header(release: dict[str, Any]) -> dict[str, Any]:
    return {"base_release_id": "", "candidate_id": "", "decision_digest": ""} | {
        k: v for k, v in release.items() if k != "members"
    }


def index(member: dict[str, Any]) -> dict[str, Any]:
    row = {k: member[k] for k in ("kind", "logical_slug", "member_digest")}
    fields = {"entity": ("entity_id",), "claim": ("subject_ref", "logical_key")}
    for name in fields.get(member["kind"], ()):
        if isinstance(member["payload"].get(name), str):
            row[name] = member["payload"][name]
    return row


@pytest.mark.parametrize(
    ("base_members", "lose_activation"), [(4, False), (13_000, False), (4, True)]
)
def test_targeted_publish_pins_the_release_and_reads_no_full_responses(
    ledger: dict[str, Any],  # noqa: F811
    base_members: int,
    lose_activation: bool,
) -> None:
    server: LedgerPlatform = ledger["server"]
    initial = server.active["id"]
    for number in range(base_members - len(server.active["members"])):
        slug = f"foreign/field-{number:05}"
        foreign = {"subject_ref": "elsewhere", "logical_key": slug, "value": "hidden" * 600}
        server.active["members"].append(
            {
                "kind": "claim",
                "logical_slug": slug,
                "payload": foreign,
                "member_digest": member_digest(foreign),
            }
        )
    assert any(m["logical_slug"].startswith("foreign/") for m in server.active["members"])
    assert len(server.active["members"]) == base_members
    lookups: list[tuple[str, list[str]]] = []
    indexed: list[str] = []
    sent: list[str] = []
    activations: list[str] = []
    receipts: dict[tuple[str, str], dict[str, Any]] = {}
    total_bytes = 0

    def route(req: httpx.Request) -> httpx.Response:
        path = req.url.path.split("/spaces/space-1/")[1]
        sent.append(path)
        if path == "releases/active/summary":
            return ok(header(server.active))
        if path.endswith(("/member-index", "/member-lookup")):
            release_id = path.split("/")[1]
            data = server.releases[release_id]
            members = sorted(data["members"], key=lambda x: x["logical_slug"])
            if path.endswith("/member-index"):
                indexed.append(release_id)
                return ok(header(data) | {"members": [index(m) for m in members]})
            slugs = json.loads(req.content)["slugs"]
            lookups.append((release_id, slugs))
            selected = [m for m in members if m["logical_slug"] in slugs]
            missing = [s for s in slugs if s not in {m["logical_slug"] for m in selected}]
            return ok(header(data) | {"members": selected, "missing": missing})
        if path.endswith("/activations"):
            activations.append(req.method)
            candidate = path.split("/")[1]
            if req.method == "GET":
                return ok(receipts[candidate, req.url.params["decision_id"]])
            assert req.url.params["response"] == "receipt"
            out = server(req).json()["data"]
            out["decision_digest"] = "e" * 64
            server.active = server.releases[out["id"]] = out
            receipt = {
                name: out[name]
                for name in ("id", "epoch", "base_release_id", "candidate_id", "decision_digest")
            }
            decision = json.loads(req.content)["decision_id"]
            receipts[candidate, decision] = receipt | {"decision_id": decision}
            if lose_activation:
                return httpx.Response(503, json={"success": False, "code": "SERVICE_UNAVAILABLE"})
            return ok(receipts[candidate, decision])
        assert not (req.method == "GET" and path.startswith("releases/")), path
        return server(req)

    def dispatch(req: httpx.Request) -> httpx.Response:
        nonlocal total_bytes
        response = route(req)
        if req.url.path.endswith(("/summary", "/member-index", "/member-lookup", "/activations")):
            total_bytes += len(response.content)
        return response

    ledger["client"] = PlatformClient("https://platform.test", "key", httpx.MockTransport(dispatch))
    result = publish(ledger, live=True, targeted_release_reads=True)
    published = server.active
    if lose_activation:
        assert result["stopped"]["code"] == "SERVICE_UNAVAILABLE"
        later = {**published, "id": "rel_later", "epoch": published["epoch"] + 1}
        server.active = server.releases[later["id"]] = later
        result = publish(ledger, live=True)
    assert result["stopped"] is None
    final = published["id"]
    assert indexed == ([initial, final, initial] if lose_activation else [initial, final])
    assert activations == (["POST", "GET"] if lose_activation else ["POST"])
    assert sent.count("releases/active/summary") == 1
    assert lookups and not any(
        slug.startswith("foreign/") for _, slugs in lookups for slug in slugs
    )
    assert sorted(server.samples[final]) == sorted(ledger["keys"])
    assert record(ledger)["targeted_release_reads"] is True
    assert len(published["members"]) >= base_members
    assert 0 < total_bytes <= 8 * 1024 * 1024
    if base_members == 13_000:
        print(f"{base_members} base members: {total_bytes} bytes, zero full Release HTTP reads")
