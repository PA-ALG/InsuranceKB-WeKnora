"""The G3 reparse chain is gone (S7d-2c-2a).

Model-dispatch journal, DocReader recovery and bound reparse are all retired.

All three were switched on only by the G3 scope or by a bound-reparse receipt from the platform
routes deleted in S7d-2b; enterprise Spaces never used them. The capture format they wrote stays
readable, and the generic retry switch other ingest paths use stays. Standard library only.
Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT  # noqa: E402

SERVICE = "internal/application/service"
REPOSITORY = "internal/application/repository"
RETIRED = (
    f"{SERVICE}/knowledge_model_dispatch.go",
    f"{SERVICE}/knowledge_model_dispatch_test.go",
    f"{SERVICE}/g3_docreader_recovery.go",
    f"{SERVICE}/g3_docreader_recovery_test.go",
    f"{SERVICE}/g3_bound_reparse.go",
    f"{SERVICE}/g3_bound_reparse_gate.go",
    f"{SERVICE}/knowledge_process_g3_bound_reparse_test.go",
    f"{REPOSITORY}/g3_bound_reparse_test.go",
    "internal/types/g3_bound_reparse.go",
    f"{SERVICE}/g3_platform_source_snapshot_test.go",
)
TOUCHED = (
    f"{SERVICE}/knowledge_process.go",
    f"{SERVICE}/g3_first_parse.go",
    f"{SERVICE}/g3_platform_source_snapshot.go",
    f"{SERVICE}/knowledge_revision_source.go",
    f"{REPOSITORY}/knowledge.go",
    f"{REPOSITORY}/knowledge_concurrency_upgrade_test.go",
    "internal/types/task.go",
    "internal/types/interfaces/knowledge.go",
)
GONE = (
    "withG3ModelDispatchParent",
    "ensureG3ModelDispatchJournal",
    "withModelDispatchWorkerRetry",
    "selectG3DocReaderRecovery",
    "loadG3DocReaderRecovery",
    "g3BoundReparseTaskAllowed",
    "G3BoundReparseRequest",
    "G3BoundReparseRepository",
    "AllocateG3BoundReparse",
    "AdvanceG3BoundReparse",
    "product_ingestion_recoveries",
    "RecoveryKey",
    "DocReaderReuse ",
    "writeFirstParseArtifact",
    "G3PlatformSourceSnapshotService",
    "ensureCurrentCompletedForScope",
)


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_the_reparse_chain_files_are_gone() -> None:
    assert [rel for rel in RETIRED if (REPO_ROOT / rel).exists()] == []


def test_the_pipeline_no_longer_references_them() -> None:
    # A file deleted later (S7d-2c-3c) references nothing.
    for rel in (rel for rel in TOUCHED if (REPO_ROOT / rel).exists()):
        source = _read(rel)
        assert [name for name in GONE if name in source] == [], rel


def test_the_capture_format_and_the_generic_retry_switch_stay() -> None:
    assert "type DocumentDocReaderReuseReference struct" in _read("internal/types/task.go")
    assert 'json:"origin_docreader,omitempty"' in _read("internal/enterprise/capture/record.go")
    assert "func WithModelAutomaticRetryDisabled(" in _read("internal/types/model_dispatch.go")
