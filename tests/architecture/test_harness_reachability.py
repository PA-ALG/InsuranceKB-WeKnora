"""Every Harness module is reachable from a real entrypoint (blueprint 1001 §10.1, slice S7a).

A module is reachable when it is in the static import closure of the roots below. The
closure follows every import (module-level and function-local, absolute and relative) and
every string that names a module path ("insurance_harness.x.y", as used by import_module).
Importing a module also loads its parent packages.

Roots:
1. the console scripts in harness/pyproject.toml (wiki-api / wiki-worker);
2. modules Alembic loads (harness/migrations/env.py and versions/);
3. the current command-line tools in CLI_ROOTS;
4. every module in the blueprint §4.2 target directories (common.HARNESS_TARGET_DIRS).

An unreachable module must be listed in KEEP_UNREACHABLE with the slice that rewires it.
The list only shrinks: stale entries fail too. Standard library only; the package is never
imported. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from collections.abc import Collection
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import HARNESS_PKG, HARNESS_TARGET_DIRS, REPO_ROOT, worktree_files  # noqa: E402

MODULE_STRING = re.compile(r"\binsurance_harness(?:\.[A-Za-z_]\w*)+")
PYPROJECT = "harness/pyproject.toml"
ROOT_FILES = ("harness/migrations/env.py",)
ROOT_GLOBS = ("harness/migrations/versions/*.py",)
CLI_ROOTS = (
    "insurance_harness.contracts.export",
    "insurance_harness.compilers.schema_fields.publish",
    "insurance_harness.compilers.schema_fields.publish_changes",
    "insurance_harness.changes.revert",
    "insurance_harness.db.scope_cli",
)
_SI = "insurance_harness.structured_import"
_LE = "insurance_harness.live_env"
# The trusted local-live image workflow and the digest-pinned plugin contract
# (deploy/upstream/weknora-plugin-contract.yaml, node compatibility.harness_retry_scope)
# run tests/test_local_live_cli_023.py, which loads harness/scripts/local_live.py.
_LOCAL_LIVE = "本地 live 供应链：harness/scripts/local_live.py 依赖，随 local-live 镜像链路退役"
KEEP_UNREACHABLE = {
    **{
        f"{_LE}.{name}": _LOCAL_LIVE
        for name in ("compose", "local_gate", "local_provisioning", "model_probe", "provision", "space")
    },
    "insurance_harness.adapters.weknora.admin_client": _LOCAL_LIVE,
    **{
        f"{_SI}{name}": "第二期前 REWIRE → ingest/：结构化导入"
        for name in ("", ".cli", ".errors", ".mapping", ".registry", ".service", ".transformers")
    },
    "insurance_harness.product.register": "structured_import.service 依赖，随结构化导入 REWIRE",
    "insurance_harness.product.aliases": "product.register 依赖",
    "insurance_harness.product.meta": "product.register 依赖",
    # S7d-1: reachable only through the G3 product-ingestion chain until it was retired; now
    # loaded only by the kept modules above, so they stay with them and leave with them.
    **{
        f"insurance_harness.{name}": _LOCAL_LIVE
        for name in (
            "adapters", "adapters.weknora", "adapters.weknora.client", "adapters.weknora.errors",
            "adapters.weknora.models", "adapters.weknora.scope", "adapters.weknora.tracing",
            "live_env", "live_env.config",
        )
    },
    **{
        f"insurance_harness.{name}": "结构化导入依赖，随结构化导入 REWIRE"
        for name in (
            "canonical", "canonical.encoder", "canonical.errors", "canonical.hashing",
            "canonical.values", "product", "product.classify", "product.version_resolver",
            "schemas", "schemas.loader", "schemas.models",
        )
    },
    "insurance_harness.config": "本地 live 与结构化导入共同依赖，随二者退役",
}

Modules = dict[str, Path]


def harness_modules() -> Modules:
    """Dotted module name -> source path for every tracked or untracked Harness module."""
    out: Modules = {}
    for rel in worktree_files():
        if rel.startswith(HARNESS_PKG + "/") and rel.endswith(".py"):
            parts = list(Path(rel).relative_to("harness/src").with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            out[".".join(parts)] = REPO_ROOT / rel
    return out


def with_parents(name: str, known: Collection[str]) -> set[str]:
    parts = name.split(".")
    return {".".join(parts[:i]) for i in range(1, len(parts) + 1)} & set(known)


def imports(tree: ast.AST, module: str | None, is_package: bool, known: Collection[str]) -> set[str]:
    """Known modules a source tree loads: lazy imports and module-path strings included."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                if module is None:
                    continue
                parts = module.split(".") if is_package else module.split(".")[:-1]
                parts = parts[: len(parts) - (node.level - 1)]
                base = ".".join(parts + ([node.module] if node.module else []))
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.update(MODULE_STRING.findall(node.value))
    found: set[str] = set()
    for name in names:
        parts = name.split(".")
        longest = next(
            (".".join(parts[:i]) for i in range(len(parts), 0, -1) if ".".join(parts[:i]) in known),
            None,
        )
        if longest is not None:
            found |= with_parents(longest, known)
    return found


def parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def roots(modules: Modules) -> set[str]:
    project = tomllib.loads((REPO_ROOT / PYPROJECT).read_text(encoding="utf-8"))["project"]
    found = {target.split(":")[0] for target in project["scripts"].values()} | set(CLI_ROOTS)
    files = [REPO_ROOT / p for p in ROOT_FILES]
    files += sorted(path for pattern in ROOT_GLOBS for path in REPO_ROOT.glob(pattern))
    for path in files:
        found |= imports(parse(path), None, False, modules)
    found |= {m for m in modules if m.count(".") and m.split(".")[1] in HARNESS_TARGET_DIRS}
    return found


def closure(modules: Modules, start: Collection[str]) -> set[str]:
    seen: set[str] = set()
    stack = [parent for name in start for parent in with_parents(name, modules)]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        path = modules[name]
        stack.extend(imports(parse(path), name, path.name == "__init__.py", modules) - seen)
    return seen


@pytest.fixture(scope="module")
def state() -> tuple[Modules, set[str], set[str]]:
    modules = harness_modules()
    start = roots(modules)
    return modules, start, closure(modules, start)


def test_named_roots_exist(state: tuple[Modules, set[str], set[str]]) -> None:
    modules, start, _ = state
    project = tomllib.loads((REPO_ROOT / PYPROJECT).read_text(encoding="utf-8"))["project"]
    named = {target.split(":")[0] for target in project["scripts"].values()} | set(CLI_ROOTS)
    assert not named - set(modules), f"entrypoint modules missing: {sorted(named - set(modules))}"
    assert start <= set(modules) | named


def test_every_module_is_reachable_or_kept(state: tuple[Modules, set[str], set[str]]) -> None:
    modules, _, reachable = state
    unreachable = sorted(set(modules) - reachable - set(KEEP_UNREACHABLE))
    assert not unreachable, (
        f"{len(unreachable)} Harness module(s) unreachable from any entrypoint; delete them "
        "(blueprint §10.1) or wire them into a root:\n" + "\n".join(unreachable)
    )


def test_keep_list_only_shrinks(state: tuple[Modules, set[str], set[str]]) -> None:
    modules, _, reachable = state
    stale = sorted(m for m in KEEP_UNREACHABLE if m not in modules or m in reachable)
    assert not stale, "remove from KEEP_UNREACHABLE (deleted or now reachable):\n" + "\n".join(stale)


def test_resolver_follows_relative_lazy_and_string_imports() -> None:
    known = {
        "insurance_harness",
        "insurance_harness.pkg",
        "insurance_harness.pkg.a",
        "insurance_harness.pkg.b",
        "insurance_harness.pkg.sub",
        "insurance_harness.pkg.sub.c",
        "insurance_harness.other",
    }
    src = (
        "def run():\n"
        "    from .b import helper\n"
        "    from .sub import c\n"
        "    return import_module('insurance_harness.other:main')\n"
    )
    found = imports(ast.parse(src), "insurance_harness.pkg.a", False, known)
    assert found == known - {"insurance_harness.pkg.a"}
    assert imports(ast.parse("from .. import b\n"), "insurance_harness.pkg.sub", True, known) == {
        "insurance_harness",
        "insurance_harness.pkg",
        "insurance_harness.pkg.b",
    }
