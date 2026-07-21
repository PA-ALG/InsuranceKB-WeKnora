"""024 E3/E7: durable outbound-call boundary and producer attribution."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from insurance_harness.compiler.attempts import (
    AttemptLedgerMismatch,
    InMemoryAttemptLedger,
    SqliteAttemptLedger,
)
from insurance_harness.compiler.extract import Window, WindowExtractor, call_and_parse
from insurance_harness.compiler.llm import GapfillBudgetExhausted
from insurance_harness.compiler.models import FieldCandidate
from insurance_harness.compiler.voting import vote_field
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.goldenset.records import Evidence
from insurance_harness.schemas import FieldSpec
from tests.test_compiler_pipeline import ScriptedClient, _run_ok


class _Replies:
    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.calls = 0

    async def complete(self, system: str, user: str) -> str:
        reply = self.replies[self.calls]
        self.calls += 1
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_e3_reservation_survives_reopen_and_consumes_hard_budget(
    tmp_path: Path,
) -> None:
    path = tmp_path / "llm-attempts.sqlite"
    first = SqliteAttemptLedger(path, run_id="run-1")
    reserved = first.reserve(
        stage="gapfill",
        prompt_version="targeted@v1",
        request_key="same-request",
        field_ids=("f1",),
        budget_scope="gapfill",
        budget_limit=1,
    )

    # Simulate a hard process crash: no finish() call and a fresh ledger instance.
    resumed = SqliteAttemptLedger(path, run_id="run-1")
    assert resumed.used("gapfill") == 1
    assert resumed.attempts_for_field("f1") == (reserved,)
    assert reserved.outcome == "reserved"
    with pytest.raises(GapfillBudgetExhausted):
        resumed.reserve(
            stage="gapfill",
            prompt_version="targeted@v1",
            request_key="second-request",
            field_ids=("f1",),
            budget_scope="gapfill",
            budget_limit=1,
        )


def test_e3_resume_cannot_expand_the_persisted_budget(tmp_path: Path) -> None:
    path = tmp_path / "llm-attempts.sqlite"
    first = SqliteAttemptLedger(path, run_id="run-1")
    first.ensure_budget("gapfill", 1)
    resumed = SqliteAttemptLedger(path, run_id="run-1")
    resumed.ensure_budget("gapfill", 1)
    with pytest.raises(AttemptLedgerMismatch):
        resumed.ensure_budget("gapfill", 2)
    with pytest.raises(AttemptLedgerMismatch):
        resumed.ensure_budget("gapfill", None)


def test_e7_same_request_retries_get_unique_attempt_ids() -> None:
    ledger = InMemoryAttemptLedger(run_id="run-1")
    one = ledger.reserve(
        stage="extract", prompt_version="baseline@v1", request_key="k",
        field_ids=("f1",),
    )
    two = ledger.reserve(
        stage="extract_retry", prompt_version="baseline@v1", request_key="k",
        field_ids=("f1",),
    )
    assert one.attempt_id != two.attempt_id
    assert [a.attempt_id for a in ledger.attempts_for_field("f1")] == [
        one.attempt_id,
        two.attempt_id,
    ]


def test_e7_replay_deterministic_ids_are_scoped_by_run(tmp_path: Path) -> None:
    path = tmp_path / "attempts.sqlite"
    first_run = SqliteAttemptLedger(path, run_id="run-1")
    second_run = SqliteAttemptLedger(path, run_id="run-2")
    one = first_run.reserve(
        stage="extract", prompt_version="baseline@v1", request_key="same",
        field_ids=("f1",),
    )
    two = second_run.reserve(
        stage="extract", prompt_version="baseline@v1", request_key="same",
        field_ids=("f1",),
    )
    assert one.attempt_id == two.attempt_id, "equivalent replay IDs stay deterministic"
    assert first_run.attempts_for_field("f1") == (one,)
    assert second_run.attempts_for_field("f1") == (two,)


def test_e7_outbound_failure_is_audited_before_exception_escapes() -> None:
    ledger = InMemoryAttemptLedger(run_id="run-1")
    client = _Replies(OSError("connection reset"))
    with pytest.raises(OSError, match="connection reset"):
        asyncio.run(
            call_and_parse(
                client,
                "system",
                "user",
                ledger=ledger,
                field_ids=("f1",),
                stage="extract",
                prompt_version="baseline@v1",
            )
        )
    attempts = ledger.attempts_for_field("f1")
    assert len(attempts) == 1
    assert attempts[0].outcome == "transport_failed"


def test_e7_parse_retry_returns_successful_retry_as_producer() -> None:
    ledger = InMemoryAttemptLedger(run_id="run-1")
    client = _Replies(
        "not-json",
        '[{"field_id":"f1","value":"ok","tri_state":"present","evidence":[]}]',
    )
    result = asyncio.run(
        call_and_parse(
            client,
            "system",
            "user",
            ledger=ledger,
            field_ids=("f1",),
            stage="gapfill",
            prompt_version="targeted@v1",
            budget_scope="gapfill",
            budget_limit=2,
        )
    )
    attempts = ledger.attempts_for_field("f1")
    assert [a.outcome for a in attempts] == ["parse_failed", "parsed"]
    assert result.items is not None
    assert result.producing_attempt_id == attempts[1].attempt_id
    assert ledger.used("gapfill") == 2


def test_e7_assignment_is_independent_of_candidate_success(tmp_path: Path) -> None:
    ledger = SqliteAttemptLedger(tmp_path / "attempts.sqlite", run_id="run-1")
    ledger.record_assignment("f1", "control")
    assert ledger.assignment_for_field("f1") == "control"
    reopened = SqliteAttemptLedger(tmp_path / "attempts.sqlite", run_id="run-1")
    assert reopened.assignment_for_field("f1") == "control"


def test_e7_mixed_batch_keeps_first_producer_for_accepted_field() -> None:
    page = PageText(page_no=1, text="字段一：甲。字段二：乙。")
    first = (
        '[{"field_id":"f1","value":"甲","tri_state":"present",'
        '"evidence":[{"page":1,"quote":"字段一：甲"}]},'
        '{"field_id":"f2","value":"错","tri_state":"present",'
        '"evidence":[{"page":1,"quote":"不存在的引文"}]}]'
    )
    retry = (
        '[{"field_id":"f2","value":"乙","tri_state":"present",'
        '"evidence":[{"page":1,"quote":"字段二：乙"}]}]'
    )
    ledger = InMemoryAttemptLedger(run_id="run-1")
    extractor = WindowExtractor(
        _Replies(first, retry),
        "产品",
        "doc.pdf",
        [page],
        ledger=ledger,
    )
    fields = [
        FieldSpec(name="字段一", field_id="f1"),
        FieldSpec(name="字段二", field_id="f2"),
    ]
    values = asyncio.run(
        extractor.extract(Window(ref="s1", fragments=(page,)), fields)
    )
    by_id = {value.field_id: value for value in values}
    f1_attempts = ledger.attempts_for_field("f1")
    f2_attempts = ledger.attempts_for_field("f2")
    assert len(f1_attempts) == 1
    assert len(f2_attempts) == 2
    assert by_id["f1"].metadata["winning_attempt_id"] == f1_attempts[0].attempt_id
    assert by_id["f2"].metadata["winning_attempt_id"] == f2_attempts[1].attempt_id


def test_e7_vote_confirmation_retains_original_producer_and_origin() -> None:
    ledger = InMemoryAttemptLedger(run_id="run-1")
    producer = ledger.reserve(
        stage="extract",
        prompt_version="baseline@v1",
        request_key="extract-request",
        field_ids=("f1",),
    )
    ledger.finish(producer.attempt_id, "parsed")
    page = PageText(page_no=1, text="等待期为90天。")
    candidate = FieldCandidate(
        field_id="f1",
        field_name="等待期",
        group="basic_info",
        doc="doc.pdf",
        value="90天",
        tri_state="present",
        evidence=[Evidence(page=1, quote="等待期为90天")],
        origin="extract",
        metadata={"winning_attempt_id": producer.attempt_id},
    )
    response = (
        '[{"field_id":"f1","value":"90天","tri_state":"present",'
        '"evidence":[{"page":1,"quote":"等待期为90天"}]}]'
    )
    confirmed = asyncio.run(
        vote_field(
            _Replies(response, response, response),
            "产品",
            FieldSpec(name="等待期", field_id="f1", risk_level="high"),
            candidate,
            [page],
            ledger=ledger,
        )
    )
    assert confirmed.origin == "extract"
    assert confirmed.metadata["winning_attempt_id"] == producer.attempt_id
    assert len(ledger.attempts_for_field("f1")) == 4


async def test_e7_pipeline_finalizes_from_durable_field_ledger(tmp_path: Path) -> None:
    result = await _run_ok(tmp_path, ScriptedClient())
    ledger_path = tmp_path / "run" / "llm-attempts.sqlite"
    assert ledger_path.is_file(), "pipeline runs must use the durable ledger"
    ledger = SqliteAttemptLedger(ledger_path, run_id=result.manifest.run_id)
    by_id = {record.field_id: record for record in result.records}

    waiver = by_id["premium_waiver"]
    assert waiver.extraction_audit is not None
    durable = ledger.attempts_for_field("premium_waiver")
    assert waiver.extraction_audit.attempts == durable
    assert {attempt.stage for attempt in durable} >= {"extract", "gapfill", "vote"}
    assert len({attempt.attempt_id for attempt in durable}) == len(durable)

    winning_id = waiver.extraction_audit.winning_attempt_id
    winner = next(attempt for attempt in durable if attempt.attempt_id == winning_id)
    expected_origin = winner.stage.split("_", 1)[0]
    assert waiver.extraction_audit.winning_origin == expected_origin
