"""Aggregate routing recognizes one complete source cohort, not a material batch."""

from typing import Any

import pytest

from insurance_harness.product_ingestion import native_dependency_aggregate as aggregate
from tests.product_ingestion.test_native_multiwindow_closure import windows

pytest_plugins = ("tests.product_ingestion.test_discovery",)


@pytest.mark.parametrize(
    "mutation",
    ["valid", "materials", "source", "parse", "scope", "duplicate", "hash", "missing", "phase"],
)
def test_aggregate_eligibility_matches_exact_complete_source_windows(
    case: Any, mutation: str
) -> None:
    snapshots, _ = windows(case)
    if mutation == "materials":
        snapshots = [
            row.model_copy(
                update={
                    "knowledge_id": f"material-{index}",
                    "window_count": 1,
                    "windows": [row.windows[0].model_copy(update={"window_id": 0})],
                }
            )
            for index, row in enumerate(snapshots)
        ]
    elif mutation == "source":
        snapshots[1] = snapshots[1].model_copy(update={"source_snapshot_sha256": "f" * 64})
    elif mutation == "parse":
        snapshots[1] = snapshots[1].model_copy(update={"parse_attempt": 99})
    elif mutation == "scope":
        snapshots[1] = snapshots[1].model_copy(update={"scope": {"space_id": "other"}})
    elif mutation == "duplicate":
        snapshots[1] = snapshots[1].model_copy(update={"windows": snapshots[0].windows})
    elif mutation == "hash":
        snapshots[1] = snapshots[1].model_copy(
            update={"snapshot_sha256": snapshots[0].snapshot_sha256}
        )
    elif mutation == "missing":
        snapshots = snapshots[:1]
    elif mutation == "phase":
        snapshots[1] = snapshots[1].model_copy(update={"phase": "plan"})
    expected = (
        "aggregate"
        if mutation == "valid"
        else "independent"
        if mutation == "materials"
        else "invalid"
    )
    assert aggregate.classify_native_window_group(snapshots) == expected
