from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import CompileOutput

MODULE = "insurance_harness.product_ingestion.discovery"


def adapter():
    assert importlib.util.find_spec(MODULE) is not None, "durable discovery adapter is missing"
    return importlib.import_module(MODULE)


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


@pytest.fixture(scope="module")
def case():
    path = Path(__file__).parents[1] / "fixtures/batch_concept_compile_830_g3/candidate.json"
    candidate = compiler.validate_batch_candidate(path.read_bytes())
    request = candidate.request
    original = candidate.model_compile_result.output
    fields = original.fields
    ids = {field.assertion_id for field in fields}
    output = CompileOutput(
        request_hash=original.request_hash,
        fields=fields,
        audit=tuple(row for row in original.audit if row.key in ids),
    )
    delta = compiler.record_model_compile(
        request,
        output,
        run_id="discovery-fixture-fields",
        implementation="fixture-extract",
        raw=compiler._canonical_json(output),
    )
    return request, delta, fields[0].entity_id


def prepared(case):
    module = adapter()
    request, delta, entity = case
    context = module.render_discovery_context(request=request, field_delta=delta, entity_id=entity)
    offered = context["source_options"][0]
    quote = offered["spans"][0]["quote"][:35]
    selection = {"source_ref": offered["source_ref"], "quote": quote}
    reference = context["window"]["entity_ref"]
    envelope = {
        "contract": "product-discovery-proposal.830.v1",
        "proposal": {
            "contract": "g3-d-compile-semantic-references.local.v1",
            "transformation": "SYNTHESIZE",
            "definitions": [],
            "fields": [],
            "pages": [
                {
                    "page_ref": "new-rule",
                    "entity_ref": reference,
                    "stable_key": "independent-process",
                    "title": "独立办理流程",
                    "body": "办理流程说明：" + quote,
                    "evidence": [selection],
                    "concept_refs": [],
                    "conditions": [],
                    "exceptions": [],
                    "valid_time": "",
                    "audit_reason": "A separate actionable process.",
                }
            ],
        },
        "dispositions": [
            {
                "candidate_id": "candidate-rule",
                "disposition": "PROPOSED_NEW",
                "text": "办理流程说明：" + quote,
                "evidence": [selection],
                "reason": "Independent process beyond the supplied field inventory.",
                "business_use": "Guide a user through this separate process.",
                "member_ref": "new-rule",
                "existing_target": None,
            }
        ],
    }
    return module, request, delta, context, envelope


def project(case, mutate=None):
    module, request, delta, context, proposal = prepared(case)
    if mutate:
        mutate(proposal)
    projection = module.project_discovery_response(
        raw=wire(proposal),
        request=request,
        field_delta=delta,
        context=context,
        run_id="discovery-fixture",
    )
    return module, request, delta, context, projection


def checked(case, *, score=100, decision="PASS", checks="ACCEPT", mutate=None):
    module, request, delta, generation, projection = project(case)
    context = module.render_discovery_review_context(
        request=request,
        field_delta=delta,
        projection=projection,
        context=generation,
    )
    scores = {
        "business_value": 25,
        "reuse": 20,
        "evidence_quality": 20,
        "definability": 15,
        "novel_identity": 10,
        "name_stability": 10,
    }
    scores["business_value"] -= 100 - score if score >= 75 else 25
    if score < 75:
        scores["reuse"] -= 75 - score
    review = {
        "contract": "product-discovery-review.830.v1",
        "review": {
            "contract": "concept-review-output.830.g2.v1",
            "request_hash": context["request_hash"],
            "output_hash": context["output_hash"],
            "decision": decision,
            "reasons": ["Checked independent use and exact evidence."],
            "page_scores": {key: scores for key in context["review_member_ids"]},
        },
        "disposition_checks": [
            {
                "candidate_id": "candidate-rule",
                "decision": checks,
                "reason": "Checked comparison and proposed placement.",
            }
        ],
    }
    if mutate:
        mutate(review)
    result = module.project_discovery_review(
        raw=wire(review),
        request=request,
        projection=projection,
        context=context,
    )
    return result, projection, context


def test_context_contains_current_and_inherited_members_schema_and_exact_coverage(case):
    module, request, delta, context, _ = prepared(case)
    comparisons = context["comparison"]
    assert comparisons["current_fields"]
    assert all(row["entity_id"] == case[2] for row in comparisons["current_fields"])
    assert comparisons["schema_fields"]
    assert {"description", "source_guidance", "value_spec"} <= comparisons["schema_fields"][
        0
    ].keys()
    assert "inherited_fields" in comparisons and "inherited_pages" in comparisons
    assert context["coverage"]["offered_chars"] <= 24000
    assert all("text" not in row["source"] for row in context["source_options"])
    assert len(wire(context)) <= 262144
    assert isinstance(module.DISCOVERY_PROMPT, bytes)
    assert isinstance(module.DISCOVERY_REVIEW_PROMPT, bytes)
    assert compiler.compose_batch_output(request, delta).fields


def test_duplicate_noise_and_update_are_retained_audit_only(case):
    def mutate(proposal):
        module, request, delta, context, _ = prepared(case)
        target = delta.output.fields[0].assertion_id
        for candidate, disposition, existing in [
            ("duplicate", "DUPLICATE", target),
            ("noise", "REJECT", None),
            ("update", "UPDATE_PROPOSAL", target),
        ]:
            proposal["dispositions"].append(
                dict(
                    candidate_id=candidate,
                    disposition=disposition,
                    text="Candidate retained for explicit disposition",
                    evidence=proposal["dispositions"][0]["evidence"] if existing else [],
                    reason="Explicit non-publication disposition",
                    business_use="",
                    member_ref=None,
                    existing_target=existing,
                )
            )

    _, request, delta, _, projection = project(case, mutate)
    assert len(projection.proposal.dispositions) == 4
    assert len(projection.new_output.pages) == 1
    assert projection.merged_delta.output.fields == delta.output.fields
    assert projection.composed_output.fields == compiler.compose_batch_output(request, delta).fields
    assert len(projection.composed_output.pages) == len(request.base_request.existing_pages) + 1


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda p: p["proposal"]["pages"][0].update(entity_ref="foreign"), "entity"),
        (lambda p: p["proposal"]["pages"][0]["evidence"][0].update(quote="NOT OFFERED"), "offered"),
        (lambda p: p["dispositions"][0].update(business_use=""), "business"),
        (lambda p: p["dispositions"][0].update(member_ref="missing"), "member"),
    ],
)
def test_generation_rejects_foreign_unsupported_or_unmatched_new_members(case, change, match):
    with pytest.raises(ValueError, match=match):
        project(case, change)


def test_generation_context_cannot_change_evidence_scope(case):
    module, request, delta, context, proposal = prepared(case)
    context["source_options"][0]["spans"][0]["quote"] = "forged"
    with pytest.raises(ValueError, match="context"):
        module.project_discovery_response(
            raw=wire(proposal),
            request=request,
            field_delta=delta,
            context=context,
            run_id="bad-context",
        )


def test_accepted_review_binds_actual_composed_output_and_comparison(case):
    result, projection, context = checked(case)
    assert result.state == "ACCEPTED"
    assert result.review.output_hash == compiler.compile_output_hash_g3(projection.composed_output)
    assert context["generation_context"]["comparison"]["current_fields"]
    assert context["dispositions"]
    assert projection.raw and result.raw


@pytest.mark.parametrize(
    "score,decision,expected",
    [
        (79, "PASS", "PENDING"),
        (59, "PASS", "REJECTED"),
        (100, "NEEDS_HUMAN", "PENDING"),
        (100, "REJECT", "REJECTED"),
    ],
)
def test_nonaccepted_group_is_retained_without_pruning_or_altering_fields(
    case, score, decision, expected
):
    result, projection, _ = checked(case, score=score, decision=decision)
    assert result.state == expected
    assert len(projection.new_output.pages) == 1
    assert projection.merged_delta.output.fields == case[1].output.fields


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda r: r["review"].update(output_hash="f" * 64), "binding"),
        (lambda r: r["review"].update(page_scores={}), "score coverage"),
        (lambda r: r["disposition_checks"].clear(), "disposition coverage"),
    ],
)
def test_review_rejects_stale_hash_or_incomplete_coverage(case, change, match):
    with pytest.raises(ValueError, match=match):
        checked(case, mutate=change)


def test_empty_is_only_a_successfully_parsed_and_reviewed_empty_group(case):
    module, request, delta, generation, proposal = prepared(case)
    proposal["proposal"]["pages"] = []
    proposal["dispositions"] = []
    projection = module.project_discovery_response(
        raw=wire(proposal),
        request=request,
        field_delta=delta,
        context=generation,
        run_id="empty-discovery",
    )
    context = module.render_discovery_review_context(
        request=request, field_delta=delta, projection=projection, context=generation
    )
    response = dict(
        contract="product-discovery-review.830.v1",
        review=dict(
            contract="concept-review-output.830.g2.v1",
            request_hash=context["request_hash"],
            output_hash=context["output_hash"],
            decision="PASS",
            reasons=["No independent finding."],
            page_scores={},
        ),
        disposition_checks=[],
    )
    result = module.project_discovery_review(
        raw=wire(response), request=request, projection=projection, context=context
    )
    assert result.state == "EMPTY"
    with pytest.raises(ValueError):
        module.project_discovery_response(
            raw=b"broken JSON",
            request=request,
            field_delta=delta,
            context=generation,
            run_id="failed",
        )


def test_duplicate_or_update_candidate_requires_source_evidence(case):
    def mutate(proposal):
        proposal["dispositions"].append(
            dict(
                candidate_id="unsupported-update",
                disposition="UPDATE_PROPOSAL",
                text="New alleged fact",
                evidence=[],
                reason="Would update a required field",
                business_use="",
                member_ref=None,
                existing_target=case[1].output.fields[0].assertion_id,
            )
        )

    with pytest.raises(ValueError, match="candidate evidence"):
        project(case, mutate)


def test_source_budget_does_not_spend_on_inherited_only_source_blocks(case):
    _, request, _, context, _ = prepared(case)
    binding = next(row for row in request.entity_bindings if row.entity_id == case[2])
    keys = {
        (b.revision_id, b.block_id)
        for entry in request.resolution_inputs.corpus.entries
        if entry.material_id in binding.source_material_ids
        for b in entry.blocks
    }
    assert all(
        (row["source"]["revision_id"], row["source"]["block_id"]) in keys
        for row in context["source_options"]
    )


def test_unresolved_disposition_keeps_whole_group_pending(case):
    result, projection, _ = checked(case, checks="NEEDS_HUMAN")
    assert result.state == "PENDING"
    assert len(projection.new_output.pages) == 1


def test_review_context_cannot_swap_comparison_inventory(case):
    module, request, delta, generation, projection = project(case)
    context = module.render_discovery_review_context(
        request=request, field_delta=delta, projection=projection, context=generation
    )
    context["generation_context"]["comparison"]["current_fields"] = []
    with pytest.raises(ValueError, match="review context"):
        module.project_discovery_review(
            raw=b"{}", request=request, projection=projection, context=context
        )


def test_caller_template_context_budget_above_default_is_honored():
    module = adapter()
    assert module._limit({"context": "small"}, 300000) == {"context": "small"}
    for invalid in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="context budget"):
            module._limit({}, invalid)


def test_update_only_result_is_pending_adapter_not_empty(case):
    module, request, delta, generation, proposal = prepared(case)
    selection = proposal["dispositions"][0]["evidence"]
    proposal["proposal"]["pages"] = []
    proposal["dispositions"] = [
        dict(
            candidate_id="update",
            disposition="UPDATE_PROPOSAL",
            text="A fact that belongs in the existing field",
            evidence=selection,
            reason="Supplement existing knowledge; adapter is not implemented",
            business_use="",
            member_ref=None,
            existing_target=delta.output.fields[0].assertion_id,
        )
    ]
    projection = module.project_discovery_response(
        raw=wire(proposal),
        request=request,
        field_delta=delta,
        context=generation,
        run_id="update-only",
    )
    context = module.render_discovery_review_context(
        request=request, field_delta=delta, projection=projection, context=generation
    )
    raw = wire(
        dict(
            contract="product-discovery-review.830.v1",
            review=dict(
                contract="concept-review-output.830.g2.v1",
                request_hash=context["request_hash"],
                output_hash=context["output_hash"],
                decision="PASS",
                reasons=["Valid update proposal"],
                page_scores={},
            ),
            disposition_checks=[
                dict(candidate_id="update", decision="ACCEPT", reason="Belongs in the field")
            ],
        )
    )
    decision = module.project_discovery_review(
        raw=raw, request=request, projection=projection, context=context
    )
    assert decision.state == "PENDING"
    assert "EXISTING_KNOWLEDGE_UPDATE_ADAPTER_REQUIRED" in decision.reasons
    assert projection.new_output.pages == ()
