"""File-level guards G2–G5, G10, G11 (blueprint 1001 §8)."""

from __future__ import annotations

import re

from common import (
    ENTERPRISE_MIGRATIONS,
    FRONTEND_ENTERPRISE,
    GO_ENTERPRISE,
    HARNESS_CORE_DIRS,
    HARNESS_PKG,
    HARNESS_TARGET_DIRS,
    HARNESS_TESTS,
    domain_terms,
    harness_module_dir,
    is_handwritten_code,
    is_test_path,
    project_added_files,
    read_text,
    upstream_patched_files,
)

MAX_LINES = 500

# G4: Goal / mission / version markers in file or directory names.
NAMING_PATTERNS = (
    re.compile(r"(?<![0-9])(?:596|728|731|815|830|1001)(?![0-9])"),
    re.compile(r"(?:^|[_\-/.])g[1-9][0-9]?(?=[_\-/.]|$)", re.IGNORECASE),
    re.compile(r"(?:^|[_\-/.])m1[0-9]{2}(?=[_\-/.]|$)", re.IGNORECASE),
    re.compile(r"[_\-]v[0-9]+(?=[_\-.]|$)", re.IGNORECASE),
)

# G5: instance data that must live in configuration, not code.
LOCAL_PATH = re.compile(r"(/Users/[^/\s\"']+|/home/[^/\s\"']+|/private/tmp/|[A-Za-z]:\\\\?Users\\)")
QUOTED_IPV4 = re.compile(r"[\"'`](?:\w+://)?((?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3})")
# Loopback, unspecified, broadcast and RFC 5737 documentation ranges are not instance data.
ALLOWED_IPV4 = re.compile(
    r"^(?:0\.0\.0\.0|127\.\d+\.\d+\.\d+|255\.255\.255\.\d+"
    r"|192\.0\.2\.\d+|198\.51\.100\.\d+|203\.0\.113\.\d+)$"
)
INSTANCE_ID = re.compile(r"(?:release|run|tenant)-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

GO_LEGACY_TERMS = re.compile(r"(?i:schema67)|\bGolden[A-Z]?\w*")


def handwritten_project_code() -> list[str]:
    return sorted(p for p in project_added_files() if is_handwritten_code(p))


def g3_file_size() -> dict[str, int]:
    sizes: dict[str, int] = {}
    for path in handwritten_project_code():
        lines = read_text(path).count("\n") + 1
        if lines > MAX_LINES:
            sizes[path] = lines
    return sizes


def naming_hit(path: str) -> bool:
    return any(pattern.search(part) for part in path.split("/") for pattern in NAMING_PATTERNS)


def g4_naming() -> dict[str, int]:
    return {p: 1 for p in handwritten_project_code() if naming_hit(p)}


def hardcoded_hits(text: str) -> int:
    hits = len(LOCAL_PATH.findall(text)) + len(INSTANCE_ID.findall(text))
    hits += sum(1 for ip in QUOTED_IPV4.findall(text) if not ALLOWED_IPV4.match(ip))
    return hits


def g5_hardcoded() -> dict[str, int]:
    out: dict[str, int] = {}
    for path in handwritten_project_code():
        if is_test_path(path):
            continue
        hits = hardcoded_hits(read_text(path))
        if hits:
            out[path] = hits
    return out


def is_core_path(path: str) -> bool:
    if path.startswith((GO_ENTERPRISE + "/", FRONTEND_ENTERPRISE + "/")):
        return True
    return harness_module_dir(path) in HARNESS_CORE_DIRS


def purity_hits(text: str) -> int:
    exact, substrings = domain_terms()
    hits = sum(text.count(term) for term in substrings)
    for literal in re.findall(r"[\"'`]([a-z][a-z0-9_]{2,})[\"'`]", text):
        if literal in exact:
            hits += 1
    return hits


def g2_core_purity() -> dict[str, int]:
    out: dict[str, int] = {}
    for path in handwritten_project_code():
        if is_test_path(path) or not is_core_path(path):
            continue
        hits = purity_hits(read_text(path))
        if hits:
            out[path] = hits
    return out


def g2_go_legacy_terms() -> dict[str, int]:
    out: dict[str, int] = {}
    candidates = (project_added_files() | upstream_patched_files())
    for path in sorted(candidates):
        if not path.endswith(".go") or is_test_path(path) or not path.startswith("internal/"):
            continue
        if path.startswith(GO_ENTERPRISE + "/"):
            continue  # enterprise code is held to zero by g2_core_purity
        try:
            hits = len(GO_LEGACY_TERMS.findall(read_text(path)))
        except FileNotFoundError:
            continue  # deleted upstream file
        if hits:
            out[path] = hits
    return out


def g10_upstream_patches() -> dict[str, int]:
    return {p: 1 for p in sorted(upstream_patched_files())}


def misplaced(path: str) -> bool:
    if path.startswith(HARNESS_PKG + "/") and path.endswith(".py"):
        return harness_module_dir(path) not in HARNESS_TARGET_DIRS
    if path.startswith(HARNESS_TESTS + "/") and path.endswith(".py"):
        rest = path[len(HARNESS_TESTS) + 1:]
        return "/" not in rest or rest.split("/", 1)[0] not in HARNESS_TARGET_DIRS
    if path.endswith(".go") and path.startswith(("internal/", "cmd/")) and not is_test_path(path):
        return not path.startswith(GO_ENTERPRISE + "/")
    if path.startswith("migrations/") and path.endswith(".sql"):
        return not path.startswith(ENTERPRISE_MIGRATIONS + "/")
    if path.startswith("frontend/src/") and path.endswith((".ts", ".vue")) and not is_test_path(path):
        return not path.startswith(FRONTEND_ENTERPRISE + "/")
    return False


def g11_new_file_location() -> dict[str, int]:
    return {p: 1 for p in sorted(project_added_files()) if misplaced(p)}


def scan() -> dict[str, dict[str, int]]:
    return {
        "G2_core_purity": g2_core_purity(),
        "G2_go_legacy_terms": g2_go_legacy_terms(),
        "G3_file_size": g3_file_size(),
        "G4_naming": g4_naming(),
        "G5_hardcoded": g5_hardcoded(),
        "G10_upstream_patches": g10_upstream_patches(),
        "G11_new_file_location": g11_new_file_location(),
    }
