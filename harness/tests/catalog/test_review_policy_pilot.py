"""RV3 pilot revoked: the shipped policy admits no pack (S12 admission evaluation 2026-10-28).

Protected file: written by Claude. History: user decision 2026-10-18 piloted the critical-illness
pack at 0.9. The S12 admission evaluation (docs/design/S12-准入评估-20261028.md, PR #405) found the
independent review score does not predict correctness (the GPT-6 judge approved 0.68 of fields
scored >= 0.9; the critical-illness S12 product's content fields were 0.53 correct), so no pack
meets admission. Until a pack passes the criteria in that document, every product goes through the
model judge before a machine-route publication (user delegation 2026-10-27).
"""

from __future__ import annotations

from insurance_harness.catalog.review_policy import load_review_policy

PACKS = (
    "schemapack_critical_illness_insurance",
    "schemapack_accident_insurance",
    "schemapack_disability_income_insurance",
    "schemapack_endowment_insurance",
    "schemapack_whole_life_insurance",
)


def test_the_shipped_policy_admits_no_pack() -> None:
    policy = load_review_policy()
    assert policy.version == "3"
    assert policy.policy_ref == "review-policy@3"
    assert policy.admitted_packs == []
    for pack in PACKS:
        assert not policy.admitted(pack)
        assert policy.threshold(pack, "waiting_period") is None
