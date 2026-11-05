"""Implementation controls: Office boundaries and versioned rule validation."""

import json

import pytest

from insurance_harness.catalog.trust_policy import TrustPolicyError, parse_trust_policy
from insurance_harness.evidence.rate_notes import restricted_regions


def test_only_first_table_on_page_can_start_notes_even_with_multiple_office_blocks() -> None:
    first = "Heading\n0 999\n注：first。"
    second = "0 888\n注：second。"
    text = first + "\n\n" + second
    ranges = [(0, len(first)), (len(first) + 2, len(text))]
    regions = restricted_regions(ranges, text, (0, 7), ["注"], [])
    assert [text[a:b] for _, a, b, kind in regions if kind == "note"] == ["注：first。"]


def test_note_in_another_office_block_is_not_adjacent_to_table() -> None:
    first, second = "Heading\n0 999", "注：second。"
    text = first + "\n\n" + second
    regions = restricted_regions(
        [(0, len(first)), (len(first) + 2, len(text))], text, (0, 7), ["注"], []
    )
    assert all(kind == "header" for _, _, _, kind in regions)


@pytest.mark.parametrize("role,repeat", [("terms", 1), ("rate_table", 2)])
def test_note_rules_cannot_create_new_role_or_duplicate_grant(role: str, repeat: int) -> None:
    data = {
        "version": "test",
        "header_rules": [{"role": "rate_table", "fields": ["premium_payment_term"]}],
        "note_rules": [
            {
                "role": role,
                "fields": ["premium_payment_frequency"],
                "markers": ["注"],
                "title_endings": ["保险"],
            }
        ]
        * repeat,
    }
    with pytest.raises(TrustPolicyError):
        parse_trust_policy(json.dumps(data))
