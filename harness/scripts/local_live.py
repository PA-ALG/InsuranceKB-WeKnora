#!/usr/bin/env python3
"""Fail-closed local-live CLI skeleton with injected external adapters."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Callable, Coroutine, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, NamedTuple, Protocol, TextIO, cast

from insurance_harness.live_env.compose import ensure_runtime_environment
from insurance_harness.live_env.config import LocalLiveConfig, load_local_live_config
from insurance_harness.live_env.model_probe import probe_all_models

Phase = Literal[
    "check",
    "probe-models",
    "up",
    "provision",
    "verify",
    "run-local",
    "down",
]
PHASES: tuple[Phase, ...] = (
    "check",
    "probe-models",
    "up",
    "provision",
    "verify",
    "run-local",
    "down",
)
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCK_PATHS = (
    REPO_ROOT / "deploy/local-live/images.lock",
    REPO_ROOT / "deploy/local-live/runner/runner.lock",
)

_URL = re.compile(r"\b(?:https?|postgres(?:ql)?):\/\/[^\s\"']+", re.IGNORECASE)
_INLINE_SECRET = re.compile(
    r"\b(token|api[_ -]?key|password|secret|credential)(\s*[:=]?\s*)\S+",
    re.IGNORECASE,
)
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "base_url",
    "credential",
    "db_url",
    "password",
    "secret",
    "token",
    "url",
)


class PhaseRequest(NamedTuple):
    phase: Phase
    delete_volumes: bool


class PhaseAdapter(Protocol):
    """Injected mutation boundary; the CLI itself performs no external calls."""

    def run(self, request: PhaseRequest) -> object: ...


class LockVerifier(Protocol):
    def require_resolved(self) -> None: ...


class LockResolutionError(RuntimeError):
    """Sanitized fail-closed lock error."""


class LocalConfigurationError(RuntimeError):
    """Sanitized local configuration failure."""


class CollaboratorUnavailable(RuntimeError):
    """Requested external phase has no injected implementation."""


class LocalExecutionError(RuntimeError):
    """Sanitized collaborator failure."""


class LocalLivePaths(NamedTuple):
    config: Path
    runtime: Path


DEFAULT_LOCAL_PATHS = LocalLivePaths(
    config=REPO_ROOT / ".env.local-live",
    runtime=REPO_ROOT / ".env.local-live.runtime",
)

class PhaseCollaborator(Protocol):
    def run(self, request: PhaseRequest) -> object: ...


ConfigLoader = Callable[[Path], LocalLiveConfig]
RuntimeEnsurer = Callable[[Path], object]
ModelProbe = Callable[[LocalLiveConfig], Coroutine[Any, Any, object]]


class LocalLiveAdapter:
    """Safe orchestration boundary; collaborators are absent unless injected."""

    __slots__ = (
        "_config_loader",
        "_model_probe",
        "_paths",
        "_provision",
        "_runtime_ensurer",
        "_subprocess",
    )

    def __init__(
        self,
        paths: LocalLivePaths,
        *,
        config_loader: ConfigLoader | None = None,
        runtime_ensurer: RuntimeEnsurer | None = None,
        model_probe: ModelProbe | None = None,
        subprocess_collaborator: PhaseCollaborator | None = None,
        provision_collaborator: PhaseCollaborator | None = None,
    ) -> None:
        self._paths = paths
        self._config_loader = (
            load_local_live_config if config_loader is None else config_loader
        )
        self._runtime_ensurer = (
            ensure_runtime_environment if runtime_ensurer is None else runtime_ensurer
        )
        self._model_probe = probe_all_models if model_probe is None else model_probe
        self._subprocess = subprocess_collaborator
        self._provision = provision_collaborator

    def run(self, request: PhaseRequest) -> object:
        try:
            config = self._config_loader(self._paths.config)
        except Exception as error:
            raise LocalConfigurationError("model configuration is invalid") from error
        try:
            self._runtime_ensurer(self._paths.runtime)
        except Exception as error:
            raise LocalConfigurationError("runtime configuration is invalid") from error
        if request.phase == "check":
            return {"status": "ok", "config": "valid", "runtime": "valid"}
        if request.phase == "probe-models":
            try:
                return asyncio.run(self._model_probe(config))
            except Exception as error:
                raise LocalExecutionError("model probe failed") from error

        collaborator = (
            self._provision
            if request.phase in {"provision", "verify"}
            else self._subprocess
        )
        if collaborator is None:
            raise CollaboratorUnavailable(f"collaborator unavailable for {request.phase}")
        try:
            return collaborator.run(request)
        except Exception as error:
            raise LocalExecutionError(f"{request.phase} collaborator failed") from error


class FileLockVerifier:
    """Require every configured runtime lock to exist and contain no placeholders."""

    __slots__ = ("_paths",)

    def __init__(self, paths: Sequence[Path]) -> None:
        self._paths = tuple(paths)

    def require_resolved(self) -> None:
        if not self._paths:
            raise LockResolutionError("runtime locks are unresolved")
        for path in self._paths:
            try:
                content = path.read_text()
            except OSError as error:
                raise LockResolutionError("runtime locks are unresolved") from error
            if not content.strip() or "UNRESOLVED" in content:
                raise LockResolutionError("runtime locks are unresolved")


def _redact_text(value: str) -> str:
    redacted = _URL.sub("<redacted>", value)
    return _INLINE_SECRET.sub(lambda match: f"{match.group(1)} <redacted>", redacted)


def _sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _redact(value: object, *, key: str | None = None) -> object:
    if key is not None and _sensitive_key(key):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {
            _redact_text(str(item_key)): _redact(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "<redacted>"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operate the isolated local-live environment")
    parser.add_argument("phase", choices=PHASES)
    parser.add_argument("--delete-volumes", action="store_true")
    parser.add_argument("--confirm-delete-volumes", action="store_true")
    return parser


def main(
    arguments: Sequence[str] | None = None,
    *,
    adapter: PhaseAdapter | None = None,
    lock_verifier: LockVerifier | None = None,
    output: TextIO | None = None,
    error: TextIO | None = None,
) -> int:
    """Validate command safety, then dispatch exactly one phase through an adapter."""

    output_stream = sys.stdout if output is None else output
    error_stream = sys.stderr if error is None else error
    namespace = _parser().parse_args(arguments)
    phase = cast("Phase", namespace.phase)
    delete_volumes = bool(namespace.delete_volumes)
    confirmed = bool(namespace.confirm_delete_volumes)

    if (delete_volumes or confirmed) and phase != "down":
        print("local-live: volume options are valid only for down", file=error_stream)
        return 2
    if delete_volumes and not confirmed:
        print("local-live: explicit confirmation required to delete volumes", file=error_stream)
        return 2
    if confirmed and not delete_volumes:
        print("local-live: confirmation requires --delete-volumes", file=error_stream)
        return 2

    verifier = FileLockVerifier(DEFAULT_LOCK_PATHS) if lock_verifier is None else lock_verifier
    try:
        verifier.require_resolved()
    except LockResolutionError:
        print("local-live: runtime locks are unresolved", file=error_stream)
        return 2

    selected_adapter = LocalLiveAdapter(DEFAULT_LOCAL_PATHS) if adapter is None else adapter

    try:
        result = selected_adapter.run(
            PhaseRequest(phase=phase, delete_volumes=delete_volumes)
        )
    except (LocalConfigurationError, CollaboratorUnavailable) as configuration_error:
        print(f"local-live: {configuration_error}", file=error_stream)
        return 2
    except Exception as adapter_error:
        print(f"local-live: {_redact_text(str(adapter_error))}", file=error_stream)
        return 1

    print(json.dumps(_redact(result), ensure_ascii=False, sort_keys=True), file=output_stream)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
