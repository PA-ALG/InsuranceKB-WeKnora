"""Assemble one plugin contract document from its parsed parts."""

from __future__ import annotations

from pathlib import Path

from scripts.adoption_validation import expect_closed_keys, expect_list, expect_string, fail
from scripts.plugin_contract_access import parse_principals, parse_states, parse_transports
from scripts.plugin_contract_endpoints import parse_endpoint, parse_string_map, parse_typed_error
from scripts.plugin_contract_model import PluginContract
from scripts.plugin_contract_policies import (
    expect_inventory_ref,
    parse_exclusions,
    parse_idempotency,
    parse_readiness,
    parse_retry_policy,
    parse_timeout_policy,
    parse_validation_lanes,
)


def parse_plugin_contract(data: dict[str, object], repository_root: Path) -> PluginContract:
    """Parse a schema-version-1 plugin contract document; the caller checks its trust anchor."""

    expect_closed_keys(
        data,
        {
            "schema_version",
            "contract_id",
            "contract_version",
            "adoption_target_ref",
            "patch_inventory_ref",
            "transports",
            "states",
            "principals",
            "endpoints",
            "typed_errors",
            "lifecycle_dispositions",
            "retry_policy",
            "timeout_policy",
            "idempotency_identities",
            "readiness_signals",
            "validation_lanes",
            "exclusions",
        },
        "plugin contract",
    )
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        fail("plugin contract schema_version must be 1")
    contract_version = data.get("contract_version")
    if type(contract_version) is not int or contract_version != 1:
        fail("plugin contract contract_version must be 1 for schema_version 1")
    contract_id = expect_string(data.get("contract_id"), "plugin contract.contract_id")
    if contract_id != "harness-weknora-w1-plugin":
        fail("plugin contract.contract_id is not the approved stable ID")
    states = parse_states(data.get("states"))
    timeout_policy = parse_timeout_policy(data.get("timeout_policy"))
    endpoints = tuple(
        parse_endpoint(item)
        for item in expect_list(data.get("endpoints"), "plugin contract.endpoints")
    )
    typed_errors = tuple(
        parse_typed_error(item)
        for item in expect_list(data.get("typed_errors"), "plugin contract.typed_errors")
    )
    lifecycle_dispositions = parse_string_map(
        data.get("lifecycle_dispositions"), "lifecycle_dispositions"
    )
    if dict(lifecycle_dispositions) != {
        "failed": "preserve_prior_source_head",
        "cancelled": "preserve_prior_source_head",
    }:
        fail("failed and cancelled attempts must preserve prior SourceHead")
    idempotency = parse_idempotency(data.get("idempotency_identities"))
    readiness_signals = parse_readiness(data.get("readiness_signals"))
    validation_lanes = parse_validation_lanes(
        data.get("validation_lanes"),
        repository_root.resolve(),
    )
    planned_nodes = tuple(
        node for lane in validation_lanes for node in lane.nodes if node.status == "planned"
    )
    if planned_nodes and states.artifact_gate.available:
        fail("planned artifact nodes cannot count as a ready artifact gate")
    adoption_target_ref = expect_inventory_ref(
        data.get("adoption_target_ref"),
        "plugin contract.adoption_target_ref",
        "deploy/upstream/",
        "-adoption-target.json",
    )
    patch_inventory_ref = expect_inventory_ref(
        data.get("patch_inventory_ref"),
        "plugin contract.patch_inventory_ref",
        "deploy/patches/",
        "-patch-inventory.yaml",
    )
    transports = parse_transports(data.get("transports"))
    principals = parse_principals(data.get("principals"))
    retry_policy = parse_retry_policy(data.get("retry_policy"))
    exclusions = parse_exclusions(data.get("exclusions"))
    return PluginContract(
        schema_version=1,
        contract_id=contract_id,
        contract_version=contract_version,
        adoption_target_ref=adoption_target_ref,
        patch_inventory_ref=patch_inventory_ref,
        transports=transports,
        states=states,
        principals=principals,
        endpoints=endpoints,
        typed_errors=typed_errors,
        lifecycle_dispositions=lifecycle_dispositions,
        retry_policy=retry_policy,
        timeout_policy=timeout_policy,
        idempotency_identities=idempotency,
        readiness_signals=readiness_signals,
        validation_lanes=validation_lanes,
        exclusions=exclusions,
    )
