"""OpenSpec 020 D1.1d/D1.5: detached canary-review envelope boundary."""

from __future__ import annotations

import base64
import inspect
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import ValidationError

import insurance_harness.goldenset.admission_cli as admission_cli
from insurance_harness.goldenset.admission_models import (
    ApprovalVerificationError,
    CanaryReviewApprovalEnvelope,
    CanaryReviewApprovalPayload,
    CanaryReviewArtifactEvidence,
    CanaryReviewTarget,
    CanaryReviewUsageEvidence,
    ModelRolePlan,
    RunAdmissionPlan,
    RunAdmissionPlanPayload,
    approval_signed_bytes,
    plan_payload_hash,
    verify_approval_envelope,
)

_NOW = datetime(2026, 7, 20, 8, 0, tzinfo=UTC)
_FIRST_PRODUCT = "平安爱满分（2026）两全保险"
_SECOND_PRODUCT = "平安附加（2026）意外伤害保险"


def _plan() -> RunAdmissionPlan:
    roles = {
        role: ModelRolePlan(
            provider="bailian",
            model_id=f"{role}-deployment",
            expected_model_revision="2026-07-19T09:00:00Z",
            protocol="https",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            provider_policy="bailian-deployment-detail-v1",
            credential_env_name="HARNESS_DASHSCOPE_API_KEY",
        )
        for role in ("annotator", "weak_extractor", "judge")
    }
    return RunAdmissionPlan(
        payload=RunAdmissionPlanPayload(
            run_identity="gs-v0.1-run-001",
            purpose="gs-v0.1-baseline",
            model_roles=roles,
            identity_contract_hash="b" * 64,
            budget_contract_hash="c" * 64,
        )
    )


def _payload(**overrides: object) -> CanaryReviewApprovalPayload:
    plan = _plan()
    values: dict[str, object] = {
        "plan_payload_hash": plan_payload_hash(plan),
        "run_identity": plan.payload.run_identity,
        "purpose": plan.payload.purpose,
        "scope": "canary-review:gs-v0.1",
        "approver_identity": "golden-owner@example.com",
        "approver_role": "canary_review_approver",
        "issued_at": _NOW - timedelta(minutes=5),
        "expires_at": _NOW + timedelta(minutes=30),
        "review_decision": "approved",
        "granted_targets": (
            {"stage": "annotation", "product_id": _SECOND_PRODUCT},
        ),
        "execution_plan_hash": "d" * 64,
        "evaluated_revision": "e" * 40,
        "runtime_capability_version": "budget-ledger-v3-canary-v1",
        "canary_target": {"stage": "annotation", "product_id": _FIRST_PRODUCT},
        "budget_account_identity": "f" * 64,
        "budget_revision": 3,
        "budget_approval_digest": "1" * 64,
        "settlement_snapshot_digest": "2" * 64,
        "artifacts": {
            "checkpoint_digest": "3" * 64,
            "manifest_digest": "4" * 64,
            "golden_digest": "5" * 64,
            "quote_verification_digest": "6" * 64,
            "disputed_quality_digest": "7" * 64,
            "disputed_count": 1,
            "record_count": 100,
            "quality_threshold_version": "golden-v0.1-thresholds-v1",
        },
        "provider_usage": {
            "role": "annotator",
            "input_tokens": 1200,
            "output_tokens": 300,
            "cost_minor_units": 17,
            "role_rate_digest": "8" * 64,
        },
    }
    values.update(overrides)
    return CanaryReviewApprovalPayload.model_validate(values)


def _envelope(
    *,
    private_key: Ed25519PrivateKey | None = None,
    payload: CanaryReviewApprovalPayload | None = None,
) -> CanaryReviewApprovalEnvelope:
    signing_key = private_key or Ed25519PrivateKey.generate()
    actual_payload = payload or _payload()
    signature = signing_key.sign(
        approval_signed_bytes("canary-review", actual_payload)
    )
    return CanaryReviewApprovalEnvelope(
        domain="canary-review",
        key_id="canary-key-1",
        payload=actual_payload,
        signature=base64.b64encode(signature).decode("ascii"),
    )


def _write_envelope(path: Path, envelope: CanaryReviewApprovalEnvelope) -> None:
    path.write_text(
        yaml.safe_dump(
            envelope.model_dump(mode="json"),
            allow_unicode=True,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)


def _protected_inbox(tmp_path: Path) -> tuple[Path, Path]:
    anchor = tmp_path / "deployment-root"
    anchor.mkdir(mode=0o700)
    inbox = anchor / "canary-review-inbox"
    inbox.mkdir(mode=0o700)
    return anchor, inbox


def _load_test_inbox(anchor: Path, inbox: Path) -> CanaryReviewApprovalEnvelope:
    return admission_cli._load_canary_review_approval_from_inbox(
        inbox,
        anchor=anchor,
        required_uid=os.geteuid(),
    )


def test_d1_1d_canary_review_payload_is_strict_frozen_and_binds_all_evidence() -> None:
    payload = _payload()

    assert payload.review_decision == "approved"
    assert payload.canary_target == CanaryReviewTarget(
        stage="annotation", product_id=_FIRST_PRODUCT
    )
    assert payload.artifacts == CanaryReviewArtifactEvidence(
        checkpoint_digest="3" * 64,
        manifest_digest="4" * 64,
        golden_digest="5" * 64,
        quote_verification_digest="6" * 64,
        disputed_quality_digest="7" * 64,
        disputed_count=1,
        record_count=100,
        quality_threshold_version="golden-v0.1-thresholds-v1",
    )
    assert payload.provider_usage == CanaryReviewUsageEvidence(
        role="annotator",
        input_tokens=1200,
        output_tokens=300,
        cost_minor_units=17,
        role_rate_digest="8" * 64,
    )
    with pytest.raises(ValidationError):
        CanaryReviewApprovalPayload.model_validate(
            {**payload.model_dump(mode="python"), "unsigned_hint": "approved"}
        )
    with pytest.raises(ValidationError):
        CanaryReviewApprovalPayload.model_validate(
            {**payload.model_dump(mode="python"), "issued_at": _NOW.replace(tzinfo=None)}
        )
    with pytest.raises(ValidationError):
        CanaryReviewApprovalPayload.model_validate(
            {
                **payload.model_dump(mode="python"),
                "provider_usage": {
                    **payload.provider_usage.model_dump(mode="python"),
                    "input_tokens": 1.5,
                },
            }
        )
    with pytest.raises(ValidationError):
        payload.model_copy(update={"review_decision": "bypass"})


def test_d1_5_signed_review_rejects_disputed_count_above_record_count() -> None:
    payload = _payload().model_dump(mode="python")
    artifacts = dict(payload["artifacts"])
    artifacts.update(disputed_count=101, record_count=100)
    payload["artifacts"] = artifacts

    with pytest.raises(ValidationError, match="disputed_count.*record_count"):
        CanaryReviewApprovalPayload.model_validate(payload)


def test_d1_5_granted_targets_are_ordered_unique_and_code_controlled() -> None:
    ordered = (
        {"stage": "annotation", "product_id": _SECOND_PRODUCT},
        {"stage": "baseline", "product_id": _FIRST_PRODUCT},
    )
    assert tuple(_payload(granted_targets=ordered).granted_targets) == tuple(
        CanaryReviewTarget.model_validate(target) for target in ordered
    )

    with pytest.raises(ValidationError, match="unique"):
        _payload(granted_targets=(ordered[0], ordered[0]))
    with pytest.raises(ValidationError, match="controlled"):
        _payload(
            granted_targets=(
                {"stage": "annotation", "product_id": "attacker-product"},
            )
        )
    with pytest.raises(ValidationError, match="controlled"):
        _payload(
            granted_targets=(
                {"stage": "publish", "product_id": _SECOND_PRODUCT},
            )
        )


def test_d1_1d_canary_review_domain_is_separate_and_not_in_plan_union() -> None:
    envelope = _envelope()
    plan = _plan()
    before = plan_payload_hash(plan)

    assert approval_signed_bytes("canary-review", envelope.payload).startswith(
        b"insurancekb.run-admission.canary-review.v1\0"
    )
    with pytest.raises(ValidationError):
        RunAdmissionPlan.model_validate(
            {
                **plan.model_dump(mode="python"),
                "approval_envelopes": [envelope.model_dump(mode="python")],
            }
        )
    assert plan_payload_hash(plan) == before


def test_d1_1d_noncanonical_base64_pad_bits_cannot_alias_capability_identity() -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope = _envelope(private_key=private_key)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    canonical_index = alphabet.index(envelope.signature[-3])
    assert canonical_index & 0b1111 == 0
    alias = (
        envelope.signature[:-3]
        + alphabet[canonical_index + 1]
        + envelope.signature[-2:]
    )
    assert alias != envelope.signature
    assert base64.b64decode(alias) == base64.b64decode(envelope.signature)
    aliased = envelope.model_copy(update={"signature": alias})

    with pytest.raises(ApprovalVerificationError, match="signature"):
        verify_approval_envelope(
            aliased,
            expected_domain="canary-review",
            expected_plan_payload_hash=envelope.payload.plan_payload_hash,
            expected_run_identity=envelope.payload.run_identity,
            expected_purpose=envelope.payload.purpose,
            expected_scope=envelope.payload.scope,
            trusted_public_keys={"canary-key-1": private_key.public_key()},
            allowed_roles=frozenset({"canary_review_approver"}),
            now=_NOW,
        )


def test_d1_1d_external_inbox_load_leaves_plan_hash_unchanged(tmp_path: Path) -> None:
    anchor, inbox = _protected_inbox(tmp_path)
    envelope = _envelope()
    _write_envelope(inbox / "review.yaml", envelope)
    tracked_candidate = anchor / "tracked-candidate.yaml"
    _write_envelope(tracked_candidate, _envelope(payload=_payload(review_decision="rejected")))
    plan = _plan()
    before = plan_payload_hash(plan)

    loaded = _load_test_inbox(anchor, inbox)

    assert loaded == envelope
    assert loaded.payload.review_decision == "approved"
    assert plan_payload_hash(plan) == before


def test_d1_1d_canary_review_cli_has_no_caller_selected_inbox() -> None:
    signature = inspect.signature(
        admission_cli._load_deployment_canary_review_approval
    )
    assert not signature.parameters

    with pytest.raises(ValueError):
        admission_cli._build_parser().parse_args(
            [
                "check",
                "--plan",
                "plan.yaml",
                "--repo-root",
                "/repo",
                "--result-json",
                "/out/result.json",
                "--report-md",
                "/out/report.md",
                "--canary-review-inbox",
                "/attacker",
            ]
        )


def test_d1_1d_deployment_trust_has_separate_canary_review_roles() -> None:
    public_key = Ed25519PrivateKey.generate().public_key().public_bytes(
        Encoding.Raw,
        PublicFormat.Raw,
    )
    parsed_keys, budget_roles, provenance_roles, canary_roles = (
        admission_cli._parse_trusted_approval_configuration(
            yaml.safe_dump(
                {
                    "public_keys": {
                        "canary-key-1": base64.b64encode(public_key).decode("ascii")
                    },
                    "budget_roles": ["budget_approver"],
                    "provenance_roles": ["provenance_approver"],
                    "canary_review_roles": ["canary_review_approver"],
                },
                sort_keys=True,
            )
        )
    )

    assert set(parsed_keys) == {"canary-key-1"}
    assert budget_roles == frozenset({"budget_approver"})
    assert provenance_roles == frozenset({"provenance_approver"})
    assert canary_roles == frozenset({"canary_review_approver"})


@pytest.mark.parametrize("unsafe", ["directory_mode", "file_mode", "file_symlink"])
def test_d1_1d_external_inbox_rejects_unprotected_or_symlink_file(
    tmp_path: Path,
    unsafe: str,
) -> None:
    anchor, inbox = _protected_inbox(tmp_path)
    approval = inbox / "review.yaml"
    if unsafe == "file_symlink":
        target = anchor / "attacker.yaml"
        _write_envelope(target, _envelope())
        approval.symlink_to(target)
    else:
        _write_envelope(approval, _envelope())
        if unsafe == "directory_mode":
            inbox.chmod(0o770)
        else:
            approval.chmod(0o660)

    with pytest.raises(admission_cli.CanaryReviewInboxError):
        _load_test_inbox(anchor, inbox)


def test_d1_1d_external_inbox_rejects_parent_component_symlink(
    tmp_path: Path,
) -> None:
    anchor = tmp_path / "deployment-root"
    anchor.mkdir(mode=0o700)
    actual = anchor / "actual"
    actual.mkdir(mode=0o700)
    inbox = actual / "inbox"
    inbox.mkdir(mode=0o700)
    _write_envelope(inbox / "review.yaml", _envelope())
    linked = anchor / "linked"
    linked.symlink_to(actual, target_is_directory=True)

    with pytest.raises(admission_cli.CanaryReviewInboxError):
        _load_test_inbox(anchor, linked / "inbox")


def test_d1_1d_external_inbox_rejects_duplicate_key_and_invalid_schema(
    tmp_path: Path,
) -> None:
    anchor, inbox = _protected_inbox(tmp_path)
    approval = inbox / "review.yaml"
    serialized = yaml.safe_dump(
        _envelope().model_dump(mode="json"), allow_unicode=True, sort_keys=True
    )
    approval.write_text(
        serialized.replace(
            "domain: canary-review\n",
            "domain: canary-review\ndomain: canary-review\n",
            1,
        ),
        encoding="utf-8",
    )
    approval.chmod(0o600)

    with pytest.raises(admission_cli.CanaryReviewApprovalInputError):
        _load_test_inbox(anchor, inbox)

    approval.write_bytes(b"")
    approval.chmod(0o600)
    with pytest.raises(admission_cli.CanaryReviewApprovalInputError):
        _load_test_inbox(anchor, inbox)

    approval.write_text("domain: canary-review\n", encoding="utf-8")
    approval.chmod(0o600)
    with pytest.raises(admission_cli.CanaryReviewApprovalInputError):
        _load_test_inbox(anchor, inbox)


def test_d1_1d_external_inbox_rejects_oversize_or_multiple_envelopes(
    tmp_path: Path,
) -> None:
    anchor, inbox = _protected_inbox(tmp_path)
    approval = inbox / "review.yaml"
    approval.write_bytes(b"x" * (admission_cli._MAX_CANARY_REVIEW_BYTES + 1))
    approval.chmod(0o600)

    with pytest.raises(admission_cli.CanaryReviewInboxError):
        _load_test_inbox(anchor, inbox)

    approval.unlink()
    _write_envelope(inbox / "review-1.yaml", _envelope())
    _write_envelope(inbox / "review-2.json", _envelope())
    with pytest.raises(admission_cli.CanaryReviewInboxError, match="exactly one"):
        _load_test_inbox(anchor, inbox)
