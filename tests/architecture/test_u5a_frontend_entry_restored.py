"""U-5a acceptance (protected, written by Claude): upstream's route table, menu store and i18n setup
are restored to the pinned upstream bytes; the enterprise module registers its pages, sidebar entry
and strings at startup through one call that main.ts gains next to its import
(Spec docs/design/slices/U-5a-前端企业入口收口.md, Issue #451 phase c).

Standard library only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT, UPSTREAM_BASE, upstream_patched_files  # noqa: E402

RESTORED = (
    "frontend/src/i18n/index.ts",
    "frontend/src/router/index.ts",
    "frontend/src/stores/menu.ts",
)
MAIN = "frontend/src/main.ts"
MAIN_ADDED = [
    'import { installEnterprise } from "@/enterprise/install";',
    "  installEnterprise({ router, i18n, pinia });",
]
# G10 on main@a4c972719 (after U-2a) was 163; main.ts becomes the one new registered patch.
G10_BEFORE = 163


def diff(*args: str) -> str:
    return subprocess.run(
        ["git", "diff", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_every_restored_file_is_byte_identical_to_upstream() -> None:
    diverged = [
        path
        for path in RESTORED
        if subprocess.run(
            ["git", "diff", "--quiet", UPSTREAM_BASE, "--", path], cwd=REPO_ROOT
        ).returncode
        != 0
    ]
    assert diverged == []


def test_main_ts_only_gains_the_import_and_the_install_call() -> None:
    out = diff("-U0", "--no-color", UPSTREAM_BASE, "--", MAIN)
    body = [
        line
        for line in out.splitlines()
        if not line.startswith(("diff ", "index ", "--- ", "+++ ", "@@"))
    ]
    assert [line for line in body if line.startswith("-")] == []
    assert [line[1:] for line in body if line.startswith("+")] == MAIN_ADDED


def test_the_g10_count_drops_by_two() -> None:
    # A later slice may register and add a new upstream patch with Claude's approval; it must
    # then raise this bound in a disclosed commit, the same way it re-records the G10 baseline.
    patched = upstream_patched_files()
    assert MAIN in patched
    assert len(patched) <= G10_BEFORE - len(RESTORED) + 1
