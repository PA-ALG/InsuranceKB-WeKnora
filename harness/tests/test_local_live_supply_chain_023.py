"""OpenSpec 023 R2.1/R3.1/R3.3 trusted app supply-chain contracts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPO_ROOT / "deploy/local-live/weknora-app-source.lock.json"
PATCH_PATH = (
    REPO_ROOT
    / "deploy/local-live/patches/model-debug-access-log-redaction.patch"
)
VERIFIER_PATH = REPO_ROOT / "harness/scripts/verify_weknora_app_source.py"
WORKFLOW_PATH = (
    REPO_ROOT / ".github/workflows/weknora-app-local-live-image.yml"
)

UPSTREAM_REPOSITORY = "https://github.com/Tencent/WeKnora.git"
UPSTREAM_COMMIT = "5eefa70e6fc8f9ec27958779f91ece6cf685598c"
UPSTREAM_TREE = "a44f7eaeb40cf156d2893398046ffcb3094e5940"
DOCKERFILE_PATH = "docker/Dockerfile.app"
DOCKERFILE_SHA256 = (
    "be66005765bbc7db61851b07cd65529b0ee3c35d75f0eff84366d83a4cca3a32"
)
REQUIRED_ANCESTORS = (
    "505bc7ddec0feaef337610ad2f26d34a9e41a012",
    "3f516d7f317d2dbba6d1e8e5170db9ff1d052ca7",
    "94d18ea15a663974f0dc4dc4d9a43f20dca14d39",
    "abcecc870a7850d33b4a0d71d3845d0f3c4a1ae5",
    "800cea0826574f351141b6b3b7d615f5e0d837d6",
    "def92bb74fcde45dfc1be84cd6d63cf47113aa0b",
)
IMAGE_REPOSITORY = "ghcr.io/pa-alg/insurancekb-weknora-app"


def _load_verifier() -> ModuleType:
    assert VERIFIER_PATH.is_file(), "R2.1 source-lock verifier is missing"
    spec = importlib.util.spec_from_file_location(
        "verify_weknora_app_source_023", VERIFIER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_lock_json() -> dict[str, object]:
    assert LOCK_PATH.is_file(), "R2.1 WeKnora app source lock is missing"
    loaded = json.loads(LOCK_PATH.read_text())
    assert isinstance(loaded, dict)
    return loaded


def test_r2_1_source_lock_pins_real_app_dockerfile_and_security_ancestry() -> None:
    lock = _load_lock_json()

    assert set(lock) == {
        "schema_version",
        "repository",
        "commit",
        "tree",
        "dockerfile",
        "required_ancestors",
        "patch",
        "platform",
        "image_repository",
    }
    assert lock["schema_version"] == 1
    assert lock["repository"] == UPSTREAM_REPOSITORY
    assert lock["commit"] == UPSTREAM_COMMIT
    assert lock["tree"] == UPSTREAM_TREE
    assert lock["dockerfile"] == {
        "path": DOCKERFILE_PATH,
        "sha256": DOCKERFILE_SHA256,
    }
    assert lock["required_ancestors"] == list(REQUIRED_ANCESTORS)
    assert lock["platform"] == "linux/arm64"
    assert lock["image_repository"] == IMAGE_REPOSITORY

    patch = lock["patch"]
    assert isinstance(patch, dict)
    assert patch.get("path") == (
        "deploy/local-live/patches/model-debug-access-log-redaction.patch"
    )
    assert re.fullmatch(r"[0-9a-f]{64}", str(patch.get("sha256", "")))
    assert patch.get("sha256") == hashlib.sha256(PATCH_PATH.read_bytes()).hexdigest()


def test_r2_1_verifier_rejects_unknown_or_mutable_lock_fields(tmp_path: Path) -> None:
    module = _load_verifier()
    lock = _load_lock_json()

    unknown = dict(lock)
    unknown["unreviewed_override"] = "allowed"
    unknown_path = tmp_path / "unknown.json"
    unknown_path.write_text(json.dumps(unknown))
    with pytest.raises(module.SourceVerificationError, match="keys"):
        module.load_source_lock(unknown_path)

    mutable = dict(lock)
    mutable["image_repository"] = "docker.io/example/weknora-app:latest"
    mutable_path = tmp_path / "mutable.json"
    mutable_path.write_text(json.dumps(mutable))
    with pytest.raises(module.SourceVerificationError, match="GHCR"):
        module.load_source_lock(mutable_path)

    output_injection = dict(lock)
    output_injection["patch"] = {
        "path": "deploy/local-live/patches/reviewed.patch\nimage_repository=evil",
        "sha256": "0" * 64,
    }
    injection_path = tmp_path / "output-injection.json"
    injection_path.write_text(json.dumps(output_injection))
    with pytest.raises(module.SourceVerificationError, match="single-line"):
        module.load_source_lock(injection_path)


def test_r2_1_verifier_checks_hermetic_checkout_patch_and_dockerfile(
    tmp_path: Path,
) -> None:
    module = _load_verifier()
    checkout = tmp_path / "upstream"
    checkout.mkdir()

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(checkout), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    git("init")
    git("config", "user.name", "OpenSpec 023 test")
    git("config", "user.email", "openspec-023@example.invalid")
    git("remote", "add", "origin", UPSTREAM_REPOSITORY)

    dockerfile = checkout / DOCKERFILE_PATH
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    git("add", DOCKERFILE_PATH)
    git("commit", "-m", "synthetic security ancestor")
    required_ancestor = git("rev-parse", "HEAD")

    dockerfile.write_text("FROM scratch\nRUN echo locked\n", encoding="utf-8")
    git("add", DOCKERFILE_PATH)
    git("commit", "-m", "synthetic locked source")
    commit = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")

    patch_path = tmp_path / "synthetic.patch"
    patch_path.write_text(
        """diff --git a/docker/Dockerfile.app b/docker/Dockerfile.app
--- a/docker/Dockerfile.app
+++ b/docker/Dockerfile.app
@@ -1,2 +1,3 @@
 FROM scratch
 RUN echo locked
+RUN echo patched
""",
        encoding="utf-8",
    )
    source_lock = module.SourceLock(
        schema_version=1,
        repository=UPSTREAM_REPOSITORY,
        commit=commit,
        tree=tree,
        dockerfile=module.LockedFile(
            path=DOCKERFILE_PATH,
            sha256=hashlib.sha256(dockerfile.read_bytes()).hexdigest(),
        ),
        required_ancestors=(required_ancestor,),
        patch=module.LockedFile(
            path=patch_path.name,
            sha256=hashlib.sha256(patch_path.read_bytes()).hexdigest(),
        ),
        platform="linux/arm64",
        image_repository=IMAGE_REPOSITORY,
    )

    module.verify_checkout(source_lock, checkout, patch_path)
    subprocess.run(
        ["git", "-C", str(checkout), "apply", "--check", str(patch_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    with pytest.raises(module.SourceVerificationError, match="Dockerfile"):
        module.verify_checkout(source_lock, checkout, patch_path)


def test_r2_1_locked_patch_pins_verified_uv_installer_and_security_changes() -> None:
    patch = PATCH_PATH.read_text(encoding="utf-8")

    assert "[model debug response omitted]" in patch
    assert "TestR3_3ModelDebugResponseIsNeverWrittenToAccessLog" in patch
    assert "+.env.*" in patch
    assert "golang-migrate/migrate/v4/cmd/migrate@v4.19.1" in patch
    assert "@latest" in patch, "the patch must explicitly remove the mutable version"
    assert "https://astral.sh/uv/0.9.26/install.sh" in patch
    assert "09ace6a888bd5941b5d44f1177a9a8a6145552ec8aa81c51b1b57ff73e6b9e18" in patch
    assert "sha256sum -c" in patch


def test_r2_1_trusted_workflow_builds_only_locked_source_with_attestations() -> None:
    assert WORKFLOW_PATH.is_file(), "R2.1 trusted GHCR workflow is missing"
    workflow = WORKFLOW_PATH.read_text()

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "\n  push:" not in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "contents: read" in workflow
    assert "packages: write" in workflow
    assert "id-token: write" in workflow
    assert "attestations: write" in workflow
    assert "ubuntu-24.04-arm" in workflow

    for action_pin in (
        "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
        "actions/setup-go@924ae3a1cded613372ab5595356fb5720e22ba16",
        "docker/setup-buildx-action@8d2750c68a42422c14e847fe6c8ac0403b4cbd6f",
        "docker/login-action@c94ce9fb468520275223c153574b00df6fe4bcc9",
        "docker/build-push-action@10e90e3645eae34f1e60eeb005ba3a3d33f178e8",
        "actions/attest-build-provenance@e8998f949152b193b063cb0ec769d69d929409be",
    ):
        assert action_pin in workflow

    assert "verify_weknora_app_source.py emit" in workflow
    assert "verify_weknora_app_source.py verify" in workflow
    assert "git apply --check" in workflow
    assert "go test ./internal/middleware -run R3_3 -count=1" in workflow
    assert "context: ${{ runner.temp }}/weknora-source" in workflow
    assert "file: ${{ runner.temp }}/weknora-source/docker/Dockerfile.app" in workflow
    assert "platforms: ${{ steps.source.outputs.platform }}" in workflow
    assert (
        "tags: ${{ steps.source.outputs.image_repository }}:"
        "${{ steps.source.outputs.image_tag }}" in workflow
    )
    assert "provenance: mode=max" in workflow
    assert "sbom: true" in workflow
    assert "push-to-registry: true" in workflow
    assert "secrets." not in workflow


def test_r3_1_workflow_has_no_legacy_key_or_caller_controlled_source_fallback() -> None:
    workflow = WORKFLOW_PATH.read_text()

    assert "legacy" not in workflow.lower()
    assert "repository:" not in workflow.split("workflow_dispatch:", 1)[1].split(
        "permissions:", 1
    )[0]
    assert "commit:" not in workflow.split("workflow_dispatch:", 1)[1].split(
        "permissions:", 1
    )[0]
    assert "platform:" not in workflow.split("workflow_dispatch:", 1)[1].split(
        "permissions:", 1
    )[0]


def test_r3_3_patch_omits_complete_model_debug_response_envelope() -> None:
    assert PATCH_PATH.is_file(), "R3.3 model-debug log redaction patch is missing"
    patch = PATCH_PATH.read_text()

    assert "sanitizeResponseBodyForLog" in patch
    assert "[model debug response omitted]" in patch
    assert "TestR3_3ModelDebugResponseIsNeverWrittenToAccessLog" in patch
    for forbidden in (
        "private prompt",
        "private model output",
        "private reasoning",
        "private provider error",
    ):
        assert forbidden in patch, "the regression fixture must exercise every leak class"
