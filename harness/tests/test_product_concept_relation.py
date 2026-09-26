"""A formal relation is a typed, source-bound atomic release member."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from insurance_harness.knowledge_compiler import concept_free_wiki_830_g2 as d
from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import (
    batch_json_bytes_830_g3,
    definition_sha256_830_g3,
)
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
    AuditDisposition,
    CompileOutput,
    CompileRequest,
    free_page_id,
    validate_output,
)


def relation_case() -> tuple[d.SourceBlock, d.ConceptDefinition, dict[str, Any]]:
    source = d.SourceBlock(
        tenant_id=1,
        space_id="space",
        raw_kb_id="raw",
        knowledge_id="document",
        parse_attempt=1,
        revision_id="revision",
        source_hash="a" * 64,
        parse_hash="b" * 64,
        parser_identity="parser",
        block_id="block",
        page_number=3,
        source_type="DOCUMENT",
        text="给付附加险的重大疾病保险金后，主险基本保险金额按给付金额等额减少。",
    )
    evidence = d.evidence_for(source, 0, len(source.text))
    definition = d.ConceptDefinition(
        space_id="space",
        canonical_key="advance-critical-illness",
        sense_key="category",
        title="提前给付型重大疾病保险",
        body=source.text,
        evidence=(evidence,),
    )
    predicate = "benefit_reduced_by_advance_payment"
    stable_key = "relation_" + d.digest(
        "product-concept-relation-identity",
        ["space", "product", predicate, definition.concept_id],
    )
    page = dict(
        space_id="space",
        entity_id="product",
        entity_version="2026",
        stable_key=stable_key,
        title="提前给付后的责任扣减",
        body=source.text,
        concept_ids=[definition.concept_id],
        evidence=[evidence.model_dump(mode="json")],
        conditions=[],
        exceptions=[],
        valid_time="",
        business_relation={
            "contract": "product-concept-relation.830.v1",
            "subject_type": "PRODUCT",
            "object_type": "CONCEPT",
            "predicate": predicate,
            "object_concept_id": definition.concept_id,
            "object_definition_sha256": definition_sha256_830_g3(definition),
        },
        content_provenance={
            "contract": "knowledge-content-provenance.830.v1",
            "segments": [
                {"text": source.text, "origin": "SOURCE_SUPPORTED", "evidence_indexes": [0]},
            ],
        },
    )
    return source, definition, page


def test_relation_member_roundtrip_and_closed_target() -> None:
    _, definition, raw = relation_case()
    page = d.FreeWikiPage.model_validate(raw)
    d.lint_members("space", (definition,), (), (page,))
    assert page.model_dump(mode="json")["business_relation"] == raw["business_relation"]
    assert b'"business_relation"' in batch_json_bytes_830_g3(page)


@pytest.mark.parametrize(
    "mutation",
    [
        "null",
        "unknown_contract",
        "unknown_predicate",
        "untyped_subject",
        "extra",
        "wrong_key",
        "different_entity",
        "wrong_link",
        "empty_version",
        "no_evidence",
        "model_origin",
        "missing_provenance",
    ],
)
def test_relation_rejects_invalid_identity_or_unsupported_fact(mutation: str) -> None:
    _, _, raw = relation_case()
    relation = raw["business_relation"]
    if mutation == "null":
        raw["business_relation"] = None
    elif mutation == "unknown_contract":
        relation["contract"] = "relation.v99"
    elif mutation == "unknown_predicate":
        relation["predicate"] = "related_to"
    elif mutation == "untyped_subject":
        relation["subject_type"] = "CONCEPT"
    elif mutation == "extra":
        relation["confidence"] = 1
    elif mutation == "wrong_key":
        raw["stable_key"] = "ordinary-article"
    elif mutation == "different_entity":
        raw["entity_id"] = "other-product"
    elif mutation == "wrong_link":
        raw["concept_ids"] = []
    elif mutation == "empty_version":
        raw["entity_version"] = ""
    elif mutation == "missing_provenance":
        raw.pop("content_provenance")
    elif mutation == "model_origin":
        raw["evidence"] = []
        raw["content_provenance"]["segments"][0].update(
            origin="MODEL_GENERATED", evidence_indexes=[]
        )
    else:
        raw["evidence"] = []
    with pytest.raises(ValueError):
        d.FreeWikiPage.model_validate(raw)


@pytest.mark.parametrize("mutation", ["missing", "changed_revision", "other_space"])
def test_relation_requires_same_release_exact_concept(mutation: str) -> None:
    _, definition, raw = relation_case()
    page = d.FreeWikiPage.model_validate(raw)
    if mutation == "missing":
        definitions = ()
    elif mutation == "other_space":
        definitions = (definition.model_copy(update={"space_id": "other"}),)
    else:
        definitions = (definition.model_copy(update={"body": definition.body + "新的义项"}),)
    with pytest.raises(ValueError):
        d.lint_members("space", definitions, (), (page,))


def test_ordinary_page_bytes_remain_unchanged_and_do_not_imply_relation() -> None:
    _, _, raw = relation_case()
    raw.pop("business_relation")
    raw["stable_key"] = "ordinary"
    page = d.FreeWikiPage.model_validate(raw)
    assert "business_relation" not in page.model_dump(mode="json")
    assert batch_json_bytes_830_g3(page) == batch_json_bytes_830_g3(raw)


def compile_case() -> tuple[CompileRequest, CompileOutput]:
    source, definition, raw = relation_case()
    page = d.FreeWikiPage.model_validate(raw)
    field = d.FieldAssertion(
        space_id="space",
        entity_id="product",
        entity_version="2026",
        field_key="name",
        state="unknown",
        value=None,
        attempted=True,
        unknown_reason="not provided",
    )
    request = CompileRequest(
        request_id="request",
        tenant_id=1,
        space_id="space",
        raw_kb_id="raw",
        wiki_kb_id="wiki",
        policy_identity="policy",
        sources=(source,),
        required_fields={"product": ("name",)},
        entity_versions={"product": "2026"},
        schema_identity="schema",
        profile_identity="profile",
    )
    output = CompileOutput(
        request_hash=request.request_hash,
        definitions=(definition,),
        fields=(field,),
        pages=(page,),
        audit=(
            AuditDisposition(key=definition.concept_id, disposition="new_page", reason="new"),
            AuditDisposition(key=free_page_id(page), disposition="new_page", reason="new"),
            AuditDisposition(key=field.assertion_id, disposition="field_rule", reason="field"),
        ),
    )
    return request, output


def test_relation_uses_existing_compile_evidence_and_review_hash() -> None:
    request, output = compile_case()
    from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
        _validate_output_g3,
    )

    _validate_output_g3(request, output)
    with pytest.raises(ValueError, match="RELATION_REQUIRES_G3"):
        validate_output(request, output)
    changed = deepcopy(output.model_dump(mode="json"))
    page = changed["pages"][0]
    page["conditions"] = ["提前给付后"]
    page["content_provenance"]["segments"][0]["text"] += "\n条件：提前给付后"
    revised = CompileOutput.model_validate(changed)
    _validate_output_g3(request, revised)
    assert revised.output_hash != output.output_hash
    assert free_page_id(revised.pages[0]) == free_page_id(output.pages[0])
    # A syntactically valid forged quote is still rejected by original source verification.
    forged = deepcopy(changed)
    evidence = forged["pages"][0]["evidence"][0]
    evidence["quote"] = "假" * len(evidence["quote"])
    import hashlib

    evidence["quote_hash"] = hashlib.sha256(evidence["quote"].encode()).hexdigest()
    with pytest.raises(ValueError, match="QUOTE_MISMATCH"):
        _validate_output_g3(request, CompileOutput.model_validate(forged))


def test_relation_version_changes_revision_not_identity_and_rejects_stale_binding() -> None:
    from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
        _validate_output_g3,
    )

    request, output = compile_case()
    page = d.FreeWikiPage.model_validate(
        {**output.pages[0].model_dump(mode="json"), "entity_version": "2027"}
    )
    assert free_page_id(page) == free_page_id(output.pages[0])
    assert batch_json_bytes_830_g3(page) != batch_json_bytes_830_g3(output.pages[0])
    revised = output.model_copy(update={"pages": (page,)})
    with pytest.raises(ValueError, match="ENTITY_VERSION_MISMATCH"):
        _validate_output_g3(request, revised)


@pytest.mark.parametrize("direction", ["promote", "demote"])
def test_update_cannot_silently_change_article_into_relation(direction: str) -> None:
    from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
        validate_disposition_semantics,
    )

    request, output = compile_case()
    typed = output.pages[0]
    raw = typed.model_dump(mode="json")
    raw.pop("business_relation")
    ordinary = d.FreeWikiPage.model_validate(raw)
    old, new = (ordinary, typed) if direction == "promote" else (typed, ordinary)
    request = request.model_copy(update={"existing_pages": (old,)})
    output = output.model_copy(
        update={
            "pages": (new,),
            "audit": tuple(
                row.model_copy(update={"disposition": "update"})
                if row.key == free_page_id(new)
                else row
                for row in output.audit
            ),
        }
    )
    with pytest.raises(ValueError, match="RELATION_MEMBER_TYPE_CHANGED"):
        list(validate_disposition_semantics(request, output))
