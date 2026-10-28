"""The trusted record of what prepare gave each judge session (RV7 Spec §2.1, §2.2; review R2, R6).

A judge session can write its own directory, so nothing in it proves what was asked: a request
rewritten together with its own hash still checks out. Prepare therefore writes only into a fresh
run root outside Git, never overwrites a file, and lists every file it gave a session with its
sha256 in `manifest.json`, outside the sessions. Ingest compares the session files byte for byte
with that list before it reads any answer.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from insurance_harness.eval.judge import JudgeRequest
from insurance_harness.eval.judge_files import check_run_directory, write_requests
from insurance_harness.ingest.judge_batch.points import JudgeBatchError

MANIFEST = "manifest.json"


def write_json(path: Path, data: object) -> None:
    """Write a whole file at once, so a reader never sees half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    temporary.replace(path)


def check_run_root(run_root: Path) -> None:
    try:
        check_run_directory(run_root)
    except ValueError:
        raise JudgeBatchError("RUN_ROOT_IN_GIT") from None


def check_fresh(run_root: Path) -> None:
    """The run root resolves outside Git and holds nothing yet, so no leftover can be reused."""
    check_run_root(run_root)
    if run_root.exists() and (not run_root.is_dir() or any(run_root.iterdir())):
        raise JudgeBatchError("RUN_EXISTS")


def preflight(run_root: Path, targets: list[Path]) -> None:
    """Checked again right before the first write: fresh, outside Git, no two files alike."""
    check_fresh(run_root)
    if len({target.as_posix() for target in targets}) != len(targets):
        raise JudgeBatchError("TARGET_COLLISION")


def write_session(
    session_dir: Path, requests: list[JudgeRequest], texts: dict[str, str]
) -> dict[str, str]:
    """Write one session without overwriting anything; returns each file's sha256."""
    write_requests(requests, session_dir)
    for relative, text in texts.items():
        target = session_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as stream:
            stream.write(text)
    return {
        path.relative_to(session_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(session_dir.rglob("*"))
        if path.is_file()
    }


def check_sessions(run_root: Path, sessions: list[str]) -> None:
    """Every file prepare gave a session is still exactly as written; no request was added."""
    try:
        manifest: Any = json.loads((run_root / MANIFEST).read_text(encoding="utf-8"))
        listed = {session: dict(manifest["sessions"][session]["files"]) for session in sessions}
    except (OSError, ValueError, KeyError, TypeError):
        raise JudgeBatchError("MANIFEST_MISSING") from None
    for session, files in sorted(listed.items()):
        session_dir = run_root / "sessions" / session
        asked = {name for name in files if name.startswith("requests/")}
        try:
            present = {f"requests/{path.name}" for path in (session_dir / "requests").iterdir()}
        except OSError:
            present = set()
        if present != asked:
            raise JudgeBatchError("REQUEST_CHANGED")
        for relative, digest in sorted(files.items()):
            try:
                same = hashlib.sha256((session_dir / relative).read_bytes()).hexdigest() == digest
            except OSError:
                same = False
            if not same:
                kind = "REQUEST_CHANGED" if relative in asked else "SESSION_CHANGED"
                raise JudgeBatchError(kind)
