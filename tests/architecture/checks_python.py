"""Python AST guards: G1 dependency direction and G6 private access (blueprint §8)."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from common import (
    HARNESS_CORE_DIRS,
    HARNESS_PKG,
    HARNESS_TARGET_DIRS,
    REPO_ROOT,
    harness_module_dir,
    project_added_files,
    read_text,
)

ROOT_PKG = "insurance_harness"
SRC_ROOT = REPO_ROOT / "harness" / "src"


def harness_sources() -> list[str]:
    return sorted(p for p in project_added_files() if p.startswith(HARNESS_PKG + "/") and p.endswith(".py"))


def module_name(path: str) -> tuple[str, bool]:
    """Dotted module name for a harness source path and whether it is a package."""
    rel = Path(path).relative_to("harness/src").with_suffix("")
    parts = list(rel.parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ".".join(parts), is_package


def resolve_from(node: ast.ImportFrom, path: str) -> str | None:
    if node.level == 0:
        return node.module
    module, is_package = module_name(path)
    base = module.split(".") if is_package else module.split(".")[:-1]
    if node.level - 1 > len(base):
        return None
    base = base[: len(base) - (node.level - 1)]
    return ".".join(base + ([node.module] if node.module else []))


def is_module(dotted: str) -> bool:
    candidate = SRC_ROOT.joinpath(*dotted.split("."))
    return candidate.with_suffix(".py").is_file() or (candidate / "__init__.py").is_file()


def top_dir(dotted: str) -> str | None:
    parts = dotted.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == ROOT_PKG else None


def imported_modules(tree: ast.AST, path: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            target = resolve_from(node, path)
            if target:
                found.append(target)
    return [m for m in found if m == ROOT_PKG or m.startswith(ROOT_PKG + ".")]


def dependency_violations(path: str, tree: ast.AST) -> Counter[str]:
    """G1: new directories never import old ones; core never imports compilers."""
    here = harness_module_dir(path)
    out: Counter[str] = Counter()
    if here not in HARNESS_TARGET_DIRS:
        return out
    for target in imported_modules(tree, path):
        dest = top_dir(target)
        if dest is None or dest == here:
            continue
        if dest not in HARNESS_TARGET_DIRS:
            out[f"{path} -> {dest}"] += 1
        elif here in HARNESS_CORE_DIRS and dest == "compilers":
            out[f"{path} -> {dest}"] += 1
    return out


def private_access_count(path: str, tree: ast.AST) -> int:
    """G6: cross-module private names and test hooks in production code."""
    count = 0
    module_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            target = resolve_from(node, path)
            if not target or not (target == ROOT_PKG or target.startswith(ROOT_PKG + ".")):
                continue
            for alias in node.names:
                if alias.name.startswith("_") and not alias.name.startswith("__"):
                    count += 1
                elif is_module(f"{target}.{alias.name}"):
                    module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(ROOT_PKG + ".") and alias.asname:
                    module_aliases.add(alias.asname)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "_for_test" in node.name:
            count += 1
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in module_aliases
            and node.attr.startswith("_")
            and not node.attr.startswith("__")
        ):
            count += 1
    return count


def scan() -> dict[str, dict[str, int]]:
    g1: Counter[str] = Counter()
    g6: dict[str, int] = {}
    for path in harness_sources():
        tree = ast.parse(read_text(path), filename=path)
        g1.update(dependency_violations(path, tree))
        hits = private_access_count(path, tree)
        if hits:
            g6[path] = hits
    return {"G1_dependency_direction": dict(g1), "G6_private_access": g6}
