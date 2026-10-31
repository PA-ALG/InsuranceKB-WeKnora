"""Local-live runtime environment: random 0600 values, idempotent reuse and AES keys."""

from __future__ import annotations

import os
import secrets
from copy import deepcopy
from pathlib import Path
from stat import S_IMODE

import pytest

from insurance_harness.live_env import compose as compose_module
from insurance_harness.live_env.compose import (
    ComposeVerificationError,
)
from tests.service_shell.local_live_compose.helpers import _runtime_values


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
        "TENANT_AES_KEY",
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
    assert len(values["TENANT_AES_KEY"].encode()) == 32
    assert len(values["SYSTEM_AES_KEY"].encode()) == 32
    assert values["TENANT_AES_KEY"] != values["SYSTEM_AES_KEY"]
    secrets = {
        values[name]
        for name in (
            "DB_PASSWORD",
            "REDIS_PASSWORD",
            "JWT_SECRET",
            "TENANT_AES_KEY",
            "SYSTEM_AES_KEY",
            "HARNESS_POSTGRES_PASSWORD",
            "WEKNORA_ADMIN_PASSWORD",
        )
    }
    assert len(secrets) == 7
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
    assert len(values["TENANT_AES_KEY"].encode()) == 32
    assert values["TENANT_AES_KEY"] != values["SYSTEM_AES_KEY"]
    assert S_IMODE(path.stat().st_mode) == 0o600


def test_r3_1_current_runtime_without_tenant_aes_key_is_atomically_migrated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / ".env.local-live.runtime"
    compose_module.ensure_runtime_environment(path)
    current = _runtime_values(path)
    current.pop("TENANT_AES_KEY", None)
    current.update(
        {
            "LOCAL_LIVE_TENANT_ID": "tenant-1",
            "LOCAL_LIVE_CHAT_MODEL_ID": "chat-1",
            "LOCAL_LIVE_EMBEDDING_MODEL_ID": "embedding-1",
            "LOCAL_LIVE_RERANK_MODEL_ID": "rerank-1",
            "LOCAL_LIVE_VLLM_MODEL_ID": "vlm-1",
            "LOCAL_LIVE_CHAT_ENDPOINT_FINGERPRINT": "a" * 64,
            "LOCAL_LIVE_EMBEDDING_ENDPOINT_FINGERPRINT": "b" * 64,
            "LOCAL_LIVE_RERANK_ENDPOINT_FINGERPRINT": "c" * 64,
            "LOCAL_LIVE_VLLM_ENDPOINT_FINGERPRINT": "d" * 64,
            "LOCAL_LIVE_RAW_KB_ID": "raw-1",
            "LOCAL_LIVE_WIKI_KB_ID": "wiki-1",
            "LOCAL_LIVE_API_KEY_ID": "key-1",
            "LOCAL_LIVE_SPACE_ID": "space-1",
            "LOCAL_LIVE_KNOWLEDGE_ID": "knowledge-1",
            "LOCAL_LIVE_PARSER_FINGERPRINT": "weknora-v0.6.3",
        }
    )
    path.write_text("".join(f"{name}={value}\n" for name, value in current.items()))
    path.chmod(0o600)
    replacements: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def tracked_replace(source: Path, destination: Path) -> None:
        replacements.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", tracked_replace)

    result = compose_module.ensure_runtime_environment(path)

    migrated = _runtime_values(path)
    assert result.created is False
    assert {name: migrated[name] for name in current} == current
    assert len(migrated["TENANT_AES_KEY"].encode()) == 32
    assert migrated["TENANT_AES_KEY"] != migrated["SYSTEM_AES_KEY"]
    assert replacements and replacements[-1][1] == path
    assert S_IMODE(path.stat().st_mode) == 0o600
    captured = capsys.readouterr()
    assert captured == ("", "")
    assert all(
        secret not in repr(result)
        for secret in (migrated["TENANT_AES_KEY"], migrated["SYSTEM_AES_KEY"])
    )


def test_r3_1_tenant_aes_migration_retries_deterministic_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / ".env.local-live.runtime"
    system_key = "s" * 32
    current = {
        "DB_USER": "weknora",
        "DB_NAME": "weknora",
        "DB_PASSWORD": "d" * 32,
        "REDIS_PASSWORD": "r" * 32,
        "JWT_SECRET": "j" * 32,
        "SYSTEM_AES_KEY": system_key,
        "HARNESS_POSTGRES_PASSWORD": "h" * 32,
        "WEKNORA_VERSION": "v0.6.3",
        "WEKNORA_ADMIN_USERNAME": "insurancekb-local-admin",
        "WEKNORA_ADMIN_EMAIL": "insurancekb-local-admin@example.invalid",
        "WEKNORA_ADMIN_PASSWORD": "w" * 32,
    }
    path.write_text("".join(f"{name}={value}\n" for name, value in current.items()))
    path.chmod(0o600)
    generated: list[str] = []

    def deterministic_token_hex(byte_count: int) -> str:
        if byte_count == 8:
            return "f" * 16
        value = system_key if not generated else "t" * 32
        generated.append(value)
        return value

    monkeypatch.setattr(secrets, "token_hex", deterministic_token_hex)

    compose_module.ensure_runtime_environment(path)

    migrated = _runtime_values(path)
    assert generated == [system_key, "t" * 32]
    assert migrated["TENANT_AES_KEY"] == "t" * 32
    assert migrated["TENANT_AES_KEY"] != migrated["SYSTEM_AES_KEY"]


@pytest.mark.parametrize(
    ("name", "invalid"),
    (
        ("TENANT_AES_KEY", ""),
        ("TENANT_AES_KEY", "t" * 31),
        ("TENANT_AES_KEY", "t" * 33),
        ("SYSTEM_AES_KEY", ""),
        ("SYSTEM_AES_KEY", "s" * 31),
        ("SYSTEM_AES_KEY", "s" * 33),
    ),
)
def test_r2_1_r3_1_runtime_rejects_invalid_aes_keys_without_overwrite(
    tmp_path: Path,
    name: str,
    invalid: str,
) -> None:
    path = tmp_path / ".env.local-live.runtime"
    compose_module.ensure_runtime_environment(path)
    values = _runtime_values(path)
    values[name] = invalid
    path.write_text("".join(f"{field}={value}\n" for field, value in values.items()))
    original = path.read_bytes()

    with pytest.raises(ValueError, match="AES key"):
        compose_module.ensure_runtime_environment(path)

    assert path.read_bytes() == original


@pytest.mark.parametrize(
    ("name", "invalid"),
    (
        ("TENANT_AES_KEY", ""),
        ("TENANT_AES_KEY", "t" * 31),
        ("SYSTEM_AES_KEY", "s" * 33),
    ),
)
def test_r2_1_r3_1_rendered_app_requires_two_exact_32_byte_aes_keys(
    compliant_rendered_compose: dict[str, object],
    compliant_lock: dict[str, str],
    name: str,
    invalid: str,
) -> None:
    rendered = deepcopy(compliant_rendered_compose)
    compose_module.verify_weknora_compose(rendered, compliant_lock)
    services = rendered["services"]
    assert isinstance(services, dict)
    app = services["app"]
    assert isinstance(app, dict)
    environment = app["environment"]
    assert isinstance(environment, dict)
    environment[name] = invalid

    with pytest.raises(ComposeVerificationError, match="AES key"):
        compose_module.verify_weknora_compose(rendered, compliant_lock)
