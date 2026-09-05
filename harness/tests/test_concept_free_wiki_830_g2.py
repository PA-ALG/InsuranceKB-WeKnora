from __future__ import annotations

import importlib
import importlib.util

import pytest


def api():
    name = "insurance_harness.knowledge_compiler.concept_free_wiki_830_g2"
    assert importlib.util.find_spec(name) is not None, "G2-R2: no shared concept/member contract"
    return importlib.import_module(name)


def test_shared_definition_identity_ignores_entity_collection():
    g = api()
    source = g.SourceBlock(
        tenant_id=1,
        space_id="space-a",
        raw_kb_id="raw-a",
        knowledge_id="knowledge-a",
        parse_attempt=1,
        revision_id="source-r1",
        source_hash="a" * 64,
        parse_hash="b" * 64,
        parser_identity="native-v1",
        block_id="p1",
        page_number=1,
        text="被保险人就是受保险合同保障的人。",
        source_type="DOCUMENT",
    )
    evidence = g.evidence_for(source, 0, len(source.text))
    definition = g.ConceptDefinition(
        space_id="space-a",
        canonical_key="insured",
        sense_key="insurance",
        title="被保险人",
        body=source.text,
        evidence=(evidence,),
    )
    first = g.FieldAssertion(
        space_id="space-a",
        entity_id="real-a",
        field_key="insured_eligibility",
        state="present",
        value="符合承保条件",
        attempted=True,
        evidence=(evidence,),
        concept_ids=(definition.concept_id,),
    )
    second = first.model_copy(
        update={
            "entity_id": "real-b",
            "state": "unknown",
            "value": None,
            "evidence": (),
            "unknown_reason": "NOT_FOUND",
        }
    )
    a = g.aggregate_concept("release-a", 1, definition, (first,))
    b = g.aggregate_concept("release-b", 2, definition, (first, second))
    assert a.definition_hash == b.definition_hash == definition.definition_hash
    assert len(a.assertions) == 1 and len(b.assertions) == 2
    assert a.aggregate_hash != b.aggregate_hash
    assert b.assertions[1].state == "unknown"


def test_identity_is_space_and_sense_scoped_and_aliases_do_not_replace_identity():
    g = api()
    assert g.concept_id("a", "insured", "insurance") != g.concept_id("b", "insured", "insurance")
    assert g.concept_id("a", "insured", "insurance") != g.concept_id("a", "insured", "other")
    assert g.concept_id("a", " INSURED ", "insurance") == g.concept_id("a", "insured", "insurance")


def test_quote_verification_rejects_text_revision_and_offsets():
    g = api()
    source = g.SourceBlock(
        tenant_id=1,
        space_id="space-a",
        raw_kb_id="raw-a",
        knowledge_id="knowledge-a",
        parse_attempt=1,
        revision_id="r",
        source_hash="a" * 64,
        parse_hash="b" * 64,
        parser_identity="native-v1",
        block_id="p1",
        page_number=1,
        text="等待期30日，意外除外。",
        source_type="DOCUMENT",
    )
    evidence = g.evidence_for(source, 0, 6)
    g.verify_evidence(evidence, (source,))
    for patch in ({"quote": "等待期90日"}, {"revision_id": "other"}, {"start": 1}):
        with pytest.raises(ValueError):
            g.verify_evidence(evidence.model_copy(update=patch), (source,))


@pytest.mark.parametrize(
    "score,expected",
    [(59, "mention"), (60, "pending"), (79, "pending"), (80, "new_page"), (100, "new_page")],
)
def test_admission_score_boundary(score, expected):
    g = api()
    assert (
        g.admission_disposition("new_page", score, evidence_valid=True, identity_valid=True)
        == expected
    )
    assert (
        g.admission_disposition("new_page", score, evidence_valid=False, identity_valid=True)
        == "reject"
    )


def test_required_unknown_bypasses_value_score_but_must_be_attempted():
    g = api()
    assert (
        g.admission_disposition(
            "field_rule",
            0,
            evidence_valid=False,
            identity_valid=True,
            required=True,
            attempted=True,
            value_state="unknown",
        )
        == "field_rule"
    )
    with pytest.raises(ValueError):
        g.FieldAssertion(
            space_id="s",
            entity_id="e",
            field_key="f",
            state="unknown",
            value=None,
            unknown_reason="NOT_FOUND",
            attempted=False,
        )


def test_foreign_assertion_and_dangling_concept_link_fail_closed():
    g = api()
    source = g.SourceBlock(
        tenant_id=1,
        space_id="space-a",
        raw_kb_id="raw-a",
        knowledge_id="knowledge-a",
        parse_attempt=1,
        revision_id="r",
        source_hash="a" * 64,
        parse_hash="b" * 64,
        parser_identity="native-v1",
        block_id="p1",
        page_number=1,
        text="被保险人",
        source_type="DOCUMENT",
    )
    d = g.ConceptDefinition(
        space_id="a",
        canonical_key="insured",
        sense_key="insurance",
        title="被保险人",
        body=source.text,
        evidence=(g.evidence_for(source, 0, len(source.text)),),
    )
    f = g.FieldAssertion(
        space_id="b",
        entity_id="e",
        field_key="f",
        state="unknown",
        value=None,
        unknown_reason="NOT_FOUND",
        attempted=True,
        concept_ids=(d.concept_id,),
    )
    with pytest.raises(ValueError):
        g.aggregate_concept("r", 1, d, (f,))
    with pytest.raises(ValueError):
        g.lint_members("a", (), (f.model_copy(update={"space_id": "a"}),), ())
