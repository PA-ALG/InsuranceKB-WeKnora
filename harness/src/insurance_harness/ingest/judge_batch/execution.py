"""Trusted, budgeted fresh-session launcher. No automatic retry of an unknown result."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import shlex
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from insurance_harness.ingest.judge_batch.launch import SANDBOX
from insurance_harness.ingest.judge_batch.manifest import check_run_root, check_sessions, write_json
from insurance_harness.ingest.judge_batch.points import JudgeBatchError
from insurance_harness.models.run_files import IntegrityError, check_directory, read_regular


def read_json(path: Path) -> Any:
    try:
        raw = read_regular(path)
        if raw is None:
            raise ValueError()
        return json.loads(raw)
    except (IntegrityError, OSError, ValueError, RecursionError):
        raise JudgeBatchError("REVIEW_RECORD_INVALID") from None


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def sha(path: Path) -> str:
    try:
        raw = read_regular(path)
        if raw is None:
            raise ValueError()
        return hashlib.sha256(raw).hexdigest()
    except (IntegrityError, OSError, ValueError):
        raise JudgeBatchError("REVIEW_RECORD_INVALID") from None


def plan_of(root: Path) -> dict[str, Any]:
    value: Any = read_json(root / "plan.json")
    try:
        if not isinstance(value, dict) or value.get("review_protocol") != "dual-v1":
            raise JudgeBatchError("DUAL_REVIEW_REQUIRED")
        if (
            type(value["round"]) is not int
            or value["round"] not in (1, 2)
            or type(value["session_budget"]) is not int
            or value["session_budget"] < 0
            or not isinstance(value["model"], str)
            or not value["model"].strip()
            or not isinstance(value["operator_prompt"], str)
            or not value["operator_prompt"].strip()
            or not isinstance(value["sessions"], dict)
        ):
            raise ValueError()
        if value["round"] == 2 and root.name != "second":
            raise ValueError()
        for name, entry in value["sessions"].items():
            if not re.fullmatch(r"s[0-9]+", name) or not isinstance(entry, dict):
                raise ValueError()
            for key in ("products", "slugs"):
                if not isinstance(entry[key], list) or not all(
                    isinstance(v, str) and v for v in entry[key]
                ):
                    raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise JudgeBatchError("REVIEW_RECORD_INVALID") from None
    return value


def binding(root: Path) -> str:
    check_run_root(root)
    try:
        check_directory(owner(root))
    except IntegrityError:
        raise JudgeBatchError("REVIEW_RECORD_INVALID") from None
    plan = plan_of(root)
    if plan.get("review_protocol") != "dual-v1":
        raise JudgeBatchError("DUAL_REVIEW_REQUIRED")
    check_sessions(root, sorted(plan["sessions"]))
    return digest(
        {
            p.relative_to(root).as_posix(): sha(p)
            for p in [
                root / "plan.json",
                root / "manifest.json",
                *sorted((root / "data").glob("*.json")),
            ]
        }
    )


def owner(root: Path) -> Path:
    plan = plan_of(root)
    return root.parent if plan.get("round") == 2 and root.name == "second" else root


@contextmanager
def locked(root: Path) -> Iterator[None]:
    path = owner(root) / ".sessions.lock"
    if path.is_symlink():
        raise JudgeBatchError("REVIEW_RECORD_INVALID")
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise JudgeBatchError("SESSION_BUSY") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def ledger(root: Path) -> list[dict[str, Any]]:
    path = owner(root) / "sessions-ledger.json"
    value = read_json(path) if path.exists() else []
    if not isinstance(value, list):
        raise JudgeBatchError("REVIEW_RECORD_INVALID")
    try:
        keys = set()
        for row in value:
            key = (row["round"], row["session"], row["attempt"])
            if (
                type(row["round"]) is not int
                or row["round"] not in (1, 2)
                or not re.fullmatch(r"s[0-9]+", row["session"])
                or type(row["attempt"]) is not int
                or row["attempt"] < 1
                or row["status"] not in {"pending", "failed", "complete"}
                or not re.fullmatch(r"[0-9a-f]{64}", row["input"])
                or key in keys
                or (row["status"] == "complete" and not isinstance(row.get("proof"), dict))
            ):
                raise ValueError()
            keys.add(key)
    except (ValueError, TypeError, KeyError):
        raise JudgeBatchError("REVIEW_RECORD_INVALID") from None
    known = {(r["round"], f"{r['session']}-{r['attempt']:04d}") for r in value}
    for number, folder in ((1, owner(root)), (2, owner(root) / "second")):
        if any(
            (number, p.name.removesuffix(".events.jsonl")) not in known
            for p in (folder / "attempts").glob("*.events.jsonl")
        ):
            raise JudgeBatchError("REVIEW_RECORD_INVALID")
    return value


def save(root: Path, rows: list[dict[str, Any]]) -> None:
    write_json(owner(root) / "sessions-ledger.json", rows)


def workspace(root: Path, row: dict[str, Any]) -> Path:
    return root / "attempts" / f"{row['session']}-{row['attempt']:04d}"


def files(root: Path, session: str) -> dict[str, str]:
    try:
        result = dict(read_json(root / "manifest.json")["sessions"][session]["files"])
        for relative, value in result.items():
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError()
        return result
    except (KeyError, TypeError, ValueError):
        raise JudgeBatchError("MANIFEST_MISSING") from None


def answers(path: Path, expected: dict[str, str]) -> dict[str, str]:
    for relative, value in expected.items():
        if sha(path / relative) != value:
            raise JudgeBatchError("SESSION_CHANGED")
    requested = {Path(p).name for p in expected if p.startswith("requests/")}
    present = {p.name for p in (path / "responses").iterdir()}
    if present != requested:
        raise JudgeBatchError("ANSWER_MISSING")
    return {name: sha(path / "responses" / name) for name in sorted(requested)}


def probe(root: Path, path: Path) -> None:
    """Real no-model sandbox writes under the same settings as the subsequent exec."""

    def writes(target: Path) -> bool:
        result = subprocess.run(
            [
                "codex",
                "sandbox",
                *shlex.split(SANDBOX),
                "--",
                "/bin/sh",
                "-c",
                'touch "$1/.boundary-probe" && rm -f "$1/.boundary-probe"',
                "probe",
                str(target),
            ],
            cwd=path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0

    if not writes(path) or any(
        writes(target)
        for target in (owner(root), root, root / "data", root / "sessions", root / "attempts")
    ):
        raise JudgeBatchError("SANDBOX_PROBE_FAILED")


def command(root: Path, path: Path) -> list[str]:
    plan = plan_of(root)
    return [
        "codex",
        "exec",
        "--json",
        "-m",
        plan["model"],
        "-c",
        'model_reasoning_effort="xhigh"',
        "--skip-git-repo-check",
        "-s",
        "workspace-write",
        *shlex.split(SANDBOX),
        "-C",
        str(path),
        plan["operator_prompt"],
    ]


def inspect(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    if row["input"] != binding(root):
        raise JudgeBatchError("REVIEW_INPUTS_CHANGED")
    path = workspace(root, row)
    if row.get("command") != digest(command(root, path)):
        raise JudgeBatchError("REVIEW_RECORD_INVALID")
    exit_path = path.parent / (path.name + ".exit.json")
    events_path = path.parent / (path.name + ".events.jsonl")
    if not exit_path.exists():
        raise JudgeBatchError("SESSION_RESULT_UNKNOWN")
    status = read_json(exit_path)
    if (
        not isinstance(status, dict)
        or set(status) != {"input", "events", "code"}
        or type(status.get("code")) is not int
    ):
        raise JudgeBatchError("REVIEW_RECORD_INVALID")
    if status["input"] != row["input"] or status["events"] != sha(events_path):
        raise JudgeBatchError("REVIEW_RECORD_INVALID")
    if status["code"] != 0:
        raise JudgeBatchError("SESSION_FAILED")
    try:
        events = [json.loads(s) for s in events_path.read_text().splitlines() if s.strip()]
        threads = [e["thread_id"] for e in events if e.get("type") == "thread.started"]
        if (
            len(threads) != 1
            or not isinstance(threads[0], str)
            or not threads[0].strip()
            or sum(e.get("type") == "turn.completed" for e in events) != 1
            or any(e.get("type") in {"turn.failed", "error"} for e in events)
        ):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise JudgeBatchError("SESSION_FAILED") from None
    return {
        "thread": threads[0],
        "model": plan_of(root)["model"],
        "input": row["input"],
        "command": row["command"],
        "events": sha(events_path),
        "exit": sha(exit_path),
        "answers": answers(path, files(root, row["session"])),
    }


def proof(root: Path) -> dict[str, dict[str, Any]]:
    binding(root)
    plan = plan_of(root)
    rows = ledger(root)
    result = {}
    for session in plan["sessions"]:
        matches = [r for r in rows if r["round"] == plan["round"] and r["session"] == session]
        if not matches or matches[-1]["status"] != "complete":
            raise JudgeBatchError("SESSION_UNVERIFIED")
        row = matches[-1]
        actual = inspect(root, row)
        if actual != row["proof"]:
            raise JudgeBatchError("REVIEW_RECORD_INVALID")
        result[session] = {**actual, "attempt": row["attempt"]}
    threads = [p["thread"] for p in result.values()]
    if len(threads) != len(set(threads)):
        raise JudgeBatchError("SESSION_NOT_INDEPENDENT")
    return result


def reconcile(root: Path, session: str) -> dict[str, Any]:
    with locked(root):
        return settle(root, session, ledger(root))


def settle(root: Path, session: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    round_number = plan_of(root)["round"]
    matches = [r for r in rows if r["round"] == round_number and r["session"] == session]
    if not matches:
        raise JudgeBatchError("SESSION_UNVERIFIED")
    row = matches[-1]
    if row["status"] == "failed":
        raise JudgeBatchError("SESSION_FAILED")
    try:
        verified = inspect(root, row)
    except JudgeBatchError as error:
        if error.code in {"SESSION_FAILED", "ANSWER_MISSING"}:
            row["status"] = "failed"
            save(root, rows)
        raise
    if row["status"] == "complete":
        if row["proof"] != verified:
            raise JudgeBatchError("REVIEW_RECORD_INVALID")
        return row
    for old in rows:
        if old is row:
            continue
        other = owner(root) / "second" if old["round"] == 2 else owner(root)
        old_path = workspace(other, old)
        events = old_path.parent / (old_path.name + ".events.jsonl")
        if events.exists():
            seen = []
            for line in events.read_text().splitlines():
                try:
                    seen.append(json.loads(line))
                except ValueError:
                    if old["status"] != "failed":
                        raise JudgeBatchError("SESSION_RESULT_UNKNOWN") from None
            if any(
                isinstance(e, dict)
                and e.get("type") == "thread.started"
                and e.get("thread_id") == verified["thread"]
                for e in seen
            ):
                row.update(status="failed", failure="SESSION_NOT_INDEPENDENT")
                save(root, rows)
                raise JudgeBatchError("SESSION_NOT_INDEPENDENT")
    row.update(status="complete", proof=verified)
    save(root, rows)
    return row


def execute(root: Path, session: str, *, retry: bool = False) -> dict[str, Any]:
    bound = binding(root)
    plan = plan_of(root)
    if plan["round"] == 2:
        from insurance_harness.ingest.judge_batch.dual import check_second

        check_second(owner(root))
    if session not in plan["sessions"] or not session.isalnum():
        raise JudgeBatchError("SESSION_INVALID")
    with locked(root):
        rows = ledger(root)
        existing = [r for r in rows if r["round"] == plan["round"] and r["session"] == session]
        if existing and any(r["input"] != bound for r in existing):
            raise JudgeBatchError("REVIEW_INPUTS_CHANGED")
        if existing and existing[-1]["status"] != "failed":
            return settle(root, session, rows)  # pending: reconcile, never send blindly
        if existing and not retry:
            raise JudgeBatchError("SESSION_RETRY_REQUIRED")
        if any(r["status"] == "pending" for r in rows):
            raise JudgeBatchError("SESSION_RESULT_UNKNOWN")
        if len(rows) >= plan_of(owner(root))["session_budget"]:
            raise JudgeBatchError("SESSION_BUDGET_EXHAUSTED")
        attempt = len(existing) + 1
        while (root / "attempts" / f"{session}-{attempt:04d}").exists():
            attempt += 1  # orphan before pending was never sent
        row = {
            "round": plan["round"],
            "session": session,
            "attempt": attempt,
            "input": bound,
            "status": "pending",
        }
        path = workspace(root, row)
        row["command"] = digest(command(root, path))
        path.mkdir(parents=True, mode=0o700)
        for relative in files(root, session):
            target = path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write((root / "sessions" / session / relative).read_bytes())
        (path / "responses").mkdir()
        (root / "data").mkdir(exist_ok=True)
        probe(root, path)
        if binding(root) != bound or any(
            sha(path / p) != h for p, h in files(root, session).items()
        ):
            raise JudgeBatchError("REVIEW_INPUTS_CHANGED")
        rows.append(row)
        save(root, rows)  # before any model start, even a failed start counts
        events = path.parent / (path.name + ".events.jsonl")
        try:
            with (
                events.open("xb") as output,
                (path.parent / (path.name + ".stderr")).open("xb") as err,
            ):
                done = subprocess.run(
                    command(root, path),
                    stdout=output,
                    stderr=err,
                    stdin=subprocess.DEVNULL,
                    check=False,
                )
            write_json(
                path.parent / (path.name + ".exit.json"),
                {"code": done.returncode, "input": bound, "events": sha(events)},
            )
        except OSError:
            raise JudgeBatchError("SESSION_RESULT_UNKNOWN") from None
        return settle(root, session, rows)


def invalid_answer(root: Path, session: str) -> None:
    """Known complete execution with invalid JSON/coverage may be explicitly retried."""
    with locked(root):
        rows = ledger(root)
        matches = [
            r for r in rows if r["round"] == plan_of(root)["round"] and r["session"] == session
        ]
        if not matches or matches[-1]["status"] != "complete":
            raise JudgeBatchError("SESSION_UNVERIFIED")
        matches[-1]["status"] = "failed"
        matches[-1]["failure"] = "ANSWER_INVALID"
        save(root, rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["execute", "reconcile"])
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--retry", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "execute":
            execute(args.run_root, args.session, retry=args.retry)
        else:
            reconcile(args.run_root, args.session)
    except JudgeBatchError as error:
        print(error.code, file=sys.stderr)
        return 3
    except OSError:
        print("REVIEW_IO_ERROR", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
