"""S12c-13a: check the instructions actually shown for synthetic, differently shaped packs."""

import json
from pathlib import Path

import pytest

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.compilers.schema_fields.cards import all_cards, cards_version
from insurance_harness.compilers.schema_fields.definitions import pack_definitions
from insurance_harness.compilers.schema_fields.engine import CompileOutput, reusable
from insurance_harness.compilers.schema_fields.prompt import (
    VALUE_PROTOCOL_VERSION,
    build_selection_request,
    build_value_request,
)
from insurance_harness.ingest.judge_batch.points import field_context


@pytest.mark.parametrize("has_sibling", [True, False])
def test_compiler_and_judge_share_inventory_and_gap_policy(tmp_path: Path, has_sibling: bool) -> None:
    keys = ["coverage_and_renewal_terms", "claim_application_deadline_and_documents"]
    if has_sibling:
        keys += ["guaranteed_renewal_status", "beneficiary_rules"]
    path = tmp_path / SCHEMA_PACK_CATALOG
    path.parent.mkdir(parents=True)
    fields = [
        dict(field_key=k, short_title=k, description="合成合同字段", formation_method="原文抽取")
        for k in keys
    ]
    pack = "synthetic_renewable" if has_sibling else "synthetic_claims"
    path.write_text(json.dumps({"entries": [{"pack": {"schema_pack_id": pack, "fields": fields}}]}))
    defs = pack_definitions(path, pack)
    text = "不保证续保。期满可重新申请，经审核后另订一年合同。遗产申请须交继承权文件。"
    selection = json.loads(build_selection_request("synthetic", defs[:1], text).user)
    values = json.loads(build_value_request("synthetic", [(defs[0], [])]).user)
    judge = field_context(tmp_path, pack, keys[:1])[keys[0]]["card"]
    first = selection["schema_fields"][0]["card"]
    second = values["schema_fields"][0]["card"]
    assert second == judge
    assert first["available_fields"] == second["available_fields"] == keys
    assert first["authority"] == second["authority"]
    for term in ("定义", "覆盖", "目录缺口", "继承权文件", "汇总", "缩小保障范围"):
        assert term in judge["authority"]
    assert "不保证续保" in first["includes"] and "重新申请" in second["includes"]
    assert "没有重新申请安排" in judge["absent_rule"]
    assert "不保证续保" not in judge["absent_rule"]
    assert all(key in judge["includes"] for key in (
        "期限", "审核", "guaranteed_renewal_status", "post_discontinuation_renewal_arrangement",
    ))


def test_overviews_share_only_their_minimum_facts() -> None:
    cards = all_cards()
    responsibilities = cards["coverage_responsibilities"]["includes"]
    summary = cards["coverage_summary"]["includes"]
    assert all(word in responsibilities for word in ("名称", "触发", "给付基准", "关键时限"))
    assert all(word in summary for word in ("名称", "一句", "核心给付", "关系"))
    for key in ("coverage_responsibilities", "coverage_summary"):
        boundary = cards[key]["writing_rule"]
        assert all(word in boundary for word in ("等待期", "免赔", "分场景比例", "申请时效", "免责"))
        assert "专门字段" in boundary
        for example in cards[key]["examples"]:
            assert "年龄比例：" not in example["value"]
            assert "宣告死亡：" not in example["value"]
            assert "LLM概括不全" not in "".join(example["pitfalls"])


def test_occupation_needs_explicit_eligibility_not_pricing() -> None:
    card = all_cards()["eligible_occupation_classes"]
    assert all(source in card["unknown_rule"] for source in ("条款", "说明书", "投保规则", "费率表"))
    assert "unknown" in card["unknown_rule"]
    assert "费率表" in card["bad"] and "不限职业" in card["absent_rule"]


def test_disease_qualifications_follow_the_clause_location() -> None:
    c = all_cards()
    definition = c["disease_definitions_and_criteria"]["includes"]
    listing = c["covered_critical_specified_diseases"]["includes"]
    exclusions = c["exclusions"]["includes"]
    assert all(w in definition for w in ("释义", "年龄限制", "总免责", "不适用"))
    assert all(w in listing for w in ("名单本身", "必须", "缩小保障范围", "不算遗漏"))
    assert all(w in exclusions for w in ("总免责条文本身", "必须", "一般阅读提示", "疾病释义"))
    for example in c["covered_critical_specified_diseases"]["examples"]:
        for warning in example.get("pitfalls", []):
            if "年龄限制" in warning and "漏选" in warning:
                assert "名单本身" in warning


def test_payment_count_and_termination_are_distinct() -> None:
    card = all_cards().get("multiple_benefit_payment_rules")
    assert card is not None
    assert "仅给付一次" in card["absent_rule"] and "引用" in card["absent_rule"]
    assert "未提" in card["unknown_rule"] and "unknown" in card["unknown_rule"]
    assert any("给付后终止" in text and "benefit_interaction_rules" in target
               for text, target in card["excludes"])
    assert "多次" in card["includes"]


def test_old_material_match_cannot_reuse_a_pre_ruling_output() -> None:
    material = ["file:" + "a" * 64]
    old = CompileOutput(entity_id="synthetic", pack_id="schemapack_medical_insurance",
                        model="offline", cards_version="draft-2026-11-05a",
                        value_protocol=VALUE_PROTOCOL_VERSION, materials=material)
    assert not reusable(old, material)
    assert reusable(old.model_copy(update={"cards_version": cards_version()}), material)
