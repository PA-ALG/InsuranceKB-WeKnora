"""Fail-closed, zero-inference provider deployment metadata probes."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self
from urllib.parse import unquote, urlsplit

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from insurance_harness.goldenset.admission_models import ModelRolePlan

type NonBlankStr = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1)
]
type ProbeMode = Literal["static", "remote"]
type ProbeRole = Literal["annotator", "weak_extractor", "judge"]
type ProbeStatusClass = Literal[
    "not_attempted",
    "success",
    "redirect",
    "client_error",
    "server_error",
    "transport_error",
]
type ProbeBlockerCode = Literal[
    "authentication_failed",
    "credential_env_not_allowed",
    "credential_missing",
    "deployment_not_running",
    "model_identity_mismatch",
    "model_identity_pending",
    "model_metadata_invalid",
    "model_not_found",
    "policy_mismatch",
    "price_observation_expired",
    "price_observation_missing",
    "probe_failed",
    "probe_not_performed",
    "probe_observation_expired",
    "probe_unreachable",
    "redirect_rejected",
    "test_policy_not_allowed",
    "unsafe_probe_configuration",
]

_PRODUCTION_POLICY_ID = "bailian-deployment-detail-v1"
_PROBE_TIMEOUT_SECONDS = 10.0
_MAX_METADATA_BYTES = 64 * 1024
_DEPLOYED_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_BASE_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_REVISION_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?$"
)
_DEPLOYMENT_STATUSES = frozenset(
    {"CREATING", "PENDING", "RUNNING", "UPDATING", "STOPPED", "FAILED", "DELETING"}
)
_ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_TEST_METADATA_PATH_TEMPLATE = "/metadata/{deployed_model}"


class _ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def copy(
        self,
        *,
        include: object = None,
        exclude: object = None,
        update: dict[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        raise TypeError("copy() is disabled; use validated model_copy()")

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        if update is None:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class ProbeBlocker(_ImmutableModel):
    """One redacted reason that the model role cannot be admitted."""

    code: ProbeBlockerCode
    message: NonBlankStr


class ProbeRequest(_ImmutableModel):
    """Caller-provided observations; clock, TTL, route, and method are code-owned."""

    role: ProbeRole
    role_plan: ModelRolePlan
    mode: ProbeMode
    probe_observed_at: datetime | None = None
    price_observed_at: datetime | None

    @field_validator("probe_observed_at", "price_observed_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("probe timestamps must include a timezone")
        return value


class ProbeResult(_ImmutableModel):
    """Minimal audit observation; response bodies, headers, and secrets are absent."""

    role: ProbeRole
    verified: bool
    provider: StrictStr | None = None
    model_id: StrictStr | None = None
    endpoint_origin: StrictStr | None = None
    status_class: ProbeStatusClass = "not_attempted"
    latency_ms: StrictInt | None = Field(default=None, ge=0)
    observed_at: datetime | None = None
    observed_revision: StrictStr | None = None
    observed_deployment_id: StrictStr | None = None
    blockers: tuple[ProbeBlocker, ...] = ()

    @model_validator(mode="after")
    def verified_has_no_blockers(self) -> ProbeResult:
        if self.verified == bool(self.blockers):
            raise ValueError("verified results require no blockers and vice versa")
        return self


@dataclass(frozen=True)
class _ProviderProbePolicy:
    policy_id: str
    provider: str
    protocol: Literal["http", "https"]
    inference_origin: str
    inference_base_path: str
    metadata_origin: str
    method: Literal["GET", "HEAD"]
    path_template: str
    credential_env_names: frozenset[str]
    credential_required: bool
    max_probe_age: timedelta
    max_price_observation_age: timedelta
    test_only: bool


@dataclass(frozen=True)
class ProviderProbePolicyRegistry:
    """Immutable registry; production routes cannot be supplied by the plan."""

    _policies: Mapping[str, _ProviderProbePolicy]

    @classmethod
    def code_owned(cls) -> ProviderProbePolicyRegistry:
        policy = _ProviderProbePolicy(
            policy_id=_PRODUCTION_POLICY_ID,
            provider="bailian",
            protocol="https",
            inference_origin="https://dashscope.aliyuncs.com",
            inference_base_path="/compatible-mode/v1",
            metadata_origin="https://dashscope.aliyuncs.com",
            method="GET",
            path_template="/api/v1/deployments/{deployed_model}",
            credential_env_names=frozenset(
                {
                    "DASHSCOPE_API_KEY",
                    "BAILIAN_API_KEY",
                    "HARNESS_DASHSCOPE_API_KEY",
                }
            ),
            credential_required=True,
            max_probe_age=timedelta(minutes=10),
            max_price_observation_age=timedelta(hours=1),
            test_only=False,
        )
        return cls(_policies=MappingProxyType({policy.policy_id: policy}))

    @classmethod
    def _for_testing_loopback(
        cls,
        *,
        policy_id: str,
        origin: str,
        path_template: str,
    ) -> ProviderProbePolicyRegistry:
        parsed_origin = urlsplit(origin)
        if (
            parsed_origin.scheme != "http"
            or parsed_origin.hostname != "127.0.0.1"
            or parsed_origin.username is not None
            or parsed_origin.password is not None
            or parsed_origin.query
            or parsed_origin.fragment
            or parsed_origin.path not in ("", "/")
            or parsed_origin.port is None
        ):
            raise ValueError("test origin must be exact HTTP 127.0.0.1 with port")
        parsed_path = urlsplit(path_template)
        decoded_path = unquote(parsed_path.path)
        if (
            parsed_path.scheme
            or parsed_path.netloc
            or parsed_path.query
            or parsed_path.fragment
            or decoded_path != parsed_path.path
            or decoded_path != _TEST_METADATA_PATH_TEMPLATE
        ):
            raise ValueError("test metadata path template is unsafe")
        normalized_origin = f"http://127.0.0.1:{parsed_origin.port}"
        policy = _ProviderProbePolicy(
            policy_id=policy_id,
            provider="bailian",
            protocol="http",
            inference_origin=normalized_origin,
            inference_base_path="",
            metadata_origin=normalized_origin,
            method="GET",
            path_template=decoded_path,
            credential_env_names=frozenset({"TEST_NO_CREDENTIAL"}),
            credential_required=False,
            max_probe_age=timedelta(minutes=10),
            max_price_observation_age=timedelta(hours=1),
            test_only=True,
        )
        return cls(_policies=MappingProxyType({policy.policy_id: policy}))

    def get(self, policy_id: str) -> _ProviderProbePolicy | None:
        return self._policies.get(policy_id)


type ClientFactory = Callable[..., httpx.Client]
type Clock = Callable[[], datetime]
type Monotonic = Callable[[], float]
type EnvironmentReader = Callable[[str], str | None]


class _DuplicateJsonKey(ValueError):
    pass


class _ProbeDeadlineExceeded(RuntimeError):
    pass


class SafeProviderProbe:
    """Perform one code-owned deployment-detail request, never model inference."""

    def __init__(self) -> None:
        self._initialize(
            policy_registry=ProviderProbePolicyRegistry.code_owned(),
            client_factory=httpx.Client,
            clock=lambda: datetime.now(UTC),
            monotonic=time.monotonic,
            env_reader=os.environ.get,
            allow_test_policy=False,
        )

    @classmethod
    def _for_testing(
        cls,
        *,
        policy_registry: ProviderProbePolicyRegistry,
        client_factory: ClientFactory,
        clock: Clock,
        monotonic: Monotonic,
        env_reader: EnvironmentReader = os.environ.get,
        allow_test_policy: bool = True,
    ) -> SafeProviderProbe:
        instance = cls.__new__(cls)
        instance._initialize(
            policy_registry=policy_registry,
            client_factory=client_factory,
            clock=clock,
            monotonic=monotonic,
            env_reader=env_reader,
            allow_test_policy=allow_test_policy,
        )
        return instance

    def _initialize(
        self,
        *,
        policy_registry: ProviderProbePolicyRegistry,
        client_factory: ClientFactory,
        clock: Clock,
        monotonic: Monotonic,
        env_reader: EnvironmentReader,
        allow_test_policy: bool,
    ) -> None:
        self._policy_registry = policy_registry
        self._client_factory = client_factory
        self._clock = clock
        self._monotonic = monotonic
        self._env_reader = env_reader
        self._allow_test_policy = allow_test_policy

    def run(self, request: ProbeRequest) -> ProbeResult:
        role_plan = self._validated_role_plan(request.role_plan)
        if role_plan is None:
            return self._blocked(request, "unsafe_probe_configuration")
        try:
            request = ProbeRequest.model_validate(
                {
                    "role": request.role,
                    "role_plan": {
                        field_name: getattr(role_plan, field_name)
                        for field_name in ModelRolePlan.model_fields
                    },
                    "mode": request.mode,
                    "probe_observed_at": request.probe_observed_at,
                    "price_observed_at": request.price_observed_at,
                }
            )
        except (AttributeError, TypeError, ValueError):
            return self._blocked(request, "unsafe_probe_configuration")
        safe_provider = self._safe_identifier(request.role_plan.provider)
        safe_model_id = self._safe_model_id(request.role_plan.model_id)
        if request.mode == "static":
            return self._blocked(
                request,
                "probe_not_performed",
                provider=safe_provider,
                model_id=safe_model_id,
            )

        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            return self._blocked(request, "unsafe_probe_configuration")
        policy = self._policy_registry.get(request.role_plan.provider_policy)
        if policy is None:
            return self._blocked(request, "policy_mismatch")
        if policy.test_only and not self._allow_test_policy:
            return self._blocked(
                request,
                "test_policy_not_allowed",
                endpoint_origin=policy.metadata_origin,
            )
        if not policy.test_only and not self._has_invocable_immutable_identity(
            request.role_plan
        ):
            return self._blocked(
                request,
                "model_identity_mismatch",
                provider=safe_provider,
                model_id=safe_model_id,
                endpoint_origin=policy.metadata_origin,
            )

        freshness = self._freshness_blockers(request, policy, now)
        if freshness:
            return self._blocked_many(
                request,
                freshness,
                provider=safe_provider,
                model_id=safe_model_id,
                endpoint_origin=policy.metadata_origin,
            )
        if not self._matches_policy(request.role_plan, policy):
            return self._blocked(
                request,
                self._configuration_blocker_code(request.role_plan, policy),
                endpoint_origin=policy.metadata_origin,
            )
        if not self._credential_env_allowed(request.role_plan.credential_env_name, policy):
            return self._blocked(
                request,
                "credential_env_not_allowed",
                provider=policy.provider,
                model_id=safe_model_id,
                endpoint_origin=policy.metadata_origin,
            )

        headers: dict[str, str] = {"Accept-Encoding": "identity"}
        if policy.credential_required:
            try:
                credential = self._env_reader(request.role_plan.credential_env_name)
            except (KeyError, OSError, TypeError, ValueError):
                return self._blocked(
                    request,
                    "unsafe_probe_configuration",
                    provider=policy.provider,
                    model_id=safe_model_id,
                    endpoint_origin=policy.metadata_origin,
                )
            if credential is None or not credential.strip():
                return self._blocked(
                    request,
                    "credential_missing",
                    provider=policy.provider,
                    model_id=safe_model_id,
                    endpoint_origin=policy.metadata_origin,
                )
            headers["Authorization"] = f"Bearer {credential}"

        endpoint = policy.metadata_origin + policy.path_template.format(
            deployed_model=request.role_plan.model_id
        )
        started = self._monotonic()
        try:
            with self._client_factory(
                verify=True,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                with client.stream(
                    policy.method,
                    endpoint,
                    headers=headers,
                    content=b"",
                    timeout=_PROBE_TIMEOUT_SECONDS,
                ) as response:
                    status_code = response.status_code
                    status_class = self._status_class(status_code)
                    if 300 <= status_code < 400:
                        return self._network_blocked(
                            request,
                            "redirect_rejected",
                            policy,
                            status_class,
                            started,
                        )
                    if status_code in (401, 403):
                        return self._network_blocked(
                            request,
                            "authentication_failed",
                            policy,
                            status_class,
                            started,
                        )
                    if status_code == 404:
                        return self._network_blocked(
                            request,
                            "model_not_found",
                            policy,
                            status_class,
                            started,
                        )
                    if not 200 <= status_code < 300:
                        return self._network_blocked(
                            request,
                            "probe_failed",
                            policy,
                            status_class,
                            started,
                        )
                    content_encoding = response.headers.get("content-encoding")
                    if (
                        content_encoding is not None
                        and content_encoding.casefold() != "identity"
                    ):
                        return self._network_blocked(
                            request,
                            "model_metadata_invalid",
                            policy,
                            "success",
                            started,
                        )
                    body = self._read_limited_body(response, started)
        except (httpx.HTTPError, OSError, RuntimeError, ValueError):
            return self._network_blocked(
                request,
                "probe_unreachable",
                policy,
                "transport_error",
                started,
            )

        if body is None:
            return self._network_blocked(
                request,
                "model_metadata_invalid",
                policy,
                "success",
                started,
            )
        metadata = self._parse_deployment_metadata(body, request.role_plan.model_id)
        if metadata is None:
            return self._network_blocked(
                request,
                "model_metadata_invalid",
                policy,
                "success",
                started,
            )
        deployed_model, base_model, revision, deployment_status = metadata
        if deployment_status != "RUNNING":
            return self._network_blocked(
                request,
                "deployment_not_running",
                policy,
                "success",
                started,
            )
        expected_revision = request.role_plan.expected_model_revision
        if policy.test_only and expected_revision is not None:
            verified = revision == expected_revision
        else:
            verified = (
                deployed_model
                == request.role_plan.immutable_deployment_id
                == request.role_plan.model_id
            )
        if deployed_model != request.role_plan.model_id or not base_model or not verified:
            return self._network_blocked(
                request,
                "model_identity_mismatch",
                policy,
                "success",
                started,
            )
        return ProbeResult(
            role=request.role,
            verified=True,
            provider=policy.provider,
            model_id=request.role_plan.model_id,
            endpoint_origin=policy.metadata_origin,
            status_class="success",
            latency_ms=self._latency_ms(started),
            observed_at=now,
            observed_revision=expected_revision,
            observed_deployment_id=request.role_plan.model_id,
        )

    def _freshness_blockers(
        self,
        request: ProbeRequest,
        policy: _ProviderProbePolicy,
        now: datetime,
    ) -> list[ProbeBlockerCode]:
        blockers: list[ProbeBlockerCode] = []
        if request.probe_observed_at is not None and self._expired(
            now, request.probe_observed_at, policy.max_probe_age
        ):
            blockers.append("probe_observation_expired")
        if request.price_observed_at is None:
            blockers.append("price_observation_missing")
        elif self._expired(
            now,
            request.price_observed_at,
            policy.max_price_observation_age,
        ):
            blockers.append("price_observation_expired")
        return blockers

    @staticmethod
    def _expired(now: datetime, observed_at: datetime, max_age: timedelta) -> bool:
        age = now - observed_at
        return age < timedelta(0) or age > max_age

    @staticmethod
    def _matches_policy(role_plan: ModelRolePlan, policy: _ProviderProbePolicy) -> bool:
        if role_plan.provider != policy.provider:
            return False
        if not _DEPLOYED_MODEL_PATTERN.fullmatch(role_plan.model_id):
            return False
        parsed = urlsplit(role_plan.base_url)
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            return False
        decoded_path = unquote(parsed.path)
        if decoded_path != parsed.path or decoded_path != policy.inference_base_path:
            return False
        if role_plan.protocol != policy.protocol or parsed.scheme != policy.protocol:
            return False
        normalized_origin = f"{parsed.scheme}://{parsed.netloc}"
        return normalized_origin == policy.inference_origin

    @staticmethod
    def _has_invocable_immutable_identity(role_plan: ModelRolePlan) -> bool:
        deployment_id = role_plan.immutable_deployment_id
        return bool(deployment_id is not None and deployment_id == role_plan.model_id)

    @staticmethod
    def _validated_role_plan(role_plan: ModelRolePlan) -> ModelRolePlan | None:
        try:
            return ModelRolePlan.model_validate(
                {
                    field_name: getattr(role_plan, field_name)
                    for field_name in ModelRolePlan.model_fields
                }
            )
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _configuration_blocker_code(
        role_plan: ModelRolePlan, policy: _ProviderProbePolicy
    ) -> ProbeBlockerCode:
        parsed = urlsplit(role_plan.base_url)
        decoded_path = unquote(parsed.path)
        structurally_unsafe = bool(
            parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or decoded_path != parsed.path
            or role_plan.protocol != parsed.scheme
            or not _DEPLOYED_MODEL_PATTERN.fullmatch(role_plan.model_id)
        )
        return "unsafe_probe_configuration" if structurally_unsafe else "policy_mismatch"

    @staticmethod
    def _credential_env_allowed(name: str, policy: _ProviderProbePolicy) -> bool:
        return bool(_ENV_NAME_PATTERN.fullmatch(name) and name in policy.credential_env_names)

    def _read_limited_body(
        self, response: httpx.Response, started: float
    ) -> bytes | None:
        payload = bytearray()
        for chunk in response.iter_bytes():
            if self._monotonic() - started > _PROBE_TIMEOUT_SECONDS:
                raise _ProbeDeadlineExceeded
            if len(payload) + len(chunk) > _MAX_METADATA_BYTES:
                return None
            payload.extend(chunk)
        return bytes(payload)

    @staticmethod
    def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateJsonKey
            result[key] = value
        return result

    @classmethod
    def _parse_deployment_metadata(
        cls, body: bytes, expected_model_id: str
    ) -> tuple[str, str, str, str] | None:
        try:
            payload = json.loads(
                body,
                object_pairs_hook=cls._reject_duplicate_keys,
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            _DuplicateJsonKey,
            RecursionError,
            TypeError,
        ):
            return None
        if not isinstance(payload, dict):
            return None
        output = payload.get("output")
        if not isinstance(output, dict):
            return None
        values = tuple(
            output.get(field)
            for field in ("deployed_model", "base_model", "gmt_modified", "status")
        )
        if not all(isinstance(value, str) for value in values):
            return None
        deployed_model, base_model, revision, status = values
        assert isinstance(deployed_model, str)
        assert isinstance(base_model, str)
        assert isinstance(revision, str)
        assert isinstance(status, str)
        if (
            not _DEPLOYED_MODEL_PATTERN.fullmatch(deployed_model)
            or not _BASE_MODEL_PATTERN.fullmatch(base_model)
            or not cls._valid_revision(revision)
            or status not in _DEPLOYMENT_STATUSES
        ):
            return None
        return (deployed_model, base_model, revision, status)

    @staticmethod
    def _valid_revision(value: str) -> bool:
        if not _REVISION_PATTERN.fullmatch(value):
            return False
        try:
            normalized = value.removesuffix("Z")
            if value.endswith("Z"):
                normalized += "+00:00"
            datetime.fromisoformat(normalized)
        except ValueError:
            return False
        return True

    @staticmethod
    def _status_class(status_code: int) -> ProbeStatusClass:
        if 200 <= status_code < 300:
            return "success"
        if 300 <= status_code < 400:
            return "redirect"
        if 400 <= status_code < 500:
            return "client_error"
        return "server_error"

    def _latency_ms(self, started: float) -> int:
        return max(0, int(round((self._monotonic() - started) * 1000)))

    @staticmethod
    def _safe_identifier(value: str) -> str | None:
        return value if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value) else None

    @staticmethod
    def _safe_model_id(value: str) -> str | None:
        return value if _DEPLOYED_MODEL_PATTERN.fullmatch(value) else None

    @classmethod
    def _safe_revision(cls, value: str | None) -> str | None:
        return value if value is not None and cls._valid_revision(value) else None

    @staticmethod
    def _blocker(code: ProbeBlockerCode) -> ProbeBlocker:
        return ProbeBlocker(code=code, message="provider metadata probe blocked")

    def _blocked(
        self,
        request: ProbeRequest,
        code: ProbeBlockerCode,
        *,
        provider: str | None = None,
        model_id: str | None = None,
        endpoint_origin: str | None = None,
    ) -> ProbeResult:
        return self._blocked_many(
            request,
            [code],
            provider=provider,
            model_id=model_id,
            endpoint_origin=endpoint_origin,
        )

    def _blocked_many(
        self,
        request: ProbeRequest,
        codes: list[ProbeBlockerCode],
        *,
        provider: str | None = None,
        model_id: str | None = None,
        endpoint_origin: str | None = None,
    ) -> ProbeResult:
        return ProbeResult(
            role=request.role,
            verified=False,
            provider=provider,
            model_id=model_id,
            endpoint_origin=endpoint_origin,
            blockers=tuple(self._blocker(code) for code in codes),
        )

    def _network_blocked(
        self,
        request: ProbeRequest,
        code: ProbeBlockerCode,
        policy: _ProviderProbePolicy,
        status_class: ProbeStatusClass,
        started: float,
    ) -> ProbeResult:
        return ProbeResult(
            role=request.role,
            verified=False,
            provider=policy.provider,
            model_id=self._safe_model_id(request.role_plan.model_id),
            endpoint_origin=policy.metadata_origin,
            status_class=status_class,
            latency_ms=self._latency_ms(started),
            observed_at=self._clock(),
            blockers=(self._blocker(code),),
        )


__all__ = [
    "ProbeBlocker",
    "ProbeRequest",
    "ProbeResult",
    "ProviderProbePolicyRegistry",
    "SafeProviderProbe",
]
