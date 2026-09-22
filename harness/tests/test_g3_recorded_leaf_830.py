from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from insurance_harness.model_policy import g3_bounded_gateway as gateway
from insurance_harness.run_admission.g3_models import (
    G3BoundedAdmissionPlanV1,
    G3CallTerminalReceiptV1,
    G3ProviderUsageV1,
    canonical_g3_hash,
    canonical_json,
)
from tests import test_g3_bounded_gateway_830 as fixture
from tests.test_g3_user_gemini_gateway_830 import _gemini_plan, _gemini_response


def _recorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: str
) -> tuple[G3BoundedAdmissionPlanV1, Path, G3CallTerminalReceiptV1, bytes, G3ProviderUsageV1]:
    root = tmp_path / "ledger"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(gateway, "G3_LEDGER_ROOT", str(root))
    monkeypatch.setattr(fixture, "valid_c_plan", _gemini_plan)
    plan, old, _, _, directory = fixture._complete_successful_stage(root)
    response = _gemini_response()
    _, semantic, usage = gateway._parse_g3_gemini_provider_response(
        plan.request_manifest.calls[0].identity, response
    )
    (directory / "response-body.private.json").write_bytes(response)
    (directory / "semantic-content.private.json").write_bytes(semantic)
    terminal = old.model_copy(
        update={
            "status": status,
            "response_body_sha256": hashlib.sha256(response).hexdigest(),
            "response_bytes": len(response),
            "semantic_content_sha256": hashlib.sha256(semantic).hexdigest()
            if status == "SUCCESS"
            else None,
            "projection_sha256": old.projection_sha256 if status == "SUCCESS" else None,
            "provider_usage": usage if status == "SUCCESS" else None,
            "receipt_sha256": "0" * 64,
        }
    )
    terminal = terminal.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-call-terminal-receipt.830.v1", terminal, "receipt_sha256"
            )
        }
    )
    (directory / "call-terminal.json").write_bytes(canonical_json(terminal.model_dump(mode="json")))
    return plan, directory, terminal, semantic, usage


@pytest.mark.parametrize("status", ["SUCCESS", "FAILED"])
def test_recorded_leaf_preserves_status_and_reports_observed_over_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: str
) -> None:
    plan, directory, terminal, semantic, usage = _recorded(monkeypatch, tmp_path, status)
    before = fixture._tree_snapshot(directory)
    value = gateway.read_g3_recorded_call(
        plan=plan, call=plan.request_manifest.calls[0], admission_artifact_digest="8" * 64
    )
    assert value.terminal == terminal
    assert value.semantic_bytes == semantic
    assert value.observed_usage == usage
    assert "OUTPUT_TOKEN_CAP_EXCEEDED" in value.anomaly_codes
    assert fixture._tree_snapshot(directory) == before


@pytest.mark.parametrize("artifact", ["request-body.private.json", "response-body.private.json"])
def test_recorded_failed_leaf_rejects_changed_raw_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, artifact: str
) -> None:
    plan, directory, _, _, _ = _recorded(monkeypatch, tmp_path, "FAILED")
    (directory / artifact).write_bytes(b"{}")
    with pytest.raises(gateway.G3LedgerDenied):
        gateway.read_g3_recorded_call(
            plan=plan, call=plan.request_manifest.calls[0], admission_artifact_digest="8" * 64
        )
