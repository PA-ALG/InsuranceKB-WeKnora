"""RV7 review round 2, R2: no judge session can write the trusted record.

Spec docs/design/slices/RV7-模型评审批次命令.md §1. `workspace-write` alone also opens $TMPDIR, /tmp
and configured extra roots, so every sandbox run.sh starts removes them, and a probe under the same
settings must show the run root read-only before any judge starts. A stand-in `codex` plays the
sandbox here: it writes a directory only where the given boundary allows and records every judge
it would start; no model runs.
"""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.ingest.judge_batch.launch import REFUSED, SANDBOX
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.ingest.test_judge_batch import prepared, world  # noqa: F401

# open: the old boundary, anything is writable; bounded: only the working (session) directory;
# broken: the sandbox cannot run at all, so a refused write proves nothing.
FAKE_CODEX = """#!/bin/sh
case "$1" in
  sandbox)
    [ "$FAKE_SANDBOX" = broken ] && exit 1
    while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done
    shift
    for target; do :; done
    if [ "$FAKE_SANDBOX" = bounded ] && [ "$target" != "$PWD" ]; then exit 1; fi
    exec "$@" ;;
  exec)
    printf '%s\\n' "$*" >> "$FAKE_CODEX_LOG" ;;
esac
"""


def launch(case: dict[str, Any], tmp_path: Path, sandbox: str) -> tuple[int, list[str]]:
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    fake = tools / "codex"
    fake.write_text(FAKE_CODEX, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / f"judges-{sandbox}.log"
    env = {
        **os.environ,
        "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
        "FAKE_SANDBOX": sandbox,
        "FAKE_CODEX_LOG": str(log),
    }
    done = subprocess.run(
        ["/bin/sh", str(case["run_root"] / "run.sh")], env=env, capture_output=True, check=False
    )
    started = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return done.returncode, started


def test_every_judge_runs_with_temporary_and_extra_roots_removed(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepared(world)
    script = (world["run_root"] / "run.sh").read_text(encoding="utf-8")
    judges = [line for line in script.splitlines() if "codex exec" in line]
    assert judges
    for line in judges:
        assert "-s workspace-write" in line and SANDBOX in line
        assert "--add-dir" not in line and "danger" not in line
    probe = next(line for line in script.splitlines() if "codex sandbox" in line)
    assert SANDBOX in probe, "the probe runs under the judges' exact settings"
    words = shlex.split(SANDBOX)
    assert "sandbox_workspace_write.exclude_tmpdir_env_var=true" in words
    assert "sandbox_workspace_write.exclude_slash_tmp=true" in words
    assert "sandbox_workspace_write.writable_roots=[]" in words


def test_the_trusted_record_lives_outside_every_session(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepared(world)
    run = world["run_root"].resolve()
    sessions = [path.resolve() for path in (run / "sessions").iterdir()]
    for trusted in ("plan.json", "manifest.json", "run.sh", "data"):
        path = (run / trusted).resolve()
        assert path.exists()
        assert not any(path.is_relative_to(session) for session in sessions)


@pytest.mark.parametrize("sandbox", ["open", "broken"])
def test_no_judge_starts_unless_the_run_root_is_shown_read_only(
    world: dict[str, Any],  # noqa: F811
    tmp_path: Path,
    sandbox: str,
) -> None:
    prepared(world)
    code, started = launch(world, tmp_path, sandbox)
    assert code == REFUSED and started == []
    assert not (world["run_root"] / "logs").exists()
    assert not list(world["run_root"].rglob(".boundary-probe"))


def test_judges_start_when_only_their_own_session_is_writable(
    world: dict[str, Any],  # noqa: F811
    tmp_path: Path,
) -> None:
    prepared(world)
    code, started = launch(world, tmp_path, "bounded")
    assert code == 0 and len(started) == 1
    assert f"-C {world['run_root']}/sessions/s01" in started[0]
    assert "sandbox_workspace_write.exclude_slash_tmp=true" in started[0]
