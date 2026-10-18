"""RV3 acceptance: the pilot admits the critical-illness pack at 0.9 and nothing else (Spec §2).

Protected file: written by Claude. User decision 2026-10-18: pilot one pack with post-release spot
checks instead of more Golden first. RV2c showed the reviewer pushed this pack's wrong claims below
0.9 (23 of 24 right at or above it); the other packs stay with people.
"""

from __future__ import annotations

from insurance_harness.catalog.review_policy import load_review_policy

PILOT = "schemapack_critical_illness_insurance"


def test_the_shipped_policy_admits_only_the_pilot_pack_at_its_threshold() -> None:
    policy = load_review_policy()
    assert policy.version == "2"
    assert policy.policy_ref == "review-policy@2"
    assert policy.admitted_packs == [PILOT]
    assert policy.threshold(PILOT, "waiting_period") == 0.9
    assert policy.threshold(PILOT, "premium_payment_term") == 0.9
    for other in (
        "schemapack_accident_insurance",
        "schemapack_disability_income_insurance",
        "schemapack_endowment_insurance",
        "schemapack_whole_life_insurance",
    ):
        assert not policy.admitted(other)
        assert policy.threshold(other, "waiting_period") is None
