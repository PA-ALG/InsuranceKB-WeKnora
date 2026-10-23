"""The Go bridge to the retired Harness product-ingestion service is gone (slice S7d-2a).

Standard library only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT  # noqa: E402

BRIDGE_FILES = (
    "internal/application/service/product_ingestion_bridge.go",
    "internal/handler/product_ingestion.go",
    "internal/handler/product_ingestion_composition.go",
    "internal/router/routes_product_ingestion.go",
)
WIRING = (
    "ProductIngestionHandler",
    "RegisterProductIngestionRoutes",
    "NewConfiguredProductIngestionHandler",
)


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_the_bridge_files_are_gone() -> None:
    assert [rel for rel in BRIDGE_FILES if (REPO_ROOT / rel).exists()] == []


def test_router_and_container_no_longer_wire_the_bridge() -> None:
    for rel in ("internal/router/router.go", "internal/container/container.go"):
        source = _read(rel)
        assert [name for name in WIRING if name in source] == [], rel


def test_the_config_keeps_no_bridge_fields() -> None:
    # S7d-2c-2b deleted the whole product-ingestion configuration, so its bridge
    # fields cannot return.
    config = REPO_ROOT / "internal/config"
    sources = [path.read_text(encoding="utf-8") for path in config.glob("*.go")]
    assert not any("type ProductIngestionConfig struct" in source for source in sources)
