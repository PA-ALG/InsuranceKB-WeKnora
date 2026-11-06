"""Older writing-rule masks must not hide a third, unapproved S12c-13a edit."""

import json
from importlib.resources import files

from tests.compilers.schema_fields.rule_alignment_scope import digest
from tests.compilers.schema_fields.test_field_cards_mask_controls import S4I, digest_after


def test_approved_overview_units_are_exact() -> None:
    assert (
        digest_after(lambda c: c["coverage_summary"].update(writing_rule="other"))
        != S4I.UNTOUCHED_DIGEST
    )
    assert (
        digest_after(lambda c: c["coverage_summary"]["examples"][0].update(state="unknown"))
        != S4I.UNTOUCHED_DIGEST
    )


def test_root_rules_only_change_as_adjudicated() -> None:
    resource = files("insurance_harness.compilers.schema_fields").joinpath("field_cards.json")
    rules = json.loads(resource.read_text(encoding="utf-8"))["rules"]
    assert (
        digest(rules) == "553aa06461dadc0369665f365c882f9118fab0f76b57a8250091c73a8ca0f9bc"
    )
