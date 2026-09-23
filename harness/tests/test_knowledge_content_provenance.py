from __future__ import annotations

from typing import Any

import pytest

from insurance_harness.knowledge_compiler import concept_free_wiki_830_g2 as domain


def page() -> dict[str, Any]:
    return dict(
        space_id="space",
        entity_id="entity",
        stable_key="reading-guide",
        title="阅读提示",
        body="这是一段模型补充说明。",
        evidence=[],
        entity_version="v1",
        content_provenance={
            "contract": "knowledge-content-provenance.830.v1",
            "segments": [
                {
                    "text": "这是一段模型补充说明。",
                    "origin": "MODEL_GENERATED",
                    "evidence_indexes": [],
                }
            ],
        },
    )


def test_explicit_model_generated_page_keeps_supplement_without_fake_evidence() -> None:
    value = domain.FreeWikiPage.model_validate(page())
    assert value.evidence == ()
    assert (
        value.model_dump(mode="json")["content_provenance"]["segments"][0]["origin"]
        == "MODEL_GENERATED"
    )


def test_explicit_model_generated_definition_has_content_provenance_in_hash() -> None:
    value = page()
    for key in ("entity_id", "stable_key", "entity_version"):
        value.pop(key)
    value.update(canonical_key="reading-guide", sense_key="general", origin="MODEL_COMPILE")
    result = domain.ConceptDefinition.model_validate(value)
    assert result.evidence == ()
    changed = result.model_dump(mode="json")
    changed["body"] += "新内容"
    changed["content_provenance"]["segments"][0]["text"] += "新内容"
    assert (
        domain.ConceptDefinition.model_validate(changed).definition_hash != result.definition_hash
    )


@pytest.mark.parametrize(
    "mutation", ["missing", "null", "gap", "fake_source", "unknown_origin", "empty"]
)
def test_generation_label_cannot_bypass_content_or_source_binding(mutation: str) -> None:
    value = page()
    if mutation == "missing":
        value.pop("content_provenance")
    elif mutation == "null":
        value["content_provenance"] = None
    elif mutation == "gap":
        value["body"] += "无来源额外正文"
    elif mutation == "fake_source":
        value["content_provenance"]["segments"][0]["origin"] = "SOURCE_SUPPORTED"
    elif mutation == "unknown_origin":
        value["content_provenance"]["segments"][0]["origin"] = "VERIFIED"
    else:
        value["content_provenance"]["segments"] = []
    with pytest.raises(ValueError):
        domain.FreeWikiPage.model_validate(value)


@pytest.mark.parametrize("transformation", ["EXTRACT", "NORMALIZE", "COMPRESS"])
def test_generated_content_requires_synthesize(transformation: str) -> None:
    from insurance_harness.knowledge_compiler.concept_compile_830_g2 import CompileOutput

    with pytest.raises(ValueError, match="GENERATED_CONTENT_REQUIRES_SYNTHESIZE"):
        CompileOutput.model_validate(
            dict(request_hash="a" * 64, fields=[], pages=[page()], transformation=transformation)
        )


def test_mixed_content_covers_conditions_and_all_evidence_without_invented_source() -> None:
    source = domain.SourceBlock(
        tenant_id=1,
        space_id="space",
        raw_kb_id="raw",
        knowledge_id="doc",
        parse_attempt=1,
        revision_id="revision",
        source_hash="a" * 64,
        parse_hash="b" * 64,
        parser_identity="parser",
        block_id="block",
        page_number=2,
        text="原文内容",
        source_type="DOCUMENT",
    )
    value = page()
    value.update(
        body="原文内容。模型说明。",
        conditions=["阅读建议"],
        evidence=[domain.evidence_for(source, 0, 4).model_dump(mode="json")],
    )
    value["content_provenance"]["segments"] = [
        dict(text="原文内容。", origin="SOURCE_SUPPORTED", evidence_indexes=[0]),
        dict(text="模型说明。\n条件：阅读建议", origin="MODEL_GENERATED", evidence_indexes=[]),
    ]
    result = domain.FreeWikiPage.model_validate(value)
    assert domain.FreeWikiPage.model_validate(result) == result
    value["content_provenance"]["segments"][1]["text"] = "模型说明。"
    with pytest.raises(ValueError, match="COVERAGE_MISMATCH"):
        domain.FreeWikiPage.model_validate(value)


def test_explicit_null_rejected_for_valid_legacy_and_copied_models() -> None:
    import json
    from pathlib import Path

    vector = json.loads(
        (
            Path(__file__).parent / "fixtures/concept_free_wiki_830_g2_contract_vector.json"
        ).read_text()
    )
    payload = next(
        m["payload"] for m in vector["page_manifest"]["members"] if m["kind"] == "concept"
    )
    legacy = domain.ConceptDefinition.model_validate(payload)
    assert "content_provenance" not in domain.ConceptDefinition.model_validate(legacy).model_dump()
    with pytest.raises(ValueError, match="EMPTY_CONTENT_PROVENANCE"):
        domain.ConceptDefinition.model_validate({**payload, "content_provenance": None})
    with pytest.raises(ValueError, match="EMPTY_CONTENT_PROVENANCE"):
        domain.ConceptDefinition.model_validate(
            legacy.model_copy(update={"content_provenance": None})
        )


def build_content_bundle() -> Any:
    import hashlib

    from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
    from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
        CompileOutput,
        free_page_id,
    )
    from tests.test_batch_concept_compile_830_g3_updates import build_update_bundle

    bundle = build_update_bundle()
    data = bundle.model_compile_result.output.model_dump(mode="json")
    definition = data["definitions"][0]
    definition["content_provenance"] = dict(
        contract="knowledge-content-provenance.830.v1",
        segments=[
            dict(
                text=definition["body"][:-6],
                origin="SOURCE_SUPPORTED",
                evidence_indexes=list(range(len(definition["evidence"]))),
            ),
            dict(text=definition["body"][-6:], origin="MODEL_GENERATED", evidence_indexes=[]),
        ],
    )
    page_data = data["pages"][0]
    page_data["body"] = "模型补充阅读建议：先核对适用条件。\ne\u0301\uf99c"
    page_data["conditions"] = ["供阅读参考"]
    page_data["exceptions"] = ["原文另有规定时以原文为准"]
    page_data["valid_time"] = ""
    page_data["evidence"] = []
    # Explicit full renderer, including metadata, without claiming invented evidence.
    text = "\n".join([page_data["body"], "条件：供阅读参考", "例外：原文另有规定时以原文为准"])
    page_data["content_provenance"] = dict(
        contract="knowledge-content-provenance.830.v1",
        segments=[dict(text=text, origin="MODEL_GENERATED", evidence_indexes=[])],
    )
    data["transformation"] = "SYNTHESIZE"
    output = CompileOutput.model_validate(data)
    delta = compiler.record_model_compile(
        bundle.request,
        output,
        run_id="synthetic-content",
        implementation="fixture-only",
        raw=compiler._canonical_json(output),
    )
    final = compiler.compose_batch_output(bundle.request, delta)
    composed = compiler.record_composed_output(
        bundle.request, delta, final, run_id="synthetic-content-composition"
    )
    review_data = bundle.review_result.output.model_dump(mode="json")
    review_data["output_hash"] = compiler.compile_output_hash_g3(final)
    review_data["page_scores"][free_page_id(output.pages[0])]["evidence_quality"] = 0
    review_output = type(bundle.review_result.output).model_validate(review_data)
    raw = compiler._canonical_json(review_output)
    review = bundle.review_result.model_copy(
        update=dict(
            output=review_output,
            execution=bundle.review_result.execution.model_copy(
                update=dict(
                    raw_output=raw,
                    raw_output_hash=hashlib.sha256(raw.encode()).hexdigest(),
                    context_hash=compiler._batch_sha256(
                        "batch-concept-review-context.830.g3.v1",
                        compiler.review_context_g3(bundle.request, final),
                    ),
                )
            ),
        )
    )
    return compiler.assemble_candidate_bundle(
        bundle.request, delta, composed, review, bundle.admission
    )


def test_generated_and_mixed_candidate_cross_language_fixture() -> None:
    import gzip
    import os
    from pathlib import Path

    from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler

    bundle = build_content_bundle()
    raw = compiler._canonical_json(bundle).encode()
    fixture = (
        Path(__file__).parent
        / "fixtures/batch_concept_compile_830_g3/content-provenance-candidate.json.gz"
    )
    if os.environ.get("UPDATE_CONTENT_PROVENANCE_FIXTURE") == "1":
        fixture.write_bytes(gzip.compress(raw, mtime=0))
    assert raw == gzip.decompress(fixture.read_bytes())
    assert compiler.validate_batch_candidate(raw) == bundle


def test_carried_generated_content_keeps_synthesize_in_final_output() -> None:
    from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
    from tests.test_batch_concept_compile_830_g3_updates import original

    bundle = original()
    from tests.test_batch_concept_compile_830_g3 import _published_g3_base

    base = _published_g3_base(compiler)
    old = base.existing_pages[0]
    data = old.model_dump(mode="json")
    data["content_provenance"] = dict(
        contract="knowledge-content-provenance.830.v1",
        segments=[
            dict(text=domain.free_page_content(old), origin="MODEL_GENERATED", evidence_indexes=[])
        ],
    )
    data["evidence"] = []
    generated = domain.FreeWikiPage.model_validate(data)
    base = base.model_copy(update={"existing_pages": (generated, *base.existing_pages[1:])})
    # Focus on the composition boundary with a published base and an empty delta.
    request = bundle.request.model_copy(
        update=dict(base_request=base, unknown_field_key_alignments=())
    )
    output = compiler.CompileOutput(request_hash=compiler.compile_request_hash_g3(base), fields=())
    assert output.transformation == "EXTRACT"
    delta = compiler.record_model_compile(
        request,
        output,
        run_id="carry-test",
        implementation="fixture-only",
        raw=compiler._canonical_json(output),
    )
    final = compiler.compose_batch_output(request, delta)
    assert final.transformation == "SYNTHESIZE"
