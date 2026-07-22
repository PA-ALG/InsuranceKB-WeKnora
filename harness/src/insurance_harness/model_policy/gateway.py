"""Canonical atomic model-call boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
import marshal
import os
import secrets
from asyncio import (
    AbstractEventLoop,
    CancelledError,
    get_running_loop,
)
from asyncio import (
    Event as AsyncEvent,
)
from collections.abc import AsyncIterator, Awaitable, Callable, Generator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from inspect import (
    CO_VARARGS,
    CO_VARKEYWORDS,
    getattr_static,
    isawaitable,
    iscoroutinefunction,
)
from threading import Event, RLock, get_ident
from types import CodeType, FunctionType
from typing import SupportsIndex, cast
from weakref import ReferenceType, WeakKeyDictionary, ref

from .admission import VerifiedAdmission, _verified_authority_snapshot
from .composition import (
    ProductionModelComposition,
    _get_composition_state,
)
from .models import (
    IdentityKey,
    ModelCallContext,
    ModelCallFacts,
    ModelCallRequest,
    ModelIdentity,
    PolicyReceipt,
)
from .policy import (
    ModelPolicyDenied,
    ProductionModelPolicy,
    _approved_keys_digest,
    _decision_authorizes_call,
    _PolicyDecision,
)

_CONSTRUCTION_SEAL = object()
_CALL_SCOPE_DOMAIN = b"insurancekb.model-policy.gateway-call-scope.v1\0"
_AUTHORITY_PID = os.getpid()
_AUTHORITY_NONCE = secrets.token_bytes(32)


class ModelGatewayDenied(PermissionError):
    """Typed secret-free refusal before the provider transport boundary."""

    _MESSAGES = {
        "invalid_gateway": "production model gateway is unavailable",
        "invalid_call_facts": "production model call facts are invalid",
        "invalid_call_request": "production model call request is invalid",
        "invalid_verified_admission": "verified admission capability is invalid",
        "invalid_transport_identity": "model transport identity is not approved",
        "call_content_digest_mismatch": "model call content digest does not match",
        "rendered_prompt_digest_mismatch": "rendered prompt digest does not match",
        "role_mismatch": "model call role does not match model identity",
        "receipt_sink_failure": "model policy receipt could not be persisted",
        "authority_revalidation_failed": "model call authority changed before transport",
    }

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(self._MESSAGES.get(reason_code, "production model call denied"))


class ModelTransportError(RuntimeError):
    """Secret-free transport failure; the original provider error is suppressed."""

    def __init__(self) -> None:
        super().__init__("approved weak-model transport failed")


@dataclass(frozen=True, slots=True)
class _GatewayState:
    composition: ProductionModelComposition
    transport_binding: _BoundModelTransport
    receipt_sink_ref: ReferenceType[object]
    receipt_sink_type_ref: ReferenceType[type[object]]
    sink_record_descriptor_ref: ReferenceType[FunctionType]
    sink_record_code: CodeType
    pid: int
    process_nonce: bytes


@dataclass(frozen=True, slots=True)
class _AuthoritySnapshot:
    gateway_state: _GatewayState
    composition_state: object
    transport_identity: ModelIdentity
    policy_digest: str
    bound_policy_digest: str
    transport_authority_digest: bytes
    transport_call: Callable[
        [ModelIdentity, ModelCallRequest], Awaitable[object]
    ]


_GATEWAY_STATES: WeakKeyDictionary[object, _GatewayState] = WeakKeyDictionary()
_GATEWAY_LOCK = RLock()


class _BoundModelTransport:
    """Opaque package-local binding between one adapter and approved identity."""

    __slots__ = ("__weakref__",)

    def __new__(
        cls,
        *_args: object,
        _seal: object | None = None,
        **_kwargs: object,
    ) -> _BoundModelTransport:
        if cls is not _BoundModelTransport or _seal is not _CONSTRUCTION_SEAL:
            raise TypeError("model transport bindings are issued only by composition")
        return super().__new__(cls)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise TypeError("model transport binding is immutable")

    def __copy__(self) -> _BoundModelTransport:
        raise TypeError("model transport binding cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> _BoundModelTransport:
        raise TypeError("model transport binding cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("model transport binding cannot be serialized")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> tuple[object, ...]:
        raise TypeError("model transport binding cannot be serialized")


class _BoundTransportExecutor:
    """Opaque package-issued authority to execute one bound transport target."""

    __slots__ = ("__weakref__",)

    def __new__(
        cls,
        *_args: object,
        _seal: object | None = None,
        **_kwargs: object,
    ) -> _BoundTransportExecutor:
        if cls is not _BoundTransportExecutor or _seal is not _CONSTRUCTION_SEAL:
            raise TypeError("model transport executors are package-issued only")
        return super().__new__(cls)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise TypeError("model transport executor is immutable")

    def __copy__(self) -> _BoundTransportExecutor:
        raise TypeError("model transport executor cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> _BoundTransportExecutor:
        raise TypeError("model transport executor cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("model transport executor cannot be serialized")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> tuple[object, ...]:
        raise TypeError("model transport executor cannot be serialized")


class _CanonicalModelTransportAdapter:
    """The sole package-owned adapter admitted to the guarded boundary."""

    __slots__ = ("__weakref__",)

    def __new__(
        cls,
        *_args: object,
        _seal: object | None = None,
        **_kwargs: object,
    ) -> _CanonicalModelTransportAdapter:
        if cls is not _CanonicalModelTransportAdapter or _seal is not _CONSTRUCTION_SEAL:
            raise TypeError("canonical model adapters are package-issued only")
        return super().__new__(cls)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise TypeError("canonical model adapter is immutable")

    async def call(
        self,
        identity: ModelIdentity,
        request: ModelCallRequest,
        /,
    ) -> str:
        del self, identity, request
        raise ModelGatewayDenied("invalid_gateway")


class GuardedModelClient:
    """Sealed client that persists one decision before one transport call."""

    __slots__ = ("__weakref__",)

    def __new__(
        cls,
        *_args: object,
        _seal: object | None = None,
        **_kwargs: object,
    ) -> GuardedModelClient:
        if cls is not GuardedModelClient or _seal is not _CONSTRUCTION_SEAL:
            raise TypeError("GuardedModelClient is built only by composition root")
        return super().__new__(cls)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise TypeError("GuardedModelClient is immutable")

    def __copy__(self) -> GuardedModelClient:
        raise TypeError("GuardedModelClient cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> GuardedModelClient:
        raise TypeError("GuardedModelClient cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("GuardedModelClient cannot be serialized")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> tuple[object, ...]:
        raise TypeError("GuardedModelClient cannot be serialized")

    async def call(
        self,
        verified_admission: VerifiedAdmission,
        facts: ModelCallFacts,
        request: ModelCallRequest,
        /,
    ) -> str:
        state = _get_gateway_state(self)
        if state is None:
            raise ModelGatewayDenied("invalid_gateway")
        transport_snapshot = _bound_transport_snapshot(state.transport_binding)
        sink_record = _resolve_sink(state)
        if transport_snapshot is None or sink_record is None:
            raise ModelGatewayDenied("invalid_gateway")
        (
            bound_identity,
            bound_policy_digest,
            transport_authority_digest,
            initial_transport_call,
        ) = transport_snapshot
        del transport_snapshot, initial_transport_call
        facts = _revalidate_facts(facts)
        request = _revalidate_request(request)
        verified_snapshot = _verified_authority_snapshot(verified_admission)
        if verified_snapshot is None:
            raise ModelGatewayDenied("invalid_verified_admission")
        admission_request, binding, verification_receipt = verified_snapshot
        if facts.role != facts.identity.role:
            raise ModelGatewayDenied("role_mismatch")
        if facts.identity != bound_identity:
            raise ModelGatewayDenied("invalid_transport_identity")
        if facts.content_digest != hashlib.sha256(request.content).hexdigest():
            raise ModelGatewayDenied("call_content_digest_mismatch")
        if facts.rendered_prompt_digest != hashlib.sha256(
            request.rendered_prompt
        ).hexdigest():
            raise ModelGatewayDenied("rendered_prompt_digest_mismatch")

        context = ModelCallContext(
            identity=facts.identity,
            purpose=facts.purpose,
            run_schema_version=facts.run_schema_version,
            space_id=facts.space_id,
            run_id=facts.run_id,
            run_revision=facts.run_revision,
            admission_hash=facts.admission_artifact_digest,
            verified_binding_digest=verification_receipt.verified_binding_digest,
            template_hash=facts.template_hash,
            model_plan_hash=facts.model_plan_hash,
            call_scope_hash=_derive_call_scope_hash(
                facts,
                admission_request.request_digest,
                binding.binding_digest,
                verification_receipt.verified_binding_digest,
            ),
        )
        decision = state.composition._evaluate_for_guard(
            verified_admission,
            context,
        )
        receipt = decision.receipt
        if receipt.decision == "DENY":
            _persist_receipt(sink_record, receipt)
            raise ModelPolicyDenied(receipt.reason_code)

        pre_sink_transport_call = _authorized_transport_call(
            self,
            state,
            decision,
            verified_admission,
            context,
            bound_identity,
            bound_policy_digest,
            transport_authority_digest,
        )
        if pre_sink_transport_call is None:
            raise ModelGatewayDenied("authority_revalidation_failed")
        del pre_sink_transport_call
        _persist_receipt(sink_record, receipt)
        if _resolve_sink(state) is None:
            raise ModelGatewayDenied("authority_revalidation_failed")
        post_transport_call = _authorized_transport_call(
            self,
            state,
            decision,
            verified_admission,
            context,
            bound_identity,
            bound_policy_digest,
            transport_authority_digest,
        )
        if post_transport_call is None:
            raise ModelGatewayDenied("authority_revalidation_failed")
        try:
            result = await post_transport_call(bound_identity, request)
        except ModelGatewayDenied:
            raise
        except Exception:
            raise ModelTransportError() from None
        return await _require_exact_transport_str(result)


def _revalidate_facts(value: object) -> ModelCallFacts:
    try:
        payload = value.model_dump(  # type: ignore[attr-defined]
            mode="python", round_trip=True, warnings=False
        )
        return ModelCallFacts.model_validate(payload)
    except Exception:
        raise ModelGatewayDenied("invalid_call_facts") from None


def _revalidate_request(value: object) -> ModelCallRequest:
    try:
        payload = value.model_dump(  # type: ignore[attr-defined]
            mode="python", round_trip=True, warnings=False
        )
        return ModelCallRequest.model_validate(payload)
    except Exception:
        raise ModelGatewayDenied("invalid_call_request") from None


def _derive_call_scope_hash(
    facts: ModelCallFacts,
    request_digest: str,
    binding_digest: str,
    verified_binding_digest: str,
) -> str:
    encoded = json.dumps(
        {
            "facts": facts.model_dump(mode="json", round_trip=True),
            "request_digest": request_digest,
            "binding_digest": binding_digest,
            "verified_binding_digest": verified_binding_digest,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(_CALL_SCOPE_DOMAIN + encoded).hexdigest()


def _authorized_transport_call(
    client: GuardedModelClient,
    expected_state: _GatewayState,
    decision: _PolicyDecision,
    verified_admission: VerifiedAdmission,
    context: ModelCallContext,
    expected_identity: ModelIdentity,
    expected_policy_digest: str,
    expected_transport_authority_digest: bytes,
) -> Callable[[ModelIdentity, ModelCallRequest], Awaitable[object]] | None:
    first = _read_authority_snapshot(client, expected_state)
    if (
        first is None
        or first.gateway_state is not expected_state
        or first.transport_identity != expected_identity
        or first.policy_digest != expected_policy_digest
        or first.bound_policy_digest != expected_policy_digest
        or first.transport_authority_digest
        != expected_transport_authority_digest
        or not _decision_authorizes_call(
            decision,
            verified_admission,
            context,
            _checked_at=_utc_now(),
            _expected_policy_snapshot_digest=first.policy_digest,
        )
    ):
        return None
    second = _read_authority_snapshot(client, expected_state)
    if (
        second is None
        or second.gateway_state is not first.gateway_state
        or second.composition_state is not first.composition_state
        or second.transport_identity != first.transport_identity
        or second.policy_digest != first.policy_digest
        or second.bound_policy_digest != first.bound_policy_digest
        or second.transport_authority_digest
        != first.transport_authority_digest
        or not _decision_authorizes_call(
            decision,
            verified_admission,
            context,
            _checked_at=_utc_now(),
            _expected_policy_snapshot_digest=second.policy_digest,
        )
    ):
        return None
    return second.transport_call


def _read_authority_snapshot(
    client: GuardedModelClient,
    expected_state: _GatewayState,
) -> _AuthoritySnapshot | None:
    current_state = _get_gateway_state(client)
    composition_state = _get_composition_state(expected_state.composition)
    transport_snapshot = _bound_transport_snapshot(
        expected_state.transport_binding
    )
    policy_digest = (
        None
        if composition_state is None
        else _approved_keys_digest(composition_state.approved_identity_keys)
    )
    if current_state is None or composition_state is None or transport_snapshot is None:
        return None
    (
        identity,
        bound_policy_digest,
        transport_authority_digest,
        transport_call,
    ) = transport_snapshot
    if policy_digest is None:
        return None
    return _AuthoritySnapshot(
        gateway_state=current_state,
        composition_state=composition_state,
        transport_identity=identity,
        policy_digest=policy_digest,
        bound_policy_digest=bound_policy_digest,
        transport_authority_digest=transport_authority_digest,
        transport_call=transport_call,
    )


def _persist_receipt(
    sink_record: Callable[[PolicyReceipt], object],
    receipt: PolicyReceipt,
) -> None:
    try:
        result = sink_record(receipt)
    except Exception:
        raise ModelGatewayDenied("receipt_sink_failure") from None
    if result is not None:
        if isawaitable(result):
            _close_or_cancel_awaitable(result)
        raise ModelGatewayDenied("receipt_sink_failure")


def _close_or_cancel_awaitable(value: object) -> None:
    """Dispose of a rejected deferred result without leaking provider details."""

    for method_name in ("cancel", "close"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                method()
            except Exception:
                pass
            return


async def _dispose_invalid_transport_result(value: object) -> None:
    """Best-effort disposal for a rejected deferred transport result."""

    async_closer = getattr(value, "aclose", None)
    if callable(async_closer):
        try:
            pending = async_closer()
            if isawaitable(pending):
                await pending
        except Exception:
            pass
        return

    cancel = getattr(value, "cancel", None)
    if callable(cancel):
        try:
            pending = cancel()
            if isawaitable(pending):
                await pending
        except Exception:
            pass

    close = getattr(value, "close", None)
    if callable(close):
        try:
            pending = close()
            if isawaitable(pending):
                await pending
        except Exception:
            pass
        return


async def _require_exact_transport_str(value: object) -> str:
    if type(value) is str:
        return value
    await _dispose_invalid_transport_result(value)
    raise ModelTransportError()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _build_guarded_model_client_for_test(
    *,
    composition: ProductionModelComposition,
    executor: _BoundTransportExecutor,
    receipt_sink: object,
) -> GuardedModelClient:
    """Test-only assembly hook until Task 5 owns production wiring."""

    composition_state = _get_composition_state(composition)
    if composition_state is None:
        raise ModelGatewayDenied("invalid_gateway")
    transport_binding = _bind_model_transport(
        executor,
        composition_state.approved_identity_keys,
    )
    receipt_sink_type = type(receipt_sink)
    sink_record_descriptor = getattr_static(receipt_sink_type, "record", None)
    try:
        receipt_sink_ref = ref(receipt_sink)
        receipt_sink_type_ref = ref(receipt_sink_type)
    except TypeError:
        raise ModelGatewayDenied("invalid_gateway") from None
    if (
        not isinstance(sink_record_descriptor, FunctionType)
        or not _function_is_isolatable(
            sink_record_descriptor,
            require_coroutine=False,
            parameter_names=("self", "receipt"),
        )
        or _bind_sink_function(
            sink_record_descriptor,
            sink_record_descriptor.__code__,
            receipt_sink,
            receipt_sink_type,
        )
        is None
    ):
        raise ModelGatewayDenied("invalid_gateway")
    gateway = GuardedModelClient.__new__(
        GuardedModelClient,
        _seal=_CONSTRUCTION_SEAL,
    )
    state = _GatewayState(
        composition=composition,
        transport_binding=transport_binding,
        receipt_sink_ref=receipt_sink_ref,
        receipt_sink_type_ref=receipt_sink_type_ref,
        sink_record_descriptor_ref=ref(sink_record_descriptor),
        sink_record_code=sink_record_descriptor.__code__,
        pid=_AUTHORITY_PID,
        process_nonce=_AUTHORITY_NONCE,
    )
    with _GATEWAY_LOCK:
        _GATEWAY_STATES[gateway] = state
    return gateway


def _get_gateway_state(value: object) -> _GatewayState | None:
    if not isinstance(value, GuardedModelClient):
        return None
    with _GATEWAY_LOCK:
        state = _GATEWAY_STATES.get(value)
        if (
            state is None
            or state.pid != _AUTHORITY_PID
            or state.process_nonce != _AUTHORITY_NONCE
            or os.getpid() != _AUTHORITY_PID
        ):
            return None
        return state


def _resolve_sink(
    state: _GatewayState,
) -> Callable[[PolicyReceipt], object] | None:
    receipt_sink = state.receipt_sink_ref()
    receipt_sink_type = state.receipt_sink_type_ref()
    sink_record_descriptor = state.sink_record_descriptor_ref()
    if (
        receipt_sink is None
        or receipt_sink_type is None
        or sink_record_descriptor is None
        or type(receipt_sink) is not receipt_sink_type
        or getattr_static(receipt_sink_type, "record", None)
        is not sink_record_descriptor
        or sink_record_descriptor.__code__ is not state.sink_record_code
    ):
        return None
    sink_record = _bind_sink_function(
        sink_record_descriptor,
        state.sink_record_code,
        receipt_sink,
        receipt_sink_type,
    )
    if sink_record is None:
        return None
    return cast(Callable[[PolicyReceipt], object], sink_record)


def _function_is_isolatable(
    function: FunctionType,
    *,
    require_coroutine: bool,
    parameter_names: tuple[str, ...],
) -> bool:
    code = function.__code__
    return (
        iscoroutinefunction(function) is require_coroutine
        and function.__closure__ is None
        and function.__defaults__ is None
        and function.__kwdefaults__ is None
        and code.co_argcount == len(parameter_names)
        and code.co_kwonlyargcount == 0
        and not code.co_flags & CO_VARARGS
        and not code.co_flags & CO_VARKEYWORDS
        and code.co_varnames[: len(parameter_names)] == parameter_names
    )


def _bind_sink_function(
    descriptor: FunctionType,
    code: CodeType,
    instance: object,
    owner: type[object],
) -> object | None:
    if not _function_is_isolatable(
        descriptor,
        require_coroutine=False,
        parameter_names=("self", "receipt"),
    ):
        return None
    try:
        isolated = FunctionType(code, descriptor.__globals__, descriptor.__name__)
        return isolated.__get__(instance, owner)
    except Exception:
        return None


def _validated_executor_identity(
    composition: ProductionModelComposition,
    identity: object,
) -> tuple[ModelIdentity, str]:
    composition_state = _get_composition_state(composition)
    if composition_state is None:
        raise ModelGatewayDenied("invalid_gateway")
    try:
        validated_identity = ModelIdentity.model_validate(
            identity.model_dump(  # type: ignore[attr-defined]
                mode="python", round_trip=True, warnings=False
            )
        )
        policy = ProductionModelPolicy(composition_state.approved_identity_keys)
        policy.evaluate(validated_identity)
    except Exception:
        raise ModelGatewayDenied("invalid_transport_identity") from None
    return validated_identity, policy.policy_snapshot_digest


_TargetSnapshot = tuple[bytes, int, type[object], FunctionType, CodeType]
_ExecutionCall = Callable[
    [ModelIdentity, ModelCallRequest], Awaitable[object]
]
_ExecutorSnapshot = tuple[ModelIdentity, str, bytes, _ExecutionCall]
_ExecutorObservation = tuple[
    ModelIdentity, ModelCallRequest, AbstractEventLoop, int
]


def _make_stateful_target_authority() -> tuple[
    Callable[[str, str, str, str], object],
    Callable[[object], _TargetSnapshot | None],
    Callable[[object, str, str], Awaitable[str]],
    Callable[[object], tuple[tuple[str, str], ...]],
    Callable[[object], tuple[tuple[str, str, AbstractEventLoop, int], ...]],
    Callable[[object, Event, Event], bool],
    Callable[[object, AsyncEvent, AsyncEvent], bool],
    Callable[[], None],
]:
    lock = RLock()
    registry: WeakKeyDictionary[object, tuple[bytes, int, int]] = (
        WeakKeyDictionary()
    )
    observations: WeakKeyDictionary[
        object, list[tuple[str, str, AbstractEventLoop, int]]
    ] = WeakKeyDictionary()
    barriers: WeakKeyDictionary[object, tuple[Event, Event]] = WeakKeyDictionary()
    precheck_barriers: WeakKeyDictionary[
        object, tuple[AsyncEvent, AsyncEvent]
    ] = WeakKeyDictionary()
    process_pid = os.getpid()
    process_generation = 1
    next_target_generation = 1
    json_dumps = json.dumps
    json_loads = json.loads
    running_loop = get_running_loop
    thread_ident = get_ident
    denied_type = ModelGatewayDenied
    target_type: type[object]
    complete_descriptor: FunctionType
    complete_code: CodeType

    def valid_state(value: object) -> tuple[bytes, int, int] | None:
        state = registry.get(value)
        if (
            state is None
            or os.getpid() != process_pid
            or state[2] != process_generation
            or type(value) is not target_type
            or getattr_static(target_type, "complete", None)
            is not complete_descriptor
            or complete_descriptor.__code__ is not complete_code
        ):
            return None
        return state

    async def invoke(value: object, system: str, user: str) -> str:
        with lock:
            precheck_barrier = precheck_barriers.get(value)
        if precheck_barrier is not None:
            precheck_barrier[0].set()
            await precheck_barrier[1].wait()
        with lock:
            state = valid_state(value)
            barrier = barriers.get(value)
        if state is None:
            raise denied_type("authority_revalidation_failed")
        if barrier is not None:
            barrier[0].set()
            if not barrier[1].wait(timeout=5):
                raise denied_type("authority_revalidation_failed")
        with lock:
            if valid_state(value) is not state:
                raise denied_type("authority_revalidation_failed")
        try:
            config = json_loads(state[0].decode("utf-8"))
            result = config["result"]
        except Exception:
            raise denied_type("authority_revalidation_failed") from None
        if type(result) is not str:
            raise denied_type("authority_revalidation_failed")
        with lock:
            if valid_state(value) is not state:
                raise denied_type("authority_revalidation_failed")
            observations.setdefault(value, []).append(
                (system, user, running_loop(), thread_ident())
            )
        return result

    class StatefulTestModelClientTarget:
        __slots__ = ("__weakref__",)

        async def complete(self, system: str, user: str) -> str:
            return await invoke(self, system, user)

    target_type = StatefulTestModelClientTarget
    descriptor_value = getattr_static(target_type, "complete", None)
    if not isinstance(descriptor_value, FunctionType):
        raise RuntimeError("invalid package target")
    complete_descriptor = descriptor_value
    complete_code = descriptor_value.__code__

    def build(endpoint: str, model: str, credential: str, result: str) -> object:
        nonlocal next_target_generation
        config = json_dumps(
            {
                "credential": credential,
                "endpoint": endpoint,
                "model": model,
                "result": result,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        target = target_type.__new__(target_type)
        with lock:
            registry[target] = (
                config,
                next_target_generation,
                process_generation,
            )
            observations[target] = []
            next_target_generation += 1
        return target

    def snapshot(value: object) -> _TargetSnapshot | None:
        with lock:
            state = valid_state(value)
            if state is None:
                return None
            return (
                state[0],
                state[1],
                target_type,
                complete_descriptor,
                complete_code,
            )

    def calls(value: object) -> tuple[tuple[str, str], ...]:
        with lock:
            records = observations.get(value)
            if records is None:
                return ()
            return tuple((record[0], record[1]) for record in records)

    def detailed_observations(
        value: object,
    ) -> tuple[tuple[str, str, AbstractEventLoop, int], ...]:
        with lock:
            records = observations.get(value)
            return () if records is None else tuple(records)

    def set_barrier(value: object, entered: Event, resume: Event) -> bool:
        with lock:
            if valid_state(value) is None:
                return False
            barriers[value] = (entered, resume)
            return True

    def set_precheck_barrier(
        value: object,
        entered: AsyncEvent,
        resume: AsyncEvent,
    ) -> bool:
        with lock:
            if valid_state(value) is None:
                return False
            precheck_barriers[value] = (entered, resume)
            return True

    def reset() -> None:
        nonlocal barriers, lock, observations, precheck_barriers
        nonlocal process_generation, process_pid
        nonlocal registry
        lock = RLock()
        registry = WeakKeyDictionary()
        observations = WeakKeyDictionary()
        barriers = WeakKeyDictionary()
        precheck_barriers = WeakKeyDictionary()
        process_pid = os.getpid()
        process_generation += 1

    return (
        build,
        snapshot,
        invoke,
        calls,
        detailed_observations,
        set_barrier,
        set_precheck_barrier,
        reset,
    )


(
    _build_stateful_target,
    _stateful_target_snapshot,
    _invoke_stateful_target,
    _test_stateful_target_calls,
    _test_stateful_target_observations,
    _set_stateful_target_barrier_for_test,
    _set_stateful_target_precheck_barrier_for_test,
    _reset_stateful_target_authority_after_fork,
) = _make_stateful_target_authority()


def _make_executor_authority(
    target_snapshot: Callable[[object], _TargetSnapshot | None],
    target_invoke: Callable[[object, str, str], Awaitable[str]],
) -> tuple[
    Callable[[str, ModelIdentity, str, bytes, object | None], _BoundTransportExecutor],
    Callable[[object], _ExecutorSnapshot | None],
    Callable[[object], tuple[tuple[ModelIdentity, ModelCallRequest], ...]],
    Callable[[object], tuple[_ExecutorObservation, ...]],
    Callable[[object], tuple[object, ...]],
    Callable[[], None],
]:
    lock = RLock()
    registry: WeakKeyDictionary[object, tuple[object, ...]] = WeakKeyDictionary()
    observations: WeakKeyDictionary[
        object, list[_ExecutorObservation]
    ] = WeakKeyDictionary()
    deferred_results: WeakKeyDictionary[object, list[object]] = WeakKeyDictionary()
    process_pid = os.getpid()
    process_generation = 1
    next_executor_generation = 1
    mac_key = secrets.token_bytes(32)
    digest_function = hmac.digest
    compare_function = hmac.compare_digest
    marshal_function = marshal.dumps
    sha256_function = hashlib.sha256
    allowed_dispatchers = frozenset(
        {
            "test:success",
            "test:failure",
            "test:cancel",
            "test:nested",
            "test:generator",
            "test:async-generator",
            "test:bytes",
            "test:object",
            "test:bare-awaitable",
            "test:slow-aclose",
            "test:model-client",
        }
    )
    if not isinstance(target_snapshot, FunctionType) or not isinstance(
        target_invoke, FunctionType
    ):
        raise RuntimeError("invalid package target helpers")

    def function_closure_fingerprint(function: FunctionType) -> bytes:
        seen: set[int] = set()

        def visit(current: FunctionType, depth: int) -> bytes:
            identity = id(current)
            code_digest = sha256_function(
                marshal_function(current.__code__)
            ).hexdigest().encode("ascii")
            if identity in seen:
                return b"cycle:" + str(identity).encode("ascii") + b":" + code_digest
            seen.add(identity)
            parts = [
                b"function",
                str(identity).encode("ascii"),
                code_digest,
            ]
            closure = current.__closure__
            if closure is None:
                return b"".join(
                    len(part).to_bytes(8, "big") + part for part in parts
                )
            for name, cell in zip(
                current.__code__.co_freevars,
                closure,
                strict=True,
            ):
                try:
                    value = cell.cell_contents
                except ValueError:
                    value_part = b"empty"
                else:
                    value_type = type(value)
                    if isinstance(value, FunctionType) and depth < 3:
                        value_part = visit(value, depth + 1)
                    elif isinstance(value, CodeType):
                        value_part = (
                            b"code:"
                            + sha256_function(marshal_function(value))
                            .hexdigest()
                            .encode("ascii")
                        )
                    elif isinstance(value, (bytes, str, int, bool, type(None))):
                        value_part = (
                            f"{value_type.__module__}.{value_type.__qualname__}:"
                            f"{value!r}"
                        ).encode()
                    else:
                        value_part = (
                            f"{value_type.__module__}.{value_type.__qualname__}:"
                            f"{id(value)}"
                        ).encode()
                parts.extend((name.encode(), value_part))
            return b"".join(
                len(part).to_bytes(8, "big") + part for part in parts
            )

        return sha256_function(visit(function, 0)).digest()

    def canonical_payload(
        *,
        dispatcher_key: str,
        identity_bytes: bytes,
        policy_digest: str,
        route_config: bytes,
        executor_generation: int,
        target_generation: int,
        target_type: type[object] | None,
        descriptor: FunctionType | None,
        code: CodeType | None,
        snapshot_helper: FunctionType,
        snapshot_code: CodeType,
        invoke_helper: FunctionType,
        invoke_code: CodeType,
        snapshot_closure_digest: bytes,
        invoke_closure_digest: bytes,
        pid: int,
        generation: int,
    ) -> bytes:
        code_digest = (
            b""
            if code is None
            else sha256_function(marshal_function(code)).hexdigest().encode("ascii")
        )
        parts = (
            b"insurancekb.executor-authority.v1",
            dispatcher_key.encode("utf-8"),
            identity_bytes,
            policy_digest.encode("ascii"),
            route_config,
            str(executor_generation).encode("ascii"),
            str(target_generation).encode("ascii"),
            str(0 if target_type is None else id(target_type)).encode("ascii"),
            str(0 if descriptor is None else id(descriptor)).encode("ascii"),
            code_digest,
            str(id(snapshot_helper)).encode("ascii"),
            sha256_function(marshal_function(snapshot_code)).hexdigest().encode("ascii"),
            str(id(invoke_helper)).encode("ascii"),
            sha256_function(marshal_function(invoke_code)).hexdigest().encode("ascii"),
            snapshot_closure_digest,
            invoke_closure_digest,
            str(pid).encode("ascii"),
            str(generation).encode("ascii"),
        )
        return b"".join(len(part).to_bytes(8, "big") + part for part in parts)

    def validate_locked(
        executor: object,
        expected: tuple[object, ...] | None = None,
    ) -> tuple[tuple[object, ...], object | None] | None:
        state = registry.get(executor)
        if (
            state is None
            or (expected is not None and state is not expected)
            or os.getpid() != process_pid
            or state[0] != process_generation
            or state[1] != process_pid
        ):
            return None
        executor_generation = state[2]
        dispatcher_key = state[3]
        identity_bytes = state[4]
        policy_digest = state[5]
        route_config = state[6]
        target_ref = cast(ReferenceType[object] | None, state[7])
        target_generation = state[8]
        target_type_ref = cast(ReferenceType[type[object]] | None, state[9])
        descriptor_ref = cast(ReferenceType[FunctionType] | None, state[10])
        code = cast(CodeType | None, state[11])
        stored_mac = state[12]
        snapshot_helper = state[13]
        snapshot_code = state[14]
        invoke_helper = state[15]
        invoke_code = state[16]
        snapshot_closure_digest = state[17]
        invoke_closure_digest = state[18]
        if (
            not isinstance(executor_generation, int)
            or not isinstance(dispatcher_key, str)
            or dispatcher_key not in allowed_dispatchers
            or not isinstance(identity_bytes, bytes)
            or not isinstance(policy_digest, str)
            or not isinstance(route_config, bytes)
            or not isinstance(target_generation, int)
            or not isinstance(stored_mac, bytes)
            or not isinstance(snapshot_helper, FunctionType)
            or not isinstance(snapshot_code, CodeType)
            or not isinstance(invoke_helper, FunctionType)
            or not isinstance(invoke_code, CodeType)
            or not isinstance(snapshot_closure_digest, bytes)
            or not isinstance(invoke_closure_digest, bytes)
            or target_snapshot is not snapshot_helper
            or target_snapshot.__code__ is not snapshot_code
            or target_invoke is not invoke_helper
            or target_invoke.__code__ is not invoke_code
            or function_closure_fingerprint(target_snapshot)
            != snapshot_closure_digest
            or function_closure_fingerprint(target_invoke)
            != invoke_closure_digest
        ):
            return None
        target = None if target_ref is None else target_ref()
        target_type = None if target_type_ref is None else target_type_ref()
        descriptor = None if descriptor_ref is None else descriptor_ref()
        if dispatcher_key == "test:model-client":
            current_target = None if target is None else snapshot_helper(target)
            if (
                current_target is None
                or current_target[0] != route_config
                or current_target[1] != target_generation
                or current_target[2] is not target_type
                or current_target[3] is not descriptor
                or current_target[4] is not code
            ):
                return None
        elif any(
            item is not None
            for item in (target_ref, target_type_ref, descriptor_ref, code)
        ) or target_generation != 0:
            return None
        payload = canonical_payload(
            dispatcher_key=dispatcher_key,
            identity_bytes=identity_bytes,
            policy_digest=policy_digest,
            route_config=route_config,
            executor_generation=executor_generation,
            target_generation=target_generation,
            target_type=target_type,
            descriptor=descriptor,
            code=code,
            snapshot_helper=snapshot_helper,
            snapshot_code=snapshot_code,
            invoke_helper=invoke_helper,
            invoke_code=invoke_code,
            snapshot_closure_digest=snapshot_closure_digest,
            invoke_closure_digest=invoke_closure_digest,
            pid=process_pid,
            generation=process_generation,
        )
        if not compare_function(stored_mac, digest_function(mac_key, payload, "sha256")):
            return None
        return state, target

    def issue(
        dispatcher_key: str,
        identity: ModelIdentity,
        policy_digest: str,
        route_config: bytes,
        target: object | None,
    ) -> _BoundTransportExecutor:
        nonlocal next_executor_generation
        if dispatcher_key not in allowed_dispatchers:
            raise ModelGatewayDenied("invalid_gateway")
        target_generation = 0
        target_ref: ReferenceType[object] | None = None
        target_type_ref: ReferenceType[type[object]] | None = None
        descriptor_ref: ReferenceType[FunctionType] | None = None
        code: CodeType | None = None
        target_type: type[object] | None = None
        descriptor: FunctionType | None = None
        if dispatcher_key == "test:model-client":
            current_target = None if target is None else target_snapshot(target)
            if current_target is None or current_target[0] != route_config:
                raise ModelGatewayDenied("invalid_gateway")
            target_generation = current_target[1]
            target_type = current_target[2]
            descriptor = current_target[3]
            code = current_target[4]
            try:
                target_ref = ref(target)
                target_type_ref = ref(target_type)
                descriptor_ref = ref(descriptor)
            except TypeError:
                raise ModelGatewayDenied("invalid_gateway") from None
        elif target is not None:
            raise ModelGatewayDenied("invalid_gateway")
        identity_bytes = identity.model_dump_json().encode("utf-8")
        snapshot_closure_digest = function_closure_fingerprint(target_snapshot)
        invoke_closure_digest = function_closure_fingerprint(target_invoke)
        payload = canonical_payload(
            dispatcher_key=dispatcher_key,
            identity_bytes=identity_bytes,
            policy_digest=policy_digest,
            route_config=route_config,
            executor_generation=next_executor_generation,
            target_generation=target_generation,
            target_type=target_type,
            descriptor=descriptor,
            code=code,
            snapshot_helper=target_snapshot,
            snapshot_code=target_snapshot.__code__,
            invoke_helper=target_invoke,
            invoke_code=target_invoke.__code__,
            snapshot_closure_digest=snapshot_closure_digest,
            invoke_closure_digest=invoke_closure_digest,
            pid=process_pid,
            generation=process_generation,
        )
        state: tuple[object, ...] = (
            process_generation,
            process_pid,
            next_executor_generation,
            dispatcher_key,
            identity_bytes,
            policy_digest,
            route_config,
            target_ref,
            target_generation,
            target_type_ref,
            descriptor_ref,
            code,
            digest_function(mac_key, payload, "sha256"),
            target_snapshot,
            target_snapshot.__code__,
            target_invoke,
            target_invoke.__code__,
            snapshot_closure_digest,
            invoke_closure_digest,
        )
        executor = _BoundTransportExecutor.__new__(
            _BoundTransportExecutor,
            _seal=_CONSTRUCTION_SEAL,
        )
        with lock:
            registry[executor] = state
            observations[executor] = []
            next_executor_generation += 1
        return executor

    def consume(value: object) -> _ExecutorSnapshot | None:
        if type(value) is not _BoundTransportExecutor:
            return None
        with lock:
            validated = validate_locked(value)
            if validated is None:
                return None
            state, target = validated
            dispatcher_key = cast(str, state[3])
            identity_bytes = cast(bytes, state[4])
            policy_digest = cast(str, state[5])
            route_config = cast(bytes, state[6])
            stored_mac = cast(bytes, state[12])
            validated_target_invoke = cast(
                Callable[[object, str, str], Awaitable[str]],
                state[15],
            )
            try:
                identity = ModelIdentity.model_validate_json(identity_bytes)
            except Exception:
                return None
            if identity.model_dump_json().encode("utf-8") != identity_bytes:
                return None
            authority_digest = sha256_function(
                b"insurancekb.transport-authority.v1\0"
                + stored_mac
                + route_config
            ).digest()

        async def execute(
            supplied_identity: ModelIdentity,
            request: ModelCallRequest,
            /,
        ) -> object:
            if supplied_identity != identity:
                raise ModelGatewayDenied("authority_revalidation_failed")
            with lock:
                revalidated = validate_locked(value, state)
                if revalidated is None:
                    raise ModelGatewayDenied("authority_revalidation_failed")
                current_target = revalidated[1]
            if dispatcher_key == "test:success":
                success_result = await _require_exact_transport_str("weak-result")
                with lock:
                    observations.setdefault(value, []).append(
                        (identity, request, get_running_loop(), get_ident())
                    )
                return success_result
            if dispatcher_key == "test:failure":
                with lock:
                    observations.setdefault(value, []).append(
                        (identity, request, get_running_loop(), get_ident())
                    )
                raise RuntimeError("provider transport failed")
            if dispatcher_key == "test:cancel":
                with lock:
                    observations.setdefault(value, []).append(
                        (identity, request, get_running_loop(), get_ident())
                    )
                raise CancelledError
            result: object
            if dispatcher_key == "test:nested":
                async def nested_result() -> object:
                    return "nested-result"

                result = nested_result()
            elif dispatcher_key == "test:generator":
                def deferred_generator() -> Iterator[object]:
                    yield "deferred-result"

                result = deferred_generator()
            elif dispatcher_key == "test:async-generator":
                async def deferred_async_generator() -> AsyncIterator[object]:
                    yield "deferred-result"

                result = deferred_async_generator()
            elif dispatcher_key == "test:bytes":
                result = b"weak-result"
            elif dispatcher_key == "test:object":
                result = object()
            elif dispatcher_key == "test:bare-awaitable":
                class BareLazyProviderAwaitable:
                    __slots__ = ("deferred_calls",)

                    def __init__(self) -> None:
                        self.deferred_calls = 0

                    def __await__(self) -> Generator[object, None, object]:
                        self.deferred_calls += 1
                        if False:
                            yield None
                        return "deferred-provider-result"

                result = BareLazyProviderAwaitable()
            elif dispatcher_key == "test:slow-aclose":
                class SlowAsyncCloseResult:
                    __slots__ = ("cleanup_entered", "cleanup_resume")

                    def __init__(self) -> None:
                        self.cleanup_entered = AsyncEvent()
                        self.cleanup_resume = AsyncEvent()

                    async def aclose(self) -> None:
                        self.cleanup_entered.set()
                        await self.cleanup_resume.wait()

                result = SlowAsyncCloseResult()
            else:
                if current_target is None:
                    raise ModelGatewayDenied("authority_revalidation_failed")
                system = request.rendered_prompt.decode("utf-8", errors="strict")
                user = request.content.decode("utf-8", errors="strict")
                result = await validated_target_invoke(current_target, system, user)
            if dispatcher_key in {
                "test:nested",
                "test:generator",
                "test:async-generator",
                "test:bare-awaitable",
                "test:slow-aclose",
            }:
                with lock:
                    deferred_results.setdefault(value, []).append(result)
            validated_result = await _require_exact_transport_str(result)
            with lock:
                observations.setdefault(value, []).append(
                    (identity, request, get_running_loop(), get_ident())
                )
            return validated_result

        return identity, policy_digest, authority_digest, execute

    def calls(value: object) -> tuple[tuple[ModelIdentity, ModelCallRequest], ...]:
        with lock:
            records = observations.get(value)
            if records is None:
                return ()
            return tuple((record[0], record[1]) for record in records)

    def detailed_observations(
        value: object,
    ) -> tuple[_ExecutorObservation, ...]:
        with lock:
            records = observations.get(value)
            return () if records is None else tuple(records)

    def deferred(value: object) -> tuple[object, ...]:
        with lock:
            records = deferred_results.get(value)
            return () if records is None else tuple(records)

    def reset() -> None:
        nonlocal deferred_results, lock, mac_key, next_executor_generation, observations
        nonlocal process_generation, process_pid
        nonlocal registry
        lock = RLock()
        registry = WeakKeyDictionary()
        observations = WeakKeyDictionary()
        deferred_results = WeakKeyDictionary()
        process_pid = os.getpid()
        process_generation += 1
        next_executor_generation = 1
        mac_key = secrets.token_bytes(32)

    return issue, consume, calls, detailed_observations, deferred, reset


(
    _issue_executor,
    _consume_executor,
    _test_executor_terminal_observations,
    _test_executor_terminal_details,
    _test_executor_deferred_results,
    _reset_executor_authority_after_fork,
) = _make_executor_authority(
    _stateful_target_snapshot,
    _invoke_stateful_target,
)


def _make_bound_transport_authority(
    consume_executor: Callable[[object], _ExecutorSnapshot | None],
) -> tuple[
    Callable[[object, frozenset[IdentityKey]], _BoundModelTransport],
    Callable[
        [object],
        tuple[ModelIdentity, str, bytes, _ExecutionCall] | None,
    ],
    Callable[[], None],
]:
    lock = RLock()
    registry: WeakKeyDictionary[object, tuple[object, ...]] = WeakKeyDictionary()
    process_pid = os.getpid()
    process_generation = 1

    def bind(
        executor: object,
        approved_identity_keys: frozenset[IdentityKey],
    ) -> _BoundModelTransport:
        executor_snapshot = consume_executor(executor)
        policy = ProductionModelPolicy(approved_identity_keys)
        if executor_snapshot is None:
            raise ModelGatewayDenied("invalid_gateway")
        identity, executor_policy_digest, authority_digest, execution_call = (
            executor_snapshot
        )
        del execution_call
        try:
            policy.evaluate(identity)
        except Exception:
            raise ModelGatewayDenied("invalid_transport_identity") from None
        if executor_policy_digest != policy.policy_snapshot_digest:
            raise ModelGatewayDenied("invalid_transport_identity")
        adapter = _CanonicalModelTransportAdapter.__new__(
            _CanonicalModelTransportAdapter,
            _seal=_CONSTRUCTION_SEAL,
        )
        descriptor = getattr_static(_CanonicalModelTransportAdapter, "call", None)
        if (
            not isinstance(descriptor, FunctionType)
            or not _function_is_isolatable(
                descriptor,
                require_coroutine=True,
                parameter_names=("self", "identity", "request"),
            )
        ):
            raise ModelGatewayDenied("invalid_gateway")
        binding = _BoundModelTransport.__new__(
            _BoundModelTransport,
            _seal=_CONSTRUCTION_SEAL,
        )
        state: tuple[object, ...] = (
            process_generation,
            process_pid,
            identity.model_dump_json().encode("utf-8"),
            policy.policy_snapshot_digest,
            adapter,
            executor,
            descriptor,
            descriptor.__code__,
            authority_digest,
        )
        with lock:
            registry[binding] = state
        return binding

    def snapshot(
        value: object,
    ) -> tuple[ModelIdentity, str, bytes, _ExecutionCall] | None:
        if type(value) is not _BoundModelTransport:
            return None
        with lock:
            state = registry.get(value)
            if (
                state is None
                or state[0] != process_generation
                or state[1] != process_pid
                or os.getpid() != process_pid
            ):
                return None
            identity_bytes = cast(bytes, state[2])
            policy_digest = cast(str, state[3])
            adapter = state[4]
            executor = state[5]
            descriptor = state[6]
            code = state[7]
            expected_authority_digest = state[8]
            if (
                type(adapter) is not _CanonicalModelTransportAdapter
                or not isinstance(descriptor, FunctionType)
                or getattr_static(_CanonicalModelTransportAdapter, "call", None)
                is not descriptor
                or descriptor.__code__ is not code
                or not isinstance(expected_authority_digest, bytes)
            ):
                return None
            executor_snapshot = consume_executor(executor)
            if executor_snapshot is None:
                return None
            executor_identity, executor_policy, authority_digest, execution_call = (
                executor_snapshot
            )
            try:
                identity = ModelIdentity.model_validate_json(identity_bytes)
            except Exception:
                return None
            if (
                identity.model_dump_json().encode("utf-8") != identity_bytes
                or executor_identity != identity
                or executor_policy != policy_digest
                or authority_digest != expected_authority_digest
            ):
                return None
            return identity, policy_digest, authority_digest, execution_call

    def reset() -> None:
        nonlocal lock, process_generation, process_pid, registry
        lock = RLock()
        registry = WeakKeyDictionary()
        process_pid = os.getpid()
        process_generation += 1

    return bind, snapshot, reset


(
    _bind_model_transport,
    _bound_transport_snapshot,
    _reset_bound_transport_registry_after_fork,
) = _make_bound_transport_authority(_consume_executor)


def _issue_test_model_executor_for_test(
    *,
    composition: ProductionModelComposition,
    transport_identity: ModelIdentity,
    mode: str = "success",
) -> _BoundTransportExecutor:
    """Issue a package-owned primitive-mode executor for deterministic tests."""

    if mode not in {
        "success",
        "failure",
        "cancel",
        "nested",
        "generator",
        "async-generator",
        "bytes",
        "object",
        "bare-awaitable",
        "slow-aclose",
    }:
        raise ModelGatewayDenied("invalid_gateway")
    identity, policy_digest = _validated_executor_identity(
        composition,
        transport_identity,
    )
    route_config = json.dumps(
        {"mode": mode},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _issue_executor(
        f"test:{mode}",
        identity,
        policy_digest,
        route_config,
        None,
    )


def _build_stateful_model_client_target_for_test(
    *,
    endpoint: str,
    model: str,
    credential: str,
    result: str = "stateful-result",
) -> object:
    return _build_stateful_target(endpoint, model, credential, result)


def _issue_stateful_model_client_executor_for_test(
    *,
    composition: ProductionModelComposition,
    transport_identity: ModelIdentity,
    target: object,
) -> _BoundTransportExecutor:
    """Explicitly seal one stateful async ModelClient-shaped test target."""

    identity, policy_digest = _validated_executor_identity(
        composition,
        transport_identity,
    )
    target_state = _stateful_target_snapshot(target)
    if target_state is None:
        raise ModelGatewayDenied("invalid_gateway")
    try:
        config = json.loads(target_state[0].decode("utf-8"))
    except Exception:
        raise ModelGatewayDenied("invalid_gateway") from None
    if config.get("model") != identity.deployment_id:
        raise ModelGatewayDenied("invalid_gateway")
    return _issue_executor(
        "test:model-client",
        identity,
        policy_digest,
        target_state[0],
        target,
    )


def _make_bound_transport_reset(
    reset_binding: Callable[[], None],
    reset_executor: Callable[[], None],
    reset_target: Callable[[], None],
) -> Callable[[], None]:
    def reset() -> None:
        reset_binding()
        reset_executor()
        reset_target()

    return reset


_reset_bound_transport_authority_after_fork = _make_bound_transport_reset(
    _reset_bound_transport_registry_after_fork,
    _reset_executor_authority_after_fork,
    _reset_stateful_target_authority_after_fork,
)


def _make_gateway_reset(
    reset_transport: Callable[[], None],
) -> Callable[[], None]:
    lock_factory = RLock
    registry_factory = WeakKeyDictionary
    current_pid = os.getpid
    new_nonce = secrets.token_bytes

    def reset() -> None:
        global _AUTHORITY_NONCE, _AUTHORITY_PID
        global _GATEWAY_LOCK, _GATEWAY_STATES
        reset_transport()
        _GATEWAY_LOCK = lock_factory()
        _GATEWAY_STATES = registry_factory()
        _AUTHORITY_PID = current_pid()
        _AUTHORITY_NONCE = new_nonce(32)

    return reset


_reset_gateway_authority_after_fork = _make_gateway_reset(
    _reset_bound_transport_authority_after_fork
)


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_gateway_authority_after_fork)
