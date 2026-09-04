#!/usr/bin/env python3
"""Run BA0's standalone, exact-image container artifact smoke."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


class ArtifactSmokeError(RuntimeError):
    """Raised when exact-image smoke authority cannot be proven."""


Runner = Callable[..., subprocess.CompletedProcess[str]]

_CONTEXT = "colima-g1-build"
_COMPOSE_FILE = "deploy/local-build/docker-compose.app-exact.yml"
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT_ID = re.compile(r"[0-9a-f]{40}")
_NONCE = re.compile(r"[0-9a-f]{16}")
_LABEL_FIELDS = {
    "io.insurancekb.app.artifact-identity": "artifact_identity",
    "io.insurancekb.app.build-source-head": "build_source_head",
    "io.insurancekb.app.manifest-sha256": "manifest_sha256",
    "io.insurancekb.app.dependency-lock-sha256": "dependency_lock_sha256",
    "io.insurancekb.app.target": "target",
    "io.insurancekb.app.platform": "platform",
}
_EFFECTS = {
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
_COMMON_SMOKE_COMMANDS = (
    "set -eu",
    "test -x /app/WeKnora",
    "test -d /app/config",
    "test -d /app/scripts",
    "test -d /app/migrations",
    "test -d /app/dataset/samples",
    "test -d /app/skills/preloaded",
    "test -d /home/appuser/.duckdb",
)


def _read_object(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactSmokeError(f"cannot read {description}: {path}") from exc
    if not isinstance(value, dict):
        raise ArtifactSmokeError(f"{description} must be a JSON object")
    return value


def _docker_environment() -> dict[str, str]:
    environment = {
        name: value
        for name in ("PATH", "HOME", "TMPDIR", "DOCKER_CONFIG")
        if (value := os.environ.get(name))
    }
    environment.setdefault("PATH", os.defpath)
    return environment


def _docker(
    runner: Runner,
    arguments: tuple[str, ...],
    *,
    root: Path,
    description: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = runner(
        arguments,
        cwd=root,
        capture_output=True,
        text=True,
        env=_docker_environment(),
    )
    if check and result.returncode != 0:
        raise ArtifactSmokeError(f"Docker {description} failed: {result.stderr.strip()}")
    return result


def _required_labels(receipt: Mapping[str, Any]) -> dict[str, str]:
    if receipt.get("contract") != "ba0-app-build-receipt.v1":
        raise ArtifactSmokeError("D2 receipt contract is invalid")
    if receipt.get("status") != "PASS":
        raise ArtifactSmokeError("D2 receipt status is not PASS")
    image_id = receipt.get("image_id")
    if not isinstance(image_id, str) or _IMAGE_ID.fullmatch(image_id) is None:
        raise ArtifactSmokeError("D2 receipt image must be an exact sha256 image ID")
    if receipt.get("platform") != "linux/arm64" or receipt.get("target") != "runtime":
        raise ArtifactSmokeError("D2 receipt platform or target is invalid")
    build_source = receipt.get("build_source_head")
    if not isinstance(build_source, str) or _COMMIT_ID.fullmatch(build_source) is None:
        raise ArtifactSmokeError("D2 receipt build-source commit is invalid")
    integration_head = receipt.get("integration_head")
    if (
        not isinstance(integration_head, str)
        or _COMMIT_ID.fullmatch(integration_head) is None
    ):
        raise ArtifactSmokeError("D2 receipt integration commit is invalid")
    artifact_identity = receipt.get("artifact_identity")
    if (
        not isinstance(artifact_identity, str)
        or _IMAGE_ID.fullmatch(artifact_identity) is None
    ):
        raise ArtifactSmokeError("D2 receipt artifact identity is invalid")
    for field in ("manifest_sha256", "dependency_lock_sha256"):
        value = receipt.get(field)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ArtifactSmokeError(f"D2 receipt provenance hash is invalid: {field}")
    labels = receipt.get("labels")
    if not isinstance(labels, Mapping):
        raise ArtifactSmokeError("D2 receipt labels are missing")
    expected: dict[str, str] = {}
    for label, field in _LABEL_FIELDS.items():
        value = receipt.get(field)
        if not isinstance(value, str) or not value:
            raise ArtifactSmokeError(f"D2 receipt field is missing: {field}")
        if labels.get(label) != value:
            raise ArtifactSmokeError(f"D2 receipt label mismatch: {label}")
        expected[label] = value
    return expected


def _inspect_source(
    record: Mapping[str, Any], image_id: str, labels: Mapping[str, str]
) -> None:
    if record.get("Id") != image_id:
        raise ArtifactSmokeError("image identity differs from the D2 receipt")
    if record.get("Os") != "linux":
        raise ArtifactSmokeError("image OS is not linux")
    if record.get("Architecture") != "arm64":
        raise ArtifactSmokeError("image architecture is not arm64")
    config = record.get("Config")
    actual = config.get("Labels") if isinstance(config, Mapping) else None
    if not isinstance(actual, Mapping):
        raise ArtifactSmokeError("image labels are missing")
    for name, value in labels.items():
        if actual.get(name) != value:
            raise ArtifactSmokeError(f"image label mismatch: {name}")


def _command_script(value: object, *, healthcheck: bool) -> str:
    if not isinstance(value, list):
        raise ArtifactSmokeError("smoke command must use executable argv")
    if healthcheck:
        if len(value) != 2 or value[0] != "CMD-SHELL":
            raise ArtifactSmokeError("healthcheck argv is invalid")
        script = value[1]
    else:
        if len(value) != 3 or value[:2] not in (
            ["/bin/sh", "-ec"],
            ["/bin/sh", "-ce"],
        ):
            raise ArtifactSmokeError("entrypoint argv is invalid")
        script = value[2]
    if not isinstance(script, str) or not script.strip():
        raise ArtifactSmokeError("smoke command script is empty")
    return script


def _validate_script(script: str, *, healthcheck: bool) -> None:
    script_kind = "healthcheck" if healthcheck else "entrypoint"
    library_output = (
        "/tmp/ba0-health-ldd.out" if healthcheck else "/tmp/ba0-ldd.out"
    )
    expected = (
        *_COMMON_SMOKE_COMMANDS,
        f"ldd /app/WeKnora > {library_output}",
        f"! grep -q 'not found' {library_output}",
        *(("sleep infinity",) if not healthcheck else ()),
    )
    commands = tuple(command.strip() for command in re.split(r"[;\n]+", script))
    commands = tuple(command for command in commands if command)
    if commands != expected:
        raise ArtifactSmokeError(f"{script_kind} command contract is invalid")


def _validate_topology(document: Mapping[str, Any], image_id: str) -> None:
    if set(document) - {"name", "services"}:
        raise ArtifactSmokeError("standalone topology has unknown top-level fields")
    services = document.get("services")
    if not isinstance(services, Mapping) or set(services) != {"app-smoke"}:
        raise ArtifactSmokeError("standalone topology must contain only app-smoke")
    service = services["app-smoke"]
    if not isinstance(service, Mapping):
        raise ArtifactSmokeError("app-smoke topology is invalid")
    allowed_service_fields = {
        "command",
        "entrypoint",
        "environment",
        "healthcheck",
        "image",
        "network_mode",
        "pull_policy",
        "read_only",
        "tmpfs",
    }
    unknown_service_fields = set(service) - allowed_service_fields
    if unknown_service_fields:
        raise ArtifactSmokeError(
            "standalone topology has unknown service fields: "
            f"{sorted(unknown_service_fields)}"
        )
    if "command" in service and service["command"] is not None:
        raise ArtifactSmokeError("standalone topology command must be empty")
    expected = {
        "image": image_id,
        "pull_policy": "never",
        "network_mode": "none",
        "read_only": True,
    }
    for name, value in expected.items():
        if service.get(name) != value:
            raise ArtifactSmokeError(f"standalone topology field is invalid: {name}")
    for forbidden in (
        "build",
        "ports",
        "volumes",
        "container_name",
        "env_file",
        "depends_on",
        "networks",
        "links",
    ):
        if forbidden in service:
            raise ArtifactSmokeError(f"standalone topology forbids {forbidden}")
    tmpfs = service.get("tmpfs")
    if tmpfs != ["/tmp"]:
        raise ArtifactSmokeError("standalone topology requires only /tmp tmpfs")
    environment = service.get("environment")
    if not isinstance(environment, Mapping) or set(environment) != {"AUTO_MIGRATE"}:
        raise ArtifactSmokeError("standalone topology environment is not closed")
    if str(environment.get("AUTO_MIGRATE")).lower() != "false":
        raise ArtifactSmokeError("standalone topology must disable migrations")
    entrypoint = _command_script(service.get("entrypoint"), healthcheck=False)
    health = service.get("healthcheck")
    if not isinstance(health, Mapping):
        raise ArtifactSmokeError("standalone topology healthcheck is missing")
    if set(health) != {"test", "interval", "timeout", "retries", "start_period"}:
        raise ArtifactSmokeError("standalone topology healthcheck fields are not closed")
    healthcheck = _command_script(health.get("test"), healthcheck=True)
    _validate_script(entrypoint, healthcheck=False)
    _validate_script(healthcheck, healthcheck=True)
    if re.search(
        r"\bsleep\s+infinity\b|\btail\s+-f\s+/dev/null\b|"
        r"\bwhile\s+(?::|true)\s*;?\s*do\b.*\bsleep\b.*\bdone\b",
        entrypoint,
        re.S,
    ) is None:
        raise ArtifactSmokeError("entrypoint does not keep the smoke container alive")
    public = json.dumps(document, sort_keys=True).lower()
    if "http" in public or any(
        forbidden in public
        for forbidden in ("postgres", "redis", "docreader", "provider", "8081")
    ):
        raise ArtifactSmokeError("standalone topology references a forbidden dependency")


def _preflight_output(path: Path) -> None:
    if path.exists():
        raise ArtifactSmokeError("D3 evidence output already exists")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        os.close(descriptor)
        Path(temporary_name).unlink()
    except OSError as exc:
        raise ArtifactSmokeError("cannot prepare D3 evidence output") from exc


def _write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    payload = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _compose_arguments(env_path: Path, project: str, action: str) -> tuple[str, ...]:
    prefix = (
        "docker",
        "--context",
        _CONTEXT,
        "compose",
        "--project-name",
        project,
        "--env-file",
        str(env_path),
        "-f",
        _COMPOSE_FILE,
    )
    suffixes = {
        "config": ("config", "--format", "json"),
        "up": (
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            "30",
            "--no-build",
            "--pull",
            "never",
            "app-smoke",
        ),
        "down": ("down", "--remove-orphans"),
    }
    return (*prefix, *suffixes[action])


def _base_receipt(d2: Mapping[str, Any], image_id: str, project: str) -> dict[str, Any]:
    return {
        "contract": "ba0-container-artifact-smoke.v1",
        "scope": "CONTAINER_ARTIFACT_SMOKE",
        "artifact_identity": d2["artifact_identity"],
        "build_source_head": d2["build_source_head"],
        "integration_head": d2["integration_head"],
        "image_id": image_id,
        "project": project,
        "build_invocations": 0,
        "pull_invocations": 0,
        "effects": dict(_EFFECTS),
    }


def run_exact_image_smoke(
    *,
    repo_root: str | os.PathLike[str],
    d2_receipt_path: str | os.PathLike[str],
    evidence_out: str | os.PathLike[str],
    nonce: str,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Validate and start one isolated container by exact image ID."""

    root = Path(repo_root).resolve(strict=True)
    d2 = _read_object(Path(d2_receipt_path), "D2 receipt")
    labels = _required_labels(d2)
    image_id = str(d2["image_id"])
    if _NONCE.fullmatch(nonce) is None:
        raise ArtifactSmokeError("D3 nonce must be 16 lowercase hex characters")
    project = f"insurancekb-ba0-d3-{nonce}"
    container = f"{project}-app-smoke-1"
    evidence = Path(evidence_out)
    _preflight_output(evidence)

    source_result = _docker(
        runner,
        (
            "docker",
            "--context",
            _CONTEXT,
            "image",
            "inspect",
            image_id,
            "--format",
            "{{json .}}",
        ),
        root=root,
        description="source image inspect",
    )
    try:
        source_record = json.loads(source_result.stdout)
    except json.JSONDecodeError as exc:
        raise ArtifactSmokeError("source image inspect returned invalid JSON") from exc
    if not isinstance(source_record, Mapping):
        raise ArtifactSmokeError("source image inspect returned a non-object")
    _inspect_source(source_record, image_id, labels)

    with tempfile.TemporaryDirectory(prefix="ba0-d3-") as temporary_directory:
        env_path = Path(temporary_directory).resolve() / "exact-image.env"
        env_path.write_text(f"BA0_APP_IMAGE={image_id}\n", encoding="utf-8")
        env_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

        config_result = _docker(
            runner,
            _compose_arguments(env_path, project, "config"),
            root=root,
            description="Compose config",
        )
        try:
            rendered = json.loads(config_result.stdout)
        except json.JSONDecodeError as exc:
            raise ArtifactSmokeError("Compose config returned invalid JSON") from exc
        if not isinstance(rendered, Mapping):
            raise ArtifactSmokeError("Compose config returned a non-object")
        _validate_topology(rendered, image_id)

        collision = _docker(
            runner,
            (
                "docker",
                "--context",
                _CONTEXT,
                "ps",
                "--all",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={project}",
            ),
            root=root,
            description="project collision check",
        )
        if collision.stdout.strip():
            raise ArtifactSmokeError("D3 Compose project collision")

        cleanup = "NOT_RUN"
        runtime_image_id: str | None = None
        failure: ArtifactSmokeError | None = None
        mutation_started = False
        try:
            mutation_started = True
            _docker(
                runner,
                _compose_arguments(env_path, project, "up"),
                root=root,
                description="Compose up",
            )
            runtime_result = _docker(
                runner,
                (
                    "docker",
                    "--context",
                    _CONTEXT,
                    "inspect",
                    container,
                    "--format",
                    "{{json .}}",
                ),
                root=root,
                description="runtime inspect",
            )
            try:
                runtime = json.loads(runtime_result.stdout)
            except json.JSONDecodeError as exc:
                raise ArtifactSmokeError("runtime inspect returned invalid JSON") from exc
            if not isinstance(runtime, Mapping):
                raise ArtifactSmokeError("runtime inspect returned a non-object")
            runtime_image_id = runtime.get("Image")
            state = runtime.get("State")
            health = state.get("Health") if isinstance(state, Mapping) else None
            if runtime_image_id != image_id:
                raise ArtifactSmokeError("runtime image identity differs from D2")
            if not isinstance(state, Mapping) or state.get("Status") != "running":
                raise ArtifactSmokeError("runtime container is not running")
            if not isinstance(health, Mapping) or health.get("Status") != "healthy":
                raise ArtifactSmokeError("runtime container health is not healthy")
        except ArtifactSmokeError as exc:
            failure = exc
        finally:
            if mutation_started:
                cleanup_result = _docker(
                    runner,
                    _compose_arguments(env_path, project, "down"),
                    root=root,
                    description="Compose cleanup",
                    check=False,
                )
                cleanup = "PASS" if cleanup_result.returncode == 0 else "FAIL"

        receipt = {
            **_base_receipt(d2, image_id, project),
            "status": "FAIL" if failure is not None or cleanup != "PASS" else "PASS",
            "runtime_image_id": runtime_image_id,
            "cleanup": cleanup,
        }
        _write_receipt(evidence, receipt)
        if failure is not None:
            raise failure
        if cleanup != "PASS":
            raise ArtifactSmokeError("D3 cleanup failed")
        return receipt


def _main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--d2-receipt", required=True)
    parser.add_argument("--evidence-out", required=True)
    parser.add_argument("--nonce", default=None)
    parsed = parser.parse_args(arguments)
    nonce = parsed.nonce or secrets.token_hex(8)
    receipt = run_exact_image_smoke(
        repo_root=parsed.repo_root,
        d2_receipt_path=parsed.d2_receipt,
        evidence_out=parsed.evidence_out,
        nonce=nonce,
    )
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_main())
    except ArtifactSmokeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
