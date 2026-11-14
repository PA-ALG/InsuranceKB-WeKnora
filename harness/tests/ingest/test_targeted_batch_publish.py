"""Public Judge Batch path over a fixed-version offline transport."""

import json
from typing import Any

import httpx

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


def test_targeted_publish_pins_the_release_and_reads_no_full_responses(
    ledger: dict[str, Any],  # noqa: F811
) -> None:
    server: LedgerPlatform = ledger["server"]
    initial = server.active["id"]
    foreign = {"subject_ref": "elsewhere", "logical_key": "foreign/key", "value": "hidden"}
    server.active["members"].append(
        {
            "kind": "claim",
            "logical_slug": "other/alias",
            "payload": foreign,
            "member_digest": member_digest(foreign),
        }
    )
    lookups: list[tuple[str, list[str]]] = []
    indexed: list[str] = []
    sent: list[str] = []

    def dispatch(req: httpx.Request) -> httpx.Response:
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
            assert req.url.params["response"] == "receipt"
            out = server(req).json()["data"]
            out["decision_digest"] = "e" * 64
            server.active = server.releases[out["id"]] = out
            receipt = {
                name: out[name]
                for name in ("id", "epoch", "base_release_id", "candidate_id", "decision_digest")
            }
            return ok(receipt | {"decision_id": json.loads(req.content)["decision_id"]})
        assert not (req.method == "GET" and path.startswith("releases/")), path
        return server(req)

    ledger["client"] = PlatformClient("https://platform.test", "key", httpx.MockTransport(dispatch))
    result = publish(ledger, live=True, targeted_release_reads=True)
    assert result["stopped"] is None
    final = server.active["id"]
    assert indexed == [initial, final]
    assert sent.count("releases/active/summary") == 1
    assert all("other/alias" not in slugs for _, slugs in lookups)
    assert sorted(server.samples[final]) == sorted(ledger["keys"])
    assert record(ledger)["targeted_release_reads"] is True
