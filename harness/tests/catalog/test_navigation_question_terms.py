"""QA3 acceptance (protected, written by Claude): the navigation carries per-field question terms.

Spec docs/design/slices/QA3-字段按问法匹配.md §2–§3. A field's term groups match a question when
every term of one group occurs in it; the vocabulary is versioned Harness data, the platform only
matches strings. RED until QA3.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from insurance_harness.catalog.navigation import NavigationError, load_navigation, parse_navigation
from insurance_harness.contracts import NavigationProfile

REPO = Path(__file__).resolve().parents[3]

BASE: dict[str, Any] = {
    "navigation_id": "enterprise",
    "navigation_version": "v-test",
    "domains": [
        {
            "domain_key": "product",
            "display_name": "产品",
            "entity_types": ["insurance_product"],
            "groups": [
                {
                    "group_key": "medical",
                    "display_name": "医疗险",
                    "classification_labels": ["medical_insurance"],
                }
            ],
        }
    ],
}


def _normal(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).lower()
    return "".join(ch for ch in folded if not unicodedata.category(ch).startswith(("P", "S", "Z")))


def test_the_contract_accepts_question_terms_and_old_navigations_stay_valid() -> None:
    terms = {"waiting_period": [["观察期"], ["多久", "生效"]]}
    profile = NavigationProfile.model_validate({**BASE, "question_terms": terms})
    assert profile.question_terms == terms
    assert NavigationProfile.model_validate(BASE).question_terms is None


@pytest.mark.parametrize(
    "terms",
    [
        {"waiting_period": [[]]},
        {"waiting_period": [["一二", "三四", "五六", "七八"]]},
        {"waiting_period": [["期"]]},
        {"waiting_period": [["  "]]},
        {"waiting_period": [["（期）"]]},
        {"waiting_period": [["观察期"], ["观察期"]]},
        {" ": [["观察期"]]},
    ],
    ids=[
        "empty group",
        "four terms",
        "one char",
        "blank",
        "one char after punctuation",
        "duplicate",
        "blank key",
    ],
)
def test_malformed_question_terms_are_refused(terms: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        NavigationProfile.model_validate({**BASE, "question_terms": terms})


def test_the_loader_refuses_terms_for_a_field_the_catalog_does_not_have() -> None:
    shipped = json.loads(
        (REPO / "harness/src/insurance_harness/catalog/navigation.json").read_text()
    )
    shipped["question_terms"] = {"no_such_field_key": [["观察期"]]}
    with pytest.raises(NavigationError):
        parse_navigation(json.dumps(shipped, ensure_ascii=False))


def test_the_shipped_navigation_carries_a_versioned_vocabulary() -> None:
    navigation = load_navigation()
    assert navigation.navigation_version == "2026-10-28.1"
    terms = navigation.question_terms or {}
    assert len(terms) >= 40, "at least the commonly asked fields of the Spec's draft"
    # q05: the question names neither 产品利率 nor 保额增长规则; one group of the rate must match.
    question = _normal("盛世金越（尊享版26）终身寿险的保额每年按多少增长？")
    groups = terms.get("sum_assured_growth_rate", [])
    assert any(all(_normal(term) in question for term in group) for group in groups)
    # Every shipped term is long enough to match (the platform ignores shorter ones).
    for groups_of_field in terms.values():
        for group in groups_of_field:
            assert all(len(_normal(term)) >= 2 for term in group)


def test_the_exported_contract_declares_question_terms() -> None:
    schema = json.loads((REPO / "contracts/navigation_profile.schema.json").read_text())
    assert "question_terms" in schema["properties"]
    assert "question_terms" not in schema.get("required", [])
