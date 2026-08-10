from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.goldenset import (
    schema67_semantic_comparator_596_2 as comparator_119,
)
from insurance_harness.goldenset.expert_golden_admission_596_2 import (
    FIXED_UNKNOWN_FIELD_IDS,
    ORDERED_FIELD_IDS,
    NamedExpertApprovalReceiptV1,
    make_total_control_named_expert_approval_receipt,
)

NOW = datetime(2026, 8, 9, 4, 0, tzinfo=UTC)


def _receipt() -> NamedExpertApprovalReceiptV1:
    return make_total_control_named_expert_approval_receipt()


def test_reference_snapshot_is_exact_workbook_owned_and_not_caller_signed() -> None:
    reference = comparator_119.load_total_control_approved_schema67_reference(
        receipt=_receipt(),
        observed_at=NOW,
    )

    assert tuple(field.field_id for field in reference.fields) == ORDERED_FIELD_IDS
    assert sum(field.expected_state == "unknown" for field in reference.fields) == 21
    assert sum(field.expected_state == "present" for field in reference.fields) == 45
    assert sum(field.expected_state == "absent_explicitly" for field in reference.fields) == 1
    assert reference.approved_by == "linyao"
    assert sum(len(field.reference_evidence_branch_sha256s) for field in reference.fields) == 94
    assert not hasattr(comparator_119, "make_total_control_approved_schema67_reference")


def test_foreign_or_stale_expert_receipt_cannot_load_reference() -> None:
    receipt = replace(_receipt(), approved_by="foreign")
    with pytest.raises(
        comparator_119.Schema67SemanticComparatorError,
        match="REFERENCE_RECEIPT_INVALID",
    ):
        comparator_119.load_total_control_approved_schema67_reference(
            receipt=receipt,
            observed_at=NOW,
        )


def test_reference_rendering_self_rehash_cannot_forge_workbook_authority() -> None:
    reference = comparator_119.load_total_control_approved_schema67_reference(
        receipt=_receipt(),
        observed_at=NOW,
    )
    field = reference.fields[0]
    mutated_field = replace(
        field,
        allowed_rendering_sha256s=("a" * 64,),
        required_component_sha256s=("a" * 64,),
    )
    mutated_field = replace(
        mutated_field,
        field_authority_sha256=canonical_hash(
            "schema67-reference-field.v1",
            mutated_field.canonical_payload(),
        ),
    )
    mutated = replace(reference, fields=(mutated_field, *reference.fields[1:]))
    mutated = replace(
        mutated,
        reference_fields_authority_sha256=canonical_hash(
            "schema67-reference-fields-snapshot.v1",
            mutated.canonical_payload(),
        ),
    )

    with pytest.raises(
        comparator_119.Schema67SemanticComparatorError,
        match="REFERENCE_AUTHORITY_INVALID",
    ):
        comparator_119.validate_approved_schema67_reference(mutated)


@pytest.mark.parametrize(
    "attribute",
    (
        "required_component_sha256s",
        "required_evidence_source_sha256s",
        "reference_evidence_branch_sha256s",
        "explicit_absence_quote_sha256s",
    ),
)
def test_reference_component_evidence_and_absence_hashes_are_pinned(
    attribute: str,
) -> None:
    reference = comparator_119.load_total_control_approved_schema67_reference(
        receipt=_receipt(),
        observed_at=NOW,
    )
    index = 33 if attribute == "explicit_absence_quote_sha256s" else 0
    field = reference.fields[index]
    if attribute == "required_component_sha256s":
        mutated_field = replace(field, required_component_sha256s=("b" * 64,))
    elif attribute == "required_evidence_source_sha256s":
        mutated_field = replace(field, required_evidence_source_sha256s=("b" * 64,))
    elif attribute == "reference_evidence_branch_sha256s":
        mutated_field = replace(field, reference_evidence_branch_sha256s=("b" * 64,))
    else:
        mutated_field = replace(field, explicit_absence_quote_sha256s=("b" * 64,))
    mutated_field = replace(
        mutated_field,
        field_authority_sha256=canonical_hash(
            "schema67-reference-field.v1", mutated_field.canonical_payload()
        ),
    )
    mutated = replace(
        reference,
        fields=(
            reference.fields[:index]
            + (mutated_field,)
            + reference.fields[index + 1 :]
        ),
    )
    mutated = replace(
        mutated,
        reference_fields_authority_sha256=canonical_hash(
            "schema67-reference-fields-snapshot.v1", mutated.canonical_payload()
        ),
    )

    with pytest.raises(comparator_119.Schema67SemanticComparatorError):
        comparator_119.validate_approved_schema67_reference(mutated)


def test_unknown_reference_fields_are_pending_not_semantic_pass() -> None:
    reference = comparator_119.load_total_control_approved_schema67_reference(
        receipt=_receipt(),
        observed_at=NOW,
    )
    unknown = reference.fields[ORDERED_FIELD_IDS.index(FIXED_UNKNOWN_FIELD_IDS[0])]

    comparator = comparator_119.make_deterministic_schema67_semantic_comparator(
        reference=reference
    )
    decision = comparator.compare(
        field_id=unknown.field_id,
        candidate_state="unknown",
        candidate_value_sha256=None,
        candidate_bundle_sha256="c" * 64,
    )

    assert decision.semantic_outcome == "PENDING"
    assert decision.reference_state == "unknown"
    assert decision.reference_value_sha256 is None


def test_present_and_absence_comparisons_use_only_sealed_reference_hashes() -> None:
    reference = comparator_119.load_total_control_approved_schema67_reference(
        receipt=_receipt(),
        observed_at=NOW,
    )
    comparator = comparator_119.make_deterministic_schema67_semantic_comparator(
        reference=reference
    )
    present = next(field for field in reference.fields if field.expected_state == "present")
    absent = next(
        field for field in reference.fields if field.expected_state == "absent_explicitly"
    )

    exact_present = comparator.compare(
        field_id=present.field_id,
        candidate_state="present",
        candidate_value_sha256=present.allowed_rendering_sha256s[0],
        candidate_bundle_sha256="d" * 64,
    )
    wrong_present = comparator.compare(
        field_id=present.field_id,
        candidate_state="present",
        candidate_value_sha256="e" * 64,
        candidate_bundle_sha256="d" * 64,
    )
    exact_absent = comparator.compare(
        field_id=absent.field_id,
        candidate_state="absent_explicitly",
        candidate_value_sha256=absent.allowed_rendering_sha256s[0],
        candidate_bundle_sha256="d" * 64,
    )

    assert exact_present.semantic_outcome == "EQUIVALENT"
    assert wrong_present.semantic_outcome == "DIFFERENT"
    assert exact_absent.semantic_outcome == "EQUIVALENT"
    assert exact_absent.required_evidence_source_sha256s


def test_comparator_authority_rejects_foreign_or_rehashed_reference() -> None:
    reference = comparator_119.load_total_control_approved_schema67_reference(
        receipt=_receipt(),
        observed_at=NOW,
    )
    comparator = comparator_119.make_deterministic_schema67_semantic_comparator(
        reference=reference
    )
    assert (
        comparator.authority.reference_fields_authority_sha256
        == comparator_119.REFERENCE_FIELDS_AUTHORITY_SHA256
    )
    assert comparator.authority.expert_subject_sha256 == reference.expert_subject_sha256
    assert comparator.authority.expert_receipt_sha256 == reference.expert_receipt_sha256
    foreign_reference = replace(reference)
    object.__setattr__(foreign_reference, "approved_by", "foreign")
    mutated = replace(comparator, _reference=foreign_reference)

    with pytest.raises(
        comparator_119.Schema67SemanticComparatorError,
        match="COMPARATOR_AUTHORITY_INVALID|REFERENCE_AUTHORITY_INVALID",
    ):
        comparator_119.validate_total_control_schema67_semantic_comparator(mutated)
    with pytest.raises(
        comparator_119.Schema67SemanticComparatorError,
        match="COMPARATOR_AUTHORITY_INVALID",
    ):
        comparator_119.validate_total_control_schema67_semantic_comparator(object())
