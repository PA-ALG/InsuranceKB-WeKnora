"""Value rules are driven by value_spec, with no field-specific dispatch."""

import pytest

from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.values import normalize_field_value, parse_value_spec


@pytest.mark.parametrize(
    ("spec", "raw", "expected"),
    [
        (None, "  完整原文；限制不变。", "  完整原文；限制不变。"),
        ("是、否", "不支持", "否"),
        ("是、否", "可以", "是"),
        ("是、否", "仅经审批可以，不允许其他情况", "仅经审批可以，不允许其他情况"),
        ("保证续保、否", "不保证", "否"),
        ("保证续保、否", "不保证续保", "不保证续保"),
        ("趸缴、年缴、月缴", "年交", "年缴"),
        ("趸缴、年缴、月缴（多选）", "月交，年交、月缴", "年缴、月缴"),
        ("甲、乙等（多选）", "乙、丙", "乙、丙"),
        ("甲、乙（多选）", "甲、未分类的详细条款", "甲、未分类的详细条款"),
        ("儿童（0-17岁）、成人（18-59岁）（多选）", "成人（18-59岁）", "成人（18-59岁）"),
        ("时长", "９０ 天", "90日"),
        ("时长", "一年", "1年"),
        ("时长", "三十日", "30日"),
        ("时长", "十二个月", "12个月"),
        ("时长", "1年", "1年"),
        ("时长", "30日，例外情况下无等待期", "30日，例外情况下无等待期"),
        ("金额", "人民币１.５万元", "15000元"),
        ("金额", "1,200元", "1200元"),
        ("金额", "-0.10元", "-0.1元"),
        ("金额", "100万日元", "100万日元"),
        ("金额", "1、200元", "1、200元"),
        ("金额", "限额100元，每日不超过20元", "限额100元，每日不超过20元"),
        ("金额", "123456789012345678901234567890万元", "1234567890123456789012345678900000元"),
    ],
)
def test_spec_normalization_preserves_unsupported_or_conditional_prose(
    spec: str | None,
    raw: str,
    expected: str,
) -> None:
    field = FieldDefinition(
        field_key="arbitrary", short_title="字段", description="定义", value_spec=spec
    )
    assert normalize_field_value(field, raw) == expected
    assert normalize_field_value(field, None) is None


def test_catalog_option_qualifiers_are_not_options() -> None:
    constraint = parse_value_spec("可选值“甲、乙、其他”（可多选、可为空）")
    assert constraint.allowed_values == ("甲", "乙", "其他")
    assert constraint.multi_select and constraint.nullable and constraint.allow_other
