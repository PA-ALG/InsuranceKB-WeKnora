"""Knowledge boundary failures must remain independent of a product or field."""

from typing import Any

import pytest
from pydantic import ValidationError

from insurance_harness.contracts import Claim, Evidence, Locator


def evidence(match: str = "EXACT", quote: str = "A supported source statement") -> Evidence:
    return Evidence(
        source_ref="source-revision",
        file_sha256="b" * 64,
        locator=Locator(kind="PDF_TEXT_SPAN", page=2, start=0, end=28),
        quote=quote,
        match=match,
        access_scope="internal",
    )


def supported_claim(**overrides: Any) -> Claim:
    fields: dict[str, Any] = {
        "claim_id": "claim-a",
        "logical_key": "entity-a:predicate-a",
        "subject_ref": "entity-a",
        "product_version_ref": "version-a",
        "predicate": "predicate-a",
        "state": "present",
        "value": "supported value",
        "evidence": [evidence()],
        "origin": "SOURCE_SUPPORTED",
    }
    fields.update(overrides)
    return Claim(**fields)


@pytest.mark.parametrize("match", ["EXACT", "NORMALIZED"])
def test_verified_evidence_can_support_a_claim(match: str) -> None:
    assert supported_claim(evidence=[evidence(match)]).state == "present"


def test_fuzzy_evidence_cannot_support_a_claim_alone() -> None:
    with pytest.raises(ValidationError):
        supported_claim(evidence=[evidence("FUZZY_REVIEW")])


@pytest.mark.parametrize("value", ["", " ", "\n\t"])
def test_present_rejects_empty_text_value(value: str) -> None:
    with pytest.raises(ValidationError):
        supported_claim(value=value)


def test_claim_is_frozen_at_the_boundary() -> None:
    claim = supported_claim()
    with pytest.raises(ValidationError):
        claim.value = "replaced"


@pytest.mark.parametrize("quote", ["", " \n\t"])
def test_empty_quote_cannot_be_evidence(quote: str) -> None:
    with pytest.raises(ValidationError):
        evidence(quote=quote)


@pytest.mark.parametrize("reason", ["", "UNDECLARED_REASON"])
def test_unknown_rejects_untyped_reasons(reason: str) -> None:
    with pytest.raises(ValidationError):
        supported_claim(state="unknown", value=None, evidence=[], unknown_reason=reason)


def test_explicit_absence_needs_verified_evidence() -> None:
    with pytest.raises(ValidationError):
        supported_claim(state="absent_explicitly", value=None, evidence=[evidence("FUZZY_REVIEW")])
