"""App build: select-or-build image lookup, budgets and the public entry."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.service_shell.app_build.contract_helpers import _identity_record
from tests.service_shell.app_build.docker_helpers import (
    _docker_option_values,
    _effective_build_labels,
    _image_inspect,
    _is_docker_build,
    _selector_call,
    _selector_runner,
)
from tests.service_shell.app_build.helpers import (
    ARTIFACT_IDENTITY,
    BUILD_SOURCE_HEAD,
    CANARY_SECRET,
    CANARY_SECRET_B,
    CONTEXT,
    IMAGE_ID,
    INTEGRATION_HEAD,
    PLATFORM,
    REPO_ROOT,
    REQUIRED_LABELS,
    FakeRunner,
    RecordedCall,
    _artifact_module,
    _json_text,
    _sha256_bytes,
)

APP_REPOSITORY = "wechatopenai/weknora-app"


def _invalid_image_inspections() -> tuple[tuple[str, str, int, str], ...]:
    drift_values = {
        "io.insurancekb.app.artifact-identity": "sha256:" + "f" * 64,
        "io.insurancekb.app.build-source-head": "e" * 40,
        "io.insurancekb.app.manifest-sha256": "3" * 64,
        "io.insurancekb.app.dependency-lock-sha256": "4" * 64,
        "io.insurancekb.app.target": "builder",
        "io.insurancekb.app.platform": "linux/amd64",
    }
    slugs = {
        "io.insurancekb.app.artifact-identity": "artifact-label",
        "io.insurancekb.app.manifest-sha256": "input-sha-label",
        "io.insurancekb.app.dependency-lock-sha256": "lock-label",
    }
    cases: list[tuple[str, str, int, str]] = []
    for label, drift in drift_values.items():
        slug = slugs.get(label, label.removeprefix("io.insurancekb.app.").replace("-", "_"))
        missing = {name: value for name, value in REQUIRED_LABELS.items() if name != label}
        changed = {**REQUIRED_LABELS, label: drift}
        cases.extend(
            (
                (
                    f"missing-{slug}",
                    _image_inspect(labels=missing),
                    0,
                    "label|missing",
                ),
                (
                    f"drift-{slug}",
                    _image_inspect(labels=changed),
                    0,
                    "label|drift|mismatch",
                ),
            )
        )
    cases.extend(
        (
            ("os", _image_inspect(os_name="darwin"), 0, "linux|os|platform"),
            ("arch", _image_inspect(architecture="amd64"), 0, "arm64|arch|platform"),
            ("inspect-error", "", 1, "inspect"),
            (
                "image-id",
                _image_inspect(image_id="sha256:" + "9" * 64),
                0,
                "image|candidate|inspect",
            ),
        )
    )
    return tuple(cases)


def _assert_exact_lookup_query(call: RecordedCall) -> None:
    arguments = call.arguments
    assert arguments[:5] == ("docker", "--context", CONTEXT, "image", "ls")
    assert "--quiet" in arguments
    assert "--no-trunc" in arguments
    filters = [
        arguments[index + 1] for index, value in enumerate(arguments[:-1]) if value == "--filter"
    ]
    assert f"label=io.insurancekb.app.artifact-identity={ARTIFACT_IDENTITY}" in filters
    reference_filters = [value for value in filters if value.startswith("reference=")]
    assert reference_filters == [f"reference={APP_REPOSITORY}:*"]


def _assert_exact_candidate_inspect(call: RecordedCall, candidate: str) -> None:
    assert call.arguments == (
        "docker",
        "--context",
        CONTEXT,
        "image",
        "inspect",
        candidate,
        "--format",
        "{{json .}}",
    )


# BA0-REQ-02/06: deterministic lookup, fail-closed reuse, secrecy, build budget.


def test_lookup_normalizes_candidate_set_and_unique_valid_hit_builds_zero(
    tmp_path: Path,
) -> None:
    module = _artifact_module()
    runner = _selector_runner(candidates=f"{IMAGE_ID}\n{IMAGE_ID}\n")

    receipt = _selector_call(module, tmp_path, runner)

    assert receipt["selector"] == "REUSE"
    assert receipt["build_invocations"] == 0
    assert receipt["candidate_image_ids"] == [IMAGE_ID]
    assert receipt["image_id"] == IMAGE_ID
    assert receipt["artifact_identity"] == ARTIFACT_IDENTITY
    assert receipt["build_source_head"] == BUILD_SOURCE_HEAD
    assert receipt["integration_head"] == INTEGRATION_HEAD
    assert sum(_is_docker_build(call.arguments) for call in runner.calls) == 0
    query_calls = [call for call in runner.calls if "ls" in call.arguments]
    inspect_calls = [call for call in runner.calls if "inspect" in call.arguments]
    assert len(query_calls) == len(inspect_calls) == 1
    _assert_exact_lookup_query(query_calls[0])
    _assert_exact_candidate_inspect(inspect_calls[0], IMAGE_ID)
    assert all(call.arguments[:3] == ("docker", "--context", CONTEXT) for call in runner.calls)


def test_lookup_zero_candidates_is_only_miss_and_builds_once(tmp_path: Path) -> None:
    module = _artifact_module()
    runner = _selector_runner(candidates="")

    receipt = _selector_call(module, tmp_path, runner)

    assert receipt["selector"] == "BUILD_AFFECTED"
    assert receipt["build_invocations"] == 1
    assert receipt["candidate_image_ids"] == []
    assert receipt["image_id"] == IMAGE_ID
    build_calls = [call for call in runner.calls if _is_docker_build(call.arguments)]
    assert len(build_calls) == 1
    built_labels = _effective_build_labels(build_calls[0].arguments, build_calls[0].cwd)
    assert REQUIRED_LABELS.items() <= built_labels.items()
    tags = _docker_option_values(build_calls[0].arguments, "--tag", short="-t")
    assert len(tags) == 1
    repository, separator, tag = tags[0].rpartition(":")
    assert separator and repository == APP_REPOSITORY
    assert tag and tag.lower() not in {"latest", "main", "dev", "runtime"}
    assert ARTIFACT_IDENTITY.removeprefix("sha256:") in tag
    assert _docker_option_values(build_calls[0].arguments, "--platform") == [PLATFORM]
    assert _docker_option_values(build_calls[0].arguments, "--target") == ["runtime"]
    assert build_calls[0].arguments.count("--iidfile") == 1
    iidfile_index = build_calls[0].arguments.index("--iidfile")
    assert iidfile_index + 1 < len(build_calls[0].arguments)
    assert Path(build_calls[0].arguments[iidfile_index + 1]).is_absolute()
    query_calls = [call for call in runner.calls if "ls" in call.arguments]
    assert len(query_calls) == 1
    _assert_exact_lookup_query(query_calls[0])
    post_build_inspects = [call for call in runner.calls if "inspect" in call.arguments]
    assert len(post_build_inspects) == 1
    _assert_exact_candidate_inspect(post_build_inspects[0], IMAGE_ID)
    assert runner.calls.index(query_calls[0]) < runner.calls.index(build_calls[0])
    assert runner.calls.index(build_calls[0]) < runner.calls.index(post_build_inspects[0])
    assert receipt["labels"] == REQUIRED_LABELS
    assert receipt["platform"] == PLATFORM


@pytest.mark.parametrize(
    ("inspect_stdout", "inspect_returncode", "message"),
    tuple(
        pytest.param(inspect_stdout, returncode, message, id=case)
        for case, inspect_stdout, returncode, message in _invalid_image_inspections()
    ),
)
def test_lookup_miss_post_build_invalid_inspect_fails_closed_after_one_build(
    tmp_path: Path,
    inspect_stdout: str,
    inspect_returncode: int,
    message: str,
) -> None:
    module = _artifact_module()
    runner = _selector_runner(
        candidates="",
        inspect_stdout=inspect_stdout,
        inspect_returncode=inspect_returncode,
    )
    evidence = tmp_path / "selector-receipt.json"

    with pytest.raises(module.ArtifactContractError, match=message):
        module.select_or_build_app(
            repo_root=REPO_ROOT,
            identity=_identity_record(),
            evidence_out=evidence,
            runner=runner,
            secret_values={},
            real_build_budget_remaining=1,
        )

    query_calls = [call for call in runner.calls if "ls" in call.arguments]
    build_calls = [call for call in runner.calls if _is_docker_build(call.arguments)]
    inspect_calls = [call for call in runner.calls if "inspect" in call.arguments]
    assert len(query_calls) == len(build_calls) == len(inspect_calls) == 1
    _assert_exact_lookup_query(query_calls[0])
    _assert_exact_candidate_inspect(inspect_calls[0], IMAGE_ID)
    assert runner.calls.index(query_calls[0]) < runner.calls.index(build_calls[0])
    assert runner.calls.index(build_calls[0]) < runner.calls.index(inspect_calls[0])
    assert evidence.is_file()
    failure_receipt = json.loads(evidence.read_text(encoding="utf-8"))
    assert failure_receipt.get("status") != "PASS"
    assert failure_receipt["selector"] == "BUILD_AFFECTED"
    assert failure_receipt["build_invocations"] == 1


@pytest.mark.parametrize(
    ("case", "candidates", "inspect_stdout", "inspect_returncode", "message"),
    (
        *tuple(
            pytest.param(
                case,
                IMAGE_ID + "\n",
                inspect_stdout,
                returncode,
                message,
                id=case,
            )
            for case, inspect_stdout, returncode, message in _invalid_image_inspections()
        ),
        pytest.param(
            "conflict",
            f"sha256:{'e' * 64}\n{IMAGE_ID}\n{IMAGE_ID}\n",
            _image_inspect(),
            0,
            "conflict|multiple|candidate",
            id="conflict",
        ),
    ),
)
def test_lookup_nonempty_invalid_conflict_or_inspect_error_fails_closed_build_zero(
    tmp_path: Path,
    case: str,
    candidates: str,
    inspect_stdout: str,
    inspect_returncode: int,
    message: str,
) -> None:
    module = _artifact_module()
    runner = _selector_runner(
        candidates=candidates,
        inspect_stdout=inspect_stdout,
        inspect_returncode=inspect_returncode,
    )

    with pytest.raises(module.ArtifactContractError, match=message):
        _selector_call(module, tmp_path, runner)

    assert sum(_is_docker_build(call.arguments) for call in runner.calls) == 0
    query_calls = [call for call in runner.calls if "ls" in call.arguments]
    assert len(query_calls) == 1
    _assert_exact_lookup_query(query_calls[0])
    inspect_calls = [call for call in runner.calls if "inspect" in call.arguments]
    if case == "conflict":
        assert inspect_calls == []
    else:
        assert len(inspect_calls) == 1
        _assert_exact_candidate_inspect(inspect_calls[0], IMAGE_ID)


def test_lookup_query_error_is_not_miss_and_builds_zero(tmp_path: Path) -> None:
    module = _artifact_module()
    runner = _selector_runner(candidates="", query_returncode=1)

    with pytest.raises(module.ArtifactContractError, match="query|lookup"):
        _selector_call(module, tmp_path, runner)

    assert sum(_is_docker_build(call.arguments) for call in runner.calls) == 0
    assert len(runner.calls) == 1
    _assert_exact_lookup_query(runner.calls[0])


def test_lookup_secret_canary_never_enters_argv_trace_labels_receipt_or_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _artifact_module()
    secret_variants: tuple[dict[str, str], ...] = (
        {},
        {"GOPRIVATE": CANARY_SECRET, "repository_token": CANARY_SECRET},
        {"GOPRIVATE": CANARY_SECRET_B, "repository_token": CANARY_SECRET_B},
    )
    runners: list[FakeRunner] = []
    receipts: list[dict[str, Any]] = []
    receipt_files: list[str] = []
    for index, secrets in enumerate(secret_variants):
        case_path = tmp_path / f"secret-variant-{index}"
        case_path.mkdir()
        runner = _selector_runner(candidates="")
        runners.append(runner)
        receipts.append(_selector_call(module, case_path, runner, secrets=secrets))
        receipt_files.append((case_path / "selector-receipt.json").read_text(encoding="utf-8"))
    captured = capsys.readouterr()

    invariant_keys = (
        "selector",
        "build_invocations",
        "artifact_identity",
        "image_id",
        "build_source_head",
        "integration_head",
        "manifest_sha256",
        "dependency_lock_sha256",
        "target",
        "platform",
        "labels",
    )
    projections = [{key: receipt[key] for key in invariant_keys} for receipt in receipts]
    assert projections[0] == projections[1] == projections[2]
    surfaces = _json_text(
        {
            "calls": [
                {
                    "arguments": call.arguments,
                    "cwd": str(call.cwd),
                    "kwargs": call.kwargs,
                }
                for runner in runners
                for call in runner.calls
            ],
            "receipts": receipts,
            "receipt_files": receipt_files,
            "labels": [receipt["labels"] for receipt in receipts],
            "identity": [receipt["artifact_identity"] for receipt in receipts],
            "stdout": captured.out,
            "stderr": captured.err,
        }
    )
    for canary in (CANARY_SECRET, CANARY_SECRET_B):
        assert canary not in surfaces
        assert _sha256_bytes(canary.encode()) not in surfaces
    assert all(receipt["build_invocations"] == 1 for receipt in receipts)


def test_lookup_miss_with_exhausted_budget_stops_before_mutation(
    tmp_path: Path,
) -> None:
    module = _artifact_module()
    runner = _selector_runner(candidates="")

    with pytest.raises(module.ArtifactContractError, match="STOP|budget|RETURN_TO_USER"):
        _selector_call(module, tmp_path, runner, budget=0)

    assert sum(_is_docker_build(call.arguments) for call in runner.calls) == 0


def test_lookup_rejects_incomplete_build_metadata_before_docker(tmp_path: Path) -> None:
    module = _artifact_module()
    identity = _identity_record()
    del identity["source_date_epoch"]
    runner = _selector_runner(candidates="")

    with pytest.raises(module.ArtifactContractError, match="metadata|incomplete"):
        module.select_or_build_app(
            repo_root=REPO_ROOT,
            identity=identity,
            evidence_out=tmp_path / "selector-receipt.json",
            runner=runner,
            secret_values={},
            real_build_budget_remaining=1,
        )

    assert runner.calls == []


def test_lookup_rejects_unwritable_evidence_target_before_docker(
    tmp_path: Path,
) -> None:
    module = _artifact_module()
    evidence_directory = tmp_path / "receipt-is-a-directory"
    evidence_directory.mkdir()
    runner = _selector_runner(candidates="")

    with pytest.raises(module.ArtifactContractError, match="evidence|receipt|output"):
        module.select_or_build_app(
            repo_root=REPO_ROOT,
            identity=_identity_record(),
            evidence_out=evidence_directory,
            runner=runner,
            secret_values={},
            real_build_budget_remaining=1,
        )

    assert runner.calls == []


@pytest.mark.parametrize(
    "arguments",
    (
        ("--definitely-unknown",),
        ("--app", "--build-source-head"),
        (
            "--app",
            "--docreader",
            "--build-source-head",
            BUILD_SOURCE_HEAD,
            "--evidence-out",
            "/private/tmp/ba0-should-not-run.json",
        ),
    ),
)
def test_public_app_entry_rejects_bad_or_mixed_arguments(arguments: tuple[str, ...]) -> None:
    result = subprocess.run(
        ("bash", "scripts/build_images.sh", *arguments),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
