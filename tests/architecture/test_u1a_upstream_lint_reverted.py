"""U-1 phase (a) acceptance (protected, written by Claude): upstream files whose only reason to
differ from the pinned WeKnora base was the v0.8.2-era lint/validation sweep (appendix A class L)
or dead legacy wiring (class D) are restored to the upstream bytes before the v0.9.0 merge, so the
G10 upstream-patch count drops by exactly that many files
(Spec docs/design/slices/U-1-上游同步v0.9.0.md §3 phase a, Issue #451).

Standard library only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT, UPSTREAM_BASE, upstream_patched_files  # noqa: E402

LIST = Path(__file__).resolve().parent / "u1a_reverted_files.txt"
# G10 on main@28b69332c (after S7f-1) was 348; the list holds the files phase (a) restores.
G10_BEFORE = 348
# Appendix A L/D files that stay patched, with the reason (reclassified as X or K):
KEPT = {
    # S7f-1 behaviour-bearing comments (lint directives, swag annotations); see the S7f-1 test.
    "internal/application/repository/retriever/opensearch/repository_test.go": "nolint directive",
    "internal/container/engine_factory.go": "nolint directive",
    "internal/handler/sandbox_skill.go": "swag annotation feeding generated OpenAPI docs",
    # Hermetic SSRF test setup: upstream versions resolve real hostnames and fail behind a
    # fake-IP resolver; our versions isolate the test (upstreamable test fix).
    "internal/application/service/tenant_sandbox_config_test.go": "hermetic SSRF test setup",
    "internal/application/service/file/oss_test.go": "hermetic SSRF test setup",
    "internal/application/service/mcp_service_test.go": "hermetic SSRF test setup",
    "internal/handler/tenant_secret_disclosure_test.go": "hermetic SSRF test setup",
    # Revision-source backfill is still wired server-side (service reads this config).
    "internal/config/config.go": "KnowledgeRevisionSource config still read by the service",
    "cli/cmd/doc/doc.go": "registers the revision-source backfill commands",
    "cli/cmd/dryrun_coverage_test.go": "covers the revision-source backfill commands",
}
# A temporary, registered lint exclusion for exactly these files lives in .golangci.yml (itself an
# upstream file) until the phase (a) follow-up PR deletes it; it is the only file this bound
# tolerates.
TEMPORARY = ".golangci.yml"


def listed() -> list[str]:
    return [line.strip() for line in LIST.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_list_is_the_frozen_phase_a_scope() -> None:
    files = listed()
    assert len(files) == 178 and len(set(files)) == 178
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


def test_the_g10_count_drops_by_the_restored_files() -> None:
    # A later slice may register and add a new upstream patch with Claude's approval; it must
    # then raise this bound in a disclosed commit, the same way it re-records the G10 baseline.
    assert len(upstream_patched_files() - {TEMPORARY}) <= G10_BEFORE - len(listed())


def test_kept_files_stay_patched() -> None:
    assert set(KEPT) <= upstream_patched_files()
