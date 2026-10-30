"""I1 #468 review R1/R3: the secret scan gates publication; receipts follow Spec §3.2.

R1: every build pushes only to the quarantine repository; within each job the scan of that
exact digest comes before any step that writes to a deployable repository or attests it, and
the multi-arch index is composed only from scanned quarantine digests.
R3: the App receipt extends the local BA0 receipt with index_digest and per-arch digests, and
on v* tags the receipts are attached to the Release by a job that alone holds contents: write.
"""

from __future__ import annotations

import json
from typing import Any

from tests.service_shell.test_images_workflow import WORKFLOW, workflow

DEPLOYABLE = ("env.APP_REPOSITORY", "$APP_REPOSITORY", "matrix.repository", "$REPOSITORY")


def text(step: dict[str, Any]) -> str:
    return json.dumps(step, sort_keys=True)


def job_steps(name: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = workflow()["jobs"][name]["steps"]
    return steps


def index_of(steps: list[dict[str, Any]], needle: str) -> int:
    matches = [i for i, step in enumerate(steps) if needle in step.get("name", "")]
    assert len(matches) == 1, f"exactly one step named like {needle!r}"
    return matches[0]


def test_every_build_pushes_to_quarantine_only() -> None:
    document = workflow()
    assert document["env"]["QUARANTINE_REPOSITORY"].endswith("-quarantine")
    for job in document["jobs"].values():
        for step in job.get("steps", []):
            if "docker/build-push-action" in step.get("uses", ""):
                outputs = step["with"]["outputs"]
                assert "name=${{ env.QUARANTINE_REPOSITORY }}," in outputs, outputs
                assert "APP_REPOSITORY" not in outputs and "matrix.repository" not in outputs


def test_app_scans_the_quarantined_digest_before_promoting_and_attesting() -> None:
    steps = job_steps("app")
    build = index_of(steps, "Build and push the App to quarantine")
    scan = index_of(steps, "Secret scan the quarantined digest")
    promote = index_of(steps, "Promote the scanned digest")
    attest = index_of(steps, "Attest the deployable App digest")
    assert build < scan < promote < attest
    assert "QUARANTINE_REPOSITORY" in text(steps[scan])
    for step in steps[:scan]:
        assert not any(marker in text(step) for marker in DEPLOYABLE), step.get("name")
    promotion = steps[promote]["run"]
    assert '"$QUARANTINE_REPOSITORY@$DIGEST"' in promotion
    assert 'if [ "$promoted" != "$DIGEST" ]' in promotion, "the promoted digest is verified"


def test_per_arch_images_never_touch_a_deployable_repository() -> None:
    steps = job_steps("images")
    scan = index_of(steps, "Secret scan the quarantined digest")
    record = index_of(steps, "Record the scanned per-arch digest")
    assert scan < record
    for step in steps:
        assert not any(marker in text(step) for marker in DEPLOYABLE), step.get("name")


def test_the_deployable_index_is_composed_only_from_scanned_digests() -> None:
    merge = workflow()["jobs"]["merge"]
    assert merge["needs"] == "images"
    steps = merge["steps"]
    compose = steps[index_of(steps, "Compose the deployable index")]["run"]
    assert "$QUARANTINE_REPOSITORY@$(cat" in compose
    attest = index_of(steps, "Attest the deployable index digest")
    assert index_of(steps, "Compose the deployable index") < attest


def test_the_app_receipt_extends_the_local_ba0_receipt() -> None:
    receipt = job_steps("app")[index_of(job_steps("app"), "Write the App receipt")]["run"]
    local_fields = (
        "contract",
        "docker_context",
        "status",
        "selector",
        "artifact_identity",
        "image_id",
        "build_source_head",
        "integration_head",
        "manifest_sha256",
        "dependency_lock_sha256",
        "platform",
        "target",
        "labels",
        "candidate_image_ids",
        "build_invocations",
    )
    for field in local_fields + ("index_digest", "digests", "pull_reference"):
        assert f'"{field}":' in receipt, field
    assert '"contract": "ba0-app-build-receipt.v1"' in receipt
    assert "steps.build.outputs.imageid" in WORKFLOW.read_text(encoding="utf-8")


def test_receipts_are_attached_to_the_release_with_least_privilege() -> None:
    document = workflow()
    release = document["jobs"]["release"]
    assert release["if"] == "startsWith(github.ref, 'refs/tags/v')"
    assert release["permissions"] == {"contents": "write"}
    assert set(release["needs"]) == {"app", "merge"}
    run = " ".join(step.get("run", "") for step in release["steps"])
    assert "gh release upload" in run and "receipt-*.json" in run
    for name, job in document["jobs"].items():
        if name != "release":
            assert "permissions" not in job, f"{name} keeps the workflow defaults"
