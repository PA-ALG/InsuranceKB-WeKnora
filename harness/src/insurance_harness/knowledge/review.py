"""审核项：内容派生稳定 ID + 受限动作集（docs/insurance-kb/03 §2.6；K4）。

思想借鉴上游 llm_wiki review-store（思想重实现，不复制 GPL 代码）：
pipeline 重跑/文档重传时同一逻辑审核项 review_key 不变——不重建、已决状态不丢。
"""

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.knowledge.models import ALLOWED_REVIEW_ACTIONS
from insurance_harness.knowledge.tables import ReviewItem


def derive_review_key(
    type_: str, subject_ref: str, predicate: str, value_hash_: str
) -> str:
    """内容派生稳定 ID（K4.1）：sha256(type::subject_ref::predicate::value_hash) 前 40 位。"""
    payload = f"{type_}::{subject_ref}::{predicate}::{value_hash_}"
    return "rv-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]


def get_review_item(session: Session, review_key: str) -> ReviewItem | None:
    return session.execute(
        select(ReviewItem).where(ReviewItem.review_key == review_key)
    ).scalar_one_or_none()


def ensure_review_item(
    session: Session,
    *,
    review_key: str,
    type_: str,
    subject: dict[str, Any],
    risk_level: str = "low",
) -> tuple[ReviewItem, bool]:
    """幂等创建：已存在（含已决）直接返回，绝不重建/重置状态（K4.1）。

    返回 (item, created)。
    """
    existing = get_review_item(session, review_key)
    if existing is not None:
        return existing, False
    item = ReviewItem(
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
