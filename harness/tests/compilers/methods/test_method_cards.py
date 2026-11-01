"""SK-2 Spec §2.2, §4.5 (RED, written by Claude): the versioned method cards and product signals."""

import json
from collections.abc import Callable
from importlib.resources import files
from typing import Any

import pytest

from insurance_harness.catalog.method_cards import (
    MethodCardsError,
    load_method_cards,
    parse_method_cards,
)
from insurance_harness.catalog.trust_policy import load_trust_policy
from insurance_harness.compilers.methods.product_info import product_signals
from tests.ingest.method_helpers import ZYBH

CARDS = ("method_summary", "method_steps", "key_phrases", "applicable_scenario", "cautions")


def shipped() -> dict[str, Any]:
    text = files("insurance_harness.catalog").joinpath("method_cards.json").read_text("utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


def test_the_cards_are_exactly_the_sales_method_fields_in_order() -> None:
    cards = load_method_cards()
    assert tuple(card.predicate for card in cards.cards) == CARDS
    assert set(CARDS) == load_trust_policy().restricted_fields("sales_method")
    assert [card.value_type for card in cards.cards] == ["text", "list", "list", "text", "list"]
    assert [card.verbatim for card in cards.cards] == [False, False, True, False, False]
    assert (cards.entity_type, cards.owner_module, cards.review_pack) == (
        "sales_method",
        "harness/sales_methods",
        "methods_sales",
    )
    assert {pattern.signal for pattern in cards.product_info_patterns} == {
        "amount",
        "percentage",
        "age",
    }


def _drop(data: dict[str, Any]) -> None:
    data["cards"].pop()


def _repeat(data: dict[str, Any]) -> None:
    data["cards"][1] = data["cards"][0]


def _foreign(data: dict[str, Any]) -> None:
    data["cards"][0]["predicate"] = "premium"


def _bad_pattern(data: dict[str, Any]) -> None:
    data["product_info_patterns"][0]["pattern"] = "("


def _bad_type(data: dict[str, Any]) -> None:
    data["cards"][0]["value_type"] = "table"


def _extra(data: dict[str, Any]) -> None:
    data["owner"] = "x"


def _blank_version(data: dict[str, Any]) -> None:
    data["version"] = " "


@pytest.mark.parametrize(
    "change", [_drop, _repeat, _foreign, _bad_pattern, _bad_type, _extra, _blank_version]
)
def test_inconsistent_cards_are_refused(change: Callable[[dict[str, Any]], None]) -> None:
    data = shipped()
    change(data)
    with pytest.raises(MethodCardsError) as raised:
        parse_method_cards(json.dumps(data, ensure_ascii=False))
    assert raised.value.code == "METHOD_CARDS_INVALID"


@pytest.mark.parametrize(
    ("text", "signals"),
    [
        ("保额50万元起步", {"amount"}),
        ("保额５０万起步", {"amount"}),
        ("年缴￥3000", {"amount"}),
        ("保费只占收入10%", {"percentage"}),
        ("保费只占收入１０％", {"percentage"}),
        ("百分之五的预算", {"percentage"}),
        ("适合30至45周岁客户", {"age"}),
        ("60岁以后", {"age"}),
        ("讲解" + ZYBH + "的责任", {"product"}),
        ("第一步先了解家庭结构", set()),
        ("讲解步骤二：分析缺口", set()),
        ("智盈话术", set()),  # a registered name shorter than four characters tells nothing
    ],
)
def test_product_signals_are_found_in_folded_text(text: str, signals: set[str]) -> None:
    assert product_signals(text, load_method_cards(), [ZYBH, "智盈"]) == frozenset(signals)
