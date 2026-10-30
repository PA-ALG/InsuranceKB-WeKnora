"""I1 acceptance (protected, written by Claude): the CI image workflow contract.

Spec docs/design/slices/I1-CI构建镜像.md §3. Four images are built on native runners and
published by digest to GHCR with provenance, SBOM and a failing secret scan; the app image is
built from the BA0 plan so its labels equal a local build's. The repository is public, so the
workflow must not consume repository secrets.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/images.yml"
HARNESS_DOCKERFILE = ROOT / "docker/Dockerfile.harness"
PINNED = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def workflow() -> dict[Any, Any]:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def triggers(document: dict[Any, Any]) -> dict[str, Any]:
    # PyYAML reads the bare key `on` as the boolean True.
    value = document.get("on", document.get(True))
    assert isinstance(value, dict)
    return value


def steps(document: dict[Any, Any]) -> list[dict[str, Any]]:
    return [step for job in document["jobs"].values() for step in job.get("steps", [])]


def test_the_workflow_runs_on_main_tags_and_manual_dispatch_only() -> None:
    on = triggers(workflow())
    assert set(on) == {"push", "workflow_dispatch"}
    assert on["push"]["branches"] == ["main"]
    assert on["push"]["tags"] == ["v*"]


def test_every_action_is_pinned_to_a_full_commit() -> None:
    for step in steps(workflow()):
        if "uses" in step:
            assert PINNED.match(step["uses"]), step["uses"]


def test_permissions_allow_ghcr_and_attestation_and_no_repository_secret_is_used() -> None:
    document = workflow()
    assert document["permissions"] == {
        "contents": "read",
        "packages": "write",
        "id-token": "write",
        "attestations": "write",
    }
    text = WORKFLOW.read_text(encoding="utf-8")
    assert re.findall(r"secrets\.[A-Za-z_]+", text) == []


def test_four_images_are_built_on_native_runners_for_both_architectures() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for name in ("app", "frontend", "docreader", "harness"):
        assert f"ghcr.io/pa-alg/insurancekb-weknora-{name}" in text
    assert "ubuntu-24.04-arm" in text
    assert re.search(r"\bubuntu-24\.04\b(?!-arm)", text), "an amd64 native runner is required"
    assert "imagetools create" in text


def test_the_app_image_is_built_from_the_ba0_plan() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/app_image_registry.py plan" in text
    assert "docker/Dockerfile.app" in text


def test_images_carry_provenance_sbom_attestation_and_a_failing_secret_scan() -> None:
    document = workflow()
    builds = [s for s in steps(document) if "docker/build-push-action" in s.get("uses", "")]
    assert builds
    for step in builds:
        options = step["with"]
        assert options["provenance"] == "mode=max"
        assert options["sbom"] is True
        assert options.get("push-by-digest", options.get("outputs")) is not None
    uses = [s.get("uses", "") for s in steps(document)]
    assert any("actions/attest-build-provenance" in u for u in uses)
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--scanners secret" in text and "--exit-code 1" in text


def test_the_harness_image_installs_the_locked_wheel_without_data_or_secrets() -> None:
    source = HARNESS_DOCKERFILE.read_text(encoding="utf-8")
    for line in source.splitlines():
        if line.startswith("FROM "):
            assert "@sha256:" in line, line
    assert "uv export --locked" in source
    assert "--require-hashes" in source
    for forbidden in ("config.yaml", "contracts/", ".env", "dataset/"):
        assert forbidden not in source
    assert "USER " in source
