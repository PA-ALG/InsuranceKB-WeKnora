"""S7f-2c2 acceptance (protected, written by Claude): the last oversized scripts are split or registered
(Spec docs/design/slices/S7f-2-拆分超长文件.md, section "S7f-2c2 收尾"; blueprint §8 G3, §11 S7).

``harness/scripts/prepare_weknora_adoption.py`` is split by responsibility inside the ``scripts`` package; the
names tests monkeypatch on it stay defined there. Eight files stay over 500 lines as registered exceptions with a
reason and an exit condition; ``internal/application/service/knowledge_revision_source.go`` was left to S7f-2b2,
which moved it into ``internal/enterprise/revisionsource``, so G3 now holds only the registered exceptions.

Standard library only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import checks_files  # noqa: E402
from common import REPO_ROOT  # noqa: E402

MAX_LINES = 500
SCRIPTS = "harness/scripts"
ENTRY = f"{SCRIPTS}/prepare_weknora_adoption.py"
SPLIT_MODULES = tuple(
    f"{SCRIPTS}/{name}.py"
    for name in (
        "adoption_validation",
        "adoption_target",
        "adoption_discovery",
        "plugin_contract_model",
        "plugin_contract_access",
        "plugin_contract_endpoints",
        "plugin_contract_policies",
        "plugin_contract_document",
    )
)
# Defined (not imported) in the entry module: tests patch or call them there.
ENTRY_DEFINITIONS = {
    "PLUGIN_CONTRACT_SCHEMA_V1_SHA256",
    "load_plugin_contract",
    "run_adoption_check",
    "_run_git",
    "_official_migrations",
    "_load_w1_paths",
    "_load_runtime_source_lock",
    "_canonical_semantic_json",
    "main",
}
REGISTERED_EXCEPTIONS = {
    "harness/src/insurance_harness/adapters/weknora/admin_client.py",
    "harness/src/insurance_harness/live_env/local_provisioning.py",
    "harness/src/insurance_harness/live_env/compose.py",
    "harness/scripts/local_live.py",
    "harness/src/insurance_harness/knowledge/tables.py",
    "harness/src/insurance_harness/product/version_resolver.py",
    "scripts/app_artifact.py",
    "scripts/start_exact_image.py",
}
MOVED_BY_S7F2B2 = "internal/application/service/knowledge_revision_source.go"
SPEC = "docs/design/slices/S7f-2-拆分超长文件.md"
EXCEPTION_HEADING = "### 登记的例外"


def _lines(path: str) -> int:
    return (REPO_ROOT / path).read_text(encoding="utf-8").count("\n") + 1


def _tree(path: str) -> ast.Module:
    return ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"), filename=path)


def _top_level_definitions(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_adoption_entry_and_split_modules_are_within_the_limit() -> None:
    too_long = {path: _lines(path) for path in (ENTRY, *SPLIT_MODULES) if _lines(path) > MAX_LINES}
    assert not too_long, f"over {MAX_LINES} lines: {too_long}"


def test_entry_module_keeps_the_patched_names_and_both_commands() -> None:
    tree = _tree(ENTRY)
    missing = ENTRY_DEFINITIONS - _top_level_definitions(tree)
    assert not missing, f"must stay defined in {ENTRY}: {sorted(missing)}"
    commands = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_parser"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }
    assert commands == {"check", "discover"}


def test_split_modules_share_no_private_names() -> None:
    private: list[str] = []
    for path in (ENTRY, *SPLIT_MODULES):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("scripts."):
                private.extend(
                    f"{path}: {node.module}.{alias.name}"
                    for alias in node.names
                    if alias.name.startswith("_")
                )
    assert not private, private


def test_g3_holds_only_registered_exceptions() -> None:
    assert not (REPO_ROOT / MOVED_BY_S7F2B2).exists()
    assert set(checks_files.g3_file_size()) == REGISTERED_EXCEPTIONS


def test_every_exception_has_a_reason_and_an_exit_condition() -> None:
    text = (REPO_ROOT / SPEC).read_text(encoding="utf-8")
    assert EXCEPTION_HEADING in text, f"{SPEC} lacks the exception table"
    section = text.split(EXCEPTION_HEADING, 1)[1].split("\n### ", 1)[0]
    rows: dict[str, list[str]] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0].startswith("`") and cells[0].endswith("`"):
            rows[cells[0].strip("`")] = cells[1:]
    assert set(rows) == REGISTERED_EXCEPTIONS
    for path, (lines, reason, exit_condition) in rows.items():
        assert lines.isdigit(), path
        assert reason and exit_condition, path
