from __future__ import annotations

import base64
import copy
import hashlib
import inspect
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from insurance_harness.goldenset.schema67_golden_quality_gate_596_1 import (
    GOLDEN_DOSSIER_REVIEW_POLICY_SHA256,
    HumanBatchDecisionReceiptV1,
    Schema67GoldenQualityGateError,
    SchemaWikiGoldenQualityDossierV2,
    canonical_human_batch_decision_receipt_v1,
    compose_schema67_golden_dossier_review_authority_596_1,
    make_schema67_golden_evaluation_review_bundle_596_1,
    make_schema67_golden_review_successor_metadata_596_1,
    make_schema_wiki_golden_quality_dossier_v2_596_1,
    schema67_golden_dossier_review_subject_preimage_596_1,
    validate_registered_schema_wiki_golden_quality_dossier_v2_596_1,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import schema_wiki_sha256
from tests.test_schema67_golden_quality_gate_596_1 import (
    _evaluate,
    _golden,
    _non_fixture_candidate_and_authority,
    _sha,
)

_RECEIPT_KEY = Ed25519PrivateKey.from_private_bytes(b"r" * 32)
_RECEIPT_KEY_ID = "test-schema-wiki-human-linyao"
_ISSUED_AT = 1_786_003_200
_EXPIRES_AT = _ISSUED_AT + 3_600
_REVIEWED_AT = "2026-08-06T19:20:00Z"
_PREPARATION_ID = "prep-596-1-golden-dossier-review"
_MAPPING_SHA256 = _sha("formal-schema67-mapping")
_GOLDEN_ARTIFACT_SHA256 = _sha("formal-schema67-golden-artifact")
_STATUS_VECTOR_SHA256 = _sha("formal-schema67-status-vector")
_ATTESTATION_SHA256 = _sha("formal-schema67-review-attestation")
_ANNOTATION_RECEIPT_SHA256 = _sha("596-1:annotation-layer")
_VECTOR = (
    Path(__file__).parents[2]
    / "internal"
    / "application"
    / "service"
    / "testdata"
    / "122_schema67_golden_dossier_human_receipt_vector.json"
)


def _public_key_text(key: Ed25519PrivateKey) -> str:
    return (
        base64.urlsafe_b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
        .rstrip(b"=")
        .decode("ascii")
    )


def _compose_authority(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HARNESS_WEKNORA_BASE_URL", "https://not-used.invalid")
    monkeypatch.setenv("HARNESS_WEKNORA_API_KEY", "not-used")
    monkeypatch.setenv(
        "HARNESS_SCHEMA_WIKI_HUMAN_DECISION_PUBLIC_KEYS",
        json.dumps(((_RECEIPT_KEY_ID, _public_key_text(_RECEIPT_KEY)),)),
    )
    return compose_schema67_golden_dossier_review_authority_596_1(now_epoch=_ISSUED_AT + 1)


def _inputs():
    candidate, evidence_authority = _non_fixture_candidate_and_authority()
    golden = _golden(candidate, evidence_authority)
    result = _evaluate(candidate=candidate, authority=evidence_authority, golden=golden)
    assert result.quality_gate_receipt is not None
    evaluation = make_schema67_golden_evaluation_review_bundle_596_1(result)
    return candidate, evidence_authority, golden, result, evaluation


def _signed_receipt(*, candidate, evidence_authority, golden, result, evaluation, **updates):
    subject_preimage = schema67_golden_dossier_review_subject_preimage_596_1(
        result=result,
        evaluation=evaluation,
        candidate=candidate,
        evidence_authority=evidence_authority,
        golden=golden,
        mapping_sha256=_MAPPING_SHA256,
        golden_artifact_sha256=_GOLDEN_ARTIFACT_SHA256,
        status_vector_sha256=_STATUS_VECTOR_SHA256,
        attestation_sha256=_ATTESTATION_SHA256,
        annotator_model_id="claude-fable-5",
        annotation_receipt_sha256=_ANNOTATION_RECEIPT_SHA256,
        reviewed_by="linyao",
        reviewed_at=_REVIEWED_AT,
        preparation_id=_PREPARATION_ID,
    )
    subject_sha256 = hashlib.sha256(subject_preimage).hexdigest()
    payload = {
        "version": "1",
        "decision": "approve",
        "principal_id": "linyao",
        "tenant_id": 10003,
        "space_id": "space-596-1",
        "raw_kb_id": "raw-kb-596-1",
        "wiki_kb_id": "wiki-kb-596-1",
        "candidate_hash": candidate.candidate_sha256,
        "human_batch_hash": subject_sha256,
        "review_policy_hash": GOLDEN_DOSSIER_REVIEW_POLICY_SHA256,
        "issued_at": _ISSUED_AT,
        "expires_at": _EXPIRES_AT,
        "nonce": "schema67-golden-dossier-review-596-1",
        "signer_key_id": _RECEIPT_KEY_ID,
    }
    payload.update(updates)
    unsigned = HumanBatchDecisionReceiptV1.model_construct(**payload, signature="")
    signature = (
        base64.urlsafe_b64encode(
            _RECEIPT_KEY.sign(canonical_human_batch_decision_receipt_v1(unsigned, False))
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    return HumanBatchDecisionReceiptV1.model_validate({**payload, "signature": signature})


def _registered_formal(monkeypatch: pytest.MonkeyPatch):
    candidate, evidence_authority, golden, result, evaluation = _inputs()
    receipt = _signed_receipt(
        candidate=candidate,
        evidence_authority=evidence_authority,
        golden=golden,
        result=result,
        evaluation=evaluation,
    )
    authority = _compose_authority(monkeypatch)
    authority.verify_dossier_receipt(
        receipt=receipt,
        result=result,
        evaluation=evaluation,
        candidate=candidate,
        evidence_authority=evidence_authority,
        golden=golden,
        mapping_sha256=_MAPPING_SHA256,
        golden_artifact_sha256=_GOLDEN_ARTIFACT_SHA256,
        status_vector_sha256=_STATUS_VECTOR_SHA256,
        attestation_sha256=_ATTESTATION_SHA256,
        annotator_model_id="claude-fable-5",
        annotation_receipt_sha256=_ANNOTATION_RECEIPT_SHA256,
        reviewed_by="linyao",
        reviewed_at=_REVIEWED_AT,
        preparation_id=_PREPARATION_ID,
    )
    successor = make_schema67_golden_review_successor_metadata_596_1(
        evaluation=evaluation,
        candidate=candidate,
        evidence_authority=evidence_authority,
        golden=golden,
        annotator_model_id="claude-fable-5",
        annotation_receipt_sha256=_ANNOTATION_RECEIPT_SHA256,
        reviewed_by="linyao",
        reviewed_at=_REVIEWED_AT,
        human_decision_receipt=receipt,
        mapping_sha256=_MAPPING_SHA256,
        golden_artifact_sha256=_GOLDEN_ARTIFACT_SHA256,
        status_vector_sha256=_STATUS_VECTOR_SHA256,
        attestation_sha256=_ATTESTATION_SHA256,
        preparation_id=_PREPARATION_ID,
    )
    dossier = make_schema_wiki_golden_quality_dossier_v2_596_1(
        preparation_id=_PREPARATION_ID,
        evaluation=evaluation,
        review_successor=successor,
        human_decision_receipt=receipt,
    )
    return candidate, evidence_authority, golden, result, evaluation, receipt, successor, dossier


def test_factory_receipt_pair_is_registered_and_fresh_replayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _registered_formal(monkeypatch)
    candidate, evidence, golden, result, evaluation, receipt, _, dossier = values
    assert (
        validate_registered_schema_wiki_golden_quality_dossier_v2_596_1(
            dossier,
            result=result,
            evaluation=evaluation,
            human_decision_receipt=receipt,
            candidate=candidate,
            evidence_authority=evidence,
            golden=golden,
            mapping_sha256=_MAPPING_SHA256,
            golden_artifact_sha256=_GOLDEN_ARTIFACT_SHA256,
            status_vector_sha256=_STATUS_VECTOR_SHA256,
            attestation_sha256=_ATTESTATION_SHA256,
        )
        is dossier
    )
    assert (
        dossier.review_successor.human_review_layer.review_receipt_sha256
        == hashlib.sha256(canonical_human_batch_decision_receipt_v1(receipt, True)).hexdigest()
    )


def test_reparsed_self_built_and_cross_pair_authorities_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _registered_formal(monkeypatch)
    candidate, evidence, golden, result, evaluation, receipt, successor, dossier = values
    reparsed_dossier = SchemaWikiGoldenQualityDossierV2.model_validate(
        dossier.model_dump(mode="python")
    )
    with pytest.raises(Schema67GoldenQualityGateError):
        validate_registered_schema_wiki_golden_quality_dossier_v2_596_1(
            reparsed_dossier,
            result=result,
            evaluation=evaluation,
            human_decision_receipt=receipt,
            candidate=candidate,
            evidence_authority=evidence,
            golden=golden,
            mapping_sha256=_MAPPING_SHA256,
            golden_artifact_sha256=_GOLDEN_ARTIFACT_SHA256,
            status_vector_sha256=_STATUS_VECTOR_SHA256,
            attestation_sha256=_ATTESTATION_SHA256,
        )

    reparsed_successor = type(successor).model_validate(successor.model_dump(mode="python"))
    with pytest.raises(Schema67GoldenQualityGateError):
        make_schema_wiki_golden_quality_dossier_v2_596_1(
            preparation_id=_PREPARATION_ID,
            evaluation=evaluation,
            review_successor=reparsed_successor,
            human_decision_receipt=receipt,
        )

    second_evaluation = make_schema67_golden_evaluation_review_bundle_596_1(result)
    with pytest.raises(Schema67GoldenQualityGateError):
        make_schema_wiki_golden_quality_dossier_v2_596_1(
            preparation_id=_PREPARATION_ID,
            evaluation=second_evaluation,
            review_successor=successor,
            human_decision_receipt=receipt,
        )


def test_missing_registration_and_fully_rehashed_evidence_change_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, evidence, golden, result, evaluation = _inputs()
    receipt = _signed_receipt(
        candidate=candidate,
        evidence_authority=evidence,
        golden=golden,
        result=result,
        evaluation=evaluation,
    )
    with pytest.raises(Schema67GoldenQualityGateError):
        make_schema67_golden_review_successor_metadata_596_1(
            evaluation=evaluation,
            candidate=candidate,
            evidence_authority=evidence,
            golden=golden,
            annotator_model_id="claude-fable-5",
            annotation_receipt_sha256=_sha("596-1:annotation-layer"),
            reviewed_by="linyao",
            reviewed_at=_REVIEWED_AT,
            human_decision_receipt=receipt,
            mapping_sha256=_MAPPING_SHA256,
            golden_artifact_sha256=_GOLDEN_ARTIFACT_SHA256,
            status_vector_sha256=_STATUS_VECTOR_SHA256,
            attestation_sha256=_ATTESTATION_SHA256,
            preparation_id=_PREPARATION_ID,
        )

    *_, registered_receipt, successor, dossier = _registered_formal(monkeypatch)
    payload = copy.deepcopy(dossier.model_dump(mode="python"))
    field = next(
        row for row in payload["review_successor"]["ordered_fields"] if row["evidence_changes"]
    )
    field["evidence_changes"][0]["candidate_evidence_id"] = "f" * 64
    change = field["evidence_changes"][0]
    change["change_sha256"] = schema_wiki_sha256(
        "schema67-golden-evidence-change.v1",
        {key: value for key, value in change.items() if key != "change_sha256"},
    )
    field["field_metadata_sha256"] = schema_wiki_sha256(
        "schema67-golden-review-field-metadata.v1",
        {key: value for key, value in field.items() if key != "field_metadata_sha256"},
    )
    successor_payload = payload["review_successor"]
    successor_payload["metadata_sha256"] = schema_wiki_sha256(
        "schema67-golden-review-successor-metadata.v1",
        {key: value for key, value in successor_payload.items() if key != "metadata_sha256"},
    )
    forged = SchemaWikiGoldenQualityDossierV2.model_validate(payload)
    with pytest.raises(Schema67GoldenQualityGateError):
        validate_registered_schema_wiki_golden_quality_dossier_v2_596_1(
            forged,
            result=result,
            evaluation=evaluation,
            human_decision_receipt=registered_receipt,
            candidate=candidate,
            evidence_authority=evidence,
            golden=golden,
            mapping_sha256=_MAPPING_SHA256,
            golden_artifact_sha256=_GOLDEN_ARTIFACT_SHA256,
            status_vector_sha256=_STATUS_VECTOR_SHA256,
            attestation_sha256=_ATTESTATION_SHA256,
        )
    assert successor is not None


@pytest.mark.parametrize(
    "updates",
    (
        {"human_batch_hash": "f" * 64},
        {"review_policy_hash": "e" * 64},
        {"space_id": "foreign-space"},
        {"raw_kb_id": "foreign-raw"},
        {"wiki_kb_id": "foreign-wiki"},
        {"tenant_id": 10004},
        {"candidate_hash": "d" * 64},
        {"principal_id": "foreign-reviewer"},
        {"nonce": "foreign-nonce"},
        {"signer_key_id": "unknown-key"},
        {"expires_at": _ISSUED_AT + 1},
    ),
)
def test_signed_subject_policy_scope_and_principal_drift_are_rejected(
    monkeypatch: pytest.MonkeyPatch, updates: dict[str, object]
) -> None:
    candidate, evidence, golden, result, evaluation = _inputs()
    receipt = _signed_receipt(
        candidate=candidate,
        evidence_authority=evidence,
        golden=golden,
        result=result,
        evaluation=evaluation,
        **updates,
    )
    authority = _compose_authority(monkeypatch)
    with pytest.raises(Schema67GoldenQualityGateError):
        authority.verify_dossier_receipt(
            receipt=receipt,
            result=result,
            evaluation=evaluation,
            candidate=candidate,
            evidence_authority=evidence,
            golden=golden,
            mapping_sha256=_MAPPING_SHA256,
            golden_artifact_sha256=_GOLDEN_ARTIFACT_SHA256,
            status_vector_sha256=_STATUS_VECTOR_SHA256,
            attestation_sha256=_ATTESTATION_SHA256,
            annotator_model_id="claude-fable-5",
            annotation_receipt_sha256=_ANNOTATION_RECEIPT_SHA256,
            reviewed_by="linyao",
            reviewed_at=_REVIEWED_AT,
            preparation_id=_PREPARATION_ID,
        )


def test_receipt_wire_is_go_compatible_and_deployment_composed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, evidence, golden, result, evaluation, receipt, _, _ = _registered_formal(monkeypatch)
    preimage = schema67_golden_dossier_review_subject_preimage_596_1(
        result=result,
        evaluation=evaluation,
        candidate=candidate,
        evidence_authority=evidence,
        golden=golden,
        mapping_sha256=_MAPPING_SHA256,
        golden_artifact_sha256=_GOLDEN_ARTIFACT_SHA256,
        status_vector_sha256=_STATUS_VECTOR_SHA256,
        attestation_sha256=_ATTESTATION_SHA256,
        annotator_model_id="claude-fable-5",
        annotation_receipt_sha256=_ANNOTATION_RECEIPT_SHA256,
        reviewed_by="linyao",
        reviewed_at=_REVIEWED_AT,
        preparation_id=_PREPARATION_ID,
    )
    vector = {
        "public_key_id": _RECEIPT_KEY_ID,
        "public_key_base64": _public_key_text(_RECEIPT_KEY),
        "review_policy_sha256": GOLDEN_DOSSIER_REVIEW_POLICY_SHA256,
        "subject_preimage_base64": base64.b64encode(preimage).decode("ascii"),
        "subject_sha256": hashlib.sha256(preimage).hexdigest(),
        "receipt_json": canonical_human_batch_decision_receipt_v1(receipt, True).decode(),
        "receipt_sha256": hashlib.sha256(
            canonical_human_batch_decision_receipt_v1(receipt, True)
        ).hexdigest(),
    }
    expected = json.dumps(vector, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    assert _VECTOR.read_bytes() == expected
    assert tuple(
        inspect.signature(compose_schema67_golden_dossier_review_authority_596_1).parameters
    ) == ("now_epoch",)


def test_deployment_human_key_ring_is_required_and_caller_cannot_inject_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_WEKNORA_BASE_URL", "https://not-used.invalid")
    monkeypatch.setenv("HARNESS_WEKNORA_API_KEY", "not-used")
    monkeypatch.delenv("HARNESS_SCHEMA_WIKI_HUMAN_DECISION_PUBLIC_KEYS", raising=False)
    with pytest.raises(Schema67GoldenQualityGateError):
        compose_schema67_golden_dossier_review_authority_596_1(now_epoch=_ISSUED_AT + 1)

    monkeypatch.setenv("HARNESS_SCHEMA_WIKI_HUMAN_DECISION_PUBLIC_KEYS", "[]")
    with pytest.raises(Schema67GoldenQualityGateError):
        compose_schema67_golden_dossier_review_authority_596_1(now_epoch=_ISSUED_AT + 1)

    public_key = _public_key_text(_RECEIPT_KEY)
    for configured in (
        (("", public_key),),
        ((_RECEIPT_KEY_ID, public_key), (_RECEIPT_KEY_ID, public_key)),
        ((_RECEIPT_KEY_ID, public_key), ("second-id", public_key)),
    ):
        monkeypatch.setenv(
            "HARNESS_SCHEMA_WIKI_HUMAN_DECISION_PUBLIC_KEYS",
            json.dumps(configured),
        )
        with pytest.raises(Schema67GoldenQualityGateError):
            compose_schema67_golden_dossier_review_authority_596_1(
                now_epoch=_ISSUED_AT + 1
            )

    assert tuple(
        inspect.signature(compose_schema67_golden_dossier_review_authority_596_1).parameters
    ) == ("now_epoch",)


@pytest.mark.parametrize(
    ("argument", "value"),
    (
        ("mapping_sha256", "a" * 64),
        ("golden_artifact_sha256", "b" * 64),
        ("status_vector_sha256", "c" * 64),
        ("attestation_sha256", "d" * 64),
        ("annotation_receipt_sha256", "e" * 64),
    ),
)
def test_signed_receipt_rejects_frozen_authority_input_drift(
    monkeypatch: pytest.MonkeyPatch, argument: str, value: str
) -> None:
    candidate, evidence, golden, result, evaluation = _inputs()
    receipt = _signed_receipt(
        candidate=candidate,
        evidence_authority=evidence,
        golden=golden,
        result=result,
        evaluation=evaluation,
    )
    authority = _compose_authority(monkeypatch)
    inputs = {
        "mapping_sha256": _MAPPING_SHA256,
        "golden_artifact_sha256": _GOLDEN_ARTIFACT_SHA256,
        "status_vector_sha256": _STATUS_VECTOR_SHA256,
        "attestation_sha256": _ATTESTATION_SHA256,
        "annotator_model_id": "claude-fable-5",
        "annotation_receipt_sha256": _ANNOTATION_RECEIPT_SHA256,
    }
    inputs[argument] = value
    with pytest.raises(Schema67GoldenQualityGateError):
        authority.verify_dossier_receipt(
            receipt=receipt,
            result=result,
            evaluation=evaluation,
            candidate=candidate,
            evidence_authority=evidence,
            golden=golden,
            reviewed_by="linyao",
            reviewed_at=_REVIEWED_AT,
            preparation_id=_PREPARATION_ID,
            **inputs,
        )
