from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from stat import S_IMODE

import pytest

from insurance_harness.live_env import compose as compose_module
from insurance_harness.live_env.compose import (
    ComposeVerificationError,
    verify_rendered_compose,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def compliant_rendered_compose() -> dict[str, object]:
    return {
        "services": {
            "app": {
                "image": "example/app:1.2.3@sha256:" + "a" * 64,
                "ports": [{"host_ip": "127.0.0.1", "published": "8080", "target": 8080}],
                "healthcheck": {"test": ["CMD", "true"]},
            },
            "frontend": {
                "image": "example/frontend:1.2.3@sha256:" + "b" * 64,
                "ports": [{"host_ip": "127.0.0.1", "published": "8081", "target": 80}],
                "healthcheck": {"test": ["CMD", "true"]},
            },
            "harness-postgres": {
                "image": "postgres:16.4@sha256:" + "c" * 64,
                "ports": [{"host_ip": "127.0.0.1", "published": "5442", "target": 5432}],
                "environment": {"POSTGRES_PASSWORD": "random-local-secret"},
                "healthcheck": {"test": ["CMD-SHELL", "pg_isready"]},
            },
            "redis": {
                "image": "redis:7.0-alpine@sha256:" + "d" * 64,
                "healthcheck": {"test": ["CMD", "redis-cli", "ping"]},
            },
            "postgres": {
                "image": "example/postgres:17@sha256:" + "e" * 64,
                "healthcheck": {"test": ["CMD", "pg_isready"]},
            },
            "docreader": {
                "image": "example/docreader:1.2.3@sha256:" + "f" * 64,
                "healthcheck": {"test": ["CMD", "grpc_health_probe"]},
            },
        }
    }


@pytest.fixture
def compliant_lock() -> dict[str, str]:
    return {
        "app": "example/app:1.2.3@sha256:" + "a" * 64,
        "frontend": "example/frontend:1.2.3@sha256:" + "b" * 64,
        "harness-postgres": "postgres:16.4@sha256:" + "c" * 64,
        "redis": "redis:7.0-alpine@sha256:" + "d" * 64,
        "postgres": "example/postgres:17@sha256:" + "e" * 64,
        "docreader": "example/docreader:1.2.3@sha256:" + "f" * 64,
    }


@pytest.mark.parametrize(
    "port",
    ["8080:8080", "0.0.0.0:8080:8080", "[::]:8080:8080"],
    ids=["bare", "ipv4-any", "ipv6-any"],
)
def test_r2_1_rejects_non_loopback_published_ports(
    compliant_rendered_compose: dict[str, object],
    compliant_lock: dict[str, str],
    port: str,
) -> None:
    rendered = deepcopy(compliant_rendered_compose)
    services = rendered["services"]
    assert isinstance(services, dict)
    service = services["app"]
    assert isinstance(service, dict)
    service["ports"] = [port]

    with pytest.raises(ComposeVerificationError, match="loopback"):
        verify_rendered_compose(rendered, compliant_lock)


def test_r2_1_rejects_host_network_mode(
    compliant_rendered_compose: dict[str, object], compliant_lock: dict[str, str]
) -> None:
    rendered = deepcopy(compliant_rendered_compose)
    services = rendered["services"]
    assert isinstance(services, dict)
    service = services["redis"]
    assert isinstance(service, dict)
    service["network_mode"] = "host"

    with pytest.raises(ComposeVerificationError, match="host network"):
        verify_rendered_compose(rendered, compliant_lock)


def test_r2_1_rejects_dependency_published_port(
    compliant_rendered_compose: dict[str, object], compliant_lock: dict[str, str]
) -> None:
    rendered = deepcopy(compliant_rendered_compose)
    services = rendered["services"]
    assert isinstance(services, dict)
    service = services["redis"]
    assert isinstance(service, dict)
    service["ports"] = ["127.0.0.1:6379:6379"]

    with pytest.raises(ComposeVerificationError, match="must not publish"):
        verify_rendered_compose(rendered, compliant_lock)


def test_r2_1_rejects_latest_image_tag(
    compliant_rendered_compose: dict[str, object], compliant_lock: dict[str, str]
) -> None:
    rendered = deepcopy(compliant_rendered_compose)
    services = rendered["services"]
    assert isinstance(services, dict)
    service = services["redis"]
    assert isinstance(service, dict)
    service["image"] = "redis:latest"

    with pytest.raises(ComposeVerificationError, match="latest"):
        verify_rendered_compose(rendered, compliant_lock)


def test_r2_1_rejects_image_without_digest(
    compliant_rendered_compose: dict[str, object], compliant_lock: dict[str, str]
) -> None:
    rendered = deepcopy(compliant_rendered_compose)
    services = rendered["services"]
    assert isinstance(services, dict)
    service = services["redis"]
    assert isinstance(service, dict)
    service["image"] = "redis:7.0-alpine"

    with pytest.raises(ComposeVerificationError, match="digest"):
        verify_rendered_compose(rendered, compliant_lock)


def test_r2_1_rejects_fixed_harness_password(
    compliant_rendered_compose: dict[str, object], compliant_lock: dict[str, str]
) -> None:
    rendered = deepcopy(compliant_rendered_compose)
    services = rendered["services"]
    assert isinstance(services, dict)
    service = services["harness-postgres"]
    assert isinstance(service, dict)
    environment = service["environment"]
    assert isinstance(environment, dict)
    environment["POSTGRES_PASSWORD"] = "harness"

    with pytest.raises(ComposeVerificationError, match="password"):
        verify_rendered_compose(rendered, compliant_lock)


def test_r2_1_rejects_missing_healthcheck(
    compliant_rendered_compose: dict[str, object], compliant_lock: dict[str, str]
) -> None:
    rendered = deepcopy(compliant_rendered_compose)
    services = rendered["services"]
    assert isinstance(services, dict)
    service = services["redis"]
    assert isinstance(service, dict)
    service.pop("healthcheck")

    with pytest.raises(ComposeVerificationError, match="healthcheck"):
        verify_rendered_compose(rendered, compliant_lock)


def test_r2_1_rejects_image_lock_mismatch(
    compliant_rendered_compose: dict[str, object], compliant_lock: dict[str, str]
) -> None:
    lock = dict(compliant_lock)
    lock["redis"] = "redis:7.0-alpine@sha256:" + "e" * 64

    with pytest.raises(ComposeVerificationError, match="image lock"):
        verify_rendered_compose(compliant_rendered_compose, lock)


def test_r2_1_accepts_compliant_rendered_compose(
    compliant_rendered_compose: dict[str, object], compliant_lock: dict[str, str]
) -> None:
    verify_rendered_compose(compliant_rendered_compose, compliant_lock)


def test_r2_1_weknora_verifier_rejects_missing_core_service(
    compliant_rendered_compose: dict[str, object], compliant_lock: dict[str, str]
) -> None:
    rendered = deepcopy(compliant_rendered_compose)
    services = rendered["services"]
    assert isinstance(services, dict)
    services.pop("docreader")
    assert hasattr(
        compose_module, "verify_weknora_compose"
    ), "R2.1 core-service verifier is missing"

    with pytest.raises(ComposeVerificationError, match="missing core service.*docreader"):
        compose_module.verify_weknora_compose(rendered, compliant_lock)


def test_r2_1_overrides_pin_only_the_six_service_minimum() -> None:
    weknora = (
        REPO_ROOT / "deploy/local-live/docker-compose.weknora.override.yml"
    ).read_text()
    harness = (
        REPO_ROOT / "deploy/local-live/docker-compose.harness.override.yml"
    ).read_text()

    def service_names(document: str) -> set[str]:
        names: set[str] = set()
        in_services = False
        for line in document.splitlines():
            if line == "services:":
                in_services = True
                continue
            if in_services and line and not line.startswith(" "):
                break
            if (
                in_services
                and line.startswith("  ")
                and not line.startswith("    ")
                and line.strip().endswith(":")
            ):
                names.add(line.strip().removesuffix(":"))
        return names

    assert service_names(weknora) == {"app", "frontend", "postgres", "redis", "docreader"}
    assert service_names(harness) == {"harness-postgres"}
    assert ".env.local-live.runtime" not in weknora
    assert "required: false" in weknora
    assert "name: local-live-weknora" in weknora
    assert "REDISCLI_AUTH: ${REDIS_PASSWORD:?" in weknora
    assert 'redis-cli -a' not in weknora
    assert "name: local-live-harness-db" in harness
    assert "pg_isready" in harness
    assert "harness-postgres-data:/var/lib/postgresql/data" in harness


def _runtime_values(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in path.read_text().splitlines()
        if line and not line.startswith("#")
    )


def test_r2_1_runtime_environment_is_random_mode_0600_and_redacted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / ".env.local-live.runtime"
    assert hasattr(
        compose_module, "ensure_runtime_environment"
    ), "R2.1 runtime environment creator is missing"

    result = compose_module.ensure_runtime_environment(path)

    values = _runtime_values(path)
    assert S_IMODE(path.stat().st_mode) == 0o600
    assert values.keys() == {
        "DB_USER",
        "DB_NAME",
        "DB_PASSWORD",
        "REDIS_PASSWORD",
        "JWT_SECRET",
        "SYSTEM_AES_KEY",
        "HARNESS_POSTGRES_PASSWORD",
        "WEKNORA_VERSION",
        "WEKNORA_ADMIN_USERNAME",
        "WEKNORA_ADMIN_EMAIL",
        "WEKNORA_ADMIN_PASSWORD",
    }
    assert values["DB_USER"] == "weknora"
    assert values["DB_NAME"] == "weknora"
    assert values["WEKNORA_VERSION"] == "v0.6.3"
    assert values["WEKNORA_ADMIN_USERNAME"] == "insurancekb-local-admin"
    assert values["WEKNORA_ADMIN_EMAIL"] == (
        "insurancekb-local-admin@example.invalid"
    )
    assert len(values["SYSTEM_AES_KEY"].encode()) == 32
    secrets = {
        values[name]
        for name in (
            "DB_PASSWORD",
            "REDIS_PASSWORD",
            "JWT_SECRET",
            "SYSTEM_AES_KEY",
            "HARNESS_POSTGRES_PASSWORD",
            "WEKNORA_ADMIN_PASSWORD",
        )
    }
    assert len(secrets) == 6
    assert all(len(secret) >= 32 for secret in secrets)
    representation = repr(result)
    assert result.created is True
    assert all(value not in representation for value in values.values())
    assert all(f"{name}=SET" in representation for name in values)
    assert capsys.readouterr() == ("", "")


def test_r2_1_runtime_environment_reuses_valid_file_idempotently(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".env.local-live.runtime"
    first = compose_module.ensure_runtime_environment(path)
    original = path.read_bytes()

    second = compose_module.ensure_runtime_environment(path)

    assert first.created is True
    assert second.created is False
    assert path.read_bytes() == original
    assert S_IMODE(path.stat().st_mode) == 0o600


def test_r3_1_runtime_environment_upgrades_legacy_file_atomically(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".env.local-live.runtime"
    legacy = {
        "DB_USER": "weknora",
        "DB_NAME": "weknora",
        "DB_PASSWORD": "d" * 32,
        "REDIS_PASSWORD": "r" * 32,
        "JWT_SECRET": "j" * 32,
        "SYSTEM_AES_KEY": "a" * 32,
        "HARNESS_POSTGRES_PASSWORD": "h" * 32,
        "WEKNORA_VERSION": "v0.6.3",
    }
    path.write_text("".join(f"{name}={value}\n" for name, value in legacy.items()))
    path.chmod(0o600)

    result = compose_module.ensure_runtime_environment(path)

    values = _runtime_values(path)
    assert result.created is False
    assert {name: values[name] for name in legacy} == legacy
    assert values["WEKNORA_ADMIN_USERNAME"] == "insurancekb-local-admin"
    assert values["WEKNORA_ADMIN_EMAIL"].endswith("@example.invalid")
    assert len(values["WEKNORA_ADMIN_PASSWORD"]) >= 32
    assert S_IMODE(path.stat().st_mode) == 0o600


def test_r3_1_runtime_state_is_complete_atomic_and_preserves_credentials(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".env.local-live.runtime"
    compose_module.ensure_runtime_environment(path)
    before = _runtime_values(path)
    state = {
        "LOCAL_LIVE_TENANT_ID": "tenant-1",
        "LOCAL_LIVE_CHAT_MODEL_ID": "chat-1",
        "LOCAL_LIVE_EMBEDDING_MODEL_ID": "embedding-1",
        "LOCAL_LIVE_RERANK_MODEL_ID": "rerank-1",
        "LOCAL_LIVE_RAW_KB_ID": "raw-1",
        "LOCAL_LIVE_WIKI_KB_ID": "wiki-1",
        "LOCAL_LIVE_API_KEY_ID": "key-1",
        "LOCAL_LIVE_API_KEY": "local-tenant-secret",
        "LOCAL_LIVE_SPACE_ID": "space-1",
        "LOCAL_LIVE_KNOWLEDGE_ID": "knowledge-1",
        "LOCAL_LIVE_PARSER_FINGERPRINT": "weknora-v0.6.3",
    }

    compose_module.update_runtime_state(path, state)

    after = _runtime_values(path)
    assert {name: after[name] for name in before} == before
    assert {name: after[name] for name in state} == state
    assert S_IMODE(path.stat().st_mode) == 0o600
    assert compose_module.ensure_runtime_environment(path).created is False


def test_r3_1_partial_runtime_state_is_rejected_without_overwrite(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".env.local-live.runtime"
    compose_module.ensure_runtime_environment(path)
    original = path.read_bytes()

    with pytest.raises(ValueError, match="runtime state.*complete"):
        compose_module.update_runtime_state(
            path,
            {"LOCAL_LIVE_TENANT_ID": "tenant-1"},
        )

    assert path.read_bytes() == original


@pytest.mark.parametrize("invalid", ["insecure", "malformed", "example"])
def test_r2_1_runtime_environment_rejects_invalid_without_overwrite(
    tmp_path: Path, invalid: str
) -> None:
    path = tmp_path / ".env.local-live.runtime"
    compose_module.ensure_runtime_environment(path)
    if invalid == "insecure":
        path.chmod(0o644)
    elif invalid == "malformed":
        path.write_text(path.read_text() + "not-a-setting\n")
    else:
        path.write_text(
            path.read_text().replace(
                f"DB_PASSWORD={_runtime_values(path)['DB_PASSWORD']}",
                "DB_PASSWORD=password",
            )
        )
    original = path.read_bytes()
    original_mode = S_IMODE(path.stat().st_mode)

    with pytest.raises(ValueError, match="runtime environment.*invalid"):
        compose_module.ensure_runtime_environment(path)

    assert path.read_bytes() == original
    assert S_IMODE(path.stat().st_mode) == original_mode


def test_r2_1_harness_verifier_requires_its_single_service(
    compliant_lock: dict[str, str],
) -> None:
    assert hasattr(
        compose_module, "verify_harness_compose"
    ), "R2.1 Harness service verifier is missing"

    with pytest.raises(ComposeVerificationError, match="missing core service.*harness"):
        compose_module.verify_harness_compose({"services": {}}, compliant_lock)


def test_r2_1_six_image_lock_is_resolved_and_matches_overrides() -> None:
    lock = json.loads((REPO_ROOT / "deploy/local-live/images.lock").read_text())
    assert set(lock) == {
        "_status",
        "frontend",
        "app",
        "docreader",
        "postgres",
        "redis",
        "harness-postgres",
    }
    assert lock["_status"] == "RESOLVED_2026-07-15"
    assert all(
        value.count("@sha256:") == 1 and "UNRESOLVED" not in value
        for key, value in lock.items()
        if key != "_status"
    )
    override_text = "\n".join(
        (
            (REPO_ROOT / "deploy/local-live/docker-compose.weknora.override.yml").read_text(),
            (REPO_ROOT / "deploy/local-live/docker-compose.harness.override.yml").read_text(),
        )
    )
    assert all(
        value in override_text for key, value in lock.items() if key != "_status"
    )
