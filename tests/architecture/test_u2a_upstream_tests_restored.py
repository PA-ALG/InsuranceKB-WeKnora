"""U-2a acceptance (protected, written by Claude): six upstream test files that were changed only to
create the revision-source table in their SQLite fixtures are restored to the pinned upstream bytes,
because the read-only pin checks now treat a catalog-confirmed missing table on SQLite as "nothing
pinned" (Spec docs/design/slices/U-2a-修订来源只读守卫与上游测试还原.md, Issue #451 phase c).

Standard library only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT, UPSTREAM_BASE, upstream_patched_files  # noqa: E402

LIST = Path(__file__).resolve().parent / "u2a_restored_upstream_tests.txt"
# G10 on main@62d2f804b (phase c start, base v0.9.0) was 169.
G10_BEFORE = 169


def listed() -> list[str]:
    return [line.strip() for line in LIST.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_list_is_the_frozen_u2a_scope() -> None:
    files = listed()
    assert len(files) == 6 and len(set(files)) == 6
    assert files == sorted(files)
    assert all(path.endswith("_test.go") for path in files)


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
