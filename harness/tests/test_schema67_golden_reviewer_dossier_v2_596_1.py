from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from insurance_harness.goldenset.schema67_golden_quality_gate_596_1 import (
    Schema67GoldenReviewSuccessorMetadataV1,
    SchemaWikiGoldenQualityDossierV2,
    make_schema67_golden_evaluation_review_bundle_596_1,
    validate_schema67_golden_review_successor_metadata_596_1,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import schema_wiki_sha256
from tests.test_schema67_golden_quality_gate_596_1 import (
    _evaluate,
    _golden,
    _non_fixture_candidate_and_authority,
)

_VECTOR = Path(__file__).parent / "fixtures" / "schema67_golden_reviewer_dossier_v2_596_1.json"


def _formal() -> tuple[object, object, object, object, Schema67GoldenReviewSuccessorMetadataV1]:
    candidate, authority = _non_fixture_candidate_and_authority()
    golden = _golden(candidate, authority)
    result = _evaluate(candidate=candidate, authority=authority, golden=golden)
    assert result.quality_gate_receipt is not None
    evaluation = make_schema67_golden_evaluation_review_bundle_596_1(result)
    dossier = SchemaWikiGoldenQualityDossierV2.model_validate_json(_VECTOR.read_bytes())
    return candidate, authority, golden, evaluation, dossier.review_successor


def test_formal_dossier_v2_cross_language_vector_is_exact67_and_closed() -> None:
    dossier = SchemaWikiGoldenQualityDossierV2.model_validate_json(_VECTOR.read_bytes())
    expected = (
        json.dumps(
            dossier.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )

    assert _VECTOR.read_bytes() == expected
    assert dossier.version == "schema-wiki-golden-quality-dossier.v2"
    assert len(dossier.review_successor.ordered_fields) == 67
    assert all(row.review_status == "REVIEWED" for row in dossier.review_successor.ordered_fields)
    assert dossier.review_successor.human_review_layer.reviewed_by == "linyao"
    assert dossier.review_successor.human_review_layer.receipt_status == "VERIFIED"


def test_current_metadata_incomplete_successor_cannot_become_formal_v2() -> None:
    _, _, _, _, successor = _formal()
    payload = successor.model_dump(mode="python")
    payload["human_review_layer"] = {
        **payload["human_review_layer"],
        "reviewed_at": None,
        "receipt_status": "UNVERIFIED",
        "review_receipt_sha256": None,
    }
    ordered_fields = list(payload["ordered_fields"])
    ordered_fields[0] = {
        **ordered_fields[0],
        "review_status": "PENDING_RESIDUAL",
        "reason_codes": ("TRI_STATE_CONFLICT",),
    }
    payload["ordered_fields"] = tuple(ordered_fields)
    payload["metadata_sha256"] = schema_wiki_sha256(
        "schema67-golden-review-successor-metadata.v1",
        {key: value for key, value in payload.items() if key != "metadata_sha256"},
    )

    with pytest.raises(ValueError):
        Schema67GoldenReviewSuccessorMetadataV1.model_validate(payload)


def test_fully_rehashed_candidate_evidence_substitution_is_rejected() -> None:
    candidate, authority, golden, evaluation, successor = _formal()
    payload = successor.model_dump(mode="python")
    field_index = next(
        index for index, row in enumerate(payload["ordered_fields"]) if row["evidence_changes"]
    )
    field = copy.deepcopy(payload["ordered_fields"][field_index])
    change = field["evidence_changes"][0]
    change["candidate_evidence_id"] = "f" * 64
    change["change_sha256"] = schema_wiki_sha256(
        "schema67-golden-evidence-change.v1",
        {key: value for key, value in change.items() if key != "change_sha256"},
    )
    field["field_metadata_sha256"] = schema_wiki_sha256(
        "schema67-golden-review-field-metadata.v1",
        {key: value for key, value in field.items() if key != "field_metadata_sha256"},
    )
    ordered_fields = list(payload["ordered_fields"])
    ordered_fields[field_index] = field
    payload["ordered_fields"] = tuple(ordered_fields)
    payload["metadata_sha256"] = schema_wiki_sha256(
        "schema67-golden-review-successor-metadata.v1",
        {key: value for key, value in payload.items() if key != "metadata_sha256"},
    )
    forged = Schema67GoldenReviewSuccessorMetadataV1.model_validate(payload)

    with pytest.raises(ValueError):
        validate_schema67_golden_review_successor_metadata_596_1(
            forged,
            evaluation=evaluation,
            candidate=candidate,
            evidence_authority=authority,
            golden=golden,
        )
