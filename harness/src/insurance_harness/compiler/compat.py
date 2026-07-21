"""E6 字段-值语义兼容性校验（024，LLM-wiki-black A10 承接）。

同名/近名字段辨析：值与目标字段语义不兼容 → 拒入 pred（转 unknown，
原因可审计）。规则为确定性纯数据（Q012/Q026 历史 bug 固化）：
- "退保损失"叙述回填"费用"类字段（旧 bug：费用 ← 退保费用文案）；
- "投保年龄"混入职业类别；
- "保证续保"填成裸年限（年限≠续保承诺表述）。

误杀防线：规则要求"字段名命中 ∧ 值形态命中"双条件；带排除词
（如字段名本身含"退保"时不触发退保规则）。
"""

from __future__ import annotations

import re
from typing import Final

from pydantic import BaseModel, ConfigDict

from insurance_harness.schemas import FieldSpec


class CompatVerdict(BaseModel):
    """兼容性判定：不兼容值不得入 pred（E6），拒绝原因可审计。"""

    model_config = ConfigDict(frozen=True)

    compatible: bool
    reason: str | None = None


class _Rule(BaseModel):
    model_config = ConfigDict(frozen=True)

    field_has: str  # 字段名须包含
    field_not: str = ""  # 字段名含此词则跳过（防误杀）
    value_re: str  # 值命中形态（regex，search 语义）
    value_not: str = ""  # 值含此形态则跳过（值级防误杀：合法值特征，如年龄单位）
    reason: str


_RULES: Final[tuple[_Rule, ...]] = (
    # 退保损失/退保说明文案回填费用类字段。仅命中"退保损失"文案特征（退保引领
    # 或 退保…损失 同句）；合法费用值虽含"退保"作为扣费因素（如"…提前退保影响…"）
    # 不落此规则——bare r"退保" 会误杀真金标（gauntlet F2）。
    _Rule(
        field_has="费用",
        field_not="退保",
        value_re=r"^\s*退保|退保[^，。；]{0,10}损失",
        reason="退保损失/退保说明文案回填费用类字段（Q012 历史 bug）",
    ),
    # 职业类别混入投保年龄字段。含年龄单位（周岁/岁/足月/出生）的值是合法年龄
    # 限定（E4 GRANULARITY_GUIDANCE 要求保留），value_not 放行——否则误杀
    # "18周岁至60周岁（1-4类职业）"（gauntlet F3）。
    _Rule(
        field_has="年龄",
        value_re=r"职业|[1-9一二三四五六]\s*[-–至~]?\s*[1-9一二三四五六]?\s*类",
        value_not=r"周岁|岁|足\s*\d*\s*月|出生",
        reason="职业类别混入投保年龄字段（Q012 历史 bug）",
    ),
    # 裸年限/年龄不构成"保证续保"（是/否承诺）字段的表述。field_not 排除
    # "保证续保期"——那是时长字段，"20年"正是其正确金标值（gauntlet F1）。
    _Rule(
        field_has="保证续保",
        field_not="保证续保期",
        value_re=r"^\s*\d+\s*(?:年|周岁)\s*$",
        reason="裸年限/年龄不构成保证续保承诺表述（Q012 历史 bug）",
    ),
)


def check_field_value(field: FieldSpec, value: str) -> CompatVerdict:
    """字段-值语义兼容性（E6）：确定性规则，双条件命中才判不兼容。"""
    text = value.strip()
    if not text:
        return CompatVerdict(compatible=True)
    for rule in _RULES:
        if rule.field_has not in field.name:
            continue
        if rule.field_not and rule.field_not in field.name:
            continue
        if rule.value_not and re.search(rule.value_not, text):
            continue  # 值级防误杀：合法值特征命中 → 不判不兼容
        if re.search(rule.value_re, text):
            return CompatVerdict(compatible=False, reason=rule.reason)
    return CompatVerdict(compatible=True)
