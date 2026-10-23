"""The 007-era Harness knowledge chain is gone; only what Alembic loads remains (slice S7c).

knowledge/__init__.py re-exported the whole chain, which kept it reachable through Alembic's
import of the tables. Without the re-exports the package holds the tables and their DDL only.
Standard library only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import HARNESS_PKG, REPO_ROOT  # noqa: E402

KNOWLEDGE = REPO_ROOT / HARNESS_PKG / "knowledge"
KEPT = {"__init__.py", "tables.py", "release_guard_ddl_018.py"}


def test_the_package_re_exports_nothing() -> None:
    tree = ast.parse((KNOWLEDGE / "__init__.py").read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert imports == []


def test_only_the_alembic_tables_remain() -> None:
    present = {path.name for path in KNOWLEDGE.iterdir() if path.name != "__pycache__"}
    assert present == KEPT


def test_alembic_still_names_the_kept_modules() -> None:
    env = (REPO_ROOT / "harness/migrations/env.py").read_text(encoding="utf-8")
    assert "from insurance_harness.knowledge import tables" in env
    versions = REPO_ROOT / "harness/migrations/versions"
    ddl = "insurance_harness.knowledge.release_guard_ddl_018"
    named = [p.name for p in versions.glob("*.py") if ddl in p.read_text(encoding="utf-8")]
    assert named, "a migration must still load the release guard DDL"
