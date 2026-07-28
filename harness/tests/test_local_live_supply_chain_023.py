"""OpenSpec 023/045 trusted multi-image supply-chain contracts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPO_ROOT / "deploy/local-live/weknora-app-source.lock.json"
MANIFEST_PATH = REPO_ROOT / "deploy/upstream/weknora-adoption-target.json"
VERIFIER_PATH = REPO_ROOT / "harness/scripts/verify_weknora_app_source.py"
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/weknora-app-local-live-image.yml"
PROJECT_REPOSITORY = "https://github.com/PA-ALG/InsuranceKB-WeKnora.git"
UPSTREAM_REPOSITORY = "https://github.com/Tencent/WeKnora.git"
IMAGE_IDS = ("app", "frontend", "docreader")
IMAGE_PATHS = {
    "app": (".", "docker/Dockerfile.app"),
    "frontend": ("frontend", "frontend/Dockerfile"),
    "docreader": (".", "docker/Dockerfile.docreader"),
}


def _load_verifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "verify_weknora_app_source_023", VERIFIER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_json(path: Path) -> dict[str, object]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(path: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(path), *arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_source_lock_is_closed_and_pins_runtime_build_target_and_three_images() -> None:
    lock = _load_json(LOCK_PATH)
    manifest = _load_json(MANIFEST_PATH)

    assert set(lock) == {
        "schema_version",
        "repository",
        "commit",
        "tree",
        "platform",
        "build_source",
        "adoption_manifest",
        "reviewed_thin_report_sha256",
        "images",
    }
    assert lock["schema_version"] == 1
    assert lock["repository"] == UPSTREAM_REPOSITORY
    assert lock["platform"] == "linux/arm64"

    build_source = lock["build_source"]
    assert isinstance(build_source, dict)
    assert set(build_source) == {"repository", "commit", "tree"}
    assert build_source["repository"] == PROJECT_REPOSITORY
    assert len(str(build_source["commit"])) == 40
    assert len(str(build_source["tree"])) == 40
    assert set(str(build_source["commit"])) <= set("0123456789abcdef")
    assert set(str(build_source["tree"])) <= set("0123456789abcdef")

    adoption = lock["adoption_manifest"]
    assert isinstance(adoption, dict)
    assert set(adoption) == {"path", "sha256", "repository", "commit", "tree"}
    assert adoption["path"] == "deploy/upstream/weknora-adoption-target.json"
    assert adoption["sha256"] == _sha256(MANIFEST_PATH)
    assert adoption["repository"] == manifest["repository"]
    assert adoption["commit"] == manifest["commit"]
    assert adoption["tree"] == manifest["tree"]

    assert len(str(lock["reviewed_thin_report_sha256"])) == 64
    images = lock["images"]
    assert isinstance(images, dict)
    assert tuple(images) == IMAGE_IDS
    for image_id, (context, dockerfile_path) in IMAGE_PATHS.items():
        image = images[image_id]
        assert isinstance(image, dict)
        assert set(image) == {"repository", "context", "dockerfile"}
        assert image["repository"] == (
            f"ghcr.io/pa-alg/insurancekb-weknora-{image_id}"
        )
        assert image["context"] == context
        dockerfile = image["dockerfile"]
        assert isinstance(dockerfile, dict)
        assert dockerfile == {
            "path": dockerfile_path,
            "sha256": _sha256(REPO_ROOT / dockerfile_path),
        }


def test_verifier_rejects_unknown_mutable_or_incomplete_lock(tmp_path: Path) -> None:
    module = _load_verifier()
    lock = _load_json(LOCK_PATH)

    mutations: list[tuple[str, dict[str, object], str]] = []
    unknown = dict(lock)
    unknown["override"] = True
    mutations.append(("unknown", unknown, "keys"))

    mutable = json.loads(json.dumps(lock))
    mutable["images"]["app"]["repository"] += ":latest"
    mutations.append(("mutable", mutable, "tag-free"))

    missing = json.loads(json.dumps(lock))
    del missing["images"]["docreader"]
    mutations.append(("missing", missing, "app, frontend, and docreader"))

    for name, value, message in mutations:
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(module.SourceVerificationError, match=message):
            module.load_source_lock(path)


def test_verifier_checks_exact_merged_source_manifest_and_dockerfiles(
    tmp_path: Path,
) -> None:
    module = _load_verifier()
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.name", "OpenSpec 045 test")
    _git(repository, "config", "user.email", "openspec-045@example.invalid")
    _git(repository, "remote", "add", "origin", PROJECT_REPOSITORY)

    for _, (_, dockerfile_path) in IMAGE_PATHS.items():
        path = repository / dockerfile_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {dockerfile_path}\nFROM scratch\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "synthetic upstream target")
    target_commit = _git(repository, "rev-parse", "HEAD")
    target_tree = _git(repository, "rev-parse", "HEAD^{tree}")

    manifest_path = repository / "deploy/upstream/weknora-adoption-target.json"
    manifest_path.parent.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "repository": UPSTREAM_REPOSITORY,
        "commit": target_commit,
        "tree": target_tree,
        "release_ancestor": {"tag": "v1.0.0", "commit": target_commit},
        "required_capability_commits": [target_commit],
        "official_migration_head": 1,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "synthetic merged code")
    source_commit = _git(repository, "rev-parse", "HEAD")
    source_tree = _git(repository, "rev-parse", "HEAD^{tree}")

    marker = repository / ".github/workflows/trusted.yml"
    marker.parent.mkdir(parents=True)
    marker.write_text("name: trusted\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "synthetic workflow")
    workflow_commit = _git(repository, "rev-parse", "HEAD")

    source_checkout = tmp_path / "source"
    workflow_checkout = tmp_path / "workflow"
    _git(tmp_path, "clone", str(repository), str(source_checkout))
    _git(tmp_path, "clone", str(repository), str(workflow_checkout))
    _git(source_checkout, "checkout", "--detach", source_commit)
    _git(workflow_checkout, "checkout", "--detach", workflow_commit)
    _git(source_checkout, "remote", "set-url", "origin", PROJECT_REPOSITORY)
    _git(workflow_checkout, "remote", "set-url", "origin", PROJECT_REPOSITORY)

    lock_value = {
        "schema_version": 1,
        "repository": UPSTREAM_REPOSITORY,
        "commit": target_commit,
        "tree": target_tree,
        "platform": "linux/arm64",
        "build_source": {
            "repository": PROJECT_REPOSITORY,
            "commit": source_commit,
            "tree": source_tree,
        },
        "adoption_manifest": {
            "path": "deploy/upstream/weknora-adoption-target.json",
            "sha256": _sha256(source_checkout / MANIFEST_PATH.relative_to(REPO_ROOT)),
            "repository": UPSTREAM_REPOSITORY,
            "commit": target_commit,
            "tree": target_tree,
        },
        "reviewed_thin_report_sha256": "0" * 64,
        "images": {
            image_id: {
                "repository": f"ghcr.io/pa-alg/insurancekb-weknora-{image_id}",
                "context": context,
                "dockerfile": {
                    "path": dockerfile_path,
                    "sha256": _sha256(source_checkout / dockerfile_path),
                },
            }
            for image_id, (context, dockerfile_path) in IMAGE_PATHS.items()
        },
    }
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock_value), encoding="utf-8")
    lock = module.load_source_lock(lock_path)

    module.verify_source(lock, source_checkout, workflow_checkout)
    (source_checkout / "docker/Dockerfile.app").write_text("FROM busybox\n")
    with pytest.raises(module.SourceVerificationError, match="clean|Dockerfile"):
        module.verify_source(lock, source_checkout, workflow_checkout)


def test_manual_thin_report_requires_exact_reviewed_digest(tmp_path: Path) -> None:
    module = _load_verifier()
    lock = module.load_source_lock(LOCK_PATH)
    report_value = {
        "schema_version": 1,
        "verdict": "manual_review_required",
        "hard_checks": {"status": "pass", "code": "ok"},
        "target": {
            "repository": lock.adoption_manifest.repository,
            "commit": lock.adoption_manifest.commit,
            "tree": lock.adoption_manifest.tree,
        },
        "official_migrations": {"status": "merged"},
        "plugin_contract": {"status": "valid"},
    }
    report = tmp_path / "report.json"
    report.write_text(json.dumps(report_value, sort_keys=True) + "\n", encoding="utf-8")
    digest = _sha256(report)
    reviewed = lock._replace(reviewed_thin_report_sha256=digest)

    module.verify_thin_report(reviewed, report)
    report.write_text(
        json.dumps({**report_value, "overlaps": {"unexpected": ["path"]}}, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(module.SourceVerificationError, match="reviewed digest"):
        module.verify_thin_report(reviewed, report)

    report_value["verdict"] = "block"
    report.write_text(json.dumps(report_value) + "\n", encoding="utf-8")
    with pytest.raises(module.SourceVerificationError, match="blocked"):
        module.verify_thin_report(reviewed, report)


def test_emit_outputs_are_closed_and_share_one_source_and_lock(tmp_path: Path) -> None:
    module = _load_verifier()
    lock = module.load_source_lock(LOCK_PATH)
    output = tmp_path / "github-output"
    module.emit_github_outputs(lock, LOCK_PATH, output)
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())

    assert set(values) == {
        "build_repository",
        "build_commit",
        "build_tree",
        "target_repository",
        "target_commit",
        "platform",
        "lock_sha256",
        "image_tag",
        "image_matrix",
    }
    matrix = json.loads(values["image_matrix"])
    assert [item["id"] for item in matrix["include"]] == list(IMAGE_IDS)
    assert all(item["source_commit"] == values["build_commit"] for item in matrix["include"])
    assert all(item["source_tree"] == values["build_tree"] for item in matrix["include"])
    assert all(item["lock_sha256"] == values["lock_sha256"] for item in matrix["include"])


def test_trusted_workflow_is_main_only_gated_and_builds_three_attested_images() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    dispatch = workflow.split("workflow_dispatch:", 1)[1].split("permissions:", 1)[0]
    assert "inputs:" not in dispatch
    assert "pull_request:" not in workflow
    assert "\n  push:" not in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "verify_weknora_app_source.py verify" in workflow
    assert "prepare_weknora_adoption.py check" in workflow
    assert "verify_weknora_app_source.py verify-report" in workflow
    for required_gate in (
        "test_r3_3_retry_vlm_consumes_marker_after_identity_before_single_reparse",
        "test_s1_2_only_bound_space_builds_scope",
        "test_t3_readiness_starts_not_ready_then_checks_db_and_uses_fresh_cache",
        "go test ./internal/database",
        "TestGetKnowledgeRevision",
        "TestKnowledgeRevisionManifestDigestVectors",
        "TestKnowledgeRevisionManifestMigrationContract",
    ):
        assert required_gate in workflow
    assert "manual_review_required" not in workflow
    assert "git apply" not in workflow
    assert "patch_sha256" not in workflow
    assert "80a5003" not in workflow
    assert "0.7.1" not in workflow
    assert "0.6.3" not in workflow

    gate_position = workflow.index("verify-report")
    login_position = workflow.index("Log in to GHCR")
    push_position = workflow.index("push: true")
    assert gate_position < login_position < push_position
    assert "fromJSON(needs.validate.outputs.image_matrix)" in workflow
    assert "provenance: mode=max" in workflow
    assert "sbom: true" in workflow
    assert "push-to-registry: true" in workflow
    assert "npm test -- src/utils/wikiLineDiff.test.ts" in workflow
    assert "\n          npm test\n" not in workflow
    assert "io.insurancekb.source.tree=" in workflow
    assert "io.insurancekb.source.lock.sha256=" in workflow
    assert "secrets." not in workflow
    assert "weknora-worker" not in workflow


def test_model_debug_redaction_is_in_merged_source_not_a_workflow_patch() -> None:
    source = (REPO_ROOT / "internal/middleware/logger.go").read_text(encoding="utf-8")
    test_source = (REPO_ROOT / "internal/middleware/logger_test.go").read_text(
        encoding="utf-8"
    )
    dockerfile = (REPO_ROOT / "docker/Dockerfile.app").read_text(encoding="utf-8")
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "[model debug response omitted]" in source
    assert "TestR3_3ModelDebugResponseIsNeverWrittenToAccessLog" in test_source
    assert "migrate/v4/cmd/migrate@v4.19.1" in dockerfile
    assert "migrate/v4/cmd/migrate@latest" not in dockerfile
    assert "https://astral.sh/uv/0.9.26/install.sh" in dockerfile
    assert (
        "09ace6a888bd5941b5d44f1177a9a8a6145552ec8aa81c51b1b57ff73e6b9e18"
        in dockerfile
    )
    assert "sha256sum -c -" in dockerfile
    assert "git apply" not in workflow
