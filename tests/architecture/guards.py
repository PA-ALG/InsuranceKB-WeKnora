"""Collect all guard results and compare them with the baseline.

Rule (blueprint 1001 §8): every (guard, key) count may only stay equal or drop.
A key missing from the baseline has an allowed count of zero. The one fixed
tolerance: a file already over the G3 limit at baseline time may grow by at
most GROWTH_ALLOWANCE lines; new or previously compliant files get none.
"""

from __future__ import annotations

import checks_contracts
import checks_files
import checks_python
from common import UPSTREAM_BASE, load_baseline

Results = dict[str, dict[str, int]]

# Tolerance for files already over the G3 limit, measured against their
# baseline count. The baseline itself only ever moves down (lowered()).
GROWTH_ALLOWANCE = {"G3_file_size": 50}

ACTIVE_GUARDS = (
    "G1_dependency_direction",
    "G2_core_purity",
    "G2_go_legacy_terms",
    "G3_file_size",
    "G4_naming",
    "G5_hardcoded",
    "G6_private_access",
    "G9_contract_drift",
    "G10_upstream_patches",
    "G11_new_file_location",
)


def collect() -> Results:
    results: Results = {}
    results.update(checks_python.scan())
    results.update(checks_files.scan())
    results.update(checks_contracts.scan())
    missing = set(ACTIVE_GUARDS) - set(results)
    if missing:
        raise RuntimeError(f"guards produced no result: {sorted(missing)}")
    return {guard: dict(sorted(results[guard].items())) for guard in ACTIVE_GUARDS}


def allowed_count(guard: str, key: str, base: dict[str, int]) -> int:
    if key not in base:
        return 0
    return base[key] + GROWTH_ALLOWANCE.get(guard, 0)


def regressions(current: Results, baseline: dict) -> dict[str, list[str]]:
    allowed = baseline.get("guards", {})
    out: dict[str, list[str]] = {}
    for guard, items in current.items():
        base = allowed.get(guard, {})
        bad = [
            f"{key}: {count} (baseline {base.get(key, 0)}, allowed {allowed_count(guard, key, base)})"
            for key, count in items.items()
            if count > allowed_count(guard, key, base)
        ]
        if bad:
            out[guard] = bad
    return out


def improved(current: Results, baseline: dict) -> bool:
    for guard, base in baseline.get("guards", {}).items():
        now = current.get(guard, {})
        if any(now.get(key, 0) < count for key, count in base.items()):
            return True
    return False


def lowered(current: Results, baseline: dict) -> Results:
    """Per-key minimum of current and baseline: counts within an allowance never raise it."""
    base = baseline.get("guards", {})
    out: Results = {}
    for guard, items in current.items():
        old = base.get(guard, {})
        out[guard] = {
            key: min(count, old[key]) if key in old else count
            for key, count in sorted(items.items())
        }
    return out


def document(current: Results) -> dict:
    return {
        "upstream_base": UPSTREAM_BASE,
        "totals": {guard: sum(items.values()) for guard, items in current.items()},
        "guards": current,
    }


def check_pin(baseline: dict) -> str | None:
    pinned = baseline.get("upstream_base")
    if pinned != UPSTREAM_BASE:
        return (
            f"baseline upstream_base {pinned} != common.UPSTREAM_BASE {UPSTREAM_BASE}; "
            "an upstream upgrade slice must re-record the baseline"
        )
    return None


def current_vs_baseline() -> tuple[Results, dict]:
    return collect(), load_baseline()
