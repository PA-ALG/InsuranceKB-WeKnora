"""OpenSpec 018 T2: deterministic full-Space SnapshotFact projection."""

from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from insurance_harness.knowledge import SnapshotBuildError, build_snapshot_facts
from tests.support.release_018 import (
    NOW,
    release_claim,
    release_product,
    release_scope,
)


def test_r1_1_r3_2_projection_contains_all_and_only_space_candidates(
    kb_session: Session,
) -> None:
    scope = release_scope(kb_session)
    product_a, version_a = release_product(kb_session, scope, code="A")
    product_b, version_b = release_product(kb_session, scope, code="B")
    claim_a, _ = release_claim(
        kb_session,
        scope,
        version_a,
        claim_id="claim-a",
        predicate="waiting_period",
    )
    claim_b, _ = release_claim(
        kb_session,
        scope,
        version_b,
        claim_id="claim-b",
        predicate="hesitation_period",
        value_state="absent_explicitly",
    )
    release_claim(
        kb_session,
        scope,
        version_a,
        claim_id="claim-unknown",
        predicate="unknown-field",
        value_state="unknown",
    )
    release_claim(
        kb_session,
        scope,
        version_a,
        claim_id="claim-draft",
        predicate="draft-field",
        status="draft",
    )
    other_scope = release_scope(kb_session, "b")
    _, other_version = release_product(kb_session, other_scope, code="C")
    release_claim(
        kb_session,
        other_scope,
        other_version,
        claim_id="claim-other-space",
        predicate="waiting_period",
    )

    facts = build_snapshot_facts(
        kb_session,
        scope,
        snapshot_id="snapshot-1",
        field_names={
            "waiting_period": "等待期",
            "hesitation_period": "犹豫期",
        },
        doc_titles={
            "knowledge-claim-a": "A条款",
            "knowledge-claim-b": "B条款",
        },
    )

    assert [fact.claim_id for fact in facts] == [claim_a.id, claim_b.id]
    assert {fact.product_id for fact in facts} == {product_a.id, product_b.id}
    assert {fact.product_code for fact in facts} == {"A", "B"}
    assert [fact.field_name for fact in facts] == ["等待期", "犹豫期"]
    assert all(fact.field_group == "basic_info" for fact in facts)
    assert facts[1].value_state == "absent_explicitly"
    assert facts[1].value is None
    assert [fact.evidence[0].doc_title for fact in facts] == ["A条款", "B条款"]


@pytest.mark.parametrize(
    "invalid_case",
    ["missing_revision", "missing_evidence", "legacy", "placeholder", "stale"],
)
def test_r1_3_any_invalid_candidate_fails_the_whole_projection(
    kb_session: Session,
    invalid_case: str,
) -> None:
    scope = release_scope(kb_session)
    _, version = release_product(kb_session, scope, code="A")
    release_claim(
        kb_session,
        scope,
        version,
        claim_id="claim-valid",
        predicate="waiting_period",
    )
    claim, evidence = release_claim(
        kb_session,
        scope,
        version,
        claim_id="claim-invalid",
        predicate="hesitation_period",
        current_revision=2 if invalid_case == "missing_revision" else 1,
        add_evidence=invalid_case != "missing_evidence",
    )
    if invalid_case == "legacy":
        assert evidence is not None
        evidence.lineage_status = None
        evidence.raw_kb_id = None
        evidence.source_revision = None
        evidence.file_hash = None
        evidence.original_digest = None
        evidence.parser_version = None
        evidence.chunk_id = None
        evidence.chunk_hash = None
    elif invalid_case == "placeholder":
        assert evidence is not None
        evidence.knowledge_id = "保险条款.pdf"
    elif invalid_case == "stale":
        assert evidence is not None
        evidence.stale_at = NOW + timedelta(minutes=1)
    kb_session.flush()

    with pytest.raises(SnapshotBuildError, match=claim.id):
        build_snapshot_facts(kb_session, scope, snapshot_id="snapshot-1")


def test_r1_1_projection_freezes_all_evidence_columns_and_source_values(
    kb_session: Session,
) -> None:
    scope = release_scope(kb_session)
    product, version = release_product(kb_session, scope, code="A")
    claim, evidence = release_claim(
        kb_session,
        scope,
        version,
        claim_id="claim-a",
        predicate="waiting_period",
    )

    fact = build_snapshot_facts(
        kb_session,
        scope,
        snapshot_id="snapshot-1",
        field_names={"waiting_period": "等待期"},
        doc_titles={"knowledge-claim-a": "正式条款"},
    )[0]
    frozen_evidence = fact.evidence[0]
    assert set(frozen_evidence.model_dump()) == {
        "id",
        "claim_id",
        "knowledge_id",
        "doc_title",
        "chunk_id",
        "quote",
        "page",
        "section",
        "table_ref",
        "timestamp_ms",
        "authority_level",
        "doc_role",
        "extraction_method",
        "extracted_at",
        "raw_kb_id",
        "source_revision",
        "file_hash",
        "original_digest",
        "parser_version",
        "chunk_hash",
        "lineage_status",
        "stale_at",
        "created_at",
        "updated_at",
    }

    product.canonical_name = "改名后的产品"
    claim.value = {"text": "180天"}
    assert evidence is not None
    evidence.quote = "已被后续修改"
    kb_session.flush()

    assert fact.product_name == "产品A"
    assert fact.value == {"text": "90天"}
    assert frozen_evidence.quote == "waiting_period=90天"
    assert frozen_evidence.doc_title == "正式条款"
    with pytest.raises(ValidationError):
        fact.product_name = "禁止修改"


def test_r3_2_zero_candidates_is_a_valid_empty_projection(
    kb_session: Session,
) -> None:
    scope = release_scope(kb_session)
    _, version = release_product(kb_session, scope, code="A")
    release_claim(
        kb_session,
        scope,
        version,
        claim_id="claim-draft",
        predicate="waiting_period",
        status="draft",
    )

    assert build_snapshot_facts(kb_session, scope, snapshot_id="snapshot-empty") == ()
