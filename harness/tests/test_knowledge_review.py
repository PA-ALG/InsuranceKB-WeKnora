"""K4：审核门禁（specs/mainchain.md）。"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.config import HarnessSettings
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.knowledge import (
    MergeEngine,
    MergePolicy,
    ProposedClaim,
    ProposedEvidence,
    build_page_claims,
    derive_review_key,
    ensure_review_item,
    policy_from_settings,
    resolve_review,
)
from insurance_harness.knowledge.tables import Claim, ReviewItem
from tests.kbhelpers import seed_bound_scope, seed_product


def _scope(session: Session) -> KnowledgeScope:
    return seed_bound_scope(
        session,
        tenant_id="tenant-review",
        raw_kb_id="raw-review",
        wiki_kb_id="wiki-review",
    )


def _prop(
    scope: KnowledgeScope,
    version_id: str,
    predicate: str = "waiting_period",
    value: str = "90天",
) -> ProposedClaim:
    return ProposedClaim(
        space_id=scope.space_id,
        product_version_id=version_id,
        predicate=predicate,
        field_name=predicate,
        value_state="present",
        value=value,
        confidence=0.9,
        evidence=[
            ProposedEvidence(
                knowledge_id="k-brochure", quote=f"{predicate}证据",
                page=1, doc_role="official_desc", authority_level=2,
            )
        ],
    )


def _merge(
    session: Session,
    scope: KnowledgeScope,
    version_id: str,
    *,
    policy: MergePolicy | None = None,
) -> MergeEngine:
    engine = MergeEngine(session, scope=scope, policy=policy)
    change_set, _ = engine.open_change_set(source_kind="document")
    engine.apply_batch(change_set, [_prop(scope, version_id)])
    return engine


def test_k4_1_review_key_stable_and_state_preserved(kb_session: Session) -> None:
    scope = _scope(kb_session)
    key = derive_review_key("low_confidence", "pv-1", "waiting_period", "abcd")
    assert key == derive_review_key("low_confidence", "pv-1", "waiting_period", "abcd")
    assert key != derive_review_key("low_confidence", "pv-1", "waiting_period", "ef01")

    item, created = ensure_review_item(
        kb_session,
        scope=scope,
        review_key=key,
        type_="low_confidence",
        subject={"x": 1},
    )
    assert created
    item.status = "resolved"
    item.resolution = {"action": "approve", "actor": "a", "reason": None, "at": "t"}
    kb_session.flush()
    again, created2 = ensure_review_item(
        kb_session,
        scope=scope,
        review_key=key,
        type_="low_confidence",
        subject={"x": 2},
    )
    assert not created2 and again.id == item.id
    assert again.status == "resolved"  # 已决状态不丢（K4.1）
    assert again.subject == {"x": 1}  # 不重建不覆盖


def test_k4_2_restricted_action_set(kb_session: Session) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    _merge(kb_session, scope, version.id)
    review = kb_session.execute(select(ReviewItem)).scalar_one()
    assert set(review.allowed_actions) == {"approve", "reject", "defer"}

    with pytest.raises(ValueError, match="受限动作集"):
        resolve_review(kb_session, scope, review.review_key, "escalate", actor="a")

    resolve_review(kb_session, scope, review.review_key, "defer", actor="a")
    kb_session.refresh(review)
    assert review.status == "open"  # defer 保持 open

    resolve_review(kb_session, scope, review.review_key, "approve", actor="agent")
    kb_session.refresh(review)
    assert review.status == "resolved"
    claim = kb_session.execute(select(Claim)).scalar_one()
    assert claim.status == "published"

    with pytest.raises(ValueError, match="翻案"):
        resolve_review(kb_session, scope, review.review_key, "reject", actor="a")


def test_k4_2_reject_keeps_nothing_published(kb_session: Session) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    _merge(kb_session, scope, version.id)
    review = kb_session.execute(select(ReviewItem)).scalar_one()
    resolve_review(
        kb_session,
        scope,
        review.review_key,
        "reject",
        actor="agent",
        reason="证据存疑",
    )
    claim = kb_session.execute(select(Claim)).scalar_one()
    assert claim.status == "retracted"
    kb_session.refresh(review)
    assert review.resolution is not None and review.resolution["action"] == "reject"


def test_k4_3_only_published_compiles(kb_session: Session) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    engine = MergeEngine(kb_session, scope=scope, policy=MergePolicy(auto_apply_add=True))
    change_set, _ = engine.open_change_set(source_kind="document")
    engine.apply_batch(change_set, [_prop(scope, version.id, "waiting_period")])  # published
    engine2 = MergeEngine(kb_session, scope=scope)  # 默认保守 → candidate
    change_set2, _ = engine2.open_change_set(source_kind="document", external_record_id="b2")
    engine2.apply_batch(change_set2, [_prop(scope, version.id, "grace_period", "60天")])

    views = build_page_claims(kb_session, scope, version.id)
    assert [v.predicate for v in views] == ["waiting_period"]  # candidate 不进编译


def test_k4_4_enrich_auto_threshold_configurable(kb_session: Session) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    # 默认关闭：同值第二证据也走审核
    engine = MergeEngine(kb_session, scope=scope, policy=MergePolicy(auto_apply_add=True))
    cs1, _ = engine.open_change_set(source_kind="document", external_record_id="b1")
    engine.apply_batch(cs1, [_prop(scope, version.id)])
    prop2 = _prop(scope, version.id)
    prop2 = prop2.model_copy(
        update={
            "evidence": [
                prop2.evidence[0].model_copy(update={"knowledge_id": "k-other"})
            ]
        }
    )
    cs2, _ = engine.open_change_set(source_kind="document", external_record_id="b2")
    report = engine.apply_batch(cs2, [prop2])
    assert report.review_keys  # needs_review

    # 开启且达阈值：自动通过；低于阈值仍审核
    settings = HarnessSettings(
        weknora_base_url="http://x", weknora_api_key="k",
        merge_auto_apply_enrich=True, merge_enrich_auto_min_confidence=0.8,
    )
    policy = policy_from_settings(settings)
    assert policy.auto_apply_enrich is True and policy.enrich_auto_min_confidence == 0.8

    engine3 = MergeEngine(kb_session, scope=scope, policy=policy)
    prop3 = _prop(scope, version.id)
    prop3 = prop3.model_copy(
        update={
            "evidence": [
                prop3.evidence[0].model_copy(update={"knowledge_id": "k-third"})
            ]
        }
    )
    cs3, _ = engine3.open_change_set(source_kind="document", external_record_id="b3")
    report3 = engine3.apply_batch(cs3, [prop3])
    assert not report3.review_keys  # 自动应用，零新增审核项

    prop4 = _prop(scope, version.id)
    prop4 = prop4.model_copy(
        update={
            "confidence": 0.5,  # 低于阈值
            "evidence": [
                prop4.evidence[0].model_copy(update={"knowledge_id": "k-fourth"})
            ],
        }
    )
    cs4, _ = engine3.open_change_set(source_kind="document", external_record_id="b4")
    report4 = engine3.apply_batch(cs4, [prop4])
    assert report4.review_keys
