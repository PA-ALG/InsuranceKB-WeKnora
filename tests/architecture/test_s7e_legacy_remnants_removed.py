"""S7e-1 acceptance (protected, written by Claude): the dead remnants of the 830 / G3 families are
gone and the behaviour still in use stays (Spec docs/design/slices/S7e-1-清理旧830残留代码.md §3).

Standard library only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT  # noqa: E402

DISPATCH_NAMES = (
    "ModelDispatchRecorder",
    "ModelDispatchReservation",
    "ModelDispatchSpec",
    "ModelDispatchResult",
    "ReserveModelDispatch",
    "WithModelDispatchRecorder",
    "ErrModelDispatchJournalUnavailable",
    "WithDispatchAttempt",
    "DispatchOperation",
)
RELEASE_METHODS = (
    "CreateDraft",
    "requireDraftExpectedHead",
    "CreateReadyPreparation",
    "GetReadyPreparation",
    "GetReadyPreparationMetadata",
    "GetDraftPreparation",
    "ReviewDraft",
    "Revert",
    "GetHead",
    "GetReleaseByPreparation",
    "GetPreparationScopeForWikiKB",
    "CountState",
)
DEAD_TYPES = (
    "WikiReleaseRevertWrite",
    "WikiReleaseStateCount",
    "WikiReleasePreparationDraft",
    "LiveRevisionSourceReceiptV1",
    "ComputeLiveRevisionSourceReceiptSHA256",
    "ValidateLiveRevisionSourceReceiptV1",
    "PublishAuthorizationV0",
    "HumanBatchDecisionReceiptV1",
    "WikiReleasePrincipal",
    "WikiReleaseCurrent",
)
PRISTINE = ("internal/models/runtime/connection.go", "config/config.yaml")


def go_sources() -> dict[str, str]:
    return {
        str(path.relative_to(REPO_ROOT)): path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "internal").rglob("*.go")
    }


def read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_the_dispatch_journal_is_gone_from_every_go_file() -> None:
    assert not (REPO_ROOT / "internal/models/api/model_dispatch.go").exists()
    found = {
        (path, name)
        for path, text in go_sources().items()
        for name in DISPATCH_NAMES
        if re.search(rf"\b{name}\b", text)
    }
    assert found == set()


def test_the_automatic_retry_switch_and_its_redirect_guard_stay() -> None:
    switch = read("internal/types/model_dispatch.go")
    assert "func WithModelAutomaticRetryDisabled(" in switch
    assert "func ModelAutomaticRetryDisabled(" in switch
    assert "types.WithModelAutomaticRetryDisabled(" in read(
        "internal/application/service/wiki_ingest.go"
    )
    endpoint = read("internal/models/api/endpoint.go")
    assert "http.ErrUseLastResponse" in endpoint
    assert "ModelAutomaticRetryDisabled(" in endpoint


def test_files_whose_only_patch_was_the_remnant_match_upstream() -> None:
    upstream = json.loads(read("tests/architecture/baseline.json"))["upstream_base"]
    for relative in PRISTINE:
        original = subprocess.run(
            ["git", "show", f"{upstream}:{relative}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
        assert (REPO_ROOT / relative).read_bytes() == original, relative


def test_the_unused_release_methods_and_types_are_gone() -> None:
    release = read("internal/application/repository/wiki_release.go")
    defined = {
        name
        for name in RELEASE_METHODS
        if re.search(rf"^func (\([^)]*\) )?{name}\(", release, re.MULTILINE)
    }
    assert defined == set()
    declared = {
        (path, name)
        for path, text in go_sources().items()
        for name in DEAD_TYPES
        if re.search(rf"^(type|func|const|var)?\s*{name}\b", text, re.MULTILINE)
        or re.search(rf"\b{name}\b", text)
    }
    assert declared == set()
    assert "Provide(repository.NewWikiReleaseRepository)" not in read(
        "internal/container/container.go"
    )


def test_the_retired_configuration_key_is_gone() -> None:
    for relative in (
        "README.md",
        *(str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "config").rglob("*")),
    ):
        path = REPO_ROOT / relative
        if path.is_file():
            assert "schema_wiki_frozen_release_scope" not in path.read_text(
                encoding="utf-8", errors="ignore"
            ), relative
