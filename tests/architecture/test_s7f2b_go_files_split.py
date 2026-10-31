"""S7f-2b acceptance (protected, written by Claude): the oversized Go files are split by responsibility
(Spec docs/design/slices/S7f-2-拆分超长文件.md, section "S7f-2b 方案"; blueprint §8 G3).

``internal/application/service/knowledge_revision_source.go`` is deliberately not covered: it cannot reach
500 lines without a new Go file in an upstream package (G11) or a move into ``internal/enterprise``; the Spec
leaves it to a follow-up slice. S7f-2b2 did that move: 11 of the service tests below now live in
``internal/enterprise/revisionsource`` (see ``test_s7f2b2_revision_source_moved.py``).

Standard library only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT, project_added_files  # noqa: E402

MAX_LINES = 500
DATABASE = "internal/database"
SERVICE = "internal/application/service"
REPOSITORY = "internal/application/repository"
REVISION_SOURCE = "internal/enterprise/revisionsource"  # S7f-2b2 moved the revision-source service here
SPLIT_FILES = (
    f"{DATABASE}/legacy_w1_bridge.go",
    f"{DATABASE}/legacy_w1_bridge_test.go",
    f"{SERVICE}/knowledge_revision_source_test.go",
    f"{REPOSITORY}/knowledge_revision_test.go",
)
CATALOG_SQL = f"{DATABASE}/catalogsql"

# Test functions of the three original test files (main@996f3826a); each must survive the move.
MOVED_TESTS = {
    DATABASE: (
        "TestLegacyW1FixtureExactBytes",
        "TestRuntimeOfficialMigrationHeadMatchesAdoptionManifest",
        "TestClassifyLegacyW1Origin",
        "TestClassifyLegacyW1OriginAllowsPackagedUpgradeResumeCheckpoints",
        "TestAcquireLegacyW1MigrationGuardRejectsDirtyBeforeLockOrWrite",
        "TestAcquireLegacyW1MigrationGuardReturnsTypedSafetyErrorOnInspectionFailure",
        "TestAcquireLegacyW1MigrationGuardRejectsUnknownBeforeLockOrWrite",
        "TestAcquireLegacyW1MigrationGuardRejectsLockedSnapshotDriftWithoutWrite",
        "TestAcquireLegacyW1MigrationGuardConvergesOnlyExactLegacy66",
        "TestAcquireLegacyW1MigrationGuardHoldsFullCurrentLockWithoutConvergenceWrites",
        "TestLegacyW1MigrationGuardReleaseUsesCleanupContextAndRejectsFalse",
        "TestAcquireLegacyW1MigrationGuardDiscardsConnectionWhenLockStateIsUnknown",
        "TestLegacyW1MigrationGuardReleaseDiscardsConnectionWhenUnlockStateIsUnknown",
        "TestInspectOfficialMigrationLedger",
        "TestInspectEnterpriseMigrationLedgerUsesIndependentTable",
        "TestMigrationLedgerShapeSQLPinsExactConstraintInventory",
        "TestInspectSpanNameFingerprint",
        "TestInspectLegacyW1Fingerprint",
        "TestLegacyW1FingerprintSQLPinsEveryLegacyObjectDefinition",
        "TestFixedCatalogFingerprintSQLPinsStructuralExactness",
        "TestLegacyW1FingerprintSQLPinsExactRevisionConstraintInventory",
        "TestInspectDependencyAnchorFingerprint",
        "TestDependencyAnchorFingerprintSQLPinsOnlyW1Dependencies",
        "TestClassifyLegacyW1OriginRequiresDependencyAnchorsAtKnownCheckpoints",
        "TestRunPostgresMigrationPhasesOrdersPreflightOfficialEnterpriseRelease",
        "TestRunPostgresMigrationPhasesStopsAfterOfficialFailureAndReleases",
        "TestRunPostgresMigrationPhasesDoesNotLoseReleaseError",
        "TestEnterpriseMigrationDSNUsesIndependentLedger",
        "TestValidatePostgresMigrationSetVersionRequiresFrozenHeads",
        "TestEnterpriseFailureDoesNotOverwriteOfficialMigrationCache",
        "TestPostgresLegacyW1MigrationMatrix",
        "TestPostgresEmbeddingsForwardRepair",
    ),
    SERVICE: (
        "TestPinnedRevisionSourceBlocksKnowledgeDeleteBeforeMutation",
        "TestPinnedRevisionSourceBlocksDirectReparseBeforeAnyMutation",
    ),
    REVISION_SOURCE: (
        "TestRevisionSourceUsesStoredBackendForBackfill",
        "TestRevisionSourceStoredBackendFailureNeverReadsDefault",
        "TestBackfillKnowledgeRevisionSourceRequiresHumanAdminBeforeAuthorityReads",
        "TestBackfillKnowledgeRevisionSourceUsesOnlyCurrentCompletedAttemptAndRecomputesObject",
        "TestImmutablePDFPageCounterAcceptsExact5961EncryptedMaterials",
        "TestImmutablePDFPageCounterRejectsCorruptExactObject",
        "TestBackfillKnowledgeRevisionSourceRejectsZeroStaleAndMissingRevisionBeforeObjectRead",
        "TestExact3BackfillPreflightsAllSourcesBeforeStrictSerialSeal",
        "TestExact3DryRunClassifiesExactExistingRowsAndStopsOnConflict",
    ),
    REPOSITORY: (
        "TestAllocateParseAttemptCommitsPendingBeforeAnyChunkDestruction",
        "TestAllocateParseAttemptSerializesConcurrentReparse",
        "TestAllocateParseAttemptFailurePreservesCurrentRevisionAndChunks",
        "TestCommitDirectRevisionIsAtomicAndFenced",
        "TestCommitDirectRevisionRejectsResourceDigestOrBindingDriftWithoutPartialWrite",
        "TestSealRevisionSourcePageCountIsExactIdempotentWriteOnce",
        "TestSealRevisionSourceBindingReplaysExactSQLiteAuthoritiesAndIsWriteOnce",
        "TestKnowledgeDeletePathsAtomicallyRejectPinnedRevisionSources",
        "TestCommitDirectRevisionRejectsStaleAttemptWithoutPartialWrite",
        "TestFailedAndCancelledAttemptsNeverCommitRevision",
        "TestExact3AuthorityReadsAllRowsInsideOneReadOnlySnapshot",
        "TestFinalizeSubtaskRevisionCommitsOnLastSlotInSameTransaction",
        "TestFinalizeSubtaskRevisionRollsBackCounterWhenManifestInvalid",
        "TestGetRevisionStateAndChunksRemainAttemptBound",
        "TestGetRevisionStateReturnsSoftDeletedTombstone",
        "TestCommittedManifestRemainsImmutableWhenChunkContentDrifts",
    ),
}

EMBED = re.compile(r"^//go:embed\s+(\S+)\s*$", re.MULTILINE)


def tracked(*paths: str) -> list[str]:
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files", "-z", "--", *paths],
        cwd=REPO_ROOT, check=True, capture_output=True,
    ).stdout.decode("utf-8")
    return [p for p in out.split("\0") if p]


def line_count(path: str) -> int:
    return (REPO_ROOT / path).read_text(encoding="utf-8").count("\n") + 1


def go_files(directory: str) -> list[str]:
    return [p for p in tracked(directory) if p.endswith(".go") and "/" not in p[len(directory) + 1:]]


def test_split_files_are_within_the_line_limit() -> None:
    over = {p: line_count(p) for p in SPLIT_FILES if (REPO_ROOT / p).exists() and line_count(p) > MAX_LINES}
    assert over == {}


def test_no_project_go_file_in_the_database_package_exceeds_the_limit() -> None:
    ours = project_added_files()  # upstream files are outside G3, e.g. migration_sqlite_versioned_schema_test.go
    over = {p: line_count(p) for p in go_files(DATABASE) if p in ours and line_count(p) > MAX_LINES}
    assert over == {}


def test_every_moved_test_is_defined_exactly_once_in_its_package() -> None:
    problems = []
    for directory, names in MOVED_TESTS.items():
        sources = [
            (REPO_ROOT / p).read_text(encoding="utf-8") for p in go_files(directory) if p.endswith("_test.go")
        ]
        for name in names:
            pattern = re.compile(rf"^func {name}\(t \*testing\.T\) \{{", re.MULTILINE)
            found = sum(len(pattern.findall(text)) for text in sources)
            if found != 1:
                problems.append(f"{directory}: {name} defined {found} times")
    assert problems == []


def test_catalog_sql_files_are_all_embedded() -> None:
    sql_files = sorted(p for p in tracked(CATALOG_SQL) if p.endswith(".sql"))
    assert sql_files, "the fixed catalog fingerprint queries move to catalogsql/*.sql"
    embedded = set()
    for path in go_files(DATABASE):
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        embedded.update(f"{DATABASE}/{target}" for target in EMBED.findall(text))
    assert [p for p in sql_files if p not in embedded] == []
    assert sorted(p for p in embedded if p.startswith(CATALOG_SQL + "/")) == sql_files
