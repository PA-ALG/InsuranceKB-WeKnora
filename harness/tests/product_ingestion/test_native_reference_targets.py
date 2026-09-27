"""The provider schema must expose the target identities the projector accepts."""

from copy import deepcopy
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from insurance_harness.product_ingestion.native_relation_wire import render_relation_wire_context
from insurance_harness.product_ingestion.stages import json_bytes
from tests.product_ingestion.test_native_relation_admission import relation_sample, run_relation

pytest_plugins = ("tests.product_ingestion.test_discovery",)


def test_version_identity_is_not_advertised_as_a_valid_reference(case: Any) -> None:
    values = relation_sample(case)
    context, payload = values[-2:]
    payload["pages"], payload["definitions"] = [], []
    payload["decisions"][0].update(
        decision="REFERENCE", member_refs=[], existing_target=context["entity"]["entity_version"]
    )
    schema = render_relation_wire_context(context)["response_schema"]
    assert not Draft202012Validator(schema).is_valid(payload)
    before = json_bytes(payload)
    assert run_relation(values).failure
    assert json_bytes(payload) == before


def test_catalog_matches_exact_context_targets_without_mutating_domain(case: Any) -> None:
    context = relation_sample(case)[-2]
    expected = {None, context["entity"]["entity_id"]}
    expected.update(row["concept_id"] for row in context["existing_knowledge"]["definitions"])
    expected.update(row["page_id"] for row in context["existing_knowledge"]["pages"])
    context["existing_knowledge"]["definitions"].append({"concept_id": "concept-a"})
    context["existing_knowledge"]["pages"].append({"page_id": "page-b"})
    before = deepcopy(context)
    wire = render_relation_wire_context(context)
    target = wire["response_schema"]["$defs"]["NativeAdmissionDecisionV2"]["properties"][
        "existing_target"
    ]
    assert set(target["enum"]) == expected | {"concept-a", "page-b"}
    assert context == before
    assert "entity_id" in target["description"]
    assert "entity_version" in target["description"]


@pytest.mark.parametrize(
    "decision", ["NEW", "UPDATE", "REJECT", "PENDING", "REQUIRES_ENTITY_RESOLUTION"]
)
def test_only_reference_can_select_an_existing_target(case: Any, decision: str) -> None:
    context, payload = relation_sample(case)[-2:]
    payload["decisions"][0].update(
        decision=decision, existing_target=context["entity"]["entity_id"]
    )
    validator = Draft202012Validator(render_relation_wire_context(context)["response_schema"])
    assert not validator.is_valid(payload)
    payload["decisions"][0]["existing_target"] = None
    assert validator.is_valid(payload)


def test_reference_requires_an_offered_identity(case: Any) -> None:
    context, payload = relation_sample(case)[-2:]
    payload["decisions"][0].update(decision="REFERENCE", member_refs=[])
    validator = Draft202012Validator(render_relation_wire_context(context)["response_schema"])
    for value in (None, "foreign", context["entity"]["entity_version"]):
        payload["decisions"][0]["existing_target"] = value
        assert not validator.is_valid(payload)
    payload["decisions"][0]["existing_target"] = context["entity"]["entity_id"]
    assert validator.is_valid(payload)
