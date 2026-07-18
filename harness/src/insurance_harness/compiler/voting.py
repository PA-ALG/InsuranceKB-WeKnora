"""高风险字段自一致性投票（004 T6；spec E4.2/E4.3；设计 04 Step 5）。

只对 risk_level=high 字段发生（成本控制，E4.3）；3 次独立采样用 3 个 prompt 变体
（直接问/表格式/逐条款式）产生多样性。3/3 → high；2/3 → medium 采多数；
三票三样 → confidence=low + 三个候选值入 metadata + 进裁决（可插拔，见 judge.py）。
"""

from collections.abc import Sequence

from ..goldenset.normalize import values_equal
from ..goldenset.pdf import PageText
from ..schemas import FieldSpec
from .extract import _candidate_from_item, call_and_parse
from .llm import ModelClient
from .models import FieldCandidate
from .prompts import EXTRACTION_SYSTEM, PROMPT_VERSION, build_vote_user
from .verification import all_quotes_verified

VOTE_SAMPLES = 3


def _context_fragments(
    cand: FieldCandidate, pages: Sequence[PageText]
) -> tuple[PageText, ...]:
    """投票上下文 = 候选值证据所在页全文（含前后页兜底）。"""
    ev_pages = {e.page for e in cand.evidence}
    hit = tuple(p for p in pages if p.page_no in ev_pages)
    return hit or tuple(pages[:2])


async def vote_field(
    client: ModelClient,
    product_name: str,
    field: FieldSpec,
    cand: FieldCandidate,
    pages: Sequence[PageText],
) -> FieldCandidate:
    """对一个已产出 present 候选值的高风险字段做 3 采样多数票。"""
    fragments = _context_fragments(cand, pages)
    samples: list[FieldCandidate] = []
    attempt_log: list[dict[str, object]] = []
    sample_attempt: dict[int, str] = {}  # sample 下标 → 产生它的 attempt_id
    for variant in range(VOTE_SAMPLES):
        user = build_vote_user(product_name, cand.doc, field, fragments, variant)
        before = len(attempt_log)
        parsed = await call_and_parse(
            client, EXTRACTION_SYSTEM, user,
            attempt_log=attempt_log,
            stage="vote", prompt_version=f"vote@{PROMPT_VERSION}",
        )
        if not parsed:
            continue
        item = next(
            (i for i in parsed if str(i.get("field_id")) == field.field_id), parsed[0]
        )
        sample_attempt[len(samples)] = str(attempt_log[before]["attempt_id"])
        samples.append(_candidate_from_item(item, field, cand.doc))

    values = [s.value for s in samples if s.tri_state == "present" and s.value]
    # 归一化等价分桶（数值/日期/枚举同义合一）
    buckets: list[tuple[str, int]] = []  # (代表值, 票数)
    for v in values:
        for i, (rep, n) in enumerate(buckets):
            if values_equal(rep, v):
                buckets[i] = (rep, n + 1)
                break
        else:
            buckets.append((v, 1))
    buckets.sort(key=lambda t: -t[1])

    if buckets and buckets[0][1] >= 2:
        majority, votes = buckets[0]
        agreement = votes
        updates: dict[str, object] = {
            "origin": "vote",
            "vote_agreement": agreement,
            "confidence": "high" if agreement >= VOTE_SAMPLES else "medium",
        }
        if not values_equal(cand.value, majority):
            # 多数票推翻原值：采多数，但证据必须来自可回验的采样，否则保守持原值降级
            winner = next(
                (
                    s
                    for s in samples
                    if s.value is not None
                    and values_equal(s.value, majority)
                    and all_quotes_verified(s.evidence, pages)
                ),
                None,
            )
            if winner is not None:
                updates.update({"value": winner.value, "evidence": winner.evidence})
                # E7 R2：多数票改写最终值——winning 指向产生该值的 vote attempt
                updates["metadata"] = {
                    **cand.metadata,
                    "attempts": [*cand.metadata.get("attempts", []), *attempt_log],
                    "winning_attempt_id": sample_attempt.get(
                        samples.index(winner),
                        cand.metadata.get("winning_attempt_id"),
                    ),
                }
            else:
                updates["confidence"] = "low"
        out = cand.model_copy(update=updates)
        if "metadata" not in updates:
            # 维持原值（vote 只确证）：attempts 追加，winning 仍指向原产生者
            out.metadata["attempts"] = [
                *cand.metadata.get("attempts", []), *attempt_log
            ]
        return out

    # 三票三样（或有效样本不足）：低置信 + 候选值留痕（E4.2），交裁决
    out = cand.model_copy(
        update={"origin": "vote", "vote_agreement": 1, "confidence": "low"}
    )
    out.metadata["vote_candidates"] = values or [cand.value]
    out.metadata["attempts"] = [*cand.metadata.get("attempts", []), *attempt_log]
    return out
