"""S12c-12b RED: real compiler/claims/scoring helpers with only synthetic completions."""

import hashlib

import pytest

from insurance_harness.bundle.assemble import BundleError
from insurance_harness.compilers.schema_fields.cards import cards_version
from insurance_harness.compilers.schema_fields.claims import claims_from
from insurance_harness.compilers.schema_fields.engine import (
    CompileOutput,
    FieldResult,
    SchemaFieldsCompiler,
    reusable,
)
from insurance_harness.compilers.schema_fields.prompt import VALUE_PROTOCOL_VERSION
from insurance_harness.eval.golden_remap import PreviousSegment, PreviousSegmentation, remap_golden
from insurance_harness.eval.segment_score import (
    GoldenV2,
    GoldenV2Evidence,
    GoldenV2Field,
    score_selection,
)
from insurance_harness.evidence.source_ref import SourceRevision
from tests.compilers.schema_fields.test_trusted_header_evidence import (
    Replay,
    answer,
    definition,
    output_of,
)
from tests.evidence.test_rate_notes import NOTE, source

TERM, FREQ, AGE = "premium_payment_term", "premium_payment_frequency", "entry_age_range"


def test_compile_and_claims_adopt_notes_only_for_the_allowed_fields() -> None:
    src = source(NOTE)
    ids = [s.id for s in src.segments]
    assert len(ids) == 2
    selection = answer(
        *[
            {"ordinal": i, "field_key": key, "state": "present", "segments": ids}
            for i, key in enumerate((TERM, FREQ, AGE))
        ]
    )
    values = answer(
        {"ordinal": 0, "field_key": TERM, "state": "present", "value": "10年交"},
        {"ordinal": 1, "field_key": FREQ, "state": "present", "value": "年交"},
    )
    output = SchemaFieldsCompiler(Replay(selection, values)).compile(
        "synthetic",
        [definition(k, i) for i, k in enumerate((TERM, FREQ, AGE))],
        [],
        table_headers={"rate_table": src.pages},
    )
    fields = {f.field_key: f for f in output.fields}
    assert fields[TERM].segment_ids == ids
    assert fields[FREQ].segment_ids == ids[1:]
    assert AGE not in fields and output.dropped_refs == 3
    assert len(fields[TERM].evidence) == 2
    claims = claims_from(output, src, {"synthetic.pdf": SourceRevision("synthetic", 1)})
    assert {c.predicate for c in claims} == {TERM, FREQ}
    assert not any("999" in e.quote for c in claims for e in c.evidence)


def test_a_forged_frequency_header_output_is_refused_even_when_notes_exist() -> None:
    src = source(NOTE)
    header = src.segments[0]
    field = FieldResult(
        field_key=FREQ,
        state="present",
        value="年交",
        segment_ids=[header.id],
        evidence=src.evidence([header.id]),
    )
    with pytest.raises(BundleError) as error:
        claims_from(output_of(field), src, {"synthetic.pdf": SourceRevision("synthetic", 1)})
    assert error.value.reason == "EVIDENCE_ROLE_NOT_TRUSTED"


def test_scoring_does_not_give_frequency_header_or_other_field_note_credit() -> None:
    src = source(NOTE)
    assert len(src.segments) == 2
    header, note = src.segments

    def gold(key: str) -> GoldenV2:
        quote = GoldenV2Evidence(
            **src.evidence([note.id])[0].model_dump(exclude={"match"}), segment_id=note.id
        )
        return GoldenV2(
            product_id="synthetic",
            cards_version="v",
            fields=(
                GoldenV2Field(
                    field_key=key, state="present", value="年交", reason="合成", evidence=(quote,)
                ),
            ),
        )

    for recorded in ([], [header.id]):
        prediction = FieldResult(
            field_key=FREQ,
            state="present",
            value="年交",
            segment_ids=recorded,
            evidence=src.evidence([header.id]),
        )
        report = score_selection(src, gold(FREQ), [prediction])
        assert report.recall_mean == 0 and report.unmapped_predicted_quotes == 1
    assert score_selection(src, gold(AGE), []).unmapped_golden_quotes == 1


def test_header_restoration_does_not_adopt_the_new_note_segments() -> None:
    src = source(NOTE)
    assert len(src.segments) == 2
    header = src.segments[0]
    old = PreviousSegment(
        id="old",
        document=header.document,
        document_sha256=header.document_sha256,
        page=1,
        start=0,
        end=len(header.text),
        text=header.text,
    )
    previous = PreviousSegmentation(
        pages={(header.document, 1): hashlib.sha256(src.pages[0].text.encode()).hexdigest()},
        segments={"old": old},
    )
    quote = GoldenV2Evidence(
        document=header.document,
        document_sha256=header.document_sha256,
        page=1,
        quote=header.text,
        segment_id="old",
    )
    gold = GoldenV2(
        product_id="synthetic",
        cards_version="v",
        fields=(
            GoldenV2Field(
                field_key=TERM, state="present", value="10年", reason="合成", evidence=(quote,)
            ),
        ),
    )
    result, _ = remap_golden(
        gold,
        previous,
        src.pages,
        excluded={header.document},
        emptied_reason="not trusted",
        table_headers={"rate_table": src.pages},
    )
    assert [q.segment_id for q in result.fields[0].evidence] == [header.id]


def test_pipeline_version_invalidates_the_old_output_without_changing_cards() -> None:
    assert VALUE_PROTOCOL_VERSION == "2026-11-05.1"
    materials = ["file:" + "a" * 64]
    old = CompileOutput(
        pack_id="synthetic",
        entity_id="synthetic",
        model="fake",
        cards_version=cards_version(),
        materials=materials,
        value_protocol="2026-10-29.4",
    )
    assert not reusable(old, materials)
    assert reusable(old.model_copy(update={"value_protocol": VALUE_PROTOCOL_VERSION}), materials)
