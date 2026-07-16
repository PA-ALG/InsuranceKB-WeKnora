"""024 gauntlet 收口回归：审计完整性与变体归属（E6.3 / E2.2）。

红队（fresh-eyes agent）发现 compat 拒绝原因在 gapfill 路径丢失（F6，违 E6.3
"记录拒绝原因"），且首轮/fastpath/vote/judge pred 无变体标识（F7，违 E2.2
"每次抽取的 pred SHALL 记录所用变体的版本化标识"）。本文件钉死修复后行为。
测试名引用条款号。零模型调用。
"""

from __future__ import annotations

import asyncio

from insurance_harness.compiler.gapfill import gapfill_field
from insurance_harness.compiler.models import FieldCandidate
from insurance_harness.compiler.pipeline import merge_candidates
from insurance_harness.compiler.sections import DocSection
from insurance_harness.compiler.variants import (
    DEFAULT_VARIANT_VERSION,
    VARIANT_METADATA_KEY,
)
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.schemas import FieldSpec

_DOC = "doc.pdf"


class _FakeClient:
    def __init__(self, resp: str) -> None:
        self._resp = resp

    async def complete(self, system: str, user: str) -> str:
        return self._resp


# ---------------------------------------------------------------------------
# F6 · E6.3：gapfill 路径的兼容性拒绝原因可审计（非笼统 not_found）
# ---------------------------------------------------------------------------


def test_e6_3_gapfill_compat_reject_records_auditable_reason() -> None:
    field = FieldSpec(name="费用", field_id="zh_fee", source_sheet="024-recall")
    page = PageText(page_no=1, text="费用说明：退保可能产生损失。")
    section = DocSection(
        section_id="s1", title="费用", headings=(), fragments=(page,)
    )
    resp = (
        '[{"field_id":"zh_fee","value":"退保时可能遭受一定损失","tri_state":"present",'
        '"evidence":[{"page":1,"quote":"退保可能产生损失"}]}]'
    )
    cand = asyncio.run(
        gapfill_field(
            _FakeClient(resp), "测试产品", field,
            [(_DOC, section)], {_DOC: [page]},
        )
    )
    assert cand.tri_state == "unknown"
    assert cand.unknown_reason == "incompatible_value", (
        f"补漏兼容性拒绝须记 incompatible_value（非 not_found），实得 {cand.unknown_reason}"
    )
    assert cand.metadata.get("compat_reject"), "拒绝原因须落 metadata.compat_reject（E6.3 可审计）"
    assert cand.metadata.get(VARIANT_METADATA_KEY), "变体标识仍须 stamp（E2.2）"


# ---------------------------------------------------------------------------
# F7 · E2.2：每个最终 pred（不止 gapfill）都记录所用变体的版本化标识
# ---------------------------------------------------------------------------


def _extract_pred(field_id: str, field_name: str, group: str) -> FieldCandidate:
    """模拟首轮抽取 pred：origin=extract，无变体元数据。"""
    return FieldCandidate(
        field_id=field_id, field_name=field_name, group=group,
        doc=_DOC, tri_state="unknown", unknown_reason="not_found", origin="extract",
    )


def test_e2_2_first_round_pred_gets_default_variant_stamp() -> None:
    """普通字段的首轮 pred 经 merge 后带 default@v1（此前元数据为空）。"""
    pred = _extract_pred("zh_random_field", "某普通字段", "coverage")
    assert pred.metadata.get(VARIANT_METADATA_KEY) is None  # 前提：首轮自身未 stamp
    merged = merge_candidates([pred])
    assert merged["zh_random_field"].metadata[VARIANT_METADATA_KEY] == DEFAULT_VARIANT_VERSION


def test_e2_2_targeted_field_pred_gets_targeted_variant_stamp() -> None:
    """定向工单字段（意外身故 zh_69f97f5c40 @ coverage）的 pred 记 targeted@v1。"""
    pred = _extract_pred("zh_69f97f5c40", "意外身故", "coverage")
    merged = merge_candidates([pred])
    assert merged["zh_69f97f5c40"].metadata[VARIANT_METADATA_KEY] == "targeted@v1", (
        "定向字段的最终 pred 须归属其注册变体（020 D4 A/B 对账）"
    )


def test_e2_2_dead_letter_pred_also_stamped() -> None:
    """dead_letter 等非常规 origin 的 pred 也必须带变体标识（E2.2 无遗漏）。"""
    dead = FieldCandidate(
        field_id="zh_x", field_name="某字段", group="basic_info",
        doc=_DOC, tri_state="unknown", unknown_reason="dead_letter", origin="extract",
    )
    merged = merge_candidates([dead])
    assert merged["zh_x"].metadata.get(VARIANT_METADATA_KEY) == DEFAULT_VARIANT_VERSION
