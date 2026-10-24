"""The SchemaPack field catalog lives in the Harness (S7d-2c-3d-1).

Insurance schemas belong to the Harness only (blueprint §4.2). The catalog moves byte for byte out
of the Go handler directory, and every Harness module reaches it through one constant.
Standard library only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT  # noqa: E402

OLD = "internal/handler/schema_pack_catalog_830_g3.generated.json"
NEW = "harness/src/insurance_harness/catalog/schema_packs.json"
SHA256 = "0d5ed6a5789362f1c72ebad5bbc47a64e1d71bc122890da96d976ec01256a3f9"
READERS = ("harness/src", "harness/tests", "tests/acceptance", "dataset")
CONSTANT_HOME = "harness/src/insurance_harness/catalog/__init__.py"


def _files(root: str) -> list[Path]:
    base = REPO_ROOT / root
    return [path for path in base.rglob("*") if path.is_file() and "__pycache__" not in path.parts]


def _mentions(root: str, needle: str) -> list[str]:
    found = []
    for path in _files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if needle in text:
            found.append(path.relative_to(REPO_ROOT).as_posix())
    return sorted(found)


def test_the_go_copy_is_gone() -> None:
    assert not (REPO_ROOT / OLD).exists()


def test_the_harness_copy_is_byte_identical() -> None:
    assert hashlib.sha256((REPO_ROOT / NEW).read_bytes()).hexdigest() == SHA256


def test_nothing_reads_the_old_location() -> None:
    stale = [rel for root in READERS for rel in _mentions(root, "internal/handler/schema_pack_catalog")]
    assert stale == []


def test_only_the_catalog_package_names_the_file() -> None:
    named = [rel for rel in _mentions("harness/src", "schema_packs.json") if rel.endswith(".py")]
    assert named == [CONSTANT_HOME]
