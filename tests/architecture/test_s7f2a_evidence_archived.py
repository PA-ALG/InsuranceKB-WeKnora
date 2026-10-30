"""S7f-2a acceptance (protected, written by Claude): the 830 evidence directory leaves the repository
(Spec docs/design/slices/S7f-2-拆分超长文件.md, row S7f-2a; blueprint §11 S7 "evidence 目录移出").

It is archived as the pushed tag ``archive/pre-s7f2a-evidence-20261030`` plus a tarball outside the
repository. Code, tests, scripts and CI must not reference the directory any more; historical Markdown
and data fixtures may still name it as provenance.

Standard library only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT  # noqa: E402

EVIDENCE = "docs/insurance-kb/evidence"
PACK_TEST = "harness/tests/test_ba0_evidence_pack_830.py"
CODE_SUFFIXES = (
    ".py", ".go", ".ts", ".tsx", ".vue", ".js", ".mjs", ".sh",
    ".yml", ".yaml", ".toml", ".cfg", ".ini",
)
CODE_NAMES = ("Makefile", "Dockerfile")


def tracked(*paths: str) -> list[str]:
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files", "-z", "--", *paths],
        cwd=REPO_ROOT, check=True, capture_output=True,
    ).stdout.decode("utf-8")
    return [p for p in out.split("\0") if p]


def is_code(path: str) -> bool:
    name = Path(path).name
    return path.endswith(CODE_SUFFIXES) or name in CODE_NAMES or name.startswith("Dockerfile")


def test_the_evidence_directory_is_gone() -> None:
    assert tracked(EVIDENCE) == []
    assert not (REPO_ROOT / EVIDENCE).exists()


def test_the_evidence_pack_test_is_deleted() -> None:
    assert tracked(PACK_TEST) == []


def test_no_code_test_script_or_ci_file_references_the_evidence_directory() -> None:
    this = "tests/architecture/test_s7f2a_evidence_archived.py"
    offenders = []
    for path in tracked():
        if path == this or not is_code(path):
            continue
        try:
            text = (REPO_ROOT / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        if EVIDENCE in text:
            offenders.append(path)
    assert offenders == []
