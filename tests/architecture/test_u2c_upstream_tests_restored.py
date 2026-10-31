"""U-2c acceptance (protected, written by Claude): the two upstream test files U-2b left for a
fixture rework (parent_child, knowledge_replace) are restored to the pinned upstream bytes; our
fixture additions move to our own test files in the same package, production code is unchanged
(Spec docs/design/slices/U-2c-上游测试夹具外移续.md, Issue #451 phase c).

Standard library only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT, UPSTREAM_BASE, upstream_patched_files  # noqa: E402

LIST = Path(__file__).resolve().parent / "u2c_restored_upstream_tests.txt"
SERVICE = REPO_ROOT / "internal" / "application" / "service"
# G10 on main@bb98264cc (after U-2b and S7f-2b2; base v0.9.0) was 153.
G10_BEFORE = 153
# Our tests that lived in the restored files or in our old replace fixture, and where they live now.
MOVED_TESTS = {
    "knowledge_replace_revision_test.go": (
        "TestReplaceKnowledgeFileBindsNewBytesWhenPreviousSHAIsNonempty",
        "TestReplaceKnowledgeFileKeepsSourceSHAPairedWithPathDuringCompensation",
    ),
    "knowledge_process_parent_child_revision_test.go": ("TestProcessChunksIndexesEveryTextChildSucceeds",),
}


def listed() -> list[str]:
    return [line.strip() for line in LIST.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_list_is_the_frozen_u2c_scope() -> None:
    files = listed()
    assert files == sorted(set(files)) and len(files) == 2
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


def test_our_replace_fixture_is_gone_and_moved_tests_exist_once() -> None:
    assert not (SERVICE / "knowledge_replace_fixture_test.go").exists()
    sources = {path.name: path.read_text(encoding="utf-8") for path in SERVICE.glob("*_test.go")}
    for owner, names in MOVED_TESTS.items():
        for name in names:
            declared = [file for file, text in sources.items() if re.search(rf"^func {name}\(", text, re.M)]
            assert declared == [owner], name


def test_the_g10_count_drops_by_the_restored_files() -> None:
    # A later slice may register and add a new upstream patch with Claude's approval; it must
    # then raise this bound in a disclosed commit, the same way it re-records the G10 baseline.
    assert len(upstream_patched_files()) <= G10_BEFORE - len(listed())
