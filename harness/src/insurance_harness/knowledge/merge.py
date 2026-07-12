"""增量合并引擎（change 007；裁决序严格按 docs/insurance-kb/03 §6.2，specs K3/K4）。

五种 ChangeItem：add / enrich / supersede / conflict / retract（03 §2.5）。
所有变更经由不可变 ChangeSet；每次应用写 ClaimRevision 留痕；自动裁决全部写
decision_basis 可翻案（翻案 = 新 ChangeSet）。裁决序④不实调模型：冲突请求进
claude-session 队列（复用 compiler judge-queue 的 JSONL 形态），回写后按 llm_verdict 裁决。
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.config import HarnessSettings
from insurance_harness.db.base import utcnow
from insurance_harness.knowledge.models import (
    ConflictJudgement,
    ConflictJudgeRequest,
    MergePolicy,
    MergeReport,
    ProposedClaim,
    normalize_value,
)
from insurance_harness.knowledge.review import derive_review_key, ensure_review_item
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    ClaimEvidence,
    ClaimRevision,
    Conflict,
    ReviewItem,
)

RiskResolver = Callable[[str], str]

_STATUS_RANK = {"published": 0, "candidate": 1, "draft": 2}


class MergeError(RuntimeError):
    pass


def policy_from_settings(settings: HarnessSettings) -> MergePolicy:
    """低风险 enrich 自动通过阈值可配（K4.4）；默认关闭=全走审核。"""
    return MergePolicy(
        auto_apply_enrich=settings.merge_auto_apply_enrich,
        enrich_auto_min_confidence=settings.merge_enrich_auto_min_confidence,
    )


# ------------------------------------------------------------------ 留痕原语


def _snapshot(claim: Claim) -> dict[str, Any]:
    return {
        "id": claim.id,
        "predicate": claim.predicate,
        "value_state": claim.value_state,
        "value": claim.value,
        "status": claim.status,
        "confidence": claim.confidence,
        "effective_from": claim.effective_from.isoformat() if claim.effective_from else None,
        "superseded_by": claim.superseded_by,
        "current_revision": claim.current_revision,
    }


def write_revision(
    session: Session,
    claim: Claim,
    *,
    before: dict[str, Any] | None,
    change_item_id: str | None,
    actor: str,
    reason: str | None = None,
) -> ClaimRevision:
    """每次 ChangeItem 应用产生一条不可变修订（03 §5.1，K3.3）。"""
    claim.current_revision += 1
    revision = ClaimRevision(
        claim_id=claim.id,
        revision_no=claim.current_revision,
        before=before,
        after=_snapshot(claim),
        change_item_id=change_item_id,
        actor=actor,
        reason=reason,
    )
    session.add(revision)
    session.flush()
    return revision


def _evidence_rows(claim_id: str, prop: ProposedClaim) -> list[ClaimEvidence]:
    return [
        ClaimEvidence(
            claim_id=claim_id,
            knowledge_id=e.knowledge_id,
            chunk_id=e.chunk_id,
            quote=e.quote,
            page=e.page,
            authority_level=e.authority_level,
            doc_role=e.doc_role,
            extraction_method=e.extraction_method,
        )
        for e in prop.evidence
    ]


def create_claim(session: Session, prop: ProposedClaim, *, status: str) -> Claim:
    claim = Claim(
        subject_type="product_version",
        product_version_id=prop.product_version_id,
        predicate=prop.predicate,
        value_state=prop.value_state,
        value=None if prop.value is None else {"text": prop.value},
        effective_from=prop.effective_from,
        status=status,
        confidence=prop.confidence,
        extraction_method=prop.extraction_method,
        schema_version=prop.schema_version,
        pending_judge=prop.pending_judge,
    )
    session.add(claim)
    session.flush()
    for row in _evidence_rows(claim.id, prop):
        session.add(row)
    session.flush()
    return claim


def claim_value_text(claim: Claim) -> str | None:
    if claim.value is None:
        return None
    text = claim.value.get("text")
    return None if text is None else str(text)


def claim_evidence(session: Session, claim_id: str) -> list[ClaimEvidence]:
    return list(
        session.execute(
            select(ClaimEvidence).where(ClaimEvidence.claim_id == claim_id)
        ).scalars()
    )


def claim_authority(session: Session, claim: Claim) -> int:
    return min((e.authority_level for e in claim_evidence(session, claim.id)), default=6)


def publish_claim(
    session: Session,
    claim: Claim,
    *,
    change_item_id: str | None,
    actor: str,
    reason: str | None = None,
    superseding: Claim | None = None,
) -> None:
    """candidate/draft → published；无 Evidence 不允许发布（03 原则 2）。

    应用层兜底"同主语同谓词只允许一条已发布"（部分唯一索引的 NULL 维度不去重，K1.2）。
    """
    if not claim_evidence(session, claim.id):
        raise MergeError(f"claim {claim.id} 无证据，不允许发布")
    others = session.execute(
        select(Claim).where(
            Claim.product_version_id == claim.product_version_id,
            Claim.predicate == claim.predicate,
            Claim.status == "published",
            Claim.id != claim.id,
        )
    ).scalars().all()
    for other in others:
        if superseding is None or other.id != superseding.id:
            raise MergeError(
                f"({claim.product_version_id}, {claim.predicate}) 已有 published claim "
                f"{other.id}，必须经 supersede/conflict 流程"
            )
    before = _snapshot(claim)
    claim.status = "published"
    write_revision(
        session, claim, before=before, change_item_id=change_item_id, actor=actor, reason=reason
    )
    if superseding is not None and superseding.status != "superseded":
        supersede_claim(
            session, superseding, claim, change_item_id=change_item_id, actor=actor, reason=reason
        )


def supersede_claim(
    session: Session,
    old: Claim,
    new: Claim,
    *,
    change_item_id: str | None,
    actor: str,
    reason: str | None = None,
) -> None:
    before = _snapshot(old)
    old.status = "superseded"
    old.superseded_by = new.id
    write_revision(
        session, old, before=before, change_item_id=change_item_id, actor=actor, reason=reason
    )


def retract_claim(
    session: Session,
    claim: Claim,
    *,
    change_item_id: str | None,
    actor: str,
    reason: str | None = None,
) -> None:
    before = _snapshot(claim)
    claim.status = "retracted"
    write_revision(
        session, claim, before=before, change_item_id=change_item_id, actor=actor, reason=reason
    )


# ------------------------------------------------------------------ 合并引擎


class MergeEngine:
    """一批 ProposedClaim vs 已有 Claim → ChangeItem 五种动作（K3）。"""

    def __init__(
        self,
        session: Session,
        *,
        policy: MergePolicy | None = None,
        risk_of: RiskResolver | None = None,
        created_by: str = "merge-engine",
    ) -> None:
        self.session = session
        self.policy = policy or MergePolicy()
        self.risk_of: RiskResolver = risk_of or (lambda predicate: "low")
        self.created_by = created_by
        self.judge_queue: list[ConflictJudgeRequest] = []

    # -- ChangeSet ---------------------------------------------------------

    def open_change_set(
        self,
        *,
        source_kind: str,
        knowledge_ids: list[str] | None = None,
        external_record_id: str | None = None,
        source_revision: str | None = None,
    ) -> tuple[ChangeSet, bool]:
        """批级幂等（K2.3）：同 (source_kind, external_record_id, source_revision)
        的已存在 ChangeSet 直接返回 (existing, False)。"""
        if external_record_id is not None:
            existing = self.session.execute(
                select(ChangeSet).where(
                    ChangeSet.source_kind == source_kind,
                    ChangeSet.external_record_id == external_record_id,
                    ChangeSet.source_revision == source_revision,
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing, False
        change_set = ChangeSet(
            source_kind=source_kind,
            knowledge_ids=knowledge_ids,
            external_record_id=external_record_id,
            source_revision=source_revision,
            status="pending",
            created_by=self.created_by,
        )
        self.session.add(change_set)
        self.session.flush()
        return change_set, True

    # -- 批应用 --------------------------------------------------------------

    def apply_batch(self, change_set: ChangeSet, proposals: list[ProposedClaim]) -> MergeReport:
        report = MergeReport(change_set_id=change_set.id)
        for prop in proposals:
            self._apply_one(change_set, prop, report)
        report.judge_queue_size = len(self.judge_queue)
        statuses = {
            item.decision
            for item in self.session.execute(
                select(ChangeItem).where(ChangeItem.change_set_id == change_set.id)
            ).scalars()
        }
        if statuses <= {"auto_applied", "approved"}:
            change_set.status = "applied"
        elif statuses & {"auto_applied", "approved"}:
            change_set.status = "partially_applied"
        else:
            change_set.status = "pending"
        self.session.flush()
        return report

    def _active_claim(self, product_version_id: str, predicate: str) -> Claim | None:
        rows = self.session.execute(
            select(Claim).where(
                Claim.product_version_id == product_version_id,
                Claim.predicate == predicate,
                Claim.status.in_(("published", "candidate", "draft")),
            )
        ).scalars().all()
        if not rows:
            return None
        return sorted(rows, key=lambda c: (_STATUS_RANK[c.status], c.created_at))[0]

    def _apply_one(self, change_set: ChangeSet, prop: ProposedClaim, report: MergeReport) -> None:
        existing = self._active_claim(prop.product_version_id, prop.predicate)
        if prop.value_state == "unknown":
            # K2.2：unknown 只落 draft 占位（禁止发布），已有事实时不产生任何变更
            if existing is None:
                self._add_unknown_placeholder(change_set, prop)
                report.bump("add")
            return
        if existing is None:
            self._do_add(change_set, prop, report)
        elif existing.value_state == "unknown":
            self._do_fill_unknown(change_set, prop, existing, report)
        elif prop.value_hash == _existing_value_hash(existing):
            self._do_enrich_append(change_set, prop, existing, report)
        else:
            self._adjudicate(change_set, prop, existing, report)

    # -- add ----------------------------------------------------------------

    def _add_unknown_placeholder(self, change_set: ChangeSet, prop: ProposedClaim) -> None:
        claim = create_claim(self.session, prop, status="draft")
        item = self._new_item(
            change_set,
            action="add",
            claim_id=claim.id,
            proposed={"claim": _prop_dump(prop), "mode": "unknown_placeholder"},
            decision="auto_applied",
            basis={"note": "unknown 占位 draft，禁止发布，等待后批 enrich 补全（K2.2）"},
        )
        write_revision(
            self.session, claim, before=None, change_item_id=item.id,
            actor=self.created_by, reason="add unknown placeholder",
        )

    def _do_add(self, change_set: ChangeSet, prop: ProposedClaim, report: MergeReport) -> None:
        risk = self.risk_of(prop.predicate)
        claim = create_claim(self.session, prop, status="candidate")
        item = self._new_item(
            change_set,
            action="add",
            claim_id=claim.id,
            proposed={"claim": _prop_dump(prop)},
            decision="needs_review",
            basis=None,
        )
        write_revision(
            self.session, claim, before=None, change_item_id=item.id,
            actor=self.created_by, reason="add candidate",
        )
        auto = self.policy.auto_apply_add and risk != "high" and not prop.pending_judge
        if auto:
            item.decision = "auto_applied"
            publish_claim(
                self.session, claim, change_item_id=item.id,
                actor=self.created_by, reason="auto add",
            )
        else:
            self._gate(item, prop, risk, report, new_claim_id=claim.id)
        report.bump("add")

    # -- enrich ---------------------------------------------------------------

    def _do_fill_unknown(
        self, change_set: ChangeSet, prop: ProposedClaim, placeholder: Claim, report: MergeReport
    ) -> None:
        """补 unknown 占位（03 §2.5 enrich 的"补 unknown 字段"分支）。"""
        risk = self.risk_of(prop.predicate)
        claim = create_claim(self.session, prop, status="candidate")
        item = self._new_item(
            change_set,
            action="enrich",
            claim_id=claim.id,
            proposed={
                "claim": _prop_dump(prop),
                "mode": "fill_unknown",
                "placeholder_claim_id": placeholder.id,
            },
            decision="needs_review",
            basis=None,
        )
        write_revision(
            self.session, claim, before=None, change_item_id=item.id,
            actor=self.created_by, reason="enrich fill unknown",
        )
        if self._enrich_auto_ok(prop, risk):
            item.decision = "auto_applied"
            publish_claim(
                self.session, claim, change_item_id=item.id, actor=self.created_by,
                reason="auto enrich fill", superseding=placeholder,
            )
        else:
            self._gate(item, prop, risk, report, new_claim_id=claim.id)
        report.bump("enrich")

    def _do_enrich_append(
        self, change_set: ChangeSet, prop: ProposedClaim, existing: Claim, report: MergeReport
    ) -> None:
        """同值追加证据，confidence 上调（03 §2.5 enrich）。"""
        risk = self.risk_of(prop.predicate)
        seen = {
            (e.knowledge_id, e.page, normalize_value(e.quote))
            for e in claim_evidence(self.session, existing.id)
        }
        new_evidence = [
            e for e in prop.evidence
            if (e.knowledge_id, e.page, normalize_value(e.quote)) not in seen
        ]
        new_confidence = min(0.99, max(existing.confidence, prop.confidence) + 0.05)
        if not new_evidence and new_confidence <= existing.confidence:
            return  # 无增量：不产生 ChangeItem（幂等）
        item = self._new_item(
            change_set,
            action="enrich",
            claim_id=existing.id,
            proposed={
                "mode": "append_evidence",
                "evidence": [e.model_dump(mode="json") for e in new_evidence],
                "confidence": new_confidence,
            },
            decision="needs_review",
            basis=None,
        )
        if self._enrich_auto_ok(prop, risk):
            item.decision = "auto_applied"
            _apply_enrich_append(self.session, item, actor=self.created_by)
        else:
            self._gate(item, prop, risk, report, new_claim_id=existing.id)
        report.bump("enrich")

    def _enrich_auto_ok(self, prop: ProposedClaim, risk: str) -> bool:
        """K4.4：默认关闭；开启后仅 risk=low 且 confidence≥阈值 且非 pending_judge。"""
        return (
            self.policy.auto_apply_enrich
            and risk == "low"
            and prop.confidence >= self.policy.enrich_auto_min_confidence
            and not prop.pending_judge
        )

    # -- 冲突裁决序（03 §6.2 逐级短路） -----------------------------------------

    def _adjudicate(
        self, change_set: ChangeSet, prop: ProposedClaim, existing: Claim, report: MergeReport
    ) -> None:
        risk = self.risk_of(prop.predicate)
        new_auth = prop.best_authority
        old_auth = claim_authority(self.session, existing)
        basis: dict[str, Any] = {
            "authority_cmp": f"proposed={new_auth} existing={old_auth}",
            "completeness_cmp": (
                f"proposed_len={len(normalize_value(prop.value))} "
                f"existing_len={len(normalize_value(claim_value_text(existing)))}"
                "（仅排序参考，永不压过①②）"
            ),
        }
        winner: str | None = None
        if new_auth < old_auth:
            winner = "proposed"
            basis["authority_cmp"] += " → proposed 胜（① 高权威直接胜出）"
        elif new_auth > old_auth:
            winner = "existing"
            basis["authority_cmp"] += " → existing 胜（① 低权威新值只进 conflict 记录）"
        else:
            basis["authority_cmp"] += " → 同级，进 ②"
            if (
                prop.effective_from is not None
                and existing.effective_from is not None
                and prop.effective_from != existing.effective_from
            ):
                newer = prop.effective_from > existing.effective_from
                winner = "proposed" if newer else "existing"
                basis["effective_cmp"] = (
                    f"proposed={prop.effective_from} existing={existing.effective_from}"
                    f" → {'proposed' if newer else 'existing'} 胜（② 生效新者胜）"
                )
            else:
                basis["effective_cmp"] = "无法比较（缺可靠 effective_from），进 ④/⑤"

        if winner == "existing":
            item = self._new_item(
                change_set,
                action="conflict",
                claim_id=None,
                proposed={"claim": _prop_dump(prop), "existing_claim_id": existing.id},
                decision="auto_applied",
                basis=basis,
            )
            self._new_conflict(item, existing, prop, basis, status="resolved")
            report.bump("conflict")
            return

        if winner == "proposed":
            claim = create_claim(self.session, prop, status="candidate")
            item = self._new_item(
                change_set,
                action="supersede",
                claim_id=claim.id,
                proposed={"claim": _prop_dump(prop), "existing_claim_id": existing.id},
                decision="needs_review",
                basis=basis,
            )
            write_revision(
                self.session, claim, before=None, change_item_id=item.id,
                actor=self.created_by, reason="supersede candidate",
            )
            auto = (
                risk != "high"
                and self.policy.auto_apply_supersede_low_risk
                and not prop.pending_judge
            )
            if auto:
                item.decision = "auto_applied"
                self._new_conflict(item, existing, prop, basis, status="resolved")
                publish_claim(
                    self.session, claim, change_item_id=item.id, actor=self.created_by,
                    reason="auto supersede（裁决序①/②）", superseding=existing,
                )
            else:
                # 高风险字段 supersede 一律进审核（03 §2.5/§6.2）
                conflict = self._new_conflict(item, existing, prop, basis, status="open")
                self._gate(
                    item, prop, "high", report,
                    new_claim_id=claim.id, conflict_id=conflict.id, type_="high_risk_change",
                )
            report.bump("supersede")
            return

        # 裁决序①②未分胜负：conflict（冲突未决期间旧 published 不动、新值停 candidate，K3.4）
        claim = create_claim(self.session, prop, status="candidate")
        item = self._new_item(
            change_set,
            action="conflict",
            claim_id=claim.id,
            proposed={"claim": _prop_dump(prop), "existing_claim_id": existing.id},
            decision="needs_review",
            basis=basis,
        )
        write_revision(
            self.session, claim, before=None, change_item_id=item.id,
            actor=self.created_by, reason="conflict candidate",
        )
        if risk == "high":
            # 高风险跳过④直接⑤（03 §6.2）
            conflict = self._new_conflict(item, existing, prop, basis, status="open")
            self._gate(
                item, prop, "high", report,
                new_claim_id=claim.id, conflict_id=conflict.id, type_="conflict",
            )
        else:
            conflict = self._new_conflict(item, existing, prop, basis, status="pending_judge")
            self.judge_queue.append(
                ConflictJudgeRequest(
                    conflict_id=conflict.id,
                    product_version_id=prop.product_version_id,
                    predicate=prop.predicate,
                    field_name=prop.field_name,
                    existing={
                        "value": claim_value_text(existing),
                        "value_state": existing.value_state,
                        "evidence": [
                            {"knowledge_id": e.knowledge_id, "page": e.page, "quote": e.quote}
                            for e in claim_evidence(self.session, existing.id)
                        ],
                    },
                    proposed=_prop_dump(prop),
                )
            )
        report.bump("conflict")

    # -- 内部构件 --------------------------------------------------------------

    def _new_item(
        self,
        change_set: ChangeSet,
        *,
        action: str,
        claim_id: str | None,
        proposed: dict[str, Any],
        decision: str,
        basis: dict[str, Any] | None,
    ) -> ChangeItem:
        item = ChangeItem(
            change_set_id=change_set.id,
            action=action,
            claim_id=claim_id,
            proposed=proposed,
            decision=decision,
            decision_basis=basis,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def _new_conflict(
        self,
        item: ChangeItem,
        existing: Claim,
        prop: ProposedClaim,
        basis: dict[str, Any],
        *,
        status: str,
    ) -> Conflict:
        conflict = Conflict(
            change_item_id=item.id,
            existing_claim_id=existing.id,
            proposed=_prop_dump(prop),
            decision_basis=basis,
            status=status,
        )
        self.session.add(conflict)
        self.session.flush()
        return conflict

    def _gate(
        self,
        item: ChangeItem,
        prop: ProposedClaim,
        risk: str,
        report: MergeReport,
        *,
        new_claim_id: str | None,
        conflict_id: str | None = None,
        type_: str | None = None,
    ) -> None:
        """审核门禁（K4.1）：needs_review 的 ChangeItem 挂稳定 ID ReviewItem。"""
        review_type = type_ or ("high_risk_change" if risk == "high" else "low_confidence")
        key = derive_review_key(
            review_type, prop.product_version_id, prop.predicate, prop.value_hash
        )
        _, created = ensure_review_item(
            self.session,
            review_key=key,
            type_=review_type,
            subject={
                "change_item_id": item.id,
                "new_claim_id": new_claim_id,
                "conflict_id": conflict_id,
                "predicate": prop.predicate,
            },
            risk_level=risk,
        )
        if key not in report.review_keys:
            report.review_keys.append(key)


def _prop_dump(prop: ProposedClaim) -> dict[str, Any]:
    return prop.model_dump(mode="json")


def _existing_value_hash(claim: Claim) -> str:
    from insurance_harness.knowledge.models import value_hash

    return value_hash(claim.value_state, claim_value_text(claim))


# ------------------------------------------------------------------ 应用与审核动作


def _apply_enrich_append(session: Session, item: ChangeItem, *, actor: str) -> None:
    claim = session.get(Claim, item.claim_id)
    assert claim is not None
    before = _snapshot(claim)
    for e in item.proposed.get("evidence", []):
        session.add(
            ClaimEvidence(
                claim_id=claim.id,
                knowledge_id=e["knowledge_id"],
                chunk_id=e.get("chunk_id"),
                quote=e["quote"],
                page=e.get("page"),
                authority_level=e.get("authority_level", 6),
                doc_role=e.get("doc_role", "external"),
                extraction_method=e.get("extraction_method", "llm"),
            )
        )
    claim.confidence = float(item.proposed.get("confidence", claim.confidence))
    write_revision(
        session, claim, before=before, change_item_id=item.id,
        actor=actor, reason="enrich append evidence",
    )


def apply_change_item(
    session: Session,
    item: ChangeItem,
    *,
    actor: str,
    decision: str = "approved",
    reason: str | None = None,
    llm_verdict: str | None = None,
) -> None:
    """采纳一个 needs_review/pending 的 ChangeItem（approve 或 ④ 裁决回写）。"""
    if item.action == "enrich" and item.proposed.get("mode") == "append_evidence":
        _apply_enrich_append(session, item, actor=actor)
    else:
        assert item.claim_id is not None
        claim = session.get(Claim, item.claim_id)
        assert claim is not None
        old_id = item.proposed.get("existing_claim_id") or item.proposed.get(
            "placeholder_claim_id"
        )
        old = session.get(Claim, old_id) if old_id else None
        publish_claim(
            session, claim, change_item_id=item.id, actor=actor, reason=reason, superseding=old
        )
    item.decision = decision
    basis = dict(item.decision_basis or {})
    if llm_verdict is not None:
        basis["llm_verdict"] = llm_verdict
    if decision == "approved":
        basis["reviewer"] = actor
    item.decision_basis = basis
    _resolve_conflicts_of(session, item, basis)
    session.flush()


def reject_change_item(
    session: Session,
    item: ChangeItem,
    *,
    actor: str,
    reason: str | None = None,
    llm_verdict: str | None = None,
) -> None:
    """驳回：候选 Claim → retracted，旧值保持 published（K4.2）。"""
    if item.claim_id is not None:
        claim = session.get(Claim, item.claim_id)
        if claim is not None and claim.status in ("candidate", "draft"):
            retract_claim(
                session, claim, change_item_id=item.id, actor=actor, reason=reason or "rejected"
            )
    item.decision = "rejected"
    basis = dict(item.decision_basis or {})
    basis["reviewer"] = actor
    if llm_verdict is not None:
        basis["llm_verdict"] = llm_verdict
    if reason:
        basis["review_reason"] = reason
    item.decision_basis = basis
    _resolve_conflicts_of(session, item, basis)
    session.flush()


def _resolve_conflicts_of(
    session: Session, item: ChangeItem, basis: dict[str, Any]
) -> None:
    conflicts = session.execute(
        select(Conflict).where(Conflict.change_item_id == item.id)
    ).scalars()
    for conflict in conflicts:
        conflict.status = "resolved"
        conflict.decision_basis = basis


def resolve_review(
    session: Session,
    review_key: str,
    action: str,
    *,
    actor: str,
    reason: str | None = None,
) -> ReviewItem:
    """受限动作集 approve/reject/defer（K4.2）；已决项翻案走 overturn_review。"""
    item = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == review_key)
    ).scalar_one_or_none()
    if item is None:
        raise KeyError(f"review item {review_key} 不存在")
    if action not in item.allowed_actions:
        raise ValueError(f"动作 {action!r} 不在受限动作集 {item.allowed_actions} 中")
    if item.status != "open":
        raise ValueError(
            f"review item {review_key} 已决（{item.status}）；翻案请走 overturn_review"
        )
    if action == "defer":
        return item  # 保持 open，不落 resolution
    change_item = session.get(ChangeItem, item.subject["change_item_id"])
    assert change_item is not None
    if action == "approve":
        apply_change_item(session, change_item, actor=actor, decision="approved", reason=reason)
    else:
        reject_change_item(session, change_item, actor=actor, reason=reason)
    item.status = "resolved"
    item.resolution = {
        "action": action,
        "actor": actor,
        "reason": reason,
        "at": utcnow().isoformat(),
    }
    session.flush()
    return item


def overturn_review(
    session: Session,
    review_key: str,
    new_action: str,
    *,
    actor: str,
    reason: str,
) -> ChangeSet:
    """翻案 = 新 ChangeSet（K3.5）：原 ChangeSet 与原 decision_basis 不改写。"""
    item = session.execute(
        select(ReviewItem).where(ReviewItem.review_key == review_key)
    ).scalar_one_or_none()
    if item is None or item.status != "resolved" or item.resolution is None:
        raise ValueError(f"review item {review_key} 不是已决项，不能翻案")
    prev = str(item.resolution["action"])
    if new_action == prev or new_action not in ("approve", "reject"):
        raise ValueError(f"翻案动作 {new_action!r} 无效（原决定 {prev!r}）")
    original = session.get(ChangeItem, item.subject["change_item_id"])
    assert original is not None
    change_set = ChangeSet(
        source_kind="manual_edit",
        knowledge_ids=None,
        status="applied",
        created_by=actor,
    )
    session.add(change_set)
    session.flush()
    if new_action == "reject":
        # 撤销先前采纳：新 Claim 撤回，被取代的旧 Claim 恢复 published
        assert original.claim_id is not None
        adopted = session.get(Claim, original.claim_id)
        assert adopted is not None
        reversal = ChangeItem(
            change_set_id=change_set.id,
            action="retract",
            claim_id=adopted.id,
            proposed={"overturn_of": original.id},
            decision="approved",
            decision_basis={"reviewer": actor, "review_reason": reason},
        )
        session.add(reversal)
        session.flush()
        retract_claim(session, adopted, change_item_id=reversal.id, actor=actor, reason=reason)
        old_id = original.proposed.get("existing_claim_id") or original.proposed.get(
            "placeholder_claim_id"
        )
        old = session.get(Claim, old_id) if old_id else None
        if old is not None and old.status == "superseded":
            before = _snapshot(old)
            old.status = "published"
            old.superseded_by = None
            write_revision(
                session, old, before=before, change_item_id=reversal.id,
                actor=actor, reason=f"翻案恢复：{reason}",
            )
    else:
        # 撤销先前驳回：按原提案重新应用
        reversal = ChangeItem(
            change_set_id=change_set.id,
            action=original.action,
            claim_id=original.claim_id,
            proposed=dict(original.proposed),
            decision="needs_review",
            decision_basis={"overturn_of": original.id},
        )
        session.add(reversal)
        session.flush()
        if original.claim_id is not None:
            claim = session.get(Claim, original.claim_id)
            if claim is not None and claim.status == "retracted":
                before = _snapshot(claim)
                claim.status = "candidate"
                write_revision(
                    session, claim, before=before, change_item_id=reversal.id,
                    actor=actor, reason=f"翻案恢复候选：{reason}",
                )
        apply_change_item(session, reversal, actor=actor, decision="approved", reason=reason)
    item.resolution = {
        "action": new_action,
        "actor": actor,
        "reason": reason,
        "overturned_from": prev,
        "at": utcnow().isoformat(),
    }
    session.flush()
    return change_set


# ------------------------------------------------------------------ ④ claude-session 队列


def write_conflict_judge_queue(path: Path, queue: list[ConflictJudgeRequest]) -> None:
    """judge-queue.jsonl 形态落盘（复用 compiler judge-queue 的行式 JSONL 约定）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(r.model_dump_json() + "\n" for r in queue), encoding="utf-8")


def read_conflict_judgements(path: Path) -> list[ConflictJudgement]:
    return [
        ConflictJudgement.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def apply_conflict_judgements(
    session: Session,
    judgements: list[ConflictJudgement],
    *,
    actor: str = "claude-session",
) -> int:
    """④ 裁决回写：按 llm_verdict 裁决并留痕（K3.2）；只处理 pending_judge 的冲突。"""
    applied = 0
    for judgement in judgements:
        conflict = session.get(Conflict, judgement.conflict_id)
        if conflict is None or conflict.status != "pending_judge":
            continue
        item = session.get(ChangeItem, conflict.change_item_id)
        assert item is not None
        if judgement.winner == "proposed":
            apply_change_item(
                session, item, actor=actor, decision="auto_applied",
                reason="④ LLM 裁决（claude-session 回写）", llm_verdict=judgement.reasoning,
            )
        else:
            reject_change_item(
                session, item, actor=actor,
                reason="④ LLM 裁决（claude-session 回写）", llm_verdict=judgement.reasoning,
            )
        applied += 1
    return applied


# ------------------------------------------------------------------ retract（来源删除）


def retract_source(
    session: Session, knowledge_id: str, *, created_by: str = "retractor"
) -> MergeReport:
    """来源删除按证据引用计数（03 §2.4）：仍有其他证据 → 仅移除 Evidence；
    证据清零 → Claim 转 retracted 并进 ChangeSet 留痕。"""
    evidence = list(
        session.execute(
            select(ClaimEvidence).where(ClaimEvidence.knowledge_id == knowledge_id)
        ).scalars()
    )
    report = MergeReport()
    if not evidence:
        return report
    change_set = ChangeSet(
        source_kind="document",
        knowledge_ids=[knowledge_id],
        status="applied",
        created_by=created_by,
    )
    session.add(change_set)
    session.flush()
    report.change_set_id = change_set.id
    by_claim: dict[str, list[ClaimEvidence]] = {}
    for e in evidence:
        by_claim.setdefault(e.claim_id, []).append(e)
    for claim_id, rows in by_claim.items():
        claim = session.get(Claim, claim_id)
        assert claim is not None
        removed_ids = {e.id for e in rows}
        remaining = [e for e in claim_evidence(session, claim_id) if e.id not in removed_ids]
        for e in rows:
            session.delete(e)
        item = ChangeItem(
            change_set_id=change_set.id,
            action="retract",
            claim_id=claim_id,
            proposed={"knowledge_id": knowledge_id, "removed_evidence": len(rows)},
            decision="auto_applied",
            decision_basis={
                "note": f"来源删除；剩余证据 {len(remaining)} 条"
                + ("→ Claim retracted" if not remaining else "，Claim 保留")
            },
        )
        session.add(item)
        session.flush()
        if not remaining and claim.status in ("published", "candidate", "draft"):
            retract_claim(
                session, claim, change_item_id=item.id, actor=created_by,
                reason=f"来源 {knowledge_id} 删除后证据清零",
            )
        report.bump("retract")
    session.flush()
    return report
