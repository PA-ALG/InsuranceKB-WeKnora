"""Spot-check edges beyond the acceptance cases: large submissions are split to the platform's
batch limit, a pack with no decided sample has no precision, and a missing platform configuration
or an unwritable report stops with fixed codes."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient, Release, ReleaseMember
from insurance_harness.catalog.spot_check import load_spot_check_policy
from insurance_harness.compilers.schema_fields import publish
from insurance_harness.eval import spot_check_report as command
from insurance_harness.ingest import source_map as source_map_module


def test_the_wilson_lower_bound_matches_known_values() -> None:
    assert command.wilson_lower_bound(9, 10) == pytest.approx(0.5958, abs=1e-4)
    assert command.wilson_lower_bound(20, 20) == pytest.approx(0.8389, abs=1e-4)
    assert command.wilson_lower_bound(0, 0) == 0.0


def test_a_publish_sample_is_split_to_the_platform_batch_limit() -> None:
    claims = [
        ReleaseMember(
            kind="claim",
            logical_slug=f"P1/f{i:04d}",
            member_digest="d" * 64,
            payload={"subject_ref": "P1", "predicate": f"f{i}", "review": {"mode": "machine"}},
        )
        for i in range(1203)
    ]
    batches: list[int] = []

    def platform(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        batches.append(len(body["samples"]))
        samples = [
            {
                "id": item["slug"],
                "release_id": "rel-1",
                "logical_slug": item["slug"],
                "member_digest": "d" * 64,
                "stratum": item["stratum"],
            }
            for item in body["samples"]
        ]
        return httpx.Response(201, json={"success": True, "data": {"samples": samples}})

    client = PlatformClient("https://weknora.test", "k", transport=httpx.MockTransport(platform))
    released = Release(id="rel-1", epoch=1, members=claims)
    policy = load_spot_check_policy()
    assert publish._submit_sample(client, "demo", released, None, policy) == 1203
    assert batches == [500, 500, 203]


def test_undecided_packs_have_no_precision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = {
        "id": "s",
        "release_id": "rel-1",
        "logical_slug": "P1/a",
        "member_digest": "d" * 64,
        "stratum": "ci/rest",
    }

    def platform(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "data": {"samples": [sample]}})

    monkeypatch.setenv(source_map_module.BASE_URL_ENV, "https://weknora.test")
    monkeypatch.setenv(source_map_module.API_KEY_ENV, "k")
    monkeypatch.setattr(
        command,
        "PlatformClient",
        lambda base, key: PlatformClient(base, key, transport=httpx.MockTransport(platform)),
    )
    assert command.main(["--space", "demo"]) == 0
    pack = json.loads(capsys.readouterr().out)["packs"]["ci"]
    assert (pack["decided"], pack["precision"], pack["lower_bound"], pack["advice"]) == (
        0,
        None,
        None,
        "insufficient",
    )
    assert command.main(["--space", "demo", "--out", str(tmp_path / "missing" / "r.json")]) == 2
    assert json.loads(capsys.readouterr().out) == {"stopped": "OUT_UNWRITABLE"}


def test_a_missing_platform_configuration_stops(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(source_map_module.API_KEY_ENV, raising=False)
    assert command.main(["--space", "demo"]) == 2
    assert json.loads(capsys.readouterr().out) == {"stopped": "PLATFORM_UNCONFIGURED"}
