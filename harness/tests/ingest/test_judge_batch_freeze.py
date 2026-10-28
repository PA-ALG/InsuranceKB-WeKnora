"""RV7 review round 2, R1: an interruption between freezing a candidate and recording it.

Spec docs/design/slices/RV7-模型评审批次命令.md §2.3. The frozen file is written before its record
and the record before anything is sent, so a frozen file without a record was never sent. A rerun
freezes under the next number and leaves that file untouched, whole or cut short, and finishes
without manual cleanup.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from insurance_harness.ingest.judge_batch.manifest import write_json
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.ingest.test_judge_batch import publish, world  # noqa: F401
from tests.ingest.test_judge_batch_recovery import attempts, ledger, posts, record  # noqa: F401


class Crash(BaseException):
    """The process dies; nothing above the failing write runs."""


RECORD_WRITE = "insurance_harness.ingest.judge_batch.records.write_json"


def crash_before_the_first_record(monkeypatch: pytest.MonkeyPatch) -> None:
    def dies(path: Path, data: object) -> None:
        monkeypatch.setattr(RECORD_WRITE, write_json)
        raise Crash

    monkeypatch.setattr(RECORD_WRITE, dies)


def frozen(case: dict[str, Any]) -> list[str]:
    folder: Path = case["run_root"] / "publish" / "1828"
    return sorted(path.name for path in folder.glob("attempt-*.bundle.json"))


@pytest.mark.parametrize("cut", [None, 40], ids=["whole", "cut-short"])
def test_an_unrecorded_freeze_is_left_alone_and_the_rerun_finishes(
    ledger: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    cut: int | None,
) -> None:
    crash_before_the_first_record(monkeypatch)
    with pytest.raises(Crash):
        publish(ledger, live=True)
    assert frozen(ledger) == ["attempt-1.bundle.json"] and attempts(ledger) == []
    assert posts(ledger) == [], "nothing is sent before the record exists"
    orphan = ledger["run_root"] / "publish" / "1828" / "attempt-1.bundle.json"
    if cut is not None:
        orphan.write_bytes(orphan.read_bytes()[:cut])  # the write itself was cut short
    left = orphan.read_bytes()
    again = publish(ledger, live=True)
    assert again["stopped"] is None
    assert again["products"]["1828"]["status"] == "published"
    assert orphan.read_bytes() == left, "a frozen identity is never overwritten"
    assert frozen(ledger) == ["attempt-1.bundle.json", "attempt-2.bundle.json"]
    assert record(ledger)["attempt"] == 2 and record(ledger)["stage"] == "sampled"
    assert len(ledger["server"].candidates) == 1
