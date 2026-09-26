"""Protocol-only fixture through existing G3 composition and independent review.

Scores/content are synthetic test inputs, never provider or semantic-quality evidence.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache

import pytest

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as g3
from insurance_harness.knowledge_compiler import concept_compile_830_g2 as g2
from insurance_harness.knowledge_compiler import concept_free_wiki_830_g2 as d
from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import (
    batch_json_bytes_830_g3,
    batch_sha256_830_g3,
    definition_sha256_830_g3,
)
from insurance_harness.knowledge_compiler.product_concept_relation import (
    ProductConceptRelation,
    relation_stable_key,
)
from tests.test_batch_concept_compile_830_g3 import G3_FIXTURE


@lru_cache(maxsize=1)
def relation_bundle() -> g3.BatchConceptCandidateBundle830G3V1:
    original = g3.validate_batch_candidate(G3_FIXTURE.read_bytes())
    request = original.request
    field = next(f for f in original.model_compile_result.output.fields if f.evidence)
    evidence = field.evidence[0]
    definition = d.ConceptDefinition(
        space_id=field.space_id,
        canonical_key="relation-protocol-fixture",
        sense_key="category",
        title="协议测试概念（非语义验收）",
        body=evidence.quote,
        evidence=(evidence,),
    )
    relation = ProductConceptRelation(
        contract="product-concept-relation.830.v1",
        subject_type="PRODUCT",
        object_type="CONCEPT",
        predicate="benefit_reduced_by_advance_payment",
        object_concept_id=definition.concept_id,
        object_definition_sha256=definition_sha256_830_g3(definition),
    )
    page = d.FreeWikiPage(
        space_id=field.space_id,
        entity_id=field.entity_id,
        entity_version=field.entity_version,
        stable_key=relation_stable_key(field.space_id, field.entity_id, relation),
        title="关系协议测试（非语义验收）",
        body=evidence.quote,
        evidence=(evidence,),
        concept_ids=(definition.concept_id,),
        business_relation=relation,
        content_provenance=d.KnowledgeContentProvenance(
            contract="knowledge-content-provenance.830.v1",
            segments=(
                d.KnowledgeContentSegment(
                    text=evidence.quote, origin="SOURCE_SUPPORTED", evidence_indexes=(0,)
                ),
            ),
        ),
    )
    delta = original.model_compile_result.output.model_copy(
        update={
            "definitions": (*original.model_compile_result.output.definitions, definition),
            "pages": (*original.model_compile_result.output.pages, page),
            "audit": (
                *original.model_compile_result.output.audit,
                g2.AuditDisposition(
                    key=definition.concept_id, disposition="new_page", reason="protocol fixture"
                ),
                g2.AuditDisposition(
                    key=g2.free_page_id(page), disposition="new_page", reason="protocol fixture"
                ),
            ),
        }
    )
    model = g3.record_model_compile(
        request,
        delta,
        run_id="relation-model-fixture",
        implementation="protocol-fixture",
        raw=batch_json_bytes_830_g3(delta).decode(),
    )
    composed = g3.compose_batch_output(request, model)
    compiled = g3.record_composed_output(
        request, model, composed, run_id="relation-composition-fixture"
    )
    score = g2.ValueScore(
        business_value=25,
        reuse=20,
        evidence_quality=20,
        definability=15,
        novel_identity=10,
        name_stability=10,
    )
    reviewed = g2.ReviewOutput(
        request_hash=g3.compile_request_hash_g3(request.base_request),
        output_hash=g3.compile_output_hash_g3(composed),
        decision="PASS",
        page_scores={key: score for key in g3.changed_knowledge_member_ids(request, composed)},
    )
    raw = batch_json_bytes_830_g3(reviewed).decode()
    review = g2.ReviewResult(
        output=reviewed,
        execution=g2.ExecutionRecord(
            run_id="relation-review-fixture",
            implementation="independent-protocol-fixture",
            raw_output=raw,
            raw_output_hash=hashlib.sha256(raw.encode()).hexdigest(),
            context_hash=batch_sha256_830_g3(
                "batch-concept-review-context.830.g3.v1", g3.review_context_g3(request, composed)
            ),
        ),
    )
    return g3.assemble_candidate_bundle(
        request, model, compiled, review, g3.knowledge_admission_g3(request, composed, reviewed)
    )


def test_relation_roundtrips_complete_candidate_and_manifest() -> None:
    bundle = relation_bundle()
    assert g3.validate_batch_candidate(batch_json_bytes_830_g3(bundle)) == bundle
    relations = [m for m in bundle.page_manifest.members if m.payload.get("business_relation")]
    assert len(relations) == 1
    assert relations[0].kind == "free_wiki_item"
    assert relations[0].member_id in bundle.review_result.output.page_scores


def test_relation_changes_cannot_reuse_the_old_final_review() -> None:
    bundle = relation_bundle()
    output = bundle.compile_result.output
    pages = list(output.pages)
    index = next(i for i, p in enumerate(pages) if p.business_relation)
    old = pages[index]
    body = old.body + "修订内容"
    pages[index] = d.FreeWikiPage.model_validate(
        {
            **old.model_dump(mode="json"),
            "body": body,
            "content_provenance": {
                "contract": "knowledge-content-provenance.830.v1",
                "segments": [
                    {"text": body, "origin": "SOURCE_SUPPORTED", "evidence_indexes": [0]},
                ],
            },
        }
    )
    changed = output.model_copy(update={"pages": tuple(pages)})
    assert g3.compile_output_hash_g3(changed) != bundle.review_result.output.output_hash
    with pytest.raises(ValueError):
        g3.assemble_candidate_bundle(
            bundle.request,
            bundle.model_compile_result,
            bundle.compile_result.model_copy(update={"output": changed}),
            bundle.review_result,
            bundle.admission,
        )
