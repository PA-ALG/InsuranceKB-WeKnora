"""K3：增量合并引擎与 03 §6.2 裁决序（specs/mainchain.md）。"""

from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.knowledge import (
    ConflictJudgement,
    MergeEngine,
    MergePolicy,
    ProposedClaim,
    ProposedEvidence,
    apply_conflict_judgements,
    read_conflict_judgements,
    request_review_overturn,
    retract_source,
    write_conflict_judge_queue,
)
from insurance_harness.knowledge.models import ConflictJudgeRequest, MergeReport
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    ClaimEvidence,
    ClaimRevision,
    Conflict,
    ReviewItem,
)
from tests.kbhelpers import (
    allow_all_gate,
    resolve_with_version,
    seed_bound_scope,
    seed_product,
)


def _prop(
    scope: KnowledgeScope,
    version_id: str,
    predicate: str = "waiting_period",
    *,
    value: str | None = "90天",
    value_state: str = "present",
    doc_role: str = "official_desc",
    authority: int = 2,
    knowledge_id: str = "k-brochure",
    quote: str = "等待期为90天",
    page: int = 3,
    confidence: float = 0.9,
    effective_from: date | None = None,
    pending_judge: bool = False,
) -> ProposedClaim:
    return ProposedClaim(
        space_id=scope.space_id,
        product_version_id=version_id,
        predicate=predicate,
        field_name=predicate,
        value_state=value_state,  # type: ignore[arg-type]
        value=value,
        effective_from=effective_from,
        confidence=confidence,
        pending_judge=pending_judge,
        evidence=[
            ProposedEvidence(
                knowledge_id=knowledge_id,
                doc_title=knowledge_id,
                quote=quote,
                page=page,
                doc_role=doc_role,
                authority_level=authority,
            )
        ],
    )


def _scope(session: Session) -> KnowledgeScope:
    return seed_bound_scope(
        session,
        tenant_id="tenant-merge",
        raw_kb_id="raw-merge",
        wiki_kb_id="wiki-merge",
    )


def _engine(
    session: Session, scope: KnowledgeScope, **kwargs: object
) -> MergeEngine:
    # 默认注入低风险放行的测试替身 gate（fail-closed 后自动发布须过 gate）；
    # 发布仍需 policy 的 auto_apply_* 位为真，故不影响"默认保守→审核"的用例。
    if "quality_gate" not in kwargs:
        gate, fp = allow_all_gate()
        kwargs.setdefault("quality_gate", gate)
        kwargs.setdefault("run_fingerprint", fp)
    return MergeEngine(session, scope=scope, **kwargs)  # type: ignore[arg-type]


def _apply(
    engine: MergeEngine, *props: ProposedClaim, external_id: str | None = None
) -> "MergeReport":
    change_set, _ = engine.open_change_set(
        source_kind="document", external_record_id=external_id
    )
    return engine.apply_batch(change_set, list(props))


def _published(session: Session, predicate: str) -> Claim:
    return session.execute(
        select(Claim).where(Claim.predicate == predicate, Claim.status == "published")
    ).scalar_one()


def test_k3_1_add_default_needs_review(kb_session: Session) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    engine = _engine(kb_session, scope)
    _apply(engine, _prop(scope, version.id))
    claim = kb_session.execute(select(Claim)).scalar_one()
    item = kb_session.execute(select(ChangeItem)).scalar_one()
    assert item.action == "add" and item.decision == "needs_review"
    assert claim.status == "candidate"  # 保守默认：全走审核
    assert kb_session.execute(select(ReviewItem)).scalar_one().status == "open"


def test_k3_1_add_auto_policy_publishes(kb_session: Session) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    engine = _engine(kb_session, scope, policy=MergePolicy(auto_apply_add=True))
    _apply(engine, _prop(scope, version.id))
    claim = kb_session.execute(select(Claim)).scalar_one()
    item = kb_session.execute(select(ChangeItem)).scalar_one()
    assert claim.status == "published" and item.decision == "auto_applied"


def test_k3_1_enrich_appends_evidence_and_raises_confidence(kb_session: Session) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    engine = _engine(
        kb_session,
        scope,
        policy=MergePolicy(auto_apply_add=True, auto_apply_enrich=True),
    )
    _apply(engine, _prop(scope, version.id, confidence=0.6))
    _apply(
        engine,
        _prop(
            scope,
            version.id,
            knowledge_id="k-terms",
            doc_role="terms",
            authority=1,
            quote="等待期为九十天", page=8, confidence=0.9,
        ),
    )
    claim = _published(kb_session, "waiting_period")
    evidence = kb_session.execute(select(ClaimEvidence)).scalars().all()
    assert len(evidence) == 2  # 同值追加证据
    assert claim.confidence > 0.9  # confidence 上调
    enrich = kb_session.execute(
        select(ChangeItem).where(ChangeItem.action == "enrich")
    ).scalar_one()
    assert enrich.decision == "auto_applied"


def test_k3_1_enrich_fills_unknown_placeholder(kb_session: Session) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    engine = _engine(kb_session, scope, policy=MergePolicy(auto_apply_add=True))
    _apply(engine, _prop(scope, version.id, value=None, value_state="unknown"))
    placeholder = kb_session.execute(select(Claim)).scalar_one()
    assert placeholder.status == "draft"

    report = _apply(engine, _prop(scope, version.id))
    assert report.actions.get("enrich") == 1
    key = report.review_keys[0]
    resolve_with_version(kb_session, scope, key, "approve", actor="tester")
    kb_session.refresh(placeholder)
    new_claim = _published(kb_session, "waiting_period")
    assert placeholder.status == "superseded" and placeholder.superseded_by == new_claim.id


def test_k3_2_authority_wins_auto_supersede(kb_session: Session) -> None:
    """① 高权威直接胜出：条款(1) 取代 说明书(2)，全留痕（K6.2 核心语义）。"""
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    # 019 Q4.1：supersede 自动应用默认关；本用例测 auto-supersede 语义，显式开启布尔位。
    engine = _engine(
        kb_session, scope,
        policy=MergePolicy(auto_apply_add=True, auto_apply_supersede_low_risk=True),
    )
    _apply(engine, _prop(scope, version.id, value="90天"))
    old = _published(kb_session, "waiting_period")

    _apply(
        engine,
        _prop(
            scope,
            version.id,
            value="180天",
            doc_role="terms",
            authority=1,
            knowledge_id="k-terms", quote="等待期为180天",
        ),
    )
    kb_session.refresh(old)
    new = _published(kb_session, "waiting_period")
    assert new.value == {"text": "180天"}
    assert old.status == "superseded" and old.superseded_by == new.id
    item = kb_session.execute(
        select(ChangeItem).where(ChangeItem.action == "supersede")
    ).scalar_one()
    assert item.decision == "auto_applied"
    assert item.decision_basis is not None
    assert "proposed 胜" in item.decision_basis["authority_cmp"]  # 留痕
    conflict = kb_session.execute(select(Conflict)).scalar_one()
    assert conflict.status == "resolved"


def test_k3_2_low_authority_only_conflict_record(kb_session: Session) -> None:
    """① 低权威新值只能进 conflict 记录，不能 supersede 高权威旧值。"""
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    engine = _engine(kb_session, scope, policy=MergePolicy(auto_apply_add=True))
    _apply(
        engine,
        _prop(
            scope,
            version.id,
            doc_role="terms",
            authority=1,
            knowledge_id="k-terms",
        ),
    )
    old = _published(kb_session, "waiting_period")

    _apply(
        engine,
        _prop(
            scope,
            version.id,
            value="30天",
            doc_role="sales",
            authority=5,
            knowledge_id="k-flyer",
        ),
    )
    kb_session.refresh(old)
    assert old.status == "published"  # 旧值不动
    assert len(kb_session.execute(select(Claim)).scalars().all()) == 1  # 不落新 Claim
    conflict = kb_session.execute(select(Conflict)).scalar_one()
    assert conflict.status == "resolved"
    assert conflict.decision_basis is not None
    assert "existing 胜" in conflict.decision_basis["authority_cmp"]


def test_k3_2_effective_date_breaks_tie(kb_session: Session) -> None:
    """② 同权威级别，生效日期新者胜。"""
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    # 019 Q4.1：显式开启 supersede 自动应用以测裁决序②的 auto 路径。
    engine = _engine(
        kb_session, scope,
        policy=MergePolicy(auto_apply_add=True, auto_apply_supersede_low_risk=True),
    )
    _apply(engine, _prop(scope, version.id, effective_from=date(2023, 1, 1)))
    _apply(
        engine,
        _prop(
            scope,
            version.id,
            value="180天",
            knowledge_id="k-brochure-2024",
            quote="2024起等待期180天", effective_from=date(2024, 1, 1),
        ),
    )
    new = _published(kb_session, "waiting_period")
    assert new.value == {"text": "180天"}
    item = kb_session.execute(
        select(ChangeItem).where(ChangeItem.action == "supersede")
    ).scalar_one()
    assert item.decision_basis is not None
    assert "生效新者胜" in item.decision_basis["effective_cmp"]


def test_k3_2_completeness_never_decides_tie_goes_to_judge_queue(
    kb_session: Session, tmp_path: Path
) -> None:
    """③ 完整度仅排序参考；④ 平局进 claude-session 队列（零模型调用）。"""
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    engine = _engine(kb_session, scope, policy=MergePolicy(auto_apply_add=True))
    _apply(engine, _prop(scope, version.id, value="90天"))
    old = _published(kb_session, "waiting_period")

    # 同权威、无生效期，新值更"完整"（更长）——完整度不得决定胜负
    _apply(
        engine,
        _prop(
            scope,
            version.id,
            value="90天（等待期自合同生效之日起算，含节假日，期间出险不赔）",
            knowledge_id="k-brochure-b", quote="等待期自合同生效……",
        ),
    )
    kb_session.refresh(old)
    assert old.status == "published"  # 冲突未决旧值不动（K3.4）
    candidate = kb_session.execute(
        select(Claim).where(Claim.status == "candidate")
    ).scalar_one()
    conflict = kb_session.execute(select(Conflict)).scalar_one()
    assert conflict.status == "pending_judge"
    assert conflict.decision_basis is not None
    assert "仅排序参考" in conflict.decision_basis["completeness_cmp"]
    assert len(engine.judge_queue) == 1

    # judge-queue JSONL 形态落盘/回读（复用 compiler 形态）
    queue_path = tmp_path / "judge-queue.jsonl"
    write_conflict_judge_queue(queue_path, engine.judge_queue)
    reloaded = [
        ConflictJudgeRequest.model_validate_json(line)
        for line in queue_path.read_text(encoding="utf-8").splitlines()
    ]
    assert reloaded[0].conflict_id == conflict.id

    # ④ 裁决回写：采信新值，llm_verdict 留痕
    judgement_path = tmp_path / "judgements.jsonl"
    judgement_path.write_text(
        ConflictJudgement(
            conflict_id=conflict.id, winner="proposed", reasoning="条款细节更完整且证据可回验"
        ).model_dump_json() + "\n",
        encoding="utf-8",
    )
    applied = apply_conflict_judgements(
        kb_session,
        scope,
        read_conflict_judgements(judgement_path),
    )
    assert applied == 1
    kb_session.refresh(old)
    kb_session.refresh(candidate)
    assert candidate.status == "published" and old.status == "superseded"
    kb_session.refresh(conflict)
    assert conflict.status == "resolved"
    item = kb_session.execute(
        select(ChangeItem).where(ChangeItem.id == conflict.change_item_id)
    ).scalar_one()
    assert item.decision_basis is not None
    assert item.decision_basis["llm_verdict"] == "条款细节更完整且证据可回验"


def test_k3_2_high_risk_skips_judge_straight_to_review(kb_session: Session) -> None:
    """高风险字段跳过④直接⑤（03 §6.2）。"""
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    engine = _engine(
        kb_session,
        scope,
        policy=MergePolicy(auto_apply_add=True),
        risk_of=lambda p: "high" if p == "exclusion_clause" else "low",
    )
    first = _apply(
        engine,
        _prop(scope, version.id, predicate="exclusion_clause", value="十项免责"),
    )
    # 高风险 add 也不自动：先审核通过第一批
    resolve_with_version(kb_session, scope, first.review_keys[0], "approve", actor="agent")
    assert _published(kb_session, "exclusion_clause").value == {"text": "十项免责"}

    _apply(
        engine,
        _prop(
            scope,
            version.id,
            predicate="exclusion_clause",
            value="八项免责",
            knowledge_id="k-b2", quote="免责八项",
        ),
    )
    assert engine.judge_queue == []  # 不进④
    review = kb_session.execute(
        select(ReviewItem).where(ReviewItem.status == "open")
    ).scalar_one()
    assert review.risk_level == "high" and review.type == "conflict"
    conflict = kb_session.execute(select(Conflict)).scalar_one()
    assert conflict.status == "open"


def test_k3_2_high_risk_supersede_needs_review(kb_session: Session) -> None:
    """权威分出胜负但高风险字段：supersede 一律进审核，旧值保持 published。"""
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    engine = _engine(
        kb_session,
        scope,
        policy=MergePolicy(auto_apply_add=True),
        risk_of=lambda p: "high",
    )
    first = _apply(engine, _prop(scope, version.id))
    resolve_with_version(kb_session, scope, first.review_keys[0], "approve", actor="agent")
    old = _published(kb_session, "waiting_period")
    _apply(
        engine,
        _prop(
            scope,
            version.id,
            value="180天",
            doc_role="terms",
            authority=1,
            knowledge_id="k-terms",
        ),
    )
    kb_session.refresh(old)
    assert old.status == "published"
    item = kb_session.execute(
        select(ChangeItem).where(ChangeItem.action == "supersede")
    ).scalar_one()
    assert item.decision == "needs_review"
    review = kb_session.execute(
        select(ReviewItem).where(ReviewItem.status == "open")
    ).scalar_one()
    assert review.type == "high_risk_change"

    resolve_with_version(
        kb_session,
        scope,
        review.review_key,
        "approve",
        actor="strong-model-agent",
    )
    kb_session.refresh(old)
    assert old.status == "superseded"
    assert _published(kb_session, "waiting_period").value == {"text": "180天"}


def test_k3_2_low_risk_supersede_review_is_not_mislabeled_high(kb_session: Session) -> None:
    """codex #8：低风险 supersede 未自动应用而进审核时，应标 low_confidence/low，
    不得硬编码 high_risk_change（否则污染审核优先级与审计语义）。"""
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    # 默认 auto_apply_supersede_low_risk=False → 低风险 supersede 进审核；risk_of 默认 low
    engine = _engine(kb_session, scope, policy=MergePolicy(auto_apply_add=True))
    _apply(engine, _prop(scope, version.id))  # gate 放行 add → 直接 published
    assert _published(kb_session, "waiting_period").status == "published"
    _apply(
        engine,
        _prop(
            scope, version.id, value="180天",
            doc_role="terms", authority=1, knowledge_id="k-terms",
        ),
    )
    review = kb_session.execute(
        select(ReviewItem).where(ReviewItem.status == "open")
    ).scalar_one()
    assert review.type == "low_confidence"  # 不是 high_risk_change
    assert review.risk_level == "low"


def test_k3_3_revisions_and_immutable_changeset(kb_session: Session) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    # 019 Q4.1：本用例断言 supersede 留痕，需显式开启 supersede 自动应用。
    engine = _engine(
        kb_session, scope,
        policy=MergePolicy(auto_apply_add=True, auto_apply_supersede_low_risk=True),
    )
    _apply(engine, _prop(scope, version.id), external_id="batch-1")
    _apply(
        engine,
        _prop(
            scope,
            version.id,
            value="180天",
            doc_role="terms",
            authority=1,
            knowledge_id="k-terms",
        ),
        external_id="batch-2",
    )
    revisions = kb_session.execute(select(ClaimRevision)).scalars().all()
    # 旧 claim：add + publish + supersede；新 claim：add + publish
    assert len(revisions) >= 4
    assert all(r.change_item_id is not None and r.after for r in revisions)
    supersede_rev = [
        r for r in revisions if r.before is not None and r.before.get("status") == "published"
    ]
    assert supersede_rev and supersede_rev[0].after["status"] == "superseded"
    sets = kb_session.execute(select(ChangeSet)).scalars().all()
    assert {s.external_record_id for s in sets} == {"batch-1", "batch-2"}
    assert all(s.status == "applied" for s in sets)


def test_k3_5_overturn_creates_new_changeset(kb_session: Session) -> None:
    """翻案=新 ChangeSet **走审核**（K3.5 + 008 W2.3 两阶段）：登记请求不改任何事实、
    原 resolution 不改写；批准翻案审核项后才执行反向应用（旧值恢复 published）。"""
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    engine = _engine(
        kb_session,
        scope,
        policy=MergePolicy(auto_apply_add=True),
        risk_of=lambda p: "high",
    )
    first = _apply(engine, _prop(scope, version.id), external_id="b1")
    resolve_with_version(kb_session, scope, first.review_keys[0], "approve", actor="agent")
    second = _apply(
        engine,
        _prop(
            scope,
            version.id,
            value="180天",
            doc_role="terms",
            authority=1,
            knowledge_id="k-terms",
        ),
        external_id="b2",
    )
    review = kb_session.execute(
        select(ReviewItem).where(ReviewItem.review_key == second.review_keys[0])
    ).scalar_one()
    resolve_with_version(kb_session, scope, review.review_key, "approve", actor="agent")
    adopted = _published(kb_session, "waiting_period")
    original_resolution = dict(review.resolution or {})
    sets_before = len(kb_session.execute(select(ChangeSet)).scalars().all())

    overturn_set, overturn_item, created = request_review_overturn(
        kb_session,
        scope,
        review.review_key,
        "reject",
        actor="human",
        reason="条款版本核对有误",
    )
    # —— 第一阶段：只登记，不改事实 ——
    assert created and overturn_set.source_kind == "manual_edit"
    assert overturn_set.status == "pending"
    assert overturn_item.status == "open" and overturn_item.type == "overturn"
    assert overturn_item.risk_level == "high", "翻案一律单条人审"
    assert len(kb_session.execute(select(ChangeSet)).scalars().all()) == sets_before + 1
    kb_session.refresh(adopted)
    assert adopted.status == "published", "登记翻案后旧事实必须原样"
    kb_session.refresh(review)
    assert dict(review.resolution or {}) == original_resolution, "原 resolution 不改写"
    # 重复请求幂等：不再新建 ChangeSet
    _, again, again_created = request_review_overturn(
        kb_session, scope, review.review_key, "reject",
        actor="human", reason="重复点击",
    )
    assert not again_created and again.review_key == overturn_item.review_key
    assert len(kb_session.execute(select(ChangeSet)).scalars().all()) == sets_before + 1

    # —— 第二阶段：批准翻案审核项后才执行反向应用 ——
    resolve_with_version(
        kb_session, scope, overturn_item.review_key, "approve", actor="human-2"
    )
    kb_session.refresh(adopted)
    assert adopted.status == "retracted"
    restored = _published(kb_session, "waiting_period")
    assert restored.value == {"text": "90天"} and restored.superseded_by is None
    kb_session.refresh(overturn_set)
    assert overturn_set.status == "applied"
    kb_session.refresh(review)
    assert dict(review.resolution or {}) == original_resolution, (
        "批准翻案也不得回写原 resolution（历史裁决不可变）"
    )


def test_k3_5_overturn_reject_of_request_keeps_facts(kb_session: Session) -> None:
    """翻案审核项被 reject：当前事实不变、复议 ChangeSet 终态 rejected。"""
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    engine = _engine(
        kb_session, scope,
        policy=MergePolicy(auto_apply_add=True), risk_of=lambda p: "high",
    )
    report = _apply(engine, _prop(scope, version.id), external_id="b1")
    resolve_with_version(kb_session, scope, report.review_keys[0], "approve", actor="agent")
    adopted = _published(kb_session, "waiting_period")
    overturn_set, overturn_item, _ = request_review_overturn(
        kb_session, scope, report.review_keys[0], "reject",
        actor="human", reason="复核一下",
    )
    resolve_with_version(
        kb_session, scope, overturn_item.review_key, "reject", actor="human-2",
        reason="原决定无误",
    )
    kb_session.refresh(adopted)
    assert adopted.status == "published", "拒绝翻案 → 事实不变"
    kb_session.refresh(overturn_set)
    assert overturn_set.status == "rejected"


def test_k3_1_retract_by_evidence_refcount(kb_session: Session) -> None:
    """retract：仍有其他证据只移除 Evidence；证据清零 → Claim retracted（03 §2.4）。"""
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    engine = _engine(
        kb_session,
        scope,
        policy=MergePolicy(auto_apply_add=True, auto_apply_enrich=True),
    )
    _apply(engine, _prop(scope, version.id))  # 单证据（k-brochure）
    _apply(
        engine,
        _prop(
            scope,
            version.id,
            predicate="grace_period",
            value="60天",
            quote="宽限期60日", knowledge_id="k-brochure",
        ),
    )
    # grace_period 再补一条 terms 证据（双源）
    _apply(
        engine,
        _prop(
            scope,
            version.id,
            predicate="grace_period",
            value="60天",
            quote="宽限期为60日", knowledge_id="k-terms", doc_role="terms", authority=1,
        ),
    )
    report = retract_source(
        kb_session,
        scope,
        "k-brochure",
        legacy_replay=True,
    )
    assert report.actions.get("retract") == 2
    waiting = kb_session.execute(
        select(Claim).where(Claim.predicate == "waiting_period")
    ).scalar_one()
    assert waiting.status == "retracted"  # 证据清零
    grace = _published(kb_session, "grace_period")  # 仍有 terms 证据 → 保留
    remaining = kb_session.execute(
        select(ClaimEvidence).where(ClaimEvidence.claim_id == grace.id)
    ).scalars().all()
    assert {e.knowledge_id for e in remaining} == {"k-terms"}
