"""Focused contracts for the minimal 830 BA0 evidence-pack verifier."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = (
    REPO_ROOT
    / "docs/insurance-kb/evidence/830-ba0/tools/verify_ba0_evidence.py"
)
ORIGIN_MAIN_BASE = "0e7a26568a2164f9501e409f38fee0d4a62539cb"
ORIGIN_MAIN_TREE = "b96aa35fd2fe86283757deb258920c489de4b4b6"
IMAGE_ID = "sha256:" + "d" * 64
CANONICAL_BYTES = b'{"fixture":"ba0-canonical-identity"}'
ARTIFACT_IDENTITY = "sha256:" + hashlib.sha256(CANONICAL_BYTES).hexdigest()
EFFECTS = {
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


def _verifier_module() -> ModuleType:
    assert VERIFIER_PATH.is_file(), f"planned BA0 verifier missing: {VERIFIER_PATH}"
    spec = importlib.util.spec_from_file_location("ba0_evidence_verifier", VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(*arguments: str) -> str:
    return subprocess.check_output(
        ("git", *arguments), cwd=REPO_ROOT, text=True
    ).strip()


def _canonical_json(value: object, *, newline: bool = False) -> bytes:
    suffix = "\n" if newline else ""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + suffix
    ).encode()


def _canonical_file_sha(path: Path) -> str:
    return hashlib.sha256(
        _canonical_json(json.loads(path.read_text(encoding="utf-8")))
    ).hexdigest()


def _raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


def _labels(head: str, manifest_sha: str, lock_sha: str) -> dict[str, str]:
    return {
        "io.insurancekb.app.artifact-identity": ARTIFACT_IDENTITY,
        "io.insurancekb.app.build-source-head": head,
        "io.insurancekb.app.manifest-sha256": manifest_sha,
        "io.insurancekb.app.dependency-lock-sha256": lock_sha,
        "io.insurancekb.app.target": "runtime",
        "io.insurancekb.app.platform": "linux/arm64",
    }


def _d2_receipt(
    *, head: str, manifest_sha: str, lock_sha: str, selector: str, builds: int
) -> dict[str, Any]:
    return {
        "contract": "ba0-app-build-receipt.v1",
        "status": "PASS",
        "selector": selector,
        "artifact_identity": ARTIFACT_IDENTITY,
        "image_id": IMAGE_ID,
        "build_source_head": head,
        "integration_head": head,
        "manifest_sha256": manifest_sha,
        "dependency_lock_sha256": lock_sha,
        "platform": "linux/arm64",
        "target": "runtime",
        "labels": _labels(head, manifest_sha, lock_sha),
        "candidate_image_ids": [] if selector == "BUILD_AFFECTED" else [IMAGE_ID],
        "build_invocations": builds,
    }


def _write_pack(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    pack = tmp_path / "830-ba0"
    head = _git("rev-parse", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    manifest_sha = _canonical_file_sha(
        REPO_ROOT / "deploy/local-build/app-build-inputs.v1.json"
    )
    lock_sha = _canonical_file_sha(
        REPO_ROOT / "deploy/local-build/app-external-dependencies.v1.json"
    )
    paths = {
        "initial": pack / "d2/initialization-build.json",
        "reuse": pack / "d2/same-identity-reuse.json",
        "d3": pack / "d3/exact-image-smoke.json",
        "closeout": pack / "ba0-closeout.json",
    }
    _write_json(
        paths["initial"],
        _d2_receipt(
            head=head,
            manifest_sha=manifest_sha,
            lock_sha=lock_sha,
            selector="BUILD_AFFECTED",
            builds=1,
        ),
    )
    _write_json(
        paths["reuse"],
        _d2_receipt(
            head=head,
            manifest_sha=manifest_sha,
            lock_sha=lock_sha,
            selector="REUSE",
            builds=0,
        ),
    )
    _write_json(
        paths["d3"],
        {
            "contract": "ba0-container-artifact-smoke.v1",
            "status": "PASS",
            "scope": "CONTAINER_ARTIFACT_SMOKE",
            "artifact_identity": ARTIFACT_IDENTITY,
            "build_source_head": head,
            "integration_head": head,
            "image_id": IMAGE_ID,
            "runtime_image_id": IMAGE_ID,
            "project": "insurancekb-ba0-d3-0123456789abcdef",
            "build_invocations": 0,
            "pull_invocations": 0,
            "cleanup": "PASS",
            "effects": dict(EFFECTS),
        },
    )
    closeout: dict[str, Any] = {
        "contract": "weknora.830.ba0-closeout.v1",
        "evidence_status": "PASS",
        "state": {
            "ba0_status": "WIP",
            "current_authorization": "BA0_ONLY",
            "current_product_goal": "NONE",
            "g2_status": "LOCKED_PENDING_BA0_PASS_AND_EXPLICIT_USER_AUTHORIZATION",
            "next_action": "INDEPENDENT_REVIEW_AND_CLOSEOUT",
        },
        "identity": {
            "origin_main_base": ORIGIN_MAIN_BASE,
            "origin_main_tree": ORIGIN_MAIN_TREE,
            "implementation_head": head,
            "implementation_tree": tree,
            "d2_build_source_head": head,
            "d2_build_source_tree": tree,
            "execution_integration_head": head,
            "image_id": IMAGE_ID,
            "artifact_identity": ARTIFACT_IDENTITY,
        },
        "inputs": {
            "manifest": {
                "path": "deploy/local-build/app-build-inputs.v1.json",
                "sha256": manifest_sha,
            },
            "dependency_lock": {
                "path": "deploy/local-build/app-external-dependencies.v1.json",
                "sha256": lock_sha,
            },
        },
        "receipts": {
            "initialization_build": {
                "path": "d2/initialization-build.json",
                "sha256": _raw_sha(paths["initial"]),
            },
            "same_identity_reuse": {
                "path": "d2/same-identity-reuse.json",
                "sha256": _raw_sha(paths["reuse"]),
            },
            "exact_image_smoke": {
                "path": "d3/exact-image-smoke.json",
                "sha256": _raw_sha(paths["d3"]),
            },
        },
        "build_budget": {"authorized": 1, "used": 1},
        "cache_probe": {
            "status": "PASS",
            "source": "docker/Dockerfile.app",
            "authority": False,
            "producer_consumer_contract_verified": True,
        },
        "g1_history": {"status": "PASS", "changed_paths": 0},
        "effects": dict(EFFECTS),
        "measurements": {
            "exact_lookup": {
                "status": "NOT_MEASURED",
                "reason": "NO_MONOTONIC_LOOKUP_SAMPLE_CAPTURED",
            },
            "natural_incremental_build": {
                "status": "NOT_MEASURED",
                "reason": "NO_SECOND_IDENTITY_OR_BUILD_CREATED",
            },
        },
        "self_sha256": None,
    }
    closeout["self_sha256"] = hashlib.sha256(
        _canonical_json(closeout, newline=True)
    ).hexdigest()
    _write_json(paths["closeout"], closeout)
    return pack, paths


def _resign_closeout(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    document["self_sha256"] = None
    document["self_sha256"] = hashlib.sha256(
        _canonical_json(document, newline=True)
    ).hexdigest()
    _write_json(path, document)


def _fixture_identity_resolver(
    repo_root: Path, build_source_head: str, integration_head: str
) -> dict[str, Any]:
    del repo_root
    return {
        "canonical_bytes": CANONICAL_BYTES,
        "artifact_identity": ARTIFACT_IDENTITY,
        "build_source_head": build_source_head,
        "integration_head": integration_head,
        "manifest_sha256": _canonical_file_sha(
            REPO_ROOT / "deploy/local-build/app-build-inputs.v1.json"
        ),
        "dependency_lock_sha256": _canonical_file_sha(
            REPO_ROOT / "deploy/local-build/app-external-dependencies.v1.json"
        ),
        "platform": "linux/arm64",
        "target": "runtime",
    }


def _verify(module: ModuleType, pack: Path) -> dict[str, Any]:
    return module.verify_evidence_pack(
        repo_root=REPO_ROOT,
        evidence_root=pack,
        identity_resolver=_fixture_identity_resolver,
    )


def _refresh_receipt_hash(
    paths: dict[str, Path], receipt_name: str, receipt_key: str
) -> None:
    closeout = json.loads(paths["closeout"].read_text(encoding="utf-8"))
    closeout["receipts"][receipt_name]["sha256"] = _raw_sha(paths[receipt_key])
    _write_json(paths["closeout"], closeout)
    _resign_closeout(paths["closeout"])


def test_ba0_evidence_pack_verifies_complete_chain(tmp_path: Path) -> None:
    module = _verifier_module()
    pack, _ = _write_pack(tmp_path)

    result = _verify(module, pack)

    assert result == {
        "contract": "weknora.830.ba0-verification-result.v1",
        "status": "PASS",
        "artifact_identity": ARTIFACT_IDENTITY,
        "image_id": IMAGE_ID,
        "first_request_build_invocations": 1,
        "second_request_build_invocations": 0,
        "d3_build_invocations": 0,
        "d3_pull_invocations": 0,
        "forbidden_effects": 0,
        "g1_history_changed_paths": 0,
        "ba0_status": "WIP",
        "g2_status": "LOCKED_PENDING_BA0_PASS_AND_EXPLICIT_USER_AUTHORIZATION",
    }


Mutation = Callable[[dict[str, Path]], None]


def _mutate_json(path: Path, mutation: Callable[[dict[str, Any]], None]) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    mutation(document)
    _write_json(path, document)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda paths: _mutate_json(
                paths["closeout"],
                lambda value: value["inputs"]["manifest"].update(sha256="f" * 64),
            ),
            "self.hash|manifest|sha256",
        ),
        (
            lambda paths: _mutate_json(
                paths["initial"],
                lambda value: value.update(build_invocations=2),
            ),
            "receipt hash|build|budget",
        ),
        (
            lambda paths: _mutate_json(
                paths["reuse"],
                lambda value: value.update(selector="BUILD_AFFECTED", build_invocations=1),
            ),
            "receipt hash|reuse|build",
        ),
        (
            lambda paths: _mutate_json(
                paths["d3"], lambda value: value.update(pull_invocations=1)
            ),
            "receipt hash|pull|D3",
        ),
    ),
    ids=("manifest-hash", "build-budget", "reuse-build", "d3-pull"),
)
def test_ba0_evidence_pack_rejects_tampered_receipts_or_hashes(
    tmp_path: Path, mutation: Mutation, message: str
) -> None:
    module = _verifier_module()
    pack, paths = _write_pack(tmp_path)
    mutation(paths)

    with pytest.raises(AssertionError, match=message):
        _verify(module, pack)


@pytest.mark.parametrize(
    ("receipt_name", "receipt_key", "mutation", "message"),
    (
        (
            "initialization_build",
            "initial",
            lambda value: value.update(build_invocations=2),
            "first request|build|budget",
        ),
        (
            "same_identity_reuse",
            "reuse",
            lambda value: value.update(
                selector="BUILD_AFFECTED", build_invocations=1
            ),
            "second request|reuse|build",
        ),
        (
            "same_identity_reuse",
            "reuse",
            lambda value: value.update(image_id="sha256:" + "e" * 64),
            "reuse|candidate|drift|image",
        ),
        (
            "exact_image_smoke",
            "d3",
            lambda value: value.update(pull_invocations=1),
            "pull|D3",
        ),
        (
            "exact_image_smoke",
            "d3",
            lambda value: value["effects"].update(networks=1),
            "D3|effect|network",
        ),
    ),
    ids=("first-build-limit", "second-build-zero", "same-image", "d3-pull", "d3-network"),
)
def test_ba0_evidence_pack_rejects_semantic_drift_with_valid_outer_hashes(
    tmp_path: Path,
    receipt_name: str,
    receipt_key: str,
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    module = _verifier_module()
    pack, paths = _write_pack(tmp_path)
    _mutate_json(paths[receipt_key], mutation)
    _refresh_receipt_hash(paths, receipt_name, receipt_key)

    with pytest.raises(AssertionError, match=message):
        _verify(module, pack)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda value: value["inputs"]["manifest"].update(sha256="f" * 64),
            "manifest|sha256",
        ),
        (
            lambda value: value["inputs"]["dependency_lock"].update(
                sha256="e" * 64
            ),
            "dependency.lock|sha256",
        ),
        (
            lambda value: value["effects"].update(provider_model=1),
            "effect|provider",
        ),
        (
            lambda value: value["measurements"]["exact_lookup"].update(reason=""),
            "NOT_MEASURED|reason",
        ),
        (
            lambda value: value["cache_probe"].update(authority=True),
            "cache|authority",
        ),
        (
            lambda value: value["g1_history"].update(changed_paths=1),
            "G1|history|changed",
        ),
        (
            lambda value: value.update(api_token="CANARY-SECRET-IN-EVIDENCE"),
            "secret|credential|token",
        ),
        (
            lambda value: value["measurements"]["exact_lookup"].update(
                reason="CANARY-SECRET-IN-ALLOWED-FIELD"
            ),
            "secret|credential|value",
        ),
    ),
    ids=(
        "manifest-hash",
        "lock-hash",
        "provider-effect",
        "measurement-reason",
        "cache-authority",
        "g1-history",
        "secret-key",
        "secret-value",
    ),
)
def test_ba0_evidence_pack_rejects_invalid_closeout_claims(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    module = _verifier_module()
    pack, paths = _write_pack(tmp_path)
    _mutate_json(paths["closeout"], mutation)
    _resign_closeout(paths["closeout"])

    with pytest.raises(AssertionError, match=message):
        _verify(module, pack)


def test_ba0_evidence_pack_accepts_final_return_state(tmp_path: Path) -> None:
    module = _verifier_module()
    pack, paths = _write_pack(tmp_path)

    def close(value: dict[str, Any]) -> None:
        value["state"] = {
            "ba0_status": "PASS",
            "current_authorization": "NONE",
            "current_product_goal": "NONE",
            "g2_status": "LOCKED_PENDING_EXPLICIT_USER_AUTHORIZATION",
            "next_action": "RETURN_TO_USER_FOR_G2_AUTHORIZATION",
        }

    _mutate_json(paths["closeout"], close)
    _resign_closeout(paths["closeout"])

    result = _verify(module, pack)
    assert result["ba0_status"] == "PASS"
    assert result["g2_status"] == "LOCKED_PENDING_EXPLICIT_USER_AUTHORIZATION"


def test_ba0_closeout_self_hash_is_required(tmp_path: Path) -> None:
    module = _verifier_module()
    pack, paths = _write_pack(tmp_path)
    _mutate_json(
        paths["closeout"], lambda value: value.update(evidence_status="TAMPERED")
    )

    with pytest.raises(AssertionError, match="self.hash"):
        _verify(module, pack)


def test_ba0_evidence_pack_rejects_recomputed_identity_disagreement(
    tmp_path: Path,
) -> None:
    module = _verifier_module()
    pack, _ = _write_pack(tmp_path)

    def disagree(
        repo_root: Path, build_source_head: str, integration_head: str
    ) -> dict[str, Any]:
        result = _fixture_identity_resolver(
            repo_root, build_source_head, integration_head
        )
        result["artifact_identity"] = "sha256:" + "f" * 64
        return result

    with pytest.raises(AssertionError, match="recomputed|canonical|identity"):
        module.verify_evidence_pack(
            repo_root=REPO_ROOT,
            evidence_root=pack,
            identity_resolver=disagree,
        )


def test_ba0_default_identity_recomputation_rejects_fabricated_pack(
    tmp_path: Path,
) -> None:
    module = _verifier_module()
    pack, _ = _write_pack(tmp_path)

    with pytest.raises(AssertionError, match="recomputed|identity"):
        module.verify_evidence_pack(repo_root=REPO_ROOT, evidence_root=pack)


def test_ba0_verifier_fails_closed_under_optimized_python(tmp_path: Path) -> None:
    _verifier_module()
    pack, _ = _write_pack(tmp_path)

    result = subprocess.run(
        (
            sys.executable,
            "-O",
            str(VERIFIER_PATH),
            "--repo-root",
            str(REPO_ROOT),
            "--evidence-root",
            str(pack),
        ),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "optimized Python" in result.stderr
    assert '"status": "PASS"' not in result.stdout


def test_ba0_g1_history_check_covers_post_integration_and_dirty_state(
    tmp_path: Path,
) -> None:
    module = _verifier_module()
    repo = tmp_path / "repository"
    g1 = repo / "docs/insurance-kb/evidence/830-g1"
    g1.mkdir(parents=True)
    (g1 / "frozen.json").write_text("{}\n", encoding="utf-8")
    subprocess.run(("git", "init", "-q"), cwd=repo, check=True)

    def commit(message: str) -> str:
        subprocess.run(("git", "add", "."), cwd=repo, check=True)
        subprocess.run(
            (
                "git",
                "-c",
                "user.name=BA0 Test",
                "-c",
                "user.email=ba0-test@example.invalid",
                "commit",
                "-q",
                "-m",
                message,
            ),
            cwd=repo,
            check=True,
        )
        return subprocess.check_output(
            ("git", "rev-parse", "HEAD"), cwd=repo, text=True
        ).strip()

    base = commit("base")
    (repo / "other.txt").write_text("integration\n", encoding="utf-8")
    integration = commit("integration")
    (g1 / "frozen.json").write_text('{"changed":true}\n', encoding="utf-8")
    commit("post-integration G1 drift")
    (g1 / "dirty.json").write_text("{}\n", encoding="utf-8")

    changed = module._g1_changed_paths(repo, base, integration)

    assert changed == [
        "docs/insurance-kb/evidence/830-g1/dirty.json",
        "docs/insurance-kb/evidence/830-g1/frozen.json",
    ]


def test_ba0_identity_custody_connects_frozen_origin_to_implementation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _verifier_module()
    pack, _ = _write_pack(tmp_path)
    calls: list[tuple[str, ...]] = []
    original = module._run

    def observe(repo_root: Path, arguments: tuple[str, ...]) -> str:
        calls.append(arguments)
        return original(repo_root, arguments)

    monkeypatch.setattr(module, "_run", observe)
    _verify(module, pack)
    implementation = _git("rev-parse", "HEAD")

    assert (
        "git",
        "merge-base",
        "--is-ancestor",
        ORIGIN_MAIN_BASE,
        implementation,
    ) in calls
