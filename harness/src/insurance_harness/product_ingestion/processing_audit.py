"""Append-only native progress snapshots and one accounting view per attempt."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any, Protocol, cast

from insurance_harness.jobs import NonRetryableJobError
from insurance_harness.product_ingestion.processing_receipts import (
    processing_summary,
    validate_processing_receipt,
)

type Receipt = dict[str, Any]


class AuditRecord(Protocol):
    payload: bytes
    payload_sha256: str


def attempt_identity(receipt: Receipt) -> tuple[str, int, int]:
    return receipt["knowledge_id"], receipt["parse_attempt"], receipt.get("processing_attempt", 0)


def _call_extends(previous: Receipt, current: Receipt | None) -> bool:
    if previous == current:
        return True
    mutable = {"state", "outcome", "http_status", "finished_at_unix_ms", "duration_ms"}
    return (
        previous["state"] == "INTERRUPTED"
        and previous["outcome"] == "DISPATCH_UNCERTAIN"
        and current is not None
        and current["state"] == "RECORDED"
        and {k: v for k, v in previous.items() if k not in mutable}
        == {k: v for k, v in current.items() if k not in mutable}
    )


def extends(previous: Receipt, current: Receipt) -> bool:
    """Previously observed terminal facts must survive a progress observation."""
    if attempt_identity(previous) != attempt_identity(current):
        return False
    if previous.get("processing_attempt") is not None and (
        previous["processing_attempt"] != current.get("processing_attempt")
    ):
        return False
    if previous["availability"] == "AVAILABLE" and (
        current["availability"] != "AVAILABLE"
        or previous["journal_marker_sha256"] != current.get("journal_marker_sha256")
    ):
        return False
    current_calls = {row["dispatch_id"]: row for row in current.get("calls", [])}
    if any(
        not _call_extends(row, current_calls.get(row["dispatch_id"]))
        for row in previous.get("calls", [])
    ):
        return False
    for old, new in zip(previous["phases"], current["phases"], strict=True):
        # Occurrence is the response's sorted ordinal, not a durable span ID.
        # A previously running earlier span may finish after a later sibling.
        def facts(rows: Sequence[Receipt]) -> Counter[str]:
            return Counter(
                json.dumps({k: v for k, v in row.items() if k != "occurrence"}, sort_keys=True)
                for row in rows
            )

        if facts(old["occurrences"]) - facts(new["occurrences"]):
            return False
    return True


def latest_attempts(receipts: Iterable[Receipt]) -> tuple[Receipt, ...]:
    """Collapse repeated observations, rejecting conflicting terminal facts."""
    selected: dict[tuple[str, int, int], Receipt] = {}
    for receipt in receipts:
        key = attempt_identity(receipt)
        previous = selected.get(key)
        if previous is None or extends(previous, receipt):
            selected[key] = receipt
        elif not extends(receipt, previous):
            raise NonRetryableJobError("SOURCE_PROCESSING_RECEIPT_CONFLICT")
    known = {key[:2] for key in selected if key[2] > 0}
    return tuple(selected[key] for key in sorted(selected) if key[2] > 0 or key[:2] not in known)


def read_audit(records: Iterable[AuditRecord]) -> tuple[Receipt, ...]:
    """Decode stored audit snapshots independently of the final stage fence."""
    values: list[Receipt] = []
    try:
        for saved in records:
            digest = hashlib.sha256(saved.payload).hexdigest()
            if getattr(saved, "payload_sha256", digest) != digest:
                raise ValueError("digest")
            value = json.loads(saved.payload)
            values.append(
                validate_processing_receipt(
                    value, knowledge_id=value["knowledge_id"], parse_attempt=value["parse_attempt"]
                )
            )
    except (ValueError, KeyError, TypeError) as error:
        raise NonRetryableJobError("SOURCE_PROCESSING_RECEIPT_INVALID") from error
    return tuple(values)


def _account_calls(
    rows: Iterable[tuple[Receipt, bool]],
) -> tuple[int, int, int, bool, bool]:
    """Aggregate dispatches without changing the receipts used by material views."""
    calls: dict[str, Receipt] = {}
    owners: dict[str, bool] = {}
    complete = reused_complete = True
    for receipt, reused in rows:
        if receipt["availability"] != "AVAILABLE":
            if reused:
                reused_complete = False
            else:
                complete = False
        for call in receipt.get("calls", []):
            key = call["dispatch_id"]
            previous = calls.get(key)
            if previous is None:
                calls[key], owners[key] = call, reused
            elif _call_extends(previous, call):
                calls[key] = call
            elif not _call_extends(call, previous):
                raise NonRetryableJobError("SOURCE_PROCESSING_RECEIPT_CONFLICT")
    attempts = reused_attempts = interrupted = 0
    for key, call in calls.items():
        if call["outcome"] == "NOT_DISPATCHED":
            continue
        if owners[key]:
            reused_attempts += 1
        else:
            attempts += 1
            interrupted += int(call["state"] == "INTERRUPTED")
    return attempts, reused_attempts, interrupted, complete, reused_complete


def _entry(receipt: Receipt, reused: bool) -> Receipt:
    return cast(
        Receipt,
        processing_summary([(receipt["knowledge_id"], receipt, reused)])["materials"][0],
    )


def source_accounting(
    summary: Receipt | None,
    receipts: Sequence[Receipt],
) -> Receipt | None:
    """Read view of latest facts; persisted v1 summary and receipts stay unchanged."""
    latest = latest_attempts(receipts)
    if summary is None and not latest:
        return None
    by_sha: dict[str, tuple[str, int, int]] = {
        row["receipt_sha256"]: attempt_identity(row) for row in receipts
    }
    by_attempt = {attempt_identity(row): row for row in latest}
    represented: set[tuple[str, int, int]] = set()
    unknown: set[str] = set()
    rows: list[tuple[Receipt, bool]] = []
    entries: list[Receipt] = []
    opaque: list[Receipt] = []
    for entry in summary["materials"] if summary is not None else []:
        key = by_sha.get(entry.get("receipt_sha256"))
        receipt = by_attempt.get(key) if key is not None else None
        if receipt is None:
            # A legacy summary without exact audit binding remains authoritative.
            # Do not guess an attempt or combine an overlapping newer journal.
            unknown.add(entry["knowledge_id"])
            opaque.append(entry)
            entries.append(entry)
        else:
            assert key is not None
            represented.add(key)
            rows.append((receipt, entry["reused"]))
            entries.append(_entry(receipt, entry["reused"]))
    prior = [
        row
        for row in latest
        if attempt_identity(row) not in represented and row["knowledge_id"] not in unknown
    ]
    rows.extend((row, False) for row in prior)
    attempts, reused, interrupted, complete, reused_complete = _account_calls(rows)
    for entry in opaque:
        available = entry["availability"] == "AVAILABLE" and entry["counts"] is not None
        if entry["reused"]:
            reused += entry["counts"]["attempts"] if available else 0
            reused_complete &= available
        else:
            attempts += entry["counts"]["attempts"] if available else 0
            interrupted += entry["counts"]["interrupted"] if available else 0
            complete &= available
    if summary is None:
        entries = [_entry(row, False) for row in latest]
        complete = False  # An in-progress journal is not sealed source accounting.
    if any(row["knowledge_id"] in unknown for row in latest):
        complete = False
    result = dict(summary or {})
    result.update(
        contract="product-source-processing-summary.830.v1",
        model_call_count=attempts if complete and interrupted == 0 else None,
        recorded_model_call_count=attempts,
        reused_model_call_count=reused if reused_complete else None,
        recorded_reused_model_call_count=reused,
        model_call_count_complete=complete and interrupted == 0,
        interrupted_count=interrupted,
        materials=sorted(entries, key=lambda row: row["knowledge_id"]),
    )
    if summary is not None and prior:
        result["prior_attempts"] = [_entry(row, False) for row in prior]
    return result
