"""S4g acceptance: member digests match the platform byte for byte (Spec §2.1).

Protected file: written by Claude. The vectors come from Go's encoding/json and are shared with
internal/enterprise/release/canonical_vectors_test.go, which pins the frozen S3b digest
definition (json.Marshal after json.Unmarshal into any) on the Go side.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.publish.canonical import canonical_json, member_digest

VECTORS = Path(__file__).resolve().parents[3] / (
    "internal/enterprise/release/testdata/canonical_vectors.json"
)


def vectors() -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = json.loads(VECTORS.read_text(encoding="utf-8"))
    return loaded


@pytest.mark.parametrize("vector", vectors(), ids=lambda v: str(v["name"]))
def test_canonical_form_and_digest_match_go(vector: dict[str, Any]) -> None:
    assert canonical_json(vector["payload"]).decode("utf-8") == vector["canonical"]
    assert member_digest(vector["payload"]) == vector["digest"]


@pytest.mark.parametrize(
    "value",
    [
        {"x": math.nan},
        {"x": math.inf},
        {"x": -math.inf},
        {"x": 2**53 + 1},
        {"x": -(2**53) - 1},
        {"x": "\ud800"},
        {"\udfff": 1},
    ],
)
def test_values_go_would_rewrite_are_rejected(value: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        canonical_json(value)
