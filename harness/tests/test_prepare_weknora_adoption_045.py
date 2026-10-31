"""WeKnora adoption: the plugin contract's approved refs, envelopes, lanes and couplings.

This module keeps its path: the digest-pinned plugin contract
(deploy/upstream/weknora-plugin-contract.yaml) names three of its tests as validation nodes.
The other adoption-tool contracts live in service_shell/weknora_adoption/.
"""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml

from scripts import prepare_weknora_adoption as adoption
from scripts.adoption_validation import AdoptionTargetError
from scripts.plugin_contract_model import ContractState, TimeoutPolicy
from tests.service_shell.weknora_adoption.helpers import (
    PLUGIN_CONTRACT,
    _contract_value,
    _write_yaml,
)


def test_plugin_contract_freezes_approved_refs_transports_and_independent_states() -> None:
    contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)

    assert contract.schema_version == 1
    assert contract.contract_id == "harness-weknora-w1-plugin"
    assert contract.contract_version == 1
    assert contract.adoption_target_ref == ("deploy/upstream/weknora-adoption-target.json")
    assert contract.patch_inventory_ref == (
        "deploy/patches/enterprise-llm-wiki-patch-inventory.yaml"
    )
    assert contract.transports.allowed == ("versioned_rest", "lifecycle_poll")
    assert contract.transports.forbidden == (
        "shared_database",
        "redis",
        "asynq",
        "internal_queue",
        "mcp_control_plane",
    )
    assert contract.states.w1_runtime == ContractState(
        available=False, status="available_after_replay"
    )
    assert contract.states.consumer_adapted == ContractState(
        available=False, status="pre_w1"
    )
    assert contract.states.source_reader_authority == ContractState(
        available=False,
        status="blocked_on_p3_acl_inspection_authority",
    )
    assert contract.states.artifact_gate == ContractState(
        available=False,
        status="planned_nodes_pending_artifact_pr",
    )
    with pytest.raises(FrozenInstanceError):
        contract.contract_version = 2  # type: ignore[misc]


def test_plugin_contract_source_reader_is_space_bound_read_only_and_not_elevated() -> None:
    contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)
    reader = contract.principals.source_reader

    assert reader.service == "source_reader"
    assert reader.authentication.header == "Authorization"
    assert reader.authentication.scheme == "Bearer"
    assert reader.authentication.capabilities == ("retrieve",)
    assert reader.space_binding.authority == "harness_persisted_space_binding"
    assert reader.space_binding.identity_fields == (
        "tenant_id",
        "raw_knowledge_base_id",
    )
    assert reader.space_binding.acl_basis == (
        "current_tenant_scope",
        "current_raw_knowledge_base_viewer_acl",
    )
    assert reader.space_binding.exact_knowledge_base_scope == ("bound_raw_knowledge_base_only")
    assert reader.allowed_operations == (
        "knowledge_list",
        "knowledge_get",
        "revision_get",
        "revision_chunks_get",
    )
    assert reader.denied_methods == ("POST", "PUT", "PATCH", "DELETE")
    assert reader.zero_write == "required"
    assert reader.download_authority == "blocked"

    writer = contract.principals.test_writer
    assert writer.service == "w1_contract_test_writer"
    assert writer.purpose == "bounded_race_stimuli"
    assert writer.allowed_operations == ("knowledge_reparse", "knowledge_delete")
    assert writer.auto_retry is False
    assert writer.bounded_to_test_runs is True


def test_plugin_contract_freezes_public_envelopes_and_stimulus_mutations() -> None:
    contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)
    endpoints = {endpoint.endpoint_id: endpoint for endpoint in contract.endpoints}

    assert tuple(endpoints) == (
        "knowledge_list",
        "knowledge_get",
        "revision_get",
        "revision_chunks_get",
        "knowledge_download",
        "knowledge_reparse",
        "knowledge_delete",
    )
    assert endpoints["knowledge_list"].authority == "discovery_only"
    assert endpoints["knowledge_get"].path == "/api/v1/knowledge/{knowledge_id}"
    assert endpoints["revision_get"].path == ("/api/v1/knowledge/{knowledge_id}/revision")
    chunks = endpoints["revision_chunks_get"]
    assert chunks.method == "GET"
    assert chunks.path == ("/api/v1/knowledge/{knowledge_id}/revisions/{parse_attempt}/chunks")
    assert chunks.success.envelope == "root"
    assert chunks.success.required_fields == (
        "success",
        "data",
        "total",
        "page",
        "page_size",
        "revision",
    )
    assert chunks.success.revision_required_fields == (
        "knowledge_id",
        "parse_attempt",
        "manifest_digest",
        "chunk_count",
    )
    assert tuple(parameter.name for parameter in chunks.request.query_parameters) == (
        "page",
        "page_size",
    )
    assert endpoints["knowledge_download"].authority == (
        "blocked_pending_source_reader_acl_authority"
    )
    assert endpoints["knowledge_download"].success.available is False
    assert endpoints["knowledge_download"].principal == "source_reader"
    for endpoint_id, endpoint in endpoints.items():
        assert endpoint.timeout_policy_ref == "w1_public_contract_timeout_v1"
        if endpoint_id != "knowledge_download":
            assert endpoint.success.available is True
            assert endpoint.success.root_success is True
            assert "success" in endpoint.success.required_fields
            assert "data" in endpoint.success.required_fields
    for endpoint_id in ("knowledge_reparse", "knowledge_delete"):
        endpoint = endpoints[endpoint_id]
        assert endpoint.authority == "stimulus_only"
        assert endpoint.principal == "test_writer"
        assert endpoint.retry.mode == "never"


def test_plugin_contract_typed_dispositions_retries_and_source_head_rules() -> None:
    contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)
    errors = {(item.code, item.reason): item for item in contract.typed_errors}

    assert errors[("revision_not_committed", "attempt_in_progress")].disposition == (
        "bounded_get_retry"
    )
    assert errors[("revision_superseded", "any")].disposition == (
        "restart_revision_and_discard_pages"
    )
    assert errors[("revision_superseded", "any")].error_required_fields == (
        "code",
        "current_parse_attempt",
        "parse_status",
    )
    assert errors[("knowledge_deleted", "any")].disposition == "record_tombstone"
    assert errors[("revision_manifest_incomplete", "any")].disposition == ("block_without_fallback")
    assert errors[("revision_not_found", "any")].disposition == ("fail_without_fallback")
    assert errors[("knowledge_not_found", "authorized_probe_only")].disposition == (
        "accept_absence_after_authorized_probe"
    )
    for status in (401, 403, 404):
        assert errors[("acl_denied", str(status))].disposition == (
            "fail_closed_without_lifecycle_inference"
        )
    for error in contract.typed_errors:
        assert error.root_success is False
        assert error.envelope == "root"
        assert error.required_fields == ("success", "error")
        assert "code" in error.error_required_fields
    lifecycle = dict(contract.lifecycle_dispositions)
    assert lifecycle["failed"] == "preserve_prior_source_head"
    assert lifecycle["cancelled"] == "preserve_prior_source_head"

    assert contract.retry_policy.allowed_methods == ("GET",)
    assert contract.retry_policy.bounded_attempts == 3
    assert contract.retry_policy.mutation_auto_retry is False
    assert contract.timeout_policy == TimeoutPolicy(
        policy_id="w1_public_contract_timeout_v1",
        connect_seconds=5,
        read_seconds=15,
        overall_seconds=60,
    )
    assert contract.idempotency_identities["revision_chunks_get"] == (
        "space_binding",
        "knowledge_id",
        "parse_attempt",
        "page",
        "page_size",
        "manifest_digest",
    )


def test_plugin_contract_matches_actual_terminal_reason_and_conditional_envelope() -> None:
    contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)
    errors = {(item.code, item.reason): item for item in contract.typed_errors}

    assert ("revision_not_committed", "failed") not in errors
    assert ("revision_not_committed", "cancelled") not in errors
    assert ("revision_not_committed", "non_parser_completed") not in errors
    assert ("revision_not_committed", "non_parse_completed") in errors
    prior_commit_reasons = {"attempt_in_progress", "attempt_terminal"}
    assert errors[("revision_not_committed", "attempt_terminal")].disposition == (
        "preserve_prior_source_head"
    )
    for error in contract.typed_errors:
        if error.code == "revision_not_committed" and error.reason in prior_commit_reasons:
            assert error.last_committed == "required_when_prior_committed"
            assert error.last_committed_required_fields == (
                "parse_attempt",
                "manifest_digest",
                "completed_at",
            )
        else:
            assert error.last_committed == "forbidden"
            assert error.last_committed_required_fields == ()


def test_plugin_contract_registers_existing_not_committed_reason_matrix_node() -> None:
    contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)
    nodes = {node.node_id: node for lane in contract.validation_lanes for node in lane.nodes}

    descriptor = nodes["compatibility.w1_revision_descriptor"]
    assert descriptor.proves == ("current_committed_revision_descriptor",)
    matrix = nodes["compatibility.w1_not_committed_error_matrix"]
    assert matrix.test_ref == (
        "internal/handler/knowledge_revision_test.go::"
        "TestGetKnowledgeRevisionNotCommittedReasonMatrix"
    )
    assert matrix.status == "existing"
    assert matrix.required_by == "code_pr"
    assert matrix.proves == (
        "revision_not_committed_reason_matrix",
        "terminal_last_committed_envelope",
    )


def test_plugin_contract_registers_in_progress_prior_commit_evidence() -> None:
    contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)
    nodes = {node.node_id: node for lane in contract.validation_lanes for node in lane.nodes}

    node = nodes["compatibility.w1_in_progress_last_committed"]
    assert node.test_ref == (
        "internal/handler/knowledge_revision_test.go::"
        "TestGetKnowledgeRevisionInProgressIncludesLastCommitted"
    )
    assert node.status == "existing"
    assert node.required_by == "code_pr"
    assert node.proves == ("in_progress_with_prior_last_committed_envelope",)
    assert contract.states.w1_runtime.available is False
    assert contract.states.consumer_adapted.available is False
    assert contract.states.artifact_gate.available is False


def test_plugin_contract_separates_readiness_lanes_and_excludes_unowned_work() -> None:
    contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)

    assert tuple(signal.signal_id for signal in contract.readiness_signals) == (
        "weknora_runtime",
        "harness_process",
        "w1_consumer_capability",
    )
    assert tuple(lane.lane_id for lane in contract.validation_lanes) == (
        "planner",
        "compatibility_ci",
        "artifact_probe",
    )
    assert all(lane.nodes for lane in contract.validation_lanes)
    existing = tuple(
        node
        for lane in contract.validation_lanes
        for node in lane.nodes
        if node.status == "existing"
    )
    planned = tuple(
        node
        for lane in contract.validation_lanes
        for node in lane.nodes
        if node.status == "planned"
    )
    assert existing
    assert all(node.required_by == "code_pr" for node in existing)
    assert planned
    planned_code_pr = tuple(node for node in planned if node.required_by == "code_pr")
    assert planned_code_pr == ()
    assert len(planned) == 5
    assert all(node.required_by == "artifact_pr" for node in planned)
    assert all(node.status != "existing" for node in planned)
    assert contract.states.artifact_gate.available is False
    assert contract.exclusions.ordinary_wiki_operations == (
        "history",
        "diff",
        "edit",
        "revert",
    )
    assert contract.exclusions.missions == (
        "P4a",
        "P4c",
        "P2d",
        "P11",
        "P13",
        "P14",
        "provider",
        "full",
    )


def test_plugin_contract_schema_v1_requires_version_bump_for_future_target_refs(
    tmp_path: Path,
) -> None:
    value = yaml.safe_load(PLUGIN_CONTRACT.read_text(encoding="utf-8"))
    value["adoption_target_ref"] = "deploy/upstream/future-adoption-target.json"
    value["patch_inventory_ref"] = "deploy/patches/future-patch-inventory.yaml"

    with pytest.raises(AdoptionTargetError, match="schema-version-1.*digest"):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "future-contract.yaml", value))


def test_plugin_contract_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    path = tmp_path / "contract.yaml"
    path.write_text(
        PLUGIN_CONTRACT.read_text(encoding="utf-8").replace(
            "contract_version: 1",
            "contract_version: 1\ncontract_version: 2",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(AdoptionTargetError, match="duplicate"):
        adoption.load_plugin_contract(path)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["principals"]["source_reader"].pop("space_binding"),
        lambda value: value["principals"]["source_reader"]["allowed_operations"].append(
            "knowledge_reparse"
        ),
        lambda value: value["principals"]["source_reader"].update(
            {"download_authority": "available"}
        ),
        lambda value: value["states"]["source_reader_authority"].update(
            {"available": True, "status": "available"}
        ),
        lambda value: value["transports"]["forbidden"].remove("shared_database"),
        lambda value: value["transports"]["forbidden"].append("grpc"),
        lambda value: value["endpoints"][0].update({"go_symbol": "handler.ListKnowledge"}),
        lambda value: value["endpoints"].append(
            {
                **copy.deepcopy(value["endpoints"][0]),
                "endpoint_id": "wiki_history",
                "path": "/api/v1/wiki/{id}/history",
            }
        ),
        lambda value: value["validation_lanes"].pop(),
        lambda value: value["validation_lanes"][1]["nodes"].append(
            copy.deepcopy(value["validation_lanes"][0]["nodes"][0])
        ),
    ],
)
def test_plugin_contract_rejects_security_coupling_private_wiki_and_lane_mutations(
    tmp_path: Path, mutation: object
) -> None:
    value = _contract_value()
    mutation(value)  # type: ignore[operator]

    with pytest.raises(AdoptionTargetError):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "invalid-contract.yaml", value))
