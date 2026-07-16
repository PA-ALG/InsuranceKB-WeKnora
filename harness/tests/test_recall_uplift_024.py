"""024 抽取召回提升——T1 机制合同用例（先全部 RED，本任务不修，E1.1）。

证明力边界（024 spec 头部）：本文件全部为**机制合同**用例——脚本/回放响应只证明
编排、解析与护栏行为符合规格，不证明模型因新 prompt 抽得更好；真实召回结论归
020 D4。金标不出现在任何触发条件中（E3）。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from insurance_harness.compiler.cleaning import clean_value
from insurance_harness.compiler.gapfill import gapfill_field
from insurance_harness.compiler.models import FieldCandidate
from insurance_harness.compiler.sections import DocSection
from insurance_harness.goldenset.pdf import PageText
from tests.support.recall_tickets_024 import (
    ALL_TICKETS,
    EXTRACT_EMPTY_TICKETS,
    RecallTicket,
    field_spec_for,
)

# ---------------------------------------------------------------------------
# E1.1 注册表自洽：工单固化必须与 005 归因清单逐条对得上
# ---------------------------------------------------------------------------


def test_e1_1_registry_matches_attribution_totals() -> None:
    assert len(EXTRACT_EMPTY_TICKETS) == 24, "005 归因清单 extract_empty 恰为 24 条"
    assert len(ALL_TICKETS) == 25, "外加 1 条 prompt 域 routing_miss（005 结论并入）"
    per_product = {
        key: sum(1 for t in EXTRACT_EMPTY_TICKETS if t.product_key == key)
        for key in ("ssjy", "esb", "shbfb")
    }
    assert per_product == {"ssjy": 10, "esb": 6, "shbfb": 8}
    assert len({t.ticket_id for t in ALL_TICKETS}) == len(ALL_TICKETS)
    known_groups = {"basic_info", "coverage", "cost_rules", "exclusion_uw", "claim_service"}
    assert {t.group for t in ALL_TICKETS} <= known_groups
    quote_mismatch = [t for t in ALL_TICKETS if t.unknown_reason == "quote_mismatch"]
    assert [t.ticket_id for t in quote_mismatch] == ["shbfb:claim_filing_requirements"]


# ---------------------------------------------------------------------------
# E1.1 × E2.2 逐工单机制合同：定向补漏产出经回验候选，且 pred 元数据带变体版本
# ---------------------------------------------------------------------------


class _TicketScriptedClient:
    """按工单构造的确定性假模型：命中该字段即给出可回验的 present 候选。"""

    def __init__(self, ticket: RecallTicket, quote: str) -> None:
        self._ticket = ticket
        self._quote = quote
        self.calls = 0

    async def complete(self, system: str, user: str) -> str:
        self.calls += 1
        item: dict[str, Any] = {
            "field_id": self._ticket.field_id,
            "value": f"{self._ticket.field_name}的核对结论",
            "tri_state": "present",
            "evidence": [{"page": self._ticket.evidence_pages[0], "quote": self._quote}],
        }
        return json.dumps([item], ensure_ascii=False)


def _ticket_section(ticket: RecallTicket, quote: str) -> DocSection:
    page_no = ticket.evidence_pages[0]
    text = f"第X条 {ticket.field_name}：{quote}。"
    return DocSection(
        section_id=f"sec-{ticket.field_id}",
        title=ticket.field_name,
        headings=(ticket.field_name,),
        fragments=(PageText(page_no=page_no, text=text),),
    )


@pytest.mark.parametrize("ticket", EXTRACT_EMPTY_TICKETS, ids=lambda t: t.ticket_id)
def test_e1_1_ticket_targeted_gapfill_yields_verified_candidate_with_variant_audit(
    ticket: RecallTicket,
) -> None:
    """工单场景：首轮空 → 定向补漏 → 回验通过的候选；元数据含变体版本（E2.2）。"""
    field = field_spec_for(ticket)
    quote = f"{ticket.field_name}按本合同约定的具体内容执行"
    section = _ticket_section(ticket, quote)
    client = _TicketScriptedClient(ticket, quote)
    cand: FieldCandidate = asyncio.run(
        gapfill_field(
            client,
            ticket.product,
            field,
            [(ticket.doc, section)],
            {ticket.doc: list(section.fragments)},
        )
    )
    # 机制合同（现有能力，应通过）：定向补漏产出经回验的 present 候选
    assert cand.origin == "gapfill", f"{ticket.ticket_id} 未触发补漏产出"
    assert cand.tri_state == "present" and cand.evidence, "回验证据缺失"
    # E2.2（RED）：所用 prompt 变体的版本化标识必须进入 pred 元数据（020 A/B 对账）
    assert "prompt_variant" in cand.metadata, (
        f"{ticket.ticket_id}: E2.2 要求 metadata 含版本化 prompt_variant 标识"
    )


# ---------------------------------------------------------------------------
# E2 prompt 变体机制（RED：模块尚不存在）
# ---------------------------------------------------------------------------


def test_e2_1_variant_registry_single_source_and_deterministic() -> None:
    from insurance_harness.compiler.variants import (  # noqa: PLC0415
        VariantRegistry,
        select_variant,
    )

    registry = VariantRegistry.default()
    first = select_variant(registry, group="basic_info", field_id="zh_67ee7025ef")
    second = select_variant(registry, group="basic_info", field_id="zh_67ee7025ef")
    assert first.version and first.version == second.version, "同输入必须同变体（E2.1）"


def test_e2_3_unregistered_group_falls_back_to_default_prompt() -> None:
    from insurance_harness.compiler.variants import (  # noqa: PLC0415
        VariantRegistry,
        select_variant,
    )

    registry = VariantRegistry.default()
    variant = select_variant(registry, group="no_such_group_024", field_id="x")
    assert variant.is_default, "未注册字段组必须回落默认 prompt（E2.3）"


# ---------------------------------------------------------------------------
# E3 定向补漏模板：schema 驱动触发，金标不得参与（RED：定向模板尚不存在）
# ---------------------------------------------------------------------------


def test_e3_1_targeted_template_exists_and_trigger_is_schema_driven() -> None:
    import inspect

    from insurance_harness.compiler import gapfill as gapfill_mod

    build = getattr(gapfill_mod, "build_targeted_gapfill_user", None)
    assert build is not None, "E3.1 要求 extract_empty 字段的定向二轮提问模板"
    params = set(inspect.signature(build).parameters)
    banned = {"golden", "gold", "gs", "keypoints"}
    assert not (params & banned), f"触发/组装签名不得含金标输入（E3.1）：{params & banned}"


# ---------------------------------------------------------------------------
# E4 值粒度指引经变体注入（RED）
# ---------------------------------------------------------------------------


def test_e4_1_granularity_guidance_available_via_variant() -> None:
    from insurance_harness.compiler.variants import (  # noqa: PLC0415
        VariantRegistry,
        select_variant,
    )

    registry = VariantRegistry.default()
    variant = select_variant(
        registry, group="cost_rules", field_id="illustrated_rate_basis"
    )
    assert "原文粒度" in (variant.guidance or ""), (
        "值粒度缺口字段应带'按条款原文粒度抽取'指引（E4.1）"
    )


# ---------------------------------------------------------------------------
# E6 弱值与字段-值兼容性护栏（RED：两族模式与兼容性校验尚不存在）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "weak", ["以合同为准", "按合同约定", "需核对条款后确认"], ids=["heti", "yueding", "hedui"]
)
def test_e6_weak_unactionable_value_becomes_unknown(weak: str) -> None:
    result = clean_value(weak)
    assert result.is_placeholder and result.value is None, (
        f"弱值文案 {weak!r} 不得冒充事实值（E6/WEAK_UNACTIONABLE）"
    )


@pytest.mark.parametrize(
    "ref", ["见第5.3条", "详见本合同第三条", "详见附表二"], ids=["jian", "benhetiao", "fubiao"]
)
def test_e6_reference_only_value_becomes_source_pointer(ref: str) -> None:
    result = clean_value(ref)
    assert result.value is None and result.source_pointer, (
        f"引用型文案 {ref!r} 应转 source_pointer 供补漏定向追抽（E6/REFERENCE_ONLY）"
    )


@pytest.mark.parametrize(
    ("field_name", "field_id", "bad_value"),
    [
        ("费用", "zh_fee_main", "退保时可能遭受一定损失，详见退保费用说明章节"),
        ("投保年龄", "zh_entry_age", "1-4类职业"),
        ("保证续保", "zh_guaranteed_renewal", "20年"),
    ],
    ids=["q012-refund-into-fee", "q012-occupation-into-age", "q012-years-into-renewal"],
)
def test_e6_field_value_compatibility_rejects_q012_bugs(
    field_name: str, field_id: str, bad_value: str
) -> None:
    from insurance_harness.compiler.compat import check_field_value  # noqa: PLC0415
    from insurance_harness.schemas import FieldSpec  # noqa: PLC0415

    field = FieldSpec(name=field_name, field_id=field_id, source_sheet="024-recall")
    verdict = check_field_value(field, bad_value)
    assert not verdict.compatible and verdict.reason, (
        f"Q012 历史 bug：{bad_value!r} 不得入 {field_name!r}（E6 兼容性校验）"
    )
