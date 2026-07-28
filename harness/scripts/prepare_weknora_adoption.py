#!/usr/bin/env python3
"""Validate and discover immutable WeKnora adoption targets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import NoReturn, Protocol

import yaml

_REPOSITORY = "https://github.com/Tencent/WeKnora.git"
_CAPABILITY_COMMIT = "80a5003cc99a427098afe184eee6601916d3d156"
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_RELEASE_TAG_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
_MIGRATION_PATH_RE = re.compile(r"migrations/versioned/(?P<head>[0-9]+)_[^/]+\.(?:up|down)\.sql")
_OFFICIAL_MIGRATION_RE = re.compile(
    r"(?P<version>[0-9]{6})_(?P<name>[a-z0-9_]+)\.(?P<direction>up|down)\.sql"
)
_MANIFEST_KEYS = {
    "schema_version",
    "repository",
    "commit",
    "tree",
    "release_ancestor",
    "required_capability_commits",
    "official_migration_head",
}
_RELEASE_KEYS = {"tag", "commit"}
_CHANNELS = ("latest-stable", "mainline-head")
_GITHUB_API = "https://api.github.com/repos/Tencent/WeKnora"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SEMANTIC_ID_RE = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
_SQL_IDENTIFIER_RE = re.compile(r"[a-z][a-z0-9_]*")
_REPOSITORY_REF_RE = re.compile(r"(?!/)(?!.*(?:^|/)\.\.(?:/|$))[a-zA-Z0-9_./-]+")
PLUGIN_CONTRACT_SCHEMA_V1_SHA256 = (
    "548ef36ec27cd3175ff2c0d2de1654d3496a3233a3fa05514b51ef04e6d93d34"
)


class AdoptionTargetError(ValueError):
    """Raised when an adoption identity cannot be trusted."""


def _fail(message: str) -> NoReturn:
    raise AdoptionTargetError(message)


def _expect_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _fail(f"{label} must be an object")
    return value


def _expect_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{label} must be a non-empty string")
    if any(character in value for character in ("\n", "\r", "\x00")):
        _fail(f"{label} must be a single-line string")
    return value


def _expect_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        _fail(f"{label} must be a boolean")
    return value


def _expect_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list) or not value:
        _fail(f"{label} must be a non-empty list")
    return value


def _expect_closed_keys(data: dict[str, object], expected: set[str], label: str) -> None:
    if set(data) != expected:
        _fail(f"{label} keys do not match the closed schema")


def _expect_identifier(value: object, label: str) -> str:
    identifier = _expect_string(value, label)
    if _SQL_IDENTIFIER_RE.fullmatch(identifier) is None:
        _fail(f"{label} must be a normalized SQL identifier")
    return identifier


def _expect_semantic_id(value: object, label: str) -> str:
    semantic_id = _expect_string(value, label)
    if _SEMANTIC_ID_RE.fullmatch(semantic_id) is None:
        _fail(f"{label} must be a stable semantic identifier")
    return semantic_id


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            _fail("YAML mapping keys must be strings")
        if key in result:
            raise _DuplicateKeyError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_yaml(path: Path, label: str) -> object:
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except _DuplicateKeyError as exc:
        raise AdoptionTargetError(str(exc)) from exc
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise AdoptionTargetError(f"{label} is unreadable") from exc


def _validate_semantic_json(value: object) -> None:
    if value is None or type(value) in {str, int, bool}:
        return
    if isinstance(value, list):
        for item in value:
            _validate_semantic_json(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if type(key) is not str:
                _fail("plugin contract canonical value is not semantic JSON")
            _validate_semantic_json(item)
        return
    _fail("plugin contract canonical value is not semantic JSON")


def _canonical_semantic_json(value: object) -> bytes:
    _validate_semantic_json(value)
    try:
        canonical = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise AdoptionTargetError("plugin contract canonical value is not semantic JSON") from exc
    return canonical.encode("utf-8")


@dataclass(frozen=True)
class ContractTransports:
    allowed: tuple[str, ...]
    forbidden: tuple[str, ...]


@dataclass(frozen=True)
class ContractState:
    available: bool
    status: str


@dataclass(frozen=True)
class ContractStates:
    w1_runtime: ContractState
    consumer_adapted: ContractState
    source_reader_authority: ContractState
    artifact_gate: ContractState


@dataclass(frozen=True)
class PrincipalAuthentication:
    header: str
    scheme: str
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class SpaceBinding:
    authority: str
    identity_fields: tuple[str, ...]
    acl_basis: tuple[str, ...]
    exact_knowledge_base_scope: str


@dataclass(frozen=True)
class SourceReaderPrincipal:
    service: str
    authentication: PrincipalAuthentication
    space_binding: SpaceBinding
    allowed_operations: tuple[str, ...]
    denied_methods: tuple[str, ...]
    zero_write: str
    download_authority: str


@dataclass(frozen=True)
class TestWriterPrincipal:
    service: str
    purpose: str
    allowed_operations: tuple[str, ...]
    auto_retry: bool
    bounded_to_test_runs: bool


@dataclass(frozen=True)
class ContractPrincipals:
    source_reader: SourceReaderPrincipal
    test_writer: TestWriterPrincipal


@dataclass(frozen=True)
class ParameterGrammar:
    name: str
    value_type: str
    required: bool
    minimum: int | None
    maximum: int | None


@dataclass(frozen=True)
class EndpointRequest:
    path_parameters: tuple[ParameterGrammar, ...]
    query_parameters: tuple[ParameterGrammar, ...]
    body: str


@dataclass(frozen=True)
class EndpointSuccess:
    available: bool
    root_success: bool | None
    statuses: tuple[int, ...]
    envelope: str
    required_fields: tuple[str, ...]
    revision_required_fields: tuple[str, ...]


@dataclass(frozen=True)
class EndpointRetry:
    mode: str
    identity_fields: tuple[str, ...]


@dataclass(frozen=True)
class EndpointContract:
    endpoint_id: str
    method: str
    path: str
    principal: str
    authority: str
    request: EndpointRequest
    success: EndpointSuccess
    retry: EndpointRetry
    timeout_policy_ref: str


@dataclass(frozen=True)
class TypedErrorContract:
    code: str
    reason: str
    status: int
    disposition: str
    root_success: bool
    envelope: str
    required_fields: tuple[str, ...]
    error_required_fields: tuple[str, ...]
    last_committed: str
    last_committed_required_fields: tuple[str, ...]


@dataclass(frozen=True)
class RetryPolicy:
    allowed_methods: tuple[str, ...]
    bounded_attempts: int
    retryable_statuses: tuple[int, ...]
    mutation_auto_retry: bool


@dataclass(frozen=True)
class TimeoutPolicy:
    policy_id: str
    connect_seconds: int
    read_seconds: int
    overall_seconds: int


@dataclass(frozen=True)
class IdempotencyIdentities:
    values: tuple[tuple[str, tuple[str, ...]], ...]

    def __getitem__(self, key: str) -> tuple[str, ...]:
        for item_key, value in self.values:
            if item_key == key:
                return value
        raise KeyError(key)


@dataclass(frozen=True)
class ReadinessSignal:
    signal_id: str
    status: str
    requires: tuple[str, ...]


@dataclass(frozen=True)
class ValidationNode:
    node_id: str
    test_ref: str
    status: str
    required_by: str
    proves: tuple[str, ...]


@dataclass(frozen=True)
class ValidationLane:
    lane_id: str
    nodes: tuple[ValidationNode, ...]


@dataclass(frozen=True)
class ContractExclusions:
    ordinary_wiki_operations: tuple[str, ...]
    missions: tuple[str, ...]


@dataclass(frozen=True)
class PluginContract:
    schema_version: int
    contract_id: str
    contract_version: int
    adoption_target_ref: str
    patch_inventory_ref: str
    transports: ContractTransports
    states: ContractStates
    principals: ContractPrincipals
    endpoints: tuple[EndpointContract, ...]
    typed_errors: tuple[TypedErrorContract, ...]
    lifecycle_dispositions: tuple[tuple[str, str], ...]
    retry_policy: RetryPolicy
    timeout_policy: TimeoutPolicy
    idempotency_identities: IdempotencyIdentities
    readiness_signals: tuple[ReadinessSignal, ...]
    validation_lanes: tuple[ValidationLane, ...]
    exclusions: ContractExclusions


def _expect_string_tuple(
    value: object, label: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        _fail(f"{label} must be a {'possibly empty ' if allow_empty else ''}list")
    result = tuple(_expect_string(item, label) for item in value)
    if len(set(result)) != len(result):
        _fail(f"{label} must contain unique values")
    return result


def _parse_contract_state(value: object, label: str) -> ContractState:
    data = _expect_object(value, label)
    _expect_closed_keys(data, {"available", "status"}, label)
    return ContractState(
        available=_expect_bool(data.get("available"), f"{label}.available"),
        status=_expect_string(data.get("status"), f"{label}.status"),
    )


def _parse_transports(value: object) -> ContractTransports:
    data = _expect_object(value, "transports")
    _expect_closed_keys(data, {"allowed", "forbidden"}, "transports")
    allowed = _expect_string_tuple(data.get("allowed"), "transports.allowed")
    forbidden = _expect_string_tuple(data.get("forbidden"), "transports.forbidden")
    if allowed != ("versioned_rest", "lifecycle_poll"):
        _fail("allowed transports must be exactly versioned_rest and lifecycle_poll")
    if set(forbidden) != {
        "shared_database",
        "redis",
        "asynq",
        "internal_queue",
        "mcp_control_plane",
    }:
        _fail("forbidden transports do not match the closed coupling boundary")
    return ContractTransports(allowed=allowed, forbidden=forbidden)


def _parse_states(value: object) -> ContractStates:
    data = _expect_object(value, "states")
    _expect_closed_keys(
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
        _fail("W1 runtime must remain unavailable before replay")
    if consumer != ContractState(False, "pre_w1"):
        _fail("consumer must remain unavailable and pre_w1")
    if reader != ContractState(False, "blocked_on_p3_acl_inspection_authority"):
        _fail("source_reader authority must remain blocked on P3 ACL authority")
    if artifact_gate != ContractState(False, "planned_nodes_pending_artifact_pr"):
        _fail("artifact gate must remain unavailable while nodes are planned")
    return ContractStates(
        w1_runtime=w1_runtime,
        consumer_adapted=consumer,
        source_reader_authority=reader,
        artifact_gate=artifact_gate,
    )


def _parse_authentication(value: object) -> PrincipalAuthentication:
    data = _expect_object(value, "source_reader.authentication")
    _expect_closed_keys(data, {"header", "scheme", "capabilities"}, "source_reader.authentication")
    authentication = PrincipalAuthentication(
        header=_expect_string(data.get("header"), "authentication.header"),
        scheme=_expect_string(data.get("scheme"), "authentication.scheme"),
        capabilities=_expect_string_tuple(data.get("capabilities"), "authentication.capabilities"),
    )
    if authentication != PrincipalAuthentication("Authorization", "Bearer", ("retrieve",)):
        _fail("source_reader authentication must use the bounded retrieve contract")
    return authentication


def _parse_space_binding(value: object) -> SpaceBinding:
    data = _expect_object(value, "source_reader.space_binding")
    _expect_closed_keys(
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
        authority=_expect_string(data.get("authority"), "space_binding.authority"),
        identity_fields=_expect_string_tuple(
            data.get("identity_fields"), "space_binding.identity_fields"
        ),
        acl_basis=_expect_string_tuple(data.get("acl_basis"), "space_binding.acl_basis"),
        exact_knowledge_base_scope=_expect_string(
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
        _fail("source_reader Space binding is not authoritative and exact")
    return binding


def _parse_principals(value: object) -> ContractPrincipals:
    data = _expect_object(value, "principals")
    _expect_closed_keys(data, {"source_reader", "test_writer"}, "principals")
    reader_data = _expect_object(data.get("source_reader"), "source_reader")
    _expect_closed_keys(
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
        service=_expect_string(reader_data.get("service"), "source_reader.service"),
        authentication=_parse_authentication(reader_data.get("authentication")),
        space_binding=_parse_space_binding(reader_data.get("space_binding")),
        allowed_operations=_expect_string_tuple(
            reader_data.get("allowed_operations"), "source_reader.allowed_operations"
        ),
        denied_methods=_expect_string_tuple(
            reader_data.get("denied_methods"), "source_reader.denied_methods"
        ),
        zero_write=_expect_string(reader_data.get("zero_write"), "source_reader.zero_write"),
        download_authority=_expect_string(
            reader_data.get("download_authority"),
            "source_reader.download_authority",
        ),
    )
    if reader.service != "source_reader":
        _fail("source_reader service identity is not exact")
    if reader.allowed_operations != (
        "knowledge_list",
        "knowledge_get",
        "revision_get",
        "revision_chunks_get",
    ):
        _fail("source_reader may perform only the approved reads")
    if set(reader.denied_methods) != {"POST", "PUT", "PATCH", "DELETE"}:
        _fail("source_reader must deny every mutation method")
    if reader.zero_write != "required" or reader.download_authority != "blocked":
        _fail("source_reader must be zero-write and may not download")

    writer_data = _expect_object(data.get("test_writer"), "test_writer")
    _expect_closed_keys(
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
        service=_expect_string(writer_data.get("service"), "test_writer.service"),
        purpose=_expect_string(writer_data.get("purpose"), "test_writer.purpose"),
        allowed_operations=_expect_string_tuple(
            writer_data.get("allowed_operations"), "test_writer.allowed_operations"
        ),
        auto_retry=_expect_bool(writer_data.get("auto_retry"), "test_writer.auto_retry"),
        bounded_to_test_runs=_expect_bool(
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
        _fail("test_writer exceeds the bounded stimulus contract")
    return ContractPrincipals(source_reader=reader, test_writer=writer)


def _parse_parameter(value: object, label: str) -> ParameterGrammar:
    data = _expect_object(value, label)
    _expect_closed_keys(data, {"name", "value_type", "required", "minimum", "maximum"}, label)
    value_type = _expect_string(data.get("value_type"), f"{label}.value_type")
    if value_type not in {"opaque_id", "positive_integer"}:
        _fail(f"{label}.value_type is not public grammar")
    minimum = data.get("minimum")
    maximum = data.get("maximum")
    if minimum is not None and type(minimum) is not int:
        _fail(f"{label}.minimum must be an integer or null")
    if maximum is not None and type(maximum) is not int:
        _fail(f"{label}.maximum must be an integer or null")
    if value_type == "positive_integer" and (
        minimum is None or minimum < 1 or (maximum is not None and maximum < minimum)
    ):
        _fail(f"{label} positive integer bounds are invalid")
    if value_type == "opaque_id" and (minimum is not None or maximum is not None):
        _fail(f"{label} opaque IDs may not have numeric bounds")
    return ParameterGrammar(
        name=_expect_identifier(data.get("name"), f"{label}.name"),
        value_type=value_type,
        required=_expect_bool(data.get("required"), f"{label}.required"),
        minimum=minimum,
        maximum=maximum,
    )


def _parse_parameter_list(value: object, label: str) -> tuple[ParameterGrammar, ...]:
    if not isinstance(value, list):
        _fail(f"{label} must be a list")
    result = tuple(_parse_parameter(item, label) for item in value)
    names = tuple(item.name for item in result)
    if len(set(names)) != len(names):
        _fail(f"{label} names must be unique")
    return result


def _parse_endpoint(value: object) -> EndpointContract:
    data = _expect_object(value, "endpoint")
    _expect_closed_keys(
        data,
        {
            "endpoint_id",
            "method",
            "path",
            "principal",
            "authority",
            "request",
            "success",
            "retry",
            "timeout_policy_ref",
        },
        "endpoint",
    )
    request_data = _expect_object(data.get("request"), "endpoint.request")
    _expect_closed_keys(
        request_data,
        {"path_parameters", "query_parameters", "body"},
        "endpoint.request",
    )
    success_data = _expect_object(data.get("success"), "endpoint.success")
    _expect_closed_keys(
        success_data,
        {
            "available",
            "root_success",
            "statuses",
            "envelope",
            "required_fields",
            "revision_required_fields",
        },
        "endpoint.success",
    )
    statuses_value = success_data.get("statuses")
    if not isinstance(statuses_value, list):
        _fail("success.statuses must be a list")
    statuses: list[int] = []
    for status in statuses_value:
        if type(status) is not int or status < 200 or status > 299:
            _fail("success.statuses must be HTTP success status integers")
        statuses.append(status)
    raw_root_success = success_data.get("root_success")
    root_success = (
        None
        if raw_root_success is None
        else _expect_bool(raw_root_success, "endpoint.success.root_success")
    )
    retry_data = _expect_object(data.get("retry"), "endpoint.retry")
    _expect_closed_keys(retry_data, {"mode", "identity_fields"}, "endpoint.retry")
    endpoint = EndpointContract(
        endpoint_id=_expect_identifier(data.get("endpoint_id"), "endpoint.endpoint_id"),
        method=_expect_string(data.get("method"), "endpoint.method"),
        path=_expect_string(data.get("path"), "endpoint.path"),
        principal=_expect_string(data.get("principal"), "endpoint.principal"),
        authority=_expect_string(data.get("authority"), "endpoint.authority"),
        request=EndpointRequest(
            path_parameters=_parse_parameter_list(
                request_data.get("path_parameters"), "endpoint.path_parameters"
            ),
            query_parameters=_parse_parameter_list(
                request_data.get("query_parameters"), "endpoint.query_parameters"
            ),
            body=_expect_string(request_data.get("body"), "endpoint.request.body"),
        ),
        success=EndpointSuccess(
            available=_expect_bool(success_data.get("available"), "endpoint.success.available"),
            root_success=root_success,
            statuses=tuple(statuses),
            envelope=_expect_string(success_data.get("envelope"), "endpoint.success.envelope"),
            required_fields=_expect_string_tuple(
                success_data.get("required_fields"),
                "endpoint.success.required_fields",
                allow_empty=True,
            ),
            revision_required_fields=_expect_string_tuple(
                success_data.get("revision_required_fields"),
                "endpoint.success.revision_required_fields",
                allow_empty=True,
            ),
        ),
        retry=EndpointRetry(
            mode=_expect_string(retry_data.get("mode"), "endpoint.retry.mode"),
            identity_fields=_expect_string_tuple(
                retry_data.get("identity_fields"),
                "endpoint.retry.identity_fields",
                allow_empty=True,
            ),
        ),
        timeout_policy_ref=_expect_identifier(
            data.get("timeout_policy_ref"), "endpoint.timeout_policy_ref"
        ),
    )
    if endpoint.success.available:
        if (
            endpoint.success.root_success is not True
            or not endpoint.success.statuses
            or endpoint.success.envelope != "root"
            or not {"success", "data"}.issubset(endpoint.success.required_fields)
        ):
            _fail("available success responses require root success=true and data envelope")
    elif (
        endpoint.success.root_success is not None
        or endpoint.success.statuses
        or endpoint.success.envelope != "blocked"
        or endpoint.success.required_fields
        or endpoint.success.revision_required_fields
    ):
        _fail("blocked endpoints may not declare a reachable success response")
    if endpoint.method not in {"GET", "POST", "DELETE"}:
        _fail("endpoint method is outside the public contract")
    if (
        re.fullmatch(
            r"/api/v[1-9][0-9]*(?:/[a-z0-9-]+|/\{[a-z][a-z0-9_]*\})+",
            endpoint.path,
        )
        is None
    ):
        _fail("endpoint path is not versioned public REST grammar")
    placeholders = tuple(re.findall(r"\{([a-z][a-z0-9_]*)\}", endpoint.path))
    if placeholders != tuple(item.name for item in endpoint.request.path_parameters):
        _fail("endpoint path parameters do not match public path placeholders")
    if endpoint.principal not in {"source_reader", "test_writer"}:
        _fail("endpoint principal is not approved")
    if endpoint.method == "GET":
        if endpoint.principal != "source_reader":
            _fail("GET endpoints must use source_reader")
        if endpoint.retry.mode not in {"bounded_get", "never"}:
            _fail("GET retry mode must be bounded_get or never")
    else:
        if (
            endpoint.principal != "test_writer"
            or endpoint.authority != "stimulus_only"
            or endpoint.retry.mode != "never"
        ):
            _fail("mutation endpoints must be non-retried test_writer stimuli")
    if any(
        operation in endpoint.endpoint_id or f"/{operation}" in endpoint.path
        for operation in ("history", "diff", "edit", "revert")
    ):
        _fail("ordinary Wiki operations are excluded from the W1 plugin contract")
    return endpoint


def _parse_typed_error(value: object) -> TypedErrorContract:
    data = _expect_object(value, "typed error")
    _expect_closed_keys(
        data,
        {
            "code",
            "reason",
            "status",
            "disposition",
            "root_success",
            "envelope",
            "required_fields",
            "error_required_fields",
            "last_committed",
            "last_committed_required_fields",
        },
        "typed error",
    )
    status = data.get("status")
    if type(status) is not int or status < 400 or status > 599:
        _fail("typed error status must be an HTTP error status")
    error = TypedErrorContract(
        code=_expect_identifier(data.get("code"), "typed error.code"),
        reason=_expect_string(data.get("reason"), "typed error.reason"),
        status=status,
        disposition=_expect_string(data.get("disposition"), "typed error.disposition"),
        root_success=_expect_bool(data.get("root_success"), "typed error.root_success"),
        envelope=_expect_string(data.get("envelope"), "typed error.envelope"),
        required_fields=_expect_string_tuple(
            data.get("required_fields"), "typed error.required_fields"
        ),
        error_required_fields=_expect_string_tuple(
            data.get("error_required_fields"),
            "typed error.error_required_fields",
        ),
        last_committed=_expect_string(data.get("last_committed"), "typed error.last_committed"),
        last_committed_required_fields=_expect_string_tuple(
            data.get("last_committed_required_fields"),
            "typed error.last_committed_required_fields",
            allow_empty=True,
        ),
    )
    if (
        error.root_success
        or error.envelope != "root"
        or error.required_fields != ("success", "error")
        or "code" not in error.error_required_fields
    ):
        _fail("typed errors require root success=false and a typed error envelope")
    prior_commit_reasons = {"attempt_in_progress", "attempt_terminal"}
    if error.code == "revision_not_committed" and error.reason in prior_commit_reasons:
        if (
            error.last_committed != "required_when_prior_committed"
            or error.last_committed_required_fields
            != ("parse_attempt", "manifest_digest", "completed_at")
        ):
            _fail("active attempts must conditionally freeze the prior committed descriptor")
    elif error.last_committed != "forbidden" or error.last_committed_required_fields:
        _fail("only active attempts may expose last_committed")
    return error


def _parse_string_map(value: object, label: str) -> tuple[tuple[str, str], ...]:
    data = _expect_object(value, label)
    return tuple(
        (
            _expect_identifier(key, f"{label} key"),
            _expect_string(item, f"{label}.{key}"),
        )
        for key, item in data.items()
    )


def _parse_retry_policy(value: object) -> RetryPolicy:
    data = _expect_object(value, "retry_policy")
    _expect_closed_keys(
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
        _fail("retry_policy.bounded_attempts must be bounded from 1 through 5")
    statuses_value = _expect_list(data.get("retryable_statuses"), "retry_policy.retryable_statuses")
    statuses: list[int] = []
    for status in statuses_value:
        if type(status) is not int or status not in {408, 425, 429, 500, 502, 503, 504}:
            _fail("retry_policy contains an unapproved retryable status")
        statuses.append(status)
    policy = RetryPolicy(
        allowed_methods=_expect_string_tuple(
            data.get("allowed_methods"), "retry_policy.allowed_methods"
        ),
        bounded_attempts=bounded_attempts,
        retryable_statuses=tuple(statuses),
        mutation_auto_retry=_expect_bool(
            data.get("mutation_auto_retry"), "retry_policy.mutation_auto_retry"
        ),
    )
    if policy.allowed_methods != ("GET",) or policy.mutation_auto_retry:
        _fail("only GET may be retried and mutations must never auto retry")
    return policy


def _parse_timeout_policy(value: object) -> TimeoutPolicy:
    data = _expect_object(value, "timeout_policy")
    _expect_closed_keys(
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
            _fail(f"timeout_policy.{field} must be between 1 and 300 seconds")
        values[field] = raw_value
    if not (values["connect_seconds"] <= values["read_seconds"] <= values["overall_seconds"]):
        _fail("timeout_policy budgets must be monotonically bounded")
    return TimeoutPolicy(
        policy_id=_expect_identifier(data.get("policy_id"), "timeout_policy.policy_id"),
        connect_seconds=values["connect_seconds"],
        read_seconds=values["read_seconds"],
        overall_seconds=values["overall_seconds"],
    )


def _parse_idempotency(value: object) -> IdempotencyIdentities:
    data = _expect_object(value, "idempotency_identities")
    values = tuple(
        (
            _expect_identifier(key, "idempotency endpoint ID"),
            _expect_string_tuple(item, f"idempotency_identities.{key}"),
        )
        for key, item in data.items()
    )
    return IdempotencyIdentities(values)


def _parse_readiness(value: object) -> tuple[ReadinessSignal, ...]:
    result: list[ReadinessSignal] = []
    for raw_signal in _expect_list(value, "readiness_signals"):
        data = _expect_object(raw_signal, "readiness signal")
        _expect_closed_keys(data, {"signal_id", "status", "requires"}, "readiness signal")
        result.append(
            ReadinessSignal(
                signal_id=_expect_identifier(data.get("signal_id"), "readiness signal.signal_id"),
                status=_expect_string(data.get("status"), "readiness signal.status"),
                requires=_expect_string_tuple(
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
        _fail("readiness signals must remain three independent ordered signals")
    return tuple(result)


def _resolve_existing_test_ref(repository_root: Path, test_ref: str) -> None:
    parts = test_ref.split("::")
    if len(parts) != 2:
        _fail("existing validation node must use repository/path::function")
    relative_path, function_name = parts
    if (
        _REPOSITORY_REF_RE.fullmatch(relative_path) is None
        or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", function_name) is None
    ):
        _fail("existing validation node reference is not normalized")
    candidate = (repository_root / relative_path).resolve()
    if not candidate.is_relative_to(repository_root.resolve()) or not candidate.is_file():
        _fail("existing validation node file does not exist")
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
        _fail("existing validation node function does not exist")


def _parse_validation_lanes(value: object, repository_root: Path) -> tuple[ValidationLane, ...]:
    lanes: list[ValidationLane] = []
    all_node_ids: list[str] = []
    for raw_lane in _expect_list(value, "validation_lanes"):
        data = _expect_object(raw_lane, "validation lane")
        _expect_closed_keys(data, {"lane_id", "nodes"}, "validation lane")
        lane_id = _expect_identifier(data.get("lane_id"), "validation lane.lane_id")
        nodes: list[ValidationNode] = []
        for raw_node in _expect_list(data.get("nodes"), "validation lane.nodes"):
            node_data = _expect_object(raw_node, "validation node")
            _expect_closed_keys(
                node_data,
                {"node_id", "test_ref", "status", "required_by", "proves"},
                "validation node",
            )
            node_id = _expect_semantic_id(node_data.get("node_id"), "validation node.node_id")
            test_ref = _expect_string(node_data.get("test_ref"), "validation node.test_ref")
            if (
                re.fullmatch(
                    r"[a-zA-Z0-9_./-]+::[a-zA-Z_][a-zA-Z0-9_]*",
                    test_ref,
                )
                is None
            ):
                _fail("validation node.test_ref is not an exact declared node")
            status = _expect_string(node_data.get("status"), "validation node.status")
            required_by = _expect_string(
                node_data.get("required_by"), "validation node.required_by"
            )
            proves = _expect_string_tuple(node_data.get("proves"), "validation node.proves")
            if status == "existing":
                if required_by != "code_pr":
                    _fail("existing validation nodes must be required by code_pr")
                _resolve_existing_test_ref(repository_root, test_ref)
            elif status == "planned":
                artifact_plan = lane_id == "artifact_probe" and required_by == "artifact_pr"
                if not artifact_plan:
                    _fail("planned validation node is outside the closed schema")
            else:
                _fail("validation node.status must be existing or planned")
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
        _fail("validation lanes must be planner, compatibility_ci, artifact_probe")
    if len(set(all_node_ids)) != len(all_node_ids):
        _fail("validation node IDs must be globally unique")
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
        _fail("schema-version-1 forbids planned code_pr evidence nodes")
    return tuple(lanes)


def _parse_exclusions(value: object) -> ContractExclusions:
    data = _expect_object(value, "exclusions")
    _expect_closed_keys(data, {"ordinary_wiki_operations", "missions"}, "exclusions")
    exclusions = ContractExclusions(
        ordinary_wiki_operations=_expect_string_tuple(
            data.get("ordinary_wiki_operations"),
            "exclusions.ordinary_wiki_operations",
        ),
        missions=_expect_string_tuple(data.get("missions"), "exclusions.missions"),
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
        _fail("plugin contract exclusions do not match the approved scope")
    return exclusions


def _expect_inventory_ref(value: object, label: str, prefix: str, suffix: str) -> str:
    reference = _expect_string(value, label)
    if (
        _REPOSITORY_REF_RE.fullmatch(reference) is None
        or not reference.startswith(prefix)
        or not reference.endswith(suffix)
    ):
        _fail(f"{label} does not point to the required inventory kind")
    return reference


def load_plugin_contract(path: Path, *, repository_root: Path | None = None) -> PluginContract:
    """Load the closed Harness-to-WeKnora public plugin contract."""

    data = _expect_object(_load_yaml(path, "plugin contract"), "plugin contract")
    _expect_closed_keys(
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
        _fail("plugin contract schema_version must be 1")
    contract_version = data.get("contract_version")
    if type(contract_version) is not int or contract_version != 1:
        _fail("plugin contract contract_version must be 1 for schema_version 1")
    contract_id = _expect_string(data.get("contract_id"), "plugin contract.contract_id")
    if contract_id != "harness-weknora-w1-plugin":
        _fail("plugin contract.contract_id is not the approved stable ID")
    states = _parse_states(data.get("states"))
    timeout_policy = _parse_timeout_policy(data.get("timeout_policy"))
    endpoints = tuple(
        _parse_endpoint(item)
        for item in _expect_list(data.get("endpoints"), "plugin contract.endpoints")
    )
    typed_errors = tuple(
        _parse_typed_error(item)
        for item in _expect_list(data.get("typed_errors"), "plugin contract.typed_errors")
    )
    lifecycle_dispositions = _parse_string_map(
        data.get("lifecycle_dispositions"), "lifecycle_dispositions"
    )
    if dict(lifecycle_dispositions) != {
        "failed": "preserve_prior_source_head",
        "cancelled": "preserve_prior_source_head",
    }:
        _fail("failed and cancelled attempts must preserve prior SourceHead")
    idempotency = _parse_idempotency(data.get("idempotency_identities"))
    readiness_signals = _parse_readiness(data.get("readiness_signals"))
    validation_lanes = _parse_validation_lanes(
        data.get("validation_lanes"),
        (repository_root or _REPOSITORY_ROOT).resolve(),
    )
    planned_nodes = tuple(
        node for lane in validation_lanes for node in lane.nodes if node.status == "planned"
    )
    if planned_nodes and states.artifact_gate.available:
        _fail("planned artifact nodes cannot count as a ready artifact gate")
    adoption_target_ref = _expect_inventory_ref(
        data.get("adoption_target_ref"),
        "plugin contract.adoption_target_ref",
        "deploy/upstream/",
        "-adoption-target.json",
    )
    patch_inventory_ref = _expect_inventory_ref(
        data.get("patch_inventory_ref"),
        "plugin contract.patch_inventory_ref",
        "deploy/patches/",
        "-patch-inventory.yaml",
    )
    transports = _parse_transports(data.get("transports"))
    principals = _parse_principals(data.get("principals"))
    retry_policy = _parse_retry_policy(data.get("retry_policy"))
    exclusions = _parse_exclusions(data.get("exclusions"))
    if re.fullmatch(r"[0-9a-f]{64}", PLUGIN_CONTRACT_SCHEMA_V1_SHA256) is None:
        _fail("schema-version-1 plugin contract trust anchor is invalid")
    semantic_digest = hashlib.sha256(_canonical_semantic_json(data)).hexdigest()
    if semantic_digest != PLUGIN_CONTRACT_SCHEMA_V1_SHA256:
        _fail("schema-version-1 plugin contract digest mismatch")
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


def _expect_sha(value: object, label: str) -> str:
    identity = _expect_string(value, label)
    if _SHA_RE.fullmatch(identity) is None:
        _fail(f"{label} must be a full lowercase Git SHA")
    return identity


def _expect_release_tag(value: object) -> str:
    tag = _expect_string(value, "release_ancestor.tag")
    if _RELEASE_TAG_RE.fullmatch(tag) is None:
        _fail("release_ancestor.tag must be an immutable normalized release tag")
    return tag


@dataclass(frozen=True)
class ReleaseAncestor:
    tag: str
    commit: str


@dataclass(frozen=True)
class AdoptionTarget:
    schema_version: int
    repository: str
    commit: str
    tree: str
    release_ancestor: ReleaseAncestor
    required_capability_commits: tuple[str, ...]
    official_migration_head: int


@dataclass(frozen=True)
class DiscoveryRevision:
    commit: str
    tree: str
    official_migration_head: int

    def __post_init__(self) -> None:
        _expect_sha(self.commit, "discovered commit")
        _expect_sha(self.tree, "discovered tree")
        if (
            type(self.official_migration_head) is not int
            or self.official_migration_head < 1
            or self.official_migration_head > 2_147_483_647
        ):
            _fail("discovered migration head must be a positive 32-bit integer")


class _DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_target(value: object) -> AdoptionTarget:
    data = _expect_object(value, "adoption target")
    if set(data) != _MANIFEST_KEYS:
        _fail("adoption target keys do not match the closed schema")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        _fail("schema_version must be 1")

    repository = _expect_string(data.get("repository"), "repository")
    if repository != _REPOSITORY:
        _fail("repository must be the reviewed Tencent upstream HTTPS URL")

    release_data = _expect_object(data.get("release_ancestor"), "release_ancestor")
    if set(release_data) != _RELEASE_KEYS:
        _fail("release_ancestor keys do not match the closed schema")
    release = ReleaseAncestor(
        tag=_expect_release_tag(release_data.get("tag")),
        commit=_expect_sha(release_data.get("commit"), "release_ancestor.commit"),
    )

    capabilities_value = data.get("required_capability_commits")
    if not isinstance(capabilities_value, list) or not capabilities_value:
        _fail("required_capability_commits must be a non-empty list")
    capabilities = tuple(
        _expect_sha(item, "required capability commit") for item in capabilities_value
    )
    if len(set(capabilities)) != len(capabilities):
        _fail("required_capability_commits must be unique")

    migration_head = data.get("official_migration_head")
    if type(migration_head) is not int or migration_head < 1 or migration_head > 2_147_483_647:
        _fail("official_migration_head must be a positive 32-bit integer")

    return AdoptionTarget(
        schema_version=1,
        repository=repository,
        commit=_expect_sha(data.get("commit"), "commit"),
        tree=_expect_sha(data.get("tree"), "tree"),
        release_ancestor=release,
        required_capability_commits=capabilities,
        official_migration_head=migration_head,
    )


def load_adoption_target(path: Path) -> AdoptionTarget:
    """Read and fail-closed validate an immutable adoption target manifest."""

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except _DuplicateKeyError as exc:
        raise AdoptionTargetError(str(exc)) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdoptionTargetError("adoption target manifest is unreadable") from exc
    return _parse_target(value)


def _run_git(cwd: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ("git", *args),
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AdoptionTargetError("git check failed") from exc
    return completed.stdout.strip()


def _load_runtime_source_lock(path: Path) -> tuple[str, str, str]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (_DuplicateKeyError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdoptionTargetError("runtime source lock is unreadable") from exc
    data = _expect_object(value, "runtime source lock")
    if data.get("schema_version") != 1 or data.get("repository") != _REPOSITORY:
        _fail("runtime source lock identity is invalid")
    return (
        _REPOSITORY,
        _expect_sha(data.get("commit"), "runtime source lock commit"),
        _expect_sha(data.get("tree"), "runtime source lock tree"),
    )


def _load_w1_paths(path: Path) -> tuple[str, ...]:
    data = _expect_object(_load_yaml(path, "patch inventory"), "patch inventory")
    patches = data.get("patches")
    if not isinstance(patches, list):
        _fail("patch inventory patches must be a list")
    matches = [
        _expect_object(item, "patch inventory entry")
        for item in patches
        if isinstance(item, dict) and item.get("patch_id") == "W1"
    ]
    if len(matches) != 1:
        _fail("patch inventory must contain exactly one W1")
    raw_paths = matches[0].get("file_path")
    if not isinstance(raw_paths, list) or not raw_paths:
        _fail("W1 file_path must be a non-empty list")
    paths = tuple(_expect_string(item, "W1 file_path") for item in raw_paths)
    canonical_paths = all(
        PurePosixPath(item).as_posix() == item
        and bool(PurePosixPath(item).parts)
        and not PurePosixPath(item).is_absolute()
        and "." not in PurePosixPath(item).parts
        and "\\" not in item
        for item in paths
    )
    if (
        len(set(paths)) != len(paths)
        or not canonical_paths
        or any(_REPOSITORY_REF_RE.fullmatch(item) is None for item in paths)
    ):
        _fail("W1 file_path values must be unique repository paths")
    return tuple(sorted(paths))


def _empty_check_report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "verdict": "block",
        "target": {},
        "hard_checks": {"code": "not_checked", "status": "block"},
        "overlaps": {
            "project_merge_base_to_target": [],
            "runtime_to_target": [],
        },
        "official_migrations": {"status": "not_checked", "head": 0, "files": []},
        "plugin_contract": {
            "digest": "",
            "existing": 0,
            "planned_artifact": 0,
            "planned_code": 0,
            "status": "not_checked",
        },
    }


def _blocked(report: dict[str, object], code: str) -> dict[str, object]:
    report["verdict"] = "block"
    report["hard_checks"] = {"code": code, "status": "block"}
    return report


def _official_migrations(
    checkout: Path, head: int
) -> tuple[list[dict[str, str]], dict[str, bytes]]:
    root = checkout / "migrations" / "versioned"
    pairs: dict[int, dict[str, tuple[str, Path]]] = {}
    for path in sorted(root.rglob("*.sql")):
        relative = path.relative_to(root).as_posix()
        match = _OFFICIAL_MIGRATION_RE.fullmatch(relative)
        if match is None:
            _fail("official migration filename is invalid")
        version = int(match.group("version"))
        direction = match.group("direction")
        by_direction = pairs.setdefault(version, {})
        if direction in by_direction:
            _fail("official migration direction is duplicated")
        by_direction[direction] = (match.group("name"), path)
    if set(pairs) != set(range(0, head + 1)):
        _fail("official migration versions do not match the manifest head")
    files: list[dict[str, str]] = []
    raw: dict[str, bytes] = {}
    for version in sorted(pairs):
        pair = pairs[version]
        if set(pair) != {"up", "down"} or pair["up"][0] != pair["down"][0]:
            _fail("official migration pair is invalid")
        for direction in ("up", "down"):
            path = pair[direction][1]
            relative = path.relative_to(checkout).as_posix()
            content = path.read_bytes()
            raw[relative] = content
            files.append({"path": relative, "sha256": hashlib.sha256(content).hexdigest()})
    return files, raw


def _plugin_summary(contract: PluginContract) -> dict[str, object]:
    nodes = [node for lane in contract.validation_lanes for node in lane.nodes]
    return {
        "digest": PLUGIN_CONTRACT_SCHEMA_V1_SHA256,
        "existing": sum(node.status == "existing" for node in nodes),
        "planned_artifact": sum(
            node.status == "planned" and node.required_by == "artifact_pr" for node in nodes
        ),
        "planned_code": sum(
            node.status == "planned" and node.required_by == "code_pr" for node in nodes
        ),
        "status": "valid",
    }


def run_adoption_check(
    *,
    target_manifest: Path,
    project_checkout: Path,
    target_checkout: Path,
    runtime_source_lock: Path,
    inventory: Path,
    plugin_contract: Path,
) -> dict[str, object]:
    """Run the finite, read-only adoption check and return sanitized JSON data."""

    report = _empty_check_report()
    try:
        target = load_adoption_target(target_manifest)
    except AdoptionTargetError:
        return _blocked(report, "target_manifest_invalid")
    report["target"] = {
        "commit": target.commit,
        "repository": target.repository,
        "tree": target.tree,
    }

    try:
        if _run_git(target_checkout, "status", "--porcelain"):
            return _blocked(report, "target_dirty")
        origin = _run_git(target_checkout, "remote", "get-url", "origin")
        if origin.rstrip("/").removesuffix(".git") != _REPOSITORY.removesuffix(".git"):
            return _blocked(report, "target_origin_mismatch")
        if _run_git(target_checkout, "rev-parse", "HEAD") != target.commit:
            return _blocked(report, "target_head_mismatch")
        if _run_git(target_checkout, "rev-parse", "HEAD^{tree}") != target.tree:
            return _blocked(report, "target_tree_mismatch")
        for ancestor in (
            target.release_ancestor.commit,
            *target.required_capability_commits,
        ):
            _run_git(
                target_checkout,
                "merge-base",
                "--is-ancestor",
                ancestor,
                target.commit,
            )
    except AdoptionTargetError:
        return _blocked(report, "target_ancestor_missing")

    try:
        contract = load_plugin_contract(plugin_contract, repository_root=project_checkout)
    except AdoptionTargetError:
        return _blocked(report, "plugin_contract_invalid")
    canonical_inventory = (project_checkout / contract.patch_inventory_ref).resolve()
    if inventory.resolve() != canonical_inventory:
        return _blocked(report, "inventory_path_mismatch")
    report["plugin_contract"] = _plugin_summary(contract)
    try:
        _, runtime_commit, runtime_tree = _load_runtime_source_lock(runtime_source_lock)
        w1_paths = set(_load_w1_paths(canonical_inventory))
    except AdoptionTargetError:
        return _blocked(report, "runtime_or_inventory_invalid")
    try:
        _run_git(project_checkout, "cat-file", "-e", f"{runtime_commit}^{{commit}}")
        if _run_git(project_checkout, "rev-parse", f"{runtime_commit}^{{tree}}") != runtime_tree:
            return _blocked(report, "runtime_tree_mismatch")
        project_head = _run_git(project_checkout, "rev-parse", "HEAD")
        merge_base = _run_git(project_checkout, "merge-base", project_head, target.commit)
        project_delta = set(
            _run_git(
                project_checkout,
                "diff",
                "--name-only",
                f"{merge_base}..{target.commit}",
            ).splitlines()
        )
        runtime_delta = set(
            _run_git(
                project_checkout,
                "diff",
                "--name-only",
                f"{runtime_commit}..{target.commit}",
            ).splitlines()
        )
    except AdoptionTargetError:
        return _blocked(report, "git_delta_invalid")
    report["overlaps"] = {
        "project_merge_base_to_target": sorted(w1_paths & project_delta),
        "runtime_to_target": sorted(w1_paths & runtime_delta),
    }

    try:
        migration_files, target_bytes = _official_migrations(
            target_checkout, target.official_migration_head
        )
    except (AdoptionTargetError, OSError):
        return _blocked(report, "official_migrations_invalid")
    merged = True
    try:
        _run_git(
            project_checkout,
            "merge-base",
            "--is-ancestor",
            target.commit,
            project_head,
        )
    except AdoptionTargetError:
        merged = False
    report["official_migrations"] = {
        "status": "merged" if merged else "pre_merge",
        "head": target.official_migration_head,
        "files": migration_files,
    }
    if merged:
        try:
            _, project_bytes = _official_migrations(
                project_checkout, target.official_migration_head
            )
        except (AdoptionTargetError, OSError):
            return _blocked(report, "project_migrations_mismatch")
        if project_bytes != target_bytes:
            return _blocked(report, "project_migrations_mismatch")

    overlaps = report["overlaps"]
    assert isinstance(overlaps, dict)
    has_overlap = bool(overlaps["project_merge_base_to_target"] or overlaps["runtime_to_target"])
    report["verdict"] = "manual_review_required" if has_overlap else "pass"
    report["hard_checks"] = {"code": "ok", "status": "pass"}
    return report


class DiscoveryResolver(Protocol):
    """Read-only interface used to resolve mutable discovery channels."""

    def latest_release_tag(self, repository: str) -> str: ...

    def resolve_revision(self, repository: str, ref: str) -> DiscoveryRevision: ...

    def is_ancestor(self, repository: str, ancestor: str, descendant: str) -> bool: ...


class GitHubDiscoveryResolver:
    """Resolve WeKnora identities through read-only GitHub API requests."""

    def _fetch_json(self, endpoint: str) -> object:
        request = urllib.request.Request(
            f"{_GITHUB_API}{endpoint}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "weknora-adoption-discovery",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except (
            OSError,
            ValueError,
            urllib.error.HTTPError,
            urllib.error.URLError,
        ) as exc:
            raise AdoptionTargetError("GitHub discovery request failed") from exc

    def _check_repository(self, repository: str) -> None:
        if repository != _REPOSITORY:
            _fail("discovery repository is not the reviewed upstream")

    def latest_release_tag(self, repository: str) -> str:
        self._check_repository(repository)
        data = _expect_object(self._fetch_json("/releases/latest"), "latest release")
        return _expect_release_tag(data.get("tag_name"))

    def _migration_head(self, tree: str) -> int:
        tree_data = _expect_object(
            self._fetch_json(f"/git/trees/{tree}?recursive=1"),
            "resolved revision tree listing",
        )
        if tree_data.get("truncated") is True:
            _fail("resolved revision tree listing is truncated")
        entries = tree_data.get("tree")
        if not isinstance(entries, list):
            _fail("resolved revision tree listing must contain entries")

        versions: list[int] = []
        for raw_entry in entries:
            entry = _expect_object(raw_entry, "resolved revision tree entry")
            path = entry.get("path")
            if entry.get("type") != "blob" or not isinstance(path, str):
                continue
            match = _MIGRATION_PATH_RE.fullmatch(path)
            if match is not None:
                versions.append(int(match.group("head")))
        if not versions:
            _fail("resolved revision has no official versioned migrations")
        return max(versions)

    def resolve_revision(self, repository: str, ref: str) -> DiscoveryRevision:
        self._check_repository(repository)
        encoded_ref = urllib.parse.quote(ref, safe="")
        data = _expect_object(self._fetch_json(f"/commits/{encoded_ref}"), "resolved revision")
        commit_data = _expect_object(data.get("commit"), "resolved revision.commit")
        tree_data = _expect_object(commit_data.get("tree"), "resolved revision tree")
        tree = _expect_sha(tree_data.get("sha"), "resolved tree")
        return DiscoveryRevision(
            commit=_expect_sha(data.get("sha"), "resolved commit"),
            tree=tree,
            official_migration_head=self._migration_head(tree),
        )

    def is_ancestor(self, repository: str, ancestor: str, descendant: str) -> bool:
        self._check_repository(repository)
        ancestor = _expect_sha(ancestor, "ancestor")
        descendant = _expect_sha(descendant, "descendant")
        data = _expect_object(
            self._fetch_json(f"/compare/{ancestor}...{descendant}"),
            "commit comparison",
        )
        return data.get("status") in {"ahead", "identical"}


def _proposal(
    channel: str,
    resolver: DiscoveryResolver,
) -> AdoptionTarget:
    if channel not in _CHANNELS:
        _fail("discovery channel must be latest-stable or mainline-head")

    release_tag = _expect_release_tag(resolver.latest_release_tag(_REPOSITORY))
    release_revision = resolver.resolve_revision(_REPOSITORY, f"refs/tags/{release_tag}")
    target_revision = (
        release_revision
        if channel == "latest-stable"
        else resolver.resolve_revision(_REPOSITORY, "refs/heads/main")
    )

    if not resolver.is_ancestor(_REPOSITORY, release_revision.commit, target_revision.commit):
        _fail("latest stable release is not an ancestor of the discovered target")
    if not resolver.is_ancestor(_REPOSITORY, _CAPABILITY_COMMIT, target_revision.commit):
        _fail("reviewed capability commit is not an ancestor of the discovered target")

    return AdoptionTarget(
        schema_version=1,
        repository=_REPOSITORY,
        commit=target_revision.commit,
        tree=target_revision.tree,
        release_ancestor=ReleaseAncestor(
            tag=release_tag,
            commit=release_revision.commit,
        ),
        required_capability_commits=(_CAPABILITY_COMMIT,),
        official_migration_head=target_revision.official_migration_head,
    )


def render_discovery_proposal(channel: str, *, resolver: DiscoveryResolver | None = None) -> str:
    """Return a deterministic immutable proposal without writing any state."""

    target = _proposal(channel, resolver or GitHubDiscoveryResolver())
    value = asdict(target)
    value["required_capability_commits"] = list(target.required_capability_commits)
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


class _UsageError(ValueError):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _UsageError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    discover = subparsers.add_parser("discover")
    discover.add_argument("--channel", choices=_CHANNELS)
    check = subparsers.add_parser("check")
    for name in (
        "target-manifest",
        "project-checkout",
        "target-checkout",
        "runtime-source-lock",
        "inventory",
        "plugin-contract",
    ):
        check.add_argument(f"--{name}", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None, *, resolver: DiscoveryResolver | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    except _UsageError as exc:
        parser.print_usage(sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command is None:
        parser.print_usage(sys.stderr)
        print("error: a command is required", file=sys.stderr)
        return 2

    if args.command == "check":
        result = run_adoption_check(
            target_manifest=args.target_manifest,
            project_checkout=args.project_checkout,
            target_checkout=args.target_checkout,
            runtime_source_lock=args.runtime_source_lock,
            inventory=args.inventory,
            plugin_contract=args.plugin_contract,
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return int(result["verdict"] == "block")

    if args.channel is None:
        parser.print_usage(sys.stderr)
        print("error: discover and --channel are required", file=sys.stderr)
        return 2
    try:
        rendered = render_discovery_proposal(args.channel, resolver=resolver)
    except AdoptionTargetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
