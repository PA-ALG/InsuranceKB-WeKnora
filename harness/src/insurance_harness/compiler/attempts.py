"""Durable, run-scoped audit ledger for real outbound LLM calls (024 E3/E7).

The reservation transaction commits before ``ModelClient.complete`` is invoked.
Consequently an indeterminate call left by a hard process crash remains visible
and, for budgeted stages, continues to consume the hard run budget.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Protocol, cast

from .llm import GapfillBudgetExhausted
from .models import AuditAttempt

Assignment = Literal["control", "treatment"]


class AttemptLedgerMismatch(RuntimeError):
    """A resume tried to change a run-scoped durable ledger contract."""


class AttemptLedger(Protocol):
    """Storage boundary used by extraction helpers and the pipeline."""

    run_id: str

    def ensure_budget(self, budget_scope: str, budget_limit: int | None) -> None: ...

    def reserve(
        self,
        *,
        stage: str,
        prompt_version: str,
        request_key: str,
        field_ids: Sequence[str],
        budget_scope: str | None = None,
        budget_limit: int | None = None,
    ) -> AuditAttempt: ...

    def finish(self, attempt_id: str, outcome: str) -> AuditAttempt: ...

    def attempts_for_field(self, field_id: str) -> tuple[AuditAttempt, ...]: ...

    def used(self, budget_scope: str) -> int: ...

    def record_assignment(self, field_id: str, arm: Assignment | None) -> None: ...

    def assignment_for_field(self, field_id: str) -> Assignment | None: ...


def _attempt_id(sequence: int, stage: str, request_key: str) -> str:
    """Run-local unique and replay-deterministic call identity."""
    return f"{sequence:08d}:{stage}:{request_key[:12]}"


class InMemoryAttemptLedger:
    """Deterministic-test/standalone implementation with the same semantics."""

    def __init__(self, run_id: str = "standalone") -> None:
        self.run_id = run_id
        self._attempts: list[AuditAttempt] = []
        self._fields: dict[str, list[str]] = {}
        self._scopes: dict[str, str] = {}
        self._budget_limits: dict[str, int | None] = {}
        self._assignments: dict[str, Assignment] = {}
        self._lock = threading.Lock()

    def ensure_budget(self, budget_scope: str, budget_limit: int | None) -> None:
        with self._lock:
            if budget_scope in self._budget_limits:
                existing = self._budget_limits[budget_scope]
                if existing != budget_limit:
                    raise AttemptLedgerMismatch(
                        f"{budget_scope!r} budget changed: {existing!r} -> {budget_limit!r}"
                    )
            else:
                self._budget_limits[budget_scope] = budget_limit

    def reserve(
        self,
        *,
        stage: str,
        prompt_version: str,
        request_key: str,
        field_ids: Sequence[str],
        budget_scope: str | None = None,
        budget_limit: int | None = None,
    ) -> AuditAttempt:
        with self._lock:
            if budget_scope is not None:
                if budget_scope in self._budget_limits:
                    existing = self._budget_limits[budget_scope]
                    if existing != budget_limit:
                        raise AttemptLedgerMismatch(
                            f"{budget_scope!r} budget changed: "
                            f"{existing!r} -> {budget_limit!r}"
                        )
                else:
                    self._budget_limits[budget_scope] = budget_limit
            if budget_limit is not None:
                used = sum(scope == budget_scope for scope in self._scopes.values())
                if used >= budget_limit:
                    raise GapfillBudgetExhausted(
                        f"{budget_scope or 'LLM'} 调用预算耗尽"
                    )
            sequence = len(self._attempts) + 1
            attempt = AuditAttempt(
                attempt_id=_attempt_id(sequence, stage, request_key),
                stage=stage,
                prompt_version=prompt_version,
                request_key=request_key,
                outcome="reserved",
            )
            self._attempts.append(attempt)
            self._fields[attempt.attempt_id] = list(dict.fromkeys(field_ids))
            if budget_scope is not None:
                self._scopes[attempt.attempt_id] = budget_scope
            return attempt

    def finish(self, attempt_id: str, outcome: str) -> AuditAttempt:
        with self._lock:
            for index, attempt in enumerate(self._attempts):
                if attempt.attempt_id == attempt_id:
                    updated = attempt.model_copy(update={"outcome": outcome})
                    self._attempts[index] = updated
                    return updated
        raise KeyError(f"unknown attempt_id: {attempt_id}")

    def attempts_for_field(self, field_id: str) -> tuple[AuditAttempt, ...]:
        with self._lock:
            return tuple(
                attempt
                for attempt in self._attempts
                if field_id in self._fields.get(attempt.attempt_id, ())
            )

    def used(self, budget_scope: str) -> int:
        with self._lock:
            return sum(scope == budget_scope for scope in self._scopes.values())

    def record_assignment(self, field_id: str, arm: Assignment | None) -> None:
        if arm is None:
            return
        with self._lock:
            existing = self._assignments.get(field_id)
            if existing is not None and existing != arm:
                raise ValueError(
                    f"field {field_id!r} assignment changed: {existing} -> {arm}"
                )
            self._assignments[field_id] = arm

    def assignment_for_field(self, field_id: str) -> Assignment | None:
        with self._lock:
            return self._assignments.get(field_id)


class SqliteAttemptLedger:
    """Crash-safe ledger shared by every node and resume of one pipeline run."""

    def __init__(self, path: Path, *, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS llm_attempts (
                    run_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    budget_scope TEXT,
                    PRIMARY KEY (run_id, attempt_id),
                    UNIQUE (run_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS ix_llm_attempts_run_scope
                    ON llm_attempts (run_id, budget_scope);
                CREATE TABLE IF NOT EXISTS llm_attempt_fields (
                    run_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    field_id TEXT NOT NULL,
                    PRIMARY KEY (run_id, attempt_id, field_id),
                    FOREIGN KEY (run_id, attempt_id)
                        REFERENCES llm_attempts(run_id, attempt_id)
                );
                CREATE INDEX IF NOT EXISTS ix_llm_attempt_fields_field
                    ON llm_attempt_fields (run_id, field_id, attempt_id);
                CREATE TABLE IF NOT EXISTS llm_budget_policies (
                    run_id TEXT NOT NULL,
                    budget_scope TEXT NOT NULL,
                    budget_limit INTEGER,
                    PRIMARY KEY (run_id, budget_scope)
                );
                CREATE TABLE IF NOT EXISTS llm_variant_assignments (
                    run_id TEXT NOT NULL,
                    field_id TEXT NOT NULL,
                    arm TEXT NOT NULL CHECK (arm IN ('control', 'treatment')),
                    PRIMARY KEY (run_id, field_id)
                );
                """
            )

    def ensure_budget(self, budget_scope: str, budget_limit: int | None) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_budget_row(conn, budget_scope, budget_limit)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_budget_row(
        self,
        conn: sqlite3.Connection,
        budget_scope: str,
        budget_limit: int | None,
    ) -> None:
        row = conn.execute(
            "SELECT budget_limit FROM llm_budget_policies "
            "WHERE run_id = ? AND budget_scope = ?",
            (self.run_id, budget_scope),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO llm_budget_policies "
                "(run_id, budget_scope, budget_limit) VALUES (?, ?, ?)",
                (self.run_id, budget_scope, budget_limit),
            )
            return
        existing = None if row[0] is None else int(row[0])
        if existing != budget_limit:
            raise AttemptLedgerMismatch(
                f"{budget_scope!r} budget changed: {existing!r} -> {budget_limit!r}"
            )

    def reserve(
        self,
        *,
        stage: str,
        prompt_version: str,
        request_key: str,
        field_ids: Sequence[str],
        budget_scope: str | None = None,
        budget_limit: int | None = None,
    ) -> AuditAttempt:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if budget_scope is not None:
                self._ensure_budget_row(conn, budget_scope, budget_limit)
            if budget_limit is not None:
                row = conn.execute(
                    "SELECT COUNT(*) FROM llm_attempts "
                    "WHERE run_id = ? AND budget_scope = ?",
                    (self.run_id, budget_scope),
                ).fetchone()
                used = int(row[0]) if row is not None else 0
                if used >= budget_limit:
                    raise GapfillBudgetExhausted(
                        f"{budget_scope or 'LLM'} 调用预算耗尽"
                    )
            row = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM llm_attempts "
                "WHERE run_id = ?",
                (self.run_id,),
            ).fetchone()
            sequence = int(row[0])
            attempt = AuditAttempt(
                attempt_id=_attempt_id(sequence, stage, request_key),
                stage=stage,
                prompt_version=prompt_version,
                request_key=request_key,
                outcome="reserved",
            )
            conn.execute(
                "INSERT INTO llm_attempts "
                "(attempt_id, run_id, sequence, stage, prompt_version, request_key, "
                " outcome, budget_scope) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt.attempt_id,
                    self.run_id,
                    sequence,
                    stage,
                    prompt_version,
                    request_key,
                    attempt.outcome,
                    budget_scope,
                ),
            )
            conn.executemany(
                "INSERT INTO llm_attempt_fields "
                "(run_id, attempt_id, field_id) VALUES (?, ?, ?)",
                (
                    (self.run_id, attempt.attempt_id, field_id)
                    for field_id in dict.fromkeys(field_ids)
                ),
            )
            conn.commit()
            return attempt
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def finish(self, attempt_id: str, outcome: str) -> AuditAttempt:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE llm_attempts SET outcome = ? "
                "WHERE run_id = ? AND attempt_id = ?",
                (outcome, self.run_id, attempt_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown attempt_id: {attempt_id}")
            row = conn.execute(
                "SELECT attempt_id, stage, prompt_version, request_key, outcome "
                "FROM llm_attempts WHERE run_id = ? AND attempt_id = ?",
                (self.run_id, attempt_id),
            ).fetchone()
        assert row is not None
        return _row_to_attempt(row)

    def attempts_for_field(self, field_id: str) -> tuple[AuditAttempt, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT a.attempt_id, a.stage, a.prompt_version, a.request_key, "
                "a.outcome FROM llm_attempts AS a "
                "JOIN llm_attempt_fields AS f "
                "ON f.run_id = a.run_id AND f.attempt_id = a.attempt_id "
                "WHERE a.run_id = ? AND f.field_id = ? ORDER BY a.sequence",
                (self.run_id, field_id),
            ).fetchall()
        return tuple(_row_to_attempt(row) for row in rows)

    def used(self, budget_scope: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM llm_attempts "
                "WHERE run_id = ? AND budget_scope = ?",
                (self.run_id, budget_scope),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def record_assignment(self, field_id: str, arm: Assignment | None) -> None:
        if arm is None:
            return
        with self._connect() as conn:
            row = conn.execute(
                "SELECT arm FROM llm_variant_assignments "
                "WHERE run_id = ? AND field_id = ?",
                (self.run_id, field_id),
            ).fetchone()
            if row is not None and row[0] != arm:
                raise ValueError(
                    f"field {field_id!r} assignment changed: {row[0]} -> {arm}"
                )
            conn.execute(
                "INSERT OR IGNORE INTO llm_variant_assignments "
                "(run_id, field_id, arm) VALUES (?, ?, ?)",
                (self.run_id, field_id, arm),
            )

    def assignment_for_field(self, field_id: str) -> Assignment | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT arm FROM llm_variant_assignments "
                "WHERE run_id = ? AND field_id = ?",
                (self.run_id, field_id),
            ).fetchone()
        if row is None:
            return None
        arm = str(row[0])
        if arm not in ("control", "treatment"):
            raise RuntimeError(f"invalid persisted assignment: {arm!r}")
        return cast(Assignment, arm)


def _row_to_attempt(row: Sequence[object]) -> AuditAttempt:
    return AuditAttempt(
        attempt_id=str(row[0]),
        stage=str(row[1]),
        prompt_version=str(row[2]),
        request_key=str(row[3]),
        outcome=str(row[4]),
    )
