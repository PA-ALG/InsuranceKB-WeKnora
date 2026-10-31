"""U-2b acceptance (protected, written by Claude): eight upstream test files that were changed only
to host our own tests, fixture fields or registrations are restored to the pinned upstream bytes;
our tests move to new test files in the same packages, production code is unchanged
(Spec docs/design/slices/U-2b-上游测试夹具外移.md, Issue #451 phase c).

Standard library only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT, UPSTREAM_BASE, upstream_patched_files  # noqa: E402

LIST = Path(__file__).resolve().parent / "u2b_restored_upstream_tests.txt"
# G10 on main@71ea503dd (after U-2a, U-5a and S7f-2b; base v0.9.0) was 161.
G10_BEFORE = 161


def listed() -> list[str]:
    return [line.strip() for line in LIST.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_list_is_the_frozen_u2b_scope() -> None:
    files = listed()
    assert len(files) == 8 and len(set(files)) == 8
    assert files == sorted(files)
    assert all(path.endswith(("_test.go", ".py")) for path in files)


def test_every_listed_file_is_byte_identical_to_upstream() -> None:
    diverged = [
        path
        for path in listed()
        if subprocess.run(
            ["git", "diff", "--quiet", UPSTREAM_BASE, "--", path], cwd=REPO_ROOT
        ).returncode
        != 0
    ]
    assert diverged == []


def test_the_g10_count_drops_by_the_restored_files() -> None:
    # A later slice may register and add a new upstream patch with Claude's approval; it must
    # then raise this bound in a disclosed commit, the same way it re-records the G10 baseline.
    assert len(upstream_patched_files()) <= G10_BEFORE - len(listed())
