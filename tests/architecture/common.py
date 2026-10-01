"""Shared repository facts for the architecture guards (blueprint 1001 §8).

Every guard works on the same classification of files:

- upstream files: present in the pinned WeKnora upstream commit;
- project-added files: tracked or untracked in the work tree but absent upstream;
- upstream-patched files: upstream files whose content differs from the pin.

Only standard library and git are used, so the guards run in any Python 3.10+.
"""

from __future__ import annotations

import functools
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD_DIR = Path(__file__).resolve().parent
BASELINE_PATH = GUARD_DIR / "baseline.json"
DOMAIN_TERMS_PATH = GUARD_DIR / "domain_terms.txt"

# WeKnora v0.8.2 fixed point adopted by PR #131. Upgrade slices move this pin
# and re-record the G10 baseline in the same PR.
UPSTREAM_BASE = "3e8b0bfc80b845b2d4b2ed683994748741450a97"

HARNESS_PKG = "harness/src/insurance_harness"
HARNESS_TESTS = "harness/tests"

# Blueprint §4.2 target directories. New Harness code may only appear here.
HARNESS_TARGET_DIRS = (
    "contracts", "catalog", "ingest", "identity", "compile", "compilers",
    "evidence", "review", "changes", "governance", "bundle", "eval",
    "jobs", "models", "service_shell",
)
# Directories that must stay free of pack-specific data and domain terms.
HARNESS_CORE_DIRS = (
    "contracts", "jobs", "models", "compile", "evidence", "review",
    "changes", "bundle", "governance",
)
GO_ENTERPRISE = "internal/enterprise"
FRONTEND_ENTERPRISE = "frontend/src/enterprise"
ENTERPRISE_MIGRATIONS = "migrations/enterprise"

CODE_SUFFIXES = (".py", ".go", ".ts", ".vue")
GENERATED_MARKERS = (".generated.", ".pb.go", "_pb2.py", ".d.ts", "/wailsjs/")
# Paths whose divergence from upstream is not counted as an upstream patch:
# CI configuration is necessarily ours and is reviewed through PRs instead.
PATCH_EXEMPT_PREFIXES = (".github/",)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    )
    return result.stdout


def require_upstream_base() -> None:
    try:
        git("cat-file", "-e", f"{UPSTREAM_BASE}^{{commit}}")
    except subprocess.CalledProcessError as exc:  # fail closed, never skip
        raise RuntimeError(
            f"upstream base {UPSTREAM_BASE} is not reachable; fetch full history "
            "(CI: actions/checkout with fetch-depth: 0)"
        ) from exc


@functools.cache
def upstream_files() -> frozenset[str]:
    require_upstream_base()
    out = git("ls-tree", "-r", "--name-only", "-z", UPSTREAM_BASE)
    return frozenset(p for p in out.split("\0") if p)


@functools.cache
def worktree_files() -> frozenset[str]:
    out = git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return frozenset(p for p in out.split("\0") if p and (REPO_ROOT / p).is_file())


@functools.cache
def project_added_files() -> frozenset[str]:
    return frozenset(worktree_files() - upstream_files())


@functools.cache
def upstream_patched_files() -> frozenset[str]:
    require_upstream_base()
    out = git("diff", "--name-only", "-z", "--diff-filter=MDT", UPSTREAM_BASE, "--")
    changed = {p for p in out.split("\0") if p}
    return frozenset(p for p in changed if not p.startswith(PATCH_EXEMPT_PREFIXES))


def is_test_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (
        name.endswith("_test.go")
        or name.startswith("test_")
        or name == "conftest.py"
        or ".test." in name
        or ".spec." in name
        or "/tests/" in f"/{path}"
        or "/__tests__/" in path
        or "/testdata/" in path
    )


def is_generated(path: str) -> bool:
    return any(marker in path for marker in GENERATED_MARKERS)


def is_handwritten_code(path: str) -> bool:
    return path.endswith(CODE_SUFFIXES) and not is_generated(path) and "/migrations/" not in f"/{path}"


def read_text(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace")


def harness_module_dir(path: str) -> str | None:
    """Top-level package directory under insurance_harness, or None."""
    prefix = HARNESS_PKG + "/"
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix):]
    return rest.split("/", 1)[0] if "/" in rest else rest.removesuffix(".py")


@functools.cache
def domain_terms() -> tuple[frozenset[str], frozenset[str]]:
    """Return (exact identifier terms, substring terms) from domain_terms.txt."""
    exact: set[str] = set()
    substrings: set[str] = set()
    for raw in DOMAIN_TERMS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        kind, _, term = line.partition(":")
        (exact if kind == "key" else substrings).add(term.strip())
    return frozenset(exact), frozenset(substrings)


def load_baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
