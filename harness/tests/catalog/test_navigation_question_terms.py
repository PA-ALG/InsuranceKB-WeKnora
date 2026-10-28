"""QA3 acceptance (protected, written by Claude): the navigation carries per-field question terms.

Spec docs/design/slices/QA3-字段按问法匹配.md §2–§3. A field's term groups match a question when
every term of one group occurs in it; the vocabulary is versioned Harness data, the platform only
matches strings. RED until QA3.

2026-10-28 (#414 review R2/R3, Owner rulings, Spec §2 amended): terms are normalized exactly as the
platform's Go normalizeQuestionTerm does before the length and duplicate checks, and duplicate
groups are compared as sets of terms.
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


# Go unicode.IsSpace (Unicode White_Space) plus the BOM the platform's normalize also drops.
PLATFORM_SPACE = frozenset(
    "\t\n\v\f\r \x85\xa0\u1680" + "".join(map(chr, range(0x2000, 0x200B))) + "\u2028\u2029"
    "\u202f\u205f\u3000\ufeff"
)


def _normal(text: str) -> str:
    """The platform's normalizeQuestionTerm: NFKC, lower case, no whitespace, no punctuation."""
    folded = unicodedata.normalize("NFKC", text).lower()
    return "".join(
        ch
        for ch in folded
        if ch not in PLATFORM_SPACE and not unicodedata.category(ch).startswith("P")
    )


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


def _validate(terms: dict[str, Any]) -> NavigationProfile:
    return NavigationProfile.model_validate({**BASE, "question_terms": terms})


@pytest.mark.parametrize(
    "space",
    ["\t", "\n", "\r", "\x85", "\xa0", "\u3000", "\ufeff", " "],
    ids=["TAB", "LF", "CR", "NEL", "NBSP", "ideographic space", "BOM", "space"],
)
def test_platform_whitespace_is_dropped_before_length_and_duplicates(space: str) -> None:
    # The platform drops it, so 期 plus it is one character: refused.
    with pytest.raises(ValidationError):
        _validate({"waiting_period": [["期" + space]]})
    # Inside a term it is dropped, not refused: still two characters.
    assert _validate({"waiting_period": [["观" + space + "察"]]}).question_terms
    # And it does not make a group different from the same group without it.
    with pytest.raises(ValidationError):
        _validate({"waiting_period": [["观察期"], ["观" + space + "察期"]]})


def test_only_platform_whitespace_and_punctuation_are_dropped() -> None:
    # Symbols stay (Go keeps them), so 期+ is two characters; % is punctuation and goes.
    assert _validate({"waiting_period": [["期+"]]}).question_terms
    with pytest.raises(ValidationError):
        _validate({"waiting_period": [["期%"]]})
    # U+001C is whitespace to Python's str.isspace but not to Go's unicode.IsSpace.
    assert _normal("期\x1c") == "期\x1c"
    assert _validate({"waiting_period": [["期\x1c"]]}).question_terms


@pytest.mark.parametrize(
    "groups",
    [
        [["保额", "增长"], ["增长", "保额"]],
        [["观察期", "观察期"]],
        [["观察期", "观察 期"]],
        [["观察期"], ["观察期", "观察期"]],
    ],
    ids=["reordered group", "repeated term", "repeated after normalization", "repeat of a group"],
)
def test_groups_are_compared_as_sets_of_terms(groups: list[list[str]]) -> None:
    with pytest.raises(ValidationError):
        _validate({"sum_assured_growth_rate": groups})


def test_genuinely_different_groups_stay_together() -> None:
    groups = [["保额", "增长"], ["保额", "增长比例"], ["增长比例"], ["增长", "比例", "保额"]]
    assert _validate({"sum_assured_growth_rate": groups}).question_terms == {
        "sum_assured_growth_rate": groups
    }


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
