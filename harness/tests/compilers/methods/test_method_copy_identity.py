"""#518 review R1 (written by Claude): a duplicate is taken only for these bytes in this base.

Through the real command, the real platform client and a mock transport down to the mapping on
disk: the platform's 409 `duplicate_file` names an existing Knowledge, and it becomes the copy only
when that Knowledge is in the discovery base and holds the record's bytes.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from insurance_harness.compilers.methods import cli
from insurance_harness.compilers.methods.copies import load_copies
from insurance_harness.compilers.methods.platform import MaterialPlatform
from insurance_harness.ingest.registry import save_registry
from insurance_harness.ingest.source_map import API_KEY_ENV, BASE_URL_ENV
from tests.compilers.methods.discovery_helpers import DISCOVERY_KB, DiscoveryWorld
from tests.ingest.upload_helpers import RAW_KB, SPACE


def existing(world: DiscoveryWorld, case: str) -> dict[str, str]:
    sha = world.raws["k-deck-a"].sha256
    return {
        "valid": {"id": "copy-0", "knowledge_base_id": DISCOVERY_KB, "file_sha256": sha},
        "other_bytes": {"id": "copy-0", "knowledge_base_id": DISCOVERY_KB, "file_sha256": "f" * 64},
        "raw_base": {"id": "k-deck-a", "knowledge_base_id": RAW_KB, "file_sha256": sha},
        "id_only": {"id": "copy-0"},
    }[case]


def handler(world: DiscoveryWorld, duplicate: dict[str, str]) -> Any:
    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/api/v1/knowledge-bases/{DISCOVERY_KB}/knowledge" and request.method == "GET":
            return httpx.Response(200, json={"success": True, "data": [], "total": 0})
        if path.endswith("/download"):
            return httpx.Response(200, content=world.files[path.split("/")[-2]])
        if path.endswith("/knowledge/file"):
            body = request.read()
            if world.files["k-deck-a"] in body:  # deck A's bytes: the platform says duplicate
                return httpx.Response(
                    409, json={"success": False, "code": "duplicate_file", "data": duplicate}
                )
            sha = hashlib.sha256(world.files["k-deck-c"]).hexdigest()
            created = {"id": "copy-c", "knowledge_base_id": DISCOVERY_KB, "file_sha256": sha}
            return httpx.Response(200, json={"success": True, "data": created})
        raise AssertionError(f"unexpected request {request.method} {path}")

    return handle


@pytest.mark.parametrize("case", ["valid", "other_bytes", "raw_base", "id_only"])
def test_a_duplicate_is_adopted_only_for_these_bytes_in_this_base(
    case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://platform.invalid")
    monkeypatch.setenv(API_KEY_ENV, "test-only")
    world = DiscoveryWorld()
    transport = httpx.MockTransport(handler(world, existing(world, case)))
    monkeypatch.setattr(
        cli, "MaterialPlatform", lambda url, key: MaterialPlatform(url, key, transport=transport)
    )
    registry, copies = tmp_path / "registry.json", tmp_path / "copies.json"
    save_registry(world.registry, registry)
    status = cli.main(["copies", "--registry", str(registry), "--copies", str(copies),
                       "--discovery-kb", DISCOVERY_KB, "--run-root", str(tmp_path / "run"),
                       "--live"])
    summary = json.loads(capsys.readouterr().out)
    mapping = {c.knowledge_id: c.copy_knowledge_id
               for c in load_copies(copies, SPACE, DISCOVERY_KB).copies}
    assert status == 0
    if case == "valid":
        assert summary["counts"] == {"adopted": 1, "copied": 1}
        assert mapping == {"k-deck-a": "copy-0", "k-deck-c": "copy-c"}
    else:
        assert summary["counts"] == {"DUPLICATE_UNVERIFIED": 1, "copied": 1}
        assert mapping == {"k-deck-c": "copy-c"}  # never recorded as adopted
