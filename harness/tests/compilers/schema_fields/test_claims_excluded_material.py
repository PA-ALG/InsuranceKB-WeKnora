"""S4i acceptance: inputs made before rate tables were excluded are refused or counted (Spec §3.2).

Protected file: written by Claude after review R4 on #200. A compile output whose evidence names a
document that was not read as evidence is refused before any id is checked; scoring counts such a
quote as unmapped; and an old id that happens to exist but cuts other text is never trusted.
"""

from __future__ import annotations

import pytest

from insurance_harness.bundle.assemble import BundleError
from insurance_harness.compilers.schema_fields.claims import claims_from
from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.eval.segment_score import (
    GoldenV2,
    GoldenV2Evidence,
    GoldenV2Field,
    score_selection,
)
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.identity.material_roles import evidence_pages

SHA_T, SHA_R = "a" * 64, "b" * 64
TERMS = PageText(
    "保险条款.pdf",
    SHA_T,
    1,
    "阅读指引\n1.4 等待期\n自本合同生效之日起90日内为等待期。\n本合同不设宽限期。\n",
)
RATES = PageText("费率表.pdf", SHA_R, 1, "年交费率表\n交费期间 10年交 15年交\n")
OLD = SegmentedSource([TERMS, RATES])  # what a compile saw before S4i
KEPT = SegmentedSource(evidence_pages([TERMS, RATES]))
SOURCES = {"保险条款.pdf": SourceRevision("k-1", 1)}


def selected(source: SegmentedSource, *ids: str) -> FieldResult:
    return FieldResult(
        field_key="field",
        state="present",
        value="取值",
        evidence=source.evidence(list(ids)),
        segment_ids=list(ids),
    )


def test_old_evidence_on_a_rate_table_is_refused_before_ids_are_checked() -> None:
    rate_id = next(s.id for s in OLD.segments if s.document == "费率表.pdf")
    fine = selected(KEPT, "D1P1S2").model_copy(update={"field_key": "waiting_period"})
    stale = selected(OLD, rate_id).model_copy(update={"field_key": "premium_payment_term"})
    output = CompileOutput(
        pack_id="pack", entity_id="p1", model="m", fields=[fine, stale], cards_version="cards-x"
    )
    with pytest.raises(BundleError) as refused:
        claims_from(output, KEPT, SOURCES)
    assert (refused.value.reason, refused.value.field_index) == ("EVIDENCE_DOCUMENT_NOT_READ", 1)


def golden() -> GoldenV2:
    segment = next(s for s in KEPT.segments if s.id == "D1P1S2")
    quote = GoldenV2Evidence(
        document=segment.document,
        document_sha256=segment.document_sha256,
        page=segment.page,
        quote=segment.text,
        segment_id=segment.id,
    )
    item = GoldenV2Field(
        field_key="field", state="present", value="90日", reason="r", evidence=(quote,)
    )
    return GoldenV2(product_id="p1", cards_version="cards-x", fields=(item,))


def test_scoring_counts_a_quote_on_a_rate_table_as_unmapped() -> None:
    rate_id = next(s.id for s in OLD.segments if s.document == "费率表.pdf")
    stale = selected(OLD, rate_id).model_copy(update={"segment_ids": []})
    report = score_selection(KEPT, golden(), [stale])
    assert report.unmapped_predicted_quotes == 1
    assert report.fields[0].recall == 0.0


def test_an_old_id_that_exists_but_cuts_other_text_is_not_trusted() -> None:
    reused = selected(KEPT, "D1P1S2").model_copy(update={"segment_ids": ["D1P1S3"]})
    report = score_selection(KEPT, golden(), [reused])
    assert (report.fields[0].recall, report.fields[0].precision) == (1.0, 1.0)
