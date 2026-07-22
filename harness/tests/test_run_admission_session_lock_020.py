"""OpenSpec 020 D1.5: production run-session lock contract (TDD RED)."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import stat
from collections.abc import Awaitable, Callable
from multiprocessing import get_context
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from threading import Event
from types import ModuleType
from typing import Protocol, Self, cast

import pytest

_RUN_020_MODULE = "insurance_harness.goldenset.run_020"
_ACCOUNT_A = "a" * 64
_ACCOUNT_B = "b" * 64
_SECRET_CANARY = "HOST-PATH-SECRET-CANARY"


class _SessionLock(Protocol):
    @property
    def lock_path(self) -> Path: ...

    def __enter__(self) -> Self: ...

    def __exit__(self, *_exc: object) -> None: ...


class _SessionLockFactory(Protocol):
    def _for_testing(self, *, lock_root: Path, account_id: str) -> _SessionLock: ...


class _LockedSessionRunner(Protocol):
    def __call__(
        self,
        *,
        session_lock: _SessionLock,
        recovery: Callable[[], None],
        begin: Callable[[], None],
        construct_client: Callable[[], None],
        model_io: Callable[[], Awaitable[None]],
        artifact: Callable[[], None],
        settle: Callable[[], None],
    ) -> Awaitable[None]: ...


def _run_020() -> ModuleType:
    try:
        return importlib.import_module(_RUN_020_MODULE)
    except ModuleNotFoundError:
        pytest.fail(
            "D1.5 RED: production run_020 module with RunSessionLock is missing",
            pytrace=False,
        )


def _lock_factory() -> _SessionLockFactory:
    module = _run_020()
    factory = getattr(module, "RunSessionLock", None)
    if factory is None:
        pytest.fail("D1.5 RED: RunSessionLock is missing", pytrace=False)
    return cast(_SessionLockFactory, factory)


def _locked_runner() -> _LockedSessionRunner:
    module = _run_020()
    runner = getattr(module, "_run_locked_session_for_testing", None)
    if runner is None:
        pytest.fail(
            "D1.5 RED: locked lifecycle test seam is missing",
            pytrace=False,
        )
    return cast(_LockedSessionRunner, runner)


def _error_type(name: str) -> type[Exception]:
    value = getattr(_run_020(), name, None)
    if not isinstance(value, type) or not issubclass(value, Exception):
        pytest.fail(f"D1.5 RED: {name} is missing", pytrace=False)
    return value


def _exception_chain_text(error: BaseException) -> str:
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    rendered: list[str] = []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        rendered.extend((str(current), repr(current)))
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return "\n".join(rendered)


def _secure_lock_root(tmp_path: Path) -> Path:
    root = tmp_path / "run-session-locks"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root


def _lock(root: Path, account_id: str = _ACCOUNT_A) -> _SessionLock:
    return _lock_factory()._for_testing(lock_root=root, account_id=account_id)


def _worker_lock(root: str, account_id: str) -> _SessionLock:
    module = importlib.import_module(_RUN_020_MODULE)
    factory = cast(_SessionLockFactory, module.RunSessionLock)
    return factory._for_testing(lock_root=Path(root), account_id=account_id)


def _try_lock_worker(root: str, account_id: str, connection: Connection) -> None:
    try:
        module = importlib.import_module(_RUN_020_MODULE)
        unavailable = cast(
            type[Exception], module.RunSessionLockUnavailableError
        )
        try:
            with _worker_lock(root, account_id):
                connection.send("acquired")
        except unavailable:
            connection.send("blocked")
    except Exception as exc:
        connection.send(f"error:{type(exc).__name__}")
    finally:
        connection.close()


def _hold_lock_worker(root: str, account_id: str, connection: Connection) -> None:
    try:
        with _worker_lock(root, account_id):
            connection.send("acquired")
            # This timeout covers parent/child scheduling and macOS ``spawn``
            # imports, not the lock acquisition contract itself.
            if not connection.poll(60):
                raise TimeoutError("parent did not release test holder")
            connection.recv()
    except Exception as exc:
        connection.send(f"error:{type(exc).__name__}")
    finally:
        connection.close()


def _join_or_terminate(process: BaseProcess) -> None:
    # macOS ``spawn`` occasionally needs more than three seconds under the full
    # suite even though the child has already reached the fail-fast lock branch.
    process.join(timeout=10)
    if process.is_alive():
        process.terminate()
        process.join(timeout=10)


def _probe_lock_once(root: Path, account_id: str) -> str:
    context = get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_try_lock_worker,
        args=(os.fspath(root), account_id, child),
    )
    process.start()
    child.close()
    try:
        # The child performs a nonblocking flock once it starts.  Allow slow
        # spawned-interpreter imports without conflating them with lock wait.
        if not parent.poll(30):
            pytest.fail("D1.5 session-lock attempt blocked instead of failing fast")
        return cast(str, parent.recv())
    finally:
        parent.close()
        _join_or_terminate(process)


def _start_holder(root: Path, account_id: str) -> tuple[BaseProcess, Connection]:
    context = get_context("spawn")
    parent, child = context.Pipe(duplex=True)
    process = context.Process(
        target=_hold_lock_worker,
        args=(os.fspath(root), account_id, child),
    )
    process.start()
    child.close()
    if not parent.poll(30):
        _join_or_terminate(process)
        pytest.fail("D1.5 session-lock holder did not acquire promptly")
    assert parent.recv() == "acquired"
    return process, parent


def _release_holder(process: BaseProcess, connection: Connection) -> None:
    if process.is_alive():
        connection.send("release")
    connection.close()
    _join_or_terminate(process)


def test_d1_5_same_account_lock_is_cross_process_and_nonblocking(tmp_path: Path) -> None:
    root = _secure_lock_root(tmp_path)
    holder, control = _start_holder(root, _ACCOUNT_A)
    try:
        assert _probe_lock_once(root, _ACCOUNT_A) == "blocked"
    finally:
        _release_holder(holder, control)


@pytest.mark.asyncio
async def test_d1_5_competitor_fails_before_recovery_or_ledger_mutation(
    tmp_path: Path,
) -> None:
    root = _secure_lock_root(tmp_path)
    holder, control = _start_holder(root, _ACCOUNT_A)
    calls: list[str] = []

    def called(name: str) -> Callable[[], None]:
        return lambda: calls.append(name)

    async def model_io() -> None:
        calls.append("model")

    try:
        with pytest.raises(_error_type("RunSessionLockUnavailableError")):
            await _locked_runner()(
                session_lock=_lock(root),
                recovery=called("recovery"),
                begin=called("begin-ledger-mutation"),
                construct_client=called("client"),
                model_io=model_io,
                artifact=called("artifact"),
                settle=called("settle-ledger-mutation"),
            )
    finally:
        _release_holder(holder, control)

    assert calls == []


@pytest.mark.asyncio
async def test_d1_5_lock_covers_recovery_through_settlement(tmp_path: Path) -> None:
    root = _secure_lock_root(tmp_path)
    events: list[str] = []

    def phase(name: str) -> Callable[[], None]:
        def run() -> None:
            events.append(name)
            assert _probe_lock_once(root, _ACCOUNT_A) == "blocked"

        return run

    async def model_io() -> None:
        events.append("model")
        assert _probe_lock_once(root, _ACCOUNT_A) == "blocked"

    await _locked_runner()(
        session_lock=_lock(root),
        recovery=phase("recovery"),
        begin=phase("begin"),
        construct_client=phase("client"),
        model_io=model_io,
        artifact=phase("artifact"),
        settle=phase("settle"),
    )

    assert events == ["recovery", "begin", "client", "model", "artifact", "settle"]
    assert _probe_lock_once(root, _ACCOUNT_A) == "acquired"


@pytest.mark.asyncio
async def test_d1_5_lock_releases_after_error(tmp_path: Path) -> None:
    root = _secure_lock_root(tmp_path)

    def fail_artifact() -> None:
        raise RuntimeError("controlled artifact failure")

    async def model_io() -> None:
        return None

    with pytest.raises(RuntimeError, match="controlled artifact failure"):
        await _locked_runner()(
            session_lock=_lock(root),
            recovery=lambda: None,
            begin=lambda: None,
            construct_client=lambda: None,
            model_io=model_io,
            artifact=fail_artifact,
            settle=lambda: None,
        )

    assert _probe_lock_once(root, _ACCOUNT_A) == "acquired"


@pytest.mark.asyncio
async def test_d1_5_lock_releases_after_cancellation(tmp_path: Path) -> None:
    root = _secure_lock_root(tmp_path)
    entered_model = asyncio.Event()

    async def model_io() -> None:
        entered_model.set()
        await asyncio.Event().wait()

    task: asyncio.Future[None] = asyncio.ensure_future(
        _locked_runner()(
            session_lock=_lock(root),
            recovery=lambda: None,
            begin=lambda: None,
            construct_client=lambda: None,
            model_io=model_io,
            artifact=lambda: None,
            settle=lambda: None,
        )
    )
    await asyncio.wait_for(entered_model.wait(), timeout=2)
    assert _probe_lock_once(root, _ACCOUNT_A) == "blocked"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert _probe_lock_once(root, _ACCOUNT_A) == "acquired"


@pytest.mark.parametrize("unsafe_kind", ["symlink", "directory", "wide-mode"])
def test_d1_5_unsafe_lock_file_is_rejected(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    root = _secure_lock_root(tmp_path)
    session_lock = _lock(root)
    path = session_lock.lock_path
    if unsafe_kind == "symlink":
        victim = tmp_path / "victim"
        victim.write_text("must remain untouched", encoding="utf-8")
        path.symlink_to(victim)
    elif unsafe_kind == "directory":
        path.mkdir()
    else:
        path.touch(mode=0o600)
        path.chmod(0o666)

    with pytest.raises(_error_type("RunSessionLockSecurityError")):
        with session_lock:
            pytest.fail("unsafe session lock was acquired")


def test_d1_5_lock_file_is_persistent_regular_and_private(tmp_path: Path) -> None:
    root = _secure_lock_root(tmp_path)
    session_lock = _lock(root)
    with session_lock:
        path = session_lock.lock_path
        first_inode = path.stat().st_ino

    metadata = path.lstat()
    assert stat.S_ISREG(metadata.st_mode)
    assert stat.S_IMODE(metadata.st_mode) == 0o600
    with _lock(root):
        assert path.stat().st_ino == first_inode
    assert path.exists(), "lock files must never be unlinked on release"


def test_d1_5_different_accounts_can_hold_session_locks_concurrently(
    tmp_path: Path,
) -> None:
    root = _secure_lock_root(tmp_path)
    first, first_control = _start_holder(root, _ACCOUNT_A)
    try:
        second, second_control = _start_holder(root, _ACCOUNT_B)
        try:
            assert first.is_alive()
            assert second.is_alive()
        finally:
            _release_holder(second, second_control)
    finally:
        _release_holder(first, first_control)


def test_d1_5_session_lock_does_not_reuse_compiler_product_lock() -> None:
    source = inspect.getsource(_run_020())
    assert "_exclusive_run_directory" not in source


def test_d1_5_session_lock_security_error_hides_host_path_chain(tmp_path: Path) -> None:
    root = tmp_path / _SECRET_CANARY / "missing-lock-root"

    with pytest.raises(_error_type("RunSessionLockSecurityError")) as caught:
        with _lock(root):
            pytest.fail("missing root must not be acquired")

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert _SECRET_CANARY not in _exception_chain_text(caught.value)


def test_d1_5_openat_walk_resists_evented_ancestor_symlink_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _run_020()
    parent = tmp_path / "trusted-parent"
    root = parent / "locks"
    root.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    held_parent = tmp_path / "held-parent"
    attacker = tmp_path / "attacker"
    (attacker / "locks").mkdir(parents=True, mode=0o700)
    (attacker / "locks").chmod(0o700)
    swapped = Event()
    real_open = os.open

    def open_and_swap(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if os.fsdecode(path) == parent.name and dir_fd is not None and not swapped.is_set():
            parent.rename(held_parent)
            parent.symlink_to(attacker, target_is_directory=True)
            swapped.set()
        return descriptor

    monkeypatch.setattr(module.os, "open", open_and_swap)
    with _lock(root):
        assert swapped.is_set(), "test hook must swap the opened ancestor"

    assert (held_parent / "locks" / f"{_ACCOUNT_A}.lock").is_file()
    assert not (attacker / "locks" / f"{_ACCOUNT_A}.lock").exists()


def test_d1_5_openat_walk_rechecks_evented_ancestor_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _run_020()
    parent = tmp_path / "trusted-parent"
    root = parent / "locks"
    root.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    widened = Event()
    real_open = os.open

    def open_and_widen(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if os.fsdecode(path) == parent.name and dir_fd is not None and not widened.is_set():
            parent.chmod(0o777)
            widened.set()
        return descriptor

    monkeypatch.setattr(module.os, "open", open_and_widen)
    try:
        with pytest.raises(_error_type("RunSessionLockSecurityError")):
            with _lock(root):
                pytest.fail("wide ancestor must not be trusted")
    finally:
        parent.chmod(0o700)

    assert widened.is_set(), "test hook must widen the opened ancestor"


def test_d1_5_unlock_failure_does_not_replace_business_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _run_020()
    root = _secure_lock_root(tmp_path)
    real_flock = module.fcntl.flock

    def fail_unlock(fd: int, operation: int) -> None:
        if operation == module.fcntl.LOCK_UN:
            raise OSError(_SECRET_CANARY)
        real_flock(fd, operation)

    monkeypatch.setattr(module.fcntl, "flock", fail_unlock)
    with pytest.raises(RuntimeError, match="business failure") as caught:
        with _lock(root):
            raise RuntimeError("business failure")

    assert type(caught.value) is RuntimeError
    assert _SECRET_CANARY not in _exception_chain_text(caught.value)
    assert _probe_lock_once(root, _ACCOUNT_A) == "acquired"
