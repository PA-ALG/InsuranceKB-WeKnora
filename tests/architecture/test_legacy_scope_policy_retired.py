"""The G3 scope configuration and the native-candidates write policy are gone (S7d-2c-2b).

After S7d-2c-2a only the G3 scope itself was left: two configuration sections and the few switches
that read them. Enterprise Spaces use none of them; first-parse capture is decided by the enterprise
capture scope alone, and the capture parser settings live in internal/enterprise/capture.
Standard library only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT  # noqa: E402

SERVICE = "internal/application/service"
RELEASESTORE = "internal/enterprise/releasestore"
RETIRED = (
    "internal/config/g3_platform_processing.go",
    "internal/config/g3_platform_processing_test.go",
    "internal/config/product_ingestion.go",
    "internal/config/product_ingestion_native_test.go",
    f"{SERVICE}/native_wiki_policy_test.go",
)
TOUCHED = (
    "internal/config/config.go",
    f"{SERVICE}/knowledge_process.go",
    f"{SERVICE}/knowledge_post_process.go",
    f"{SERVICE}/wiki_ingest_batch.go",
    f"{SERVICE}/g3_first_parse.go",
    "internal/container/recover_pending_wiki_tasks.go",
    "internal/router/router.go",
    f"{RELEASESTORE}/production.go",
    f"{RELEASESTORE}/spaces.go",
)
GONE = (
    "G3PlatformProcessing",
    "ProductIngestion",
    "NativeWikiWritesDisabled",
    "NativeCandidatesPolicy",
    "DecodeG3PlatformProcessing",
    "g3FirstParseScope",
    "g3FirstParseConfig",
    "reservedScopes",
)


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_the_scope_and_policy_files_are_gone() -> None:
    assert [rel for rel in RETIRED if (REPO_ROOT / rel).exists()] == []


def test_nothing_reads_the_g3_scope_or_the_write_policy() -> None:
    for rel in TOUCHED:
        source = _read(rel)
        assert [name for name in GONE if name in source] == [], rel


def test_capture_is_decided_by_the_enterprise_scope_with_its_own_parser_settings() -> None:
    process = _read(f"{SERVICE}/knowledge_process.go")
    assert "conceptNativeCapture830G2" not in process
    assert "capture.ParserConfig(" in process
    assert "s.captureScope.RawKB(" in process
    package = "\n".join(path.read_text(encoding="utf-8")
                        for path in (REPO_ROOT / "internal/enterprise/capture").glob("*.go"))
    assert "func ParserConfig(" in package
