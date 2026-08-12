from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.goldenset.schema67_reviewed_golden_successor_596_1 import (
    Schema67ReviewedGoldenSuccessorError,
    _field_metadata_sha256,
    build_schema67_reviewed_golden_successor_596_1,
    canonical_schema67_reviewed_golden_artifact_files,
    canonical_schema67_reviewed_golden_successor_bytes,
    load_schema67_reviewed_golden_successor_596_1,
    schema67_reviewed_golden_successor_sha256,
    validate_schema67_reviewed_golden_successor_596_1,
)
from insurance_harness.knowledge_compiler.medical_schema_pack_596_1 import (
    make_medical_schema_pack_596_1,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import SchemaFieldPageV1
from insurance_harness.knowledge_compiler.schema_wiki_release_596_1 import (
    compile_schema_wiki_release_596_1,
)

_REPO = Path(__file__).resolve().parents[2]
_OLD60 = _REPO / "dataset/goldenset/gs-s0q-596-v1/596.jsonl"
_LATEST71 = _REPO / "dataset/goldenset-drafts/esheng-zunxiang-v0/annotations.jsonl"
_SUCCESSOR = (
    _REPO
    / "dataset/goldenset-drafts/schema67-reviewed-golden-successor-596-1/golden67-successor.json"
)

_NOT_COVERED = (
    "product_type",
    "marketing_tagline",
    "product_overview",
    "health_declaration_requirements",
    "eligible_occupation_classes",
    "premium_grace_period",
    "guaranteed_renewal_status",
    "premium_adjustment_rules",
    "direct_billing_and_advance_payment_rules",
    "eligible_service_packages",
    "tax_qualified_status",
    "tax_benefit_rules",
    "objection_handling_scripts",
    "product_faq",
    "four_step_sales_script",
    "sales_pitch_script",
)
_NOT_COVERED_REASON = "NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS"
_REVIEWED_51_CANONICAL_SHA256 = "76640dd6d20398b836de6443d755c769b1ee721d859f0f9b333e2b9abb498d8f"


def _inputs() -> tuple[bytes, bytes]:
    return _OLD60.read_bytes(), _LATEST71.read_bytes()


def _build() -> Any:
    old60, latest71 = _inputs()
    return build_schema67_reviewed_golden_successor_596_1(
        old60_bytes=old60,
        latest71_bytes=latest71,
    )


def _reseal(value: Any, **updates: object) -> Any:
    mutated = value.model_copy(update=updates)
    return mutated.model_copy(
        update={"golden_set_sha256": schema67_reviewed_golden_successor_sha256(mutated)}
    )


def test_exact_reviewed_inputs_are_distinct_and_metadata_is_honest() -> None:
    successor = _build()

    assert successor.old60_input.row_count == 60
    assert successor.old60_input.sha256 == (
        "562c37c7cf262e2e78f0b3ca4b7de4b0dab2f407d3cd7318a8a69b5dca33d8fb"
    )
    assert successor.old60_input.authority_level == "HUMAN_APPROVED_S0_Q_MIGRATION_INPUT"
    assert successor.old60_input.approval_receipt_sha256 == (
        "484fdb78bdc73109bccd4d771e41089574b26f28c1992b67b2114524a515c868"
    )

    assert successor.latest71_input.row_count == 71
    assert successor.latest71_input.sha256 == (
        "25c62051d04c8bd56f3770e77d071ae18945daee5dce6b8fb584937555260be4"
    )
    assert successor.latest71_input.authority_level == "HUMAN_REVIEWED_SOURCE"
    assert successor.latest71_input.annotator_model_id == "claude-fable-5"
    assert successor.review_metadata.source_review_status == "COMPLETED"
    assert successor.schema67_mapping_status == "COMPLETE_67"
    assert successor.golden_admission_status == "BLOCKED_RECEIPT_UNVERIFIED"
    assert successor.review_metadata.reviewed_by == "linyao"
    assert successor.review_metadata.reviewed_at is None
    assert successor.review_metadata.approval_receipt_sha256 is None
    assert successor.review_metadata.attestation_sources[-1].source_kind == ("USER_AUTHORITY_FACT")
    assert successor.review_metadata.attestation_sources[-1].reference == (
        "user-authority:2026-08-11:latest71-reviewed-by-linyao-confirmed-by-workspace-owner-houjing"
    )


def test_explicit_mappings_close_exact67_and_keep_uncovered_fields_unknown() -> None:
    successor = _build()
    ordered67 = make_medical_schema_pack_596_1().ordered_field_ids

    assert tuple(row.field_id for row in successor.fields) == ordered67
    assert len(successor.old60_mappings) == 80
    assert len(successor.latest71_mappings) == 81
    assert all(row.review_status == "REVIEWED" for row in successor.fields)
    assert successor.residual_pending_field_ids == ()
    assert successor.summary.reviewed_field_count == 67
    assert successor.summary.pending_residual_field_count == 0
    assert successor.summary.human_annotation_zero is False
    assert successor.summary.evaluator_formal_conclusion_allowed is False

    by_id = {row.field_id: row for row in successor.fields}
    assert by_id["product_name"].source_field_ids == ("product_name",)
    assert by_id["product_name"].mapping_action == "reuse"
    assert by_id["product_name"].state == "present"
    assert by_id["product_name"].value == "平安e生保（尊享版）医疗保险"
    for field_id in _NOT_COVERED:
        row = by_id[field_id]
        assert row.review_status == "REVIEWED"
        assert row.state == "unknown"
        assert row.value is None
        assert row.evidence == ()
        assert row.residual_reason is None
        assert row.unknown_reason == _NOT_COVERED_REASON
        assert all(evidence.page != 1 for evidence in row.evidence)


def test_existing_51_reviewed_rows_keep_exact_canonical_bytes() -> None:
    rows = [
        row.model_dump(mode="json") for row in _build().fields if row.field_id not in _NOT_COVERED
    ]
    canonical = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert len(rows) == 51
    assert hashlib.sha256(canonical).hexdigest() == _REVIEWED_51_CANONICAL_SHA256


def test_not_covered_unknowns_compile_as_normal_pages_in_exact75() -> None:
    from tests.test_expert_golden_admission_596_2_119 import (
        _approved_cases,
        _candidate_v2,
    )
    from tests.test_schema_wiki_release_596_1 import _candidate_and_authority_from_cases

    cases = tuple(
        case for case in _approved_cases() if case.field_output.field_id not in _NOT_COVERED
    )
    candidate = _candidate_v2(cases)
    candidate, authority = _candidate_and_authority_from_cases(candidate, cases)
    release = compile_schema_wiki_release_596_1(
        candidate=candidate,
        evidence_authority=authority,
    )
    pages = {
        member.field_id: member.payload
        for member in release.members
        if member.member_kind == "field"
    }

    assert len(release.members) == 75
    assert tuple(pages) == candidate.ordered_field_ids
    for field_id in _NOT_COVERED:
        page = pages[field_id]
        assert isinstance(page, SchemaFieldPageV1)
        assert page.state == "unknown"
        assert page.value_snapshot is None
        assert page.citations == ()
        assert page.evidence_receipt_sha256s == ()
        assert page.review_item_reason == "FIELD_UNKNOWN"


def test_reviewed_tri_state_and_evidence_are_direct_latest71_projections() -> None:
    successor = _build()
    latest_rows = {
        json.loads(line)["field_id"]: json.loads(line)
        for line in _LATEST71.read_bytes().splitlines()
        if line
    }
    reviewed = [row for row in successor.fields if row.field_id not in _NOT_COVERED]

    assert reviewed
    for row in reviewed:
        assert len(row.source_field_ids) == 1
        source = latest_rows[row.source_field_ids[0]]
        assert row.annotator_model_id == source["annotator_model"]
        assert row.state == source["tri_state"]
        assert row.value == source["value"]
        assert (
            row.source_record_sha256
            == hashlib.sha256(
                json.dumps(
                    source,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
        if row.state == "unknown":
            assert row.value is None and row.evidence == ()
        else:
            assert row.evidence
        for evidence in row.evidence:
            assert (
                evidence.quote_sha256 == hashlib.sha256(evidence.quote.encode("utf-8")).hexdigest()
            )
            assert evidence.bbox is None
            assert evidence.coordinate_space is None
            assert evidence.bbox_status == "PENDING_CAPTURE"

    for row in successor.fields:
        if row.field_id in _NOT_COVERED:
            assert row.state == "unknown"
            assert row.value is None
            assert row.evidence == ()
            assert row.residual_reason is None
            assert row.unknown_reason == _NOT_COVERED_REASON
            assert row.annotator_model_id == "claude-fable-5"


def test_complete_mapping_rejects_residual_semantics_even_when_rehashed() -> None:
    old60, latest71 = _inputs()
    successor = _build()
    index = next(
        index for index, row in enumerate(successor.fields) if row.field_id in _NOT_COVERED
    )
    rows = list(successor.fields)
    row_payload = rows[index].model_dump(mode="python")
    row_payload["unknown_reason"] = None
    row_payload["residual_reason"] = "LATEST_REVIEWED_SOURCE_MISSING"
    row_payload["field_metadata_sha256"] = _field_metadata_sha256(row_payload)
    rows[index] = type(rows[index]).model_construct(**row_payload)
    forged = _reseal(successor, fields=tuple(rows))

    with pytest.raises(Schema67ReviewedGoldenSuccessorError):
        validate_schema67_reviewed_golden_successor_596_1(
            forged,
            old60_bytes=old60,
            latest71_bytes=latest71,
        )


def test_ready_to_sign_payload_is_bound_but_never_fake_signed() -> None:
    successor = _build()
    receipt = successor.ready_to_sign

    assert receipt.status == "READY_TO_SIGN"
    assert receipt.golden_set_sha256 == successor.golden_set_sha256
    assert receipt.reviewed_by == "linyao"
    assert receipt.reviewed_at is None
    assert receipt.key_id is None
    assert receipt.signature is None
    assert receipt.approval_receipt_sha256 is None


@pytest.mark.parametrize(
    "mutation",
    [
        "source_hash",
        "field_reorder",
        "reviewed_value",
        "pending_value",
        "invented_reviewer",
        "fake_signature",
        "mapping",
    ],
)
def test_fully_rehashed_mutations_fail_fresh_replay(mutation: str) -> None:
    old60, latest71 = _inputs()
    successor = _build()
    if mutation == "source_hash":
        forged_input = successor.latest71_input.model_copy(update={"sha256": "f" * 64})
        forged = _reseal(successor, latest71_input=forged_input)
    elif mutation == "field_reorder":
        forged = _reseal(successor, fields=tuple(reversed(successor.fields)))
    elif mutation == "reviewed_value":
        row = successor.fields[0].model_copy(update={"value": "caller-replacement"})
        forged = _reseal(successor, fields=(row, *successor.fields[1:]))
    elif mutation == "pending_value":
        index = next(
            index for index, row in enumerate(successor.fields) if row.field_id in _NOT_COVERED
        )
        rows = list(successor.fields)
        rows[index] = rows[index].model_copy(update={"value": "material-wiki-fallback"})
        forged = _reseal(successor, fields=tuple(rows))
    elif mutation == "invented_reviewer":
        metadata = successor.review_metadata.model_copy(update={"reviewed_by": "invented"})
        forged = _reseal(successor, review_metadata=metadata)
    elif mutation == "fake_signature":
        receipt = successor.ready_to_sign.model_copy(
            update={"key_id": "caller", "signature": "fake"}
        )
        forged = _reseal(successor, ready_to_sign=receipt)
    else:
        mapping = successor.latest71_mappings[0].model_copy(
            update={"target_field_ids": ("sales_pitch_script",)}
        )
        forged = _reseal(
            successor,
            latest71_mappings=(mapping, *successor.latest71_mappings[1:]),
        )

    with pytest.raises(Schema67ReviewedGoldenSuccessorError):
        validate_schema67_reviewed_golden_successor_596_1(
            forged,
            old60_bytes=old60,
            latest71_bytes=latest71,
        )


def test_wire_is_closed_canonical_and_committed_artifact_matches_builder() -> None:
    old60, latest71 = _inputs()
    successor = _build()
    canonical = canonical_schema67_reviewed_golden_successor_bytes(successor)
    assert _SUCCESSOR.read_bytes() == canonical
    assert (
        load_schema67_reviewed_golden_successor_596_1(
            canonical,
            old60_bytes=old60,
            latest71_bytes=latest71,
        )
        == successor
    )

    decoded = json.loads(canonical)
    for payload in (
        json.dumps(
            {**decoded, "foreign_authority": True},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n",
        canonical + b"{}\n",
        json.dumps(decoded, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
    ):
        with pytest.raises(Schema67ReviewedGoldenSuccessorError):
            load_schema67_reviewed_golden_successor_596_1(
                payload,
                old60_bytes=old60,
                latest71_bytes=latest71,
            )


def test_exact_artifact_manifest_binds_mappings_metadata_residuals_and_unsigned_payload() -> None:
    successor = _build()
    expected = canonical_schema67_reviewed_golden_artifact_files(successor)
    directory = _SUCCESSOR.parent

    assert set(expected) == {
        "golden67-successor.json",
        "mapping-old60-to-schema67.json",
        "mapping-reviewed71-to-schema67.json",
        "review-metadata.json",
        "review-attestation.json",
        "source-coverage-gaps.json",
        "whole-batch-ready-to-sign.json",
        "manifest.json",
    }
    assert {path.name for path in directory.iterdir() if path.is_file()} == set(expected)
    assert {name: (directory / name).read_bytes() for name in expected} == expected

    manifest = json.loads(expected["manifest.json"])
    assert manifest["golden_set_sha256"] == successor.golden_set_sha256
    assert manifest["reviewed_field_count"] == 67
    assert manifest["pending_residual_field_count"] == 0
    assert manifest["review_completion_fact"] is True
    assert manifest["source_review_status"] == "COMPLETED"
    assert manifest["schema67_mapping_status"] == "COMPLETE_67"
    assert manifest["golden_admission_status"] == "BLOCKED_RECEIPT_UNVERIFIED"
    assert manifest["authority_metadata_complete"] is False
    assert manifest["cryptographic_receipt_signed"] is False
    assert manifest["evaluator_formal_conclusion_allowed"] is False
    assert set(manifest["files"]) == set(expected) - {"manifest.json"}
    assert all(
        manifest["files"][name] == hashlib.sha256(expected[name]).hexdigest()
        for name in manifest["files"]
    )

    coverage = json.loads(expected["source-coverage-gaps.json"])
    assert coverage["source_artifact_sha256"] == (
        "e58d0ffdc7e0c16d98df13f1be51b5d747bf81102f0e35f01612a969c2164506"
    )
    assert coverage["source_manifest_external_sha256"] == (
        "2e98c5e45f9c4447b61e9b0055f12774062a8ce2e96e6f48ed59156d4a11acf2"
    )
    assert coverage["source_manifest_self_sha256"] == (
        "9071fe763efd18aea7afca22d3dfe2d7911067237c118999744e72cfeceda70d"
    )
    assert coverage["field_ids"] == list(_NOT_COVERED)
    assert coverage["informational_only"] is True
    assert coverage["decision_required"] is False
    assert coverage["publish_blocking"] is False
    assert all(row["unknown_reason"] == _NOT_COVERED_REASON for row in coverage["rows"])
    assert all(
        row["value"] is None
        and row["evidence"] == []
        and row["page"] is None
        and row["bbox"] is None
        for row in coverage["rows"]
    )

    attestation = json.loads(expected["review-attestation.json"])
    assert attestation["source_review_status"] == "COMPLETED"
    assert attestation["reviewer_id"] == "linyao"
    assert attestation["annotator_model_id"] == "claude-fable-5"
    assert attestation["reviewed_at"] is None
    assert attestation["attestor_id"] == "workspace-owner-houjing"
    assert attestation["source_thread_id"] == "019fda9b-f72b-7661-b88f-f2ae1bb02634"
    assert attestation["attested_at"] == "2026-08-11T11:21:07Z"
    assert attestation["schema67_mapping_status"] == "COMPLETE_67"
    assert attestation["golden_admission_status"] == "BLOCKED_RECEIPT_UNVERIFIED"
    assert attestation["receipt_status"] == "UNVERIFIED"
    assert attestation["signature"] is None
    assert attestation["golden_set_sha256"] == successor.golden_set_sha256
    assert len(attestation["schema67_mapping_sha256"]) == 64


def test_governance_text_records_review_completion_without_formal_quality_claim() -> None:
    paths = (
        _REPO / "docs/superpowers/plans/2026-08-11-schema67-human-annotation-kit.md",
        _REPO / "docs/superpowers/plans/2026-08-11-schema67-golden-quality-gate.md",
        _REPO / "openspec/changes/122-schema67-golden-quality-gate/proposal.md",
        _REPO / "openspec/changes/122-schema67-golden-quality-gate/specs/"
        "schema67-golden-quality-gate/spec.md",
        _REPO / "openspec/changes/122-schema67-golden-quality-gate/tasks.md",
        _REPO / "openspec/changes/122-schema67-golden-quality-gate/validation-report.md",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "67 REVIEWED / 0 PENDING_RESIDUAL" in combined
    assert "source_review_status=COMPLETED" in combined
    assert "schema67_mapping_status=COMPLETE_67" in combined
    assert "golden_admission_status=BLOCKED_RECEIPT_UNVERIFIED" in combined
    assert _NOT_COVERED_REASON in combined
    assert "does not restart human review" in combined
    assert "QUALITY-INCONCLUSIVE" in combined
    assert "reviewed_by" in combined and "reviewed_at" in combined
    assert "MUST NOT be invented" in combined or "SHALL NOT be fabricated" in combined
