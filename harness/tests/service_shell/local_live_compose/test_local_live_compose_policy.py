"""Local-live compose: loopback ports, pinned images, secrets, healthchecks and overrides."""

from __future__ import annotations

from copy import deepcopy

import pytest

from insurance_harness.live_env import compose as compose_module
from insurance_harness.live_env.compose import (
    ComposeVerificationError,
    verify_rendered_compose,
)
from tests.service_shell.local_live_compose.helpers import REPO_ROOT


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


def test_r2_1_source_app_build_context_excludes_all_local_env_secrets() -> None:
    dockerignore = (REPO_ROOT / ".dockerignore").read_text().splitlines()

    assert ".env" in dockerignore
    assert ".env.*" in dockerignore


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
