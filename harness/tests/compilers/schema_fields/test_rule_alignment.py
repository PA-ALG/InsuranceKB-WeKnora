"""S12c-12a RED: one authority across selection, values and review; synthetic inputs only."""

import json
from pathlib import Path

import pytest

from insurance_harness.compilers.schema_fields.cards import all_cards, card_payload, cards_version
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition, pack_definitions
from insurance_harness.compilers.schema_fields.profiles import field_extraction_profile
from insurance_harness.compilers.schema_fields.prompt import (
    VALUE_PROMPT,
    build_selection_request,
    build_value_request,
)
from insurance_harness.ingest.judge_batch.points import field_context, field_digests

BENEFITS = (
    "accidental_death_benefit_rules",
    "additional_benefit_rules",
    "disability_benefit_rules",
    "death_benefit_rules",
    "maturity_benefit_rules",
    "survival_benefit_rules",
    "premium_waiver_rules",
    "income_loss_benefit_eligibility_conditions",
    "income_loss_care_benefit_conditions",
)


def catalog(repo: Path, keys: list[str]) -> Path:
    from insurance_harness.catalog import SCHEMA_PACK_CATALOG

    path = repo / SCHEMA_PACK_CATALOG
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "pack": {
                            "schema_pack_id": "schemapack_synthetic",
                            "fields": [
                                {
                                    "field_key": key,
                                    "short_title": key,
                                    "description": "合成字段",
                                    "formation_method": "原文抽取" if i == 0 else "派生",
                                }
                                for i, key in enumerate(keys)
                            ],
                        }
                    }
                ]
            }
        )
    )
    return path


@pytest.mark.parametrize(
    "keys",
    [
        ["surrender_and_cancellation_terms", "cash_value_rules"],
        ["surrender_and_cancellation_terms", "cooling_off_period"],
    ],
)
def test_full_pack_not_batch_controls_fallback(tmp_path: Path, keys: list[str]) -> None:
    fields = pack_definitions(catalog(tmp_path, keys), "schemapack_synthetic")
    assert len(fields) == 1  # the other field is not in this extraction batch
    select = json.loads(build_selection_request("synthetic", fields, "").user)
    value = json.loads(build_value_request("synthetic", [(fields[0], [])]).user)
    judge = field_context(tmp_path, "schemapack_synthetic", keys[:1])[keys[0]]["card"]
    cards = [select["schema_fields"][0]["card"], value["schema_fields"][0]["card"], judge]
    for card in cards:
        assert card["available_fields"] == keys
        assert "每条事实只归入一个字段" in card["authority"]
        assert "没有专门字段" in card["authority"]
        assert "混合段" in card["authority"]
    assert cards[0]["authority"] == cards[1]["authority"] == cards[2]["authority"]
    assert cards[1] == cards[2]
    before = field_digests(field_context(tmp_path, "schemapack_synthetic", keys[:1]))
    catalog(tmp_path, [keys[0], "policyholder_rights"])
    after = field_digests(field_context(tmp_path, "schemapack_synthetic", keys[:1]))
    assert before != after  # a changed sibling inventory changes the review's question


def test_missing_pack_inventory_is_unknown_not_an_empty_pack() -> None:
    field = FieldDefinition(field_key="sum_assured_range", short_title="保额", description="保额")
    card = card_payload(field)
    assert card and card["available_fields"] is None


def test_source_priority_is_identical_to_actual_value_prompt(tmp_path: Path) -> None:
    field = pack_definitions(catalog(tmp_path, ["sum_assured_range"]), "schemapack_synthetic")[0]
    selection = json.loads(build_selection_request("synthetic", [field], "").user)
    value = json.loads(build_value_request("synthetic", [(field, [])]).user)
    judge = field_context(tmp_path, "schemapack_synthetic", [field.field_key])
    rule = selection["schema_fields"][0]["card"]["source_priority"]
    assert rule in VALUE_PROMPT
    assert "不同数值、起算点、比例或另加的例外，不写进 value" in rule
    assert "条款没有涉及的事项，可以用说明书的内容" in rule
    assert value["schema_fields"][0]["card"]["source_priority"] == rule
    assert judge[field.field_key]["card"]["source_priority"] == rule


def test_numeric_amount_rule_has_no_non_numeric_present_examples() -> None:
    card = all_cards()["sum_assured_range"]
    assert "数值" in card["includes"]
    assert "没有数值" in card["unknown_rule"]
    for example in card["examples"]:
        if "监管" in (example.get("value") or "") or "规定的限额" in (example.get("value") or ""):
            pytest.fail("non-numeric regulatory limit remains a present example")
        if example["state"] == "unknown":
            assert example["value"] is None and example["reason"]


def test_bound_profiles_no_longer_contradict_cards() -> None:
    from insurance_harness.catalog import SCHEMA_PACK_CATALOG

    repo = Path(__file__).resolve().parents[4]
    definitions = pack_definitions(
        repo / SCHEMA_PACK_CATALOG, "schemapack_medical_insurance", only_source_extractable=False
    )
    definitions += pack_definitions(
        repo / SCHEMA_PACK_CATALOG, "schemapack_whole_life_insurance", only_source_extractable=False
    )
    found = {d.field_key: field_extraction_profile(d).instruction for d in definitions}
    assert "保额约定方式" not in found["sum_assured_range"]
    assert "不得因为没有具体上下限数字" not in found["sum_assured_range"]
    assert "费用类别" in found["reimbursable_expense_scope"]
    assert "其他计算限制" not in found["reimbursable_expense_scope"]


def test_new_expense_and_outpatient_cards_keep_scope_separate_from_calculation() -> None:
    cards = all_cards()
    expense = cards["reimbursable_expense_scope"]
    for part in ("费用", "合理", "必要", "社保", "医院", "地域"):
        assert part in expense["includes"]
    excluded = " ".join(content for content, _ in expense["excludes"])
    assert all(part in excluded for part in ("免赔", "比例", "限额"))
    outpatient = cards["outpatient_inpatient_scope"]
    assert "没有专门字段" in outpatient["includes"] and "分项限额" in outpatient["includes"]
    assert any("reimbursable_expense_scope" in target for _, target in outpatient["excludes"])
    assert expense["unknown_rule"] and expense["absent_rule"]


def test_refund_result_and_calculation_have_one_owner() -> None:
    cards = all_cards()
    surrender = cards["surrender_and_cancellation_terms"]
    cash = cards["cash_value_rules"]
    assert "退还什么" in surrender["includes"]
    assert "cash_value_rules" in surrender["includes"] and "没有" in surrender["includes"]
    assert "退保退还现金价值" not in cash["includes"]
    assert any(
        "退还什么" in content and "surrender_and_cancellation_terms" in target
        for content, target in cash["excludes"]
    )


def test_specific_benefit_conditions_are_not_duplicated() -> None:
    cards = all_cards()
    for key in BENEFITS:
        assert "只针对本项责任的不给付条件" in cards[key]["includes"]
        assert "同时选入责任免除" not in cards[key]["includes"]
    assert "同时属于该项责任的给付规则字段" not in cards["exclusions"]["includes"]
    assert "没有专门给付字段" in cards["exclusions"]["includes"]


def test_termination_examples_cannot_teach_expiry_or_exclusion_refunds() -> None:
    card = all_cards()["benefit_interaction_rules"]
    for example in card["examples"]:
        text = example.get("value") or ""
        assert "或本合同保险期间届满时本合同终止" not in text
        assert "无需承担保险责任的，合同终止并退还" not in text
        assert "主险终止引起本合同终止的规则" not in text
    assert "自身等待期" in card["writing_rule"]


def test_generic_payment_date_is_not_a_product_frequency_option() -> None:
    card = all_cards()["premium_payment_frequency"]
    text = json.dumps(card["excludes"], ensure_ascii=False)
    assert "交费频率仍属本字段" not in text
    assert "不证明" in text and "本产品" in text


def test_version_and_unchanged_example_separation() -> None:
    assert cards_version() == "draft-2026-11-12a"
    field = FieldDefinition(
        field_key="death_benefit_rules",
        short_title="身故",
        description="身故",
        pack_id="schemapack_whole_life_insurance",
    )
    first, second = card_payload(field), card_payload(field, examples=False)
    assert first and second
    assert first.get("examples") and "examples" not in second
    assert "good" not in second
