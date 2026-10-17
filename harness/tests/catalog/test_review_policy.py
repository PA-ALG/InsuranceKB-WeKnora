"""RV1 acceptance: the versioned review policy (Spec §3.1).

Protected file: written by Claude. Thresholds per pack with field overrides, admitted packs, a
policy reference that changes with the version, and a shipped policy that admits no pack until a
pack passes quality admission (RV3). Anything malformed is refused.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.catalog.review_policy import load_review_policy


def write(tmp_path: Path, content: Any) -> Path:
    path = tmp_path / "policy.json"
    text = content if isinstance(content, str) else json.dumps(content)
    path.write_text(text, encoding="utf-8")
    return path


def test_the_shipped_policy_admits_no_pack_yet() -> None:
    policy = load_review_policy()
    assert policy.admitted_packs == []
    assert policy.policy_ref == f"review-policy@{policy.version}"
    assert not policy.admitted("schemapack_critical_illness_insurance")


def test_field_thresholds_override_the_pack_default(tmp_path: Path) -> None:
    policy = load_review_policy(
        write(
            tmp_path,
            {
                "version": "7",
                "admitted_packs": ["pack_a"],
                "thresholds": {
                    "pack_a": {"default": 0.9, "fields": {"term_b": 0.95}},
                    "pack_c": {"fields": {"term_x": 0.8}},
                },
            },
        )
    )
    assert policy.policy_ref == "review-policy@7"
    assert policy.admitted("pack_a") and not policy.admitted("pack_c")
    assert policy.threshold("pack_a", "term_a") == 0.9
    assert policy.threshold("pack_a", "term_b") == 0.95
    assert policy.threshold("pack_c", "term_x") == 0.8
    assert policy.threshold("pack_c", "term_y") is None
    assert policy.threshold("pack_b", "term_a") is None


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        {"version": ""},
        {"version": "1", "thresholds": {"p": {"default": 1.5}}},
        {"version": "1", "thresholds": {"p": {"fields": {"x": -0.1}}}},
        {"version": "1", "admitted_packs": ["p", "p"]},
        {"version": "1", "extra": 1},
        {"version": "1", "thresholds": {"p": {"default": 0.9, "unknown": 1}}},
    ],
)
def test_a_malformed_policy_is_refused(tmp_path: Path, content: Any) -> None:
    with pytest.raises(ValueError):
        load_review_policy(write(tmp_path, content))


def test_an_unreadable_policy_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        load_review_policy(tmp_path / "missing.json")
