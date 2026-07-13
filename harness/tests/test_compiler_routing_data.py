"""spec E2.3 / E3.3：路由数据与清洗正则为独立数据模块（06 资产 A5/A6/A8 数据翻译）。"""

from pathlib import Path

from insurance_harness.compiler.cleaning import (
    PLACEHOLDER_PATTERNS,
    SOURCE_ONLY_PATTERNS,
    clean_value,
)
from insurance_harness.compiler.routing_data import (
    FIELD_EVIDENCE_KEYWORDS,
    FIELD_NAME_TO_GROUP,
    GROUP_KEYWORDS,
    GROUP_ORDER,
    group_of_field,
)
from insurance_harness.schemas import load_schema_registry

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs/insurance-kb/schema-baseline"


def test_e2_3_seven_groups_in_order() -> None:
    assert GROUP_ORDER == (
        "basic_info", "coverage", "cost_rules", "exclusion_uw",
        "claim_service", "contract_admin", "disease_definition",
    )
    assert set(GROUP_KEYWORDS) == set(GROUP_ORDER)
    # coverage 扫描全部章节（源资产语义：keyword 为 null）
    assert GROUP_KEYWORDS["coverage"] is None
    assert all(GROUP_KEYWORDS[g] is not None for g in GROUP_ORDER if g != "coverage")


def test_e2_3_group_keywords_match_source_asset() -> None:
    """关键词正则与 06 §3.3 照抄源码的清单一致（抽查锚点词）。"""
    assert GROUP_KEYWORDS["basic_info"] is not None
    for kw in ("犹豫期", "宽限期", "豁免", "合同解除"):
        assert GROUP_KEYWORDS["basic_info"].search(kw)
    assert GROUP_KEYWORDS["exclusion_uw"] is not None
    assert GROUP_KEYWORDS["exclusion_uw"].search("免责")
    assert GROUP_KEYWORDS["disease_definition"] is not None
    assert GROUP_KEYWORDS["disease_definition"].search("恶性")


def test_e2_3_every_extractable_field_bridged_to_group() -> None:
    """字段→组桥接覆盖 schema v1.1 全部可抽取字段（未登记会回落 coverage，
    但基线字段必须显式登记，防止路由语义漂移）。"""
    registry = load_schema_registry(SCHEMA_DIR)
    missing = {
        f.name
        for line in registry.lines.values()
        for f in line.extractable_fields
        if f.name not in FIELD_NAME_TO_GROUP
    }
    assert not missing, f"未登记字段→组桥接：{sorted(missing)}"
    # 桥接目标必须是合法组
    assert set(FIELD_NAME_TO_GROUP.values()) <= set(GROUP_ORDER)


def test_group_of_field_fallback_is_coverage() -> None:
    assert group_of_field("犹豫期") == "basic_info"
    assert group_of_field("从未见过的新字段") == "coverage"  # 宁多勿漏


def test_e3_3_placeholder_patterns_data_driven_30_plus() -> None:
    """清洗正则集数据化且 ≥30 模式（06 A6：30+ 正则）。"""
    assert len(PLACEHOLDER_PATTERNS) + len(SOURCE_ONLY_PATTERNS) >= 30


def test_e3_3_placeholder_hits_become_none_not_empty_string() -> None:
    """占位值 → unknown（None），不是空字符串（master plan P0-3 三态硬要求）。"""
    for raw in ("未明确", "未提及说明内容", "N/A", "无", "暂无相关信息", "证据不足"):
        result = clean_value(raw)
        assert result.is_placeholder, raw
        assert result.value is None, raw


def test_e3_3_source_only_records_pointer_for_gapfill() -> None:
    result = clean_value("详见费率表")
    assert result.is_placeholder and result.value is None
    assert result.source_pointer == "详见费率表"  # 供补漏 pass 消解（04 Step 4）


def test_e3_3_normal_values_pass_through() -> None:
    for raw in ("20日", "无免赔额，100%报销", "终身", "0-65周岁"):
        result = clean_value(raw)
        assert not result.is_placeholder
        assert result.value == raw
    # "无" 是行首锚定全匹配：作为前缀的正常值不得误伤
    assert not clean_value("无免赔额").is_placeholder


def test_evidence_keywords_include_waiver_seeds() -> None:
    """豁免类字段的补漏同义词种子必须存在（04 Step 6 的正解字段）。"""
    assert "豁免" in FIELD_EVIDENCE_KEYWORDS["投被保人豁免"]
    assert "免交保险费" in FIELD_EVIDENCE_KEYWORDS["投被保人豁免"]
