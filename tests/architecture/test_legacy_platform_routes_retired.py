"""The G3 platform routes and the code only they used are gone (slice S7d-2b).

Their only caller was the Harness product-ingestion client retired in S7d-1. Standard library
only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT  # noqa: E402

SERVICE = "internal/application/service"
RETIRED = (
    "internal/router/routes_g3_platform_snapshots.go",
    "internal/router/routes_g3_platform_release.go",
    "internal/handler/g3_platform_composition.go",
    "internal/handler/g3_platform_native_discovery.go",
    "internal/handler/g3_platform_release.go",
    "internal/handler/g3_platform_snapshots.go",
    f"{SERVICE}/g3_platform_base_snapshot.go",
    f"{SERVICE}/g3_platform_candidate_transfer.go",
    f"{SERVICE}/g3_platform_machine_access.go",
    f"{SERVICE}/g3_platform_snapshot_signer.go",
    f"{SERVICE}/g3_native_discovery.go",
    f"{SERVICE}/system_policy_decision.go",
    f"{SERVICE}/wiki_release_automated.go",
    "internal/types/g3_platform_candidate_transfer.go",
)
WIRING = (
    "G3PlatformSnapshotsHandler",
    "G3PlatformReleaseHandler",
    "registerConfiguredG3PlatformRoutes",
    "ConfiguredG3PlatformSystemOptions",
    "NewConfiguredG3PlatformHandlers",
)


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_the_routes_and_the_code_only_they_used_are_gone() -> None:
    assert [rel for rel in RETIRED if (REPO_ROOT / rel).exists()] == []


def test_router_and_container_no_longer_wire_them() -> None:
    for rel in ("internal/router/router.go", "internal/container/container.go"):
        source = _read(rel)
        assert [name for name in WIRING if name in source] == [], rel


def test_the_release_service_drops_the_automation_policy() -> None:
    # S7d-2c-3c deleted the old release service altogether.
    assert not (REPO_ROOT / SERVICE / "wiki_release.go").exists()


def test_the_snapshot_helpers_went_with_the_830_family() -> None:
    # Enterprise capture stopped using them in S7d-2c-3b; S7d-2c-3c deleted them.
    assert not (REPO_ROOT / SERVICE / "g3_platform_source_snapshot.go").exists()
