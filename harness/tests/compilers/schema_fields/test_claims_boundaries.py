"""Compile output to claims: failures give codes and positions, never input text (PR #169)."""

from __future__ import annotations

import pytest

from insurance_harness.bundle.assemble import BundleError
from insurance_harness.compilers.schema_fields.claims import candidate_bundle
from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision

SECRET = "SECRET-MARKER-保险条款原文"


class Page:
    document, document_sha256, page, text = "条款.pdf", "ab" * 32, 1, "本合同等待期为90日。\n"


SOURCE = SegmentedSource([Page()])
SOURCES = {"条款.pdf": SourceRevision("k-1", 2)}
GOOD = FieldResult(
    field_key="waiting_period",
    state="present",
    value="90日",
    evidence=SOURCE.evidence(["D1P1S1"]),
    segment_ids=["D1P1S1"],
)


def output(*fields: FieldResult, version: str | None = "draft-test") -> CompileOutput:
    return CompileOutput(
        pack_id="p", entity_id="1828", model="m", fields=list(fields), cards_version=version
    )


@pytest.mark.parametrize("version", [None, "", "   "])
def test_missing_or_blank_versions_are_refused_at_the_conversion(version: str | None) -> None:
    with pytest.raises(BundleError) as caught:
        candidate_bundle(output(GOOD, version=version), SOURCE, SOURCES, compiler_identity="x")
    assert caught.value.reason == "CARDS_VERSION_UNKNOWN"


def test_a_claim_the_contract_rejects_is_reported_by_position() -> None:
    no_value = FieldResult(
        field_key=SECRET,
        state="present",
        value=None,
        evidence=SOURCE.evidence(["D1P1S1"]),
        segment_ids=["D1P1S1"],
    )
    with pytest.raises(BundleError) as caught:
        candidate_bundle(output(GOOD, no_value), SOURCE, SOURCES, compiler_identity="x")
    assert (caught.value.reason, caught.value.field_index) == ("CLAIM_INVALID", 1)
    assert SECRET not in str(caught.value)


def test_evidence_errors_never_echo_the_field_key() -> None:
    bad_ids = FieldResult(
        field_key=SECRET,
        state="present",
        value="90日",
        evidence=SOURCE.evidence(["D1P1S1"]),
        segment_ids=["D9P9S9"],
    )
    with pytest.raises(BundleError) as caught:
        candidate_bundle(output(bad_ids), SOURCE, SOURCES, compiler_identity="x")
    assert (caught.value.reason, caught.value.field_index) == ("EVIDENCE_MISMATCH", 0)
    assert SECRET not in str(caught.value)
