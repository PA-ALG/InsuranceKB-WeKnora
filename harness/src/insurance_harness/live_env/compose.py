from __future__ import annotations

import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from stat import S_IMODE
from typing import cast

_ALLOWED_PUBLISHED_PORT_SERVICES = frozenset({"app", "frontend", "harness-postgres"})
_REQUIRED_HEALTHCHECK_SERVICES = frozenset(
    {"app", "frontend", "harness-postgres", "postgres", "redis", "docreader"}
)
_IMAGE_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$", re.IGNORECASE)
_ENDPOINT_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_KNOWN_FIXED_PASSWORDS = frozenset({"harness", "password", "postgres", "changeme"})
_WEKNORA_CORE_SERVICES = frozenset({"app", "frontend", "postgres", "redis", "docreader"})
_HARNESS_CORE_SERVICES = frozenset({"harness-postgres"})
_RUNTIME_ENVIRONMENT_NAME = ".env.local-live.runtime"
_PRE_TENANT_RUNTIME_KEYS = (
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
)
_RUNTIME_KEYS = (
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
)
_LEGACY_RUNTIME_KEYS = _PRE_TENANT_RUNTIME_KEYS[:8]
_RUNTIME_STATE_KEYS = (
    "LOCAL_LIVE_TENANT_ID",
    "LOCAL_LIVE_CHAT_MODEL_ID",
    "LOCAL_LIVE_EMBEDDING_MODEL_ID",
    "LOCAL_LIVE_RERANK_MODEL_ID",
    "LOCAL_LIVE_VLLM_MODEL_ID",
    "LOCAL_LIVE_CHAT_ENDPOINT_FINGERPRINT",
    "LOCAL_LIVE_EMBEDDING_ENDPOINT_FINGERPRINT",
    "LOCAL_LIVE_RERANK_ENDPOINT_FINGERPRINT",
    "LOCAL_LIVE_VLLM_ENDPOINT_FINGERPRINT",
    "LOCAL_LIVE_RAW_KB_ID",
    "LOCAL_LIVE_WIKI_KB_ID",
    "LOCAL_LIVE_API_KEY_ID",
    "LOCAL_LIVE_SPACE_ID",
    "LOCAL_LIVE_KNOWLEDGE_ID",
    "LOCAL_LIVE_PARSER_FINGERPRINT",
)
_PRE_TASK4_RUNTIME_STATE_KEYS = (
    "LOCAL_LIVE_TENANT_ID",
    "LOCAL_LIVE_CHAT_MODEL_ID",
    "LOCAL_LIVE_EMBEDDING_MODEL_ID",
    "LOCAL_LIVE_RERANK_MODEL_ID",
    "LOCAL_LIVE_RAW_KB_ID",
    "LOCAL_LIVE_WIKI_KB_ID",
    "LOCAL_LIVE_API_KEY_ID",
    "LOCAL_LIVE_API_KEY",
    "LOCAL_LIVE_SPACE_ID",
    "LOCAL_LIVE_KNOWLEDGE_ID",
    "LOCAL_LIVE_PARSER_FINGERPRINT",
)
_TOKENIZED_CURRENT_RUNTIME_STATE_KEYS = (
    *_RUNTIME_STATE_KEYS,
    "LOCAL_LIVE_API_KEY",
)
_RUNTIME_SECRET_KEYS = frozenset(
    {
        "DB_PASSWORD",
        "REDIS_PASSWORD",
        "JWT_SECRET",
        "TENANT_AES_KEY",
        "SYSTEM_AES_KEY",
        "HARNESS_POSTGRES_PASSWORD",
        "WEKNORA_ADMIN_PASSWORD",
    }
)
_KNOWN_RUNTIME_EXAMPLES = frozenset(
    {"changeme", "example", "harness", "password", "postgres", "weknora"}
)
_ENDPOINT_FINGERPRINT_KEYS = tuple(
    name for name in _RUNTIME_STATE_KEYS if name.endswith("_ENDPOINT_FINGERPRINT")
)
class ComposeVerificationError(ValueError):
    """Rendered Compose configuration violates the local-live policy."""


class RuntimeEnvironmentError(ValueError):
    """Local runtime environment is unsafe or malformed."""


@dataclass(frozen=True, repr=False)
class RuntimeEnvironmentResult:
    """Redacted outcome from creating or validating the runtime environment."""

    created: bool
    fields: tuple[str, ...] = _RUNTIME_KEYS

    def __repr__(self) -> str:
        status = "CREATED" if self.created else "REUSED"
        fields = ", ".join(f"{name}=SET" for name in self.fields)
        return f"RuntimeEnvironmentResult(status={status}, fields=[{fields}])"


def _new_aes_key(*, different_from: str | None = None) -> str:
    value = secrets.token_hex(16)
    while value == different_from:
        value = secrets.token_hex(16)
    return value


def verify_weknora_compose(
    rendered: Mapping[str, object], image_lock: Mapping[str, str]
) -> None:
    services_value = rendered.get("services")
    if not isinstance(services_value, Mapping):
        raise ComposeVerificationError("rendered Compose services must be a mapping")
    missing = sorted(_WEKNORA_CORE_SERVICES - services_value.keys())
    if missing:
        raise ComposeVerificationError(f"missing core service: {missing[0]}")
    app = services_value.get("app")
    environment = app.get("environment") if isinstance(app, Mapping) else None
    if not isinstance(environment, Mapping):
        raise ComposeVerificationError("app AES key environment is invalid")
    aes_keys = tuple(environment.get(name) for name in ("TENANT_AES_KEY", "SYSTEM_AES_KEY"))
    if (
        any(
            not isinstance(value, str)
            or not value
            or len(value.encode("utf-8")) != 32
            for value in aes_keys
        )
        or aes_keys[0] == aes_keys[1]
    ):
        raise ComposeVerificationError("app AES key environment is invalid")
    verify_rendered_compose(rendered, image_lock)


def verify_harness_compose(
    rendered: Mapping[str, object], image_lock: Mapping[str, str]
) -> None:
    services_value = rendered.get("services")
    if not isinstance(services_value, Mapping):
        raise ComposeVerificationError("rendered Compose services must be a mapping")
    missing = sorted(_HARNESS_CORE_SERVICES - services_value.keys())
    if missing:
        raise ComposeVerificationError(f"missing core service: {missing[0]}")
    verify_rendered_compose(rendered, image_lock)


def ensure_runtime_environment(path: Path) -> RuntimeEnvironmentResult:
    """Create or validate the ignored, local-only Compose runtime environment."""

    if path.name != _RUNTIME_ENVIRONMENT_NAME:
        raise RuntimeEnvironmentError("runtime environment is invalid: unexpected path")
    if path.exists() or path.is_symlink():
        values = _validate_runtime_environment(path)
        _migrate_existing_runtime_environment(path, values)
        return RuntimeEnvironmentResult(created=False)

    path.parent.mkdir(parents=True, exist_ok=True)
    tenant_aes_key = _new_aes_key()
    system_aes_key = _new_aes_key(different_from=tenant_aes_key)
    values = {
        "DB_USER": "weknora",
        "DB_NAME": "weknora",
        "DB_PASSWORD": secrets.token_urlsafe(32),
        "REDIS_PASSWORD": secrets.token_urlsafe(32),
        "JWT_SECRET": secrets.token_urlsafe(32),
        "TENANT_AES_KEY": tenant_aes_key,
        "SYSTEM_AES_KEY": system_aes_key,
        "HARNESS_POSTGRES_PASSWORD": secrets.token_urlsafe(32),
        "WEKNORA_VERSION": "v0.6.3",
        "WEKNORA_ADMIN_USERNAME": "insurancekb-local-admin",
        "WEKNORA_ADMIN_EMAIL": "insurancekb-local-admin@example.invalid",
        "WEKNORA_ADMIN_PASSWORD": secrets.token_urlsafe(32),
    }
    payload = "".join(f"{name}={values[name]}\n" for name in _RUNTIME_KEYS)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        values = _validate_runtime_environment(path)
        _migrate_existing_runtime_environment(path, values)
        return RuntimeEnvironmentResult(created=False)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return RuntimeEnvironmentResult(created=True)


def _validate_runtime_environment(path: Path) -> dict[str, str]:
    try:
        if path.is_symlink() or S_IMODE(path.stat().st_mode) != 0o600:
            raise RuntimeEnvironmentError("runtime environment is invalid: permission")
        document = path.read_text(encoding="utf-8")
    except RuntimeEnvironmentError:
        raise
    except (OSError, UnicodeError):
        raise RuntimeEnvironmentError("runtime environment is invalid: unreadable") from None

    values: dict[str, str] = {}
    for raw_line in document.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or not name or name in values:
            raise RuntimeEnvironmentError("runtime environment is invalid: syntax")
        values[name] = value
    field_set = set(values)
    if field_set not in (
        set(_RUNTIME_KEYS),
        set(_PRE_TENANT_RUNTIME_KEYS),
        set(_LEGACY_RUNTIME_KEYS),
        set((*_RUNTIME_KEYS, *_RUNTIME_STATE_KEYS)),
        set((*_PRE_TENANT_RUNTIME_KEYS, *_RUNTIME_STATE_KEYS)),
        set((*_RUNTIME_KEYS, *_PRE_TASK4_RUNTIME_STATE_KEYS)),
        set((*_PRE_TENANT_RUNTIME_KEYS, *_PRE_TASK4_RUNTIME_STATE_KEYS)),
        set((*_RUNTIME_KEYS, *_TOKENIZED_CURRENT_RUNTIME_STATE_KEYS)),
        set((*_PRE_TENANT_RUNTIME_KEYS, *_TOKENIZED_CURRENT_RUNTIME_STATE_KEYS)),
    ):
        raise RuntimeEnvironmentError("runtime environment is invalid: fields")
    if values["DB_USER"] != "weknora" or values["DB_NAME"] != "weknora":
        raise RuntimeEnvironmentError("runtime environment is invalid: database identity")
    if values["WEKNORA_VERSION"] != "v0.6.3":
        raise RuntimeEnvironmentError("runtime environment is invalid: version")
    if set(_RUNTIME_STATE_KEYS).issubset(values):
        if any(not values[name] for name in _RUNTIME_STATE_KEYS):
            raise RuntimeEnvironmentError("runtime environment is invalid: state")
        if any(
            _ENDPOINT_FINGERPRINT.fullmatch(values[name]) is None
            for name in _ENDPOINT_FINGERPRINT_KEYS
        ):
            raise RuntimeEnvironmentError(
                "runtime environment is invalid: endpoint fingerprint"
            )
    if set(_PRE_TENANT_RUNTIME_KEYS).issubset(values) and (
        values["WEKNORA_ADMIN_USERNAME"] != "insurancekb-local-admin"
        or values["WEKNORA_ADMIN_EMAIL"]
        != "insurancekb-local-admin@example.invalid"
    ):
        raise RuntimeEnvironmentError("runtime environment is invalid: admin identity")
    if any(
        not values[name]
        or len(values[name].encode("utf-8")) != 32
        for name in ("TENANT_AES_KEY", "SYSTEM_AES_KEY")
        if name in values
    ):
        raise RuntimeEnvironmentError("runtime environment is invalid: AES key")
    if any(
        len(values[name]) < 32
        or values[name].casefold() in _KNOWN_RUNTIME_EXAMPLES
        for name in _RUNTIME_SECRET_KEYS
        if name in values
    ):
        raise RuntimeEnvironmentError("runtime environment is invalid: secret")
    if (
        "TENANT_AES_KEY" in values
        and values["TENANT_AES_KEY"] == values["SYSTEM_AES_KEY"]
    ):
        raise RuntimeEnvironmentError("runtime environment is invalid: AES key")
    if set(_RUNTIME_STATE_KEYS).issubset(values) and any(
        not values[name] for name in _RUNTIME_STATE_KEYS
    ):
        raise RuntimeEnvironmentError("runtime environment is invalid: state")
    return values


def _upgrade_runtime_environment(path: Path, legacy: Mapping[str, str]) -> None:
    values = dict(legacy)
    values.update(
        {
            "WEKNORA_ADMIN_USERNAME": "insurancekb-local-admin",
            "WEKNORA_ADMIN_EMAIL": "insurancekb-local-admin@example.invalid",
            "WEKNORA_ADMIN_PASSWORD": secrets.token_urlsafe(32),
            "TENANT_AES_KEY": _new_aes_key(
                different_from=values["SYSTEM_AES_KEY"]
            ),
        }
    )
    _write_runtime_environment(path, values, _RUNTIME_KEYS)
    _validate_runtime_environment(path)


def _migrate_existing_runtime_environment(
    path: Path,
    values: Mapping[str, str],
) -> None:
    fields = set(values)
    if fields == set(_LEGACY_RUNTIME_KEYS):
        _upgrade_runtime_environment(path, values)
        return
    pre_tenant_layouts = (
        (),
        _RUNTIME_STATE_KEYS,
        _PRE_TASK4_RUNTIME_STATE_KEYS,
        _TOKENIZED_CURRENT_RUNTIME_STATE_KEYS,
    )
    for state_fields in pre_tenant_layouts:
        if fields == set((*_PRE_TENANT_RUNTIME_KEYS, *state_fields)):
            migrated = dict(values)
            migrated["TENANT_AES_KEY"] = _new_aes_key(
                different_from=migrated["SYSTEM_AES_KEY"]
            )
            _write_runtime_environment(
                path,
                migrated,
                (*_RUNTIME_KEYS, *state_fields),
            )
            _validate_runtime_environment(path)
            values = migrated
            fields = set(migrated)
            break
    if fields == set((*_RUNTIME_KEYS, *_PRE_TASK4_RUNTIME_STATE_KEYS)):
        _scrub_pre_task4_runtime_state(path, values)
    elif fields == set(
        (*_RUNTIME_KEYS, *_TOKENIZED_CURRENT_RUNTIME_STATE_KEYS)
    ):
        _remove_legacy_runtime_api_key(path, values)


def _write_runtime_environment(
    path: Path,
    values: Mapping[str, str],
    fields: tuple[str, ...],
) -> None:
    payload = "".join(f"{name}={values[name]}\n" for name in fields)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def read_runtime_environment(path: Path) -> dict[str, str]:
    """Return a defensive copy for trusted local controllers only."""

    ensure_runtime_environment(path)
    return dict(_validate_runtime_environment(path))


def update_runtime_state(path: Path, state: Mapping[str, str]) -> None:
    """Atomically persist one complete provisioned identity graph."""

    if set(state) != set(_RUNTIME_STATE_KEYS) or any(
        not isinstance(value, str) or not value for value in state.values()
    ):
        raise RuntimeEnvironmentError("runtime state must be complete")
    if any(
        _ENDPOINT_FINGERPRINT.fullmatch(state[name]) is None
        for name in _ENDPOINT_FINGERPRINT_KEYS
    ):
        raise RuntimeEnvironmentError("runtime state has invalid endpoint fingerprint")
    values = read_runtime_environment(path)
    for name in _RUNTIME_STATE_KEYS:
        values[name] = state[name]
    _write_runtime_environment(
        path,
        values,
        (*_RUNTIME_KEYS, *_RUNTIME_STATE_KEYS),
    )
    _validate_runtime_environment(path)


def _remove_legacy_runtime_api_key(
    path: Path,
    legacy: Mapping[str, str],
) -> None:
    values = {
        name: value
        for name, value in legacy.items()
        if name != "LOCAL_LIVE_API_KEY"
    }
    _write_runtime_environment(
        path,
        values,
        (*_RUNTIME_KEYS, *_RUNTIME_STATE_KEYS),
    )
    _validate_runtime_environment(path)


def _scrub_pre_task4_runtime_state(
    path: Path,
    legacy: Mapping[str, str],
) -> None:
    _write_runtime_environment(path, legacy, _RUNTIME_KEYS)
    _validate_runtime_environment(path)


def verify_rendered_compose(
    rendered: Mapping[str, object],
    image_lock: Mapping[str, str],
) -> None:
    """Verify the rendered Compose configuration against its image lock."""
    services_value = rendered.get("services")
    if not isinstance(services_value, Mapping):
        raise ComposeVerificationError("rendered Compose services must be a mapping")
    services = cast(Mapping[str, object], services_value)

    for service_name, service_value in services.items():
        if not isinstance(service_value, Mapping):
            raise ComposeVerificationError(f"service {service_name!r} must be a mapping")
        service = cast(Mapping[str, object], service_value)

        network_mode = service.get("network_mode")
        if isinstance(network_mode, str) and network_mode.casefold() == "host":
            raise ComposeVerificationError(
                f"service {service_name!r} must not use host network mode"
            )

        _verify_published_ports(service_name, service.get("ports"))
        _verify_image(service_name, service.get("image"), image_lock)

        if service_name in _REQUIRED_HEALTHCHECK_SERVICES:
            _verify_healthcheck(service_name, service.get("healthcheck"))

        if service_name == "harness-postgres":
            _verify_harness_password(service.get("environment"))


def _verify_published_ports(service_name: str, ports_value: object) -> None:
    if ports_value is None:
        return
    if not isinstance(ports_value, list):
        raise ComposeVerificationError(f"service {service_name!r} ports must be a list")
    ports = cast(list[object], ports_value)
    if ports and service_name not in _ALLOWED_PUBLISHED_PORT_SERVICES:
        raise ComposeVerificationError(
            f"dependency service {service_name!r} must not publish host ports"
        )

    for port in ports:
        if isinstance(port, str):
            loopback_only = port.startswith("127.0.0.1:")
        elif isinstance(port, Mapping):
            port_mapping = cast(Mapping[str, object], port)
            loopback_only = port_mapping.get("host_ip") == "127.0.0.1"
        else:
            loopback_only = False
        if not loopback_only:
            raise ComposeVerificationError(
                f"service {service_name!r} published ports must bind loopback 127.0.0.1"
            )


def _verify_image(
    service_name: str,
    image_value: object,
    image_lock: Mapping[str, str],
) -> None:
    if image_value is None:
        return
    if not isinstance(image_value, str) or not image_value:
        raise ComposeVerificationError(f"service {service_name!r} image must be a string")

    tagged_reference = image_value.partition("@")[0]
    if tagged_reference.rsplit("/", 1)[-1].casefold().endswith(":latest"):
        raise ComposeVerificationError(f"service {service_name!r} uses latest image tag")
    if _IMAGE_DIGEST.search(image_value) is None:
        raise ComposeVerificationError(
            f"service {service_name!r} image must include a sha256 digest"
        )
    if image_lock.get(service_name) != image_value:
        raise ComposeVerificationError(
            f"service {service_name!r} does not match the image lock"
        )

def _verify_healthcheck(service_name: str, healthcheck_value: object) -> None:
    if not isinstance(healthcheck_value, Mapping):
        raise ComposeVerificationError(
            f"service {service_name!r} must define a healthcheck"
        )
    healthcheck = cast(Mapping[str, object], healthcheck_value)
    if healthcheck.get("disable") is True or not healthcheck.get("test"):
        raise ComposeVerificationError(
            f"service {service_name!r} must define an enabled healthcheck test"
        )


def _verify_harness_password(environment_value: object) -> None:
    password: object = None
    if isinstance(environment_value, Mapping):
        environment = cast(Mapping[str, object], environment_value)
        password = environment.get("POSTGRES_PASSWORD")
    elif isinstance(environment_value, list):
        for entry in cast(list[object], environment_value):
            if isinstance(entry, str) and entry.startswith("POSTGRES_PASSWORD="):
                password = entry.partition("=")[2]
                break

    if (
        not isinstance(password, str)
        or len(password) < 16
        or password.casefold() in _KNOWN_FIXED_PASSWORDS
    ):
        raise ComposeVerificationError(
            "harness-postgres password must be a non-example random local value"
        )
