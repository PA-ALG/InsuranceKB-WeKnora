#!/usr/bin/env python3
"""Deterministic local application artifact contracts for BA0.

This module deliberately keeps Docker behind an injected process boundary.  The
manifest and identity functions are pure preflight operations: they validate a
closed versioned contract, resolve the Linux/arm64 Go build closure, and hash
only effective public build inputs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any


class ArtifactContractError(RuntimeError):
    """Raised when a local artifact contract cannot be proven."""


Runner = Callable[..., subprocess.CompletedProcess[str]]

_MANIFEST_FIELDS = {
    "schema_version",
    "artifact",
    "context",
    "dockerfile",
    "dockerignore",
    "go_packages",
    "required_paths",
    "external_dependency_lock",
    "build_contract",
}
_BUILD_CONTRACT_FIELDS = {"target", "platform", "goos", "goarch", "cgo_enabled"}
_LOCK_FIELDS = {
    "schema_version",
    "platform",
    "base_images",
    "debian",
    "python_tools",
    "downloads",
}
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}")
_IMAGE_REFERENCE = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}")
_SNAPSHOT = re.compile(r"https://snapshot\.debian\.org/archive/[^/]+/\d{8}T\d{6}Z/")
_IGNORED_DIRECTORY_PARTS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache"}
_INPUT_FILE_FIELDS = (
    "GoFiles",
    "CgoFiles",
    "CFiles",
    "CXXFiles",
    "MFiles",
    "HFiles",
    "FFiles",
    "SFiles",
    "SwigFiles",
    "SwigCXXFiles",
    "SysoFiles",
    "EmbedFiles",
)
_PUBLIC_BUILD_ARGUMENTS = {
    "CGO_ENABLED": {"0", "1"},
    "GOOS": {"linux"},
    "GOARCH": {"arm64"},
}
_TRANSPORT_OR_SECRET_NAME = re.compile(
    r"mirror|proxy|private|secret|token|password|credential", re.I
)
_OPERATIONAL_ENVIRONMENT = (
    "PATH",
    "HOME",
    "TMPDIR",
    "GOROOT",
    "GOPATH",
    "GOMODCACHE",
    "GOCACHE",
    "CC",
    "CXX",
    "PKG_CONFIG_PATH",
    "CGO_CFLAGS",
    "CGO_CPPFLAGS",
    "CGO_CXXFLAGS",
    "CGO_LDFLAGS",
)


def _read_json_object(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactContractError(
            f"cannot read {description}: {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise ArtifactContractError(f"{description} schema must be a JSON object")
    return value


def _closed_fields(
    value: Mapping[str, Any], expected: set[str], description: str
) -> None:
    actual = set(value)
    missing = expected - actual
    unknown = actual - expected
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {sorted(missing)}")
        if unknown:
            details.append(f"unknown fields: {sorted(unknown)}")
        raise ArtifactContractError(
            f"{description} schema error ({'; '.join(details)})"
        )


def _mapping(value: object, description: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactContractError(f"{description} must be an object")
    return value


def _nonempty_string(value: object, description: str) -> str:
    if not isinstance(value, str) or not value or re.search(r"\s", value):
        raise ArtifactContractError(f"{description} must be a non-empty single token")
    return value


def _repository_relative(value: object, description: str) -> str:
    text = _nonempty_string(value, description)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or text != path.as_posix():
        raise ArtifactContractError(f"{description} must stay inside the repository")
    return text


def load_manifest(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load and strictly validate the versioned app input manifest."""

    document = _read_json_object(Path(path), "app build-input manifest")
    _closed_fields(document, _MANIFEST_FIELDS, "manifest")
    if document["schema_version"] != 1 or document["artifact"] != "weknora-app":
        raise ArtifactContractError("unsupported manifest schema or artifact")
    if document["context"] != ".":
        raise ArtifactContractError("manifest context must be the repository root")
    _repository_relative(document["dockerfile"], "manifest dockerfile")
    _repository_relative(document["dockerignore"], "manifest dockerignore")
    _repository_relative(
        document["external_dependency_lock"], "manifest dependency lock"
    )

    packages = document["go_packages"]
    if not isinstance(packages, list) or packages != [
        "./cmd/server",
        "./cmd/download/duckdb",
    ]:
        raise ArtifactContractError(
            "manifest go_packages schema is not the app build closure"
        )
    paths = document["required_paths"]
    if (
        not isinstance(paths, list)
        or not paths
        or not all(isinstance(item, str) for item in paths)
    ):
        raise ArtifactContractError(
            "manifest required_paths must be a non-empty string list"
        )
    normalized = [
        _repository_relative(item, "manifest required path") for item in paths
    ]
    if len(normalized) != len(set(normalized)):
        raise ArtifactContractError("manifest required_paths contains duplicate fields")

    contract = _mapping(document["build_contract"], "manifest build_contract")
    _closed_fields(contract, _BUILD_CONTRACT_FIELDS, "manifest build_contract")
    expected_contract = {
        "target": "runtime",
        "platform": "linux/arm64",
        "goos": "linux",
        "goarch": "arm64",
        "cgo_enabled": True,
    }
    if dict(contract) != expected_contract:
        raise ArtifactContractError(
            "manifest build_contract is outside BA0 linux/arm64"
        )
    return document


def _sha(value: object, description: str) -> str:
    text = _nonempty_string(value, description)
    if _HEX_SHA256.fullmatch(text) is None:
        raise ArtifactContractError(f"{description} must be a sha256 digest")
    return text


def _download_record(
    value: object, description: str, *, includes_version: bool = True
) -> Mapping[str, Any]:
    record = _mapping(value, description)
    fields = {"platform", "origin", "sha256"}
    if includes_version:
        fields.add("version")
    _closed_fields(record, fields, description)
    if includes_version:
        _nonempty_string(record["version"], f"{description} version")
    _nonempty_string(record["platform"], f"{description} platform")
    _nonempty_string(record["origin"], f"{description} origin")
    _sha(record["sha256"], f"{description} sha256")
    return record


def load_dependency_lock(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load a closed dependency lock and reject mutable or incomplete facts."""

    document = _read_json_object(Path(path), "external dependency lock")
    _closed_fields(document, _LOCK_FIELDS, "dependency lock")
    if document["schema_version"] != 1:
        raise ArtifactContractError("unsupported dependency lock schema")

    platform = _mapping(document["platform"], "dependency lock platform")
    _closed_fields(platform, {"os", "arch", "duckdb"}, "dependency lock platform")
    if platform["os"] != "linux" or platform["arch"] != "arm64":
        raise ArtifactContractError("dependency lock platform must be linux/arm64")
    duckdb_platform = _nonempty_string(platform["duckdb"], "DuckDB platform")

    images = _mapping(document["base_images"], "base images")
    _closed_fields(images, {"builder", "runtime"}, "base images")
    for stage in ("builder", "runtime"):
        record = _mapping(images[stage], f"{stage} base image")
        _closed_fields(record, {"reference"}, f"{stage} base image")
        reference = _nonempty_string(
            record["reference"], f"{stage} base image reference"
        )
        if _IMAGE_REFERENCE.fullmatch(reference) is None:
            raise ArtifactContractError(
                f"{stage} base image must be pinned by immutable sha256 digest"
            )

    debian = _mapping(document["debian"], "Debian lock")
    _closed_fields(debian, {"repositories", "packages"}, "Debian lock")
    repositories = _mapping(debian["repositories"], "Debian repositories")
    _closed_fields(repositories, {"debian", "debian-security"}, "Debian repositories")
    for name, raw_record in repositories.items():
        record = _mapping(raw_record, f"Debian repository {name}")
        _closed_fields(
            record, {"snapshot", "release_sha256"}, f"Debian repository {name}"
        )
        snapshot = _nonempty_string(
            record["snapshot"], f"Debian repository {name} snapshot"
        )
        if _SNAPSHOT.fullmatch(snapshot) is None:
            raise ArtifactContractError(f"Debian repository {name} snapshot is mutable")
        _sha(record["release_sha256"], f"Debian repository {name} Release sha256")
    packages = _mapping(debian["packages"], "Debian packages")
    if not packages:
        raise ArtifactContractError("Debian package facts are missing")
    for name, version in packages.items():
        _nonempty_string(name, "Debian package name")
        resolved = _nonempty_string(version, f"Debian package {name} version")
        if "latest" in resolved.lower():
            raise ArtifactContractError(f"Debian package {name} is not pinned")

    python_tools = _mapping(document["python_tools"], "Python tools")
    missing_tools = {"pip", "setuptools", "wheel"} - set(python_tools)
    if missing_tools:
        raise ArtifactContractError(
            f"Python tool facts missing: {sorted(missing_tools)}"
        )
    for name, raw_record in python_tools.items():
        record = _mapping(raw_record, f"Python tool {name}")
        _closed_fields(record, {"version", "origin", "sha256"}, f"Python tool {name}")
        version = _nonempty_string(record["version"], f"Python tool {name} version")
        origin = _nonempty_string(record["origin"], f"Python tool {name} origin")
        if version not in origin or "latest" in origin.lower():
            raise ArtifactContractError(
                f"Python tool {name} origin is not version pinned"
            )
        _sha(record["sha256"], f"Python tool {name} sha256")

    downloads = _mapping(document["downloads"], "downloads")
    _closed_fields(downloads, {"go_tools", "uv", "duckdb"}, "downloads")
    go_tools = _mapping(downloads["go_tools"], "Go tools")
    _closed_fields(go_tools, {"migrate"}, "Go tools")
    migrate = _mapping(go_tools["migrate"], "migrate tool")
    _closed_fields(migrate, {"module", "version", "go_sum"}, "migrate tool")
    if migrate["module"] != "github.com/golang-migrate/migrate/v4/cmd/migrate":
        raise ArtifactContractError("migrate module is not the locked command")
    _nonempty_string(migrate["version"], "migrate version")
    go_sum = _nonempty_string(migrate["go_sum"], "migrate go_sum")
    if not go_sum.startswith("h1:"):
        raise ArtifactContractError("migrate go_sum is missing its h1 digest")

    _download_record(downloads["uv"], "uv download")
    duckdb = _mapping(downloads["duckdb"], "DuckDB download")
    _closed_fields(duckdb, {"version", "extensions"}, "DuckDB download")
    _nonempty_string(duckdb["version"], "DuckDB version")
    extensions = _mapping(duckdb["extensions"], "DuckDB extensions")
    missing_extensions = {"spatial", "excel"} - set(extensions)
    unknown_extensions = set(extensions) - {"spatial", "excel"}
    if missing_extensions or unknown_extensions:
        raise ArtifactContractError(
            "DuckDB extension facts missing or unknown: "
            f"missing={sorted(missing_extensions)}, unknown={sorted(unknown_extensions)}"
        )
    for name, raw_record in extensions.items():
        record = _download_record(
            raw_record, f"DuckDB extension {name}", includes_version=False
        )
        if record["platform"] != duckdb_platform:
            raise ArtifactContractError(f"DuckDB extension {name} platform mismatch")

    public = json.dumps(document, sort_keys=True, separators=(",", ":")).lower()
    if "latest" in public:
        raise ArtifactContractError("dependency lock contains a floating latest fact")
    return document


def _inside_repository(repo_root: Path, candidate: Path, description: str) -> Path:
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repo_root)
    except (OSError, ValueError) as exc:
        raise ArtifactContractError(
            f"{description} is missing or outside repository"
        ) from exc
    return resolved


def _rooted(repo_root: Path, candidate: str | os.PathLike[str]) -> Path:
    path = Path(candidate)
    return path if path.is_absolute() else repo_root / path


def _relative(repo_root: Path, candidate: Path) -> str:
    return candidate.relative_to(repo_root).as_posix()


def _manifest_files(repo_root: Path, manifest: Mapping[str, Any]) -> set[Path]:
    entries: set[Path] = set()
    relative_names = {
        str(manifest["dockerfile"]),
        str(manifest["dockerignore"]),
        str(manifest["external_dependency_lock"]),
        "go.mod",
        "go.sum",
        *[str(value) for value in manifest["required_paths"]],
    }
    for relative_name in relative_names:
        relative_name = _repository_relative(relative_name, "manifest input")
        resolved = _inside_repository(
            repo_root, repo_root / relative_name, f"manifest input {relative_name}"
        )
        if resolved.is_file():
            entries.add(resolved)
            continue
        if not resolved.is_dir():
            raise ArtifactContractError(
                f"manifest input {relative_name} is not a file or directory"
            )
        for candidate in resolved.rglob("*"):
            if any(part in _IGNORED_DIRECTORY_PARTS for part in candidate.parts):
                continue
            if candidate.is_file():
                entries.add(
                    _inside_repository(
                        repo_root, candidate, f"manifest input {relative_name}"
                    )
                )
    return entries


def _json_stream(text: str) -> list[Mapping[str, Any]]:
    decoder = json.JSONDecoder()
    index = 0
    records: list[Mapping[str, Any]] = []
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index == len(text):
            return records
        try:
            record, index = decoder.raw_decode(text, index)
        except json.JSONDecodeError as exc:
            raise ArtifactContractError(
                f"go list dependency output is invalid: {exc}"
            ) from exc
        if not isinstance(record, Mapping):
            raise ArtifactContractError(
                "go list dependency output contains a non-object"
            )
        records.append(record)


def _operational_environment() -> dict[str, str]:
    environment = {
        name: value
        for name in _OPERATIONAL_ENVIRONMENT
        if (value := os.environ.get(name))
    }
    environment.setdefault("PATH", os.defpath)
    return environment


def resolve_inputs(
    repo_root: str | os.PathLike[str],
    manifest: Mapping[str, Any],
    *,
    runner: Runner = subprocess.run,
) -> tuple[dict[str, Any], ...]:
    """Resolve every effective file in the Linux/arm64 app build closure."""

    root = Path(repo_root).resolve(strict=True)
    files = _manifest_files(root, manifest)
    go_package_directories_by_file: dict[Path, set[str]] = {}
    contract = _mapping(manifest["build_contract"], "manifest build_contract")
    environment = {
        **_operational_environment(),
        "GOOS": str(contract["goos"]),
        "GOARCH": str(contract["goarch"]),
        "CGO_ENABLED": "1" if contract["cgo_enabled"] else "0",
    }
    arguments = (
        "go",
        "list",
        "-deps",
        "-json",
        *tuple(str(package) for package in manifest["go_packages"]),
    )
    result = runner(
        arguments,
        cwd=root,
        capture_output=True,
        text=True,
        env=environment,
    )
    if result.returncode != 0:
        raise ArtifactContractError(
            f"go list dependency resolution failed: {result.stderr.strip()}"
        )
    packages = _json_stream(result.stdout)
    if not packages:
        raise ArtifactContractError(
            "go list dependency resolution returned no packages"
        )
    for package in packages:
        if (
            package.get("Incomplete")
            or package.get("DepsErrors")
            or package.get("Error")
        ):
            raise ArtifactContractError("go list reported an unresolved dependency")
        directory_value = package.get("Dir")
        if not isinstance(directory_value, str):
            continue
        directory = Path(directory_value).resolve()
        try:
            package_directory = directory.relative_to(root).as_posix()
        except ValueError:
            continue
        for field in _INPUT_FILE_FIELDS:
            values = package.get(field, [])
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                raise ArtifactContractError(
                    f"go list dependency field {field} is invalid"
                )
            for name in values:
                if not isinstance(name, str):
                    raise ArtifactContractError(
                        f"go list dependency field {field} is invalid"
                    )
                candidate = Path(name)
                if not candidate.is_absolute():
                    candidate = directory / candidate
                resolved_file = _inside_repository(
                    root, candidate, f"go list dependency {name}"
                )
                files.add(resolved_file)
                go_package_directories_by_file.setdefault(resolved_file, set()).add(
                    package_directory
                )

    resolved: list[dict[str, Any]] = []
    for path in sorted(files, key=lambda item: _relative(root, item)):
        content = path.read_bytes()
        record: dict[str, Any] = {
            "path": _relative(root, path),
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        }
        package_directories = go_package_directories_by_file.get(path)
        if package_directories:
            record["go_package_directories"] = sorted(package_directories)
        resolved.append(record)
    return tuple(resolved)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_build_args(arguments: Mapping[str, object]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for name, value in arguments.items():
        normalized_name = str(name)
        if _TRANSPORT_OR_SECRET_NAME.search(normalized_name):
            continue
        if normalized_name not in _PUBLIC_BUILD_ARGUMENTS:
            raise ArtifactContractError(
                f"unsupported public build argument: {normalized_name}"
            )
        normalized_value = str(value)
        if normalized_value not in _PUBLIC_BUILD_ARGUMENTS[normalized_name]:
            raise ArtifactContractError(
                f"invalid value for public build argument {normalized_name}"
            )
        safe[normalized_name] = normalized_value
    return dict(sorted(safe.items()))


def _declared_input_pathspecs(
    root: Path,
    manifest_file: Path,
    lock_file: Path,
    manifest: Mapping[str, Any],
    inputs: Sequence[Mapping[str, Any]],
) -> list[str]:
    go_package_directories = {
        str(directory)
        for record in inputs
        for directory in record.get("go_package_directories", [])
    }
    return sorted(
        {
            _relative(root, manifest_file),
            _relative(root, lock_file),
            str(manifest["dockerfile"]),
            str(manifest["dockerignore"]),
            str(manifest["external_dependency_lock"]),
            "go.mod",
            "go.sum",
            *[str(value) for value in manifest["required_paths"]],
            *[str(record["path"]) for record in inputs],
            *go_package_directories,
        }
    )


def canonical_identity(
    *,
    repo_root: str | os.PathLike[str],
    manifest_path: str | os.PathLike[str],
    dependency_lock_path: str | os.PathLike[str],
    build_source_head: str,
    integration_head: str,
    runner: Runner = subprocess.run,
    effective_build_args: Mapping[str, object],
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return stable canonical bytes and identity for one frozen build source."""

    del environment  # runtime configuration and credentials are never identity inputs
    if re.fullmatch(r"[0-9a-f]{40}", build_source_head) is None:
        raise ArtifactContractError("build_source_head must be a full commit id")
    if re.fullmatch(r"[0-9a-f]{40}", integration_head) is None:
        raise ArtifactContractError("integration_head must be a full commit id")
    root = Path(repo_root).resolve(strict=True)
    manifest_file = _inside_repository(
        root, _rooted(root, manifest_path), "app build-input manifest"
    )
    lock_file = _inside_repository(
        root, _rooted(root, dependency_lock_path), "dependency lock"
    )
    manifest = load_manifest(manifest_file)
    lock = load_dependency_lock(lock_file)
    declared_lock = _inside_repository(
        root,
        root / str(manifest["external_dependency_lock"]),
        "manifest dependency lock",
    )
    if declared_lock != lock_file:
        raise ArtifactContractError("dependency lock path differs from the manifest")

    inputs = resolve_inputs(root, manifest, runner=runner)
    drift_paths = _declared_input_pathspecs(
        root, manifest_file, lock_file, manifest, inputs
    )
    command_environment = _operational_environment()
    drift = runner(
        ("git", "diff", "--quiet", build_source_head, "--", *drift_paths),
        cwd=root,
        capture_output=True,
        text=True,
        env=command_environment,
    )
    if drift.returncode != 0:
        raise ArtifactContractError("manifest input drift from build_source_head")
    untracked = runner(
        (
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            *drift_paths,
        ),
        cwd=root,
        capture_output=True,
        text=True,
        env=command_environment,
    )
    if untracked.returncode != 0:
        raise ArtifactContractError("cannot verify untracked manifest input drift")
    if any(line.startswith("?? ") for line in untracked.stdout.splitlines()):
        raise ArtifactContractError(
            "untracked manifest input drift from build_source_head"
        )

    manifest_sha256 = hashlib.sha256(_canonical_json(manifest)).hexdigest()
    dependency_lock_sha256 = hashlib.sha256(_canonical_json(lock)).hexdigest()
    identity_document = {
        "schema_version": 1,
        "artifact": manifest["artifact"],
        "build_source_head": build_source_head,
        "manifest_sha256": manifest_sha256,
        "dependency_lock_sha256": dependency_lock_sha256,
        "build_contract": manifest["build_contract"],
        "effective_build_args": _safe_build_args(effective_build_args),
        "inputs": list(inputs),
    }
    canonical_bytes = _canonical_json(identity_document)
    artifact_identity = "sha256:" + hashlib.sha256(canonical_bytes).hexdigest()
    return {
        "artifact": manifest["artifact"],
        "artifact_identity": artifact_identity,
        "canonical_bytes": canonical_bytes,
        "manifest_sha256": manifest_sha256,
        "dependency_lock_sha256": dependency_lock_sha256,
        "build_source_head": build_source_head,
        "integration_head": integration_head,
        "target": manifest["build_contract"]["target"],
        "platform": manifest["build_contract"]["platform"],
    }
