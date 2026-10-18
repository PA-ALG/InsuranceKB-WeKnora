"""S3e-3 acceptance: the concept member contract (Spec §4.1).

Protected file: written by Claude. A concept summary is model-generated text over published claims:
every statement references at least one claim, every reference is among the claims it was built on,
and the origin says it is model-generated.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from insurance_harness.contracts import ConceptSummary
from insurance_harness.contracts.export import export


def summary(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "concept_key": "cooling_off_period",
        "title": "犹豫期",
        "definition": "签收合同后可无损失解除合同的期间。",
        "explanation": "犹豫期是签收合同后的冷静期。",
        "statements": [
            {"text": "两款产品为15日。", "refs": ["P1/cooling_off_period", "P2/cooling_off_period"]}
        ],
        "based_on": {"P1/cooling_off_period": "a" * 64, "P2/cooling_off_period": "b" * 64},
        "origin": "MODEL_GENERATED",
        "model": "deepseek-flash",
        "prompt_version": "concept-test",
    }
    data.update(changes)
    return data


def test_a_valid_summary_parses() -> None:
    parsed = ConceptSummary.model_validate(summary())
    assert parsed.statements[0].refs == ["P1/cooling_off_period", "P2/cooling_off_period"]


@pytest.mark.parametrize(
    "data",
    [
        summary(statements=[]),
        summary(statements=[{"text": "无依据。", "refs": []}]),
        summary(statements=[{"text": "x", "refs": ["P9/cooling_off_period"]}]),
        summary(based_on={}),
        summary(origin="SOURCE_SUPPORTED"),
        summary(explanation=" "),
        summary(based_on={"P1/cooling_off_period": "short"}),
        summary(statements=[{"text": "x", "refs": ["P1/cooling_off_period"]}] * 7),
    ],
    ids=[
        "no statement",
        "no ref",
        "ref outside basis",
        "no basis",
        "not generated",
        "blank",
        "bad digest",
        "too many",
    ],
)
def test_an_invalid_summary_is_refused(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ConceptSummary.model_validate(data)


def test_the_concept_summary_schema_is_exported(tmp_path: Path) -> None:
    names = {path.name for path in export(tmp_path)}
    assert "concept_summary.schema.json" in names
    schema = json.loads((tmp_path / "concept_summary.schema.json").read_text(encoding="utf-8"))
    assert {"statements", "based_on", "origin"} <= set(schema["properties"])
