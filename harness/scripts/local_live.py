#!/usr/bin/env python3
"""Fail-closed local-live CLI skeleton with injected external adapters."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from collections.abc import Callable, Coroutine, Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, NamedTuple, Protocol, TextIO, cast

from insurance_harness.live_env.compose import (
    ensure_runtime_environment,
    verify_harness_compose,
    verify_weknora_compose,
)
from insurance_harness.live_env.config import LocalLiveConfig, load_local_live_config
from insurance_harness.live_env.local_gate import LocalGateCollaborator
from insurance_harness.live_env.local_provisioning import (
    ProvisionCollaborator,
    RealProvisioningOperation,
    RuntimeAPIKeyResolver,
    VLMSmokeCollaborator,
)
from insurance_harness.live_env.model_probe import probe_all_models

Phase = Literal[
    "check",
    "probe-models",
    "up",
    "provision",
    "verify",
    "smoke-vlm",
    "retry-vlm",
    "run-local",
    "down",
]
PHASES: tuple[Phase, ...] = (
    "check",
    "probe-models",
    "up",
    "provision",
    "verify",
    "smoke-vlm",
    "retry-vlm",
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
    pdf_path: Path | None = None
    knowledge_id: str | None = None


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
ComposeVerifier = Callable[[Mapping[str, object], Mapping[str, str]], None]


class CommandRunner(Protocol):
    def __call__(
        self,
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        capture_output: bool,
    ) -> subprocess.CompletedProcess[str]: ...


def _run_command(
    arguments: tuple[str, ...],
    *,
    cwd: Path,
    capture_output: bool,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        cwd=cwd,
        check=False,
        capture_output=capture_output,
        text=True,
    )


class ComposeCollaborator:
    """Render/attest both Compose projects before starting their six services."""

    __slots__ = (
        "_harness_verifier",
        "_image_lock_path",
        "_repo_root",
        "_runner",
        "_runtime_path",
        "_weknora_verifier",
    )

    def __init__(
        self,
        *,
        repo_root: Path,
        runtime_path: Path,
        image_lock_path: Path,
        runner: CommandRunner | None = None,
        weknora_verifier: ComposeVerifier | None = None,
        harness_verifier: ComposeVerifier | None = None,
    ) -> None:
        self._repo_root = repo_root
        self._runtime_path = runtime_path
        self._image_lock_path = image_lock_path
        self._runner = _run_command if runner is None else runner
        self._weknora_verifier = (
            verify_weknora_compose
            if weknora_verifier is None
            else weknora_verifier
        )
        self._harness_verifier = (
            verify_harness_compose if harness_verifier is None else harness_verifier
        )

    def _compose(self, group: Literal["weknora", "harness"]) -> tuple[str, ...]:
        base = (
            "docker",
            "compose",
            "--env-file",
            str(self._runtime_path),
        )
        if group == "weknora":
            return (
                *base,
                "--project-name",
                "insurancekb-local-live",
                "-f",
                "docker-compose.yml",
                "-f",
                "deploy/local-live/docker-compose.weknora.override.yml",
            )
        return (
            *base,
            "--project-name",
            "insurancekb-harness-live",
            "-f",
            "docker-compose.harness.yml",
            "-f",
            "deploy/local-live/docker-compose.harness.override.yml",
        )

    def _command(
        self,
        arguments: tuple[str, ...],
        *,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        result = self._runner(
            arguments,
            cwd=self._repo_root,
            capture_output=capture_output,
        )
        if result.returncode != 0:
            raise RuntimeError("local Compose command failed")
        return result

    def _lock(self) -> dict[str, str]:
        document: object = json.loads(self._image_lock_path.read_text())
        if not isinstance(document, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in document.items()
        ):
            raise ValueError("image lock is invalid")
        return {
            str(key): str(value)
            for key, value in document.items()
            if key != "_status"
        }

    def _render(
        self,
        group: Literal["weknora", "harness"],
    ) -> Mapping[str, object]:
        result = self._command(
            (*self._compose(group), "config", "--format", "json"),
            capture_output=True,
        )
        document: object = json.loads(result.stdout)
        if not isinstance(document, dict):
            raise ValueError("rendered Compose configuration is invalid")
        return cast(Mapping[str, object], document)

    def _verify_before_up(self) -> None:
        lock = self._lock()
        self._weknora_verifier(self._render("weknora"), lock)
        self._harness_verifier(self._render("harness"), lock)

    def _verify_runtime_port(
        self,
        group: Literal["weknora", "harness"],
        service: str,
        target: int,
    ) -> None:
        result = self._command(
            (*self._compose(group), "port", service, str(target)),
            capture_output=True,
        )
        addresses = tuple(line.strip() for line in result.stdout.splitlines() if line.strip())
        if not addresses or any(
            not address.startswith("127.0.0.1:") for address in addresses
        ):
            raise RuntimeError("local Compose port is not loopback-only")

    def run(self, request: PhaseRequest) -> object:
        if request.phase == "up":
            self._verify_before_up()
            self._command(
                (
                    *self._compose("weknora"),
                    "up",
                    "-d",
                    "--wait",
                    "--wait-timeout",
                    "180",
                    "app",
                    "frontend",
                    "postgres",
                    "redis",
                    "docreader",
                )
            )
            self._command(
                (
                    *self._compose("harness"),
                    "up",
                    "-d",
                    "--wait",
                    "--wait-timeout",
                    "180",
                    "harness-postgres",
                )
            )
            self._verify_runtime_port("weknora", "app", 8080)
            self._verify_runtime_port("weknora", "frontend", 80)
            self._verify_runtime_port("harness", "harness-postgres", 5432)
            return {"status": "started", "services": 6}
        if request.phase == "down":
            suffix = ("--volumes",) if request.delete_volumes else ()
            failures = 0
            for group in ("weknora", "harness"):
                try:
                    self._command(
                        (*self._compose(group), "down", "--remove-orphans", *suffix)
                    )
                except RuntimeError:
                    failures += 1
            if failures:
                raise RuntimeError("local Compose cleanup failed")
            return {"status": "stopped", "volumes_deleted": request.delete_volumes}
        raise ValueError("unsupported Compose phase")


class LocalLiveAdapter:
    """Safe orchestration boundary; collaborators are absent unless injected."""

    __slots__ = (
        "_config_loader",
        "_default_collaborators",
        "_model_probe",
        "_paths",
        "_provision",
        "_runtime_ensurer",
        "_subprocess",
        "_vlm",
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
        vlm_collaborator: PhaseCollaborator | None = None,
        default_collaborators: bool = False,
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
        self._vlm = vlm_collaborator
        self._default_collaborators = default_collaborators

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

        if request.phase in {"provision", "verify"}:
            collaborator = self._provision
        elif request.phase in {"smoke-vlm", "retry-vlm"}:
            collaborator = self._vlm
        else:
            collaborator = self._subprocess
        if collaborator is None and self._default_collaborators:
            if request.phase in {"provision", "verify"}:
                collaborator = cast(
                    PhaseCollaborator,
                    ProvisionCollaborator(
                        config=config,
                        runtime_path=self._paths.runtime,
                        operation=RealProvisioningOperation(
                            repo_root=self._paths.config.parent,
                        ),
                    ),
                )
            elif request.phase in {"smoke-vlm", "retry-vlm"}:
                collaborator = cast(
                    PhaseCollaborator,
                    VLMSmokeCollaborator(runtime_path=self._paths.runtime),
                )
            elif request.phase == "run-local":
                collaborator = cast(
                    PhaseCollaborator,
                    LocalGateCollaborator(
                        harness_root=self._paths.config.parent / "harness",
                        runtime_path=self._paths.runtime,
                        api_key_resolver=RuntimeAPIKeyResolver(
                            runtime_path=self._paths.runtime,
                        ),
                    ),
                )
            else:
                collaborator = ComposeCollaborator(
                    repo_root=self._paths.config.parent,
                    runtime_path=self._paths.runtime,
                    image_lock_path=(
                        self._paths.config.parent / "deploy/local-live/images.lock"
                    ),
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


def _git_output(repo_root: Path, arguments: tuple[str, ...]) -> str:
    result = subprocess.run(
        arguments,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("implementation identity is unavailable")
    return result.stdout


def _implementation_evidence(repo_root: Path) -> dict[str, object]:
    head = _git_output(repo_root, ("git", "rev-parse", "HEAD")).strip()
    status = _git_output(
        repo_root,
        ("git", "status", "--porcelain=v1", "--untracked-files=all"),
    )
    if not status:
        return {
            "implementation_sha": head,
            "dirty": False,
            "evidence": "exact",
        }
    digest = sha256()
    tracked = _git_output(repo_root, ("git", "diff", "--binary", "HEAD", "--"))
    digest.update(b"tracked\0")
    digest.update(tracked.encode("utf-8"))
    untracked = _git_output(
        repo_root,
        ("git", "ls-files", "--others", "--exclude-standard", "-z"),
    )
    resolved_root = repo_root.resolve()
    for relative in sorted(name for name in untracked.split("\0") if name):
        path = (repo_root / relative).resolve()
        if not path.is_relative_to(resolved_root) or not path.is_file():
            raise RuntimeError("implementation identity is unavailable")
        content = path.read_bytes()
        digest.update(b"untracked\0")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return {
        "head": head,
        "dirty": True,
        "diff_digest": digest.hexdigest(),
        "evidence": "provisional",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operate the isolated local-live environment")
    parser.add_argument("phase", choices=PHASES)
    parser.add_argument("--delete-volumes", action="store_true")
    parser.add_argument("--confirm-delete-volumes", action="store_true")
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--knowledge-id")
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
    pdf_path = cast(Path | None, namespace.pdf)
    knowledge_id = cast(str | None, namespace.knowledge_id)

    if (delete_volumes or confirmed) and phase != "down":
        print("local-live: volume options are valid only for down", file=error_stream)
        return 2
    if delete_volumes and not confirmed:
        print("local-live: explicit confirmation required to delete volumes", file=error_stream)
        return 2
    if confirmed and not delete_volumes:
        print("local-live: confirmation requires --delete-volumes", file=error_stream)
        return 2
    if pdf_path is not None and phase != "provision":
        print("local-live: --pdf is valid only for provision", file=error_stream)
        return 2
    if knowledge_id is not None and phase != "retry-vlm":
        print("local-live: --knowledge-id is valid only for retry-vlm", file=error_stream)
        return 2
    if phase == "retry-vlm" and not knowledge_id:
        print("local-live: --knowledge-id is required for retry-vlm", file=error_stream)
        return 2

    verifier = FileLockVerifier(DEFAULT_LOCK_PATHS) if lock_verifier is None else lock_verifier
    try:
        verifier.require_resolved()
    except LockResolutionError:
        print("local-live: runtime locks are unresolved", file=error_stream)
        return 2

    selected_adapter = (
        LocalLiveAdapter(DEFAULT_LOCAL_PATHS, default_collaborators=True)
        if adapter is None
        else adapter
    )

    try:
        result = selected_adapter.run(
            PhaseRequest(
                phase=phase,
                delete_volumes=delete_volumes,
                pdf_path=pdf_path,
                knowledge_id=knowledge_id,
            )
        )
    except (LocalConfigurationError, CollaboratorUnavailable) as configuration_error:
        print(f"local-live: {configuration_error}", file=error_stream)
        return 2
    except Exception as adapter_error:
        print(f"local-live: {_redact_text(str(adapter_error))}", file=error_stream)
        return 1

    if phase in {"smoke-vlm", "retry-vlm"}:
        if not isinstance(result, Mapping):
            print("local-live: VLM result is invalid", file=error_stream)
            return 1
        try:
            result = {**result, **_implementation_evidence(REPO_ROOT)}
        except Exception:
            print("local-live: implementation identity is unavailable", file=error_stream)
            return 1
    print(json.dumps(_redact(result), ensure_ascii=False, sort_keys=True), file=output_stream)
    if phase in {"smoke-vlm", "retry-vlm"} and result.get("status") != "completed":
        print("local-live: VLM operation did not complete", file=error_stream)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
