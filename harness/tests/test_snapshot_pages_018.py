"""OpenSpec 018 T4: Wiki pages render only from frozen SnapshotFact views."""

from sqlalchemy.orm import Session

from insurance_harness.knowledge import (
    build_snapshot_facts,
    render_snapshot_pages,
)
from tests.support.release_018 import (
    NOW,
    release_claim,
    release_product,
    release_scope,
)


def test_r2_3_r4_4_renderer_builds_deterministic_owned_pages_for_all_products(
    kb_session: Session,
) -> None:
    scope = release_scope(kb_session)
    product_a, version_a = release_product(kb_session, scope, code="A")
    product_b, version_b = release_product(kb_session, scope, code="B")
    claim_a, evidence_a = release_claim(
        kb_session,
        scope,
        version_a,
        claim_id="claim-a",
        predicate="waiting_period",
    )
    claim_b, evidence_b = release_claim(
        kb_session,
        scope,
        version_b,
        claim_id="claim-b",
        predicate="hesitation_period",
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
            "knowledge-claim-a": "A正式条款",
            "knowledge-claim-b": "B正式条款",
        },
    )

    pages = render_snapshot_pages(
        facts,
        space_id=scope.space_id,
        snapshot_id="snapshot-1",
        compiled_at=NOW,
    )

    assert [page.slug for page in pages] == [
        "product/A/V1/overview",
        "product/B/V1/overview",
    ]
    assert [page.page_metadata["entity_ids"] for page in pages] == [
        {"product_id": product_a.id, "product_version_id": version_a.id},
        {"product_id": product_b.id, "product_version_id": version_b.id},
    ]
    assert all(
        page.page_metadata["managed_by"] == "insurance-harness"
        and page.page_metadata["space_id"] == scope.space_id
        and page.page_metadata["snapshot_id"] == "snapshot-1"
        and page.page_metadata["compiled_at"] == NOW.isoformat()
        and page.page_metadata["harness_version"]
        and page.page_metadata["schema_versions"] == ["v1.1+release"]
        for page in pages
    )
    assert pages[0].page_metadata["claim_ids"] == [claim_a.id]
    assert pages[1].page_metadata["claim_ids"] == [claim_b.id]
    assert pages[0].source_refs == ["knowledge-claim-a|A正式条款"]
    assert pages[0].chunk_refs == ["chunk-claim-a"]

    product_a.canonical_name = "后来改名"
    claim_a.value = {"text": "180天"}
    assert evidence_a is not None and evidence_b is not None
    evidence_a.quote = "后来改证据"
    evidence_b.quote = "后来改证据"
    kb_session.flush()

    assert render_snapshot_pages(
        facts,
        space_id=scope.space_id,
        snapshot_id="snapshot-1",
        compiled_at=NOW,
    ) == pages


def test_r2_3_renderer_supports_valid_empty_release_and_rejects_mixed_identity(
    kb_session: Session,
) -> None:
    scope = release_scope(kb_session)
    _, version = release_product(kb_session, scope, code="A")
    release_claim(
        kb_session,
        scope,
        version,
        claim_id="claim-a",
        predicate="waiting_period",
    )
    facts = build_snapshot_facts(kb_session, scope, snapshot_id="snapshot-1")

    assert render_snapshot_pages(
        (),
        space_id=scope.space_id,
        snapshot_id="snapshot-empty",
        compiled_at=NOW,
    ) == ()

    try:
        render_snapshot_pages(
            facts,
            space_id=scope.space_id,
            snapshot_id="wrong-snapshot",
            compiled_at=NOW,
        )
    except ValueError as exc:
        assert str(exc) == "snapshot fact identity mismatch"
    else:
        raise AssertionError("mixed snapshot identity must fail closed")
