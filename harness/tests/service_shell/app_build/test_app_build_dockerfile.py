"""App build: build metadata, Dockerfile caches and the external dependency lock."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from tests.service_shell.app_build.helpers import (
    BUILD_SOURCE_HEAD,
    DEPENDENCY_LOCK_PATH,
    DOCKERFILE_PATH,
    REPO_ROOT,
    _artifact_module,
    _dockerfile_instructions,
    _executable_text,
    _json_text,
    _load_json,
)
from tests.service_shell.app_build.resolver_helpers import _identity_runner

GET_VERSION_PATH = REPO_ROOT / "scripts/get_version.sh"
BROWSER_SKILL_BUILD_PATH = REPO_ROOT / "scripts/build_browserskill.sh"
ANYDOC_BUILD_PATH = REPO_ROOT / "scripts/build-anydoc-lib.sh"


def _duckdb_version_from_go_mod(repo_root: Path) -> str:
    source = (repo_root / "go.mod").read_text(encoding="utf-8")
    match = re.search(
        r"github\.com/duckdb/duckdb-go/v2\s+v2\.([0-9])([0-9]{2})([0-9]{2})\.[0-9]+",
        source,
    )
    assert match is not None, "go.mod must pin the DuckDB binding version"
    major, minor, patch = (int(value) for value in match.groups())
    return f"v{major}.{minor}.{patch}"


# BA0-REQ-03/04: stable metadata, builder facts, persistent caches, locked inputs.


def test_metadata_comes_from_build_source_epoch_and_is_wall_clock_stable() -> None:
    module = _artifact_module()
    first_runner = _identity_runner(REPO_ROOT, source_epoch=1_700_000_000)
    second_runner = _identity_runner(REPO_ROOT, source_epoch=1_700_000_000)

    first = module.build_metadata(
        repo_root=REPO_ROOT,
        build_source_head=BUILD_SOURCE_HEAD,
        runner=first_runner,
    )
    second = module.build_metadata(
        repo_root=REPO_ROOT,
        build_source_head=BUILD_SOURCE_HEAD,
        runner=second_runner,
    )

    assert first == second
    assert set(first) == {"version", "commit_id", "source_date_epoch", "build_time"}
    assert first["version"] == "v1.2.3"
    assert first["commit_id"] == BUILD_SOURCE_HEAD
    assert first["source_date_epoch"] == 1_700_000_000
    assert first["build_time"] == datetime.fromtimestamp(1_700_000_000, tz=UTC).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )
    assert "go_version" not in first, "host Go version must not enter metadata"

    script = GET_VERSION_PATH.read_text(encoding="utf-8")
    assert "BUILD_SOURCE_HEAD" in script
    assert "SOURCE_DATE_EPOCH" in script
    assert "%ct" in script
    build_time_lines = [
        line for line in script.splitlines() if "BUILD_TIME=" in line and "date" in line
    ]
    assert all("SOURCE_DATE_EPOCH" in line for line in build_time_lines)
    assert "go version" not in script


def _cache_mounts(instruction: str) -> dict[str, str]:
    mounts: dict[str, str] = {}
    for mount in re.findall(r"--mount=([^ ]+)", instruction):
        fields = dict(part.split("=", 1) for part in mount.split(",") if "=" in part)
        if fields.get("type") == "cache" and "target" in fields:
            assert fields.get("sharing") == "locked"
            assert fields.get("id"), f"cache mount lacks a stable id: {mount}"
            mounts[fields["target"]] = fields["id"]
    return mounts


def _shell_assignments(command: str) -> dict[str, str]:
    assignments: dict[str, str] = {}
    pattern = re.compile(
        r"(?:^|[ ;])([A-Za-z_][A-Za-z0-9_]*)=(?:\"([^\"]+)\"|'([^']+)'|([^\s;&]+))"
    )
    for match in pattern.finditer(command):
        assignments[match.group(1)] = next(value for value in match.groups()[1:] if value)
    return assignments


def _resolve_shell_path(token: str, assignments: Mapping[str, str]) -> str:
    value = token.strip("\"'")
    variable = re.fullmatch(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))", value)
    if variable is not None:
        return assignments.get(variable.group(1) or variable.group(2), "")
    return value


def test_dockerfile_gets_go_version_inside_builder_and_uses_stable_metadata() -> None:
    source = DOCKERFILE_PATH.read_text(encoding="utf-8")
    instructions = _dockerfile_instructions(source)
    build = next(item for item in instructions if "make build-prod" in item)

    assert "go version" in build
    assert "GO_VERSION" in build
    assert "SOURCE_DATE_EPOCH" in source
    assert "GO_VERSION_ARG" not in source
    for instruction in instructions:
        if "BUILD_TIME" in instruction and "date" in instruction:
            assert "SOURCE_DATE_EPOCH" in instruction


def test_dockerfile_go_runs_share_locked_module_build_cache_ids_and_probe() -> None:
    source = DOCKERFILE_PATH.read_text(encoding="utf-8")
    instructions = _dockerfile_instructions(source)
    duckdb_run = next(
        item for item in instructions if "go run cmd/download/duckdb/duckdb.go" in item
    )
    build_run = next(item for item in instructions if "make build-prod" in item)

    first_mounts = _cache_mounts(duckdb_run)
    second_mounts = _cache_mounts(build_run)
    assert set(first_mounts) == {"/go/pkg/mod", "/root/.cache/go-build"}
    assert first_mounts == second_mounts
    assert all(
        "SOURCE" not in cache_id and "COMMIT" not in cache_id for cache_id in first_mounts.values()
    )
    first_command = _executable_text(duckdb_run)
    second_command = _executable_text(build_run)
    first_assignments = _shell_assignments(first_command)
    second_assignments = _shell_assignments(second_command)
    writes = [
        (
            _resolve_shell_path(match.group("path") or match.group("tee"), first_assignments),
            match.start(),
        )
        for match in re.finditer(
            r"\b(?:printf|echo)\b[^;&|]*?>\s*(?P<path>[^\s;&]+)|\btee\s+(?P<tee>[^\s;&]+)",
            first_command,
        )
    ]
    first_checks = [
        (_resolve_shell_path(match.group("path"), first_assignments), match.start())
        for match in re.finditer(r"(?:\btest|\[)\s+-s\s+(?P<path>[^\s;&\]]+)", first_command)
    ]
    second_checks = [
        (_resolve_shell_path(match.group("path"), second_assignments), match.start())
        for match in re.finditer(r"(?:\btest|\[)\s+-s\s+(?P<path>[^\s;&\]]+)", second_command)
    ]
    download_position = first_command.index("go run cmd/download/duckdb/duckdb.go")
    for cache_path in first_mounts:
        cache_writes = [
            (path, position)
            for path, position in writes
            if path == cache_path or path.startswith(cache_path + "/")
        ]
        assert cache_writes, f"the first Go RUN must write a probe in {cache_path}"
        written_probe, write_position = cache_writes[0]
        assert written_probe
        assert not re.search(r"secret|token|password|credential", written_probe, re.I)
        assert write_position > download_position
        assert any(
            path == written_probe and position > write_position for path, position in first_checks
        ), f"the first Go RUN must verify non-empty evidence in {cache_path}"
        assert not any(path == written_probe for path, _ in second_checks), (
            "compile cache may be absent; historical probes are observations, not prerequisites"
        )


def test_dependency_lock_covers_all_versioned_external_facts_without_proxy() -> None:
    document = _load_json(DEPENDENCY_LOCK_PATH, description="external dependency lock")

    assert document["schema_version"] == 1
    assert document["platform"]["os"] == "linux"
    assert document["platform"]["arch"] == "arm64"
    for stage in ("builder", "browserskill", "rust", "runtime"):
        reference = document["base_images"][stage]["reference"]
        assert re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", reference)
    assert document["toolchains"] == {"rust": "1.90.0"}
    assert document["toolchains"]["rust"] in document["base_images"]["rust"]["reference"]

    debian = document["debian"]
    assert set(debian["repositories"]) == {"debian", "debian-security"}
    for repository in debian["repositories"].values():
        assert re.fullmatch(
            r"\S+/\d{8}T\d{6}Z/",
            repository["snapshot"],
        )
        assert re.fullmatch(r"[0-9a-f]{64}", repository["release_sha256"])
    required_packages = {
        "git",
        "build-essential",
        "libsqlite3-dev",
        "ca-certificates",
        "postgresql-client",
        "default-mysql-client",
        "tzdata",
        "sed",
        "curl",
        "bash",
        "vim",
        "wget",
        "libsqlite3-0",
        "python3",
        "python3-pip",
        "python3-dev",
        "libffi-dev",
        "libssl-dev",
        "nodejs",
        "npm",
        "gosu",
        "ffmpeg",
        "cmake",
        "pkg-config",
    }
    assert required_packages <= set(debian["packages"])
    assert all(value and "latest" not in value for value in debian["packages"].values())

    for name in ("pip", "setuptools", "wheel"):
        tool = document["python_tools"][name]
        assert tool["version"]
        assert tool["version"] in tool["origin"]
        assert re.fullmatch(r"[0-9a-f]{64}", tool["sha256"])

    downloads = document["downloads"]
    migrate = downloads["go_tools"]["migrate"]
    assert migrate["module"] == "github.com/golang-migrate/migrate/v4/cmd/migrate"
    assert migrate["version"] == "v4.19.1"
    assert migrate["go_sum"].startswith("h1:")
    for item in (
        downloads["uv"],
        downloads["anydoc"],
        downloads["browserskill"],
        downloads["pnpm"],
        *downloads["duckdb"]["extensions"].values(),
    ):
        assert item["platform"]
        assert item["origin"] and not re.search(r"\s", item["origin"])
        assert re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
    assert re.fullmatch(r"[0-9a-f]{40}", downloads["browserskill"]["source_commit"])
    release = json.loads(
        (REPO_ROOT / "scripts/browserskill-release.json").read_text(encoding="utf-8")
    )
    assert downloads["browserskill"]["version"] == release["version"]
    assert downloads["browserskill"]["source_commit"] == release["daemon"]["source_commit"]
    assert downloads["browserskill"]["source_commit"] == release["extension"]["source_commit"]
    assert set(downloads["duckdb"]["extensions"]) == {"spatial", "excel"}
    assert downloads["duckdb"]["version"] == _duckdb_version_from_go_mod(REPO_ROOT)
    assert all(
        item["platform"] == document["platform"]["duckdb"]
        for item in downloads["duckdb"]["extensions"].values()
    )

    public = _json_text(document).lower()
    for forbidden in ("mirror", "proxy", "credential", "password", "secret", "token"):
        assert forbidden not in public
    assert "latest" not in public


def test_upstream_component_scripts_verify_locked_archives_before_extracting() -> None:
    anydoc = ANYDOC_BUILD_PATH.read_text(encoding="utf-8")
    browser = BROWSER_SKILL_BUILD_PATH.read_text(encoding="utf-8")

    for variable in ("ANYDOC_CRATE_VERSION", "ANYDOC_CRATE_ORIGIN", "ANYDOC_CRATE_SHA256"):
        assert variable in anydoc
    assert "rsproxy.cn" not in anydoc
    assert anydoc.index("sha256sum -c") < anydoc.index("tar -x")

    for variable in (
        "BROWSERSKILL_VERSION",
        "BROWSERSKILL_SOURCE_COMMIT",
        "BROWSERSKILL_SOURCE_ORIGIN",
        "BROWSERSKILL_SOURCE_SHA256",
        "PNPM_VERSION",
        "PNPM_ORIGIN",
        "PNPM_SHA256",
        "PNPM_STORE_DIR",
        "CARGO_TARGET_DIR",
    ):
        assert variable in browser
    assert "git clone" not in browser
    assert "npx" not in browser
    assert browser.index("sha256sum -c") < browser.index("tar -x")
    assert "pnpm install --frozen-lockfile" in browser
    assert "cargo build --locked" in browser


def test_dockerfile_isolates_and_caches_anydoc_and_browserskill() -> None:
    source = DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert not re.search(r"^(?:<<<<<<<|=======|>>>>>>>)", source, re.M)
    assert "ARG BROWSERSKILL_IMAGE" in source
    assert "ARG RUST_IMAGE" in source
    assert "FROM ${RUST_IMAGE} AS anydoc-builder" in source
    assert "FROM --platform=$TARGETPLATFORM ${BROWSERSKILL_IMAGE} AS browserskill" in source
    assert "FROM ${BUILDER_IMAGE} AS lock-plan" in source
    assert "FROM lock-plan AS builder" in source

    anydoc_start = source.index("FROM ${RUST_IMAGE} AS anydoc-builder")
    browser_start = source.index(
        "FROM --platform=$TARGETPLATFORM ${BROWSERSKILL_IMAGE} AS browserskill"
    )
    builder_start = source.index("FROM lock-plan AS builder")
    first_component = min(anydoc_start, browser_start)
    component_region = source[first_component:builder_start]
    assert "COPY . ." not in component_region

    instructions = _dockerfile_instructions(source)
    anydoc_run = next(
        item
        for item in instructions
        if item.startswith("RUN ") and "build-anydoc-lib.sh" in item
    )
    browser_run = next(
        item
        for item in instructions
        if item.startswith("RUN ") and "build_browserskill.sh" in item
    )
    browser_region = source[browser_start:builder_start]
    assert (
        "COPY --from=lock-plan /etc/ssl/certs/ca-certificates.crt "
        "/etc/ssl/certs/ca-certificates.crt"
    ) in browser_region
    assert set(_cache_mounts(anydoc_run)) == {
        "/usr/local/cargo/registry",
        "/usr/local/cargo/git",
        "/app/third_party/anydoc-go/target",
    }
    assert set(_cache_mounts(browser_run)) == {
        "/root/.local/share/pnpm/store",
        "/usr/local/cargo/registry",
        "/usr/local/cargo/git",
        "/var/cache/browserskill-cargo-target",
    }
    assert "COPY --from=anydoc-builder" in source
    assert "make build-prod GO_BUILD_TAGS=anydoc" in source
    assert "go version -m /app/WeKnora" in source
    assert "-tags=anydoc" in source
    assert "COPY --from=browserskill /opt/weknora/browserskill" in source
    assert "COPY --from=builder /license-bundle/ ./" in source
    for floating in ("rustup.rs", "default-toolchain stable", "@latest", "npx --yes"):
        assert floating not in source


def test_runtime_reuse_protects_upstream_runtime_resources() -> None:
    module = _artifact_module()
    source = inspect.getsource(module.runtime_reuse_facts)
    for path in ("LICENSE", "THIRD_PARTY_NOTICES.md", "licenses"):
        assert path in source
