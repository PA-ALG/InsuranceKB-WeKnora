"""SK-3 acceptance: the shipped navigation's sales-method domain and method intent (Spec
docs/design/slices/SK-3-销售方法阅读与问答.md §2.3).

Protected file: written by Claude. The method domain repeats the product domain's insurance groups
(same names, labels and order), then 通用 (scope:general), then the plan type, life stage and sales
stage groups of the sales taxonomy, named by each label's first word. The method intent is data in
question_intents, with terms of its own.
"""

from __future__ import annotations

import json
from pathlib import Path

from insurance_harness.catalog.navigation import load_navigation

TAXONOMY = Path(__file__).resolve().parents[2] / "src/insurance_harness/catalog/sales_taxonomy.json"


def test_the_method_domain_reuses_the_insurance_groups_then_the_taxonomy() -> None:
    navigation = load_navigation()
    domains = {domain.domain_key: domain for domain in navigation.domains}
    product, method = domains["product"], domains["sales_method"]
    assert (method.display_name, method.entity_types) == ("销售方法", ["sales_method"])
    insurance = [(g.display_name, g.classification_labels) for g in product.groups]
    groups = [(g.display_name, g.classification_labels) for g in method.groups]
    assert groups[: len(insurance)] == insurance
    taxonomy = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    general = taxonomy["general"]
    rest = [
        (entry["words"][0], [entry["label"]])
        for key in ("plan_types", "life_stages", "sales_stages")
        for entry in taxonomy[key]
    ]
    assert groups[len(insurance) :] == [("通用", [general["label"]]), *rest]
    assert len({g.group_key for g in method.groups}) == len(method.groups)


def test_the_method_intent_is_navigation_data_with_terms_of_its_own() -> None:
    navigation = load_navigation()
    intents = navigation.question_intents or {}
    assert intents.get("method")
    method = {term for group in intents["method"] for term in group}
    others = {term for key in ("sales", "service") for group in intents[key] for term in group}
    assert {"怎么讲", "话术", "异议"} <= method
    assert not method & others
