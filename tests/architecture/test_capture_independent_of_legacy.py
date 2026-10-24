"""First-parse capture no longer borrows from the old 830 family (S7d-2c-3b).

The capture store, its signing keys and the pipeline's native-structure check all come from
internal/enterprise/capture and the deployment signing ring, so S7d-2c-3c can delete the old family.
Standard library only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT  # noqa: E402

SERVICE = "internal/application/service"


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_the_capture_store_holds_no_legacy_type() -> None:
    source = _read(f"{SERVICE}/g3_first_parse.go")
    for name in (
        "conceptSourceReuseStore830G3",
        "SchemaWikiCitationTokenCodec",
        "NewConceptSourceAuthorityService830G2WithFirstParse",
    ):
        assert name not in source, name


def test_the_pipeline_checks_captures_with_the_capture_package() -> None:
    source = _read(f"{SERVICE}/knowledge_process.go")
    for name in (
        "prepareConceptNativeQuoteIndex830G2",
        "conceptNativeHeader830G2",
        "ErrConceptSourceAuthorityUnavailable830G2",
    ):
        assert name not in source, name
    assert "capture.ValidateNative(" in source
    assert "capture.ParserIdentitySHA256(" in source


def test_the_container_builds_capture_keys_from_the_signing_ring() -> None:
    source = _read("internal/container/container.go")
    assert "NewConceptSourceAuthorityService830G2WithFirstParse" not in source
    assert "capture.NewKeys(" in source
