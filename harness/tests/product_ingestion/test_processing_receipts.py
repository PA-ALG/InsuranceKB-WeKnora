import copy
import hashlib
import importlib
import typing

import pytest

from insurance_harness.product_ingestion.platform import _canonical

CONTRACT = "g3-platform-source-processing-receipt.830.v1"
PHASES = ("docreader", "chunking", "embedding", "postprocess.summary")


def sealed(value: typing.Any) -> typing.Any:
    value = copy.deepcopy(value)
    value.pop("receipt_sha256", None)
    value["receipt_sha256"] = hashlib.sha256(
        CONTRACT.encode() + b"\0" + _canonical(value)
    ).hexdigest()
    return value


def receipt() -> typing.Any:
    return sealed(
        {
            "contract": CONTRACT,
            "availability": "AVAILABLE",
            "knowledge_id": "knowledge",
            "parse_attempt": 2,
            "processing_attempt": 3,
            "journal_marker_sha256": "a" * 64,
            "calls": [],
            "counts": {
                "attempts": 0,
                "confirmed": 0,
                "interrupted": 0,
                "not_dispatched": 0,
                "transport_retries": 0,
            },
            "phases": [{"phase": name, "recorded": False, "occurrences": []} for name in PHASES],
        }
    )


def api() -> typing.Any:
    try:
        return importlib.import_module("insurance_harness.product_ingestion.processing_receipts")
    except ModuleNotFoundError:
        pytest.fail("platform source model accounting is not implemented")


def validate(value: typing.Any) -> typing.Any:
    return api().validate_processing_receipt(value, knowledge_id="knowledge", parse_attempt=2)


def test_proven_zero_requires_marker_and_legacy_unavailable_is_not_zero() -> None:
    assert validate(receipt())["counts"]["attempts"] == 0
    old = {
        "contract": CONTRACT,
        "availability": "UNAVAILABLE",
        "knowledge_id": "knowledge",
        "parse_attempt": 2,
        "unavailability_reason": "LEGACY_NO_JOURNAL",
        "phases": receipt()["phases"],
    }
    assert "counts" not in validate(sealed(old))
    old["counts"] = receipt()["counts"]
    with pytest.raises(ValueError):
        validate(sealed(old))
    changed = receipt()
    changed.pop("journal_marker_sha256")
    with pytest.raises(ValueError):
        validate(sealed(changed))


def test_attempt_identity_and_receipt_hash_cannot_drift() -> None:
    changed = receipt()
    changed["parse_attempt"] = 3
    with pytest.raises(ValueError):
        validate(sealed(changed))
    changed = receipt()
    changed["processing_attempt"] = 4
    with pytest.raises(ValueError):
        validate(changed)


def test_dispatch_accounting_distinguishes_unsent_and_uncertain() -> None:
    value = receipt()
    calls = []
    for index, (state, outcome) in enumerate(
        [
            ("RECORDED", "HTTP_RESPONSE"),
            ("INTERRUPTED", "NOT_DISPATCHED"),
            ("INTERRUPTED", "DISPATCH_UNCERTAIN"),
        ]
    ):
        call = {
            "contract": "knowledge-model-dispatch-receipt.830.v1",
            "dispatch_id": str(index),
            "operation": "embedding",
            "purpose": "document_embedding",
            "model_id": "embed",
            "model_name": "qwen",
            "request_sha256": "b" * 64,
            "transport_retry_index": index,
            "state": state,
            "outcome": outcome,
            "started_at_unix_ms": 1000,
            "finished_at_unix_ms": 1020,
            "duration_ms": 20,
        }
        if outcome == "HTTP_RESPONSE":
            call["http_status"] = 200
        calls.append(call)
    value["calls"] = calls
    value["counts"] = {
        "attempts": 2,
        "confirmed": 1,
        "interrupted": 1,
        "not_dispatched": 1,
        "transport_retries": 1,
    }
    assert validate(sealed(value))["counts"]["attempts"] == 2
    value["counts"]["attempts"] = 3
    with pytest.raises(ValueError):
        validate(sealed(value))


def test_phase_times_are_real_or_explicitly_unrecorded() -> None:
    value = receipt()
    row = value["phases"][0]
    row["recorded"] = True
    row["occurrences"] = [
        {
            "occurrence": 0,
            "status": "done",
            "started_at_unix_ms": 1000,
            "finished_at_unix_ms": 1300,
            "duration_ms": 300,
        }
    ]
    assert validate(sealed(value))["phases"][0]["recorded"]
    row["occurrences"][0]["duration_ms"] = 3
    with pytest.raises(ValueError):
        validate(sealed(value))


def test_unknown_processing_totals_remain_unknown_and_reused_calls_are_not_new_calls() -> None:
    summary = api().processing_summary([("legacy", None, False)])
    assert summary["model_call_count"] is None
    assert summary["recorded_model_call_count"] == 0
    assert summary["model_call_count_complete"] is False
    reuse = api().processing_summary([("legacy", None, True)])
    assert reuse["model_call_count"] == 0
    assert reuse["reused_model_call_count"] is None
    assert reuse["model_call_count_complete"] is True


def test_actual_go_processing_receipt_wire_is_accepted_without_rewriting() -> None:
    import json
    from pathlib import Path

    path = (
        Path(__file__).parents[3]
        / "internal/application/service/testdata/g3_platform_processing_receipt_v1.json"
    )
    raw = path.read_bytes()
    value = json.loads(raw)
    validated = api().validate_processing_receipt(
        value, knowledge_id=value["knowledge_id"], parse_attempt=value["parse_attempt"]
    )
    assert validated is value
    assert (
        value["receipt_sha256"]
        == "975e2f1ca835a3ea1c95727e17085b6a54001042cfa6617c9e2e33ebf9204f43"
    )
    assert value["counts"]["attempts"] == 2
    assert any(row["model_name"] == "qwen<&>" for row in value["calls"])
