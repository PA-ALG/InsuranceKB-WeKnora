"""Shared lifecycle plus dependency-free liveness and truthful readiness."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from enum import StrEnum
from importlib.resources import as_file, files
from pathlib import Path
from threading import Event, Lock
from time import monotonic as system_monotonic

from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session


class ProcessState(StrEnum):
    STARTING = "starting"
    SERVING = "serving"
    DRAINING = "draining"
    TERMINATED = "terminated"
    REFUSED = "refused"


class Lifecycle:
    """Thread-safe process state shared by HTTP and worker execution."""

    def __init__(self) -> None:
        self._state = ProcessState.STARTING
        self._lock = Lock()
        self._immediate_termination = Event()
        self._drain_listeners: set[Callable[[], None]] = set()
        self._immediate_listeners: set[Callable[[], None]] = set()

    @property
    def state(self) -> ProcessState:
        with self._lock:
            return self._state

    @property
    def immediate_termination_requested(self) -> bool:
        return self._immediate_termination.is_set()

    def mark_serving(self) -> None:
        with self._lock:
            if self._state is not ProcessState.STARTING:
                raise RuntimeError(f"cannot serve from {self._state.value}")
            self._state = ProcessState.SERVING

    def begin_drain(self) -> bool:
        """First signal starts drain; a repeated signal requests immediate termination."""
        drain_listeners: tuple[Callable[[], None], ...] = ()
        immediate_listeners: tuple[Callable[[], None], ...] = ()
        drain_started = False
        with self._lock:
            if self._state in (ProcessState.STARTING, ProcessState.SERVING):
                self._state = ProcessState.DRAINING
                drain_started = True
                drain_listeners = tuple(self._drain_listeners)
            elif (
                self._state is ProcessState.DRAINING
                and not self._immediate_termination.is_set()
            ):
                self._immediate_termination.set()
                immediate_listeners = tuple(self._immediate_listeners)
        for listener in drain_listeners:
            listener()
        for listener in immediate_listeners:
            listener()
        return drain_started

    def subscribe_drain(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Wake process composition as soon as the first drain signal is observed."""
        notify_now = False
        with self._lock:
            if self._state is ProcessState.DRAINING:
                notify_now = True
            else:
                self._drain_listeners.add(listener)
        if notify_now:
            listener()

        def unsubscribe() -> None:
            with self._lock:
                self._drain_listeners.discard(listener)

        return unsubscribe

    def subscribe_immediate_termination(
        self,
        listener: Callable[[], None],
    ) -> Callable[[], None]:
        """Wake an active drain when a repeated signal requests immediate exit."""
        notify_now = False
        with self._lock:
            if self._immediate_termination.is_set():
                notify_now = True
            else:
                self._immediate_listeners.add(listener)
        if notify_now:
            listener()

        def unsubscribe() -> None:
            with self._lock:
                self._immediate_listeners.discard(listener)

        return unsubscribe

    def mark_terminated(self) -> None:
        with self._lock:
            self._state = ProcessState.TERMINATED

    def mark_refused(self) -> None:
        with self._lock:
            self._state = ProcessState.REFUSED


class HealthResult(BaseModel):
    """Secret-free probe payload."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    status: str
    reason: str | None = None


class MigrationHeadMismatch(Exception):
    """Database and wheel revision sets are not one exact equal head."""

    code = "migration_head_mismatch"


def liveness(lifecycle: Lifecycle) -> HealthResult:
    """Answer only whether this process loop is alive; never touch a dependency."""
    alive = lifecycle.state not in (ProcessState.TERMINATED, ProcessState.REFUSED)
    return HealthResult(
        ok=alive,
        status="live" if alive else "terminated",
        reason=None if alive else "process_terminated",
    )


def evaluate_revision_heads(
    *, current_heads: tuple[str, ...], expected_head: str
) -> None:
    """Require one database head that exactly equals the packaged wheel head."""
    if current_heads != (expected_head,):
        raise MigrationHeadMismatch()


def _alembic_head_from_root(migration_root: Path) -> str:
    config = Config(str(migration_root / "alembic.ini"))
    config.set_main_option("script_location", str(migration_root / "migrations"))
    script = ScriptDirectory.from_config(config)
    heads = tuple(script.get_heads())
    if len(heads) != 1:
        raise MigrationHeadMismatch()
    return heads[0]


def packaged_alembic_head() -> str:
    """Read the expected revision from wheel-owned Alembic metadata, never a constant."""
    packaged_migrations = files("insurance_harness").joinpath("_migration")
    if packaged_migrations.is_dir():
        with as_file(packaged_migrations) as migration_root:
            return _alembic_head_from_root(migration_root)
    # Editable source check: still anchor to this module, never the caller's CWD.
    return _alembic_head_from_root(Path(__file__).resolve().parents[3])


def database_readiness_probe(
    session_factory: Callable[[], Session],
    *,
    expected_head: str | None = None,
) -> Callable[[], None]:
    """Build the real read-only PostgreSQL connectivity + migration probe."""
    wheel_head = packaged_alembic_head() if expected_head is None else expected_head

    def probe() -> None:
        with session_factory() as session:
            session.execute(text("SELECT 1")).scalar_one()
            current = tuple(
                str(value)
                for value in session.execute(
                    text("SELECT version_num FROM alembic_version ORDER BY version_num")
                ).scalars()
            )
        evaluate_revision_heads(current_heads=current, expected_head=wheel_head)

    return probe


class ReadinessChecker:
    """Bounded real checks with success-only freshness caching and fail-closed states."""

    def __init__(
        self,
        *,
        lifecycle: Lifecycle,
        probe: Callable[[], None],
        timeout_seconds: float,
        freshness_seconds: float,
        monotonic: Callable[[], float] = system_monotonic,
    ) -> None:
        self._lifecycle = lifecycle
        self._probe = probe
        self._timeout_seconds = timeout_seconds
        self._freshness_seconds = freshness_seconds
        self._monotonic = monotonic
        self._last_success_at: float | None = None
        self._lock = Lock()

    def _state_result(self) -> HealthResult | None:
        state = self._lifecycle.state
        if state is ProcessState.STARTING:
            return HealthResult(ok=False, status="not_ready", reason="starting")
        if state is ProcessState.DRAINING:
            return HealthResult(ok=False, status="not_ready", reason="draining")
        if state is not ProcessState.SERVING:
            return HealthResult(ok=False, status="not_ready", reason="process_not_serving")
        return None

    def current(self) -> HealthResult:
        """Return cached state without starting an external check."""
        state_result = self._state_result()
        if state_result is not None:
            return state_result
        if self._last_success_at is None:
            return HealthResult(
                ok=False,
                status="not_ready",
                reason="readiness_not_checked",
            )
        if self._monotonic() - self._last_success_at > self._freshness_seconds:
            return HealthResult(ok=False, status="not_ready", reason="readiness_stale")
        return HealthResult(ok=True, status="ready")

    def check(self) -> HealthResult:
        """Run a real bounded check when no fresh successful result exists."""
        state_result = self._state_result()
        if state_result is not None:
            return state_result
        current = self.current()
        if current.ok:
            return current
        with self._lock:
            state_result = self._state_result()
            if state_result is not None:
                return state_result
            current = self.current()
            if current.ok:
                return current
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wiki-readiness")
            future = executor.submit(self._probe)
            try:
                future.result(timeout=self._timeout_seconds)
            except FutureTimeoutError:
                future.cancel()
                return HealthResult(
                    ok=False,
                    status="not_ready",
                    reason="readiness_check_timeout",
                )
            except MigrationHeadMismatch:
                return HealthResult(
                    ok=False,
                    status="not_ready",
                    reason="migration_head_mismatch",
                )
            except Exception:
                return HealthResult(
                    ok=False,
                    status="not_ready",
                    reason="database_unavailable",
                )
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
            self._last_success_at = self._monotonic()
            return HealthResult(ok=True, status="ready")
