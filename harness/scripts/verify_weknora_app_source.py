#!/usr/bin/env python3
"""Verify the reviewed source used to build trusted WeKnora images."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import NamedTuple, NoReturn

_SHA_RE = re.compile(r"[0-9a-f]{40}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_LOCK_KEYS = {
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
_IDENTITY_KEYS = {"repository", "commit", "tree"}
_MANIFEST_KEYS = {"path", "sha256", "repository", "commit", "tree"}
_IMAGE_KEYS = {"repository", "context", "dockerfile"}
_FILE_KEYS = {"path", "sha256"}
_UPSTREAM_REPOSITORY = "https://github.com/Tencent/WeKnora.git"
_PROJECT_REPOSITORY = "https://github.com/PA-ALG/InsuranceKB-WeKnora.git"
_PLATFORM = "linux/arm64"
_IMAGE_LAYOUT = {
    "app": (
        "ghcr.io/pa-alg/insurancekb-weknora-app",
        ".",
        "docker/Dockerfile.app",
    ),
    "frontend": (
        "ghcr.io/pa-alg/insurancekb-weknora-frontend",
        "frontend",
        "frontend/Dockerfile",
    ),
    "docreader": (
        "ghcr.io/pa-alg/insurancekb-weknora-docreader",
        ".",
        "docker/Dockerfile.docreader",
    ),
}


class SourceVerificationError(ValueError):
    """Raised when an input differs from the reviewed source lock."""


class LockedFile(NamedTuple):
    path: str
    sha256: str


class GitIdentity(NamedTuple):
    repository: str
    commit: str
    tree: str


class AdoptionManifest(NamedTuple):
    path: str
    sha256: str
    repository: str
    commit: str
    tree: str


class LockedImage(NamedTuple):
    repository: str
    context: str
    dockerfile: LockedFile


class SourceLock(NamedTuple):
    schema_version: int
    repository: str
    commit: str
    tree: str
    platform: str
    build_source: GitIdentity
    adoption_manifest: AdoptionManifest
    reviewed_thin_report_sha256: str
    images: tuple[tuple[str, LockedImage], ...]


def _fail(message: str) -> NoReturn:
    raise SourceVerificationError(message)


def _expect_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _fail(f"{label} must be an object")
    return value


def _expect_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{label} must be a non-empty string")
    if any(character in value for character in ("\n", "\r", "\x00")):
        _fail(f"{label} must be a single-line string")
    return value


def _expect_sha(value: object, label: str, pattern: re.Pattern[str]) -> str:
    digest = _expect_string(value, label)
    if pattern.fullmatch(digest) is None:
        _fail(f"{label} must be a full lowercase digest")
    return digest


def _expect_path(value: object, label: str) -> str:
    path = _expect_string(value, label)
    pure_path = PurePosixPath(path)
    if pure_path.is_absolute() or ".." in pure_path.parts or path != pure_path.as_posix():
        _fail(f"{label} must be a normalized relative path")
    return path


def _normalize_repository(value: str) -> str:
    return value.removesuffix("/").removesuffix(".git")


def _expect_identity(value: object, label: str, repository: str) -> GitIdentity:
    item = _expect_object(value, label)
    if set(item) != _IDENTITY_KEYS:
        _fail(f"{label} keys do not match the closed schema")
    actual_repository = _expect_string(item.get("repository"), f"{label}.repository")
    if _normalize_repository(actual_repository) != _normalize_repository(repository):
        _fail(f"{label}.repository is not the reviewed repository")
    return GitIdentity(
        repository=actual_repository,
        commit=_expect_sha(item.get("commit"), f"{label}.commit", _SHA_RE),
        tree=_expect_sha(item.get("tree"), f"{label}.tree", _SHA_RE),
    )


def _expect_locked_file(value: object, label: str) -> LockedFile:
    item = _expect_object(value, label)
    if set(item) != _FILE_KEYS:
        _fail(f"{label} keys do not match the closed schema")
    return LockedFile(
        path=_expect_path(item.get("path"), f"{label}.path"),
        sha256=_expect_sha(item.get("sha256"), f"{label}.sha256", _SHA256_RE),
    )


def load_source_lock(path: Path) -> SourceLock:
    """Parse and strictly validate the reviewed JSON source lock."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceVerificationError("source lock is unreadable") from exc
    data = _expect_object(raw, "source lock")
    if set(data) != _LOCK_KEYS:
        _fail("source lock keys do not match the reviewed schema")
    if data.get("schema_version") != 1:
        _fail("source lock schema_version must be 1")

    repository = _expect_string(data.get("repository"), "repository")
    if repository != _UPSTREAM_REPOSITORY:
        _fail("repository must preserve the Tencent runtime baseline")
    commit = _expect_sha(data.get("commit"), "commit", _SHA_RE)
    tree = _expect_sha(data.get("tree"), "tree", _SHA_RE)
    platform = _expect_string(data.get("platform"), "platform")
    if platform != _PLATFORM:
        _fail("platform must be the reviewed linux/arm64 target")

    build_source = _expect_identity(
        data.get("build_source"), "build_source", _PROJECT_REPOSITORY
    )

    manifest_data = _expect_object(data.get("adoption_manifest"), "adoption_manifest")
    if set(manifest_data) != _MANIFEST_KEYS:
        _fail("adoption_manifest keys do not match the closed schema")
    manifest_identity = _expect_identity(
        {
            key: manifest_data.get(key)
            for key in ("repository", "commit", "tree")
        },
        "adoption_manifest",
        _UPSTREAM_REPOSITORY,
    )
    adoption_manifest = AdoptionManifest(
        path=_expect_path(manifest_data.get("path"), "adoption_manifest.path"),
        sha256=_expect_sha(
            manifest_data.get("sha256"), "adoption_manifest.sha256", _SHA256_RE
        ),
        repository=manifest_identity.repository,
        commit=manifest_identity.commit,
        tree=manifest_identity.tree,
    )
    reviewed_digest = _expect_sha(
        data.get("reviewed_thin_report_sha256"),
        "reviewed_thin_report_sha256",
        _SHA256_RE,
    )

    images_data = _expect_object(data.get("images"), "images")
    if tuple(images_data) != tuple(_IMAGE_LAYOUT):
        _fail("images must contain app, frontend, and docreader in reviewed order")
    images: list[tuple[str, LockedImage]] = []
    for image_id, expected in _IMAGE_LAYOUT.items():
        image_data = _expect_object(images_data.get(image_id), f"images.{image_id}")
        if set(image_data) != _IMAGE_KEYS:
            _fail(f"images.{image_id} keys do not match the closed schema")
        repository_value = _expect_string(
            image_data.get("repository"), f"images.{image_id}.repository"
        )
        context = _expect_path(image_data.get("context"), f"images.{image_id}.context")
        dockerfile = _expect_locked_file(
            image_data.get("dockerfile"), f"images.{image_id}.dockerfile"
        )
        if (repository_value, context, dockerfile.path) != expected:
            _fail(f"images.{image_id} must use the reviewed tag-free image layout")
        if any(marker in repository_value for marker in ("@", ":")):
            _fail(f"images.{image_id}.repository must be tag-free")
        images.append(
            (
                image_id,
                LockedImage(
                    repository=repository_value,
                    context=context,
                    dockerfile=dockerfile,
                ),
            )
        )

    return SourceLock(
        schema_version=1,
        repository=repository,
        commit=commit,
        tree=tree,
        platform=platform,
        build_source=build_source,
        adoption_manifest=adoption_manifest,
        reviewed_thin_report_sha256=reviewed_digest,
        images=tuple(images),
    )


def _git(checkout: Path, *arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ("git", "-C", str(checkout), *arguments),
        check=False,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        _fail(f"git verification failed for {arguments[0]}")
    return completed.stdout.strip()


def _require_ancestor(checkout: Path, ancestor: str, descendant: str, label: str) -> None:
    completed = subprocess.run(
        ("git", "-C", str(checkout), "merge-base", "--is-ancestor", ancestor, descendant),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        _fail(f"{label} is not an ancestor of the reviewed source")


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise SourceVerificationError("locked file is unreadable") from exc


def _verify_repository(checkout: Path, expected: str, label: str) -> None:
    actual = _git(checkout, "remote", "get-url", "origin")
    if _normalize_repository(actual) != _normalize_repository(expected):
        _fail(f"{label} repository does not match the lock")


def verify_source(
    lock: SourceLock, source_checkout: Path, workflow_checkout: Path
) -> None:
    """Verify that one clean merged source is used by all image builds."""

    if not source_checkout.is_dir() or not workflow_checkout.is_dir():
        _fail("source or workflow checkout is missing")
    _verify_repository(source_checkout, lock.build_source.repository, "source checkout")
    _verify_repository(
        workflow_checkout, lock.build_source.repository, "workflow checkout"
    )
    if _git(source_checkout, "rev-parse", "HEAD") != lock.build_source.commit:
        _fail("source checkout commit does not match the lock")
    if _git(source_checkout, "rev-parse", "HEAD^{tree}") != lock.build_source.tree:
        _fail("source checkout tree does not match the lock")
    if _git(source_checkout, "status", "--porcelain", "--untracked-files=all"):
        _fail("source checkout must be clean")

    workflow_commit = _git(workflow_checkout, "rev-parse", "HEAD")
    _require_ancestor(
        workflow_checkout,
        lock.build_source.commit,
        workflow_commit,
        "locked build source",
    )
    _require_ancestor(
        source_checkout,
        lock.adoption_manifest.commit,
        lock.build_source.commit,
        "adoption target",
    )

    manifest_path = source_checkout / lock.adoption_manifest.path
    if _sha256(manifest_path) != lock.adoption_manifest.sha256:
        _fail("adoption manifest SHA-256 does not match the lock")
    try:
        manifest = _expect_object(
            json.loads(manifest_path.read_text(encoding="utf-8")), "adoption manifest"
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceVerificationError("adoption manifest is unreadable") from exc
    for key, expected in (
        ("repository", lock.adoption_manifest.repository),
        ("commit", lock.adoption_manifest.commit),
        ("tree", lock.adoption_manifest.tree),
    ):
        if manifest.get(key) != expected:
            _fail(f"adoption manifest {key} does not match the lock")

    for image_id, image in lock.images:
        if _sha256(source_checkout / image.dockerfile.path) != image.dockerfile.sha256:
            _fail(f"{image_id} Dockerfile SHA-256 does not match the lock")


def verify_thin_report(lock: SourceLock, report_path: Path) -> None:
    """Accept only a passing report or the exact manually reviewed report."""

    try:
        report_bytes = report_path.read_bytes()
        report = _expect_object(json.loads(report_bytes), "thin report")
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceVerificationError("thin report is unreadable") from exc
    verdict = report.get("verdict")
    if verdict == "block":
        _fail("thin report blocked the image build")
    if verdict not in {"pass", "manual_review_required"}:
        _fail("thin report has an unsupported verdict")

    hard_checks = _expect_object(report.get("hard_checks"), "hard_checks")
    if hard_checks.get("status") != "pass" or hard_checks.get("code") != "ok":
        _fail("thin report hard checks did not pass")
    target = _expect_object(report.get("target"), "target")
    for key, expected in (
        ("repository", lock.adoption_manifest.repository),
        ("commit", lock.adoption_manifest.commit),
        ("tree", lock.adoption_manifest.tree),
    ):
        if target.get(key) != expected:
            _fail(f"thin report target {key} does not match the lock")
    official = _expect_object(report.get("official_migrations"), "official_migrations")
    plugin = _expect_object(report.get("plugin_contract"), "plugin_contract")
    if official.get("status") != "merged":
        _fail("official migrations are not merged")
    if plugin.get("status") != "valid":
        _fail("plugin contract is not valid")
    if verdict == "manual_review_required":
        digest = hashlib.sha256(report_bytes).hexdigest()
        if digest != lock.reviewed_thin_report_sha256:
            _fail("thin report does not match the reviewed digest")


def emit_github_outputs(
    lock: SourceLock, lock_path: Path, output_path: Path
) -> None:
    """Expose validated lock values and a closed build matrix."""

    lock_sha256 = _sha256(lock_path)
    image_tag = (
        f"src-{lock.build_source.commit[:12]}-lock-{lock_sha256[:12]}"
    )
    matrix = {
        "include": [
            {
                "id": image_id,
                "repository": image.repository,
                "context": image.context,
                "dockerfile": image.dockerfile.path,
                "source_commit": lock.build_source.commit,
                "source_tree": lock.build_source.tree,
                "lock_sha256": lock_sha256,
            }
            for image_id, image in lock.images
        ]
    }
    values = {
        "build_repository": lock.build_source.repository,
        "build_commit": lock.build_source.commit,
        "build_tree": lock.build_source.tree,
        "target_repository": lock.adoption_manifest.repository,
        "target_commit": lock.adoption_manifest.commit,
        "platform": lock.platform,
        "lock_sha256": lock_sha256,
        "image_tag": image_tag,
        "image_matrix": json.dumps(matrix, separators=(",", ":")),
    }
    with output_path.open("a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    emit = subparsers.add_parser("emit")
    emit.add_argument("--lock", type=Path, required=True)
    emit.add_argument("--github-output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--lock", type=Path, required=True)
    verify.add_argument("--source-checkout", type=Path, required=True)
    verify.add_argument("--workflow-checkout", type=Path, required=True)
    report = subparsers.add_parser("verify-report")
    report.add_argument("--lock", type=Path, required=True)
    report.add_argument("--report", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    lock = load_source_lock(args.lock)
    if args.command == "emit":
        emit_github_outputs(lock, args.lock, args.github_output)
    elif args.command == "verify":
        verify_source(lock, args.source_checkout, args.workflow_checkout)
    else:
        verify_thin_report(lock, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
