"""024 归因工单注册表（E1.1）：005 归因清单的机器可读固化。

来源：`openspec/changes/005-eval-refinement-recall/validation-report.md`
（3 基线产品：extract_empty 24 条 + 1 条 prompt 域 routing_miss——005 结论
"随 extract_empty 一并进入 prompt 变体迭代"）。
ticket_id = "{product_key}:{field_id}"，测试用例名引用该标识（E1.1）。
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from insurance_harness.schemas import FieldSpec

Reason = Literal["extract_empty", "routing_miss_prompt_domain"]

_SSJY: Final[str] = "平安盛世金越（尊享版26）终身寿"
_ESB: Final[str] = "平安e生保（尊享版）医疗保险"
_SHBFB: Final[str] = "平安守护百分百（2026）两全保"


class RecallTicket(BaseModel):
    """一条归因工单：字段在真实基线中漏抽的现场记录。"""

    model_config = ConfigDict(frozen=True)

    ticket_id: str
    product: str
    product_key: str
    field_id: str
    field_name: str
    group: str
    doc: str
    evidence_pages: tuple[int, ...]
    reason: Reason = "extract_empty"
    unknown_reason: str | None = None


def _t(
    product_key: str,
    product: str,
    field_name: str,
    field_id: str,
    group: str,
    doc: str,
    pages: tuple[int, ...],
    reason: Reason = "extract_empty",
    unknown_reason: str | None = None,
) -> RecallTicket:
    return RecallTicket(
        ticket_id=f"{product_key}:{field_id}",
        product=product,
        product_key=product_key,
        field_id=field_id,
        field_name=field_name,
        group=group,
        doc=doc,
        evidence_pages=pages,
        reason=reason,
        unknown_reason=unknown_reason,
    )


ALL_TICKETS: Final[tuple[RecallTicket, ...]] = (
    # --- 平安盛世金越（尊享版26）终身寿：10 条 ---
    _t("ssjy", _SSJY, "主附加险", "zh_67ee7025ef", "basic_info", "保险条款.pdf", (7,)),
    _t("ssjy", _SSJY, "交费期限", "zh_14b93ce275", "basic_info", "费率表.pdf", (1,)),
    _t(
        "ssjy", _SSJY, "理赔申请时效与申请材料", "claim_filing_requirements",
        "claim_service", "保险条款.pdf", (5,),
    ),
    _t("ssjy", _SSJY, "保障人群", "zh_58d313ee26", "basic_info", "保险条款.pdf", (8,)),
    _t("ssjy", _SSJY, "免责少", "zh_f93c945d66", "exclusion_uw", "保险条款.pdf", (3, 4)),
    _t("ssjy", _SSJY, "意外身故", "zh_69f97f5c40", "coverage", "保险条款.pdf", (1, 2)),
    _t("ssjy", _SSJY, "疾病身故", "zh_17ba71cda4", "coverage", "保险条款.pdf", (1, 2)),
    _t("ssjy", _SSJY, "保证利率", "zh_7be37f7605", "cost_rules", "产品说明书.pdf", (1,)),
    _t("ssjy", _SSJY, "特殊免责", "zh_e1bea0527a", "exclusion_uw", "保险条款.pdf", (3,)),
    _t(
        "ssjy", _SSJY, "演示利率口径", "illustrated_rate_basis",
        "cost_rules", "产品说明书.pdf", (1,),
    ),
    # --- 平安e生保（尊享版）医疗保险：6 条 extract_empty + 1 条 prompt 域 ---
    _t("esb", _ESB, "产品类别", "zh_ad4a95859a", "basic_info", "保险条款.pdf", (1,)),
    _t(
        "esb", _ESB, "产品类型", "zh_0b3894ed2a", "basic_info", "保险条款.pdf", (9,),
        reason="routing_miss_prompt_domain",
    ),
    _t("esb", _ESB, "保单权益", "zh_a271d96039", "coverage", "保险条款.pdf", (1,)),
    _t("esb", _ESB, "产品搭配规则", "zh_0c5a8e59e2", "basic_info", "保险条款.pdf", (2, 39)),
    _t(
        "esb", _ESB, "理赔申请时效与申请材料", "claim_filing_requirements",
        "claim_service", "保险条款.pdf", (24,),
    ),
    _t("esb", _ESB, "投保职业", "zh_c588207763", "basic_info", "保险条款.pdf", (38, 39)),
    _t("esb", _ESB, "特殊免责", "zh_e1bea0527a", "exclusion_uw", "保险条款.pdf", (21, 22)),
    # --- 平安守护百分百（2026）两全保：8 条 ---
    _t("shbfb", _SHBFB, "主附加险", "zh_67ee7025ef", "basic_info", "保险条款.pdf", (2,)),
    _t("shbfb", _SHBFB, "产品搭配规则", "zh_0c5a8e59e2", "basic_info", "保险条款.pdf", (2,)),
    _t(
        "shbfb", _SHBFB, "等待期内出险处理", "waiting_period_claim_handling",
        "basic_info", "保险条款.pdf", (9,),
    ),
    _t(
        "shbfb", _SHBFB, "理赔申请时效与申请材料", "claim_filing_requirements",
        "claim_service", "保险条款.pdf", (5,), unknown_reason="quote_mismatch",
    ),
    _t("shbfb", _SHBFB, "免责少", "zh_f93c945d66", "exclusion_uw", "保险条款.pdf", (3, 4)),
    _t("shbfb", _SHBFB, "意外身故", "zh_69f97f5c40", "coverage", "保险条款.pdf", (2, 3)),
    _t("shbfb", _SHBFB, "疾病身故", "zh_17ba71cda4", "coverage", "保险条款.pdf", (2, 3)),
    _t("shbfb", _SHBFB, "特殊免责", "zh_e1bea0527a", "exclusion_uw", "保险条款.pdf", (3,)),
)

EXTRACT_EMPTY_TICKETS: Final[tuple[RecallTicket, ...]] = tuple(
    t for t in ALL_TICKETS if t.reason == "extract_empty"
)


def field_spec_for(ticket: RecallTicket) -> FieldSpec:
    """工单 → 最小可运行 FieldSpec（回放用例用；aliases 走 routing_data 同义词库）。"""
    return FieldSpec(
        name=ticket.field_name,
        field_id=ticket.field_id,
        source_sheet="024-recall",
    )
