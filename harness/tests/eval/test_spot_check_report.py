"""RV4c acceptance: the spot-check report and resubmission (Spec §2.3).

Protected file: written by Claude. Verdicts are counted per pack (the pack is the stratum's
prefix); "incomplete" is not counted as wrong (S2c); precision gets a 95% Wilson lower bound, and
advice is given only once enough samples are decided, never applied. Wrong items form the
correction list. --submit samples a release against its own base, idempotently on the platform.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient
from insurance_harness.eval import spot_check_report as command
from insurance_harness.ingest import source_map as source_map_module


def verdict(outcome: str, note: str = "") -> dict[str, Any]:
    return {
        "id": f"v-{outcome}",
        "sample_id": "s",
        "outcome": outcome,
        "note": note,
        "reviewer": "user:alice",
        "decided_at": "2026-10-18T12:00:00Z",
    }


def stored(slug: str, stratum: str, outcome: str | None, release: str = "rel-2") -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": f"s-{slug}",
        "space_id": "demo",
        "release_id": release,
        "logical_slug": slug,
        "member_digest": "d" * 64,
        "stratum": stratum,
        "created_by": "svc",
        "created_at": "2026-10-18T11:00:00Z",
    }
    if outcome:
        data["verdict"] = verdict(outcome, "缺少等待期" if outcome == "wrong" else "")
    return data


SAMPLES = [
    *(stored(f"P1/f{i}", "ci/rest", "correct") for i in range(8)),
    stored("P1/inc", "ci/rest", "incomplete"),
    stored("P1/bad", "ci/must", "wrong"),
    stored("P1/open", "ci/must", None),
    stored("P2/g", "med/rest", "correct"),
]


def entity(entity_id: str, label: str) -> dict[str, Any]:
    payload = {"entity_id": entity_id, "names": [entity_id], "classification_labels": [label]}
    return {
        "kind": "entity",
        "logical_slug": f"entity/{entity_id}",
        "member_digest": "a" * 64,
        "payload": payload,
    }


def machine_claim(slug: str, digest: str) -> dict[str, Any]:
    entity_id, field = slug.split("/")
    payload = {
        "subject_ref": entity_id,
        "predicate": field,
        "state": "present",
        "value": "v",
        "review": {"mode": "machine"},
    }
    return {"kind": "claim", "logical_slug": slug, "member_digest": digest * 64, "payload": payload}


PROFILE = {
    "kind": "presentation_profile",
    "logical_slug": "presentation/profile_ci",
    "member_digest": "b" * 64,
    "payload": {
        "profile_id": "profile_ci",
        "schema_pack_id": "ci",
        "classification_labels": ["ci_label"],
        "sections": [],
    },
}
RELEASES = {
    "rel-1": {
        "id": "rel-1",
        "epoch": 1,
        "members": [PROFILE, entity("P1", "ci_label"), machine_claim("P1/a", "1")],
    },
    "rel-2": {
        "id": "rel-2",
        "epoch": 2,
        "base_release_id": "rel-1",
        "members": [
            PROFILE,
            entity("P1", "ci_label"),
            machine_claim("P1/a", "1"),
            machine_claim("P1/b", "2"),
        ],
    },
}


class Platform:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body: Any = json.loads(request.content) if request.content else None
        path = request.url.path.removeprefix("/api/v1/enterprise/spaces/demo/")
        self.seen.append(
            (
                request.method,
                path + ("?" + request.url.query.decode() if request.url.query else ""),
                body,
            )
        )
        if path == "samples":
            return ok({"samples": SAMPLES})
        if path.endswith("/samples"):
            picks = [stored(item["slug"], item["stratum"], None) for item in body["samples"]]
            return ok({"samples": picks}, 201)
        release = path.removeprefix("releases/")
        return ok(RELEASES[release])


def ok(data: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"success": True, "data": data})


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> Platform:
    server = Platform()
    monkeypatch.setenv(source_map_module.BASE_URL_ENV, "https://weknora.test")
    monkeypatch.setenv(source_map_module.API_KEY_ENV, "key-123")
    monkeypatch.setattr(
        command,
        "PlatformClient",
        lambda base, key: PlatformClient(base, key, transport=httpx.MockTransport(server)),
    )
    return server


POLICY = {
    "version": "t",
    "default": {"rate": 1.0, "minimum": 5, "target": 0.9, "must_check": []},
    "packs": {"med": {"rate": 1.0, "minimum": 5, "target": 0.9, "must_check": []}},
}


def run(tmp_path: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> tuple[int, Any]:
    (tmp_path / "policy.json").write_text(json.dumps(POLICY), encoding="utf-8")
    argv = [
        "--space",
        "demo",
        "--policy",
        str(tmp_path / "policy.json"),
        "--out",
        str(tmp_path / "report.json"),
        *extra,
    ]
    code = command.main(argv)
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and str(tmp_path) not in out[0]
    return code, json.loads(out[0])


def test_verdicts_are_counted_per_pack_with_a_wilson_lower_bound_and_advice(
    tmp_path: Path, platform: Platform, capsys: pytest.CaptureFixture[str]
) -> None:
    code, summary = run(tmp_path, capsys)
    assert code == 0
    ci, med = summary["packs"]["ci"], summary["packs"]["med"]
    assert (ci["samples"], ci["decided"], ci["correct"], ci["incomplete"], ci["wrong"]) == (
        11,
        10,
        8,
        1,
        1,
    )
    assert ci["precision"] == pytest.approx(0.9)  # incomplete is not wrong
    assert ci["lower_bound"] == pytest.approx(0.5958, abs=1e-3)
    assert ci["advice"] == "raise_threshold_or_revoke"  # 0.596 < 0.9 with 10 >= 5 decided
    assert med["decided"] == 1 and med["advice"] == "insufficient"
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["corrections"] == [
        {"slug": "P1/bad", "release_id": "rel-2", "reviewer": "user:alice", "note": "缺少等待期"}
    ]
    assert summary["corrections"] == 1


def test_a_release_filter_is_passed_to_the_platform(
    tmp_path: Path, platform: Platform, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmp_path, capsys, "--release", "rel-2")[0] == 0
    assert ("GET", "samples?release=rel-2", None) in platform.seen


def test_submit_samples_a_release_against_its_base(
    tmp_path: Path, platform: Platform, capsys: pytest.CaptureFixture[str]
) -> None:
    code, summary = run(tmp_path, capsys, "--release", "rel-2", "--submit")
    assert code == 0 and summary["submitted"] == 1
    [body] = [body for method, path, body in platform.seen if path == "releases/rel-2/samples"]
    assert body == {"samples": [{"slug": "P1/b", "stratum": "ci/rest"}]}  # P1/a is unchanged


def test_submit_needs_a_release_and_failures_are_fixed_codes(
    tmp_path: Path, platform: Platform, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmp_path, capsys, "--submit") == (2, {"stopped": "INVALID_ARGUMENTS"})
    (tmp_path / "bad.json").write_text("{}", encoding="utf-8")
    code = command.main(["--space", "demo", "--policy", str(tmp_path / "bad.json")])
    assert code == 2
    assert json.loads(capsys.readouterr().out) == {"stopped": "SPOT_CHECK_POLICY_INVALID"}
