"""Parse the plugin contract's states, transports and principals."""

from __future__ import annotations

from scripts.adoption_validation import (
    expect_bool,
    expect_closed_keys,
    expect_object,
    expect_string,
    expect_string_tuple,
    fail,
)
from scripts.plugin_contract_model import (
    ContractPrincipals,
    ContractState,
    ContractStates,
    ContractTransports,
    PrincipalAuthentication,
    SourceReaderPrincipal,
    SpaceBinding,
    TestWriterPrincipal,
)


def _parse_contract_state(value: object, label: str) -> ContractState:
    data = expect_object(value, label)
    expect_closed_keys(data, {"available", "status"}, label)
    return ContractState(
        available=expect_bool(data.get("available"), f"{label}.available"),
        status=expect_string(data.get("status"), f"{label}.status"),
    )


def parse_transports(value: object) -> ContractTransports:
    data = expect_object(value, "transports")
    expect_closed_keys(data, {"allowed", "forbidden"}, "transports")
    allowed = expect_string_tuple(data.get("allowed"), "transports.allowed")
    forbidden = expect_string_tuple(data.get("forbidden"), "transports.forbidden")
    if allowed != ("versioned_rest", "lifecycle_poll"):
        fail("allowed transports must be exactly versioned_rest and lifecycle_poll")
    if set(forbidden) != {
        "shared_database",
        "redis",
        "asynq",
        "internal_queue",
        "mcp_control_plane",
    }:
        fail("forbidden transports do not match the closed coupling boundary")
    return ContractTransports(allowed=allowed, forbidden=forbidden)


def parse_states(value: object) -> ContractStates:
    data = expect_object(value, "states")
    expect_closed_keys(
        data,
        {
            "w1_runtime",
            "consumer_adapted",
            "source_reader_authority",
            "artifact_gate",
        },
        "states",
    )
    w1_runtime = _parse_contract_state(data.get("w1_runtime"), "states.w1_runtime")
    consumer = _parse_contract_state(data.get("consumer_adapted"), "states.consumer_adapted")
    reader = _parse_contract_state(
        data.get("source_reader_authority"),
        "states.source_reader_authority",
    )
    artifact_gate = _parse_contract_state(data.get("artifact_gate"), "states.artifact_gate")
    if w1_runtime != ContractState(False, "available_after_replay"):
        fail("W1 runtime must remain unavailable before replay")
    if consumer != ContractState(False, "pre_w1"):
        fail("consumer must remain unavailable and pre_w1")
    if reader != ContractState(False, "blocked_on_p3_acl_inspection_authority"):
        fail("source_reader authority must remain blocked on P3 ACL authority")
    if artifact_gate != ContractState(False, "planned_nodes_pending_artifact_pr"):
        fail("artifact gate must remain unavailable while nodes are planned")
    return ContractStates(
        w1_runtime=w1_runtime,
        consumer_adapted=consumer,
        source_reader_authority=reader,
        artifact_gate=artifact_gate,
    )


def _parse_authentication(value: object) -> PrincipalAuthentication:
    data = expect_object(value, "source_reader.authentication")
    expect_closed_keys(data, {"header", "scheme", "capabilities"}, "source_reader.authentication")
    authentication = PrincipalAuthentication(
        header=expect_string(data.get("header"), "authentication.header"),
        scheme=expect_string(data.get("scheme"), "authentication.scheme"),
        capabilities=expect_string_tuple(data.get("capabilities"), "authentication.capabilities"),
    )
    if authentication != PrincipalAuthentication("Authorization", "Bearer", ("retrieve",)):
        fail("source_reader authentication must use the bounded retrieve contract")
    return authentication


def _parse_space_binding(value: object) -> SpaceBinding:
    data = expect_object(value, "source_reader.space_binding")
    expect_closed_keys(
        data,
        {
            "authority",
            "identity_fields",
            "acl_basis",
            "exact_knowledge_base_scope",
        },
        "source_reader.space_binding",
    )
    binding = SpaceBinding(
        authority=expect_string(data.get("authority"), "space_binding.authority"),
        identity_fields=expect_string_tuple(
            data.get("identity_fields"), "space_binding.identity_fields"
        ),
        acl_basis=expect_string_tuple(data.get("acl_basis"), "space_binding.acl_basis"),
        exact_knowledge_base_scope=expect_string(
            data.get("exact_knowledge_base_scope"),
            "space_binding.exact_knowledge_base_scope",
        ),
    )
    if binding != SpaceBinding(
        authority="harness_persisted_space_binding",
        identity_fields=("tenant_id", "raw_knowledge_base_id"),
        acl_basis=(
            "current_tenant_scope",
            "current_raw_knowledge_base_viewer_acl",
        ),
        exact_knowledge_base_scope="bound_raw_knowledge_base_only",
    ):
        fail("source_reader Space binding is not authoritative and exact")
    return binding


def parse_principals(value: object) -> ContractPrincipals:
    data = expect_object(value, "principals")
    expect_closed_keys(data, {"source_reader", "test_writer"}, "principals")
    reader_data = expect_object(data.get("source_reader"), "source_reader")
    expect_closed_keys(
        reader_data,
        {
            "service",
            "authentication",
            "space_binding",
            "allowed_operations",
            "denied_methods",
            "zero_write",
            "download_authority",
        },
        "source_reader",
    )
    reader = SourceReaderPrincipal(
        service=expect_string(reader_data.get("service"), "source_reader.service"),
        authentication=_parse_authentication(reader_data.get("authentication")),
        space_binding=_parse_space_binding(reader_data.get("space_binding")),
        allowed_operations=expect_string_tuple(
            reader_data.get("allowed_operations"), "source_reader.allowed_operations"
        ),
        denied_methods=expect_string_tuple(
            reader_data.get("denied_methods"), "source_reader.denied_methods"
        ),
        zero_write=expect_string(reader_data.get("zero_write"), "source_reader.zero_write"),
        download_authority=expect_string(
            reader_data.get("download_authority"),
            "source_reader.download_authority",
        ),
    )
    if reader.service != "source_reader":
        fail("source_reader service identity is not exact")
    if reader.allowed_operations != (
        "knowledge_list",
        "knowledge_get",
        "revision_get",
        "revision_chunks_get",
    ):
        fail("source_reader may perform only the approved reads")
    if set(reader.denied_methods) != {"POST", "PUT", "PATCH", "DELETE"}:
        fail("source_reader must deny every mutation method")
    if reader.zero_write != "required" or reader.download_authority != "blocked":
        fail("source_reader must be zero-write and may not download")

    writer_data = expect_object(data.get("test_writer"), "test_writer")
    expect_closed_keys(
        writer_data,
        {
            "service",
            "purpose",
            "allowed_operations",
            "auto_retry",
            "bounded_to_test_runs",
        },
        "test_writer",
    )
    writer = TestWriterPrincipal(
        service=expect_string(writer_data.get("service"), "test_writer.service"),
        purpose=expect_string(writer_data.get("purpose"), "test_writer.purpose"),
        allowed_operations=expect_string_tuple(
            writer_data.get("allowed_operations"), "test_writer.allowed_operations"
        ),
        auto_retry=expect_bool(writer_data.get("auto_retry"), "test_writer.auto_retry"),
        bounded_to_test_runs=expect_bool(
            writer_data.get("bounded_to_test_runs"),
            "test_writer.bounded_to_test_runs",
        ),
    )
    if writer != TestWriterPrincipal(
        service="w1_contract_test_writer",
        purpose="bounded_race_stimuli",
        allowed_operations=("knowledge_reparse", "knowledge_delete"),
        auto_retry=False,
        bounded_to_test_runs=True,
    ):
        fail("test_writer exceeds the bounded stimulus contract")
    return ContractPrincipals(source_reader=reader, test_writer=writer)
