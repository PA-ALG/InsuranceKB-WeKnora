"""S7f-2b2 acceptance (protected, written by Claude): the revision-source service moves out of the upstream
``service`` package into ``internal/enterprise/revisionsource`` (Spec docs/design/slices/S7f-2-拆分超长文件.md,
section "S7f-2b2 方案"; blueprint §8 G3/G11). The pinned-source guards stay in ``service`` because upstream
service files call them.

Standard library only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT, is_test_path, upstream_files  # noqa: E402

MAX_LINES = 500
SERVICE = "internal/application/service"
PACKAGE = "internal/enterprise/revisionsource"
OLD_FILE = f"{SERVICE}/knowledge_revision_source.go"
IMPORT_PATH = "github.com/Tencent/WeKnora/" + PACKAGE
SERVICE_IMPORT = "github.com/Tencent/WeKnora/" + SERVICE

# Exported declarations of the moved service (names unchanged by the move).
MOVED_DECLARATIONS = (
    r"type KnowledgeRevisionSourceService struct",
    r"func NewKnowledgeRevisionSourceService\(",
    r"type KnowledgeRevisionSourceExact3RequestV1 struct",
    r"type KnowledgeRevisionSourceExact3ResultV1 struct",
    r"type KnowledgeRevisionSourceExact3Error struct",
    r"(?:var |const )?ErrRevisionSourceMismatch\s+=",
    r"(?:var |const )?ErrRevisionSourcePageUnavailable\s+=",
    r"(?:var |const )?ErrRevisionSourceBackfillDisabled\s+=",
    r"(?:var |const )?ErrRevisionSourceExact3Conflict\s+=",
    r"(?:var |const )?KnowledgeRevisionSourceExact3ContractV1\s+=",
)
# Called from upstream service files; they stay in the service package.
SERVICE_GUARDS = (
    r"(?:var |const )?ErrKnowledgeRevisionSourcePinned\s+=",
    r"func requireKnowledgeRevisionSourceDeleteAllowed\(",
    r"func requireKnowledgeRevisionSourceReparseAllowed\(",
)
TESTS = {
    PACKAGE: (
        "TestRevisionSourceUsesStoredBackendForBackfillAndFixedRead",
        "TestRevisionSourceStoredBackendFailureNeverReadsDefault",
        "TestBackfillKnowledgeRevisionSourceRequiresHumanAdminBeforeAuthorityReads",
        "TestBackfillKnowledgeRevisionSourceUsesOnlyCurrentCompletedAttemptAndRecomputesObject",
        "TestImmutablePDFPageCounterAcceptsExact5961EncryptedMaterials",
        "TestImmutablePDFPageCounterRejectsCorruptExactObject",
        "TestBackfillKnowledgeRevisionSourceRejectsZeroStaleAndMissingRevisionBeforeObjectRead",
        "TestReadFixedRevisionSourceRejectsBindingAndPageDriftBeforeBytes",
        "TestReadFixedRevisionSourceReturnsOnlyExactPinnedObject",
        "TestExact3BackfillPreflightsAllSourcesBeforeStrictSerialSeal",
        "TestExact3DryRunClassifiesExactExistingRowsAndStopsOnConflict",
    ),
    SERVICE: (
        "TestPinnedRevisionSourceBlocksKnowledgeDeleteBeforeMutation",
        "TestPinnedRevisionSourceBlocksDirectReparseBeforeAnyMutation",
    ),
}
# The only upstream file allowed to import the new package (dependency wiring).
UPSTREAM_IMPORTERS = ("internal/container/container.go",)


def tracked(*paths: str) -> list[str]:
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files", "-z", "--", *paths],
        cwd=REPO_ROOT, check=True, capture_output=True,
    ).stdout.decode("utf-8")
    return [p for p in out.split("\0") if p and (REPO_ROOT / p).exists()]


def text(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def go_files(directory: str) -> list[str]:
    return [p for p in tracked(directory) if p.endswith(".go") and "/" not in p[len(directory) + 1:]]


def count(pattern: str, paths: list[str]) -> int:
    compiled = re.compile(rf"^\s*{pattern}", re.MULTILINE)
    return sum(len(compiled.findall(text(p))) for p in paths)


def test_old_file_is_gone_and_new_files_are_within_the_limit() -> None:
    assert not (REPO_ROOT / OLD_FILE).exists()
    files = go_files(PACKAGE)
    assert [p for p in files if not is_test_path(p)], "the service moves into the new package"
    over = {p: text(p).count("\n") + 1 for p in files if text(p).count("\n") + 1 > MAX_LINES}
    assert over == {}


def test_moved_declarations_live_only_in_the_new_package() -> None:
    package = [p for p in go_files(PACKAGE) if not is_test_path(p)]
    elsewhere = [
        p for p in tracked("internal")
        if p.endswith(".go") and not is_test_path(p) and not p.startswith(PACKAGE + "/")
    ]
    problems = []
    for pattern in MOVED_DECLARATIONS:
        inside, outside = count(pattern, package), count(pattern, elsewhere)
        if inside != 1 or outside != 0:
            problems.append(f"{pattern}: {inside} in {PACKAGE}, {outside} elsewhere")
    assert problems == []


def test_new_package_does_not_import_the_upstream_service_package() -> None:
    offenders = [p for p in go_files(PACKAGE) if f'"{SERVICE_IMPORT}"' in text(p)]
    assert offenders == []


def test_pinned_source_guards_stay_in_the_service_package() -> None:
    service = [p for p in go_files(SERVICE) if not is_test_path(p)]
    assert {pattern: count(pattern, service) for pattern in SERVICE_GUARDS} == dict.fromkeys(SERVICE_GUARDS, 1)


def test_every_moved_test_is_defined_exactly_once_in_its_package() -> None:
    problems = []
    for directory, names in TESTS.items():
        tests = [p for p in go_files(directory) if p.endswith("_test.go")]
        for name in names:
            found = count(rf"func {name}\(t \*testing\.T\) \{{", tests)
            if found != 1:
                problems.append(f"{directory}: {name} defined {found} times")
    assert problems == []


def test_only_the_container_wiring_imports_the_new_package_among_upstream_files() -> None:
    upstream = upstream_files()
    importers = sorted(
        p for p in tracked("internal", "cmd")
        if p.endswith(".go") and p in upstream and f'"{IMPORT_PATH}"' in text(p)
    )
    assert importers == list(UPSTREAM_IMPORTERS)
