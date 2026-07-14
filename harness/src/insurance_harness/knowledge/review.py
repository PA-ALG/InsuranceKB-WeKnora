"""审核项：内容派生稳定 ID + 受限动作集（docs/insurance-kb/03 §2.6；K4）。

思想借鉴上游 llm_wiki review-store（思想重实现，不复制 GPL 代码）：
pipeline 重跑/文档重传时同一逻辑审核项 review_key 不变——不重建、已决状态不丢。
"""

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
    require_current_scope,
)
from insurance_harness.knowledge.models import ALLOWED_REVIEW_ACTIONS
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    Conflict,
    ReviewItem,
)


class _ReviewSubjectRefs(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    change_item_id: str | None = None
    new_claim_id: str | None = None
    conflict_id: str | None = None


def _require_scoped_review_subject(
    session: Session,
    scope: KnowledgeScope,
    subject: dict[str, Any],
) -> _ReviewSubjectRefs:
    try:
        refs = _ReviewSubjectRefs.model_validate(subject)
    except ValidationError as exc:
        raise ScopeViolation("scope mismatch") from exc
    if (refs.new_claim_id or refs.conflict_id) and not refs.change_item_id:
        raise ScopeViolation("scope mismatch")
    change_item: ChangeItem | None = None
    if refs.change_item_id:
        change_item = session.execute(
            select(ChangeItem)
            .join(ChangeSet, ChangeSet.id == ChangeItem.change_set_id)
            .where(
                ChangeItem.id == refs.change_item_id,
                ChangeSet.space_id == scope.space_id,
            )
        ).scalar_one_or_none()
        if change_item is None:
            raise ScopeViolation("scope mismatch")
    if refs.new_claim_id:
        found = session.execute(
            select(Claim.id).where(
                Claim.id == refs.new_claim_id,
                Claim.space_id == scope.space_id,
            )
        ).scalar_one_or_none()
        if found is None:
            raise ScopeViolation("scope mismatch")
    conflict: Conflict | None = None
    if refs.conflict_id:
        conflict = session.execute(
            select(Conflict)
            .join(ChangeItem, ChangeItem.id == Conflict.change_item_id)
            .join(ChangeSet, ChangeSet.id == ChangeItem.change_set_id)
            .where(
                Conflict.id == refs.conflict_id,
                ChangeSet.space_id == scope.space_id,
            )
        ).scalar_one_or_none()
        if conflict is None:
            raise ScopeViolation("scope mismatch")
    if change_item is not None:
        if (
            refs.new_claim_id is not None
            and change_item.claim_id != refs.new_claim_id
        ):
            raise ScopeViolation("scope mismatch")
        if conflict is not None and conflict.change_item_id != change_item.id:
            raise ScopeViolation("scope mismatch")
    return refs


def derive_review_key(
    type_: str, subject_ref: str, predicate: str, value_hash_: str
) -> str:
    """内容派生稳定 ID（K4.1）：sha256(type::subject_ref::predicate::value_hash) 前 40 位。"""
    payload = f"{type_}::{subject_ref}::{predicate}::{value_hash_}"
    return "rv-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]


def get_review_item(
    session: Session, scope: KnowledgeScope, review_key: str
) -> ReviewItem | None:
    require_current_scope(session, scope)
    return session.execute(
        select(ReviewItem).where(
            ReviewItem.space_id == scope.space_id,
            ReviewItem.review_key == review_key,
        )
    ).scalar_one_or_none()


def ensure_review_item(
    session: Session,
    *,
    scope: KnowledgeScope,
    review_key: str,
    type_: str,
    subject: dict[str, Any],
    risk_level: str = "low",
) -> tuple[ReviewItem, bool]:
    """幂等创建：已存在（含已决）直接返回，绝不重建/重置状态（K4.1）。

    返回 (item, created)。
    """
    require_current_scope(session, scope)
    _require_scoped_review_subject(session, scope, subject)
    existing = get_review_item(session, scope, review_key)
    if existing is not None:
        return existing, False
    item = ReviewItem(
        space_id=scope.space_id,
        review_key=review_key,
        type=type_,
        subject=subject,
        allowed_actions=list(ALLOWED_REVIEW_ACTIONS),
        status="open",
        risk_level=risk_level,
    )
    session.add(item)
    session.flush()
    return item, True
