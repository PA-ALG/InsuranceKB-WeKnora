"""OpenSpec 018 T6: curated-first, same-Scope RAW fallback policy."""

from collections.abc import Sequence

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.knowledge import (
    CoverageGap,
    FallbackAnswer,
    RawFallbackPolicy,
    RawHit,
    SnapshotFactsResult,
)
from insurance_harness.knowledge.snapshots import SnapshotFactView
from insurance_harness.knowledge.tables import SnapshotFact
from tests.support.release_018 import release_scope


class _Provider:
    def __init__(self, hits: Sequence[RawHit]) -> None:
        self.hits = tuple(hits)
        self.calls: list[tuple[KnowledgeScope, CoverageGap, str]] = []

    async def search(
        self,
        scope: KnowledgeScope,
        gap: CoverageGap,
        query: str,
    ) -> Sequence[RawHit]:
        self.calls.append((scope, gap, query))
        return self.hits


def _fact(scope: KnowledgeScope) -> SnapshotFactView:
    return SnapshotFactView(
        space_id=scope.space_id,
        snapshot_id="snapshot-1",
        claim_id="claim-1",
        revision_no=1,
        product_id="product-1",
        product_version_id="version-1",
        product_code="P1",
        product_name="产品一",
        version_label="V1",
        predicate="waiting_period",
        field_name="等待期",
        field_group="保障责任",
        value_state="present",
        value={"days": 90},
        effective_from=None,
        effective_to=None,
        confidence=0.99,
        schema_version="1.1",
        evidence=(),
    )


@pytest.mark.asyncio
async def test_r5_1_r5_3_curated_facts_never_call_or_merge_raw_provider(
    kb_session: Session,
) -> None:
    scope = release_scope(kb_session)
    provider = _Provider(
        [RawHit(space_id=scope.space_id, raw_kb_id=scope.raw_kb_id, text="冲突文本")]
    )
    result = SnapshotFactsResult(snapshot_id="snapshot-1", facts=(_fact(scope),))

    answer = await RawFallbackPolicy(provider).answer(scope, result, query="等待期")

    assert answer is result
    assert provider.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    [
        "no_release",
        "legacy_release",
        "product_not_found",
        "predicate_not_found",
        "effective_date_miss",
    ],
)
async def test_r5_1_every_typed_gap_can_explicitly_invoke_raw_provider(
    kb_session: Session,
    code: str,
) -> None:
    scope = release_scope(kb_session, code)
    hit = RawHit(
        space_id=scope.space_id,
        raw_kb_id=scope.raw_kb_id,
        text=f"raw:{code}",
        source_ref="knowledge/chunk-1",
    )
    provider = _Provider([hit])
    gap = CoverageGap(code=code, snapshot_id=None)  # type: ignore[arg-type]

    answer = await RawFallbackPolicy(provider).answer(scope, gap, query="查询")

    assert answer == FallbackAnswer(review_status="unreviewed_raw", hits=(hit,))
    assert provider.calls == [(scope, gap, "查询")]


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["space_id", "raw_kb_id"])
async def test_r5_2_any_cross_scope_hit_rejects_whole_answer_without_writeback(
    kb_session: Session,
    mismatch: str,
) -> None:
    scope = release_scope(kb_session, mismatch)
    valid = RawHit(
        space_id=scope.space_id,
        raw_kb_id=scope.raw_kb_id,
        text="valid",
    )
    invalid = RawHit(
        space_id="other-space" if mismatch == "space_id" else scope.space_id,
        raw_kb_id="other-raw" if mismatch == "raw_kb_id" else scope.raw_kb_id,
        text="must-not-leak",
    )
    before = kb_session.scalar(select(func.count()).select_from(SnapshotFact))

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        await RawFallbackPolicy(_Provider([valid, invalid])).answer(
            scope,
            CoverageGap(code="product_not_found", snapshot_id="snapshot-1"),
            query="查询",
        )

    kb_session.expire_all()
    after = kb_session.scalar(select(func.count()).select_from(SnapshotFact))
    assert after == before
