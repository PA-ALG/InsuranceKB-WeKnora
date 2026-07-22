"""OpenSpec 016 S1/S2/S4：publisher 与页面编译必须绑定 KnowledgeScope。"""

import copy
import inspect
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.orm import Session

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.adapters.weknora.errors import WeKnoraError
from insurance_harness.db.base import utcnow
from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
)
from insurance_harness.knowledge import (
    MergeEngine,
    MergePolicy,
    ProposedClaim,
    ProposedEvidence,
    build_page_claims,
    current_snapshot_id,
    default_snapshot_label,
    snapshot_claim_set,
)
from insurance_harness.knowledge.tables import (
    ChangeSet,
    Claim,
    ClaimEvidence,
    CurrentRelease,
    ReleaseSnapshot,
    SnapshotClaim,
)
from tests.conftest import BASE_URL
from tests.kbhelpers import green_gate, seed_bound_scope, seed_product
from tests.support.legacy_publisher_007 import (
    legacy_publish_product_version as _legacy_publish_product_version,
)
from tests.support.legacy_publisher_007 import (
    legacy_rollback_to_snapshot as _legacy_rollback_to_snapshot,
)
from tests.support.release_plan_018 import _issue_test_staging_capability


async def publish_product_version(
    session: Session,
    client: WeKnoraClient,
    scope: KnowledgeScope,
    **kwargs: Any,
) -> Any:
    return await _legacy_publish_product_version(
        session,
        client,
        scope,
        staging_capability=_issue_test_staging_capability(scope),
        **kwargs,
    )


async def rollback_to_snapshot(
    session: Session,
    client: WeKnoraClient,
    scope: KnowledgeScope,
    **kwargs: Any,
) -> Any:
    return await _legacy_rollback_to_snapshot(
        session,
        client,
        scope,
        staging_capability=_issue_test_staging_capability(scope),
        **kwargs,
    )


def _scopes(session: Session) -> tuple[KnowledgeScope, KnowledgeScope]:
    return (
        seed_bound_scope(
            session,
            tenant_id="tenant-a",
            raw_kb_id="raw-a",
            wiki_kb_id="wiki-a",
        ),
        seed_bound_scope(
            session,
            tenant_id="tenant-b",
            raw_kb_id="raw-b",
            wiki_kb_id="wiki-b",
        ),
    )


def _publish_claim(session: Session, scope: KnowledgeScope, version_id: str) -> Claim:
    gate, fp = green_gate(["waiting_period"])
    engine = MergeEngine(
        session,
        scope=scope,
        policy=MergePolicy(auto_apply_add=True),
        quality_gate=gate,
        run_fingerprint=fp,
    )
    change_set, _ = engine.open_change_set(source_kind="document")
    engine.apply_batch(
        change_set,
        [
            ProposedClaim(
                space_id=scope.space_id,
                product_version_id=version_id,
                predicate="waiting_period",
                field_name="等待期",
                value_state="present",
                value="90天",
                confidence=0.9,
                evidence=[
                    ProposedEvidence(
                        knowledge_id="k-terms",
                        quote="等待期为90天",
                        page=3,
                        doc_role="terms",
                        authority_level=1,
                    )
                ],
            )
        ],
    )
    return session.execute(
        select(Claim).where(
            Claim.space_id == scope.space_id,
            Claim.product_version_id == version_id,
        )
    ).scalar_one()


def _page_response(body: bytes | None = None) -> httpx.Response:
    payload = json.loads(body) if body else {"slug": "x"}
    return httpx.Response(
        200,
        json={"data": {**payload, "id": "page-1"}, "success": True},
    )


def _mock_create(wiki_kb_id: str) -> respx.Route:
    base = f"{BASE_URL}/api/v1/knowledgebase/{wiki_kb_id}/wiki"
    respx.get(url__startswith=f"{base}/pages/").mock(
        return_value=httpx.Response(404, text="not found")
    )
    return respx.post(f"{base}/pages").mock(
        side_effect=lambda request: _page_response(request.content)
    )


def _counts(session: Session) -> tuple[int, int, int]:
    return (
        session.scalar(select(func.count()).select_from(ReleaseSnapshot)) or 0,
        session.scalar(select(func.count()).select_from(CurrentRelease)) or 0,
        session.scalar(select(func.count()).select_from(ChangeSet)) or 0,
    )


@contextmanager
def _sqlite_foreign_keys_disabled(session: Session) -> Iterator[None]:
    """Allow a test to model legacy corruption, then restore FK enforcement."""

    session.commit()
    assert not session.in_transaction()
    try:
        session.execute(text("PRAGMA foreign_keys = OFF"))
        assert session.scalar(text("PRAGMA foreign_keys")) == 0
        yield
    finally:
        session.rollback()
        assert not session.in_transaction()
        session.execute(text("PRAGMA foreign_keys = ON"))
        assert session.scalar(text("PRAGMA foreign_keys")) == 1
        session.commit()


def test_page_read_rejects_forged_scope_with_matching_bound_values(
    kb_session: Session,
) -> None:
    scope, _ = _scopes(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    _publish_claim(kb_session, scope, version.id)
    forged = KnowledgeScope(**scope.model_dump())

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        build_page_claims(kb_session, forged, version.id)

    assert kb_session.is_active


@respx.mock
async def test_publisher_rejects_forged_matching_scope_before_io_or_mutation(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    _publish_claim(kb_session, scope, version.id)
    forged = KnowledgeScope(**scope.model_dump())
    before = _counts(kb_session)

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        await publish_product_version(
            kb_session,
            client,
            forged,
            product_version_id=version.id,
            label="forged-release",
        )

    assert _counts(kb_session) == before
    assert not respx.calls
    assert kb_session.is_active


async def _published_snapshot(
    session: Session,
    client: WeKnoraClient,
    scope: KnowledgeScope,
) -> tuple[Claim, ReleaseSnapshot]:
    _, version = seed_product(session, scope=scope)
    claim = _publish_claim(session, scope, version.id)
    _mock_create(scope.wiki_kb_id)
    result = await publish_product_version(
        session,
        client,
        scope,
        product_version_id=version.id,
        label="release-1",
    )
    snapshot = session.get(ReleaseSnapshot, result.snapshot_id)
    assert snapshot is not None and snapshot.rendered_pages
    return claim, snapshot


def _rendered_pages(snapshot: ReleaseSnapshot) -> list[dict[str, Any]]:
    pages = snapshot.rendered_pages
    assert pages
    return copy.deepcopy(pages)


def _replace_current_with_malformed_snapshot(
    session: Session,
    scope: KnowledgeScope,
    source: ReleaseSnapshot,
    *,
    rendered_pages: list[dict[str, Any]],
    include_frozen_claims: bool = True,
) -> ReleaseSnapshot:
    """Insert malformed legacy-shaped data without mutating a published row."""

    malformed = ReleaseSnapshot(
        space_id=scope.space_id,
        label=f"malformed-{source.id}",
        rendered_pages=rendered_pages,
        status="published",
        read_model_version=1,
        projection_frozen_at=utcnow(),
        published_at=utcnow(),
        published_by="test-fixture",
    )
    session.add(malformed)
    session.flush()
    if include_frozen_claims:
        frozen_claims = session.scalars(
            select(SnapshotClaim).where(
                SnapshotClaim.space_id == scope.space_id,
                SnapshotClaim.snapshot_id == source.id,
            )
        )
        session.add_all(
            [
                SnapshotClaim(
                    space_id=row.space_id,
                    snapshot_id=malformed.id,
                    claim_id=row.claim_id,
                    revision_no=row.revision_no,
                )
                for row in frozen_claims
            ]
        )
    current = session.scalar(
        select(CurrentRelease).where(CurrentRelease.space_id == scope.space_id)
    )
    assert current is not None
    current.snapshot_id = malformed.id
    session.flush()
    return malformed


async def _assert_rollback_rejected_before_io(
    session: Session,
    client: WeKnoraClient,
    scope: KnowledgeScope,
    snapshot: ReleaseSnapshot,
) -> None:
    before = _counts(session)
    calls_before = len(respx.calls)

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        await rollback_to_snapshot(
            session,
            client,
            scope,
            snapshot_id=snapshot.id,
        )

    assert _counts(session) == before
    assert current_snapshot_id(session, scope) == snapshot.id
    assert len(respx.calls) == calls_before


def test_s2_3_publisher_surface_has_scope_and_no_free_form_kb_id() -> None:
    for service in (
        publish_product_version,
        rollback_to_snapshot,
        current_snapshot_id,
        default_snapshot_label,
        snapshot_claim_set,
        build_page_claims,
    ):
        parameters = inspect.signature(service).parameters
        assert "scope" in parameters
        assert "kb_id" not in parameters


def test_s2_3_current_snapshot_returns_none_only_when_pointer_is_absent(
    kb_session: Session,
) -> None:
    scope, _ = _scopes(kb_session)

    assert current_snapshot_id(kb_session, scope) is None


def test_s2_2_current_snapshot_rejects_pointer_to_other_space_snapshot(
    kb_session: Session,
) -> None:
    scope_a, scope_b = _scopes(kb_session)
    snapshot = ReleaseSnapshot(
        space_id=scope_a.space_id,
        label="release-a",
        status="published",
        read_model_version=1,
        projection_frozen_at=utcnow(),
        published_at=utcnow(),
        published_by="test",
    )
    kb_session.add(snapshot)
    kb_session.flush()
    kb_session.add(
        CurrentRelease(
            space_id=scope_a.space_id,
            snapshot_id=snapshot.id,
        )
    )
    kb_session.flush()
    with _sqlite_foreign_keys_disabled(kb_session):
        kb_session.execute(
            update(ReleaseSnapshot)
            .where(ReleaseSnapshot.id == snapshot.id)
            .values(space_id=scope_b.space_id)
        )
        kb_session.commit()
        kb_session.expire_all()

        with pytest.raises(ScopeViolation, match="scope mismatch"):
            current_snapshot_id(kb_session, scope_a)


def test_s2_2_current_snapshot_rejects_dangling_pointer(
    kb_session: Session,
) -> None:
    scope, _ = _scopes(kb_session)
    snapshot = ReleaseSnapshot(
        space_id=scope.space_id,
        label="release-a",
        status="published",
        read_model_version=1,
        projection_frozen_at=utcnow(),
        published_at=utcnow(),
        published_by="test",
    )
    kb_session.add(snapshot)
    kb_session.flush()
    kb_session.add(
        CurrentRelease(
            space_id=scope.space_id,
            snapshot_id=snapshot.id,
        )
    )
    kb_session.flush()
    with _sqlite_foreign_keys_disabled(kb_session):
        kb_session.execute(
            delete(ReleaseSnapshot).where(ReleaseSnapshot.id == snapshot.id)
        )
        kb_session.commit()
        kb_session.expire_all()

        with pytest.raises(ScopeViolation, match="scope mismatch"):
            current_snapshot_id(kb_session, scope)


@respx.mock
async def test_s2_5_current_release_and_same_label_are_independent_per_space(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope_a, scope_b = _scopes(kb_session)
    _, version_a = seed_product(kb_session, scope=scope_a, code="SAME")
    _, version_b = seed_product(kb_session, scope=scope_b, code="SAME")
    _publish_claim(kb_session, scope_a, version_a.id)
    _publish_claim(kb_session, scope_b, version_b.id)
    create_a = _mock_create(scope_a.wiki_kb_id)
    create_b = _mock_create(scope_b.wiki_kb_id)

    result_a = await publish_product_version(
        kb_session,
        client,
        scope_a,
        product_version_id=version_a.id,
        label="release-1",
    )
    result_b = await publish_product_version(
        kb_session,
        client,
        scope_b,
        product_version_id=version_b.id,
        label="release-1",
    )

    assert create_a.call_count == 1
    assert create_b.call_count == 1
    assert current_snapshot_id(kb_session, scope_a) == result_a.snapshot_id
    assert current_snapshot_id(kb_session, scope_b) == result_b.snapshot_id
    assert result_a.snapshot_id != result_b.snapshot_id
    snapshot_spaces = {
        row.space_id
        for row in kb_session.execute(
            select(ReleaseSnapshot).where(ReleaseSnapshot.label == "release-1")
        ).scalars()
    }
    assert snapshot_spaces == {scope_a.space_id, scope_b.space_id}


@respx.mock
async def test_s1_3_unbound_space_cannot_publish_and_performs_no_io_or_write(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    row = KnowledgeSpace(name="offline", binding_status="unbound")
    kb_session.add(row)
    kb_session.flush()
    forged = KnowledgeScope(
        space_id=row.id,
        tenant_id="forged",
        raw_kb_id="forged",
        wiki_kb_id="forged",
    )
    before = _counts(kb_session)

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        await publish_product_version(
            kb_session,
            client,
            forged,
            product_version_id="missing",
            label="release-1",
        )

    assert _counts(kb_session) == before
    assert not respx.calls


@respx.mock
async def test_s2_3_scope_a_cannot_publish_product_version_b_before_write_or_io(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope_a, scope_b = _scopes(kb_session)
    _, version_b = seed_product(kb_session, scope=scope_b)
    _publish_claim(kb_session, scope_b, version_b.id)
    before = _counts(kb_session)

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        await publish_product_version(
            kb_session,
            client,
            scope_a,
            product_version_id=version_b.id,
            label="release-1",
        )

    assert _counts(kb_session) == before
    assert not respx.calls


@respx.mock
async def test_s2_3_rollback_cannot_read_or_move_to_other_space_snapshot(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope_a, scope_b = _scopes(kb_session)
    _, version_b = seed_product(kb_session, scope=scope_b)
    _publish_claim(kb_session, scope_b, version_b.id)
    _mock_create(scope_b.wiki_kb_id)
    result_b = await publish_product_version(
        kb_session,
        client,
        scope_b,
        product_version_id=version_b.id,
        label="release-1",
    )
    before = _counts(kb_session)
    calls_before = len(respx.calls)

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        await rollback_to_snapshot(
            kb_session,
            client,
            scope_a,
            snapshot_id=result_b.snapshot_id,
        )

    assert _counts(kb_session) == before
    assert current_snapshot_id(kb_session, scope_a) is None
    assert current_snapshot_id(kb_session, scope_b) == result_b.snapshot_id
    assert len(respx.calls) == calls_before


@respx.mock
async def test_s2_2_rollback_rejects_page_metadata_that_references_other_space_claim(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope_a, scope_b = _scopes(kb_session)
    _, version_a = seed_product(kb_session, scope=scope_a, code="A")
    _, version_b = seed_product(kb_session, scope=scope_b, code="B")
    _publish_claim(kb_session, scope_a, version_a.id)
    claim_b = _publish_claim(kb_session, scope_b, version_b.id)
    _mock_create(scope_a.wiki_kb_id)
    result_a = await publish_product_version(
        kb_session,
        client,
        scope_a,
        product_version_id=version_a.id,
        label="release-1",
    )
    source = kb_session.get(ReleaseSnapshot, result_a.snapshot_id)
    assert source is not None and source.rendered_pages
    tampered_pages = copy.deepcopy(source.rendered_pages)
    tampered_pages[0]["page_metadata"]["claim_ids"] = [claim_b.id]
    snapshot = _replace_current_with_malformed_snapshot(
        kb_session,
        scope_a,
        source,
        rendered_pages=tampered_pages,
    )
    before = _counts(kb_session)
    calls_before = len(respx.calls)

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        await rollback_to_snapshot(
            kb_session,
            client,
            scope_a,
            snapshot_id=snapshot.id,
        )

    assert _counts(kb_session) == before
    assert current_snapshot_id(kb_session, scope_a) == snapshot.id
    assert len(respx.calls) == calls_before


@respx.mock
async def test_s2_2_rollback_wraps_malformed_rendered_page_as_scope_violation(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    _, source = await _published_snapshot(kb_session, client, scope)
    snapshot = _replace_current_with_malformed_snapshot(
        kb_session,
        scope,
        source,
        rendered_pages=[{"slug": 123}],
    )

    await _assert_rollback_rejected_before_io(kb_session, client, scope, snapshot)


@respx.mock
async def test_s2_2_rollback_rejects_page_slug_outside_product_overview(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    _, source = await _published_snapshot(kb_session, client, scope)
    pages = _rendered_pages(source)
    pages[0]["slug"] = "admin/home"
    snapshot = _replace_current_with_malformed_snapshot(
        kb_session, scope, source, rendered_pages=pages
    )

    await _assert_rollback_rejected_before_io(kb_session, client, scope, snapshot)


@respx.mock
async def test_s2_2_rollback_rejects_duplicate_page_slug(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    _, source = await _published_snapshot(kb_session, client, scope)
    page = _rendered_pages(source)[0]
    snapshot = _replace_current_with_malformed_snapshot(
        kb_session,
        scope,
        source,
        rendered_pages=[page, copy.deepcopy(page)],
    )

    await _assert_rollback_rejected_before_io(kb_session, client, scope, snapshot)


@respx.mock
async def test_s2_2_rollback_rejects_duplicate_claim_within_page(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    claim, source = await _published_snapshot(kb_session, client, scope)
    pages = _rendered_pages(source)
    pages[0]["page_metadata"]["claim_ids"] = [claim.id, claim.id]
    snapshot = _replace_current_with_malformed_snapshot(
        kb_session, scope, source, rendered_pages=pages
    )

    await _assert_rollback_rejected_before_io(kb_session, client, scope, snapshot)


@respx.mock
async def test_s2_2_rollback_rejects_claim_repeated_across_pages(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    _, source = await _published_snapshot(kb_session, client, scope)
    page = _rendered_pages(source)[0]
    repeated = copy.deepcopy(page)
    repeated["slug"] = "other/page"
    snapshot = _replace_current_with_malformed_snapshot(
        kb_session,
        scope,
        source,
        rendered_pages=[page, repeated],
    )

    await _assert_rollback_rejected_before_io(kb_session, client, scope, snapshot)


@respx.mock
async def test_s2_2_rollback_rejects_empty_rendered_pages(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    _, source = await _published_snapshot(kb_session, client, scope)
    snapshot = _replace_current_with_malformed_snapshot(
        kb_session, scope, source, rendered_pages=[]
    )

    await _assert_rollback_rejected_before_io(kb_session, client, scope, snapshot)


@respx.mock
async def test_s2_2_rollback_rejects_snapshot_without_frozen_claims(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    _, snapshot = await _published_snapshot(kb_session, client, scope)
    kb_session.execute(
        delete(SnapshotClaim).where(
            SnapshotClaim.space_id == scope.space_id,
            SnapshotClaim.snapshot_id == snapshot.id,
        )
    )
    kb_session.flush()

    await _assert_rollback_rejected_before_io(kb_session, client, scope, snapshot)


@respx.mock
async def test_s2_2_rollback_rejects_snapshot_with_no_pages_and_no_claims(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    _, source = await _published_snapshot(kb_session, client, scope)
    snapshot = _replace_current_with_malformed_snapshot(
        kb_session,
        scope,
        source,
        rendered_pages=[],
        include_frozen_claims=False,
    )

    await _assert_rollback_rejected_before_io(kb_session, client, scope, snapshot)


@respx.mock
async def test_s2_2_publish_rejects_product_without_claim_anchor_before_io(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    before = _counts(kb_session)

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        await publish_product_version(
            kb_session,
            client,
            scope,
            product_version_id=version.id,
            label="release-1",
        )

    assert _counts(kb_session) == before
    assert not respx.calls


def test_s2_3_page_and_snapshot_read_helpers_reject_bare_cross_space_ids(
    kb_session: Session,
) -> None:
    scope_a, scope_b = _scopes(kb_session)
    _, version_b = seed_product(kb_session, scope=scope_b)
    claim_b = _publish_claim(kb_session, scope_b, version_b.id)
    snapshot_b = ReleaseSnapshot(
        space_id=scope_b.space_id,
        label="release-1",
        published_by="test",
    )
    kb_session.add(snapshot_b)
    kb_session.flush()
    kb_session.add(
        SnapshotClaim(
            space_id=scope_b.space_id,
            snapshot_id=snapshot_b.id,
            claim_id=claim_b.id,
            revision_no=claim_b.current_revision,
        )
    )
    kb_session.flush()

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        build_page_claims(kb_session, scope_a, version_b.id)
    with pytest.raises(ScopeViolation, match="scope mismatch"):
        snapshot_claim_set(kb_session, scope_a, snapshot_b.id)


def test_s2_2_snapshot_claim_set_rejects_missing_frozen_revision(
    kb_session: Session,
) -> None:
    scope, _ = _scopes(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    claim = _publish_claim(kb_session, scope, version.id)
    snapshot = ReleaseSnapshot(
        space_id=scope.space_id,
        label="release-1",
        published_by="test",
    )
    kb_session.add(snapshot)
    kb_session.flush()
    kb_session.add(
        SnapshotClaim(
            space_id=scope.space_id,
            snapshot_id=snapshot.id,
            claim_id=claim.id,
            revision_no=claim.current_revision + 99,
        )
    )
    kb_session.flush()

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        snapshot_claim_set(kb_session, scope, snapshot.id)


@respx.mock
async def test_s2_3_publisher_uses_scope_wiki_kb_for_get_create_and_update(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    product, version = seed_product(kb_session, scope=scope)
    _publish_claim(kb_session, scope, version.id)
    base = f"{BASE_URL}/api/v1/knowledgebase/{scope.wiki_kb_id}/wiki"
    slug = f"product/{product.product_code}/{version.version_label}/overview"
    get = respx.get(f"{base}/pages/{slug}")
    get.mock(return_value=httpx.Response(404, text="not found"))
    create = respx.post(f"{base}/pages").mock(
        side_effect=lambda request: _page_response(request.content)
    )
    update = respx.put(f"{base}/pages/{slug}").mock(
        side_effect=lambda request: _page_response(request.content)
    )

    await publish_product_version(
        kb_session,
        client,
        scope,
        product_version_id=version.id,
        label="release-1",
    )
    get.mock(return_value=_page_response())
    await publish_product_version(
        kb_session,
        client,
        scope,
        product_version_id=version.id,
        label="release-2",
    )

    assert get.call_count == 2
    assert create.call_count == 1
    assert update.call_count == 1
    assert all(
        f"/knowledgebase/{scope.wiki_kb_id}/" in str(call.request.url) for call in respx.calls
    )


@respx.mock
async def test_s2_3_publish_validates_claim_evidence_before_any_write_or_io(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    kb_session.add(
        Claim(
            space_id=scope.space_id,
            product_version_id=version.id,
            predicate="waiting_period",
            value_state="present",
            value={"text": "90天"},
            status="published",
            confidence=0.9,
        )
    )
    kb_session.flush()
    before = _counts(kb_session)

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        await publish_product_version(
            kb_session,
            client,
            scope,
            product_version_id=version.id,
            label="release-1",
        )

    assert _counts(kb_session) == before
    assert not respx.calls


@respx.mock
async def test_s2_3_publish_validates_frozen_revision_before_any_write_or_io(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    claim = Claim(
        space_id=scope.space_id,
        product_version_id=version.id,
        predicate="waiting_period",
        value_state="present",
        value={"text": "90天"},
        status="published",
        confidence=0.9,
        current_revision=7,
    )
    kb_session.add(claim)
    kb_session.flush()
    kb_session.add(
        ClaimEvidence(
            claim_id=claim.id,
            knowledge_id="k-terms",
            quote="等待期为90天",
            page=3,
            authority_level=1,
            doc_role="terms",
        )
    )
    kb_session.flush()
    before = _counts(kb_session)

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        await publish_product_version(
            kb_session,
            client,
            scope,
            product_version_id=version.id,
            label="release-1",
        )

    assert _counts(kb_session) == before
    assert not respx.calls


@respx.mock
async def test_s2_4_duplicate_label_fails_before_io_and_keeps_pointer(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    _publish_claim(kb_session, scope, version.id)
    _mock_create(scope.wiki_kb_id)
    first = await publish_product_version(
        kb_session,
        client,
        scope,
        product_version_id=version.id,
        label="release-1",
    )
    before = _counts(kb_session)
    calls_before = len(respx.calls)

    with pytest.raises(ValueError, match="release label is unavailable"):
        await publish_product_version(
            kb_session,
            client,
            scope,
            product_version_id=version.id,
            label="release-1",
        )

    assert _counts(kb_session) == before
    assert current_snapshot_id(kb_session, scope) == first.snapshot_id
    assert len(respx.calls) == calls_before


@pytest.mark.parametrize(
    ("label", "published_by"),
    [
        ("", "publisher"),
        ("x" * 129, "publisher"),
        ("release-1", ""),
        ("release-1", "p" * 129),
    ],
)
@respx.mock
async def test_s2_3_publish_rejects_invalid_audit_metadata_before_io(
    kb_session: Session,
    client: WeKnoraClient,
    label: str,
    published_by: str,
) -> None:
    scope, _ = _scopes(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    _publish_claim(kb_session, scope, version.id)
    before = _counts(kb_session)

    with pytest.raises(ValueError):
        await publish_product_version(
            kb_session,
            client,
            scope,
            product_version_id=version.id,
            label=label,
            published_by=published_by,
        )

    assert _counts(kb_session) == before
    assert not respx.calls


@pytest.mark.parametrize(
    ("actor", "reason"),
    [
        ("", "rollback"),
        ("a" * 129, "rollback"),
        ("operator", ""),
        ("operator", "r" * 65),
    ],
)
@respx.mock
async def test_s2_3_rollback_rejects_invalid_audit_metadata_before_io(
    kb_session: Session,
    client: WeKnoraClient,
    actor: str,
    reason: str,
) -> None:
    scope, _ = _scopes(kb_session)
    _, snapshot = await _published_snapshot(kb_session, client, scope)
    before = _counts(kb_session)
    calls_before = len(respx.calls)

    with pytest.raises(ValueError):
        await rollback_to_snapshot(
            kb_session,
            client,
            scope,
            snapshot_id=snapshot.id,
            actor=actor,
            reason=reason,
        )

    assert _counts(kb_session) == before
    assert current_snapshot_id(kb_session, scope) == snapshot.id
    assert len(respx.calls) == calls_before


@respx.mock
async def test_s2_4_rollback_persists_reason_and_allows_repeated_operation(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    _, snapshot = await _published_snapshot(kb_session, client, scope)

    first = await rollback_to_snapshot(
        kb_session,
        client,
        scope,
        snapshot_id=snapshot.id,
        actor="operator",
        reason="customer-request",
    )
    second = await rollback_to_snapshot(
        kb_session,
        client,
        scope,
        snapshot_id=snapshot.id,
        actor="operator",
        reason="customer-request",
    )

    rows = list(
        kb_session.execute(
            select(ChangeSet).where(
                ChangeSet.id.in_([first.change_set_id, second.change_set_id]),
                ChangeSet.space_id == scope.space_id,
                ChangeSet.source_kind == "rollback",
            )
        ).scalars()
    )
    assert len(rows) == 2
    assert {row.source_revision for row in rows} == {"customer-request"}
    assert all(
        row.external_record_id is not None and row.external_record_id.startswith(f"{snapshot.id}:")
        for row in rows
    )
    assert len({row.external_record_id for row in rows}) == 2


@respx.mock
async def test_rh1_1_rollback_flush_failure_performs_zero_wiki_mutations(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    product, version = seed_product(kb_session, scope=scope)
    _publish_claim(kb_session, scope, version.id)
    base = f"{BASE_URL}/api/v1/knowledgebase/{scope.wiki_kb_id}/wiki"
    slug = f"product/{product.product_code}/{version.version_label}/overview"
    get = respx.get(f"{base}/pages/{slug}")
    get.mock(return_value=httpx.Response(404, text="not found"))
    respx.post(f"{base}/pages").mock(side_effect=lambda request: _page_response(request.content))
    respx.put(f"{base}/pages/{slug}").mock(
        side_effect=lambda request: _page_response(request.content)
    )
    first = await publish_product_version(
        kb_session,
        client,
        scope,
        product_version_id=version.id,
        label="release-1",
    )
    get.mock(return_value=_page_response())
    second = await publish_product_version(
        kb_session,
        client,
        scope,
        product_version_id=version.id,
        label="release-2",
    )
    calls_before = len(respx.calls)
    rollback_ids_before = list(
        kb_session.scalars(
            select(ChangeSet.id).where(
                ChangeSet.space_id == scope.space_id,
                ChangeSet.source_kind == "rollback",
            )
        )
    )

    def fail_rollback_flush(
        session: Session,
        _context: object,
        _instances: object,
    ) -> None:
        if any(isinstance(row, ChangeSet) and row.source_kind == "rollback" for row in session.new):
            raise RuntimeError("injected rollback flush failure")

    event.listen(kb_session, "before_flush", fail_rollback_flush)
    try:
        with pytest.raises(RuntimeError, match="injected rollback flush failure"):
            await rollback_to_snapshot(
                kb_session,
                client,
                scope,
                snapshot_id=first.snapshot_id,
                actor="operator",
            )
    finally:
        event.remove(kb_session, "before_flush", fail_rollback_flush)

    kb_session.commit()
    assert len(respx.calls) - calls_before == 0
    assert current_snapshot_id(kb_session, scope) == second.snapshot_id
    assert (
        list(
            kb_session.scalars(
                select(ChangeSet.id).where(
                    ChangeSet.space_id == scope.space_id,
                    ChangeSet.source_kind == "rollback",
                )
            )
        )
        == rollback_ids_before
    )


@respx.mock
async def test_rh1_2_rollback_wiki_failure_rolls_back_savepoint_after_outer_commit(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    product, version = seed_product(kb_session, scope=scope)
    _publish_claim(kb_session, scope, version.id)
    base = f"{BASE_URL}/api/v1/knowledgebase/{scope.wiki_kb_id}/wiki"
    slug = f"product/{product.product_code}/{version.version_label}/overview"
    get = respx.get(f"{base}/pages/{slug}")
    get.mock(return_value=httpx.Response(404, text="not found"))
    respx.post(f"{base}/pages").mock(side_effect=lambda request: _page_response(request.content))
    update = respx.put(f"{base}/pages/{slug}").mock(
        side_effect=lambda request: _page_response(request.content)
    )
    first = await publish_product_version(
        kb_session,
        client,
        scope,
        product_version_id=version.id,
        label="release-1",
    )
    get.mock(return_value=_page_response())
    second = await publish_product_version(
        kb_session,
        client,
        scope,
        product_version_id=version.id,
        label="release-2",
    )
    update_calls_before = update.call_count
    rollback_ids_before = list(
        kb_session.scalars(
            select(ChangeSet.id).where(
                ChangeSet.space_id == scope.space_id,
                ChangeSet.source_kind == "rollback",
            )
        )
    )
    update.mock(return_value=httpx.Response(500, text="failed"))

    with pytest.raises(WeKnoraError):
        await rollback_to_snapshot(
            kb_session,
            client,
            scope,
            snapshot_id=first.snapshot_id,
            actor="operator",
        )

    kb_session.commit()
    assert update.call_count > update_calls_before
    assert current_snapshot_id(kb_session, scope) == second.snapshot_id
    assert (
        list(
            kb_session.scalars(
                select(ChangeSet.id).where(
                    ChangeSet.space_id == scope.space_id,
                    ChangeSet.source_kind == "rollback",
                )
            )
        )
        == rollback_ids_before
    )


@respx.mock
async def test_s2_3_wiki_failure_leaves_no_committable_snapshot_or_pointer(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    _publish_claim(kb_session, scope, version.id)
    base = f"{BASE_URL}/api/v1/knowledgebase/{scope.wiki_kb_id}/wiki"
    respx.get(url__startswith=f"{base}/pages/").mock(
        return_value=httpx.Response(500, text="failed")
    )
    before = _counts(kb_session)

    with pytest.raises(WeKnoraError):
        await publish_product_version(
            kb_session,
            client,
            scope,
            product_version_id=version.id,
            label="release-1",
        )

    assert _counts(kb_session) == before
    kb_session.commit()
    assert current_snapshot_id(kb_session, scope) is None


@respx.mock
async def test_s2_3_rollback_wiki_failure_does_not_move_pointer_or_add_trace(
    kb_session: Session,
    client: WeKnoraClient,
) -> None:
    scope, _ = _scopes(kb_session)
    product, version = seed_product(kb_session, scope=scope)
    _publish_claim(kb_session, scope, version.id)
    base = f"{BASE_URL}/api/v1/knowledgebase/{scope.wiki_kb_id}/wiki"
    slug = f"product/{product.product_code}/{version.version_label}/overview"
    get = respx.get(f"{base}/pages/{slug}")
    get.mock(return_value=httpx.Response(404, text="not found"))
    respx.post(f"{base}/pages").mock(side_effect=lambda request: _page_response(request.content))
    update = respx.put(f"{base}/pages/{slug}").mock(
        side_effect=lambda request: _page_response(request.content)
    )
    first = await publish_product_version(
        kb_session,
        client,
        scope,
        product_version_id=version.id,
        label="release-1",
    )
    get.mock(return_value=_page_response())
    second = await publish_product_version(
        kb_session,
        client,
        scope,
        product_version_id=version.id,
        label="release-2",
    )
    assert update.call_count == 1
    get.mock(return_value=httpx.Response(500, text="failed"))
    before = _counts(kb_session)

    with pytest.raises(WeKnoraError):
        await rollback_to_snapshot(
            kb_session,
            client,
            scope,
            snapshot_id=first.snapshot_id,
            actor="operator",
        )

    assert _counts(kb_session) == before
    assert current_snapshot_id(kb_session, scope) == second.snapshot_id
    assert (
        not kb_session.execute(
            select(ChangeSet).where(
                ChangeSet.space_id == scope.space_id,
                ChangeSet.source_kind == "rollback",
            )
        )
        .scalars()
        .all()
    )


def test_s2_4_default_snapshot_label_is_counted_per_space(
    kb_session: Session,
) -> None:
    scope_a, scope_b = _scopes(kb_session)
    first_a = default_snapshot_label(kb_session, scope_a)
    first_b = default_snapshot_label(kb_session, scope_b)
    assert first_a == first_b
    kb_session.add(
        ReleaseSnapshot(
            space_id=scope_a.space_id,
            label=first_a,
            published_by="test",
        )
    )
    kb_session.flush()

    assert default_snapshot_label(kb_session, scope_a).endswith("-r2")
    assert default_snapshot_label(kb_session, scope_b).endswith("-r1")
