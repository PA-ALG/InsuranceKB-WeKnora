#!/usr/bin/env python3
"""Verify the immutable WeKnora app source lock used by OpenSpec 023."""

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
    "dockerfile",
    "required_ancestors",
    "patch",
    "platform",
    "image_repository",
}
_FILE_KEYS = {"path", "sha256"}
_UPSTREAM_REPOSITORY = "https://github.com/Tencent/WeKnora.git"
_PLATFORM = "linux/arm64"
_GHCR_PREFIX = "ghcr.io/pa-alg/"


class SourceVerificationError(ValueError):
    """Raised when source identity differs from the reviewed source lock."""


class LockedFile(NamedTuple):
    path: str
    sha256: str


class SourceLock(NamedTuple):
    schema_version: int
    repository: str
    commit: str
    tree: str
    dockerfile: LockedFile
    required_ancestors: tuple[str, ...]
    patch: LockedFile
    platform: str
    image_repository: str


def _fail(message: str) -> NoReturn:
    raise SourceVerificationError(message)


def _expect_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _fail(f"{label} must be an object")
    return value


def _expect_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{label} must be a non-empty string")
    return value


def _expect_locked_file(value: object, label: str) -> LockedFile:
    item = _expect_object(value, label)
    if set(item) != _FILE_KEYS:
        _fail(f"{label} keys do not match the source-lock schema")
    path = _expect_string(item.get("path"), f"{label}.path")
    digest = _expect_string(item.get("sha256"), f"{label}.sha256")
    pure_path = PurePosixPath(path)
    if pure_path.is_absolute() or ".." in pure_path.parts or path != pure_path.as_posix():
        _fail(f"{label}.path must be a normalized relative path")
    if _SHA256_RE.fullmatch(digest) is None:
        _fail(f"{label}.sha256 must be a full lowercase SHA-256")
    return LockedFile(path=path, sha256=digest)


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
        _fail("repository must be the reviewed Tencent upstream HTTPS URL")

    commit = _expect_string(data.get("commit"), "commit")
    tree = _expect_string(data.get("tree"), "tree")
    if _SHA_RE.fullmatch(commit) is None or _SHA_RE.fullmatch(tree) is None:
        _fail("commit and tree must be full lowercase Git SHAs")

    ancestors_raw = data.get("required_ancestors")
    if not isinstance(ancestors_raw, list) or not ancestors_raw:
        _fail("required_ancestors must be a non-empty list")
    ancestors: list[str] = []
    for value in ancestors_raw:
        ancestor = _expect_string(value, "required ancestor")
        if _SHA_RE.fullmatch(ancestor) is None:
            _fail("required ancestors must be full lowercase Git SHAs")
        ancestors.append(ancestor)
    if len(set(ancestors)) != len(ancestors):
        _fail("required ancestors must be unique")

    platform = _expect_string(data.get("platform"), "platform")
    if platform != _PLATFORM:
        _fail("platform must be the reviewed linux/arm64 target")

    image_repository = _expect_string(
        data.get("image_repository"), "image_repository"
    )
    if not image_repository.startswith(_GHCR_PREFIX) or any(
        marker in image_repository for marker in ("@", ":")
    ):
        _fail("image_repository must be a tag-free PA-ALG GHCR repository")

    dockerfile = _expect_locked_file(data.get("dockerfile"), "dockerfile")
    if dockerfile.path != "docker/Dockerfile.app":
        _fail("Dockerfile path must identify the real WeKnora app Dockerfile")

    return SourceLock(
        schema_version=1,
        repository=repository,
        commit=commit,
        tree=tree,
        dockerfile=dockerfile,
        required_ancestors=tuple(ancestors),
        patch=_expect_locked_file(data.get("patch"), "patch"),
        platform=platform,
        image_repository=image_repository,
    )


def _git(checkout: Path, *arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", "-C", str(checkout), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        _fail(f"git verification failed for {arguments[0]}")
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise SourceVerificationError("locked file is unreadable") from exc


def verify_checkout(lock: SourceLock, checkout: Path, patch_path: Path) -> None:
    """Fail closed unless checkout, ancestors, Dockerfile and patch match the lock."""

    if not checkout.is_dir():
        _fail("source checkout is missing")
    if _git(checkout, "remote", "get-url", "origin") != lock.repository:
        _fail("source checkout repository does not match the lock")
    if _git(checkout, "rev-parse", "HEAD") != lock.commit:
        _fail("source checkout commit does not match the lock")
    if _git(checkout, "rev-parse", "HEAD^{tree}") != lock.tree:
        _fail("source checkout tree does not match the lock")

    dockerfile_path = checkout / lock.dockerfile.path
    if _sha256(dockerfile_path) != lock.dockerfile.sha256:
        _fail("Dockerfile SHA-256 does not match the lock")
    if _sha256(patch_path) != lock.patch.sha256:
        _fail("patch SHA-256 does not match the lock")

    for ancestor in lock.required_ancestors:
        completed = subprocess.run(
            ["git", "-C", str(checkout), "merge-base", "--is-ancestor", ancestor, lock.commit],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            _fail("required security ancestor is missing")

    dirty = _git(checkout, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        _fail("source checkout must be clean before applying the locked patch")

    completed = subprocess.run(
        ["git", "-C", str(checkout), "apply", "--check", str(patch_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        _fail("locked patch does not apply cleanly")


def emit_github_outputs(lock: SourceLock, output_path: Path) -> None:
    """Expose validated single-line lock values to later trusted workflow steps."""

    values = {
        "repository": lock.repository,
        "commit": lock.commit,
        "tree": lock.tree,
        "dockerfile_path": lock.dockerfile.path,
        "patch_path": lock.patch.path,
        "patch_sha256": lock.patch.sha256,
        "platform": lock.platform,
        "image_repository": lock.image_repository,
        "image_tag": f"src-{lock.commit[:12]}-patch-{lock.patch.sha256[:12]}",
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
    verify.add_argument("--checkout", type=Path, required=True)
    verify.add_argument("--patch", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    lock = load_source_lock(args.lock)
    if args.command == "emit":
        emit_github_outputs(lock, args.github_output)
    else:
        verify_checkout(lock, args.checkout, args.patch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
