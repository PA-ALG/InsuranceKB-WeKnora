"""The operator's launch script for the judge sessions, and the boundary it keeps (RV7 Spec §1).

The run root is the trusted record only while no judge can write it. `workspace-write` alone also
makes the temporary directories ($TMPDIR, /tmp) and any configured extra roots writable, so a run
root under one of them would let a judge rewrite the plan and the manifest together with its
questions (review round 2, R2). Every sandbox the script starts therefore removes those roots,
leaving each session only its own directory. Before any judge starts, the script runs a probe
under exactly the same sandbox settings: it must be able to write the session directory (or the
probe proves nothing) and must fail to write the run root, its data and the sessions directory;
otherwise it stops with exit code 3 and starts no session. The probe runs no model.
"""

from __future__ import annotations

import shlex
from pathlib import Path

SANDBOX = (
    "-c 'sandbox_mode=\"workspace-write\"' "
    "-c 'sandbox_workspace_write.writable_roots=[]' "
    "-c 'sandbox_workspace_write.exclude_tmpdir_env_var=true' "
    "-c 'sandbox_workspace_write.exclude_slash_tmp=true'"
)
REFUSED = 3


def run_script(run_root: Path, sessions: list[str]) -> str:
    """The managed executor probes each fresh workspace and owns durable attempt receipts."""
    import sys

    lines = [
        "#!/bin/sh",
        "set -e",
        "# Fresh codex exec sessions, no resume; operator-only.",
    ]
    for session in sessions:
        lines.append(
            f"{shlex.quote(sys.executable)} -m insurance_harness.ingest.judge_batch "
            f"execute --run-root {shlex.quote(str(run_root))} --session {shlex.quote(session)}"
        )
    return "\n".join(lines) + "\n"
