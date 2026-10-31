"""S7f-2d/2e acceptance (protected, written by Claude): the 18 oversized Harness test modules are split
(Spec docs/design/slices/S7f-2-拆分超长文件.md, section "S7f-2d / S7f-2e 实施"; blueprint §8 G3, §11 S7).

Each source module becomes a directory under a blueprint §4.2 target directory holding scenario-group
test modules, an optional conftest.py (the source's fixtures) and an optional helpers.py (shared code).
Tests move verbatim; the AST/collection proof lives in the PR.

Standard library only. Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from checks_files import MAX_LINES, g3_file_size, misplaced, naming_hit  # noqa: E402
from common import HARNESS_TESTS, REPO_ROOT  # noqa: E402

MOVES = {
    "test_ci_lanes_022.py": "service_shell/ci_lanes",
    "test_job_store_035.py": "jobs/job_store",
    "test_job_store_postgres_035.py": "jobs/job_store_postgres",
    "test_local_app_build_830_ba0.py": "service_shell/app_build",
    "test_local_live_cli_023.py": "service_shell/local_live_cli",
    "test_local_live_compose_023.py": "service_shell/local_live_compose",
    "test_local_live_model_probe_023.py": "service_shell/model_probe",
    "test_local_live_provisioning_023.py": "service_shell/local_provisioning",
    "test_prepare_weknora_adoption_045.py": "service_shell/weknora_adoption",
    "test_service_shell_apps_039.py": "service_shell/apps",
    "test_service_shell_worker_039.py": "service_shell/worker",
    "test_product_version_resolver_041.py": "identity/product_version",
    "test_scope_016.py": "identity/knowledge_scope",
    "test_scope_migration_016.py": "identity/knowledge_scope_migration",
    "test_source_lifecycle_migration_021.py": "ingest/source_lifecycle_migration",
    "test_source_lifecycle_migration_postgres_021.py": "ingest/source_lifecycle_postgres",
    "test_structured_import_010.py": "ingest/structured_import",
    "test_weknora_source_contract_017.py": "ingest/weknora_source",
}
ALLOWED_SUPPORT = {"conftest.py", "helpers.py"}


def tracked(*paths: str) -> list[str]:
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files", "-z", "--", *paths],
        cwd=REPO_ROOT, check=True, capture_output=True,
    ).stdout.decode("utf-8")
    return [p for p in out.split("\0") if p]


def test_the_source_modules_are_gone() -> None:
    sources = [f"{HARNESS_TESTS}/{name}" for name in MOVES]
    assert tracked(*sources) == []
    assert [s for s in sources if (REPO_ROOT / s).exists()] == []


def test_g3_lists_no_harness_test_module() -> None:
    assert sorted(p for p in g3_file_size() if p.startswith(HARNESS_TESTS + "/")) == []


def test_each_directory_holds_only_split_modules_within_limits() -> None:
    problems = []
    for directory in sorted(set(MOVES.values())):
        rel_dir = f"{HARNESS_TESTS}/{directory}"
        files = tracked(rel_dir)
        tests = [f for f in files if Path(f).name.startswith("test_") and f.endswith(".py")]
        if len(tests) < 2:
            problems.append(f"{rel_dir}: expected at least two test modules, found {len(tests)}")
        for path in files:
            name = Path(path).name
            if Path(path).parent.as_posix() != rel_dir:
                problems.append(f"{path}: nested below the split directory")
            elif not (name in ALLOWED_SUPPORT or (name.startswith("test_") and name.endswith(".py"))):
                problems.append(f"{path}: only test modules, conftest.py and helpers.py belong here")
            lines = (REPO_ROOT / path).read_text(encoding="utf-8").count("\n") + 1
            if lines > MAX_LINES:
                problems.append(f"{path}: {lines} lines")
            if misplaced(path):
                problems.append(f"{path}: outside the blueprint §4.2 target directories (G11)")
            if naming_hit(path):
                problems.append(f"{path}: version or mission marker in its name (G4)")
    assert problems == []


def test_test_module_basenames_stay_unique() -> None:
    """pytest imports modules in directories without __init__.py by file name."""
    names = Counter(
        Path(p).name for p in tracked(HARNESS_TESTS)
        if Path(p).name.startswith("test_") and p.endswith(".py")
    )
    assert sorted(n for n, count in names.items() if count > 1) == []
