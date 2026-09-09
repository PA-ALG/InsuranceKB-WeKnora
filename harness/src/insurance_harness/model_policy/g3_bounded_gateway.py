"""Code-owned route, durable reservation, receipt sink and G3 gateway factory."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import secrets
import stat
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Annotated, Literal, Self, SupportsIndex, cast
from urllib.parse import urlsplit
from weakref import WeakKeyDictionary

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from insurance_harness.run_admission.g3_models import (
    G3BoundedAdmissionPlanV1,
    G3CallPlanV1,
    G3CallReservationV1,
    G3CallTerminalReceiptV1,
    G3PreparedReceiptV1,
    G3ProviderResponseMetaV1,
    G3ProviderUsageV1,
    G3ReservedChainBudgetV1,
    G3StageLedgerBindingV1,
    G3StageTerminalReceiptV1,
    G3StartedReceiptV1,
    canonical_g3_hash,
    canonical_json,
)

from .admission import VerifiedAdmission, _verified_authority_snapshot
from .composition import _bind_verified_production_model_composition
from .gateway import (
    GuardedModelClient,
    ModelGatewayDenied,
    _build_g3_guarded_model_client,
)
from .models import ModelCallRequest, ModelIdentity, PolicyReceipt

G3_LEDGER_ROOT = "/var/lib/insurancekb/g3-bounded-execution-ledger/v1"
_CAPABILITY_SEAL = object()
_PID = os.getpid()
_NONCE = secrets.token_bytes(32)
_LOCK = RLock()
_CAPABILITIES: WeakKeyDictionary[object, tuple[object, ...]] = WeakKeyDictionary()
_SINKS: WeakKeyDictionary[object, tuple[object, ...]] = WeakKeyDictionary()
_ACTIVE_SINKS: dict[str, G3LedgerPolicyReceiptSink] = {}
_RESPONSE_AUDIT: dict[str, tuple[G3ProviderResponseMetaV1, G3ProviderUsageV1 | None]] = {}
Sha256Hex = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]


def _is_g3_gemini_identity(identity: ModelIdentity) -> bool:
    return (
        identity.provider,
        identity.family,
        identity.deployment_id,
        identity.policy_version,
        identity.role,
    ) in {
        (
            "g3-user-gateway",
            "gemini",
            "gemini-3.7-flash-medium",
            "g3-user-gemini-gateway-v1",
            role,
        )
        for role in ("classify", "extract", "verify")
    }


def _strict_json(raw: bytes, *, label: str) -> object:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key in {label}")
            value[key] = item
        return value

    return json.loads(
        raw,
        object_pairs_hook=unique,
        parse_constant=lambda _value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON in {label}")
        ),
    )


def _parse_g3_gemini_provider_response(
    identity: ModelIdentity, raw: bytes
) -> tuple[str, bytes, G3ProviderUsageV1]:
    """Derive exact Gemini semantic bytes and normalized budget usage."""

    try:
        if not _is_g3_gemini_identity(identity):
            raise ValueError
        value = _strict_json(raw, label="Gemini response")
        if (
            type(value) is not dict
            or type(value.get("choices")) is not list
            or len(value["choices"]) != 1
        ):
            raise ValueError
        choice = value["choices"][0]
        if (
            type(choice) is not dict
            or type(choice.get("finish_reason")) is not str
            or not choice["finish_reason"]
            or choice["finish_reason"] == "length"
        ):
            raise ValueError
        message = choice.get("message")
        if (
            type(message) is not dict
            or type(message.get("content")) is not str
            or not message["content"]
        ):
            raise ValueError
        content = cast(str, message["content"])
        if (
            set(value) != {"id", "object", "created", "model", "choices", "usage"}
            or type(value["id"]) is not str
            or not value["id"]
            or value["object"] != "chat.completion"
            or type(value["created"]) is not int
            or value["created"] < 0
            or value["model"] != "gemini-3.7-flash-medium"
            or set(choice) != {"index", "message", "finish_reason"}
            or type(choice["index"]) is not int
            or choice["index"] != 0
            or choice["finish_reason"] != "stop"
            or set(message) != {"role", "content"}
            or message["role"] != "assistant"
        ):
            raise ValueError
        raw_usage = value["usage"]
        if type(raw_usage) is not dict:
            raise ValueError
        usage_keys = set(raw_usage)
        aggregate_keys = {"prompt_tokens", "completion_tokens", "total_tokens"}
        detailed_keys = aggregate_keys | {"completion_tokens_details"}
        if usage_keys not in (aggregate_keys, detailed_keys):
            raise ValueError
        prompt = raw_usage["prompt_tokens"]
        visible = raw_usage["completion_tokens"]
        total = raw_usage["total_tokens"]
        if any(type(item) is not int or item < 0 for item in (prompt, visible, total)):
            raise ValueError
        completion = visible
        if usage_keys == detailed_keys:
            details = raw_usage["completion_tokens_details"]
            if type(details) is not dict or set(details) != {"reasoning_tokens"}:
                raise ValueError
            reasoning = details["reasoning_tokens"]
            if type(reasoning) is not int or reasoning < 0:
                raise ValueError
            completion += reasoning
        if total != prompt + completion:
            raise ValueError
        semantic_value = _strict_json(content.encode(), label="Gemini message content")
        semantic_bytes = canonical_json(semantic_value)
        usage = G3ProviderUsageV1(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            usage_verified=True,
        )
        return semantic_bytes.decode(), semantic_bytes, usage
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise G3LedgerDenied("INVALID_PROVIDER_RESPONSE") from None


class G3LedgerDenied(PermissionError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__("G3 bounded ledger denied the operation")


class G3BoundedRouteConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    endpoint_origin: StrictStr
    endpoint_path: Literal[
        "/compatible-mode/v1/chat/completions", "/v1/chat/completions"
    ]
    timeout_seconds: Annotated[StrictInt, Field(gt=0)]
    follow_redirects: Literal[False]
    call_directory: StrictStr | None = None
    request_body_sha256: Sha256Hex | None = None
    prepared_receipt_sha256: Sha256Hex | None = None
    chain_manifest_hash: Sha256Hex | None = None
    stage: Literal["C_CLASSIFY", "D_COMPILE", "D_REVIEW"] | None = None
    admission_artifact_digest: Sha256Hex | None = None
    call_id: StrictStr | None = None
    ordinal: Annotated[StrictInt, Field(ge=0)] | None = None
    input_token_ceiling: Annotated[StrictInt, Field(gt=0)] | None = None
    output_token_ceiling: Annotated[StrictInt, Field(gt=0)] | None = None


def validate_g3_route(route: G3BoundedRouteConfig) -> G3BoundedRouteConfig:
    try:
        current = G3BoundedRouteConfig.model_validate(route.model_dump())
        parsed = urlsplit(current.endpoint_origin)
        route_key = (current.endpoint_origin, current.endpoint_path)
        if (
            route_key
            not in {
                (
                    "https://dashscope.aliyuncs.com",
                    "/compatible-mode/v1/chat/completions",
                ),
                ("http://8.148.158.241:3131", "/v1/chat/completions"),
            }
            or parsed.scheme
            != ("https" if route_key[0] == "https://dashscope.aliyuncs.com" else "http")
            or parsed.hostname
            != ("dashscope.aliyuncs.com" if parsed.scheme == "https" else "8.148.158.241")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError
        if parsed.port != (None if parsed.scheme == "https" else 3131):
            raise ValueError
        if current.call_directory is not None:
            call_dir = Path(current.call_directory)
            root = Path(G3_LEDGER_ROOT)
            if not call_dir.is_absolute() or not call_dir.is_relative_to(root):
                raise ValueError
        return current
    except Exception:
        raise G3LedgerDenied("INVALID_G3_ROUTE") from None


class G3CallReservationCapability:
    __slots__ = ("__weakref__",)

    def __new__(cls, *_args: object, _seal: object | None = None, **_kwargs: object) -> Self:
        if cls is not G3CallReservationCapability or _seal is not _CAPABILITY_SEAL:
            raise TypeError("reservation capabilities are issued by the fixed ledger")
        return super().__new__(cls)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise TypeError("reservation capability is immutable")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("reservation capability cannot be serialized")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> tuple[object, ...]:
        raise TypeError("reservation capability cannot be serialized")


def _reservation_snapshot(value: object) -> tuple[object, ...] | None:
    if type(value) is not G3CallReservationCapability:
        return None
    with _LOCK:
        state = _CAPABILITIES.get(value)
        if state is None or state[0] != _PID or state[1] != _NONCE or os.getpid() != _PID:
            return None
        call_dir = Path(str(state[2]))
        try:
            info = call_dir.stat(follow_symlinks=False)
        except OSError:
            return None
        if (
            not stat.S_ISDIR(info.st_mode)
            or call_dir.is_symlink()
            or (info.st_dev, info.st_ino) != state[3]
        ):
            return None
        return state


class G3LedgerPolicyReceiptSink:
    __slots__ = ("__weakref__",)

    def __new__(cls, *_args: object, _seal: object | None = None, **_kwargs: object) -> Self:
        if cls is not G3LedgerPolicyReceiptSink or _seal is not _CAPABILITY_SEAL:
            raise TypeError("ledger sinks are factory-owned")
        return super().__new__(cls)

    def record(self, receipt: PolicyReceipt) -> None:
        with _LOCK:
            state = _SINKS.get(self)
        if state is None or state[0] != _PID or state[1] != _NONCE:
            raise G3LedgerDenied("INVALID_LEDGER_SINK")
        path = Path(str(state[2])) / "policy-receipt.json"
        _write_exclusive(path, receipt.model_dump_json().encode("utf-8"))


def _write_exclusive(path: Path, payload: bytes) -> None:
    temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(16)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short ledger write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.link(temporary, path, follow_symlinks=False)
        directory_fd = os.open(
            path.parent, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _g3_reservation_key(
    plan: G3BoundedAdmissionPlanV1,
    call: G3CallPlanV1,
    admission_artifact_digest: str,
) -> str:
    key_payload = {
        "admission_artifact_digest": admission_artifact_digest,
        "call_id": call.call_id,
        "chain_manifest_hash": plan.chain_manifest_hash,
        "ordinal": call.ordinal,
        "stage": plan.stage,
    }
    return hashlib.sha256(
        b"g3-call-reservation-key.830.v1\0"
        + json.dumps(key_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def reserve_g3_call(
    *,
    plan: G3BoundedAdmissionPlanV1,
    call: G3CallPlanV1,
    admission_artifact_digest: Sha256Hex,
) -> G3CallReservationCapability:
    """Atomically consume one fixed-ledger leaf; an existing leaf always denies."""

    from insurance_harness.run_admission.profiles.g3_bounded_execution import (
        validate_g3_bounded_plan,
    )

    try:
        plan = validate_g3_bounded_plan(plan)
    except ValueError:
        raise G3LedgerDenied("INVALID_CALL_RESERVATION") from None
    if (
        type(admission_artifact_digest) is not str
        or len(admission_artifact_digest) != 64
        or any(character not in "0123456789abcdef" for character in admission_artifact_digest)
        or call not in plan.request_manifest.calls
        or call.stage != plan.stage
    ):
        raise G3LedgerDenied("INVALID_CALL_RESERVATION")
    key = _g3_reservation_key(plan, call, admission_artifact_digest)
    root = Path(G3_LEDGER_ROOT)
    try:
        root_info = root.stat(follow_symlinks=False)
        if (
            not stat.S_ISDIR(root_info.st_mode)
            or root.is_symlink()
            or stat.S_IMODE(root_info.st_mode) != 0o700
            or root_info.st_uid != os.geteuid()
        ):
            raise OSError
        chain_dir = root / "chains" / plan.chain_manifest_hash
        calls_dir = chain_dir / "calls"
        bindings_dir = chain_dir / "stage-bindings"
        terminals_dir = chain_dir / "stage-terminals"
        for directory in (chain_dir, calls_dir, bindings_dir, terminals_dir):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            info = directory.stat(follow_symlinks=False)
            if (
                directory.is_symlink()
                or not stat.S_ISDIR(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o700
                or info.st_uid != os.geteuid()
            ):
                raise OSError
        lock_path = chain_dir / ".chain.lock"
        lock_fd = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            if (terminals_dir / f"{plan.stage}.json").exists():
                raise G3LedgerDenied("DUPLICATE_OR_LEDGER_CONFLICT")
            binding_path = bindings_dir / f"{plan.stage}.json"
            if binding_path.exists():
                binding_raw = binding_path.read_bytes()
                binding = G3StageLedgerBindingV1.model_validate_json(binding_raw)
                if (
                    binding.admission_artifact_digest != admission_artifact_digest
                    or binding.chain_manifest_hash != plan.chain_manifest_hash
                    or binding.receipt_sha256
                    != canonical_g3_hash(
                        "g3-stage-ledger-binding.830.v1", binding, "receipt_sha256"
                    )
                ):
                    raise G3LedgerDenied("DUPLICATE_OR_LEDGER_CONFLICT")
            else:
                provisional_binding = G3StageLedgerBindingV1(
                    contract="g3-stage-ledger-binding.830.v1",
                    chain_manifest_hash=plan.chain_manifest_hash,
                    parent_authorization_digest=plan.parent_authorization_digest,
                    stage=plan.stage,
                    admission_artifact_digest=admission_artifact_digest,
                    bound_at=datetime.now(UTC),
                    receipt_sha256="0" * 64,
                )
                binding = provisional_binding.model_copy(
                    update={
                        "receipt_sha256": canonical_g3_hash(
                            "g3-stage-ledger-binding.830.v1",
                            provisional_binding,
                            "receipt_sha256",
                        )
                    }
                )
                _write_exclusive(
                    binding_path,
                    canonical_json(binding.model_dump(mode="json", round_trip=True)),
                )
            calls_reserved = 0
            input_reserved = 0
            output_reserved = 0
            time_reserved = 0
            for child in calls_dir.iterdir():
                if not child.is_dir() or child.is_symlink():
                    raise G3LedgerDenied("RESERVATION_INCOMPLETE")
                reservation_path = child / "reservation.json"
                if not reservation_path.is_file():
                    raise G3LedgerDenied("RESERVATION_INCOMPLETE")
                prior = G3CallReservationV1.model_validate_json(reservation_path.read_bytes())
                stage_order = ("C_CLASSIFY", "D_COMPILE", "D_REVIEW")
                if (
                    prior.stage not in stage_order
                    or stage_order.index(prior.stage) > stage_order.index(plan.stage)
                ):
                    raise G3LedgerDenied("RESERVATION_INCOMPLETE")
                prior_call = next(
                    (
                        candidate
                        for candidate in plan.request_manifest.calls
                        if candidate.call_id == prior.call_id and candidate.ordinal == prior.ordinal
                    ),
                    None,
                )
                prior_binding = G3StageLedgerBindingV1.model_validate_json(
                    (bindings_dir / f"{prior.stage}.json").read_bytes()
                )
                same_stage = prior.stage == plan.stage
                if (
                    child.name != prior.reservation_key_sha256
                    or prior.contract != "g3-call-reservation.830.v1"
                    or prior.chain_manifest_hash != plan.chain_manifest_hash
                    or prior.parent_authorization_digest != plan.parent_authorization_digest
                    or prior.admission_artifact_digest
                    != prior_binding.admission_artifact_digest
                    or prior.stage_binding_receipt_sha256 != prior_binding.receipt_sha256
                    or prior_binding.chain_manifest_hash != plan.chain_manifest_hash
                    or prior_binding.parent_authorization_digest
                    != plan.parent_authorization_digest
                    or prior_binding.stage != prior.stage
                    or prior_binding.receipt_sha256
                    != canonical_g3_hash(
                        "g3-stage-ledger-binding.830.v1",
                        prior_binding,
                        "receipt_sha256",
                    )
                    or (
                        same_stage
                        and (
                            prior.admission_artifact_digest != admission_artifact_digest
                            or prior.stage_binding_receipt_sha256 != binding.receipt_sha256
                            or prior_call is None
                            or prior.input_tokens_reserved
                            != prior_call.input_token_ceiling
                            or prior.output_tokens_reserved
                            != prior_call.output_token_ceiling
                            or prior.time_seconds_reserved != prior_call.timeout_seconds
                        )
                    )
                    or prior.receipt_sha256
                    != canonical_g3_hash("g3-call-reservation.830.v1", prior, "receipt_sha256")
                ):
                    raise G3LedgerDenied("RESERVATION_INCOMPLETE")
                started_exists = (child / "started.json").exists()
                terminal_path = child / "call-terminal.json"
                if not terminal_path.exists():
                    raise G3LedgerDenied(
                        "OUTCOME_UNKNOWN" if started_exists else "RESERVATION_INCOMPLETE"
                    )
                if not started_exists:
                    raise G3LedgerDenied("RESERVATION_INCOMPLETE")
                terminal = G3CallTerminalReceiptV1.model_validate_json(terminal_path.read_bytes())
                if (
                    terminal.contract != "g3-call-terminal-receipt.830.v1"
                    or terminal.receipt_sha256
                    != canonical_g3_hash(
                        "g3-call-terminal-receipt.830.v1",
                        terminal,
                        "receipt_sha256",
                    )
                    or terminal.call_reservation_receipt_sha256 != prior.receipt_sha256
                    or terminal.admission_artifact_digest
                    != prior.admission_artifact_digest
                    or terminal.call_id != prior.call_id
                    or terminal.ordinal != prior.ordinal
                    or terminal.stage != prior.stage
                    or terminal.status != "SUCCESS"
                    or (same_stage and terminal.ordinal >= call.ordinal)
                ):
                    raise G3LedgerDenied("RESERVATION_INCOMPLETE")
                if not same_stage:
                    prior_stage_terminal = G3StageTerminalReceiptV1.model_validate_json(
                        (terminals_dir / f"{prior.stage}.json").read_bytes()
                    )
                    if (
                        prior_stage_terminal.status != "SUCCESS"
                        or prior_stage_terminal.chain_id != plan.chain_id
                        or prior_stage_terminal.parent_authorization_digest
                        != plan.parent_authorization_digest
                        or prior_stage_terminal.admission_artifact_digest
                        != prior.admission_artifact_digest
                        or terminal.receipt_sha256
                        not in prior_stage_terminal.call_terminal_sha256s
                        or prior_stage_terminal.receipt_sha256
                        != canonical_g3_hash(
                            "g3-stage-terminal-receipt.830.v1",
                            prior_stage_terminal,
                            "receipt_sha256",
                        )
                    ):
                        raise G3LedgerDenied("RESERVATION_INCOMPLETE")
                calls_reserved += 1
                input_reserved += prior.input_tokens_reserved
                output_reserved += prior.output_tokens_reserved
                time_reserved += prior.time_seconds_reserved
            budget = plan.chain_manifest
            if (
                calls_reserved + 1 > budget.max_calls
                or input_reserved + call.input_token_ceiling > budget.total_input_token_ceiling
                or output_reserved + call.output_token_ceiling > budget.total_output_token_ceiling
                or time_reserved + call.timeout_seconds > budget.total_time_limit_seconds
            ):
                raise G3LedgerDenied("CHAIN_BUDGET_EXHAUSTED")
            call_dir = calls_dir / key
            os.mkdir(call_dir, 0o700)
            provisional = G3CallReservationV1(
                contract="g3-call-reservation.830.v1",
                chain_manifest_hash=plan.chain_manifest_hash,
                parent_authorization_digest=plan.parent_authorization_digest,
                stage=plan.stage,
                admission_artifact_digest=admission_artifact_digest,
                call_id=call.call_id,
                call_id_sha256=hashlib.sha256(call.call_id.encode()).hexdigest(),
                ordinal=call.ordinal,
                reservation_key_sha256=key,
                call_limit_reserved=1,
                input_tokens_reserved=call.input_token_ceiling,
                output_tokens_reserved=call.output_token_ceiling,
                time_seconds_reserved=call.timeout_seconds,
                stage_binding_receipt_sha256=binding.receipt_sha256,
                reserved_at=datetime.now(UTC),
                receipt_sha256="0" * 64,
            )
            reservation = provisional.model_copy(
                update={
                    "receipt_sha256": canonical_g3_hash(
                        "g3-call-reservation.830.v1", provisional, "receipt_sha256"
                    )
                }
            )
            _write_exclusive(
                call_dir / "reservation.json",
                canonical_json(reservation.model_dump(mode="json", round_trip=True)),
            )
            reserved_budget = G3ReservedChainBudgetV1(
                calls_reserved=calls_reserved + 1,
                input_tokens_reserved=input_reserved + call.input_token_ceiling,
                output_tokens_reserved=output_reserved + call.output_token_ceiling,
                time_seconds_reserved=time_reserved + call.timeout_seconds,
                calls_remaining_after_reservation=budget.max_calls - calls_reserved - 1,
                input_tokens_remaining_after_reservation=(
                    budget.total_input_token_ceiling - input_reserved - call.input_token_ceiling
                ),
                output_tokens_remaining_after_reservation=(
                    budget.total_output_token_ceiling - output_reserved - call.output_token_ceiling
                ),
                time_seconds_remaining_after_reservation=(
                    budget.total_time_limit_seconds - time_reserved - call.timeout_seconds
                ),
            )
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)
        info = call_dir.stat(follow_symlinks=False)
    except FileExistsError:
        raise G3LedgerDenied("DUPLICATE_OR_LEDGER_CONFLICT") from None
    except OSError:
        raise G3LedgerDenied("LEDGER_UNAVAILABLE") from None
    capability = G3CallReservationCapability.__new__(
        G3CallReservationCapability, _seal=_CAPABILITY_SEAL
    )
    with _LOCK:
        _CAPABILITIES[capability] = (
            _PID,
            _NONCE,
            str(call_dir),
            (info.st_dev, info.st_ino),
            reservation,
            reserved_budget,
        )
    return capability


def _read_secure_ledger_file(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
        ):
            raise G3LedgerDenied("LEDGER_UNAVAILABLE")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError:
        raise G3LedgerDenied("LEDGER_UNAVAILABLE") from None
    finally:
        os.close(descriptor)


def _read_completed_g3_call_leaf(
    *,
    plan: G3BoundedAdmissionPlanV1,
    call: G3CallPlanV1,
    admission_artifact_digest: Sha256Hex,
    chain_dir: Path,
    call_dir: Path,
) -> tuple[G3CallTerminalReceiptV1, bytes, bytes, str]:
    """Validate one completed call leaf while the caller holds the chain lock."""

    required = {
        name: call_dir / name
        for name in (
            "reservation.json",
            "prepared.json",
            "policy-receipt.json",
            "request-body.private.json",
            "started.json",
            "response-body.private.json",
            "semantic-content.private.json",
            "call-terminal.json",
        )
    }
    if not required["started.json"].exists():
        raise G3LedgerDenied("RESERVATION_INCOMPLETE")
    if not required["call-terminal.json"].exists():
        raise G3LedgerDenied("OUTCOME_UNKNOWN")
    reservation_bytes = _read_secure_ledger_file(required["reservation.json"])
    prepared_bytes = _read_secure_ledger_file(required["prepared.json"])
    policy_bytes = _read_secure_ledger_file(required["policy-receipt.json"])
    started_bytes = _read_secure_ledger_file(required["started.json"])
    terminal_bytes = _read_secure_ledger_file(required["call-terminal.json"])
    reservation = G3CallReservationV1.model_validate_json(reservation_bytes)
    prepared = G3PreparedReceiptV1.model_validate_json(prepared_bytes)
    policy_receipt = PolicyReceipt.model_validate_json(policy_bytes)
    started = G3StartedReceiptV1.model_validate_json(started_bytes)
    terminal = G3CallTerminalReceiptV1.model_validate_json(terminal_bytes)
    binding_bytes = _read_secure_ledger_file(
        chain_dir / "stage-bindings" / f"{plan.stage}.json"
    )
    binding = G3StageLedgerBindingV1.model_validate_json(binding_bytes)
    if (
        reservation.chain_manifest_hash != plan.chain_manifest_hash
        or reservation.parent_authorization_digest != plan.parent_authorization_digest
        or reservation.stage != plan.stage
        or reservation.admission_artifact_digest != admission_artifact_digest
        or reservation.call_id != call.call_id
        or reservation.ordinal != call.ordinal
        or reservation.reservation_key_sha256 != call_dir.name
        or reservation.receipt_sha256
        != canonical_g3_hash("g3-call-reservation.830.v1", reservation, "receipt_sha256")
        or binding.chain_manifest_hash != plan.chain_manifest_hash
        or binding.parent_authorization_digest != plan.parent_authorization_digest
        or binding.stage != plan.stage
        or binding.admission_artifact_digest != admission_artifact_digest
        or binding.receipt_sha256
        != canonical_g3_hash("g3-stage-ledger-binding.830.v1", binding, "receipt_sha256")
        or reservation.stage_binding_receipt_sha256 != binding.receipt_sha256
        or prepared.call_reservation_receipt_sha256 != reservation.receipt_sha256
        or prepared.admission_artifact_digest != admission_artifact_digest
        or prepared.stage != plan.stage
        or prepared.call_id != call.call_id
        or prepared.ordinal != call.ordinal
        or prepared.request_body_sha256 != call.request_body_sha256
        or prepared.request_bytes != call.request_bytes
        or prepared.input_token_estimate != call.input_token_estimate
        or prepared.input_token_ceiling != call.input_token_ceiling
        or prepared.output_token_ceiling != call.output_token_ceiling
        or prepared.timeout_seconds != call.timeout_seconds
        or prepared.receipt_sha256
        != canonical_g3_hash("g3-prepared-receipt.830.v1", prepared, "receipt_sha256")
        or started.prepared_receipt_sha256 != prepared.receipt_sha256
        or not started.call_consumed
        or started.receipt_sha256
        != canonical_g3_hash("g3-started-receipt.830.v1", started, "receipt_sha256")
        or policy_receipt.decision != "ALLOW"
        or policy_receipt.identity_key != call.identity.identity_key
        or policy_receipt.admission_hash != admission_artifact_digest
        or hashlib.sha256(policy_bytes).hexdigest() != terminal.policy_receipt_sha256
        or terminal.chain_id != plan.chain_id
        or terminal.stage != plan.stage
        or terminal.call_id != call.call_id
        or terminal.ordinal != call.ordinal
        or terminal.run_id != plan.run_id
        or terminal.run_revision != plan.run_revision
        or terminal.admission_artifact_digest != admission_artifact_digest
        or terminal.call_reservation_receipt_sha256 != reservation.receipt_sha256
        or terminal.identity != call.identity
        or terminal.endpoint_origin != call.endpoint_origin
        or terminal.endpoint_path != call.endpoint_path
        or terminal.request_body_sha256 != call.request_body_sha256
        or terminal.request_bytes != call.request_bytes
        or terminal.started_receipt_sha256 != started.receipt_sha256
        or terminal.receipt_sha256
        != canonical_g3_hash(
            "g3-call-terminal-receipt.830.v1", terminal, "receipt_sha256"
        )
    ):
        raise G3LedgerDenied("RESERVATION_INCOMPLETE")
    if terminal.status != "SUCCESS":
        response_path = required["response-body.private.json"]
        if terminal.status == "FAILED":
            if not response_path.exists():
                raise G3LedgerDenied("RESERVATION_INCOMPLETE")
            failed_response = _read_secure_ledger_file(response_path)
            if (
                terminal.response_meta is None
                or terminal.response_body_sha256
                != hashlib.sha256(failed_response).hexdigest()
                or terminal.response_bytes != len(failed_response)
                or terminal.semantic_content_sha256 is not None
                or terminal.projection_sha256 is not None
            ):
                raise G3LedgerDenied("RESERVATION_INCOMPLETE")
            raise G3LedgerDenied("TERMINAL_FAILED")
        if response_path.exists() or any(
            value is not None
            for value in (
                terminal.response_meta,
                terminal.response_body_sha256,
                terminal.response_bytes,
                terminal.semantic_content_sha256,
                terminal.projection_sha256,
                terminal.provider_usage,
            )
        ):
            raise G3LedgerDenied("RESERVATION_INCOMPLETE")
        raise G3LedgerDenied("OUTCOME_UNKNOWN")
    request_bytes = _read_secure_ledger_file(required["request-body.private.json"])
    response_bytes = _read_secure_ledger_file(required["response-body.private.json"])
    semantic_bytes = _read_secure_ledger_file(required["semantic-content.private.json"])
    if (
        hashlib.sha256(request_bytes).hexdigest() != call.request_body_sha256
        or len(request_bytes) != call.request_bytes
        or terminal.response_meta is None
        or terminal.provider_usage is None
        or terminal.response_body_sha256 != hashlib.sha256(response_bytes).hexdigest()
        or terminal.response_bytes != len(response_bytes)
        or terminal.semantic_content_sha256 != hashlib.sha256(semantic_bytes).hexdigest()
        or terminal.projection_sha256 is None
    ):
        raise G3LedgerDenied("RESERVATION_INCOMPLETE")
    if _is_g3_gemini_identity(call.identity):
        _content, derived_semantic, derived_usage = _parse_g3_gemini_provider_response(
            call.identity, response_bytes
        )
        if derived_semantic != semantic_bytes or derived_usage != terminal.provider_usage:
            raise G3LedgerDenied("RESERVATION_INCOMPLETE")
    return terminal, semantic_bytes, policy_bytes, str(call_dir)


def _reopen_completed_g3_call(
    *,
    plan: G3BoundedAdmissionPlanV1,
    call: G3CallPlanV1,
    admission_artifact_digest: Sha256Hex,
) -> tuple[G3CallTerminalReceiptV1, bytes, bytes, str] | None:
    """Reopen one exact successful call leaf without issuing transport authority."""

    from insurance_harness.run_admission.profiles.g3_bounded_execution import (
        validate_g3_bounded_plan,
    )

    try:
        plan = validate_g3_bounded_plan(plan)
    except ValueError:
        raise G3LedgerDenied("INVALID_CALL_RESERVATION") from None
    if call not in plan.request_manifest.calls or call.stage != plan.stage:
        raise G3LedgerDenied("INVALID_CALL_RESERVATION")
    root = Path(G3_LEDGER_ROOT)
    chain_dir = root / "chains" / plan.chain_manifest_hash
    call_dir = chain_dir / "calls" / _g3_reservation_key(
        plan, call, admission_artifact_digest
    )
    if not call_dir.exists():
        return None
    try:
        for directory in (root, chain_dir, chain_dir / "calls", call_dir):
            info = directory.stat(follow_symlinks=False)
            if (
                directory.is_symlink()
                or not stat.S_ISDIR(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o700
                or info.st_uid != os.geteuid()
            ):
                raise G3LedgerDenied("LEDGER_UNAVAILABLE")
        lock_fd = os.open(
            chain_dir / ".chain.lock",
            os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError:
        raise G3LedgerDenied("LEDGER_UNAVAILABLE") from None
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if (chain_dir / "stage-terminals" / f"{plan.stage}.json").exists():
            raise G3LedgerDenied("DUPLICATE_OR_LEDGER_CONFLICT")
        return _read_completed_g3_call_leaf(
            plan=plan,
            call=call,
            admission_artifact_digest=admission_artifact_digest,
            chain_dir=chain_dir,
            call_dir=call_dir,
        )
    except G3LedgerDenied:
        raise
    except (ValueError, OSError):
        raise G3LedgerDenied("RESERVATION_INCOMPLETE") from None
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _read_successful_g3_stage_call(
    *,
    plan: G3BoundedAdmissionPlanV1,
    call: G3CallPlanV1,
    admission_artifact_digest: Sha256Hex,
) -> tuple[G3CallTerminalReceiptV1, bytes, bytes, str]:
    """Read one successful call already sealed by its successful stage terminal."""

    from insurance_harness.run_admission.profiles.g3_bounded_execution import (
        validate_g3_bounded_plan,
    )

    try:
        plan = validate_g3_bounded_plan(plan)
    except ValueError:
        raise G3LedgerDenied("INVALID_CALL_RESERVATION") from None
    if call not in plan.request_manifest.calls or call.stage != plan.stage:
        raise G3LedgerDenied("INVALID_CALL_RESERVATION")
    root = Path(G3_LEDGER_ROOT)
    chain_dir = root / "chains" / plan.chain_manifest_hash
    call_dir = chain_dir / "calls" / _g3_reservation_key(
        plan, call, admission_artifact_digest
    )
    if not call_dir.exists():
        raise G3LedgerDenied("RESERVATION_INCOMPLETE")
    try:
        for directory in (root, chain_dir, chain_dir / "calls", call_dir):
            info = directory.stat(follow_symlinks=False)
            if (
                directory.is_symlink()
                or not stat.S_ISDIR(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o700
                or info.st_uid != os.geteuid()
            ):
                raise G3LedgerDenied("LEDGER_UNAVAILABLE")
        lock_fd = os.open(
            chain_dir / ".chain.lock",
            os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError:
        raise G3LedgerDenied("LEDGER_UNAVAILABLE") from None
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        stage_path = chain_dir / "stage-terminals" / f"{plan.stage}.json"
        if not stage_path.exists():
            raise G3LedgerDenied("RESERVATION_INCOMPLETE")
        stage_bytes = _read_secure_ledger_file(stage_path)
        stage_terminal = G3StageTerminalReceiptV1.model_validate_json(stage_bytes)
        if stage_bytes != canonical_json(
            stage_terminal.model_dump(mode="json", round_trip=True)
        ):
            raise G3LedgerDenied("RESERVATION_INCOMPLETE")
        if (
            stage_terminal.contract != "g3-stage-terminal-receipt.830.v1"
            or stage_terminal.chain_id != plan.chain_id
            or stage_terminal.stage != plan.stage
            or stage_terminal.parent_authorization_digest
            != plan.parent_authorization_digest
            or stage_terminal.admission_artifact_digest != admission_artifact_digest
            or stage_terminal.prior_terminal_receipt_sha256
            != plan.prior_terminal_receipt_sha256
            or stage_terminal.receipt_sha256
            != canonical_g3_hash(
                "g3-stage-terminal-receipt.830.v1",
                stage_terminal,
                "receipt_sha256",
            )
        ):
            raise G3LedgerDenied("RESERVATION_INCOMPLETE")
        if stage_terminal.status == "FAILED":
            raise G3LedgerDenied("TERMINAL_FAILED")
        if stage_terminal.status == "OUTCOME_UNKNOWN":
            raise G3LedgerDenied("OUTCOME_UNKNOWN")
        if stage_terminal.stage_output_sha256 is None:
            raise G3LedgerDenied("RESERVATION_INCOMPLETE")
        if not (call_dir / "started.json").exists() or not (
            call_dir / "call-terminal.json"
        ).exists():
            raise G3LedgerDenied("RESERVATION_INCOMPLETE")
        result = _read_completed_g3_call_leaf(
            plan=plan,
            call=call,
            admission_artifact_digest=admission_artifact_digest,
            chain_dir=chain_dir,
            call_dir=call_dir,
        )
        call_terminal = result[0]
        if (
            stage_terminal.stage_binding_receipt_sha256
            != G3CallReservationV1.model_validate_json(
                _read_secure_ledger_file(call_dir / "reservation.json")
            ).stage_binding_receipt_sha256
            or stage_terminal.calls_consumed != len(plan.request_manifest.calls)
            or len(stage_terminal.call_terminal_sha256s)
            != len(plan.request_manifest.calls)
            or stage_terminal.call_terminal_sha256s[call.ordinal]
            != call_terminal.receipt_sha256
        ):
            raise G3LedgerDenied("RESERVATION_INCOMPLETE")
        return result
    except G3LedgerDenied:
        raise
    except (IndexError, ValueError, OSError):
        raise G3LedgerDenied("RESERVATION_INCOMPLETE") from None
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def build_g3_bounded_model_client(
    *,
    verified_admission: VerifiedAdmission,
    transport_identity: ModelIdentity,
    route_config: G3BoundedRouteConfig,
    reservation_capability: G3CallReservationCapability,
) -> GuardedModelClient:
    """Build the only G3 guarded client; paths and sinks are derived internally."""

    state = _reservation_snapshot(reservation_capability)
    if state is None:
        raise ModelGatewayDenied("invalid_gateway")
    route = validate_g3_route(route_config)
    call_dir = Path(str(state[2]))
    if route.call_directory != str(call_dir):
        raise ModelGatewayDenied("invalid_gateway")
    verified = _verified_authority_snapshot(verified_admission)
    if verified is None:
        raise ModelGatewayDenied("invalid_verified_admission")
    _request, binding, _receipt = verified
    composition = _bind_verified_production_model_composition(
        verified_admission,
        expected_identities=(transport_identity,),
        expected_model_plan_hash=binding.actual_model_plan_hash,
    )
    sink = G3LedgerPolicyReceiptSink.__new__(G3LedgerPolicyReceiptSink, _seal=_CAPABILITY_SEAL)
    with _LOCK:
        _SINKS[sink] = (_PID, _NONCE, str(call_dir))
        if str(call_dir) in _ACTIVE_SINKS:
            raise ModelGatewayDenied("invalid_gateway")
        _ACTIVE_SINKS[str(call_dir)] = sink
    return _build_g3_guarded_model_client(
        composition=composition,
        verified_admission=verified_admission,
        transport_identity=transport_identity,
        route_config=route,
        reservation_capability=reservation_capability,
        receipt_sink=sink,
    )


def prepare_g3_reserved_call(
    *,
    plan: G3BoundedAdmissionPlanV1,
    call: G3CallPlanV1,
    admission_artifact_digest: Sha256Hex,
    verified_binding_digest: Sha256Hex,
    reservation_capability: G3CallReservationCapability,
) -> G3BoundedRouteConfig:
    """Persist the exact prepared receipt and derive the sealed transport route."""

    state = _reservation_snapshot(reservation_capability)
    if state is None:
        raise G3LedgerDenied("INVALID_CALL_RESERVATION")
    reservation = state[4]
    budget = state[5]
    if type(reservation) is not G3CallReservationV1 or type(budget) is not G3ReservedChainBudgetV1:
        raise G3LedgerDenied("INVALID_CALL_RESERVATION")
    if (
        reservation.call_id != call.call_id
        or reservation.ordinal != call.ordinal
        or reservation.admission_artifact_digest != admission_artifact_digest
    ):
        raise G3LedgerDenied("INVALID_CALL_RESERVATION")
    provisional = G3PreparedReceiptV1(
        contract="g3-prepared-receipt.830.v1",
        chain_id=plan.chain_id,
        stage=plan.stage,
        call_id=call.call_id,
        ordinal=call.ordinal,
        admission_artifact_digest=admission_artifact_digest,
        verified_binding_digest=verified_binding_digest,
        call_reservation_receipt_sha256=reservation.receipt_sha256,
        request_body_sha256=call.request_body_sha256,
        request_bytes=call.request_bytes,
        input_token_estimate=call.input_token_estimate,
        input_token_ceiling=call.input_token_ceiling,
        output_token_ceiling=call.output_token_ceiling,
        timeout_seconds=call.timeout_seconds,
        reserved_chain_budget=budget,
        prepared_at=datetime.now(UTC),
        receipt_sha256="0" * 64,
    )
    prepared = provisional.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-prepared-receipt.830.v1", provisional, "receipt_sha256"
            )
        }
    )
    call_dir = Path(str(state[2]))
    _write_exclusive(
        call_dir / "prepared.json",
        canonical_json(prepared.model_dump(mode="json", round_trip=True)),
    )
    return G3BoundedRouteConfig(
        endpoint_origin=call.endpoint_origin,
        endpoint_path=call.endpoint_path,
        timeout_seconds=call.timeout_seconds,
        follow_redirects=False,
        call_directory=str(call_dir),
        request_body_sha256=call.request_body_sha256,
        prepared_receipt_sha256=prepared.receipt_sha256,
        chain_manifest_hash=plan.chain_manifest_hash,
        stage=plan.stage,
        admission_artifact_digest=admission_artifact_digest,
        call_id=call.call_id,
        ordinal=call.ordinal,
        input_token_ceiling=call.input_token_ceiling,
        output_token_ceiling=call.output_token_ceiling,
    )


def consume_g3_response_audit(
    reservation_capability: G3CallReservationCapability,
) -> tuple[G3ProviderResponseMetaV1, G3ProviderUsageV1 | None]:
    state = _reservation_snapshot(reservation_capability)
    if state is None:
        raise G3LedgerDenied("INVALID_CALL_RESERVATION")
    with _LOCK:
        value = _RESPONSE_AUDIT.pop(str(state[2]), None)
        _ACTIVE_SINKS.pop(str(state[2]), None)
    if value is None:
        raise G3LedgerDenied("RESPONSE_AUDIT_UNAVAILABLE")
    return value


async def _fixed_openai_compatible_dispatch(
    route_config: bytes,
    identity: ModelIdentity,
    request: ModelCallRequest,
) -> str:
    """Single fixed POST. Unit tests never call this function against a network."""

    route = validate_g3_route(G3BoundedRouteConfig.model_validate_json(route_config))
    qwen_route = (
        identity.provider == "bailian"
        and identity.family == "qwen"
        and route.endpoint_origin == "https://dashscope.aliyuncs.com"
        and route.endpoint_path == "/compatible-mode/v1/chat/completions"
    )
    gemini_route = (
        _is_g3_gemini_identity(identity)
        and route.endpoint_origin == "http://8.148.158.241:3131"
        and route.endpoint_path == "/v1/chat/completions"
    )
    if (
        not (qwen_route or gemini_route)
        or route.call_directory is None
        or route.request_body_sha256 is None
        or route.prepared_receipt_sha256 is None
        or route.chain_manifest_hash is None
        or route.stage is None
        or route.admission_artifact_digest is None
        or route.call_id is None
        or route.ordinal is None
        or route.input_token_ceiling is None
        or route.output_token_ceiling is None
    ):
        raise G3LedgerDenied("RESERVATION_INCOMPLETE")
    body = request.content
    if hashlib.sha256(body).hexdigest() != route.request_body_sha256:
        raise G3LedgerDenied("REQUEST_BODY_MISMATCH")
    call_dir = Path(route.call_directory)
    chain_dir = call_dir.parents[1]
    lock_fd = os.open(
        chain_dir / ".chain.lock",
        os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        reservation = G3CallReservationV1.model_validate_json(
            (call_dir / "reservation.json").read_bytes()
        )
        prepared = G3PreparedReceiptV1.model_validate_json(
            (call_dir / "prepared.json").read_bytes()
        )
        policy_receipt = PolicyReceipt.model_validate_json(
            (call_dir / "policy-receipt.json").read_bytes()
        )
        if (
            reservation.chain_manifest_hash != route.chain_manifest_hash
            or reservation.stage != route.stage
            or reservation.admission_artifact_digest != route.admission_artifact_digest
            or reservation.call_id != route.call_id
            or reservation.ordinal != route.ordinal
            or reservation.receipt_sha256
            != canonical_g3_hash("g3-call-reservation.830.v1", reservation, "receipt_sha256")
            or prepared.receipt_sha256 != route.prepared_receipt_sha256
            or prepared.receipt_sha256
            != canonical_g3_hash("g3-prepared-receipt.830.v1", prepared, "receipt_sha256")
            or prepared.stage != route.stage
            or prepared.call_id != route.call_id
            or prepared.ordinal != route.ordinal
            or prepared.admission_artifact_digest != route.admission_artifact_digest
            or prepared.verified_binding_digest != policy_receipt.verified_binding_digest
            or prepared.request_body_sha256 != route.request_body_sha256
            or prepared.request_bytes != len(body)
            or prepared.input_token_ceiling != route.input_token_ceiling
            or prepared.output_token_ceiling != route.output_token_ceiling
            or prepared.timeout_seconds != route.timeout_seconds
            or prepared.call_reservation_receipt_sha256 != reservation.receipt_sha256
            or policy_receipt.decision != "ALLOW"
            or policy_receipt.identity_key != identity.identity_key
            or policy_receipt.admission_hash != route.admission_artifact_digest
            or (call_dir / "started.json").exists()
        ):
            raise G3LedgerDenied("DUPLICATE_OR_LEDGER_CONFLICT")
        _write_exclusive(call_dir / "request-body.private.json", body)
        provisional_started = G3StartedReceiptV1(
            contract="g3-started-receipt.830.v1",
            prepared_receipt_sha256=route.prepared_receipt_sha256,
            started_at=datetime.now(UTC),
            monotonic_start_ns=__import__("time").monotonic_ns(),
            call_consumed=True,
            receipt_sha256="0" * 64,
        )
        started = provisional_started.model_copy(
            update={
                "receipt_sha256": canonical_g3_hash(
                    "g3-started-receipt.830.v1",
                    provisional_started,
                    "receipt_sha256",
                )
            }
        )
        _write_exclusive(
            call_dir / "started.json",
            canonical_json(started.model_dump(mode="json", round_trip=True)),
        )
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)
    key = os.environ.get("G3_BOUNDED_MODEL_API_KEY")
    if not key:
        raise G3LedgerDenied("MISSING_PROVIDER_CREDENTIAL")
    timeout = httpx.Timeout(float(route.timeout_seconds))
    async with asyncio.timeout(float(route.timeout_seconds)):
        async with httpx.AsyncClient(
            timeout=timeout, trust_env=False, follow_redirects=False, verify=True
        ) as client:
            response = await client.post(
                route.endpoint_origin.rstrip("/") + route.endpoint_path,
                content=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
    raw = response.content
    _write_exclusive(call_dir / "response-body.private.json", raw)
    received_content_type = (
        response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    content_type = received_content_type or "MISSING"
    request_ids = response.headers.get_list("x-request-id")
    provider_request_id = request_ids[0] if len(request_ids) == 1 and request_ids[0] else None
    headers_value = {
        "content_type": content_type,
        "provider_request_id": provider_request_id,
    }
    response_meta = G3ProviderResponseMetaV1(
        http_status=response.status_code,
        content_type=content_type,
        provider_request_id=provider_request_id,
        canonical_headers_sha256=hashlib.sha256(
            b"g3-provider-response-headers.830.v1\0" + canonical_json(headers_value)
        ).hexdigest(),
    )
    with _LOCK:
        if str(call_dir) in _RESPONSE_AUDIT:
            raise G3LedgerDenied("DUPLICATE_OR_LEDGER_CONFLICT")
        _RESPONSE_AUDIT[str(call_dir)] = (response_meta, None)
    if not received_content_type:
        raise G3LedgerDenied("INVALID_PROVIDER_RESPONSE")
    response.raise_for_status()
    if _is_g3_gemini_identity(identity):
        content, semantic_bytes, usage = _parse_g3_gemini_provider_response(identity, raw)
    else:
        value = json.loads(raw)
        if (
            type(value) is not dict
            or type(value.get("choices")) is not list
            or len(value["choices"]) != 1
        ):
            raise G3LedgerDenied("INVALID_PROVIDER_RESPONSE")
        choice = value["choices"][0]
        if (
            type(choice) is not dict
            or type(choice.get("finish_reason")) is not str
            or not choice["finish_reason"]
            or choice["finish_reason"] == "length"
        ):
            raise G3LedgerDenied("INVALID_PROVIDER_RESPONSE")
        message = choice.get("message")
        if (
            type(message) is not dict
            or type(message.get("content")) is not str
            or not message["content"]
        ):
            raise G3LedgerDenied("INVALID_PROVIDER_RESPONSE")
        content = cast(str, message["content"])
        semantic_bytes = content.encode()
        usage = G3ProviderUsageV1.model_validate(
            {**value.get("usage", {}), "usage_verified": True}
        )
    if (
        usage.prompt_tokens > route.input_token_ceiling
        or usage.completion_tokens > route.output_token_ceiling
    ):
        raise G3LedgerDenied("PROVIDER_USAGE_EXCEEDS_CAP")
    with _LOCK:
        _RESPONSE_AUDIT[str(call_dir)] = (response_meta, usage)
    _write_exclusive(call_dir / "semantic-content.private.json", semantic_bytes)
    return content


__all__ = [
    "G3BoundedRouteConfig",
    "G3CallReservationCapability",
    "G3LedgerDenied",
    "G3LedgerPolicyReceiptSink",
    "G3_LEDGER_ROOT",
    "build_g3_bounded_model_client",
    "consume_g3_response_audit",
    "prepare_g3_reserved_call",
    "reserve_g3_call",
    "validate_g3_route",
]
