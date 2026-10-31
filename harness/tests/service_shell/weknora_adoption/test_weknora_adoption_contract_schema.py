"""WeKnora adoption: plugin contract schema v1, canonical JSON and digest rules."""

from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from scripts import prepare_weknora_adoption as adoption
from scripts.adoption_validation import AdoptionTargetError
from tests.service_shell.weknora_adoption.helpers import (
    PLUGIN_CONTRACT,
    _contract_value,
    _write_yaml,
)


def test_plugin_contract_rejects_consumer_adapted_without_required_w1_surface(
    tmp_path: Path,
) -> None:
    value = _contract_value()
    value["states"]["consumer_adapted"] = {"available": True, "status": "adapted"}
    value["endpoints"] = [
        endpoint
        for endpoint in value["endpoints"]
        if endpoint["endpoint_id"] != "revision_chunks_get"
    ]

    with pytest.raises(AdoptionTargetError, match="consumer"):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "invalid-contract.yaml", value))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["validation_lanes"][0]["nodes"][0].update(
            {"test_ref": "harness/tests/test_prepare_weknora_adoption_045.py::not_a_test"}
        ),
        lambda value: value["validation_lanes"][2]["nodes"][0].update({"required_by": "code_pr"}),
        lambda value: value["validation_lanes"][2]["nodes"][0].update({"status": "existing"}),
        lambda value: value["validation_lanes"][0]["nodes"][0].pop("status"),
        lambda value: value["validation_lanes"][0]["nodes"][0].pop("required_by"),
        lambda value: value["validation_lanes"][1]["nodes"].pop(2),
        lambda value: value["validation_lanes"][1]["nodes"][2].update(
            {
                "test_ref": (
                    "internal/handler/knowledge_revision_test.go::"
                    "TestGetKnowledgeRevisionFuturePlaceholder"
                )
            }
        ),
        lambda value: value["validation_lanes"][1]["nodes"][2].update(
            {"proves": ["in_progress_last_committed"]}
        ),
        lambda value: value["validation_lanes"][1]["nodes"][2].update({"status": "planned"}),
        lambda value: value["validation_lanes"][1]["nodes"][2].update(
            {"required_by": "artifact_pr"}
        ),
    ],
)
def test_plugin_contract_rejects_unresolved_or_untruthful_validation_nodes(
    tmp_path: Path, mutation: object
) -> None:
    value = _contract_value()
    mutation(value)  # type: ignore[operator]

    with pytest.raises(AdoptionTargetError):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "contract.yaml", value))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["endpoints"][0]["success"].pop("root_success"),
        lambda value: value["endpoints"][0]["success"].update({"root_success": False}),
        lambda value: value["endpoints"][0]["success"]["required_fields"].remove("success"),
        lambda value: value["typed_errors"][0].pop("root_success"),
        lambda value: value["typed_errors"][0].update({"root_success": True}),
        lambda value: value["typed_errors"][0]["required_fields"].remove("error"),
        lambda value: value["typed_errors"][0]["error_required_fields"].remove("code"),
        lambda value: value["typed_errors"][0].update(
            {"last_committed": "forbidden", "last_committed_required_fields": []}
        ),
        lambda value: value["typed_errors"][1].update(
            {"last_committed": "forbidden", "last_committed_required_fields": []}
        ),
        lambda value: value["typed_errors"][2].update(
            {
                "last_committed": "required_when_prior_committed",
                "last_committed_required_fields": [
                    "parse_attempt",
                    "manifest_digest",
                    "completed_at",
                ],
            }
        ),
    ],
)
def test_plugin_contract_rejects_incomplete_or_false_response_envelopes(
    tmp_path: Path, mutation: object
) -> None:
    value = _contract_value()
    mutation(value)  # type: ignore[operator]

    with pytest.raises(AdoptionTargetError):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "contract.yaml", value))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("timeout_policy"),
        lambda value: value["timeout_policy"].update({"connect_seconds": 0}),
        lambda value: value["timeout_policy"].update({"overall_seconds": 301}),
        lambda value: value["endpoints"][0].pop("timeout_policy_ref"),
        lambda value: value["endpoints"][0].update({"timeout_policy_ref": "unknown_timeout"}),
    ],
)
def test_plugin_contract_rejects_missing_invalid_or_unbound_timeout_policy(
    tmp_path: Path, mutation: object
) -> None:
    value = _contract_value()
    mutation(value)  # type: ignore[operator]

    with pytest.raises(AdoptionTargetError):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "contract.yaml", value))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["endpoints"].append(
            {
                **copy.deepcopy(value["endpoints"][0]),
                "endpoint_id": "knowledge_search",
                "path": "/api/v1/knowledge/search",
                "request": {
                    **copy.deepcopy(value["endpoints"][0]["request"]),
                    "path_parameters": [],
                },
            }
        ),
        lambda value: value["typed_errors"].append(
            {
                **copy.deepcopy(value["typed_errors"][0]),
                "code": "unexpected_error",
            }
        ),
        lambda value: value["typed_errors"].append(copy.deepcopy(value["typed_errors"][0])),
        lambda value: value["idempotency_identities"].update({"unexpected_get": ["space_binding"]}),
        lambda value: value["readiness_signals"].append(
            copy.deepcopy(value["readiness_signals"][0])
        ),
        lambda value: value["typed_errors"].reverse(),
        lambda value: value.update({"contract_version": 2}),
        lambda value: value["states"]["consumer_adapted"].update({"available": True}),
        lambda value: value["states"]["consumer_adapted"].update({"status": "adapted"}),
        lambda value: value["states"]["w1_runtime"].update({"available": True}),
        lambda value: value["states"]["source_reader_authority"].update({"available": True}),
        lambda value: value["states"]["artifact_gate"].update({"available": True}),
    ],
)
def test_plugin_contract_schema_v1_rejects_extras_version_and_conflated_states(
    tmp_path: Path, mutation: object
) -> None:
    value = _contract_value()
    mutation(value)  # type: ignore[operator]

    with pytest.raises(AdoptionTargetError):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "contract.yaml", value))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["endpoints"][1].update(
            {"path": "/api/v1/knowledge/{knowledge_id}/detail"}
        ),
        lambda value: value["endpoints"][2]["success"].update({"revision_required_fields": []}),
        lambda value: value["typed_errors"][5].update(
            {"status": 409, "disposition": "bounded_get_retry"}
        ),
        lambda value: value["readiness_signals"][2]["requires"].remove("source_reader_authority"),
        lambda value: value["idempotency_identities"]["knowledge_get"].remove("knowledge_id"),
    ],
    ids=[
        "knowledge-get-path",
        "revision-descriptor-envelope",
        "revision-superseded-semantics",
        "w1-readiness-authority",
        "knowledge-get-idempotency",
    ],
)
def test_plugin_contract_schema_v1_rejects_public_contract_value_drift(
    tmp_path: Path, mutation: object
) -> None:
    value = _contract_value()
    mutation(value)  # type: ignore[operator]

    with pytest.raises(AdoptionTargetError, match="schema-version-1"):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "contract.yaml", value))


def test_plugin_contract_canonical_json_ignores_mapping_order_comments_and_formatting(
    tmp_path: Path,
) -> None:
    value = _contract_value()
    reordered = {key: value[key] for key in reversed(value)}
    path = tmp_path / "reformatted-contract.yaml"
    path.write_text(
        "# mapping order and formatting are not semantic\n"
        + yaml.safe_dump(reordered, sort_keys=True, width=40),
        encoding="utf-8",
    )

    contract = adoption.load_plugin_contract(path)

    assert contract.schema_version == 1


def test_plugin_contract_schema_v1_digest_is_single_lowercase_sha256(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert adoption.PLUGIN_CONTRACT_SCHEMA_V1_SHA256 == (
        adoption.PLUGIN_CONTRACT_SCHEMA_V1_SHA256.lower()
    )
    assert len(adoption.PLUGIN_CONTRACT_SCHEMA_V1_SHA256) == 64
    assert set(adoption.PLUGIN_CONTRACT_SCHEMA_V1_SHA256) <= set("0123456789abcdef")

    monkeypatch.setattr(adoption, "PLUGIN_CONTRACT_SCHEMA_V1_SHA256", "not-a-sha256")
    with pytest.raises(AdoptionTargetError, match="trust anchor"):
        adoption.load_plugin_contract(PLUGIN_CONTRACT)


def test_plugin_contract_canonical_json_is_fixed_and_utf8() -> None:
    value = {"z": [1, True, None], "a": "合同"}

    assert adoption._canonical_semantic_json(value) == ('{"a":"合同","z":[1,true,null]}'.encode())


@pytest.mark.parametrize(
    "value",
    [
        1.5,
        float("nan"),
        datetime(2026, 7, 28, 12, 0),
        {1: "non-string-key"},
        b"custom-type",
    ],
    ids=["float", "nan", "timestamp", "non-string-key", "custom-type"],
)
def test_plugin_contract_canonical_json_rejects_nonsemantic_types(value: object) -> None:
    with pytest.raises(AdoptionTargetError, match="semantic JSON"):
        adoption._canonical_semantic_json(value)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["validation_lanes"][1]["nodes"].pop(0),
        lambda value: value["validation_lanes"][1]["nodes"].append(
            {
                **copy.deepcopy(value["validation_lanes"][1]["nodes"][0]),
                "node_id": "compatibility.extra_existing",
            }
        ),
        lambda value: value["validation_lanes"][1]["nodes"].reverse(),
        lambda value: value["validation_lanes"][2]["nodes"].pop(0),
        lambda value: value["validation_lanes"][2]["nodes"].append(
            {
                **copy.deepcopy(value["validation_lanes"][2]["nodes"][0]),
                "node_id": "artifact.extra_probe",
                "test_ref": ".github/workflows/weknora-app-local-live-image.yml::extra_probe",
            }
        ),
        lambda value: value["validation_lanes"][2]["nodes"].reverse(),
    ],
    ids=[
        "existing-delete",
        "existing-add",
        "existing-reorder",
        "artifact-delete",
        "artifact-add",
        "artifact-reorder",
    ],
)
def test_plugin_contract_digest_rejects_validation_node_set_or_order_mutation(
    tmp_path: Path, mutation: object
) -> None:
    value = _contract_value()
    mutation(value)  # type: ignore[operator]

    with pytest.raises(AdoptionTargetError, match="schema-version-1"):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "contract.yaml", value))
