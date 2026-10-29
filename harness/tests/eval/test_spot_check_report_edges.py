"""Spot-check edges beyond the acceptance cases: large submissions are split to the platform's
batch limit, a pack with no decided sample has no precision, and a missing platform configuration
or an unwritable report stops with fixed codes. Review of PR #224: the platform's spot-check codes
reach the caller (R1), a resubmission checks the release and base it was given (R2), samples keep
every field the platform returns (R3), and an unassigned claim is always "unassigned/rest" (R4)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient, PlatformError, Release, ReleaseMember
from insurance_harness.catalog.spot_check import PackRule, SpotCheckPolicy
from insurance_harness.compilers.schema_fields import publish
from insurance_harness.eval import spot_check_report as command
from insurance_harness.ingest import source_map as source_map_module


def test_the_wilson_lower_bound_matches_known_values() -> None:
    assert command.wilson_lower_bound(9, 10) == pytest.approx(0.5958, abs=1e-4)
    assert command.wilson_lower_bound(20, 20) == pytest.approx(0.8389, abs=1e-4)
    assert command.wilson_lower_bound(0, 0) == 0.0


def test_a_publish_sample_is_split_to_the_platform_batch_limit() -> None:
    # Spot-check policy v2 (2026-10-29) samples 10% by default; this edge test is about batching,
    # so it pins a full-sample policy instead of depending on the shipped rate.
    full = PackRule(rate=1.0, minimum=5, target=0.9)
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
                "space_id": "demo",
                "created_by": "svc",
                "created_at": "2026-10-18T12:00:00Z",
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
    policy = SpotCheckPolicy(version="test-full", default=full)
    assert publish._submit_sample(client, "demo", released, None, policy) == 1203
    assert batches == [500, 500, 203]


def test_undecided_packs_have_no_precision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = {
        "id": "s",
        "space_id": "demo",
        "created_by": "svc",
        "created_at": "2026-10-18T12:00:00Z",
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


def sample_json(slug: str, release: str = "rel-2") -> dict[str, object]:
    return {
        "id": f"s-{slug}",
        "space_id": "demo",
        "release_id": release,
        "logical_slug": slug,
        "member_digest": "d" * 64,
        "stratum": "ci/rest",
        "created_by": "svc",
        "created_at": "2026-10-18T11:00:00Z",
    }


@pytest.mark.parametrize("code", ["SAMPLE_INVALID", "MEMBER_NOT_FOUND", "SAMPLE_NOT_FOUND"])
def test_spot_check_rejections_keep_their_codes(code: str) -> None:
    def platform(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"success": False, "code": code})

    client = PlatformClient("https://weknora.test", "k", transport=httpx.MockTransport(platform))
    with pytest.raises(PlatformError) as refused:
        client.submit_samples("demo", "rel-1", [("P1/a", "ci/rest")])
    assert refused.value.code == code
    with pytest.raises(PlatformError) as listed:
        client.samples("demo")
    assert listed.value.code == code


def test_a_sample_keeps_every_field_the_platform_returns() -> None:
    def platform(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"success": True, "data": {"samples": [sample_json("P1/a")]}}
        )

    client = PlatformClient("https://weknora.test", "k", transport=httpx.MockTransport(platform))
    [got] = client.samples("demo")
    assert (got.space_id, got.created_by, got.created_at) == ("demo", "svc", "2026-10-18T11:00:00Z")


def release_json(release_id: str, base: str = "", slugs: tuple[str, ...] = ()) -> dict[str, object]:
    members = [
        {
            "kind": "claim",
            "logical_slug": slug,
            "member_digest": "d" * 64,
            "payload": {
                "subject_ref": "P1",
                "predicate": slug.split("/")[1],
                "review": {"mode": "machine"},
            },
        }
        for slug in slugs
    ]
    return {"id": release_id, "epoch": 2, "base_release_id": base, "members": members}


@pytest.mark.parametrize(
    "answers",
    [
        {"rel-2": release_json("other", "rel-1", ("P1/a",)), "rel-1": release_json("rel-1")},
        {"rel-2": release_json("rel-2", "rel-1", ("P1/a",)), "rel-1": release_json("wrong-base")},
    ],
    ids=["another release", "another base"],
)
def test_a_resubmission_checks_the_release_and_base_it_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], answers: dict[str, object]
) -> None:
    posted: list[str] = []

    def platform(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1/enterprise/spaces/demo/")
        if request.method == "POST":
            posted.append(path)
        return httpx.Response(
            200, json={"success": True, "data": answers[path.removeprefix("releases/")]}
        )

    monkeypatch.setenv(source_map_module.BASE_URL_ENV, "https://weknora.test")
    monkeypatch.setenv(source_map_module.API_KEY_ENV, "k")
    monkeypatch.setattr(
        command,
        "PlatformClient",
        lambda base, key: PlatformClient(base, key, transport=httpx.MockTransport(platform)),
    )
    assert command.main(["--space", "demo", "--release", "rel-2", "--submit"]) == 2
    assert json.loads(capsys.readouterr().out) == {"stopped": "RELEASE_MISMATCH"}
    assert posted == []


@pytest.mark.parametrize(("rate", "minimum"), [(0.0, 0), (0.0, 1), (0.5, 0), (1.0, 0)])
def test_an_unassigned_claim_keeps_the_default_selection_as_the_rest_layer(
    rate: float, minimum: int
) -> None:
    from insurance_harness.catalog.spot_check import PackRule, SpotCheckPolicy
    from insurance_harness.review.spot_check import sample

    rule = PackRule(rate=rate, minimum=minimum, target=0.9, must_check=["risk"])
    policy = SpotCheckPolicy(version="t", default=rule, packs={})
    claims = [
        ReleaseMember(
            kind="claim",
            logical_slug=f"P9/{field}",
            member_digest="d" * 64,
            payload={"subject_ref": "P9", "predicate": field, "review": {"mode": "machine"}},
        )
        for field in ("ordinary", "risk")
    ]
    picks = sample(Release(id="rel-1", epoch=1, members=claims), None, policy)
    assert ("P9/risk", "unassigned/rest") in [(pick.slug, pick.stratum) for pick in picks]
    assert {pick.stratum for pick in picks} == {"unassigned/rest"}
