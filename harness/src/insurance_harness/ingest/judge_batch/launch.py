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
# Directories under the run root that no judge may write; each session's own is the one it may.
TRUSTED = ('"$run"', '"$run/data"', '"$run/sessions"')


def run_script(run_root: Path, sessions: list[str], model: str, operator_prompt: str) -> str:
    probe = (
        f'(cd "$run/sessions/$1" && codex sandbox {SANDBOX} -- '
        '/bin/sh -c \'touch "$1/.boundary-probe" && rm -f "$1/.boundary-probe"\' probe "$2")'
        " > /dev/null 2>&1"
    )
    lines = [
        "#!/bin/sh",
        "# Operator step (RV7 Spec §1): one independent judge session per directory, in parallel.",
        "# Each sandbox may write only its own session directory; see judge_batch/launch.py.",
        f"run={shlex.quote(str(run_root))}",
        f"prompt={shlex.quote(operator_prompt)}",
        f"writes() {{ {probe}; }}",
        f"for session in {' '.join(sessions)}; do",
        '  if ! writes "$session" "$run/sessions/$session"; then',
        '    echo "SANDBOX_PROBE_FAILED $session: no judge started" >&2',
        f"    exit {REFUSED}",
        "  fi",
        f"  for dir in {' '.join(TRUSTED)}; do",
        '    if writes "$session" "$dir"; then',
        '      echo "TRUST_BOUNDARY_OPEN $dir: no judge started" >&2',
        f"      exit {REFUSED}",
        "    fi",
        "  done",
        "done",
        'mkdir -p "$run/logs"',
    ]
    for session in sessions:
        lines.append(
            f"(codex exec -m {shlex.quote(model)} -c model_reasoning_effort='\"xhigh\"' "
            f"--skip-git-repo-check -s workspace-write {SANDBOX} "
            f'-C "$run/sessions/{session}" '
            f'-o "$run/logs/{session}.last.txt" "$prompt" < /dev/null '
            f'> "$run/logs/{session}.codex.log" 2>&1; '
            f'echo "{session} exit=$?" >> "$run/logs/status.txt") &'
        )
    lines.append("wait")
    return "\n".join(lines) + "\n"
