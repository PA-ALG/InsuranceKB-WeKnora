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
from pydantic import ValidationError

import insurance_harness.goldenset.schema67_golden_quality_gate_596_1 as quality_gate_module
from insurance_harness.goldenset.expert_golden_admission_596_2 import (
    EvidenceReplayCaseV1,
    Schema67CandidateV2,
)
from insurance_harness.goldenset.schema67_golden_quality_gate_596_1 import (
    GOLDEN_METRIC_IDS,
    METRIC_POLICY_SHA256,
    NORMALIZATION_POLICY_SHA256,
    RISK_POLICY_SHA256,
    Schema67GoldenApprovalV1,
    Schema67GoldenEvaluationResultV1,
    Schema67GoldenEvaluationReviewBundleV1,
    Schema67GoldenEvidenceTargetV1,
    Schema67GoldenFieldV1,
    Schema67GoldenMetricV1,
    Schema67GoldenQualityEvaluatorAuthority,
    Schema67GoldenQualityEvaluatorSigningCredentialSource,
    Schema67GoldenQualityGateError,
    Schema67GoldenSet5961V1,
    compose_schema67_golden_quality_evaluator_authority_596_1,
    make_schema67_golden_evaluation_review_bundle_596_1,
    schema67_golden_approval_signing_bytes,
    validate_schema67_golden_quality_gate_receipt_596_1,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    APPROVED_ORDERED_FIELD_IDS,
)
from insurance_harness.knowledge_compiler.schema_wiki_candidate_evidence_join_596_1 import (
    Schema67CandidateEvidenceAuthorityV1,
    Schema67CitationAuthorityJoinReceiptV1,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import (
    SchemaWikiContractError,
    schema_wiki_sha256,
    validate_schema_wiki_review_bundle,
)
from insurance_harness.knowledge_compiler.schema_wiki_release_596_1 import (
    SchemaWikiCompilationError,
    build_schema_wiki_review_bundle_596_1,
    compile_schema_wiki_release_596_1,
)
from tests.test_expert_golden_admission_596_2_119 import (
    _approved_cases,
    _candidate_v2,
)
from tests.test_schema_wiki_release_596_1 import (
    _candidate_and_authority,
    _candidate_and_authority_from_cases,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _target(join: Schema67CitationAuthorityJoinReceiptV1) -> Schema67GoldenEvidenceTargetV1:
    payload: dict[str, object] = {
        "contract": "schema67-golden-evidence-target.v1",
        "source_role": join.source_role,
        "live_revision_source_receipt_sha256": (join.live_revision_source_receipt_sha256),
        "revision_source_id": join.live_revision_source_receipt.revision_source_id,
        "knowledge_id": join.knowledge_id,
        "evidence_parse_attempt_id": join.evidence_parse_attempt_id,
        "weknora_parse_attempt": join.weknora_parse_attempt,
        "file_sha256": join.file_sha256,
        "parsed_document_sha256": join.parsed_document_sha256,
        "parse_manifest_sha256": join.parse_manifest_sha256,
        "weknora_manifest_algorithm": join.weknora_manifest_algorithm,
        "weknora_manifest_digest": join.weknora_manifest_digest,
        "chunk_id": join.chunk_id,
        "page_number": join.page_number,
        "locator_kind": join.locator_kind,
        "locator_ref": join.locator_ref,
        "quote_sha256": join.quote_sha256,
        "content_sha256": join.locator_content_sha256,
        "bbox_evaluation": "required",
        "coordinate_space": join.target_coordinate_space,
        "bbox": join.normalized_bbox,
        "page_width": join.page_width,
        "page_height": join.page_height,
        "rotation_degrees": join.rotation_degrees,
    }
    return Schema67GoldenEvidenceTargetV1.model_validate(
        {
            **payload,
            "target_sha256": schema_wiki_sha256("schema67-golden-evidence-target.v1", payload),
        }
    )


def _golden(
    candidate: Schema67CandidateV2,
    authority: Schema67CandidateEvidenceAuthorityV1,
) -> Schema67GoldenSet5961V1:
    joins_by_field: dict[str, list[Schema67CitationAuthorityJoinReceiptV1]] = {}
    for join in authority.join_receipts:
        joins_by_field.setdefault(join.field_id, []).append(join)
    fields: list[Schema67GoldenFieldV1] = []
    for output in candidate.fields:
        evidence_targets = tuple(_target(join) for join in joins_by_field.get(output.field_id, ()))
        canonical_value = output.value_snapshot
        field_payload = {
            "contract": "schema67-golden-field.v1",
            "field_id": output.field_id,
            "state": output.state,
            "value_schema": "scalar",
            "canonical_value": canonical_value,
            "accepted_values": (() if canonical_value is None else (canonical_value,)),
            "normalization_rule_id": "schema67-nfc-trim-exact.v1",
            "evidence_targets": evidence_targets,
            "risk_level": "critical" if output.field_id == "product_code" else "standard",
            "conflict_status": ("resolved" if output.field_id == "product_code" else "agreed"),
            "annotator_decision_sha256s": (
                _sha(f"annotator-a:{output.field_id}"),
                _sha(f"annotator-b:{output.field_id}"),
            ),
            "adjudication_sha256": (
                _sha("adjudicator:product_code") if output.field_id == "product_code" else None
            ),
        }
        fields.append(
            Schema67GoldenFieldV1.model_validate(
                {
                    **field_payload,
                    "field_sha256": schema_wiki_sha256(
                        "schema67-golden-field.v1", field_payload
                    ),
                }
            )
        )
    schema_pack = compile_schema_wiki_release_596_1(
        candidate=candidate,
        evidence_authority=authority,
    ).schema_pack
    golden_payload: dict[str, object] = {
        "contract": "schema67-golden-set-596-1.v1",
        "golden_id": "596-1-test-only-human-golden",
        "golden_version": "test.v1",
        "product_version_id": "596-1",
        "entity_version_id": "ping-an-e-sheng-bao@596-1",
        "schema_pack_id": schema_pack.schema_pack_id,
        "schema_pack_sha256": schema_pack.schema_pack_sha256,
        "ordered_field_ids": candidate.ordered_field_ids,
        "source_authorities": authority.source_authorities,
        "fields": tuple(fields),
        "annotator_principal_ids": (
            "human:test-annotator-a",
            "human:test-annotator-b",
        ),
        "whole_batch_approval_receipt_sha256": _sha("test-only-human-approval"),
        "normalization_policy_sha256": NORMALIZATION_POLICY_SHA256,
        "risk_policy_sha256": RISK_POLICY_SHA256,
        "metric_policy_sha256": METRIC_POLICY_SHA256,
    }
    return Schema67GoldenSet5961V1.model_validate(
        {
            **golden_payload,
            "golden_set_sha256": schema_wiki_sha256(
                "schema67-golden-set-596-1.v1", golden_payload
            ),
        }
    )


def _non_fixture_candidate_and_authority(
    *, value_snapshot: str | None = None,
) -> tuple[Schema67CandidateV2, Schema67CandidateEvidenceAuthorityV1]:
    cases = list(_approved_cases())
    case_index = (
        next(
            index
            for index, row in enumerate(cases)
            if row.field_output.state == "present"
        )
        if value_snapshot is not None
        else 0
    )
    first = cases[case_index]
    changed = first.field_output.model_copy(
        update={
            "value_snapshot": (
                value_snapshot
                if value_snapshot is not None
                else f"{first.field_output.value_snapshot}（独立合成值）"
            )
        }
    )
    cases[case_index] = EvidenceReplayCaseV1(
        case_id=f"{first.case_id}:golden-gate",
        field_output=changed,
        documents=first.documents,
        manifests=first.manifests,
    )
    exact_cases = tuple(cases)
    candidate = _candidate_v2(exact_cases)
    return _candidate_and_authority_from_cases(candidate, exact_cases)


_APPROVER_KEYS = (
    Ed25519PrivateKey.from_private_bytes(b"a" * 32),
    Ed25519PrivateKey.from_private_bytes(b"b" * 32),
)
_EVALUATOR_KEY = Ed25519PrivateKey.from_private_bytes(b"e" * 32)
_EVALUATION_BUNDLE_VECTOR = (
    Path(__file__).parent
    / "fixtures"
    / "schema67_golden_evaluation_bundle_596_1.json"
)


class _TestCredentialSource(Schema67GoldenQualityEvaluatorSigningCredentialSource):
    def __init__(self, key: Ed25519PrivateKey = _EVALUATOR_KEY) -> None:
        self._key = key

    def load_ed25519_private_key(self, signer_key_id: str) -> Ed25519PrivateKey:
        assert signer_key_id == "test-golden-evaluator"
        return self._key


def _public_key_text(key: Ed25519PrivateKey) -> str:
    return (
        base64.urlsafe_b64encode(
            key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        )
        .rstrip(b"=")
        .decode("ascii")
    )


def _compose_test_evaluator(
    *,
    approver_keys: tuple[tuple[str, str], ...] | None = None,
    credential_source: Schema67GoldenQualityEvaluatorSigningCredentialSource
    | None = None,
) -> Schema67GoldenQualityEvaluatorAuthority:
    configured_approver_keys = (
        approver_keys
        if approver_keys is not None
        else tuple(
            (f"test-golden-human-{index + 1}", _public_key_text(key))
            for index, key in enumerate(_APPROVER_KEYS)
        )
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HARNESS_WEKNORA_BASE_URL", "https://not-used.invalid")
        patch.setenv("HARNESS_WEKNORA_API_KEY", "not-used")
        patch.setenv(
            "HARNESS_SCHEMA67_GOLDEN_APPROVER_PUBLIC_KEYS",
            json.dumps(configured_approver_keys),
        )
        patch.setenv(
            "HARNESS_SCHEMA67_GOLDEN_EVALUATOR_SIGNER_KEY_ID",
            "test-golden-evaluator",
        )
        patch.setenv(
            "HARNESS_SCHEMA67_GOLDEN_EVALUATOR_PUBLIC_KEY_BASE64",
            _public_key_text(_EVALUATOR_KEY),
        )
        return compose_schema67_golden_quality_evaluator_authority_596_1(
            signer_credential_source=(
                _TestCredentialSource()
                if credential_source is None
                else credential_source
            ),
            now_epoch=1_786_000_100,
        )


def _approval(
    golden: Schema67GoldenSet5961V1,
    *,
    ordinal: int,
) -> Schema67GoldenApprovalV1:
    key_id = f"test-golden-human-{ordinal + 1}"
    payload = {
        "contract": "schema67-golden-approval.v1",
        "domain": "insurancekb.schema67-golden-approval.596-1.v1",
        "action": "approve",
        "principal_id": f"human:test-golden-{ordinal + 1}",
        "golden_set_sha256": golden.golden_set_sha256,
        "golden_version": golden.golden_version,
        "product_version_id": golden.product_version_id,
        "entity_version_id": golden.entity_version_id,
        "schema_pack_sha256": golden.schema_pack_sha256,
        "ordered_field_ids_sha256": schema_wiki_sha256(
            "schema67-golden-ordered-fields.v1",
            {"ordered_field_ids": golden.ordered_field_ids},
        ),
        "source_authorities_sha256": schema_wiki_sha256(
            "schema67-golden-source-authorities.v1",
            {"source_authorities": golden.source_authorities},
        ),
        "policies_sha256": schema_wiki_sha256(
            "schema67-golden-policies.v1",
            {
                "normalization_policy_sha256": golden.normalization_policy_sha256,
                "risk_policy_sha256": golden.risk_policy_sha256,
                "metric_policy_sha256": golden.metric_policy_sha256,
            },
        ),
        "issued_at": 1_786_000_000,
        "expires_at": 1_786_086_400,
        "signer_key_id": key_id,
    }
    unsigned = Schema67GoldenApprovalV1.model_construct(
        **payload,  # type: ignore[arg-type]
        signature="",
        approval_sha256="0" * 64,
    )
    signature = (
        base64.urlsafe_b64encode(
            _APPROVER_KEYS[ordinal].sign(schema67_golden_approval_signing_bytes(unsigned))
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    signed_payload = {**payload, "signature": signature}
    return Schema67GoldenApprovalV1.model_validate(
        {
            **signed_payload,
            "approval_sha256": schema_wiki_sha256(
                "schema67-golden-approval.v1", signed_payload
            ),
        }
    )


def _security(
    golden: Schema67GoldenSet5961V1,
) -> tuple[
    tuple[Schema67GoldenApprovalV1, Schema67GoldenApprovalV1],
    Schema67GoldenQualityEvaluatorAuthority,
]:
    approvals = (_approval(golden, ordinal=0), _approval(golden, ordinal=1))

    authority = _compose_test_evaluator()
    return approvals, authority


def _evaluate(
    *,
    candidate: Schema67CandidateV2,
    authority: Schema67CandidateEvidenceAuthorityV1,
    golden: Schema67GoldenSet5961V1,
    fixture_provenance: object | None = None,
) -> Schema67GoldenEvaluationResultV1:
    approvals, evaluator = _security(golden)
    if fixture_provenance is not None:
        return evaluator.evaluate_provider_zero_fixture(
            candidate=candidate,
            evidence_authority=authority,
            fixture_provenance=fixture_provenance,
            golden=golden,
            golden_approvals=approvals,
        )
    return evaluator.evaluate(
        candidate=candidate,
        evidence_authority=authority,
        golden=golden,
        golden_approvals=approvals,
    )


def _fixture_provenance(
    candidate: Schema67CandidateV2,
    authority: Schema67CandidateEvidenceAuthorityV1,
) -> object:
    factory = getattr(
        quality_gate_module,
        "make_schema67_provider_zero_fixture_provenance_596_1",
        None,
    )
    assert callable(factory), "provider-zero fixture provenance factory is missing"
    return factory(candidate=candidate, evidence_authority=authority)


def _synthetic_evaluation_bundle_vector() -> Schema67GoldenEvaluationReviewBundleV1:
    candidate, authority = _non_fixture_candidate_and_authority()
    result = _evaluate(
        candidate=candidate,
        authority=authority,
        golden=_golden(candidate, authority),
    )
    assert result.status == "PASS"
    assert result.quality_gate_receipt is not None
    return make_schema67_golden_evaluation_review_bundle_596_1(result)


def test_current_and_frozen_evaluation_bundles_are_canonical_and_ordered67() -> None:
    current = _synthetic_evaluation_bundle_vector()
    current_payload = current.model_dump(mode="json")
    current_bytes = (
        json.dumps(
            current_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    assert (
        Schema67GoldenEvaluationReviewBundleV1.model_validate_json(current_bytes)
        == current
    )
    frozen_bytes = _EVALUATION_BUNDLE_VECTOR.read_bytes()
    frozen_payload = json.loads(frozen_bytes)
    assert frozen_bytes == (
        json.dumps(
            frozen_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    frozen = Schema67GoldenEvaluationReviewBundleV1.model_validate(frozen_payload)

    for bundle in (frozen, current):
        assert bundle.contract == "schema67-golden-evaluation-review-bundle.v1"
        assert bundle.evaluation_id == bundle.quality_gate_receipt.receipt_sha256
        assert tuple(row.field_id for row in bundle.private_dossier.field_decisions) == (
            APPROVED_ORDERED_FIELD_IDS
        )
        assert "canonical_value" not in json.dumps(
            bundle.public_aggregate.model_dump(mode="json"), ensure_ascii=False
        )


def test_provider_zero_candidate_is_fixture_only_and_never_issues_pass() -> None:
    candidate, authority = _candidate_and_authority()
    result = _evaluate(
        candidate=candidate,
        authority=authority,
        golden=_golden(candidate, authority),
        fixture_provenance=_fixture_provenance(candidate, authority),
    )

    assert result.status == "FIXTURE_ONLY"
    assert result.quality_gate_receipt is None
    assert result.provider_calls == 0
    assert result.draft_calls == 0


def test_provider_zero_fixture_status_does_not_depend_on_candidate_sha256() -> None:
    candidate, authority = _non_fixture_candidate_and_authority()
    result = _evaluate(
        candidate=candidate,
        authority=authority,
        golden=_golden(candidate, authority),
        fixture_provenance=_fixture_provenance(candidate, authority),
    )

    assert result.status == "FIXTURE_ONLY"
    assert result.quality_gate_receipt is None


def test_provider_zero_fixture_provenance_is_required_and_bound_closed_world() -> None:
    candidate, authority = _candidate_and_authority()
    golden = _golden(candidate, authority)
    approvals, evaluator = _security(golden)
    evaluate_fixture = getattr(evaluator, "evaluate_provider_zero_fixture", None)
    assert callable(evaluate_fixture), "provider-zero fixture evaluator is missing"
    provenance = _fixture_provenance(candidate, authority)

    for invalid in (None, object(), object.__new__(type(provenance))):
        with pytest.raises(Schema67GoldenQualityGateError) as caught:
            evaluate_fixture(
                candidate=candidate,
                evidence_authority=authority,
                fixture_provenance=invalid,
                golden=golden,
                golden_approvals=approvals,
            )
        assert caught.value.reason_code == "PROVIDER_ZERO_FIXTURE_PROVENANCE_INVALID"

    drifted_candidate, drifted_authority = _non_fixture_candidate_and_authority()
    with pytest.raises(Schema67GoldenQualityGateError) as drifted:
        evaluate_fixture(
            candidate=drifted_candidate,
            evidence_authority=drifted_authority,
            fixture_provenance=provenance,
            golden=_golden(drifted_candidate, drifted_authority),
            golden_approvals=_security(
                _golden(drifted_candidate, drifted_authority)
            )[0],
        )
    assert drifted.value.reason_code == "PROVIDER_ZERO_FIXTURE_PROVENANCE_INVALID"


def test_exact_candidate_and_revision_custody_produce_private_and_public_outputs() -> None:
    candidate, authority = _non_fixture_candidate_and_authority()
    result = _evaluate(
        candidate=candidate,
        authority=authority,
        golden=_golden(candidate, authority),
    )

    assert result.status == "PASS"
    assert result.quality_gate_receipt is not None
    assert len(result.private_dossier.field_decisions) == 67
    assert tuple(metric.metric_id for metric in result.public_aggregate.metrics) == (
        GOLDEN_METRIC_IDS
    )
    assert all(metric.denominator is not None for metric in result.public_aggregate.metrics)
    assert "canonical_value" not in json.dumps(
        result.public_aggregate.model_dump(mode="json"), ensure_ascii=False
    )
    assert (
        validate_schema67_golden_quality_gate_receipt_596_1(
            result.quality_gate_receipt,
            candidate=candidate,
            evidence_authority=authority,
        )
        is result.quality_gate_receipt
    )


def test_wrong_value_and_absent_unknown_confusion_fail_without_draft_authority() -> None:
    candidate, authority = _non_fixture_candidate_and_authority()
    golden = _golden(candidate, authority)
    fields = list(golden.fields)
    field_index = next(
        index for index, field in enumerate(fields) if field.state == "present"
    )
    first = fields[field_index]
    changed_payload = first.model_dump(mode="python", exclude={"field_sha256"})
    changed_payload["canonical_value"] = "不匹配值"
    changed_payload["accepted_values"] = ("不匹配值",)
    fields[field_index] = Schema67GoldenFieldV1.model_validate(
        {
            **changed_payload,
            "field_sha256": schema_wiki_sha256("schema67-golden-field.v1", changed_payload),
        }
    )
    golden_payload = golden.model_dump(mode="python", exclude={"golden_set_sha256"})
    golden_payload["fields"] = tuple(fields)
    changed_golden = Schema67GoldenSet5961V1.model_validate(
        {
            **golden_payload,
            "golden_set_sha256": schema_wiki_sha256("schema67-golden-set-596-1.v1", golden_payload),
        }
    )

    result = _evaluate(
        candidate=candidate,
        authority=authority,
        golden=changed_golden,
    )

    assert result.status == "FAIL"
    assert result.quality_gate_receipt is None
    assert result.draft_calls == result.review_calls == result.activation_calls == 0


def test_present_value_metrics_use_normalized_atom_tp_fp_fn() -> None:
    candidate, authority = _non_fixture_candidate_and_authority(
        value_snapshot='["A","C"]'
    )
    golden = _golden(candidate, authority)
    fields = list(golden.fields)
    field_index = next(
        index
        for index, output in enumerate(candidate.fields)
        if output.value_snapshot == '["A","C"]'
    )
    first = fields[field_index]
    field_payload = first.model_dump(mode="python", exclude={"field_sha256"})
    field_payload.update(
        value_schema="ordered_list",
        canonical_value='["A","B"]',
        accepted_values=('["A","B"]',),
    )
    fields[field_index] = Schema67GoldenFieldV1.model_validate(
        {
            **field_payload,
            "field_sha256": schema_wiki_sha256(
                "schema67-golden-field.v1", field_payload
            ),
        }
    )
    golden_payload = golden.model_dump(mode="python", exclude={"golden_set_sha256"})
    golden_payload["fields"] = tuple(fields)
    partial_golden = Schema67GoldenSet5961V1.model_validate(
        {
            **golden_payload,
            "golden_set_sha256": schema_wiki_sha256(
                "schema67-golden-set-596-1.v1", golden_payload
            ),
        }
    )

    result = _evaluate(
        candidate=candidate,
        authority=authority,
        golden=partial_golden,
    )

    decision = result.private_dossier.field_decisions[field_index]
    assert (decision.atom_true_positive, decision.atom_false_positive) == (1, 1)
    assert decision.atom_false_negative == 1
    metrics = {metric.metric_id: metric for metric in result.public_aggregate.metrics}
    present_decisions = tuple(
        row
        for row in result.private_dossier.field_decisions
        if row.golden_state == "present"
    )
    atom_tp = sum(row.atom_true_positive for row in present_decisions)
    atom_fp = sum(row.atom_false_positive for row in present_decisions)
    atom_fn = sum(row.atom_false_negative for row in present_decisions)
    assert (
        metrics[GOLDEN_METRIC_IDS[2]].numerator,
        metrics[GOLDEN_METRIC_IDS[2]].denominator,
    ) == (atom_tp, atom_tp + atom_fp)
    assert (
        metrics[GOLDEN_METRIC_IDS[3]].numerator,
        metrics[GOLDEN_METRIC_IDS[3]].denominator,
    ) == (atom_tp, atom_tp + atom_fn)
    precision_ppm = metrics[GOLDEN_METRIC_IDS[2]].value_ppm
    recall_ppm = metrics[GOLDEN_METRIC_IDS[3]].value_ppm
    f1_ppm = metrics[GOLDEN_METRIC_IDS[4]].value_ppm
    assert precision_ppm is not None and precision_ppm < 1_000_000
    assert recall_ppm is not None and recall_ppm < 1_000_000
    assert f1_ppm is not None and f1_ppm < 1_000_000
    assert result.status == "FAIL"
    assert result.quality_gate_receipt is None


def test_golden_is_closed_and_rejects_self_generated_candidate_authority() -> None:
    candidate, authority = _non_fixture_candidate_and_authority()
    payload = _golden(candidate, authority).model_dump(mode="python")
    payload["candidate_sha256"] = candidate.candidate_sha256

    with pytest.raises(ValidationError):
        Schema67GoldenSet5961V1.model_validate(payload)

    model_generated = _golden(candidate, authority).model_dump(mode="python")
    model_generated["annotator_principal_ids"] = (
        "model:deepseek-v4-flash",
        "human:test-annotator-b",
    )
    model_generated["golden_set_sha256"] = schema_wiki_sha256(
        "schema67-golden-set-596-1.v1",
        {key: value for key, value in model_generated.items() if key != "golden_set_sha256"},
    )
    with pytest.raises(ValidationError):
        Schema67GoldenSet5961V1.model_validate(model_generated)


def test_golden_requires_two_distinct_trusted_human_approvals() -> None:
    candidate, authority = _non_fixture_candidate_and_authority()
    golden = _golden(candidate, authority)
    approvals, evaluator = _security(golden)

    assert not hasattr(quality_gate_module, "evaluate_schema67_golden_quality_596_1")
    assert tuple(inspect.signature(evaluator.evaluate).parameters) == (
        "candidate",
        "evidence_authority",
        "golden",
        "golden_approvals",
    )
    assert tuple(
        inspect.signature(
            compose_schema67_golden_quality_evaluator_authority_596_1
        ).parameters
    ) == ("signer_credential_source", "now_epoch")
    with pytest.raises(Schema67GoldenQualityGateError) as direct_constructor:
        Schema67GoldenQualityEvaluatorAuthority(
            object(), object(), object()  # type: ignore[arg-type]
        )
    assert (
        direct_constructor.value.reason_code
        == "GOLDEN_EVALUATOR_AUTHORITY_UNAVAILABLE"
    )
    with pytest.raises(AttributeError):
        evaluator._approval_verifier = object()  # type: ignore[assignment]
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HARNESS_WEKNORA_BASE_URL", "https://not-used.invalid")
        patch.setenv("HARNESS_WEKNORA_API_KEY", "not-used")
        patch.setenv("HARNESS_SCHEMA67_GOLDEN_APPROVER_PUBLIC_KEYS", "[]")
        patch.setenv("HARNESS_SCHEMA67_GOLDEN_EVALUATOR_SIGNER_KEY_ID", "")
        patch.setenv("HARNESS_SCHEMA67_GOLDEN_EVALUATOR_PUBLIC_KEY_BASE64", "")
        with pytest.raises(Schema67GoldenQualityGateError) as missing:
            compose_schema67_golden_quality_evaluator_authority_596_1(
                signer_credential_source=None,
                now_epoch=1_786_000_100,
            )
    assert missing.value.reason_code == "GOLDEN_EVALUATOR_AUTHORITY_UNAVAILABLE"

    duplicate_material = _public_key_text(_APPROVER_KEYS[0])
    with pytest.raises(Schema67GoldenQualityGateError) as duplicate_keys:
        _compose_test_evaluator(
            approver_keys=(
                ("test-golden-human-1", duplicate_material),
                ("test-golden-human-2", duplicate_material),
            )
        )
    assert duplicate_keys.value.reason_code == "GOLDEN_APPROVER_KEY_RING_INVALID"

    with pytest.raises(Schema67GoldenQualityGateError) as duplicate_ids:
        _compose_test_evaluator(
            approver_keys=(
                ("test-golden-human", _public_key_text(_APPROVER_KEYS[0])),
                ("test-golden-human", _public_key_text(_APPROVER_KEYS[1])),
            )
        )
    assert duplicate_ids.value.reason_code == "GOLDEN_APPROVER_KEY_RING_INVALID"

    with pytest.raises(Schema67GoldenQualityGateError) as duplicate:
        evaluator.evaluate(
            candidate=candidate,
            evidence_authority=authority,
            golden=golden,
            golden_approvals=(approvals[0], approvals[0]),
        )
    assert duplicate.value.reason_code == "GOLDEN_APPROVAL_INVALID"

    attacker_key = Ed25519PrivateKey.from_private_bytes(b"x" * 32)
    forged = approvals[0].model_dump(mode="python", exclude={"approval_sha256"})
    unsafe = Schema67GoldenApprovalV1.model_construct(
        **{**forged, "signature": ""},
        approval_sha256="0" * 64,
    )
    forged["signature"] = (
        base64.urlsafe_b64encode(
            attacker_key.sign(schema67_golden_approval_signing_bytes(unsafe))
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    forged_approval = Schema67GoldenApprovalV1.model_validate(
        {
            **forged,
            "approval_sha256": schema_wiki_sha256(
                "schema67-golden-approval.v1", forged
            ),
        }
    )
    with pytest.raises(Schema67GoldenQualityGateError) as self_signed:
        evaluator.evaluate(
            candidate=candidate,
            evidence_authority=authority,
            golden=golden,
            golden_approvals=(forged_approval, approvals[1]),
        )
    assert self_signed.value.reason_code == "GOLDEN_APPROVAL_INVALID"


def test_pass_receipt_is_required_and_factory_provenance_cannot_be_reparsed() -> None:
    candidate, authority = _non_fixture_candidate_and_authority()
    evaluation = _evaluate(
        candidate=candidate,
        authority=authority,
        golden=_golden(candidate, authority),
    )
    assert evaluation.quality_gate_receipt is not None
    release = compile_schema_wiki_release_596_1(
        candidate=candidate,
        evidence_authority=authority,
    )

    with pytest.raises(TypeError):
        build_schema_wiki_review_bundle_596_1(  # type: ignore[call-arg]
            candidate=candidate, release=release
        )

    bundle = build_schema_wiki_review_bundle_596_1(
        candidate=candidate,
        evidence_authority=authority,
        release=release,
        quality_gate_receipt=evaluation.quality_gate_receipt,
    )
    assert bundle.quality_gate_receipt.receipt_sha256 == (
        evaluation.quality_gate_receipt.receipt_sha256
    )

    reparsed = type(evaluation.quality_gate_receipt).model_validate(
        evaluation.quality_gate_receipt.model_dump(mode="python")
    )
    with pytest.raises(SchemaWikiCompilationError) as caught:
        build_schema_wiki_review_bundle_596_1(
            candidate=candidate,
            evidence_authority=authority,
            release=release,
            quality_gate_receipt=reparsed,
        )
    assert caught.value.reason_code == "QUALITY_GATE_RECEIPT_INVALID"


def test_missing_candidate_and_threshold_or_identity_drift_fail_closed() -> None:
    candidate, authority = _non_fixture_candidate_and_authority()
    golden = _golden(candidate, authority)
    approvals, evaluator = _security(golden)
    with pytest.raises(Schema67GoldenQualityGateError) as caught:
        evaluator.evaluate(
            candidate=None,
            evidence_authority=authority,
            golden=golden,
            golden_approvals=approvals,
        )
    assert caught.value.reason_code == "CANDIDATE_ABSENT"

    forged = copy.deepcopy(golden.model_dump(mode="python"))
    forged["ordered_field_ids"] = tuple(reversed(forged["ordered_field_ids"]))
    with pytest.raises(ValidationError):
        Schema67GoldenSet5961V1.model_validate(forged)

    threshold_drift = golden.model_dump(mode="python")
    threshold_drift["metric_policy_sha256"] = "f" * 64
    threshold_drift["golden_set_sha256"] = schema_wiki_sha256(
        "schema67-golden-set-596-1.v1",
        {key: value for key, value in threshold_drift.items() if key != "golden_set_sha256"},
    )
    with pytest.raises(ValidationError):
        Schema67GoldenSet5961V1.model_validate(threshold_drift)

    with pytest.raises(ValidationError):
        Schema67GoldenMetricV1.model_validate(
            {
                "metric_id": GOLDEN_METRIC_IDS[0],
                "numerator": 67,
                "denominator": None,
                "value_ppm": None,
                "supports": (67,),
                "evaluability": "NOT_EVALUABLE",
                "sample_size": "NOT_EVALUABLE",
                "wilson_low_ppm": None,
                "wilson_high_ppm": None,
                "admission_status": "FAIL",
                "metric_sha256": "0" * 64,
            }
        )


@pytest.mark.parametrize("drift", ["page", "bbox"])
def test_rehashed_page_or_bbox_drift_fails_without_pass_receipt(drift: str) -> None:
    candidate, authority = _non_fixture_candidate_and_authority()
    golden = _golden(candidate, authority)
    fields = list(golden.fields)
    field_index = next(index for index, field in enumerate(fields) if field.evidence_targets)
    field = fields[field_index]
    targets = list(field.evidence_targets)
    target_payload = targets[0].model_dump(mode="python", exclude={"target_sha256"})
    if drift == "page":
        target_payload["page_number"] += 1
    else:
        bbox = target_payload["bbox"]
        target_payload["bbox"] = {**bbox, "x0": bbox["x1"] - 1}
    targets[0] = Schema67GoldenEvidenceTargetV1.model_validate(
        {
            **target_payload,
            "target_sha256": schema_wiki_sha256(
                "schema67-golden-evidence-target.v1", target_payload
            ),
        }
    )
    field_payload = field.model_dump(mode="python", exclude={"field_sha256"})
    field_payload["evidence_targets"] = tuple(targets)
    fields[field_index] = Schema67GoldenFieldV1.model_validate(
        {
            **field_payload,
            "field_sha256": schema_wiki_sha256("schema67-golden-field.v1", field_payload),
        }
    )
    golden_payload = golden.model_dump(mode="python", exclude={"golden_set_sha256"})
    golden_payload["fields"] = tuple(fields)
    drifted = Schema67GoldenSet5961V1.model_validate(
        {
            **golden_payload,
            "golden_set_sha256": schema_wiki_sha256("schema67-golden-set-596-1.v1", golden_payload),
        }
    )

    result = _evaluate(
        candidate=candidate,
        authority=authority,
        golden=drifted,
    )

    assert result.status == "FAIL"
    assert result.quality_gate_receipt is None
    assert result.draft_calls == result.review_calls == result.activation_calls == 0


@pytest.mark.parametrize(
    ("mode", "expected_iou"),
    [("exact", 1_000_000), ("partial", 500_000), ("zero", 0)],
)
def test_bbox_metric_reports_actual_fragment_iou(
    mode: str,
    expected_iou: int,
) -> None:
    candidate, authority = _non_fixture_candidate_and_authority()
    golden = _golden(candidate, authority)
    fields = list(golden.fields)
    field_index = next(index for index, field in enumerate(fields) if field.evidence_targets)
    field = fields[field_index]
    targets = list(field.evidence_targets)
    if mode != "exact":
        target_payload = targets[0].model_dump(
            mode="python", exclude={"target_sha256"}
        )
        bbox = target_payload["bbox"]
        width = bbox["x1"] - bbox["x0"]
        if mode == "partial":
            replacement = {**bbox, "x0": bbox["x0"] + width // 2}
        elif bbox["x1"] + width <= 1_000_000:
            replacement = {
                **bbox,
                "x0": bbox["x1"],
                "x1": bbox["x1"] + width,
            }
        else:
            replacement = {
                **bbox,
                "x0": bbox["x0"] - width,
                "x1": bbox["x0"],
            }
        target_payload["bbox"] = replacement
        targets[0] = Schema67GoldenEvidenceTargetV1.model_validate(
            {
                **target_payload,
                "target_sha256": schema_wiki_sha256(
                    "schema67-golden-evidence-target.v1", target_payload
                ),
            }
        )
        field_payload = field.model_dump(mode="python", exclude={"field_sha256"})
        field_payload["evidence_targets"] = tuple(targets)
        fields[field_index] = Schema67GoldenFieldV1.model_validate(
            {
                **field_payload,
                "field_sha256": schema_wiki_sha256(
                    "schema67-golden-field.v1", field_payload
                ),
            }
        )
        golden_payload = golden.model_dump(
            mode="python", exclude={"golden_set_sha256"}
        )
        golden_payload["fields"] = tuple(fields)
        golden = Schema67GoldenSet5961V1.model_validate(
            {
                **golden_payload,
                "golden_set_sha256": schema_wiki_sha256(
                    "schema67-golden-set-596-1.v1", golden_payload
                ),
            }
        )

    result = _evaluate(candidate=candidate, authority=authority, golden=golden)
    decision = result.private_dossier.field_decisions[field_index]
    assert decision.bbox_iou_ppm_values[0] == expected_iou
    bbox_metric = result.public_aggregate.metrics[11]
    all_ious = tuple(
        value
        for row in result.private_dossier.field_decisions
        for value in row.bbox_iou_ppm_values
    )
    assert bbox_metric.numerator == sum(all_ious)
    assert bbox_metric.denominator == len(all_ious) * 1_000_000


def test_manifest_drift_cannot_reuse_a_pass_receipt_or_review_bundle() -> None:
    candidate, authority = _non_fixture_candidate_and_authority()
    evaluation = _evaluate(
        candidate=candidate,
        authority=authority,
        golden=_golden(candidate, authority),
    )
    assert evaluation.quality_gate_receipt is not None
    release = compile_schema_wiki_release_596_1(
        candidate=candidate,
        evidence_authority=authority,
    )
    bundle = build_schema_wiki_review_bundle_596_1(
        candidate=candidate,
        evidence_authority=authority,
        release=release,
        quality_gate_receipt=evaluation.quality_gate_receipt,
    )
    drifted_payload = bundle.model_dump(mode="python", exclude={"review_bundle_sha256"})
    drifted_payload["manifest_digest"] = "f" * 64
    drifted = type(bundle).model_validate(
        {
            **drifted_payload,
            "review_bundle_sha256": schema_wiki_sha256(
                "schema-wiki-review-bundle.v1", drifted_payload
            ),
        }
    )

    with pytest.raises(SchemaWikiContractError):
        validate_schema_wiki_review_bundle(drifted, release)
