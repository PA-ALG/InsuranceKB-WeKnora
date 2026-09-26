"""Normal native relation admission; synthetic data checks custody, not semantic quality."""

import hashlib
from copy import deepcopy
from typing import Any

import pytest

from insurance_harness.product_ingestion.native_admission_context import (
    render_native_admission_context,
)
from insurance_harness.product_ingestion.native_admission_contract import (
    NativeAdmissionResponseV2,
)
from insurance_harness.product_ingestion.native_admission_preflight import (
    preflight_native_admission_response,
)
from insurance_harness.product_ingestion.stages import json_bytes
from tests.product_ingestion.test_native_admission_wire import wire_sample

pytest_plugins = ("tests.product_ingestion.test_discovery",)
PROTOCOL = "native-knowledge-admission.830.v4"
CAPABILITY = "product-concept-relation.830.v1"


def relation_sample(case: Any) -> tuple[Any, ...]:
    request, entity, snapshot, source, old_context, payload = wire_sample(case)
    context = render_native_admission_context(
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        dependency_policy=old_context["dependency_policy"],
        isolation_enabled=True,
        relation_capability=CAPABILITY,
    )
    page = payload["pages"][0]
    definition = {
        k: deepcopy(page[k])
        for k in (
            "member_ref",
            "action",
            "expected_revision_sha256",
            "title",
            "body",
            "content_provenance",
            "audit_reason",
        )
    }
    definition.update(
        member_ref="d1", canonical_key="advance_payment_category", sense_key="insurance", aliases=[]
    )
    payload["definitions"] = [definition]
    payload["contract"] = PROTOCOL
    page.update(
        stable_key="$relation",
        concept_refs=["d1"],
        relation={
            "predicate": "benefit_reduced_by_advance_payment",
            "object_ref": "d1",
        },
    )
    payload["decisions"][0]["member_refs"].append("d1")
    return request, entity, snapshot, source, context, payload


def run_relation(values: tuple[Any, ...], protocol: str = PROTOCOL) -> Any:
    request, entity, snapshot, source, context, payload = values
    return preflight_native_admission_response(
        raw=json_bytes(payload),
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        context=context,
        wire_protocol=protocol,
    )


def test_v4_binds_real_concept_revision_and_server_identity(case: Any) -> None:
    from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import definition_sha256_830_g3
    from insurance_harness.knowledge_compiler.concept_compile_830_g2 import free_page_id
    from insurance_harness.knowledge_compiler.product_concept_relation import relation_stable_key
    from insurance_harness.product_ingestion.native_dependency_selection import (
        validate_dependency_selection,
    )

    values = relation_sample(case)
    outcome = run_relation(values)
    assert outcome.failure is None
    projected = outcome.projection
    page, definition = projected.output.pages[0], projected.output.definitions[0]
    relation = page.business_relation
    assert relation.object_concept_id == definition.concept_id
    assert relation.object_definition_sha256 == definition_sha256_830_g3(definition)
    assert page.stable_key == relation_stable_key(page.space_id, page.entity_id, relation)
    assert page.entity_version == values[4]["entity"]["entity_version"]
    assert page.evidence[0].quote == values[3].blocks[0].text
    assert projected.dependency_selection["admission_context"]["relation_capability"] == CAPABILITY
    validate_dependency_selection(
        projected.dependency_selection,
        {free_page_id(page), definition.concept_id},
        projected.output.request_hash,
    )
    assert outcome.receipt["wire_expansion"]["wire_protocol"] == PROTOCOL


@pytest.mark.parametrize(
    "fault", ["null", "unknown", "target", "stable", "refs", "generated", "capability", "legacy"]
)
def test_relation_proposal_fails_closed(case: Any, fault: str) -> None:
    values = relation_sample(case)
    page = values[-1]["pages"][0]
    if fault == "null":
        page["relation"] = None
    elif fault == "unknown":
        page["relation"]["subject"] = "forged"
    elif fault == "target":
        page["relation"]["object_ref"] = "advance_payment_category"
        page["concept_refs"] = ["advance_payment_category"]
    elif fault == "stable":
        page["stable_key"] = "model-picked-identity"
    elif fault == "refs":
        page["concept_refs"] = []
    elif fault == "generated":
        page["content_provenance"]["segments"][0].update(origin="MODEL_GENERATED", evidence_refs=[])
    elif fault == "capability":
        values[-2]["relation_capability"] = "unknown"
    else:
        values[-1]["contract"] = "native-knowledge-admission.830.v3"
    outcome = run_relation(values)
    assert outcome.projection is None and outcome.failure


def test_old_v2_schema_and_v3_acceptance_are_unchanged(case: Any) -> None:
    assert hashlib.sha256(
        json_bytes(NativeAdmissionResponseV2.model_json_schema())
    ).hexdigest() == ("df9c2951117196adb2146842edde279069c2d260e57abd21464d20a5d2e03a19")
    values = wire_sample(case)
    values[-1]["pages"][0]["relation"] = None
    outcome = run_relation(values, "native-knowledge-admission.830.v3")
    assert outcome.projection is None


def test_normal_review_includes_typed_relation_and_new_prompt(case: Any) -> None:
    from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
        compile_output_hash_g3,
    )
    from insurance_harness.product_ingestion.discovery import (
        build_discovery_exclusion_index,
        independent_discovery_review_policy,
        render_independent_discovery_review_context,
    )
    from insurance_harness.product_ingestion.native_relation_admission import PREDICATE_MEANING

    values = relation_sample(case)
    request, entity = values[:2]
    result = run_relation(values).projection
    assert result is not None
    purpose, prompt = independent_discovery_review_policy(result.output, dependency_selection=True)
    assert purpose == "g3-relation-discovery-review"
    assert PREDICATE_MEANING.encode() in prompt
    candidates = {
        "output": result.output.model_dump(mode="json"),
        "sources": values[-2]["source_options"],
        "dispositions": result.dispositions,
        "dependency_selection": result.dependency_selection,
    }

    def render(**extra: Any) -> Any:
        return render_independent_discovery_review_context(
            request=request,
            entity_id=entity,
            exclusion_index=build_discovery_exclusion_index(request, entity),
            discovery_candidates=candidates,
            final_composed_output=result.output,
            final_composed_output_hash=compile_output_hash_g3(result.output),
            **extra,
        )

    context = render()
    assert context["contract"] == "product-discovery-review-context.830.v9"
    assert context["relation_predicates"]["benefit_reduced_by_advance_payment"] == PREDICATE_MEANING
    page = next(row for row in context["candidate_members"] if "business_relation" in row)
    assert page["business_relation"] == result.output.pages[0].business_relation.model_dump(
        mode="json"
    )
    assert page["evidence"][0]["quote"] == values[3].blocks[0].text
    with pytest.raises(ValueError):
        render(context_version="product-discovery-review-context.830.v6")
    with pytest.raises(ValueError, match="unsupported"):
        render(context_version="product-discovery-review-context.830.v7")
    candidates.pop("dependency_selection")
    with pytest.raises(ValueError, match="relation.*selection"):
        render()


@pytest.mark.parametrize("fault", [None, "revision", "disabled", "ordinary", "version"])
def test_relation_content_update_keeps_identity_and_exact_revision(
    case: Any, fault: str | None
) -> None:
    from insurance_harness.knowledge_compiler.concept_compile_830_g2 import free_page_id

    values = relation_sample(case)
    first = run_relation(values).projection.output
    request, entity, snapshot, source, _, payload = values
    old = first.pages[0]
    if fault == "ordinary":
        old = old.model_copy(update={"business_relation": None})
    request = request.model_copy(
        update={
            "knowledge_update_policy": "explicit-same-identity.830.v1",
            "entity_bindings": tuple(
                b.model_copy(update={"entity_version": b.entity_version + "-next"})
                if b.entity_id == entity and fault == "version"
                else b
                for b in request.entity_bindings
            ),
            "base_request": request.base_request.model_copy(
                update={"existing_pages": (old,), "existing_definitions": first.definitions}
            ),
        }
    )
    if fault == "disabled":
        request = request.model_copy(update={"knowledge_update_policy": None})
    ctx = render_native_admission_context(
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        dependency_policy="candidate-dependencies.830.v1",
        isolation_enabled=True,
        relation_capability=CAPABILITY,
    )
    payload["definitions"] = []
    row = payload["pages"][0]
    row["body"] += "修订说明"
    row["content_provenance"]["segments"][0]["text"] = row["body"]
    row.update(
        action="UPDATE",
        concept_refs=[first.definitions[0].concept_id],
        expected_revision_sha256="0" * 64
        if fault == "revision"
        else ctx["existing_knowledge"]["pages"][0]["revision_sha256"],
    )
    row["relation"]["object_ref"] = first.definitions[0].concept_id
    payload["decisions"][0].update(decision="UPDATE", member_refs=[row["member_ref"]])
    outcome = run_relation((request, entity, snapshot, source, ctx, payload))
    if fault:
        assert outcome.projection is None and outcome.failure
    else:
        assert outcome.failure is None
        page = outcome.projection.output.pages[0]
        assert free_page_id(page) == free_page_id(old)
        assert page.entity_version == old.entity_version
        assert outcome.projection.output.audit[0].disposition == "update"


def test_relation_projection_requires_complete_dependency_domain(case: Any) -> None:
    request, entity, snapshot, source, _, payload = relation_sample(case)
    context = render_native_admission_context(request=request, entity_id=entity, snapshot=snapshot,
        source=source, dependency_policy="candidate-dependencies.830.v1", isolation_enabled=False,
        relation_capability=CAPABILITY)
    outcome = run_relation((request, entity, snapshot, source, context, payload))
    assert outcome.projection is None and outcome.failure
