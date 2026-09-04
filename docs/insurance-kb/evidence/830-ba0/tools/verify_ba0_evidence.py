#!/usr/bin/env python3
"""Verify the bounded 830 BA0 evidence chain without invoking Docker."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any


ORIGIN_MAIN_BASE = "0e7a26568a2164f9501e409f38fee0d4a62539cb"
ORIGIN_MAIN_TREE = "b96aa35fd2fe86283757deb258920c489de4b4b6"
MANIFEST_PATH = "deploy/local-build/app-build-inputs.v1.json"
DEPENDENCY_LOCK_PATH = "deploy/local-build/app-external-dependencies.v1.json"
DOCKERFILE_PATH = "docker/Dockerfile.app"
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT_ID = re.compile(r"[0-9a-f]{40}")
PROJECT = re.compile(r"insurancekb-ba0-d3-[0-9a-f]{16}")
SECRET_KEY = re.compile(r"(?:^|[_-])(secret|token|password|credential)(?:$|[_-])", re.I)
SECRET_VALUE = re.compile(
    r"(?:secret|password|credential|bearer|api[_-]?key|access[_-]?token)", re.I
)
LABEL_FIELDS = {
    "io.insurancekb.app.artifact-identity": "artifact_identity",
    "io.insurancekb.app.build-source-head": "build_source_head",
    "io.insurancekb.app.manifest-sha256": "manifest_sha256",
    "io.insurancekb.app.dependency-lock-sha256": "dependency_lock_sha256",
    "io.insurancekb.app.target": "target",
    "io.insurancekb.app.platform": "platform",
}
ZERO_EFFECTS = {
    "networks": 0,
    "published_ports": 0,
    "volumes": 0,
    "dependencies": 0,
    "provider_model": 0,
    "business_db": 0,
    "production_8081": 0,
    "production_active": 0,
    "g2": 0,
}
WIP_STATE = {
    "ba0_status": "WIP",
    "current_authorization": "BA0_ONLY",
    "current_product_goal": "NONE",
    "g2_status": "LOCKED_PENDING_BA0_PASS_AND_EXPLICIT_USER_AUTHORIZATION",
    "next_action": "INDEPENDENT_REVIEW_AND_CLOSEOUT",
}
FINAL_STATE = {
    "ba0_status": "PASS",
    "current_authorization": "NONE",
    "current_product_goal": "NONE",
    "g2_status": "LOCKED_PENDING_EXPLICIT_USER_AUTHORIZATION",
    "next_action": "RETURN_TO_USER_FOR_G2_AUTHORIZATION",
}
RECEIPT_PATHS = {
    "initialization_build": "d2/initialization-build.json",
    "same_identity_reuse": "d2/same-identity-reuse.json",
    "exact_image_smoke": "d3/exact-image-smoke.json",
}
NOT_MEASURED_REASONS = {
    "exact_lookup": "NO_MONOTONIC_LOOKUP_SAMPLE_CAPTURED",
    "natural_incremental_build": "NO_SECOND_IDENTITY_OR_BUILD_CREATED",
}
IdentityResolver = Callable[[Path, str, str], Mapping[str, Any]]
D2_FIELDS = {
    "contract",
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
}
D3_FIELDS = {
    "contract",
    "status",
    "scope",
    "artifact_identity",
    "build_source_head",
    "integration_head",
    "image_id",
    "runtime_image_id",
    "project",
    "build_invocations",
    "pull_invocations",
    "cleanup",
    "effects",
}
CLOSEOUT_FIELDS = {
    "contract",
    "evidence_status",
    "state",
    "identity",
    "inputs",
    "receipts",
    "build_budget",
    "cache_probe",
    "g1_history",
    "effects",
    "measurements",
    "self_sha256",
}
IDENTITY_FIELDS = {
    "origin_main_base",
    "origin_main_tree",
    "implementation_head",
    "implementation_tree",
    "d2_build_source_head",
    "d2_build_source_tree",
    "execution_integration_head",
    "image_id",
    "artifact_identity",
}


def _run(repo_root: Path, arguments: Sequence[str]) -> str:
    result = subprocess.run(
        tuple(arguments),
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"command failed ({result.returncode}): {' '.join(arguments)}: "
        f"{result.stderr.strip()}"
    )
    return result.stdout.strip()


def _load_object(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AssertionError(f"cannot read {description}: {path}: {exc}") from exc
    assert isinstance(value, dict), f"{description} must be a JSON object"
    return value


def _canonical_json(value: object, *, newline: bool = False) -> bytes:
    suffix = "\n" if newline else ""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + suffix
    ).encode()


def _canonical_file_sha(path: Path) -> str:
    return hashlib.sha256(_canonical_json(_load_object(path, str(path)))).hexdigest()


def _raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_no_secret_keys(value: object, location: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            assert isinstance(key, str), f"non-string evidence key at {location}"
            assert SECRET_KEY.search(key) is None, (
                f"secret, credential, or token key in public evidence: {location}.{key}"
            )
            _assert_no_secret_keys(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_secret_keys(child, f"{location}[{index}]")
    elif isinstance(value, str):
        assert SECRET_VALUE.search(value) is None, (
            f"secret or credential-like value in public evidence: {location}"
        )


def _assert_self_hash(closeout: Mapping[str, Any]) -> None:
    expected = closeout.get("self_sha256")
    assert isinstance(expected, str) and SHA256.fullmatch(expected), (
        "closeout self-hash is missing or malformed"
    )
    unsigned = deepcopy(dict(closeout))
    unsigned["self_sha256"] = None
    actual = hashlib.sha256(_canonical_json(unsigned, newline=True)).hexdigest()
    assert actual == expected, "closeout self-hash mismatch"


def _assert_exact_effects(value: object, description: str) -> None:
    assert value == ZERO_EFFECTS, f"{description} effects must all be zero: {value}"
    assert isinstance(value, Mapping) and all(
        type(item) is int for item in value.values()
    ), f"{description} effect counters must be integers"


def _assert_receipt_reference(
    evidence_root: Path,
    name: str,
    reference: object,
) -> Path:
    assert isinstance(reference, Mapping), f"receipt reference is invalid: {name}"
    assert set(reference) == {"path", "sha256"}, (
        f"receipt reference fields are not closed: {name}"
    )
    assert reference.get("path") == RECEIPT_PATHS[name], (
        f"receipt path is invalid: {name}"
    )
    expected = reference.get("sha256")
    assert isinstance(expected, str) and SHA256.fullmatch(expected), (
        f"receipt hash is invalid: {name}"
    )
    path = evidence_root / RECEIPT_PATHS[name]
    assert path.is_file(), f"receipt is missing: {path}"
    assert _raw_sha(path) == expected, f"receipt hash mismatch: {name}"
    return path


def _assert_d2(
    receipt: Mapping[str, Any],
    *,
    description: str,
    manifest_sha: str,
    lock_sha: str,
) -> None:
    assert set(receipt) == D2_FIELDS, f"{description} fields are not closed"
    assert receipt.get("contract") == "ba0-app-build-receipt.v1", (
        f"{description} contract is invalid"
    )
    assert receipt.get("status") == "PASS", f"{description} status is not PASS"
    assert receipt.get("platform") == "linux/arm64", (
        f"{description} platform is invalid"
    )
    assert receipt.get("target") == "runtime", f"{description} target is invalid"
    for field, pattern in (
        ("artifact_identity", IMAGE_ID),
        ("image_id", IMAGE_ID),
        ("build_source_head", COMMIT_ID),
        ("integration_head", COMMIT_ID),
        ("manifest_sha256", SHA256),
        ("dependency_lock_sha256", SHA256),
    ):
        value = receipt.get(field)
        assert isinstance(value, str) and pattern.fullmatch(value), (
            f"{description} {field} is malformed"
        )
    assert receipt["manifest_sha256"] == manifest_sha, (
        f"{description} manifest sha256 differs from the canonical input"
    )
    assert receipt["dependency_lock_sha256"] == lock_sha, (
        f"{description} dependency lock sha256 differs from the canonical input"
    )
    labels = receipt.get("labels")
    assert isinstance(labels, Mapping), f"{description} labels are missing"
    assert set(labels) == set(LABEL_FIELDS), f"{description} labels are not closed"
    for label, field in LABEL_FIELDS.items():
        assert labels.get(label) == receipt[field], f"{description} label mismatch: {label}"
    candidates = receipt.get("candidate_image_ids")
    assert isinstance(candidates, list), f"{description} candidate set is invalid"
    assert all(isinstance(item, str) and IMAGE_ID.fullmatch(item) for item in candidates), (
        f"{description} candidate image ID is invalid"
    )
    assert candidates == sorted(set(candidates)), (
        f"{description} candidate image IDs are not deterministic"
    )


def _assert_d2_chain(
    initial: Mapping[str, Any], reuse: Mapping[str, Any], closeout: Mapping[str, Any]
) -> None:
    initial_selector = initial.get("selector")
    initial_builds = initial.get("build_invocations")
    assert type(initial_builds) is int, "first request build count must be an integer"
    assert (initial_selector, initial_builds) in {
        ("REUSE", 0),
        ("BUILD_AFFECTED", 1),
    }, "first request exceeds the one-build budget or has an invalid selector"
    expected_candidates = [initial["image_id"]] if initial_selector == "REUSE" else []
    assert initial.get("candidate_image_ids") == expected_candidates, (
        "first request candidate set is inconsistent with its selector"
    )
    assert reuse.get("selector") == "REUSE", "second request must be exact reuse"
    assert type(reuse.get("build_invocations")) is int, (
        "second request build count must be an integer"
    )
    assert reuse.get("build_invocations") == 0, "second reuse request must build zero times"
    assert reuse.get("candidate_image_ids") == [reuse["image_id"]], (
        "second reuse request must select exactly its frozen image"
    )
    same_fields = {
        "artifact_identity",
        "image_id",
        "build_source_head",
        "integration_head",
        "manifest_sha256",
        "dependency_lock_sha256",
        "platform",
        "target",
        "labels",
    }
    for field in same_fields:
        assert initial[field] == reuse[field], f"D2 request drift: {field}"
    budget = closeout.get("build_budget")
    assert isinstance(budget, Mapping) and all(
        type(value) is int for value in budget.values()
    ), "closeout build budget counters must be integers"
    assert budget == {"authorized": 1, "used": initial_builds}, (
        "closeout build budget differs from D2 receipts"
    )


def _assert_d3(
    receipt: Mapping[str, Any], reuse: Mapping[str, Any]
) -> None:
    assert set(receipt) == D3_FIELDS, "D3 receipt fields are not closed"
    assert receipt.get("contract") == "ba0-container-artifact-smoke.v1", (
        "D3 contract is invalid"
    )
    assert receipt.get("status") == "PASS", "D3 status is not PASS"
    assert receipt.get("scope") == "CONTAINER_ARTIFACT_SMOKE", (
        "D3 scope is not artifact smoke"
    )
    assert receipt.get("artifact_identity") == reuse["artifact_identity"], (
        "D3 artifact identity differs from D2"
    )
    assert receipt.get("build_source_head") == reuse["build_source_head"], (
        "D3 build-source identity differs from D2"
    )
    assert receipt.get("integration_head") == reuse["integration_head"], (
        "D3 integration identity differs from D2"
    )
    assert receipt.get("image_id") == reuse["image_id"], (
        "D3 image identity differs from D2"
    )
    assert receipt.get("runtime_image_id") == reuse["image_id"], (
        "D3 runtime image identity differs from D2"
    )
    assert type(receipt.get("build_invocations")) is int, (
        "D3 build count must be an integer"
    )
    assert type(receipt.get("pull_invocations")) is int, (
        "D3 pull count must be an integer"
    )
    assert receipt.get("build_invocations") == 0, "D3 must have build invocation=0"
    assert receipt.get("pull_invocations") == 0, "D3 must have pull invocation=0"
    assert receipt.get("cleanup") == "PASS", "D3 cleanup is not PASS"
    project = receipt.get("project")
    assert isinstance(project, str) and PROJECT.fullmatch(project), (
        "D3 project identity is invalid"
    )
    _assert_exact_effects(receipt.get("effects"), "D3")


def _assert_cache_contract(repo_root: Path, closeout: Mapping[str, Any]) -> None:
    probe = closeout.get("cache_probe")
    assert probe == {
        "status": "PASS",
        "source": DOCKERFILE_PATH,
        "authority": False,
        "producer_consumer_contract_verified": True,
    }, "cache probe must be verified and must not be correctness authority"
    dockerfile = (repo_root / DOCKERFILE_PATH).read_text(encoding="utf-8")
    for cache_id, target, marker in (
        ("ba0-app-go-mod-v1", "/go/pkg/mod", "ba0-app-go-mod-cache-v1"),
        (
            "ba0-app-go-build-v1",
            "/root/.cache/go-build",
            "ba0-app-go-build-cache-v1",
        ),
    ):
        mount = f"id={cache_id},target={target},sharing=locked"
        assert dockerfile.count(mount) >= 2, f"cache mount contract missing: {cache_id}"
        probe_path = f"{target}/.ba0-app-cache-v1"
        write_position = dockerfile.find(f"> {probe_path}")
        consume_position = dockerfile.rfind(f"test -s {probe_path}")
        assert marker in dockerfile, f"cache producer marker missing: {cache_id}"
        assert 0 <= write_position < consume_position, (
            f"cache producer/consumer order is invalid: {cache_id}"
        )


def _assert_measurements(closeout: Mapping[str, Any]) -> None:
    measurements = closeout.get("measurements")
    assert isinstance(measurements, Mapping) and set(measurements) == {
        "exact_lookup",
        "natural_incremental_build",
    }, "measurement records are missing"
    for name, record in measurements.items():
        assert isinstance(record, Mapping), f"measurement is invalid: {name}"
        assert record == {
            "status": "NOT_MEASURED",
            "reason": NOT_MEASURED_REASONS[name],
        }, f"NOT_MEASURED measurement requires its closed reason: {name}"


def _commit_tree(repo_root: Path, commit: object, description: str) -> str:
    assert isinstance(commit, str) and COMMIT_ID.fullmatch(commit), (
        f"{description} commit is invalid"
    )
    return _run(repo_root, ("git", "rev-parse", f"{commit}^{{tree}}"))


def _g1_changed_paths(
    repo_root: Path, origin_base: str, integration: str
) -> list[str]:
    path = "docs/insurance-kb/evidence/830-g1"
    command_sets = (
        (
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--name-only",
            f"{origin_base}..{integration}",
            "--",
            path,
        ),
        ("git", "-c", "core.quotePath=false", "diff", "--name-only", "--", path),
        (
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--cached",
            "--name-only",
            "--",
            path,
        ),
        (
            "git",
            "-c",
            "core.quotePath=false",
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            path,
        ),
    )
    changed = {
        item
        for arguments in command_sets
        for item in _run(repo_root, arguments).splitlines()
        if item
    }
    current_head = _run(repo_root, ("git", "rev-parse", "HEAD"))
    changed.update(
        item
        for item in _run(
            repo_root,
            (
                "git",
                "-c",
                "core.quotePath=false",
                "diff",
                "--name-only",
                f"{integration}..{current_head}",
                "--",
                path,
            ),
        ).splitlines()
        if item
    )
    return sorted(changed)


def _recompute_identity(
    repo_root: Path, build_source_head: str, integration_head: str
) -> Mapping[str, Any]:
    module_path = repo_root / "scripts/app_artifact.py"
    spec = importlib.util.spec_from_file_location("ba0_artifact_identity", module_path)
    assert spec is not None and spec.loader is not None, (
        "cannot load the canonical artifact identity implementation"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.canonical_identity(
        repo_root=repo_root,
        manifest_path=repo_root / MANIFEST_PATH,
        dependency_lock_path=repo_root / DEPENDENCY_LOCK_PATH,
        build_source_head=build_source_head,
        integration_head=integration_head,
        effective_build_args={
            "CGO_ENABLED": "1",
            "GOOS": "linux",
            "GOARCH": "arm64",
        },
        environment={},
    )


def _assert_recomputed_identity(
    recomputed: Mapping[str, Any], reuse: Mapping[str, Any]
) -> None:
    canonical_bytes = recomputed.get("canonical_bytes")
    assert isinstance(canonical_bytes, bytes), (
        "recomputed canonical identity bytes are missing"
    )
    actual_identity = "sha256:" + hashlib.sha256(canonical_bytes).hexdigest()
    assert recomputed.get("artifact_identity") == actual_identity, (
        "recomputed artifact identity is not the canonical byte hash"
    )
    for field in (
        "artifact_identity",
        "build_source_head",
        "integration_head",
        "manifest_sha256",
        "dependency_lock_sha256",
        "platform",
        "target",
    ):
        assert recomputed.get(field) == reuse.get(field), (
            f"D2 {field} differs from independently recomputed identity"
        )


def _assert_identity(
    repo_root: Path,
    closeout: Mapping[str, Any],
    initial: Mapping[str, Any],
    reuse: Mapping[str, Any],
) -> None:
    identity = closeout.get("identity")
    assert isinstance(identity, Mapping) and set(identity) == IDENTITY_FIELDS, (
        "closeout identity is missing or not closed"
    )
    assert identity.get("origin_main_base") == ORIGIN_MAIN_BASE, (
        "origin/main frozen base differs"
    )
    assert identity.get("origin_main_tree") == ORIGIN_MAIN_TREE, (
        "origin/main frozen tree differs"
    )
    assert _commit_tree(repo_root, ORIGIN_MAIN_BASE, "origin/main") == ORIGIN_MAIN_TREE
    implementation = identity.get("implementation_head")
    implementation_tree = _commit_tree(repo_root, implementation, "implementation")
    assert identity.get("implementation_tree") == implementation_tree, (
        "implementation tree differs"
    )
    build_source = identity.get("d2_build_source_head")
    build_tree = _commit_tree(repo_root, build_source, "D2 build source")
    assert build_source == implementation == initial["build_source_head"], (
        "implementation and D2 build-source identities differ"
    )
    assert identity.get("d2_build_source_tree") == build_tree, (
        "D2 build-source tree differs"
    )
    integration = identity.get("execution_integration_head")
    _commit_tree(repo_root, integration, "execution integration")
    assert integration == initial["integration_head"] == reuse["integration_head"], (
        "execution integration identity differs from D2 receipts"
    )
    _run(
        repo_root,
        ("git", "merge-base", "--is-ancestor", ORIGIN_MAIN_BASE, implementation),
    )
    _run(repo_root, ("git", "merge-base", "--is-ancestor", implementation, integration))
    current_head = _run(repo_root, ("git", "rev-parse", "HEAD"))
    _run(repo_root, ("git", "merge-base", "--is-ancestor", integration, current_head))
    assert identity.get("image_id") == reuse["image_id"], (
        "closeout image identity differs from D2"
    )
    assert identity.get("artifact_identity") == reuse["artifact_identity"], (
        "closeout artifact identity differs from D2"
    )
    changed = _g1_changed_paths(repo_root, ORIGIN_MAIN_BASE, integration)
    assert not changed, f"G1 history changed during BA0: {changed}"
    assert closeout.get("g1_history") == {"status": "PASS", "changed_paths": 0}, (
        "G1 history preservation claim is invalid"
    )


def verify_evidence_pack(
    *,
    repo_root: str | Path,
    evidence_root: str | Path,
    identity_resolver: IdentityResolver | None = None,
) -> dict[str, Any]:
    """Recompute and validate BA0 evidence without Docker or external services."""

    if sys.flags.optimize:
        raise AssertionError("optimized Python disables assertions; verifier fails closed")
    repo = Path(repo_root).resolve(strict=True)
    root = Path(evidence_root).resolve(strict=True)
    closeout = _load_object(root / "ba0-closeout.json", "BA0 closeout")
    _assert_no_secret_keys(closeout)
    assert set(closeout) == CLOSEOUT_FIELDS, "closeout fields are not closed"
    _assert_self_hash(closeout)
    assert closeout.get("contract") == "weknora.830.ba0-closeout.v1", (
        "closeout contract is invalid"
    )
    assert closeout.get("evidence_status") == "PASS", (
        "closeout evidence status is not PASS"
    )
    state = closeout.get("state")
    assert state in (WIP_STATE, FINAL_STATE), "BA0/G2 state transition is invalid"

    receipts = closeout.get("receipts")
    assert isinstance(receipts, Mapping) and set(receipts) == set(RECEIPT_PATHS), (
        "closeout receipt references are incomplete"
    )
    receipt_paths = {
        name: _assert_receipt_reference(root, name, receipts[name])
        for name in RECEIPT_PATHS
    }
    initial = _load_object(receipt_paths["initialization_build"], "first D2 receipt")
    reuse = _load_object(receipt_paths["same_identity_reuse"], "reuse D2 receipt")
    d3 = _load_object(receipt_paths["exact_image_smoke"], "D3 receipt")
    for name, document in (
        ("initialization_build", initial),
        ("same_identity_reuse", reuse),
        ("exact_image_smoke", d3),
    ):
        _assert_no_secret_keys(document, name)

    inputs = closeout.get("inputs")
    assert isinstance(inputs, Mapping) and set(inputs) == {
        "manifest",
        "dependency_lock",
    }, "closeout input identity is missing or not closed"
    expected_inputs = {
        "manifest": MANIFEST_PATH,
        "dependency_lock": DEPENDENCY_LOCK_PATH,
    }
    canonical_hashes: dict[str, str] = {}
    for name, relative in expected_inputs.items():
        record = inputs.get(name)
        assert (
            isinstance(record, Mapping)
            and set(record) == {"path", "sha256"}
            and record.get("path") == relative
        ), (
            f"{name} input path is invalid"
        )
        actual = _canonical_file_sha(repo / relative)
        assert record.get("sha256") == actual, f"{name} canonical sha256 differs"
        canonical_hashes[name] = actual

    _assert_d2(
        initial,
        description="first D2 receipt",
        manifest_sha=canonical_hashes["manifest"],
        lock_sha=canonical_hashes["dependency_lock"],
    )
    _assert_d2(
        reuse,
        description="reuse D2 receipt",
        manifest_sha=canonical_hashes["manifest"],
        lock_sha=canonical_hashes["dependency_lock"],
    )
    _assert_d2_chain(initial, reuse, closeout)
    resolver = identity_resolver or _recompute_identity
    _assert_recomputed_identity(
        resolver(repo, reuse["build_source_head"], reuse["integration_head"]),
        reuse,
    )
    _assert_d3(d3, reuse)
    _assert_cache_contract(repo, closeout)
    _assert_identity(repo, closeout, initial, reuse)
    _assert_exact_effects(closeout.get("effects"), "closeout")
    _assert_measurements(closeout)

    return {
        "contract": "weknora.830.ba0-verification-result.v1",
        "status": "PASS",
        "artifact_identity": reuse["artifact_identity"],
        "image_id": reuse["image_id"],
        "first_request_build_invocations": initial["build_invocations"],
        "second_request_build_invocations": reuse["build_invocations"],
        "d3_build_invocations": d3["build_invocations"],
        "d3_pull_invocations": d3["pull_invocations"],
        "forbidden_effects": sum(closeout["effects"].values()),
        "g1_history_changed_paths": closeout["g1_history"]["changed_paths"],
        "ba0_status": state["ba0_status"],
        "g2_status": state["g2_status"],
    }


def main(arguments: Sequence[str] | None = None) -> int:
    file_path = Path(__file__).resolve()
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(file_path.parents[5]))
    parser.add_argument("--evidence-root", default=str(file_path.parents[1]))
    parsed = parser.parse_args(arguments)
    result = verify_evidence_pack(
        repo_root=parsed.repo_root,
        evidence_root=parsed.evidence_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(
            json.dumps(
                {
                    "contract": "weknora.830.ba0-verification-result.v1",
                    "status": "FAIL",
                    "reason": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
