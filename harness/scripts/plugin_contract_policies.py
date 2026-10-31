"""Parse the plugin contract's runtime policies, validation lanes and exclusions."""

from __future__ import annotations

import re
from pathlib import Path

from scripts.adoption_validation import (
    REPOSITORY_REF_RE,
    AdoptionTargetError,
    expect_bool,
    expect_closed_keys,
    expect_identifier,
    expect_list,
    expect_object,
    expect_string,
    expect_string_tuple,
    fail,
)
from scripts.plugin_contract_model import (
    ContractExclusions,
    IdempotencyIdentities,
    ReadinessSignal,
    RetryPolicy,
    TimeoutPolicy,
    ValidationLane,
    ValidationNode,
)

_SEMANTIC_ID_RE = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")


def _expect_semantic_id(value: object, label: str) -> str:
    semantic_id = expect_string(value, label)
    if _SEMANTIC_ID_RE.fullmatch(semantic_id) is None:
        fail(f"{label} must be a stable semantic identifier")
    return semantic_id


def parse_retry_policy(value: object) -> RetryPolicy:
    data = expect_object(value, "retry_policy")
    expect_closed_keys(
        data,
        {
            "allowed_methods",
            "bounded_attempts",
            "retryable_statuses",
            "mutation_auto_retry",
        },
        "retry_policy",
    )
    bounded_attempts = data.get("bounded_attempts")
    if type(bounded_attempts) is not int or not 1 <= bounded_attempts <= 5:
        fail("retry_policy.bounded_attempts must be bounded from 1 through 5")
    statuses_value = expect_list(data.get("retryable_statuses"), "retry_policy.retryable_statuses")
    statuses: list[int] = []
    for status in statuses_value:
        if type(status) is not int or status not in {408, 425, 429, 500, 502, 503, 504}:
            fail("retry_policy contains an unapproved retryable status")
        statuses.append(status)
    policy = RetryPolicy(
        allowed_methods=expect_string_tuple(
            data.get("allowed_methods"), "retry_policy.allowed_methods"
        ),
        bounded_attempts=bounded_attempts,
        retryable_statuses=tuple(statuses),
        mutation_auto_retry=expect_bool(
            data.get("mutation_auto_retry"), "retry_policy.mutation_auto_retry"
        ),
    )
    if policy.allowed_methods != ("GET",) or policy.mutation_auto_retry:
        fail("only GET may be retried and mutations must never auto retry")
    return policy


def parse_timeout_policy(value: object) -> TimeoutPolicy:
    data = expect_object(value, "timeout_policy")
    expect_closed_keys(
        data,
        {
            "policy_id",
            "connect_seconds",
            "read_seconds",
            "overall_seconds",
        },
        "timeout_policy",
    )
    values: dict[str, int] = {}
    for field in ("connect_seconds", "read_seconds", "overall_seconds"):
        raw_value = data.get(field)
        if type(raw_value) is not int or not 1 <= raw_value <= 300:
            fail(f"timeout_policy.{field} must be between 1 and 300 seconds")
        values[field] = raw_value
    if not (values["connect_seconds"] <= values["read_seconds"] <= values["overall_seconds"]):
        fail("timeout_policy budgets must be monotonically bounded")
    return TimeoutPolicy(
        policy_id=expect_identifier(data.get("policy_id"), "timeout_policy.policy_id"),
        connect_seconds=values["connect_seconds"],
        read_seconds=values["read_seconds"],
        overall_seconds=values["overall_seconds"],
    )


def parse_idempotency(value: object) -> IdempotencyIdentities:
    data = expect_object(value, "idempotency_identities")
    values = tuple(
        (
            expect_identifier(key, "idempotency endpoint ID"),
            expect_string_tuple(item, f"idempotency_identities.{key}"),
        )
        for key, item in data.items()
    )
    return IdempotencyIdentities(values)


def parse_readiness(value: object) -> tuple[ReadinessSignal, ...]:
    result: list[ReadinessSignal] = []
    for raw_signal in expect_list(value, "readiness_signals"):
        data = expect_object(raw_signal, "readiness signal")
        expect_closed_keys(data, {"signal_id", "status", "requires"}, "readiness signal")
        result.append(
            ReadinessSignal(
                signal_id=expect_identifier(data.get("signal_id"), "readiness signal.signal_id"),
                status=expect_string(data.get("status"), "readiness signal.status"),
                requires=expect_string_tuple(
                    data.get("requires"),
                    "readiness signal.requires",
                    allow_empty=True,
                ),
            )
        )
    if tuple(item.signal_id for item in result) != (
        "weknora_runtime",
        "harness_process",
        "w1_consumer_capability",
    ):
        fail("readiness signals must remain three independent ordered signals")
    return tuple(result)


def _resolve_existing_test_ref(repository_root: Path, test_ref: str) -> None:
    parts = test_ref.split("::")
    if len(parts) != 2:
        fail("existing validation node must use repository/path::function")
    relative_path, function_name = parts
    if (
        REPOSITORY_REF_RE.fullmatch(relative_path) is None
        or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", function_name) is None
    ):
        fail("existing validation node reference is not normalized")
    candidate = (repository_root / relative_path).resolve()
    if not candidate.is_relative_to(repository_root.resolve()) or not candidate.is_file():
        fail("existing validation node file does not exist")
    try:
        source = candidate.read_text(encoding="utf-8")
    except OSError as exc:
        raise AdoptionTargetError("existing validation node file is unreadable") from exc
    declaration = (
        rf"^(?:async\s+)?def\s+{re.escape(function_name)}\s*\("
        if candidate.suffix == ".py"
        else rf"^func\s+{re.escape(function_name)}\s*\("
    )
    if (
        candidate.suffix not in {".py", ".go"}
        or re.search(declaration, source, re.MULTILINE) is None
    ):
        fail("existing validation node function does not exist")


def parse_validation_lanes(value: object, repository_root: Path) -> tuple[ValidationLane, ...]:
    lanes: list[ValidationLane] = []
    all_node_ids: list[str] = []
    for raw_lane in expect_list(value, "validation_lanes"):
        data = expect_object(raw_lane, "validation lane")
        expect_closed_keys(data, {"lane_id", "nodes"}, "validation lane")
        lane_id = expect_identifier(data.get("lane_id"), "validation lane.lane_id")
        nodes: list[ValidationNode] = []
        for raw_node in expect_list(data.get("nodes"), "validation lane.nodes"):
            node_data = expect_object(raw_node, "validation node")
            expect_closed_keys(
                node_data,
                {"node_id", "test_ref", "status", "required_by", "proves"},
                "validation node",
            )
            node_id = _expect_semantic_id(node_data.get("node_id"), "validation node.node_id")
            test_ref = expect_string(node_data.get("test_ref"), "validation node.test_ref")
            if (
                re.fullmatch(
                    r"[a-zA-Z0-9_./-]+::[a-zA-Z_][a-zA-Z0-9_]*",
                    test_ref,
                )
                is None
            ):
                fail("validation node.test_ref is not an exact declared node")
            status = expect_string(node_data.get("status"), "validation node.status")
            required_by = expect_string(
                node_data.get("required_by"), "validation node.required_by"
            )
            proves = expect_string_tuple(node_data.get("proves"), "validation node.proves")
            if status == "existing":
                if required_by != "code_pr":
                    fail("existing validation nodes must be required by code_pr")
                _resolve_existing_test_ref(repository_root, test_ref)
            elif status == "planned":
                artifact_plan = lane_id == "artifact_probe" and required_by == "artifact_pr"
                if not artifact_plan:
                    fail("planned validation node is outside the closed schema")
            else:
                fail("validation node.status must be existing or planned")
            nodes.append(
                ValidationNode(
                    node_id=node_id,
                    test_ref=test_ref,
                    status=status,
                    required_by=required_by,
                    proves=proves,
                )
            )
            all_node_ids.append(node_id)
        lanes.append(
            ValidationLane(
                lane_id=lane_id,
                nodes=tuple(nodes),
            )
        )
    if tuple(lane.lane_id for lane in lanes) != (
        "planner",
        "compatibility_ci",
        "artifact_probe",
    ):
        fail("validation lanes must be planner, compatibility_ci, artifact_probe")
    if len(set(all_node_ids)) != len(all_node_ids):
        fail("validation node IDs must be globally unique")
    planned_code_pr_nodes = tuple(
        (
            lane.lane_id,
            node.node_id,
            node.test_ref,
            node.required_by,
            node.proves,
        )
        for lane in lanes
        for node in lane.nodes
        if node.status == "planned" and node.required_by == "code_pr"
    )
    if planned_code_pr_nodes:
        fail("schema-version-1 forbids planned code_pr evidence nodes")
    return tuple(lanes)


def parse_exclusions(value: object) -> ContractExclusions:
    data = expect_object(value, "exclusions")
    expect_closed_keys(data, {"ordinary_wiki_operations", "missions"}, "exclusions")
    exclusions = ContractExclusions(
        ordinary_wiki_operations=expect_string_tuple(
            data.get("ordinary_wiki_operations"),
            "exclusions.ordinary_wiki_operations",
        ),
        missions=expect_string_tuple(data.get("missions"), "exclusions.missions"),
    )
    if exclusions.ordinary_wiki_operations != (
        "history",
        "diff",
        "edit",
        "revert",
    ) or exclusions.missions != (
        "P4a",
        "P4c",
        "P2d",
        "P11",
        "P13",
        "P14",
        "provider",
        "full",
    ):
        fail("plugin contract exclusions do not match the approved scope")
    return exclusions


def expect_inventory_ref(value: object, label: str, prefix: str, suffix: str) -> str:
    reference = expect_string(value, label)
    if (
        REPOSITORY_REF_RE.fullmatch(reference) is None
        or not reference.startswith(prefix)
        or not reference.endswith(suffix)
    ):
        fail(f"{label} does not point to the required inventory kind")
    return reference
