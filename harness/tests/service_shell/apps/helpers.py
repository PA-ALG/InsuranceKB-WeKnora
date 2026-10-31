"""OpenSpec 039 wiki-api / wiki-worker 应用组装：共用路径与设置辅助。"""

from __future__ import annotations

from insurance_harness.jobs import JobState
from insurance_harness.service_shell.health import Lifecycle, ReadinessChecker


def _health() -> tuple[Lifecycle, ReadinessChecker]:
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    checker = ReadinessChecker(
        lifecycle=lifecycle,
        probe=lambda: None,
        timeout_seconds=0.1,
        freshness_seconds=1,
    )
    return lifecycle, checker


def _state_counts(**overrides: int) -> dict[JobState, int]:
    counts = {state: 0 for state in JobState}
    for name, value in overrides.items():
        counts[JobState(name)] = value
    return counts
