"""Validate signed platform processing facts without inferring missing usage."""

from __future__ import annotations

import hashlib
import re

from insurance_harness.product_ingestion.platform import _canonical

CONTRACT = "g3-platform-source-processing-receipt.830.v1"
PHASES = ("docreader", "chunking", "embedding", "postprocess.summary")
COUNT_KEYS = ("attempts", "confirmed", "interrupted", "not_dispatched", "transport_retries")


def _require(value):
    if not value:
        raise ValueError("SOURCE_PROCESSING_RECEIPT_INVALID")


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _times(row):
    _require(
        all(
            _integer(row.get(k))
            for k in ("started_at_unix_ms", "finished_at_unix_ms", "duration_ms")
        )
    )
    elapsed = row["finished_at_unix_ms"] - row["started_at_unix_ms"]
    _require(elapsed >= 0 and abs(row["duration_ms"] - elapsed) <= 1)


def _phases(rows):
    _require(isinstance(rows, list) and len(rows) == len(PHASES))
    for expected, row in zip(PHASES, rows, strict=True):
        _require(isinstance(row, dict) and set(row) == {"phase", "recorded", "occurrences"})
        occurrences = row["occurrences"]
        _require(
            row["phase"] == expected
            and type(row["recorded"]) is bool
            and isinstance(occurrences, list)
            and row["recorded"] == bool(occurrences)
        )
        _require(expected == "postprocess.summary" or len(occurrences) <= 1)
        previous = -1
        for index, item in enumerate(occurrences):
            _require(
                isinstance(item, dict)
                and set(item)
                == {
                    "occurrence",
                    "status",
                    "started_at_unix_ms",
                    "finished_at_unix_ms",
                    "duration_ms",
                }
            )
            _require(
                type(item["occurrence"]) is int
                and item["occurrence"] == index
                and item["status"] in {"done", "failed", "skipped", "cancelled"}
            )
            _times(item)
            _require(item["started_at_unix_ms"] >= previous)
            previous = item["started_at_unix_ms"]


def validate_processing_receipt(value, *, knowledge_id, parse_attempt):
    """Return the unchanged, closed wire object after identity and arithmetic checks."""
    _require(isinstance(value, dict))
    common = {
        "contract",
        "availability",
        "knowledge_id",
        "parse_attempt",
        "phases",
        "receipt_sha256",
    }
    _require(common <= set(value))
    _require(
        value["contract"] == CONTRACT
        and value["knowledge_id"] == knowledge_id
        and type(value["parse_attempt"]) is int
        and value["parse_attempt"] == parse_attempt
    )
    _require(
        _hash(value["receipt_sha256"])
        and value["receipt_sha256"]
        == hashlib.sha256(
            CONTRACT.encode()
            + b"\0"
            + _canonical({k: v for k, v in value.items() if k != "receipt_sha256"})
        ).hexdigest()
    )
    _phases(value["phases"])
    if value["availability"] == "UNAVAILABLE":
        expected = common | {"unavailability_reason"}
        if "processing_attempt" in value:
            expected.add("processing_attempt")
            _require(_integer(value["processing_attempt"], 1))
        _require(set(value) == expected and value["unavailability_reason"] == "LEGACY_NO_JOURNAL")
        return value
    _require(
        value["availability"] == "AVAILABLE"
        and set(value)
        == common | {"processing_attempt", "journal_marker_sha256", "calls", "counts"}
    )
    _require(_integer(value["processing_attempt"], 1) and _hash(value["journal_marker_sha256"]))
    calls, counts = value["calls"], value["counts"]
    _require(
        isinstance(calls, list) and isinstance(counts, dict) and set(counts) == set(COUNT_KEYS)
    )
    _require(all(_integer(item) for item in counts.values()))
    expected = dict.fromkeys(COUNT_KEYS, 0)
    ids = []
    for row in calls:
        keys = {
            "contract",
            "dispatch_id",
            "operation",
            "purpose",
            "model_id",
            "model_name",
            "request_sha256",
            "transport_retry_index",
            "state",
            "outcome",
            "started_at_unix_ms",
            "finished_at_unix_ms",
            "duration_ms",
        }
        _require(isinstance(row, dict))
        if row.get("outcome") == "HTTP_RESPONSE":
            keys.add("http_status")
            _require(type(row.get("http_status")) is int and 100 <= row["http_status"] <= 599)
        _require(set(row) == keys and row["contract"] == "knowledge-model-dispatch-receipt.830.v1")
        _require(
            all(
                isinstance(row[k], str) and row[k] and row[k] == row[k].strip()
                for k in ("dispatch_id", "model_id", "model_name")
            )
        )
        _require(re.fullmatch(r"[A-Za-z0-9_-]{1,128}", row["dispatch_id"]) is not None)
        ids.append(row["dispatch_id"])
        _require(_hash(row["request_sha256"]) and _integer(row["transport_retry_index"]))
        _require(
            (row["operation"], row["purpose"])
            in {
                ("embedding", "document_embedding"),
                ("embedding", "summary_embedding"),
                ("document_summary", "document_summary"),
            }
        )
        _times(row)
        if row["state"] == "RECORDED":
            _require(row["outcome"] in {"HTTP_RESPONSE", "TRANSPORT_ERROR"})
            expected["confirmed"] += 1
        else:
            _require(
                row["state"] == "INTERRUPTED"
                and row["outcome"] in {"NOT_DISPATCHED", "DISPATCH_UNCERTAIN"}
            )
            expected["not_dispatched" if row["outcome"] == "NOT_DISPATCHED" else "interrupted"] += 1
        if row["outcome"] != "NOT_DISPATCHED":
            expected["attempts"] += 1
            expected["transport_retries"] += int(row["transport_retry_index"] > 0)
    _require(ids == sorted(set(ids)) and counts == expected)
    return value


def processing_summary(rows):
    """Aggregate current source captures; cached predecessor calls are historical usage."""
    entries = []
    attempts = reused_attempts = interrupted = 0
    complete = True
    reused_complete = True
    for knowledge_id, receipt, reused in rows:
        available = receipt is not None and receipt["availability"] == "AVAILABLE"
        calls = receipt["counts"]["attempts"] if available else None
        if reused:
            reused_attempts += calls or 0
            reused_complete = reused_complete and available
        elif available:
            attempts += calls
            interrupted += receipt["counts"]["interrupted"]
        else:
            complete = False
        entries.append(
            {
                "knowledge_id": knowledge_id,
                "reused": reused,
                "availability": "AVAILABLE" if available else "UNAVAILABLE",
                "receipt_sha256": receipt["receipt_sha256"] if receipt else None,
                "counts": receipt["counts"] if available else None,
                "phases": receipt["phases"] if receipt else [],
            }
        )
    return {
        "contract": "product-source-processing-summary.830.v1",
        "model_call_count": attempts if complete and interrupted == 0 else None,
        "recorded_model_call_count": attempts,
        "reused_model_call_count": reused_attempts if reused_complete else None,
        "recorded_reused_model_call_count": reused_attempts,
        "model_call_count_complete": complete and interrupted == 0,
        "interrupted_count": interrupted,
        "materials": sorted(entries, key=lambda row: row["knowledge_id"]),
    }
