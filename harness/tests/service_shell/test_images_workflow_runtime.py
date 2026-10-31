"""I1 runtime fixes (2026-10-31): the first Images runs on main failed on arm64.

- trivy resolved the quarantined index (image + attestations) to linux/amd64 and found no such
  child on the arm64 legs, so every scan names its platform explicitly;
- the repo-wide GitHub Actions cache (10 GB) evicted blobs of `mode=max` entries and arm64
  builds failed importing it ("blob … not found"), so build cache lives in a non-deployable
  GHCR repository instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "images.yml"


def load() -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return document


def build_steps(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        step
        for job in document["jobs"].values()
        for step in job.get("steps", [])
        if "build-push-action" in str(step.get("uses", ""))
    ]


def scan_steps(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        step
        for job in document["jobs"].values()
        for step in job.get("steps", [])
        if "--scanners secret" in str(step.get("run", ""))
    ]


def test_every_secret_scan_names_its_platform() -> None:
    scans = scan_steps(load())
    assert len(scans) == 2
    for step in scans:
        assert "--platform" in step["run"], step["run"]
    app, matrix = scans
    assert "--platform linux/arm64" in app["run"]
    assert matrix["env"]["PLATFORM"] == "linux/${{ matrix.arch }}"


def test_build_cache_uses_a_non_deployable_registry_not_the_actions_cache() -> None:
    document = load()
    cache_repo = document["env"]["BUILDCACHE_REPOSITORY"]
    assert cache_repo.endswith("-buildcache")
    deployable = {
        document["env"]["APP_REPOSITORY"],
        document["env"]["QUARANTINE_REPOSITORY"],
    }
    assert cache_repo not in deployable
    builds = build_steps(document)
    assert len(builds) == 2
    for step in builds:
        with_ = step["with"]
        assert "type=gha" not in with_["cache-from"] + with_["cache-to"]
        assert with_["cache-from"].startswith("type=registry,ref=${{ env.BUILDCACHE_REPOSITORY }}:")
        assert with_["cache-to"].startswith("type=registry,ref=${{ env.BUILDCACHE_REPOSITORY }}:")
        assert "ignore-error=true" in with_["cache-to"]
