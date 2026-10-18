"""A field the model adds to a concept or a statement is ignored, not a refusal (S3e-3 Spec §4.1
revision, 2026-10-18 run: 8 of 33 answers added "title", "explanation_note" or "key_note").

The added text is never read: only the named fields become the draft, so nothing of it is checked
or published. A missing or mistyped field still refuses the whole batch.
"""

from __future__ import annotations

import json

import pytest

from insurance_harness.bundle.client import Release
from insurance_harness.compilers.concepts.synthesis import (
    ConceptOutputError,
    concept_inputs,
    parse_concepts,
)

A = "P1/cooling_off_period"


def concept(key: str, **extra: object) -> dict[str, object]:
    return {"key": key, "definition": "定义。", "explanation": "解释。",
            "statements": [{"text": "甲产品为15日。", "refs": [A], **extra}], **extra}  # fmt: skip


def test_added_fields_are_dropped(release: Release) -> None:
    batch = concept_inputs(release)
    text = json.dumps(
        {"concepts": [concept("cooling_off_period", title="犹豫期", explanation_note="注"),
                      concept("premium_grace_period", key_note="x")]},
        ensure_ascii=False,
    )  # fmt: skip
    drafts = parse_concepts(text, batch)
    cooling = drafts["cooling_off_period"]
    assert (cooling.definition, cooling.explanation) == ("定义。", "解释。")
    assert cooling.statements[0].refs == (A,)
    assert not hasattr(cooling, "title")


@pytest.mark.parametrize("missing", ["definition", "explanation", "statements", "key"])
def test_a_missing_field_still_refuses_the_batch(release: Release, missing: str) -> None:
    batch = concept_inputs(release)
    broken = concept("cooling_off_period")
    del broken[missing]
    text = json.dumps({"concepts": [broken, concept("premium_grace_period")]}, ensure_ascii=False)
    with pytest.raises(ConceptOutputError):
        parse_concepts(text, batch)


def test_the_top_level_object_stays_exact(release: Release) -> None:
    batch = concept_inputs(release)
    text = json.dumps(
        {"concepts": [concept("cooling_off_period"), concept("premium_grace_period")], "note": "x"}
    )
    with pytest.raises(ConceptOutputError):
        parse_concepts(text, batch)
