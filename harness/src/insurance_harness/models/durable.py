"""Durable send accounting for a run root shared by the commands that call a model.

Run-root files: budget.jsonl gains one line before every send (so a send that was in flight when
the process died still counts), ledger.jsonl gains every attempt record as it lands, and .lock
serializes runs that share the root. A root holds raw model output that may quote material, so
it must lie outside any git repository. A floating model alias that resolves to a second served
version within one root stops the next send: quality numbers must name one served model.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .ledger import CallLedger, CallRecord


class ServedModelChanged(RuntimeError):
    """A floating model alias resolved to a different version within one run root."""


class RunRootBusy(RuntimeError):
    """Another process holds the run root; sharing it could double-spend the budget."""


def write_new(path: Path, text: str) -> None:
    """Create path atomically and durably; an existing file (or stale temp) is never replaced."""
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()


def _append_durably(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def stored_records(run_root: Path) -> list[CallRecord]:
    return [CallRecord.model_validate_json(line) for line in _lines(run_root / "ledger.jsonl")]


def _recorded_sends(run_root: Path) -> int:
    return sum(
        record.outcome not in ("input_too_large", "budget_exceeded")
        for record in stored_records(run_root)
    )


def prior_sends(run_root: Path) -> int:
    """Sends already spent in this root, counting reservations whose outcome never landed.

    budget.jsonl is authoritative once it exists. It is created atomically with
    a baseline line (an older root's recorded sends, else 0), followed by one
    line per reservation. A file without that first baseline line cannot be
    trusted to be complete, so it fails closed. Roots that predate the file
    only have the ledger's recorded sends.
    """
    budget = run_root / "budget.jsonl"
    if not budget.exists():
        return _recorded_sends(run_root)
    entries = [json.loads(line) for line in _lines(budget)]
    if not entries or not _is_entry(entries[0], "baseline"):
        raise ValueError("budget.jsonl lacks its baseline line; refusing to infer spent sends")
    if not all(_is_entry(entry, "reserved") and entry["reserved"] == 1 for entry in entries[1:]):
        raise ValueError("budget.jsonl has an unexpected entry")
    return int(entries[0]["baseline"]) + len(entries) - 1


def _is_entry(entry: object, key: str) -> bool:
    """Exactly {key: non-negative int}; bools, floats and extra keys are rejected."""
    if not isinstance(entry, dict) or set(entry) != {key}:
        return False
    value = entry[key]
    return type(value) is int and value >= 0


def _adopt_legacy_budget(run_root: Path) -> None:
    """Create budget.jsonl atomically with its baseline, under the lock."""
    if not (run_root / "budget.jsonl").exists():
        write_new(
            run_root / "budget.jsonl", json.dumps({"baseline": _recorded_sends(run_root)}) + "\n"
        )


class DurableLedger(CallLedger):
    """Persist each send reservation before transport entry and each record on arrival.

    The served-model guard runs at reservation time, so a changed version stops
    the very next send, including retries and later batches of the same product.
    """

    def __init__(self, run_root: Path, *, max_sent: int, served: set[str]) -> None:
        super().__init__(max_sent=max_sent)
        self._root, self._served = run_root, served

    @classmethod
    def open(cls, run_root: Path, *, max_sent: int) -> DurableLedger:
        """The root's ledger with what is left of max_sent, which counts every earlier send.

        Call under run_lock: the budget read and every later reservation must not interleave
        with another run on the same root.
        """
        _adopt_legacy_budget(run_root)
        served = {record.served_model for record in stored_records(run_root) if record.served_model}
        if len(served) > 1:
            raise ServedModelChanged("ledger already records more than one served model")
        return cls(run_root, max_sent=max(0, max_sent - prior_sends(run_root)), served=served)

    @property
    def served(self) -> set[str]:
        return set(self._served)

    def reserve_send(self) -> bool:
        if len(self._served) > 1:
            raise ServedModelChanged("served model changed; no further sends")
        if not super().reserve_send():
            return False
        _append_durably(self._root / "budget.jsonl", '{"reserved":1}')
        return True

    def append(self, record: CallRecord) -> None:
        super().append(record)
        _append_durably(self._root / "ledger.jsonl", record.model_dump_json())
        if record.served_model:
            self._served.add(record.served_model)


def _check_outside_git(run_root: Path) -> None:
    """Resolve symlinks before checking every ancestor for Git worktrees or repositories."""
    resolved = run_root.resolve()
    if any((parent / ".git").exists() for parent in (resolved, *resolved.parents)):
        raise ValueError("run root must be outside any git repository")


_HELD: dict[Path, int] = {}


@contextmanager
def run_lock(run_root: Path) -> Iterator[None]:
    """Exclusive across processes and threads; reentrant only for the owning thread.

    A command holds it from the budget read until its last file is written; library entry
    points take it again so direct callers are protected as well. Another thread opens its
    own descriptor, which flock then refuses.
    """
    _check_outside_git(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    key = run_root.resolve()
    if _HELD.get(key) == threading.get_ident():
        yield
        return
    descriptor = os.open(run_root / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RunRootBusy("run root is in use by another process") from None
        _HELD[key] = threading.get_ident()
        try:
            yield
        finally:
            del _HELD[key]
    finally:
        os.close(descriptor)
