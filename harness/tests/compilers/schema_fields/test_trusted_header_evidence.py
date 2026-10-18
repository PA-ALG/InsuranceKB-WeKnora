"""S4j acceptance: only a trusted field may cite a table header, at compile and at publish (§3.4).

Protected file: written by Claude. The shipped TrustPolicy lets the payment term cite a rate
table's header block. At compile a reference to a header segment from any other field is dropped
like an unknown id and counted; at publish such evidence is refused with its own code; and a
source read without table headers still refuses any rate-table evidence as S4i did.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from insurance_harness.bundle.assemble import BundleError
from insurance_harness.compilers.schema_fields.claims import claims_from
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.engine import (
    CompileOutput,
    FieldResult,
    SchemaFieldsCompiler,
)
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision

TERMS = PageText("保险条款.pdf", "a" * 64, 1, "阅读指引\n投保年龄为0周岁至55周岁。\n")
RATES = PageText(
    "费率表.pdf",
    "b" * 64,
    1,
    "《某某重大疾病保险》年交费率表\n交费期间\n投保年龄\n10年交 15年交 20年交 30年交\n"
    "0 408 275 222 157\n",
)
HEADERS = {"rate_table": [RATES]}
SOURCES = {"保险条款.pdf": SourceRevision("k-1", 1), "费率表.pdf": SourceRevision("k-2", 2)}
TERM, AGE = "premium_payment_term", "entry_age_range"


class Replay:
    model = "offline-fixture"

    def __init__(self, *responses: str) -> None:
        self.responses = iter(responses)

    def complete(self, *, system: str, user: str) -> str:
        return next(self.responses)


def definition(key: str, ordinal: int) -> FieldDefinition:
    return FieldDefinition(field_key=key, short_title=key, description=key, ordinal=ordinal)


def answer(*rows: dict[str, object]) -> str:
    return json.dumps({"fields": list(rows)}, ensure_ascii=False)


def header_id(source: SegmentedSource) -> str:
    return next(s.id for s in source.segments if s.document == "费率表.pdf")


def test_compile_keeps_a_trusted_header_reference_and_drops_an_untrusted_one() -> None:
    source = SegmentedSource([TERMS], table_headers=HEADERS)
    header = header_id(source)
    selection = answer(
        {"ordinal": 0, "field_key": TERM, "state": "present", "segments": [header]},
        {"ordinal": 1, "field_key": AGE, "state": "present", "segments": ["D1P1S1", header]},
    )
    values = answer(
        {"ordinal": 0, "field_key": TERM, "value": "10年交、15年交、20年交、30年交"},
        {"ordinal": 1, "field_key": AGE, "value": "0周岁至55周岁"},
    )
    output = SchemaFieldsCompiler(Replay(selection, values)).compile(
        "p1", [definition(TERM, 0), definition(AGE, 1)], [TERMS], table_headers=HEADERS
    )
    by_key = {field.field_key: field for field in output.fields}
    assert by_key[TERM].segment_ids == [header]
    assert {quote.document for quote in by_key[TERM].evidence} == {"费率表.pdf"}
    assert by_key[AGE].segment_ids == ["D1P1S1"]
    assert output.dropped_refs == 1


def test_a_field_left_with_only_untrusted_header_references_is_dropped() -> None:
    source = SegmentedSource([TERMS], table_headers=HEADERS)
    selection = answer(
        {"ordinal": 1, "field_key": AGE, "state": "present", "segments": [header_id(source)]}
    )
    output = SchemaFieldsCompiler(Replay(selection)).compile(
        "p1", [definition(AGE, 1)], [TERMS], table_headers=HEADERS
    )
    assert output.fields == [] and output.dropped_fields == [AGE] and output.dropped_refs == 1


def cited(source: SegmentedSource, key: str) -> FieldResult:
    header = header_id(source)
    return FieldResult(
        field_key=key,
        state="present",
        value="10年交、15年交、20年交、30年交",
        evidence=source.evidence([header]),
        segment_ids=[header],
    )


def output_of(*fields: FieldResult) -> CompileOutput:
    return CompileOutput(
        pack_id="pack", entity_id="p1", model="m", fields=list(fields), cards_version="cards-x"
    )


def test_publish_accepts_the_trusted_field_and_refuses_any_other() -> None:
    source = SegmentedSource([TERMS], table_headers=HEADERS)
    claims = claims_from(output_of(cited(source, TERM)), source, SOURCES)
    assert [claim.predicate for claim in claims] == [TERM]
    assert [e.file_sha256 for e in claims[0].evidence] == ["b" * 64]  # the rate table
    with pytest.raises(BundleError) as refused:
        claims_from(output_of(cited(source, TERM), cited(source, AGE)), source, SOURCES)
    assert (refused.value.reason, refused.value.field_index) == ("EVIDENCE_ROLE_NOT_TRUSTED", 1)


def test_a_source_read_without_table_headers_still_refuses_rate_table_evidence() -> None:
    with_headers = SegmentedSource([TERMS], table_headers=HEADERS)
    without = SegmentedSource([TERMS])
    with pytest.raises(BundleError) as refused:
        claims_from(output_of(cited(with_headers, TERM)), without, SOURCES)
    assert (refused.value.reason, refused.value.field_index) == ("EVIDENCE_DOCUMENT_NOT_READ", 0)


@dataclass(frozen=True)
class Page:
    document: str
    document_sha256: str
    page: int
    text: str


def test_requests_list_header_segments_without_any_rate() -> None:
    requests = SchemaFieldsCompiler(Replay()).build_requests(
        "p1",
        [definition(TERM, 0)],
        [Page(TERMS.document, TERMS.document_sha256, TERMS.page, TERMS.text)],
        table_headers=HEADERS,
    )
    text = "".join(request.user for request in requests)
    assert "10年交 15年交 20年交 30年交" in text
    assert "0 408 275" not in text
