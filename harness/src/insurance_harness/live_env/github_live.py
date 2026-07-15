"""Typed, side-effect-free plans for an isolated local-live GitHub runner."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal, NamedTuple, Protocol, cast

_NONCE = re.compile(r"[0-9a-f]{16}")
_SHA = re.compile(r"[0-9a-f]{40}")
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
_CHECKSUM = re.compile(r"[0-9a-f]{64}")

LIVE_SECRET_NAMES = (
    "HARNESS_LIVE_API_KEY",
    "HARNESS_LIVE_DB_URL",
)
LIVE_VARIABLE_NAMES = (
    "HARNESS_LIVE_BASE_URL",
    "HARNESS_LIVE_SPACE_ID",
    "HARNESS_LIVE_KNOWLEDGE_ID",
    "HARNESS_LIVE_PARSER_FINGERPRINT",
    "HARNESS_LIVE_KB_ID",
)
LIVE_VALUE_NAMES = frozenset((*LIVE_SECRET_NAMES, *LIVE_VARIABLE_NAMES))
RUNNER_NETWORKS = ("local-live-weknora", "local-live-harness-db")
RunnerArchitecture = Literal["arm64", "x64", "UNRESOLVED"]


class RunnerIdentity(NamedTuple):
    """Unique runner name and routing label derived only from a run nonce."""

    name: str
    label: str

    @classmethod
    def from_nonce(cls, nonce: str) -> RunnerIdentity:
        if _NONCE.fullmatch(nonce) is None:
            raise ValueError("runner nonce must be 16 lowercase hexadecimal characters")
        identity = f"insurancekb-live-{nonce}"
        return cls(name=identity, label=identity)


class RunnerPackageLock(NamedTuple):
    """Attested official runner archive coordinates."""

    version: str
    arch: RunnerArchitecture
    archive: str
    sha256: str

    @classmethod
    def load(cls, path: Path) -> RunnerPackageLock:
        values: dict[str, str] = {}
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator or key in values:
                raise ValueError("runner lock is malformed")
            values[key] = value
        if set(values) != {"version", "arch", "archive", "sha256"}:
            raise ValueError("runner lock is malformed")
        arch = values["arch"]
        if arch not in {"arm64", "x64", "UNRESOLVED"}:
            raise ValueError("runner package lock is invalid")
        return cls(
            version=values["version"],
            arch=cast("RunnerArchitecture", arch),
            archive=values["archive"],
            sha256=values["sha256"],
        )

    def require_verified(self) -> None:
        if "UNRESOLVED" in self:
            raise ValueError("runner package lock is unresolved")
        expected_archive = (
            f"actions-runner-linux-{self.arch}-{self.version}.tar.gz"
        )
        if (
            _VERSION.fullmatch(self.version) is None
            or self.arch not in {"arm64", "x64"}
            or self.archive != expected_archive
            or _CHECKSUM.fullmatch(self.sha256) is None
        ):
            raise ValueError("runner package lock is invalid")

    @property
    def download_url(self) -> str:
        self.require_verified()
        return (
            "https://github.com/actions/runner/releases/download/"
            f"v{self.version}/{self.archive}"
        )


class RedactedLiveValues:
    """Secret-bearing live values with explicit adapter-only disclosure."""

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)

    def reveal(self) -> dict[str, str]:
        """Return a defensive plaintext copy for the external injection adapter."""

        return dict(self._values)

    def __repr__(self) -> str:
        return "RedactedLiveValues(<redacted>)"

    __str__ = __repr__


class RunnerPlan(NamedTuple):
    """Validated resource shape; an adapter may render it without widening access."""

    identity: RunnerIdentity
    package: RunnerPackageLock
    mounts: tuple[()]
    published_ports: tuple[()]
    attached_networks: tuple[str, str]
    outbound_https: bool
    max_jobs: Literal[1]
    live_values: RedactedLiveValues


def build_runner_plan(
    *,
    nonce: str,
    live_values: Mapping[str, str],
    lock: RunnerPackageLock,
) -> RunnerPlan:
    """Validate all isolation inputs before an external adapter may act."""

    lock.require_verified()
    if set(live_values) != LIVE_VALUE_NAMES or any(not value for value in live_values.values()):
        raise ValueError("runner requires exactly seven non-empty live values")
    return RunnerPlan(
        identity=RunnerIdentity.from_nonce(nonce),
        package=lock,
        mounts=(),
        published_ports=(),
        attached_networks=RUNNER_NETWORKS,
        outbound_https=True,
        max_jobs=1,
        live_values=RedactedLiveValues(live_values),
    )


class PullRequest(NamedTuple):
    number: int
    state: str
    base_repository: str
    head_repository: str
    head_sha: str


class PullRequestGateway(Protocol):
    """Injected read-only GitHub boundary."""

    def get_pull(self, repository: str, number: int) -> PullRequest: ...


def approve_pull_request(
    gateway: PullRequestGateway,
    *,
    repository: str,
    pr_number: int,
    head_sha: str,
) -> PullRequest:
    """Fail closed unless approval targets an open same-repository exact SHA."""

    pull = gateway.get_pull(repository, pr_number)
    if (
        _SHA.fullmatch(head_sha) is None
        or pull.number != pr_number
        or pull.state != "open"
        or pull.base_repository != repository
        or pull.head_repository != repository
        or pull.head_sha != head_sha
    ):
        raise ValueError("PR is not an open same-repository exact-SHA request")
    return pull


class EphemeralResources(NamedTuple):
    """Opaque identifiers only; credentials are deliberately not retained here."""

    tenant_key: str
    db_role: str
    runner_registration: str
    container: str
    volume: str
    workspace: str
    logs: str

    @classmethod
    def for_nonce(cls, nonce: str) -> EphemeralResources:
        identity = RunnerIdentity.from_nonce(nonce).name
        return cls(
            tenant_key=f"{identity}-tenant-key",
            db_role=identity.replace("-", "_"),
            runner_registration=identity,
            container=identity,
            volume=f"{identity}-work",
            workspace=f"{identity}-workspace",
            logs=f"{identity}-logs",
        )


CleanupKind = Literal[
    "delete_secret",
    "delete_variable",
    "revoke_tenant_key",
    "drop_db_role",
    "remove_runner_registration",
    "remove_container",
    "remove_volume",
    "remove_workspace",
    "remove_logs",
]


class CleanupAction(NamedTuple):
    kind: CleanupKind
    resource: str


def cleanup_plan(resources: EphemeralResources) -> tuple[CleanupAction, ...]:
    """Return the complete unconditional cleanup stack in stable order."""

    actions = [CleanupAction("delete_secret", name) for name in LIVE_SECRET_NAMES]
    actions.extend(CleanupAction("delete_variable", name) for name in LIVE_VARIABLE_NAMES)
    actions.extend(
        (
            CleanupAction("revoke_tenant_key", resources.tenant_key),
            CleanupAction("drop_db_role", resources.db_role),
            CleanupAction("remove_runner_registration", resources.runner_registration),
            CleanupAction("remove_container", resources.container),
            CleanupAction("remove_volume", resources.volume),
            CleanupAction("remove_workspace", resources.workspace),
            CleanupAction("remove_logs", resources.logs),
        )
    )
    return tuple(actions)


class CleanupExecutor(Protocol):
    """Injected mutation boundary; tests use fakes and this module calls no systems."""

    def execute(self, action: CleanupAction) -> None: ...


class CleanupFailure(RuntimeError):
    """Sanitized aggregate raised only when no primary failure exists."""

    def __init__(self, kinds: tuple[CleanupKind, ...]) -> None:
        self.kinds = kinds
        super().__init__(f"cleanup failures: {', '.join(kinds)}")


def _attempt_cleanup(
    executor: CleanupExecutor,
    resources: EphemeralResources,
) -> tuple[CleanupKind, ...]:
    failures: list[CleanupKind] = []
    for action in cleanup_plan(resources):
        try:
            executor.execute(action)
        except BaseException:
            failures.append(action.kind)
    return tuple(failures)


def execute_with_cleanup[Result](
    operation: Callable[[], Result],
    executor: CleanupExecutor,
    resources: EphemeralResources,
) -> Result:
    """Attempt every cleanup on success, failure, or cancellation."""

    try:
        result = operation()
    except BaseException as primary:
        failures = _attempt_cleanup(executor, resources)
        if failures:
            primary.add_note(f"cleanup failures: {', '.join(failures)}")
        raise
    failures = _attempt_cleanup(executor, resources)
    if failures:
        raise CleanupFailure(failures)
    return result
