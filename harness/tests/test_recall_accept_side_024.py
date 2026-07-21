"""024 gauntlet 误杀防线（E6 accept 侧）：兼容性/清洗规则绝不得把**正确的金标值**
判为不兼容或清成 placeholder——否则"召回提升"变净召回回归。

源起：fresh-eyes 红队用真金标复现 compat 误杀 保证续保期="20年"、费用含"退保"
（gauntlet F1/F2），而当时全套仅有拒绝侧断言、无一条 accept 侧（"误杀防线"缺失）。
本文件补齐：既钉死已复现的真金标个案，又扫描整个 goldenset 防未来回归。

测试名引用条款号（E6）。零模型调用。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from insurance_harness.compiler.cleaning import clean_value
from insurance_harness.compiler.compat import check_field_value
from insurance_harness.schemas import FieldSpec

_GOLDENSET = (
    Path(__file__).resolve().parents[2] / "dataset" / "goldenset" / "wip-gs-v0.1"
)


def _field(name: str) -> FieldSpec:
    # check_field_value 只读 .name；model_construct 绕过与本测试无关的必填项。
    return FieldSpec.model_construct(name=name)


# ---------------------------------------------------------------------------
# E6 accept 侧：真金标个案（红队已用 goldenset 复现的 F1/F2/F3 误杀点）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field_name", "good_value"),
    [
        # F1：保证续保「期」是时长字段，"20年"正是其正确答案（区别于是/否的保证续保）
        ("保证续保期", "20年"),
        # F2：合法费用值把"退保"作为扣费因素叙述，非退保损失文案
        (
            "费用",
            "从所交保险费中扣除相关费用（对应公司经营支出、保险责任成本及提前"
            "退保影响），未披露具体费用比例",
        ),
        # F3：带年龄单位的投保年龄值含职业限定是合法的（E4 要求保留限定条件）
        ("投保年龄", "18周岁至60周岁（1-4类职业）"),
        ("投保年龄", "出生满28日至60周岁，且职业符合本公司投保规则"),
    ],
    ids=["f1-renewal-term-20y", "f2-fee-mentions-refund", "f3-age-with-occ", "f3-age-birth"],
)
def test_e6_compat_accepts_legit_values_not_kill_gold(
    field_name: str, good_value: str
) -> None:
    verdict = check_field_value(_field(field_name), good_value)
    assert verdict.compatible, (
        f"E6 误杀：正确值 {good_value!r} 被判不兼容于 {field_name!r}"
        f"（reason={verdict.reason!r}）——召回回归"
    )


def _iter_present_gold() -> list[tuple[str, str, str]]:
    """(product, field_name, value) —— 仅 tri_state=present 的事实值。"""
    out: list[tuple[str, str, str]] = []
    if not _GOLDENSET.exists():
        return out
    for gf in sorted(_GOLDENSET.glob("*/golden.jsonl")):
        product = gf.parent.name
        for line in gf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("tri_state") != "present":
                continue
            fn = rec.get("field_name")
            val = rec.get("value")
            if fn and isinstance(val, str) and val.strip():
                out.append((product, fn, val))
    return out


def test_e6_compat_no_gold_present_value_is_rejected() -> None:
    """整集扫描：goldenset 中每个 present 金标值都必须 compatible=True。"""
    gold = _iter_present_gold()
    if not gold:
        pytest.skip("goldenset 不可见（本地样本未解压）")
    killed = [
        (p, fn, v, check_field_value(_field(fn), v).reason)
        for p, fn, v in gold
        if not check_field_value(_field(fn), v).compatible
    ]
    assert not killed, (
        f"E6 兼容性误杀 {len(killed)}/{len(gold)} 个真金标 present 值（召回回归）："
        + "; ".join(f"{fn}={v[:24]!r}@{p}({r})" for p, fn, v, r in killed[:5])
    )


def test_e6_cleaning_no_gold_present_value_becomes_placeholder() -> None:
    """整集扫描：清洗不得把任何 present 金标事实值吞成 placeholder。"""
    gold = _iter_present_gold()
    if not gold:
        pytest.skip("goldenset 不可见（本地样本未解压）")
    swallowed = [
        (p, fn, v) for p, fn, v in gold if clean_value(v).is_placeholder
    ]
    assert not swallowed, (
        f"清洗误吞 {len(swallowed)}/{len(gold)} 个真金标 present 值成 placeholder："
        + "; ".join(f"{fn}={v[:24]!r}@{p}" for p, fn, v in swallowed[:5])
    )
