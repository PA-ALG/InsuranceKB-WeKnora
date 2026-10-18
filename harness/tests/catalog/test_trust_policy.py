"""S4j acceptance: the TrustPolicy decides, by field and material role, what is evidence (§3.2).

Protected file: written by Claude. User ruling 2026-10-18: a rate table stays out as a whole, but
the payment-term field may cite the header block of its pages. The rule is versioned data; a
policy that names an unknown role, a role that is evidence anyway, or malformed fields is refused.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from insurance_harness.catalog.trust_policy import (
    TrustPolicyError,
    load_trust_policy,
    parse_trust_policy,
)


def test_the_shipped_policy_lets_only_the_payment_term_cite_rate_table_headers() -> None:
    policy = load_trust_policy()
    assert policy.version
    assert policy.header_roles() == frozenset({"rate_table"})
    assert policy.header_fields("rate_table") == frozenset({"premium_payment_term"})
    assert policy.header_fields("terms") == frozenset()
    assert policy.header_fields("no_such_role") == frozenset()


def rule(role: str = "rate_table", fields: Any = ("premium_payment_term",)) -> dict[str, Any]:
    return {"role": role, "fields": list(fields)}


def policy(*rules: dict[str, Any], **extra: Any) -> str:
    return json.dumps({"version": "v1", "header_rules": list(rules), **extra}, ensure_ascii=False)


def test_a_valid_policy_text_parses() -> None:
    parsed = parse_trust_policy(policy(rule(fields=("a", "b"))))
    assert parsed.header_fields("rate_table") == frozenset({"a", "b"})


INVALID = {
    "unknown role": policy(rule(role="fax_sheet")),
    "role that is evidence anyway": policy(rule(role="terms")),
    "role twice": policy(rule(fields=("a",)), rule(fields=("b",))),
    "no fields": policy(rule(fields=())),
    "field twice": policy(rule(fields=("a", "a"))),
    "blank field": policy(rule(fields=(" ",))),
    "extra top-level key": policy(rule(), scope="all"),
    "extra rule key": json.dumps(
        {"version": "v1", "header_rules": [{**rule(), "scope": "document"}]}
    ),
    "blank version": json.dumps({"version": " ", "header_rules": [rule()]}),
    "not json": "{",
    "fields not a list": json.dumps(
        {"version": "v1", "header_rules": [{"role": "rate_table", "fields": "a"}]}
    ),
}


@pytest.mark.parametrize("text", INVALID.values(), ids=INVALID.keys())
def test_an_invalid_policy_is_refused_with_one_code(text: str) -> None:
    with pytest.raises(TrustPolicyError) as refused:
        parse_trust_policy(text)
    assert refused.value.code == "TRUST_POLICY_INVALID"
    assert isinstance(refused.value, ValueError)
