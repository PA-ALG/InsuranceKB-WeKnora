"""S7f-1 acceptance (protected, written by Claude): upstream files whose only divergence from the
pinned WeKnora base is layout or comment text are restored to the upstream bytes, so the G10
upstream-patch count drops by exactly that many files
(Spec docs/design/slices/S7f-1-回退格式改动.md §3).

Standard library only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT, UPSTREAM_BASE, upstream_patched_files  # noqa: E402

LIST = Path(__file__).resolve().parent / "s7f1_format_only_files.txt"
# G10 before S7f-1 (main@5c9e9ae5f) was 477; the list holds the 129 files S7f-1 restores.
G10_BEFORE = 477
# Files that look comment-only but carry behaviour (build tag, lint directives, swag
# annotations feeding the generated OpenAPI docs). They stay patched (Spec §2.3).
KEPT = (
    "docreader/client/client_test.go",
    "internal/application/repository/retriever/opensearch/repository_test.go",
    "internal/container/engine_factory.go",
    "internal/handler/sandbox_skill.go",
)


def listed() -> list[str]:
    return [line.strip() for line in LIST.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_list_is_the_frozen_s7f1_scope() -> None:
    files = listed()
    assert len(files) == 129 and len(set(files)) == 129
    assert files == sorted(files)
    assert not set(files) & set(KEPT)


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


# Updated by Claude in a disclosed commit (Spec §2.2 correction, 2026-10-29): .golangci.yml is an
# upstream file, and S7f-1 adds a registered, temporary lint exclusion to it; the S7f-1 follow-up
# deletes that block and the file returns to the upstream bytes. It is the only file this bound
# tolerates.
TEMPORARY = ".golangci.yml"


def test_the_g10_count_drops_by_the_restored_files() -> None:
    # A later slice may register and add a new upstream patch with Claude's approval; it must
    # then raise this bound in a disclosed commit, the same way it re-records the G10 baseline.
    assert len(upstream_patched_files() - {TEMPORARY}) <= G10_BEFORE - len(listed())


def test_behaviour_bearing_comment_changes_stay_patched() -> None:
    assert set(KEPT) <= upstream_patched_files()
