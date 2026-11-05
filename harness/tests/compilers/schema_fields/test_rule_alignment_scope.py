"""Negative controls for the independent S12c-12a protected-test adaptation."""

import copy

import pytest

from insurance_harness.compilers.schema_fields.cards import all_cards
from tests.compilers.schema_fields.rule_alignment_scope import UNITS, digest, neutralize
from tests.compilers.schema_fields.test_field_cards_rate_tables import UNTOUCHED_DIGEST, untouched


def test_each_approved_unit_is_exact_not_a_whole_attribute_escape_hatch() -> None:
    for key, path, _, after in UNITS:
        data = copy.deepcopy(all_cards())
        if path is None:
            assert digest(data[key]) == after
            data[key]["unapproved"] = "change"
        else:
            parts = path.split("/")
            parent = data[key]
            for part in parts[:-1]:
                parent = parent[int(part)] if isinstance(parent, list) else parent[part]
            assert digest(parent[parts[-1]]) == after
            parent[parts[-1]] = "unauthorised change"
        baseline = copy.deepcopy(all_cards())
        neutralize(data)
        neutralize(baseline)
        assert data != baseline, (key, path)


@pytest.mark.parametrize(
    "where", ["definition", "example_identity", "unmodified_example", "other_card"]
)
def test_unapproved_content_still_breaks_the_historical_digest(where: str) -> None:
    data = copy.deepcopy(all_cards())
    if where == "definition":
        data["premium_payment_term"]["definition"] += "changed"
    elif where == "example_identity":
        data["sum_assured_range"]["examples"][0]["product"] += "changed"
    elif where == "unmodified_example":
        data["sum_assured_range"]["examples"][3]["reason"] += "changed"
    else:
        data["product_bundle_rules"]["writing_rule"] = "changed"
    assert untouched(data) != UNTOUCHED_DIGEST
