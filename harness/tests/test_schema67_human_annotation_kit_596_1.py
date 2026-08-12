from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.goldenset.schema67_human_annotation_kit_596_1 import (
    Schema67HumanAnnotationKitError,
    build_schema67_human_annotation_kit_596_1,
    canonical_schema67_human_annotation_kit_bytes,
    load_schema67_human_annotation_kit_596_1,
    schema67_human_annotation_kit_safe_summary,
    schema67_human_annotation_kit_sha256,
    validate_schema67_human_annotation_kit_596_1,
)
from insurance_harness.knowledge_compiler.medical_schema_pack_596_1 import (
    make_medical_schema_pack_596_1,
)

_REPO = Path(__file__).resolve().parents[2]
_OLD60 = _REPO / "dataset/goldenset/gs-s0q-596-v1/596.jsonl"
_DRAFT71 = _REPO / "dataset/goldenset-drafts/esheng-zunxiang-v0/annotations.jsonl"
_COMMITTED_KIT = _REPO / "dataset/goldenset-drafts/schema67-human-annotation-kit-596-1/kit.json"


def _inputs() -> tuple[bytes, bytes]:
    return _OLD60.read_bytes(), _DRAFT71.read_bytes()


def _jsonl_ids(payload: bytes) -> tuple[str, ...]:
    return tuple(json.loads(line)["field_id"] for line in payload.splitlines() if line)


def _reseal(kit: Any, **updates: object) -> Any:
    mutated = kit.model_copy(update=updates)
    return mutated.model_copy(update={"kit_sha256": schema67_human_annotation_kit_sha256(mutated)})


def test_builder_binds_exact_inputs_and_explicit_complete_mappings() -> None:
    old60, draft71 = _inputs()
    kit = build_schema67_human_annotation_kit_596_1(
        old60_bytes=old60,
        draft71_bytes=draft71,
    )
    ordered67 = make_medical_schema_pack_596_1().ordered_field_ids

    assert kit.old60_input.row_count == 60
    assert (
        kit.old60_input.sha256 == "562c37c7cf262e2e78f0b3ca4b7de4b0dab2f407d3cd7318a8a69b5dca33d8fb"
    )
    assert kit.draft71_input.row_count == 71
    assert (
        kit.draft71_input.sha256
        == "25c62051d04c8bd56f3770e77d071ae18945daee5dce6b8fb584937555260be4"
    )
    assert tuple(kit.schema_pack.ordered_field_ids) == ordered67

    assert tuple(
        mapping.source_field_id
        for mapping in kit.old60_mappings
        if mapping.source_field_id is not None
    ) == _jsonl_ids(old60)
    assert tuple(
        mapping.source_field_id
        for mapping in kit.draft71_mappings
        if mapping.source_field_id is not None
    ) == _jsonl_ids(draft71)
    assert {target for mapping in kit.old60_mappings for target in mapping.target_field_ids} == set(
        ordered67
    )
    assert {
        target for mapping in kit.draft71_mappings for target in mapping.target_field_ids
    } == set(ordered67)
    assert {mapping.action for mapping in kit.old60_mappings} <= {
        "reuse",
        "rename",
        "split",
        "merge",
        "new",
        "N-A",
    }
    assert {mapping.action for mapping in kit.draft71_mappings} <= {
        "reuse",
        "rename",
        "split",
        "merge",
        "new",
        "N-A",
    }
    assert all(
        mapping.source_authority_level == "HUMAN_APPROVED_S0_Q_MIGRATION_INPUT"
        and mapping.admission_status == "PROPOSED_MIGRATION"
        and mapping.human_review_status == "PENDING"
        for mapping in kit.old60_mappings
    )
    assert all(
        mapping.source_authority_level == "MODEL_SUGGESTION"
        and mapping.admission_status == "MODEL_SUGGESTION"
        and mapping.human_review_status == "PENDING"
        for mapping in kit.draft71_mappings
    )
    assert sum(mapping.source_risk_level == "high" for mapping in kit.draft71_mappings) == 23
    assert sum(mapping.mandatory_human_review for mapping in kit.draft71_mappings) == 11
    assert sum(mapping.tri_state_conflict for mapping in kit.draft71_mappings) == 8
    assert (
        validate_schema67_human_annotation_kit_596_1(
            kit,
            old60_bytes=old60,
            draft71_bytes=draft71,
        )
        is kit
    )


def test_exact67_template_is_pending_and_contains_no_copied_answer() -> None:
    old60, draft71 = _inputs()
    kit = build_schema67_human_annotation_kit_596_1(
        old60_bytes=old60,
        draft71_bytes=draft71,
    )
    ordered67 = make_medical_schema_pack_596_1().ordered_field_ids

    assert tuple(row.field_id for row in kit.annotations) == ordered67
    assert len(kit.annotations) == 67
    assert all(
        row.annotation_status == "PENDING"
        and row.state is None
        and row.value is None
        and row.value_schema is None
        and row.allowed_values == ()
        and row.normalization_rule_id is None
        and row.evidence == ()
        and row.page is None
        and row.locator is None
        and row.quote is None
        and row.quote_sha256 is None
        and row.content_sha256 is None
        and row.bbox is None
        and row.coordinate_space is None
        and row.bbox_status == "PENDING_CAPTURE"
        and row.risk_level is None
        and row.conflict_status == "PENDING"
        and row.reviewer_decisions == ()
        for row in kit.annotations
    )


def test_revision_page_work_and_reviewer_receipt_slots_are_fail_closed() -> None:
    old60, draft71 = _inputs()
    kit = build_schema67_human_annotation_kit_596_1(
        old60_bytes=old60,
        draft71_bytes=draft71,
    )

    revisions = {item.role: item for item in kit.source_revisions}
    assert revisions["terms"].parse_attempt == 2
    assert revisions["terms"].page_count == 39
    assert revisions["brochure"].parse_attempt == 1
    assert revisions["brochure"].page_count == 27
    assert revisions["rate"].parse_attempt == 1
    assert revisions["rate"].page_count == 2
    assert all(item.bbox_status == "PENDING_CAPTURE" for item in kit.special_pages)
    assert {
        (item.role, item.page, item.action) for item in kit.special_pages if item.role == "rate"
    } == {
        ("rate", 12, "PROHIBITED_PAGE_OUT_OF_RANGE"),
        ("rate", 27, "PROHIBITED_PAGE_OUT_OF_RANGE"),
    }
    assert all(
        item.action.startswith("PENDING_")
        for item in kit.special_pages
        if item.role in {"terms", "brochure"}
    )
    assert all(
        slot.named_human_id == "PENDING_NAMED_HUMAN_ID" and slot.decision_status == "PENDING"
        for slot in kit.reviewer_slots
    )
    assert kit.whole_batch_receipt.status == "PENDING"
    assert kit.whole_batch_receipt.golden_set_sha256 is None
    assert kit.whole_batch_receipt.receipt_sha256 is None
    assert kit.whole_batch_receipt.signature is None


@pytest.mark.parametrize(
    "mutation",
    [
        "reordered_fields",
        "approved_status",
        "copied_material_value",
        "source_revision",
        "rate_page12",
        "reviewer_identity",
    ],
)
def test_fully_rehashed_authority_mutations_cannot_create_golden(
    mutation: str,
) -> None:
    old60, draft71 = _inputs()
    kit = build_schema67_human_annotation_kit_596_1(
        old60_bytes=old60,
        draft71_bytes=draft71,
    )
    if mutation == "reordered_fields":
        forged = _reseal(kit, annotations=tuple(reversed(kit.annotations)))
    elif mutation == "approved_status":
        forged = _reseal(kit, kit_status="APPROVED_GOLDEN")
    elif mutation == "copied_material_value":
        row = kit.annotations[0].model_copy(
            update={
                "annotation_status": "APPROVED",
                "state": "present",
                "value": "copied-material-wiki-answer",
            }
        )
        forged = _reseal(kit, annotations=(row, *kit.annotations[1:]))
    elif mutation == "source_revision":
        revision = kit.source_revisions[0].model_copy(update={"file_sha256": "f" * 64})
        forged = _reseal(
            kit,
            source_revisions=(revision, *kit.source_revisions[1:]),
        )
    elif mutation == "rate_page12":
        pages = tuple(
            item.model_copy(update={"action": "PENDING_RECAPTURE"})
            if item.role == "rate" and item.page == 12
            else item
            for item in kit.special_pages
        )
        forged = _reseal(kit, special_pages=pages)
    else:
        slot = kit.reviewer_slots[0].model_copy(update={"named_human_id": "invented-reviewer"})
        forged = _reseal(kit, reviewer_slots=(slot, *kit.reviewer_slots[1:]))

    with pytest.raises(Schema67HumanAnnotationKitError):
        validate_schema67_human_annotation_kit_596_1(
            forged,
            old60_bytes=old60,
            draft71_bytes=draft71,
        )


def test_loader_rejects_unknown_duplicate_trailing_noncanonical_and_input_drift() -> None:
    old60, draft71 = _inputs()
    kit = build_schema67_human_annotation_kit_596_1(
        old60_bytes=old60,
        draft71_bytes=draft71,
    )
    canonical = canonical_schema67_human_annotation_kit_bytes(kit)
    decoded = json.loads(canonical)

    unknown = (
        json.dumps(
            {**decoded, "foreign_authority": "caller"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    noncanonical = json.dumps(decoded, ensure_ascii=False, indent=2).encode("utf-8")
    duplicate = b'{"contract":"schema67-human-annotation-kit-596-1.v1",' + canonical[1:]
    for payload in (unknown, noncanonical, duplicate, canonical + b"\n"):
        with pytest.raises(Schema67HumanAnnotationKitError):
            load_schema67_human_annotation_kit_596_1(
                payload,
                old60_bytes=old60,
                draft71_bytes=draft71,
            )
    with pytest.raises(Schema67HumanAnnotationKitError):
        load_schema67_human_annotation_kit_596_1(
            canonical,
            old60_bytes=old60 + b" ",
            draft71_bytes=draft71,
        )


def test_safe_summary_is_counts_only_and_committed_artifact_is_canonical() -> None:
    old60, draft71 = _inputs()
    expected = build_schema67_human_annotation_kit_596_1(
        old60_bytes=old60,
        draft71_bytes=draft71,
    )
    summary = schema67_human_annotation_kit_safe_summary(expected)

    assert summary.model_dump(mode="json") == {
        "contract": "schema67-human-annotation-kit-summary-596-1.v1",
        "kit_status": "NON_AUTHORITATIVE_DRAFT",
        "field_count": 67,
        "pending_field_count": 67,
        "old60_source_count": 60,
        "draft71_source_count": 71,
        "model_high_risk_count": 23,
        "mandatory_human_review_count": 11,
        "tri_state_conflict_count": 8,
        "bbox_pending_count": 67,
        "reviewer_slot_count": len(expected.reviewer_slots),
        "assigned_reviewer_count": 0,
        "approved_field_count": 0,
        "can_emit_approved_golden": False,
    }
    assert _COMMITTED_KIT.read_bytes() == canonical_schema67_human_annotation_kit_bytes(expected)
    assert (
        load_schema67_human_annotation_kit_596_1(
            _COMMITTED_KIT.read_bytes(),
            old60_bytes=old60,
            draft71_bytes=draft71,
        )
        == expected
    )
    assert Counter(row.annotation_status for row in expected.annotations) == {"PENDING": 67}
