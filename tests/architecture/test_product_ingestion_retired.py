"""The G3 product-ingestion chain is retired from the Harness (slice S7d-1).

The service shell no longer composes product ingestion, its deployment is gone, the package
keeps only the tables Alembic loads, the packages that chain kept reachable are deleted, and
the three kept legacy tools no longer pull that chain in. Standard library only. Run from the
repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import HARNESS_PKG, REPO_ROOT  # noqa: E402

PKG = REPO_ROOT / HARNESS_PKG
RETIRED_PACKAGES = (
    "compiler",
    "goldenset",
    "model_policy",
    "run_admission",
    "knowledge_compiler",
    "sources",
    "template_packages",
)


def _loaded_modules(path: Path) -> set[str]:
    """Every module a file names: imports at any depth and module-path strings."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
    return names


def _names(path: Path, prefix: str) -> list[str]:
    return sorted(name for name in _loaded_modules(path) if name.startswith(prefix))


def test_the_deployment_is_gone() -> None:
    assert not (REPO_ROOT / "deploy/product-ingestion").exists()


def test_the_service_shell_never_loads_product_ingestion() -> None:
    for path in sorted((PKG / "service_shell").glob("*.py")):
        assert _names(path, "insurance_harness.product_ingestion") == [], path.name


def test_only_the_alembic_tables_remain() -> None:
    package = PKG / "product_ingestion"
    present = {path.name for path in package.iterdir() if path.name != "__pycache__"}
    assert present == {"__init__.py", "tables.py", "artifact_tables.py"}


def test_the_packages_the_chain_kept_alive_are_deleted() -> None:
    assert [name for name in RETIRED_PACKAGES if (PKG / name).exists()] == []


def test_the_kept_legacy_tools_no_longer_pull_the_chain_in() -> None:
    assert _names(PKG / "live_env/model_probe.py", "insurance_harness.compiler") == []
    assert _names(PKG / "product/classify.py", "insurance_harness.goldenset") == []
    config = _loaded_modules(PKG / "config.py")
    assert not [name for name in config if "model_policy" in name]
