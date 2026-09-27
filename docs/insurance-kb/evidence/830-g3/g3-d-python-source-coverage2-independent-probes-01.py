from __future__ import annotations

import hashlib
import json
from pathlib import Path

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as d
from insurance_harness.knowledge_compiler import concept_compile_830_g2 as g2
from insurance_harness.knowledge_compiler import concept_free_wiki_830_g2 as concept


ROOT = Path("/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation")
CANDIDATE = ROOT / "harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json"
PREP = ROOT / "harness/tests/fixtures/batch_concept_compile_830_g3/preparation-request.json"

bundle = d.validate_batch_candidate(CANDIDATE.read_bytes())
request = bundle.request
base = request.base_request
corpus = request.resolution_inputs.corpus

selected = {
    material_id
    for binding in request.entity_bindings
    for material_id in binding.source_material_ids
}
expected = {
    (block.revision_id, block.block_id)
    for entry in corpus.entries
    if entry.material_id in selected
    for block in entry.blocks
}
members = (*base.existing_definitions, *base.existing_fields, *base.existing_pages)
expected.update(
    (evidence.revision_id, evidence.block_id)
    for member in members
    for evidence in member.evidence
)
actual = {(block.revision_id, block.block_id) for block in base.sources}
assert actual == expected and len(actual) == len(base.sources) == 27

field_evidence = next(
    evidence
    for proposal in request.resolution_inputs.proposals.proposals
    for evidence in proposal.evidence
    if evidence.purpose == "field"
)
field_key = (field_evidence.evidence.revision_id, field_evidence.evidence.block_id)
identity_keys = {
    (bound.evidence.revision_id, bound.evidence.block_id)
    for binding in request.entity_bindings
    for bound in binding.resolution_evidence
}
assert field_key in actual and field_key not in identity_keys
assert any(
    field.field_key == field_evidence.field_key
    and field.evidence == (field_evidence.evidence,)
    for field in bundle.model_compile_result.output.fields
)

field_block = next(
    block for block in base.sources
    if (block.revision_id, block.block_id) == field_key
)

def closure_reason(changed_sources: tuple[object, ...]) -> str:
    try:
        d._validate_request_closure(
            request.model_copy(
                update={"base_request": base.model_copy(update={"sources": changed_sources})}
            )
        )
    except d.BatchConceptCompileError as exc:
        return exc.reason_code
    raise AssertionError("closure mutation was accepted")


missing_reason = closure_reason(tuple(block for block in base.sources if block != field_block))
extra = field_block.model_copy(
    update={"block_id": field_block.block_id + "-foreign", "text": "foreign"}
)
extra_reason = closure_reason(
    tuple(sorted((*base.sources, extra), key=lambda block: (block.revision_id, block.block_id)))
)
different = field_block.model_copy(update={"text": field_block.text + "\nchanged"})
different_reason = closure_reason(
    tuple(different if block == field_block else block for block in base.sources)
)
assert {missing_reason, extra_reason, different_reason} == {"SOURCE_CLOSURE_MISMATCH"}

definitions = {item.concept_id: item for item in base.existing_definitions}
linked_checks = 0
linked_example = None
for owner in base.existing_entity_versions:
    owner_members = tuple(
        item for item in (*base.existing_fields, *base.existing_pages)
        if item.entity_id == owner
    )
    linked = {concept_id for item in owner_members for concept_id in item.concept_ids}
    allowed_definition_keys = {
        (evidence.revision_id, evidence.block_id)
        for concept_id in linked
        if concept_id in definitions
        for evidence in definitions[concept_id].evidence
    }
    assert allowed_definition_keys.issubset(actual)
    linked_checks += len(allowed_definition_keys)
    if linked_example is None and allowed_definition_keys:
        linked_key = next(iter(allowed_definition_keys))
        linked_definition = next(
            definition
            for concept_id in linked
            if (definition := definitions.get(concept_id)) is not None
            if any(
                (evidence.revision_id, evidence.block_id) == linked_key
                for evidence in definition.evidence
            )
        )
        linked_example = (owner, linked_definition.evidence[0])

assert linked_example is not None
linked_owner, linked_evidence = linked_example
linked_page = concept.FreeWikiPage(
    space_id=base.space_id,
    entity_id=linked_owner,
    stable_key="independent-linked-definition-source",
    title="Linked definition source probe",
    body="Synthetic protocol probe.",
    evidence=(linked_evidence,),
    entity_version=base.entity_versions[linked_owner],
)
linked_output = bundle.model_compile_result.output.model_copy(
    update={
        "pages": (linked_page,),
        "audit": tuple(sorted(
            (*bundle.model_compile_result.output.audit,
             g2.AuditDisposition(
                 key=g2.free_page_id(linked_page),
                 disposition="new_page",
                 reason="INDEPENDENT_LINKED_DEFINITION_SOURCE_PROBE",
             )),
            key=lambda item: item.key,
        )),
    }
)
linked_result = d.record_model_compile(
    request,
    linked_output,
    run_id="independent-linked-definition-run",
    implementation="independent-static-probe",
    raw=d._canonical_json(linked_output),
)
d.validate_delta_output(request, linked_result)

raw_hashes = {
    hashlib.sha256(value.encode()).hexdigest()
    for value in (
        bundle.model_compile_result.execution.raw_output,
        bundle.compile_result.execution.raw_output,
        bundle.review_result.execution.raw_output,
    )
}
assert len(raw_hashes) == 3
assert len(bundle.request.base_request.existing_fields) == 134
assert len(d.aligned_existing_fields(request)) == 134
assert len(bundle.model_compile_result.output.fields) == 208
assert len(bundle.compile_result.output.fields) == 342
assert len(PREP.read_bytes()) == 2_254_490 < 8 * 1024 * 1024

print(json.dumps({
    "status": "PASS",
    "source_union": {"selected_materials": len(selected), "blocks": len(actual)},
    "field_block_not_identity_block": True,
    "closure_rejections": {
        "missing": missing_reason,
        "extra": extra_reason,
        "same_identity_different_bytes": different_reason,
    },
    "linked_definition_source_checks": linked_checks,
    "linked_definition_delta": "PASS",
    "field_counts": {"base": 134, "aligned_total": 134, "delta": 208, "final": 342},
    "raw_contexts": 3,
    "preparation_bytes": len(PREP.read_bytes()),
    "effects": 0,
}, ensure_ascii=False, sort_keys=True))
