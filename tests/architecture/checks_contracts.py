"""G9: every schema drift is a new violation, without baseline tolerance."""

from __future__ import annotations

import sys
from pathlib import Path

from common import REPO_ROOT

# Resolve this worktree's source even when another checkout is installed editable.
sys.path.insert(0, str(REPO_ROOT / "harness" / "src"))

from insurance_harness.contracts.export import check  # noqa: E402


def scan(destination: Path = REPO_ROOT / "contracts") -> dict[str, dict[str, int]]:
    return {"G9_contract_drift": {filename: 1 for filename in check(destination)}}
