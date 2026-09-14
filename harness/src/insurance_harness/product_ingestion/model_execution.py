"""Permanent configured Gemini boundary for product-ingestion model calls."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict

from insurance_harness.jobs import JobSnapshot
from insurance_harness.model_policy.models import (
    ModelIdentity,
    ModelPermitView,
    PolicyReceipt,
    _model_permit_view_digest,
)
from insurance_harness.product_ingestion.artifact_models import (
    StageCallAction,
    StageCallSnapshot,
)
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.model_settings import (
    ModelTemplatePolicy,
    ProductModelSettings,
    _digest,
)
from insurance_harness.product_ingestion.models import ProductScope

SettingsProvider = Callable[[], ProductModelSettings]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class ModelPolicyDenied(PermissionError):
    """Safe pre-provider rejection with no endpoint, credential, prompt, or raw body."""


@dataclass(frozen=True, slots=True)
class PreparedModelRequest:
    semantic_request: bytes
    request_bytes: bytes
    request_sha256: str


class ModelExecutionReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    authority_kind: Literal["configured_product_model_policy"] = "configured_product_model_policy"
    call_id: str
    run_id: str
    stage_key: str
    operation_key: str
    dependency_sha256: str
    input_sha256: str
    request_sha256: str
    raw_sha256: str | None
    policy_receipt_sha256: str | None
    state: Literal["recorded", "interrupted"]
    diagnostic: str | None
    usage: dict[str, int]
    dispatched_at: datetime
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class ModelExecutionResult:
    state: Literal["recorded", "interrupted"]
    call_id: str
    raw: bytes | None
    raw_ref: str
    diagnostic: str | None
    usage: dict[str, int]
    policy_receipt: PolicyReceipt | None
    policy_receipt_raw: bytes | None
    policy_receipt_raw_sha256: str | None
    execution_receipt: ModelExecutionReceipt
    execution_receipt_raw: bytes
    execution_receipt_sha256: str


def _settings(provider: SettingsProvider) -> ProductModelSettings:
    value = provider()
    if type(value) is not ProductModelSettings:
        raise ModelPolicyDenied("configured model policy is unavailable")
    return value


def _template_and_request(
    settings: ProductModelSettings,
    *,
    scope: ProductScope,
    content: bytes,
    input_sha256: str,
    prompt: bytes,
    template_id: str,
) -> tuple[ModelTemplatePolicy, PreparedModelRequest]:
    if scope != settings.scope:
        raise ModelPolicyDenied("configured model scope mismatch")
    if type(content) is not bytes or _sha(content) != input_sha256:
        raise ModelPolicyDenied("configured model input identity mismatch")
    try:
        content_text = content.decode("utf-8", errors="strict")
        prompt_text = prompt.decode("utf-8", errors="strict")
        template = settings.template(template_id)
    except (UnicodeError, ValueError):
        raise ModelPolicyDenied("configured model template is unavailable") from None
    if _sha(prompt) != template.prompt_sha256:
        raise ModelPolicyDenied("configured model template mismatch")
    if len(content) > template.max_context_bytes:
        raise ModelPolicyDenied("configured model context capacity exceeded")
    request = _canonical(
        {
            "max_tokens": template.max_output_tokens,
            "messages": [
                {"content": prompt_text, "role": "system"},
                {"content": content_text, "role": "user"},
            ],
            "model": settings.model,
            "stream": False,
            "temperature": 0,
        }
    )
    if len(request) > settings.max_request_bytes:
        raise ModelPolicyDenied("configured model request capacity exceeded")
    return template, PreparedModelRequest(content, request, _sha(request))


def _policy_receipt(
    settings: ProductModelSettings,
    template: ModelTemplatePolicy,
    *,
    scope: ProductScope,
    run_id: str,
    job_id: str,
    generation: int,
    stage_key: str,
    operation_key: str,
    dependency_sha256: str,
    input_sha256: str,
    request_sha256: str,
    evaluated_at: datetime,
) -> PolicyReceipt:
    identity = ModelIdentity(
        provider="g3-user-gateway",
        deployment_id=settings.model,
        family="gemini",
        role=template.role,
        policy_version=settings.policy_version,
    )
    call_scope = _digest(
        "product-model-call-scope.v1",
        {
            "scope": scope.model_dump(mode="json"),
            "run_id": run_id,
            "job_id": job_id,
            "generation": generation,
            "stage_key": stage_key,
            "operation_key": operation_key,
            "dependency_sha256": dependency_sha256,
            "input_sha256": input_sha256,
            "request_sha256": request_sha256,
        },
    )
    view = ModelPermitView(
        identity=identity,
        purpose=template.purpose,
        run_schema_version=template.run_schema_version,
        space_id=scope.space_id,
        run_id=run_id,
        run_revision=dependency_sha256,
        admission_hash=settings.policy_sha256,
        verified_binding_digest=settings.scope_sha256,
        template_hash=template.prompt_sha256,
        model_plan_hash=settings.model_plan_sha256,
        policy_snapshot_digest=settings.policy_sha256,
        call_scope_hash=call_scope,
        expires_at=settings.expires_at,
    )
    return PolicyReceipt(
        decision="ALLOW",
        reason_code="policy_allowed",
        identity_key=identity.identity_key,
        purpose=view.purpose,
        run_schema_version=view.run_schema_version,
        space_id=view.space_id,
        run_id=view.run_id,
        run_revision=view.run_revision,
        admission_hash=view.admission_hash,
        request_digest=request_sha256,
        binding_digest=settings.policy_sha256,
        verified_binding_digest=view.verified_binding_digest,
        template_hash=view.template_hash,
        model_plan_hash=view.model_plan_hash,
        call_scope_hash=view.call_scope_hash,
        attempted_context_digest=call_scope,
        policy_snapshot_digest=view.policy_snapshot_digest,
        permit_digest=_model_permit_view_digest(view),
        permit_view=view,
        evaluated_at=evaluated_at,
    )


def provider_usage(raw: bytes | None) -> dict[str, int]:
    if raw is None:
        return {}
    try:
        value = json.loads(raw)
        usage = value.get("usage")
    except (AttributeError, UnicodeError, ValueError):
        return {}
    if not isinstance(usage, dict):
        return {}
    allowed = {
        "input_tokens",
        "output_tokens",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }
    return {
        key: item
        for key, item in usage.items()
        if key in allowed and type(item) is int and item >= 0
    }


def _result(
    call: StageCallSnapshot,
    *,
    policy_receipt: PolicyReceipt | None,
) -> ModelExecutionResult:
    state: Literal["recorded", "interrupted"] = (
        "interrupted" if call.state.value == "interrupted" else "recorded"
    )
    policy_raw = (
        _canonical(policy_receipt.model_dump(mode="json")) if policy_receipt is not None else None
    )
    if call.dispatched_at is None or call.recorded_at is None:
        raise ValueError("terminal model call is missing durable times")
    receipt = ModelExecutionReceipt(
        call_id=call.call_id,
        run_id=call.run_id,
        stage_key=call.stage_key,
        operation_key=call.operation_key,
        dependency_sha256=call.dependency_sha256,
        input_sha256=call.input_sha256,
        request_sha256=call.request_sha256 or "",
        raw_sha256=call.raw_sha256,
        policy_receipt_sha256=_sha(policy_raw) if policy_raw is not None else None,
        state=state,
        diagnostic=call.diagnostic,
        usage=dict(call.usage),
        dispatched_at=call.dispatched_at,
        recorded_at=call.recorded_at,
    )
    receipt_raw = _canonical(receipt.model_dump(mode="json"))
    return ModelExecutionResult(
        state=state,
        call_id=call.call_id,
        raw=call.raw,
        raw_ref=call.raw_ref,
        diagnostic=call.diagnostic,
        usage=dict(call.usage),
        policy_receipt=policy_receipt,
        policy_receipt_raw=policy_raw,
        policy_receipt_raw_sha256=_sha(policy_raw) if policy_raw is not None else None,
        execution_receipt=receipt,
        execution_receipt_raw=receipt_raw,
        execution_receipt_sha256=_sha(receipt_raw),
    )


class ConfiguredModelExecutor:
    def __init__(
        self,
        *,
        settings_provider: SettingsProvider,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings_provider = settings_provider
        self._client = client

    async def replay_stage_call(
        self,
        *,
        store: ProductArtifactStore,
        scope: ProductScope,
        run_id: str,
        job: JobSnapshot,
        stage_key: str,
        operation_key: str,
        dependency_sha256: str,
        input_sha256: str,
        content: bytes,
        prompt: bytes,
        template_id: str,
    ) -> ModelExecutionResult:
        """Revalidate a cross-run recorded call without reserving or sending a new call."""
        return await asyncio.to_thread(
            self._replay_stage_call,
            store=store,
            scope=scope,
            run_id=run_id,
            job=job,
            stage_key=stage_key,
            operation_key=operation_key,
            dependency_sha256=dependency_sha256,
            input_sha256=input_sha256,
            content=content,
            prompt=prompt,
            template_id=template_id,
        )

    def _replay_stage_call(
        self,
        *,
        store: ProductArtifactStore,
        scope: ProductScope,
        run_id: str,
        job: JobSnapshot,
        stage_key: str,
        operation_key: str,
        dependency_sha256: str,
        input_sha256: str,
        content: bytes,
        prompt: bytes,
        template_id: str,
    ) -> ModelExecutionResult:
        """Revalidate a cross-run recorded call without reserving or sending a new call."""
        if stage_key != "identity" or operation_key != "current-product-identity":
            raise ValueError("recorded identity replay stage mismatch")
        call = store.get_identity_replay_call(
            scope=scope,
            run_id=run_id,
            job_id=job.id,
            generation=job.lease_generation,
            dependency_sha256=dependency_sha256,
        )
        settings = _settings(self._settings_provider)
        template, prepared = _template_and_request(
            settings,
            scope=scope,
            content=content,
            input_sha256=input_sha256,
            prompt=prompt,
            template_id=template_id,
        )
        if (
            settings.expires_at <= datetime.now(UTC)
            or template.role != "classify"
            or template.purpose != "g3-batch-resolution"
            or template.run_schema_version != "830-g3-v1"
            or call.model_policy_sha256 != settings.policy_sha256
            or call.prompt_policy_sha256 != template.prompt_sha256
            or call.input_sha256 != input_sha256
            or call.request_bytes != prepared.request_bytes
            or call.request_sha256 != prepared.request_sha256
        ):
            raise ValueError("recorded identity request or model policy changed")
        receipt = _policy_receipt(
            settings,
            template,
            scope=scope,
            run_id=call.run_id,
            job_id=call.job_id,
            generation=call.generation,
            stage_key=call.stage_key,
            operation_key=call.operation_key,
            dependency_sha256=call.dependency_sha256,
            input_sha256=call.input_sha256,
            request_sha256=call.request_sha256,
            evaluated_at=call.dispatched_at,
        )
        store.record_identity_replay(
            scope=scope,
            run_id=run_id,
            job_id=job.id,
            generation=job.lease_generation,
            dependency_sha256=dependency_sha256,
        )
        return _result(call, policy_receipt=receipt)

    async def _send(
        self, settings: ProductModelSettings, prepared: PreparedModelRequest
    ) -> tuple[bytes | None, str | None]:
        client = self._client or httpx.AsyncClient(
            timeout=settings.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )
        close = self._client is None
        try:
            try:
                async with client.stream(
                    "POST",
                    str(settings.endpoint),
                    content=prepared.request_bytes,
                    headers={
                        "Authorization": "Bearer " + settings.api_key.get_secret_value(),
                        "Content-Type": "application/json",
                    },
                ) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > settings.max_response_bytes:
                            return None, "response_capacity_exceeded"
                        raw.extend(chunk)
                    diagnostic = (
                        None if 200 <= response.status_code < 300 else "provider_http_status"
                    )
                    return bytes(raw), diagnostic
            except Exception as error:
                return None, "transport:" + type(error).__name__
        finally:
            if close:
                await client.aclose()

    async def execute_stage_call(
        self,
        *,
        store: ProductArtifactStore,
        scope: ProductScope,
        run_id: str,
        job: JobSnapshot,
        stage_key: str,
        operation_key: str,
        dependency_sha256: str,
        input_sha256: str,
        content: bytes,
        prompt: bytes,
        template_id: str,
        call_id: str | None = None,
    ) -> ModelExecutionResult:
        initial = _settings(self._settings_provider)
        template, prepared = _template_and_request(
            initial,
            scope=scope,
            content=content,
            input_sha256=input_sha256,
            prompt=prompt,
            template_id=template_id,
        )
        reservation = store.reserve_stage_call(
            scope=scope,
            run_id=run_id,
            stage_key=stage_key,
            operation_key=operation_key,
            dependency_sha256=dependency_sha256,
            job_id=job.id,
            generation=job.lease_generation,
            attempt=job.attempt,
            call_id=call_id or str(uuid4()),
            input_sha256=input_sha256,
            model_policy_sha256=initial.policy_sha256,
            prompt_policy_sha256=template.prompt_sha256,
        )
        call = reservation.call
        if reservation.action is StageCallAction.INTERRUPTED:
            return _result(call, policy_receipt=None)
        if reservation.action is StageCallAction.RECORDED:
            if (
                call.request_bytes != prepared.request_bytes
                or call.request_sha256 != prepared.request_sha256
                or call.dispatched_at is None
            ):
                raise ValueError("recorded endpoint request does not match current policy")
            receipt = _policy_receipt(
                initial,
                template,
                scope=scope,
                run_id=run_id,
                job_id=call.job_id,
                generation=call.generation,
                stage_key=stage_key,
                operation_key=operation_key,
                dependency_sha256=dependency_sha256,
                input_sha256=input_sha256,
                request_sha256=prepared.request_sha256,
                evaluated_at=call.dispatched_at,
            )
            return _result(call, policy_receipt=receipt)

        if initial.expires_at <= datetime.now(UTC):
            raise ModelPolicyDenied("configured model policy expired")

        call = store.begin_stage_call(
            scope=scope,
            call_id=call.call_id,
            job_id=job.id,
            generation=job.lease_generation,
            request_sha256=prepared.request_sha256,
            request_bytes=prepared.request_bytes,
        )
        current = _settings(self._settings_provider)
        if current.policy_sha256 != initial.policy_sha256 or current.expires_at <= datetime.now(
            UTC
        ):
            call = store.record_stage_call_result(
                scope=scope,
                call_id=call.call_id,
                job_id=job.id,
                generation=job.lease_generation,
                request_sha256=prepared.request_sha256,
                raw=None,
                diagnostic="policy_changed_before_dispatch",
                usage={},
            )
            return _result(call, policy_receipt=None)
        receipt = _policy_receipt(
            current,
            template,
            scope=scope,
            run_id=run_id,
            job_id=call.job_id,
            generation=call.generation,
            stage_key=stage_key,
            operation_key=operation_key,
            dependency_sha256=dependency_sha256,
            input_sha256=input_sha256,
            request_sha256=prepared.request_sha256,
            evaluated_at=call.dispatched_at,
        )
        raw, diagnostic = await self._send(current, prepared)
        call = store.record_stage_call_result(
            scope=scope,
            call_id=call.call_id,
            job_id=job.id,
            generation=job.lease_generation,
            request_sha256=prepared.request_sha256,
            raw=raw,
            diagnostic=diagnostic,
            usage=provider_usage(raw),
        )
        return _result(call, policy_receipt=receipt)

    def field_transport(
        self,
        scope: ProductScope,
        run_id: str,
        job: JobSnapshot,
        *,
        prompt: bytes,
    ) -> ConfiguredFieldTransport:
        return ConfiguredFieldTransport(self, scope=scope, run_id=run_id, job=job, prompt=prompt)


class ConfiguredFieldTransport:
    def __init__(
        self,
        executor: ConfiguredModelExecutor,
        *,
        scope: ProductScope,
        run_id: str,
        job: JobSnapshot,
        prompt: bytes,
    ) -> None:
        self._executor = executor
        self._scope = scope
        self._run_id = run_id
        self._job = job
        self._prompt = bytes(prompt)
        self._initial = _settings(executor._settings_provider)
        if self._initial.scope != scope:
            raise ModelPolicyDenied("configured model scope mismatch")
        self._template = self._initial.template(self._initial.field_template_id)

    @property
    def model_policy_sha256(self) -> str:
        return self._initial.policy_sha256

    def prepare(self, semantic_request: bytes) -> PreparedModelRequest:
        _template, prepared = _template_and_request(
            self._initial,
            scope=self._scope,
            content=semantic_request,
            input_sha256=_sha(semantic_request),
            prompt=self._template_prompt(),
            template_id=self._template.template_id,
        )
        return prepared

    def _template_prompt(self) -> bytes:
        return self._prompt

    async def send(self, prepared: PreparedModelRequest) -> bytes:
        current = _settings(self._executor._settings_provider)
        if (
            current.policy_sha256 != self._initial.policy_sha256
            or current.expires_at <= datetime.now(UTC)
        ):
            raise ModelPolicyDenied("configured model policy changed before dispatch")
        raw, diagnostic = await self._executor._send(current, prepared)
        if raw is None:
            raise RuntimeError(diagnostic or "model transport failed")
        return raw

    def semantic_request(self, request_bytes: bytes) -> bytes:
        try:
            body = json.loads(request_bytes)
            messages = body["messages"]
            content = messages[1]["content"]
        except (KeyError, TypeError, ValueError, IndexError):
            raise ValueError("recorded field request envelope is invalid") from None
        if type(content) is not str:
            raise ValueError("recorded field semantic request is invalid")
        semantic = content.encode()
        _template, expected = _template_and_request(
            self._initial,
            scope=self._scope,
            content=semantic,
            input_sha256=_sha(semantic),
            prompt=self._prompt,
            template_id=self._template.template_id,
        )
        if expected.request_bytes != request_bytes:
            raise ValueError("recorded field request does not match current policy")
        return semantic

    @staticmethod
    def decode_response(raw: bytes) -> bytes:
        try:
            body = json.loads(raw)
            content = body["choices"][0]["message"]["content"]
        except (KeyError, TypeError, ValueError, IndexError):
            raise ValueError("model response envelope is invalid") from None
        if type(content) is not str:
            raise ValueError("model response semantic content is invalid")
        return content.encode()
