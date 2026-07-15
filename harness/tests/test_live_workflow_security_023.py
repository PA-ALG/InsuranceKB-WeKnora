"""OpenSpec 023 R4.1/R4.2: trusted exact-SHA live workflow contract."""

from collections.abc import Mapping
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "harness-live.yml"
LIVE_VALUES = {
    "HARNESS_LIVE_BASE_URL",
    "HARNESS_LIVE_API_KEY",
    "HARNESS_LIVE_DB_URL",
    "HARNESS_LIVE_SPACE_ID",
    "HARNESS_LIVE_KNOWLEDGE_ID",
    "HARNESS_LIVE_PARSER_FINGERPRINT",
    "HARNESS_LIVE_KB_ID",
}


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, dict)
    return value


def _workflow() -> Mapping[str, object]:
    document = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    return _mapping(document)


def _named_step(job: Mapping[str, object], name: str) -> Mapping[str, object]:
    steps = job["steps"]
    assert isinstance(steps, list)
    for step in steps:
        if isinstance(step, dict) and step.get("name") == name:
            return step
    raise AssertionError(f"workflow step is missing: {name}")


def _steps(job: Mapping[str, object]) -> list[Mapping[str, object]]:
    steps = job["steps"]
    assert isinstance(steps, list)
    return [_mapping(step) for step in steps]


def test_r4_1_dispatch_requires_pr_sha_and_nonce_inputs() -> None:
    dispatch = _mapping(_mapping(_workflow()["on"])["workflow_dispatch"])
    inputs = _mapping(dispatch["inputs"])

    assert set(inputs) == {"pr_number", "head_sha", "runner_nonce"}
    for configuration in inputs.values():
        assert _mapping(configuration)["required"] == "true"


def test_r4_1_hosted_preflight_is_secretless_same_repo_exact_sha_gate() -> None:
    jobs = _mapping(_workflow()["jobs"])
    preflight = _mapping(jobs["preflight"])

    assert preflight["runs-on"] == "ubuntu-latest"
    assert "environment" not in preflight
    serialized = yaml.safe_dump(dict(preflight))
    assert "secrets." not in serialized
    gate = _named_step(preflight, "Approve same-repository exact SHA")
    script = str(_mapping(gate["with"])["script"])
    for term in (
        "refs/heads/main",
        "workflow_ref",
        "pulls.get",
        "state",
        "head.repo.full_name",
        "head.sha",
        "^[0-9a-f]{40}$",
        "insurancekb-live-",
    ):
        assert term in script


def test_r4_1_live_job_uses_unique_label_and_detached_approved_sha() -> None:
    live = _mapping(_mapping(_workflow()["jobs"])["live"])
    labels = live["runs-on"]

    assert isinstance(labels, list)
    assert labels == ["self-hosted", "${{ needs.preflight.outputs.runner-label }}"]
    assert live["needs"] == "preflight"
    checkout = next(
        step
        for step in _steps(live)
        if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    checkout_with = _mapping(checkout["with"])
    assert checkout_with["ref"] == "${{ needs.preflight.outputs.approved-sha }}"
    assert checkout_with["persist-credentials"] == "false"
    assertion = _named_step(live, "Assert detached approved SHA")
    command = str(assertion["run"])
    assert "git rev-parse HEAD" in command
    assert "symbolic-ref" in command


def test_r4_1_hosted_postflight_rechecks_unchanged_pr_head() -> None:
    postflight = _mapping(_mapping(_workflow()["jobs"])["postflight"])

    assert postflight["runs-on"] == "ubuntu-latest"
    assert "always()" in str(postflight["if"])
    assert "environment" not in postflight
    serialized = yaml.safe_dump(dict(postflight))
    assert "secrets." not in serialized
    script = str(_mapping(_named_step(postflight, "Confirm PR head stability")["with"])["script"])
    assert "pulls.get" in script
    assert "head.sha" in script
    assert "EXPECTED_SHA" in script


def test_r4_2_live_job_receives_only_seven_frozen_values_and_exact_gate() -> None:
    live = _mapping(_mapping(_workflow()["jobs"])["live"])
    assert "env" not in live
    for step in _steps(live):
        if "env" in step:
            assert set(_mapping(step["env"])) == LIVE_VALUES

    test_step = _named_step(live, "Tests (WeKnora live)")
    assert set(_mapping(test_step["env"])) == LIVE_VALUES
    command = str(test_step["run"])
    assert "scripts/run_live_gate.py" in command
    assert "live-nodes.txt" in command
    assert "reports/live.sanitized.xml" in command

    upload = next(
        step
        for step in _steps(live)
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    assert _mapping(upload["with"])["path"] == "harness/reports/live.sanitized.xml"
    steps = _steps(live)
    test_index = steps.index(test_step)
    assert steps[test_index + 1 :] == [upload]
    assert "run" not in upload
