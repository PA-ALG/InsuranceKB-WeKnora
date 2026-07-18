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
# F7 → E7（codex PR#13 阻断2 返工）：merge 不再按注册表 membership 盖标签；
# prompt_variant_used 只在真实使用处记录，其余在 _to_pred 按 origin 如实归因。
# ---------------------------------------------------------------------------


def _extract_pred(field_id: str, field_name: str, group: str) -> FieldCandidate:
    """模拟首轮抽取 pred：origin=extract，无变体元数据。"""
    return FieldCandidate(
        field_id=field_id, field_name=field_name, group=group,
        doc=_DOC, tri_state="unknown", unknown_reason="not_found", origin="extract",
    )


def test_e7_merge_does_not_fabricate_variant_labels() -> None:
    """merge 不得给未走 targeted prompt 的候选盖注册表标签（membership≠实际使用）。"""
    pred = _extract_pred("zh_69f97f5c40", "意外身故", "coverage")  # 注册表内字段
    merged = merge_candidates([pred])
    assert VARIANT_METADATA_KEY not in merged["zh_69f97f5c40"].metadata, (
        "首轮 baseline 抽取的候选不得被盖 targeted 标签——A/B 归因不得被污染"
    )


def test_e7_gapfill_stamp_records_actual_template_and_arm() -> None:
    """gapfill 是唯一真实使用变体模板的路径：stamp 记实际所用 + 实验臂。"""
    field = FieldSpec(name="意外身故", field_id="zh_69f97f5c40", source_sheet="024")
    page = PageText(page_no=1, text="等待期为90天。")
    section = DocSection(section_id="s1", title="责任", headings=(), fragments=(page,))
    resp = '[{"field_id":"zh_69f97f5c40","value":null,"tri_state":"unknown","evidence":[]}]'
    cand = asyncio.run(
        gapfill_field(
            _FakeClient(resp), "测试产品", field,
            [(_DOC, section)], {_DOC: [page]}, arm="control",
        )
    )
    assert cand.metadata[VARIANT_METADATA_KEY] == DEFAULT_VARIANT_VERSION, (
        "control 臂强制默认模板：实际使用=default@v1，即使字段在注册表内"
    )
    assert cand.metadata["variant_assignment"] == "control"
    treat = asyncio.run(
        gapfill_field(
            _FakeClient(resp), "测试产品", field,
            [(_DOC, section)], {_DOC: [page]}, arm="treatment",
        )
    )
    assert treat.metadata[VARIANT_METADATA_KEY] == "targeted@v1", (
        "treatment 臂对注册字段实际使用 targeted 模板"
    )
