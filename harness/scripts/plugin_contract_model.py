"""The closed Harness-to-WeKnora public plugin contract, as frozen values."""

from __future__ import annotations

from dataclasses import dataclass


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
