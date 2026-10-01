"""Architecture guards (blueprint 1001 §8). Counts may only decrease.

Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import checks_files  # noqa: E402
import checks_python  # noqa: E402
import guards  # noqa: E402
from common import load_baseline, require_upstream_base  # noqa: E402


@pytest.fixture(scope="module")
def state() -> tuple[guards.Results, dict]:
    require_upstream_base()
    return guards.current_vs_baseline()


def test_baseline_pinned_to_current_upstream(state: tuple[guards.Results, dict]) -> None:
    assert guards.check_pin(state[1]) is None


@pytest.mark.parametrize("guard", guards.ACTIVE_GUARDS)
def test_no_new_violations(guard: str, state: tuple[guards.Results, dict]) -> None:
    current, baseline = state
    bad = guards.regressions({guard: current[guard]}, baseline).get(guard, [])
    assert not bad, f"{guard} new violations:\n" + "\n".join(bad[:50])


# ---- self-tests: each detector must catch a known violation -------------------


def _tree(src: str) -> ast.AST:
    return ast.parse(src)


def test_g1_detects_new_dir_importing_old_dir() -> None:
    path = "harness/src/insurance_harness/compile/planner.py"
    tree = _tree("from insurance_harness.product_ingestion import pipeline\nimport insurance_harness.jobs.store\n")
    hits = checks_python.dependency_violations(path, tree)
    assert hits == {f"{path} -> product_ingestion": 1}


def test_g1_detects_core_importing_compilers() -> None:
    path = "harness/src/insurance_harness/review/router.py"
    tree = _tree("from ..compilers.schema_fields import engine\n")
    assert checks_python.dependency_violations(path, tree) == {f"{path} -> compilers": 1}


def test_g1_ignores_old_dirs() -> None:
    path = "harness/src/insurance_harness/product_ingestion/x.py"
    assert not checks_python.dependency_violations(path, _tree("from insurance_harness.knowledge import a\n"))


def test_g6_detects_private_import_and_test_hook() -> None:
    path = "harness/src/insurance_harness/compile/x.py"
    src = (
        "from insurance_harness.jobs.store import _claim\n"
        "def helper_for_test():\n    pass\n"
    )
    assert checks_python.private_access_count(path, _tree(src)) == 2


def test_g2_purity_counts_terms_and_keys() -> None:
    assert checks_files.purity_hits('x = "waiting_period"  # 医疗险') == 2
    assert checks_files.purity_hits('x = "product_code"; y = "release"') == 0


def test_g4_naming_patterns() -> None:
    bad = [
        "harness/src/insurance_harness/knowledge_compiler/g3_bounded_model_execution.py",
        "harness/src/insurance_harness/x/concept_compile_830_g2.py",
        "frontend/src/views/ConceptDirectory830G2.vue",
        "harness/src/insurance_harness/v5/m158_run.py",
        "internal/types/schema_wiki_v2.go",
    ]
    good = [
        "harness/src/insurance_harness/compilers/schema_fields/engine.py",
        "internal/enterprise/release/service.go",
        "frontend/src/enterprise/pages/FieldPage.vue",
    ]
    assert all(checks_files.naming_hit(p) for p in bad)
    assert not any(checks_files.naming_hit(p) for p in good)


def test_g5_hardcoded_patterns() -> None:
    home = "/" + "Users/someone/x"
    text = f'a = "{home}"\nb = "10.20.30.40"\nc = "127.0.0.1"\nd = "release-12345678-1234-1234-1234-123456789abc"\n'
    assert checks_files.hardcoded_hits(text) == 3


def test_g11_locations() -> None:
    misplaced = [
        "harness/src/insurance_harness/product_ingestion/new_stage.py",
        "harness/tests/test_new_thing.py",
        "internal/handler/new_handler.go",
        "migrations/versioned/000200_new.up.sql",
        "frontend/src/views/knowledge/NewPage.vue",
    ]
    placed = [
        "harness/src/insurance_harness/compile/job.py",
        "harness/tests/compile/test_job.py",
        "internal/enterprise/release/service.go",
        "internal/handler/new_handler_test.go",
        "migrations/enterprise/versioned/000006_x.up.sql",
        "frontend/src/enterprise/pages/FieldPage.vue",
    ]
    assert all(checks_files.misplaced(p) for p in misplaced)
    assert not any(checks_files.misplaced(p) for p in placed)


def test_regression_logic() -> None:
    baseline = {"guards": {"G3_file_size": {"a.py": 800}}}
    assert not guards.regressions({"G3_file_size": {"a.py": 700}}, baseline)
    assert guards.regressions({"G3_file_size": {"a.py": 900}}, baseline)
    assert guards.regressions({"G3_file_size": {"b.py": 501}}, baseline)
    assert guards.improved({"G3_file_size": {}}, baseline)


def test_baseline_file_is_readable() -> None:
    doc = load_baseline()
    assert set(guards.ACTIVE_GUARDS) <= set(doc["guards"])
