"""Fail-closed model-call boundary for an admitted Golden-set run."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal, Protocol

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)

from insurance_harness.goldenset.admission import (
    AdmissionBlocker,
    AdmissionResult,
    InitialExecutionAuthorization,
    ProductionAdmissionEvaluator,
    ReviewedExecutionAuthorization,
    RunAdmissionDocument,
    RuntimeAdmissionDecision,
)
from insurance_harness.goldenset.admission_budget import (
    SQLITE_SAFE_INTEGER_MAX,
    AccountSnapshot,
    AttemptKey,
    BudgetAmounts,
    BudgetLedger,
    ProductReserve,
    RequestPoolReserve,
    RequestReserve,
    RoleRate,
    SendPermit,
    model_role_budget_identity_hash,
    role_rate_cost,
)
from insurance_harness.goldenset.admission_models import (
    ModelRolePlan,
    canonical_json_bytes,
)

type ModelRole = Literal["annotator", "weak_extractor", "judge"]

_REQUEST_UNIT_DOMAIN = b"insurancekb.run-admission.request-unit.v1\0"
_RESPONSE_PATH_DOMAIN = b"insurancekb.run-admission.response-path.v1\0"
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_MAX_PROVIDER_ENVELOPE_BYTES = _MAX_RESPONSE_BYTES
_BAILIAN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_BAILIAN_POLICY = "bailian-deployment-detail-v1"
_BAILIAN_CREDENTIAL_ENV = "HARNESS_DASHSCOPE_API_KEY"
_FIRST_CANARY_STAGE = "annotation"
_FIRST_CANARY_PRODUCT_ID = "平安爱满分（2026）两全保险"


class AdmissionBlockedError(RuntimeError):
    """Fresh admission evaluation refused the product boundary."""

    def __init__(self, result: AdmissionResult) -> None:
        super().__init__("fresh run admission is BLOCKED")
        self.result = result


class AdmissionPausedError(RuntimeError):
    """Execution must pause because safe automatic replay is not possible."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ApprovedModelResponse(BaseModel):
    """Strict provider response with independently verifiable usage provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    content: StrictStr
    input_tokens: Annotated[StrictInt, Field(ge=0)]
    output_tokens: Annotated[StrictInt, Field(ge=0)]
    usage_verified: StrictBool
    usage_unrepresentable: StrictBool = False

    @model_validator(mode="after")
    def require_consistent_usage_provenance(self) -> ApprovedModelResponse:
        if self.usage_unrepresentable and self.usage_verified:
            raise ValueError("unrepresentable provider usage cannot be verified")
        return self


def request_unit_fingerprint(
    role: ModelRole,
    role_plan: ModelRolePlan,
    system: str,
    user: str,
) -> str:
    """Bind one reserve to its role, approved model identity, and exact prompts."""

    payload = canonical_json_bytes(
        {
            "model_role_identity_hash": model_role_budget_identity_hash(role_plan),
            "role": role,
            "system": system,
            "user": user,
        }
    )
    return hashlib.sha256(_REQUEST_UNIT_DOMAIN + payload).hexdigest()


class ApprovedModelInvoker(Protocol):
    """Code-owned invocation surface receiving the exact admitted identity/bound."""

    async def complete(
        self,
        *,
        role_plan: ModelRolePlan,
        maximum: BudgetAmounts,
        system: str,
        user: str,
    ) -> ApprovedModelResponse: ...


class _BailianApprovedModelInvoker:
    """Production invoker sealed to the sole provider policy admitted by change 020."""

    async def complete(
        self,
        *,
        role_plan: ModelRolePlan,
        maximum: BudgetAmounts,
        system: str,
        user: str,
    ) -> ApprovedModelResponse:
        role_plan = _validated_bailian_role_plan(role_plan)
        if (
            role_plan.provider != "bailian"
            or role_plan.protocol != "https"
            or role_plan.base_url != _BAILIAN_BASE_URL
            or role_plan.provider_policy != _BAILIAN_POLICY
            or role_plan.credential_env_name != _BAILIAN_CREDENTIAL_ENV
        ):
            raise AdmissionPausedError("approved_model_policy_unsupported")
        if maximum.output_tokens <= 0:
            raise AdmissionPausedError("request_output_bound_invalid")
        api_key = os.environ.get(_BAILIAN_CREDENTIAL_ENV)
        if api_key is None or not api_key.strip():
            raise AdmissionPausedError("model_credential_missing")
        try:
            return await _invoke_bailian(
                role_plan=role_plan,
                maximum=maximum,
                system=system,
                user=user,
                api_key=api_key,
            )
        except AdmissionPausedError as exc:
            error_code = exc.code
        except Exception:
            error_code = "provider_request_failed"
        raise AdmissionPausedError(error_code) from None


async def _invoke_bailian(
    *,
    role_plan: ModelRolePlan,
    maximum: BudgetAmounts,
    system: str,
    user: str,
    api_key: str,
) -> ApprovedModelResponse:
    role_plan = _validated_bailian_role_plan(role_plan)
    async with httpx.AsyncClient(
        base_url=_BAILIAN_BASE_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=180.0,
        trust_env=False,
        follow_redirects=False,
    ) as client:
        async with client.stream(
            "POST",
            "/chat/completions",
            json={
                "model": role_plan.model_id,
                "temperature": 0.0,
                "max_tokens": maximum.output_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        ) as response:
            if response.status_code != 200:
                raise AdmissionPausedError("provider_request_failed")
            declared_length = response.headers.get("content-length")
            if declared_length is not None:
                length = None
                try:
                    length = int(declared_length)
                except ValueError:
                    pass
                if length is None:
                    raise AdmissionPausedError("provider_response_invalid")
                if length < 0 or length > _MAX_PROVIDER_ENVELOPE_BYTES:
                    raise AdmissionPausedError("provider_response_too_large")
            payload = bytearray()
            async for chunk in response.aiter_bytes():
                payload.extend(chunk)
                if len(payload) > _MAX_PROVIDER_ENVELOPE_BYTES:
                    raise AdmissionPausedError("provider_response_too_large")
    data = json.loads(bytes(payload))
    if not isinstance(data, Mapping):
        raise AdmissionPausedError("provider_response_invalid")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AdmissionPausedError("provider_response_invalid")
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise AdmissionPausedError("provider_response_invalid")
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise AdmissionPausedError("provider_response_invalid")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise AdmissionPausedError("provider_response_invalid")
    if len(content.encode("utf-8")) > _MAX_RESPONSE_BYTES:
        raise AdmissionPausedError("model_response_too_large")
    input_tokens, output_tokens, usage_verified, usage_unrepresentable = _strict_provider_usage(
        data
    )
    return ApprovedModelResponse(
        content=content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        usage_verified=usage_verified,
        usage_unrepresentable=usage_unrepresentable,
    )


def _validated_bailian_role_plan(role_plan: ModelRolePlan) -> ModelRolePlan:
    """Revalidate the invocable identity at each production mutation boundary."""

    try:
        validated = ModelRolePlan.model_validate(
            {
                field_name: getattr(role_plan, field_name)
                for field_name in ModelRolePlan.model_fields
            }
        )
    except (AttributeError, TypeError, ValueError):
        raise AdmissionPausedError("approved_model_identity_not_invocable") from None
    if (
        validated.immutable_deployment_id is None
        or validated.immutable_deployment_id != validated.model_id
    ):
        raise AdmissionPausedError("approved_model_identity_not_invocable")
    if (
        validated.provider != "bailian"
        or validated.protocol != "https"
        or validated.base_url != _BAILIAN_BASE_URL
        or validated.provider_policy != _BAILIAN_POLICY
        or validated.credential_env_name != _BAILIAN_CREDENTIAL_ENV
    ):
        raise AdmissionPausedError("approved_model_policy_unsupported")
    return validated


def _strict_provider_usage(
    data: Mapping[object, object],
) -> tuple[int, int, bool, bool]:
    usage = data.get("usage")
    if not isinstance(usage, Mapping):
        return 0, 0, False, False
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    if (
        type(input_tokens) is not int
        or type(output_tokens) is not int
        or input_tokens < 0
        or output_tokens < 0
    ):
        return 0, 0, False, False
    if input_tokens > SQLITE_SAFE_INTEGER_MAX or output_tokens > SQLITE_SAFE_INTEGER_MAX:
        return 0, 0, False, True
    return input_tokens, output_tokens, True, False


class _ResponseStore:
    """Owned response directory held by dirfd so later path swaps are irrelevant."""

    def __init__(self, root: Path) -> None:
        self.path = Path(os.path.abspath(root))
        self._lock = Lock()
        self.dir_fd = -1
        open_failed = False
        try:
            self.dir_fd = _open_owned_directory(self.path)
        except AdmissionPausedError:
            raise
        except OSError:
            open_failed = True
        if open_failed:
            raise AdmissionPausedError("response_root_unsafe")

    def __del__(self) -> None:
        self.close()

    def close(self) -> None:
        """Idempotently release the held directory capability."""

        lock = getattr(self, "_lock", None)
        if lock is None:
            return
        with lock:
            descriptor = getattr(self, "dir_fd", -1)
            self.dir_fd = -1
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass

    @contextmanager
    def lease(self) -> Iterator[int]:
        """Duplicate the directory capability for one complete request lifecycle."""

        with self._lock:
            if self.dir_fd < 0:
                raise AdmissionPausedError("runtime_guard_closed")
            descriptor = -1
            try:
                descriptor = os.dup(self.dir_fd)
            except OSError:
                pass
        if descriptor < 0:
            raise AdmissionPausedError("response_root_unsafe")
        try:
            yield descriptor
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass


class AdmissionRuntimeGuard:
    """Re-evaluate the immutable admission document at every product boundary."""

    def __init__(
        self,
        *,
        document: RunAdmissionDocument,
        evaluator: ProductionAdmissionEvaluator,
        ledger: BudgetLedger,
        response_root: Path,
    ) -> None:
        self._initialize(
            document=document,
            evaluator=evaluator,
            ledger=ledger,
            response_root=response_root,
            model_invoker=_BailianApprovedModelInvoker(),
            enforce_execution_authorization=True,
        )

    @classmethod
    def _for_testing(
        cls,
        *,
        document: RunAdmissionDocument,
        evaluator: ProductionAdmissionEvaluator,
        ledger: BudgetLedger,
        response_root: Path,
        model_invoker: ApprovedModelInvoker,
        enforce_execution_authorization: bool = False,
    ) -> AdmissionRuntimeGuard:
        instance = cls.__new__(cls)
        instance._initialize(
            document=document,
            evaluator=evaluator,
            ledger=ledger,
            response_root=response_root,
            model_invoker=model_invoker,
            enforce_execution_authorization=enforce_execution_authorization,
        )
        return instance

    def _initialize(
        self,
        *,
        document: RunAdmissionDocument,
        evaluator: ProductionAdmissionEvaluator,
        ledger: BudgetLedger,
        response_root: Path,
        model_invoker: ApprovedModelInvoker,
        enforce_execution_authorization: bool,
    ) -> None:
        if type(enforce_execution_authorization) is not bool:
            raise TypeError("execution authorization enforcement must be boolean")
        self._document = document
        self._evaluator = evaluator
        self._ledger = ledger
        self._response_store = _ResponseStore(response_root)
        self._model_invoker = model_invoker
        self._enforce_execution_authorization = enforce_execution_authorization

    def recover_incomplete_at_startup(self) -> int:
        """Revalidate, then recover ambiguous attempts before any workers start."""

        result, account = self._fresh_account()
        if result.state != "READY" or account is None:
            raise AdmissionBlockedError(result)
        recovered = 0
        recovery_failed = False
        try:
            recovered = self._ledger.recover_incomplete(account.account_id)
        except Exception:
            recovery_failed = True
        if recovery_failed:
            raise AdmissionPausedError("attempt_recovery_failed")
        return recovered

    def begin_product(self, *, stage: str, product_id: str) -> ProductAdmission:
        if self._enforce_execution_authorization:
            return self._begin_authorized_product(stage=stage, product_id=product_id)
        result, account = self._fresh_account()
        if result.state != "READY" or account is None:
            raise AdmissionBlockedError(result)
        reserve = _find_product_reserve(self._document, stage, product_id)
        contract = self._document.budget_contract
        if contract is None:
            raise AdmissionPausedError("budget_contract_missing")
        reservation_failed = False
        try:
            self._ledger.reserve_product(
                account.account_id,
                reserve.stage,
                reserve.product_id,
                reserve.maximum,
            )
        except Exception:
            reservation_failed = True
        if reservation_failed:
            raise AdmissionPausedError("product_budget_reservation_failed")
        return ProductAdmission(
            _ProductAdmissionBinding(
                account=account,
                reserve=reserve,
                ledger=self._ledger,
                response_store=self._response_store,
                model_roles=self._document.plan.payload.model_roles,
                role_rates=contract.role_rates,
                model_invoker=self._model_invoker,
                execution_decision=None,
            )
        )

    def _begin_authorized_product(self, *, stage: str, product_id: str) -> ProductAdmission:
        with self._response_store.lease():
            pass
        decision = None
        try:
            decision = self._evaluator.evaluate_execution(self._document, self._ledger)
        except Exception:
            pass
        if decision is None:
            raise AdmissionPausedError("admission_evaluation_failed")
        authorization = decision.authorization
        account = decision.account
        if decision.result.state != "READY" or authorization is None or account is None:
            raise AdmissionBlockedError(decision.result)
        target = (stage, product_id)
        granted_targets = tuple((item.stage, item.product_id) for item in authorization.targets)
        if target not in granted_targets:
            blocked_result = decision.result.model_copy(
                update={
                    "state": "BLOCKED",
                    "blockers": (
                        AdmissionBlocker(
                            check="execution_authorization",
                            code="execution_target_unauthorized",
                        ),
                    ),
                }
            )
            raise AdmissionBlockedError(blocked_result)
        reserve = _find_product_reserve(self._document, stage, product_id)
        contract = self._document.budget_contract
        if contract is None:
            raise AdmissionPausedError("budget_contract_missing")

        if isinstance(authorization, InitialExecutionAuthorization):
            revalidation_failed = False
            try:
                self._evaluator.revalidate_initial_authorization(
                    self._document,
                    authorization,
                )
            except Exception:
                revalidation_failed = True
            if revalidation_failed:
                raise AdmissionPausedError("initial_execution_authorization_invalid")
            reservation_failed = False
            try:
                self._ledger.reserve_product_for_authorized_snapshot(
                    account_id=authorization.account_id,
                    expected_account_revision=authorization.account_revision,
                    expected_approval_digest=authorization.account_approval_digest,
                    authorization_evaluated_at=authorization.evaluated_at,
                    authorization_expires_at=authorization.expires_at,
                    stage=reserve.stage,
                    product_id=reserve.product_id,
                    maximum=reserve.maximum,
                )
            except Exception:
                reservation_failed = True
            if reservation_failed:
                raise AdmissionPausedError("initial_authorized_reservation_failed")
        elif isinstance(authorization, ReviewedExecutionAuthorization):
            revalidation_failed = False
            try:
                self._evaluator.revalidate_review_authorization(self._document, authorization)
            except Exception:
                revalidation_failed = True
            if revalidation_failed:
                raise AdmissionPausedError("reviewed_execution_authorization_invalid")
            claim_failed = False
            try:
                self._ledger.claim_canary_capability_and_reserve(
                    account_id=authorization.account_id,
                    capability_digest=authorization.capability_digest,
                    canary_stage=_FIRST_CANARY_STAGE,
                    canary_product_id=_FIRST_CANARY_PRODUCT_ID,
                    expected_settlement_digest=(authorization.settlement_snapshot_digest),
                    authorization_evaluated_at=authorization.evaluated_at,
                    authorization_expires_at=authorization.expires_at,
                    target_stage=reserve.stage,
                    target_product_id=reserve.product_id,
                    target_maximum=reserve.maximum,
                    granted_targets=granted_targets,
                )
            except Exception:
                claim_failed = True
            if claim_failed:
                raise AdmissionPausedError("reviewed_capability_claim_failed")
        else:
            raise AdmissionPausedError("execution_authorization_invalid")

        return ProductAdmission(
            _ProductAdmissionBinding(
                account=account,
                reserve=reserve,
                ledger=self._ledger,
                response_store=self._response_store,
                model_roles=self._document.plan.payload.model_roles,
                role_rates=contract.role_rates,
                model_invoker=self._model_invoker,
                execution_decision=decision,
            )
        )

    def _fresh_account(self) -> tuple[AdmissionResult, AccountSnapshot | None]:
        with self._response_store.lease():
            pass
        evaluated: tuple[AdmissionResult, AccountSnapshot | None] | None = None
        try:
            evaluated = self._evaluator.admit_budget_account(self._document, self._ledger)
        except Exception:
            pass
        if evaluated is None:
            raise AdmissionPausedError("admission_evaluation_failed")
        return evaluated

    def close(self) -> None:
        self._response_store.close()

    def __enter__(self) -> AdmissionRuntimeGuard:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


@dataclass(frozen=True)
class _ProductAdmissionBinding:
    account: AccountSnapshot
    reserve: ProductReserve
    ledger: BudgetLedger
    response_store: _ResponseStore
    model_roles: Mapping[str, object]
    role_rates: Mapping[str, RoleRate]
    model_invoker: ApprovedModelInvoker
    execution_decision: RuntimeAdmissionDecision | None


class ProductAdmission:
    """A single freshly admitted and durably reserved product boundary."""

    def __init__(self, binding: _ProductAdmissionBinding) -> None:
        self._account = binding.account
        self._reserve = binding.reserve
        self._ledger = binding.ledger
        self._response_store = binding.response_store
        self._model_roles = binding.model_roles
        self._role_rates = binding.role_rates
        self._model_invoker = binding.model_invoker
        self._execution_decision = binding.execution_decision

    @property
    def execution_decision(self) -> RuntimeAdmissionDecision:
        """Return the exact fresh decision that authorized this product boundary."""

        if self._execution_decision is None:
            raise AdmissionPausedError("execution_decision_unavailable")
        return self._execution_decision

    def client(self, *, role: ModelRole) -> AdmittedModelClient:
        role_plan = self._model_roles.get(role)
        if not isinstance(role_plan, ModelRolePlan):
            raise AdmissionPausedError("approved_model_identity_pending")
        role_rate = self._role_rates.get(role)
        if not isinstance(role_rate, RoleRate):
            raise AdmissionPausedError("approved_role_rate_missing")
        return AdmittedModelClient(
            _AdmittedClientBinding(
                account_id=self._account.account_id,
                product_reserve=self._reserve,
                role=role,
                role_plan=role_plan,
                role_rate=role_rate,
                model_invoker=self._model_invoker,
                ledger=self._ledger,
                response_store=self._response_store,
            )
        )

    def settle(self) -> None:
        settlement_failed = False
        try:
            self._ledger.settle_product(
                self._account.account_id,
                self._reserve.stage,
                self._reserve.product_id,
            )
        except Exception:
            settlement_failed = True
        if settlement_failed:
            raise AdmissionPausedError("product_budget_settlement_failed")


@dataclass(frozen=True)
class _AdmittedClientBinding:
    account_id: str
    product_reserve: ProductReserve
    role: ModelRole
    role_plan: ModelRolePlan
    role_rate: RoleRate
    model_invoker: ApprovedModelInvoker
    ledger: BudgetLedger
    response_store: _ResponseStore


class AdmittedModelClient:
    """ModelClient wrapper created only from a freshly admitted product binding."""

    def __init__(self, binding: _AdmittedClientBinding) -> None:
        self._account_id = binding.account_id
        self._product_reserve = binding.product_reserve
        self._role = binding.role
        self._role_plan = binding.role_plan
        self._role_rate = binding.role_rate
        self._model_invoker = binding.model_invoker
        self._ledger = binding.ledger
        self._response_store = binding.response_store

    async def complete(self, system: str, user: str) -> str:
        with self._response_store.lease() as response_dir_fd:
            request_unit = request_unit_fingerprint(self._role, self._role_plan, system, user)
            reserve = self._request_reserve(request_unit)
            key = AttemptKey(
                account_id=self._account_id,
                stage=self._product_reserve.stage,
                product_id=self._product_reserve.product_id,
                request_unit=request_unit,
                attempt_no=1,
            )
            maximum = (
                reserve.maximum
                if isinstance(reserve, RequestReserve)
                else reserve.per_attempt_maximum
            )
            permit = None
            claim_failed = False
            try:
                if isinstance(reserve, RequestReserve):
                    permit = self._ledger.claim_attempt(
                        self._account_id,
                        self._product_reserve.stage,
                        self._product_reserve.product_id,
                        request_unit,
                        1,
                        secrets.token_hex(32),
                        maximum,
                    )
                else:
                    permit = self._ledger.claim_pool_attempt(
                        account_id=self._account_id,
                        stage=self._product_reserve.stage,
                        product_id=self._product_reserve.product_id,
                        request_unit=request_unit,
                        attempt_no=1,
                        owner_token=secrets.token_hex(32),
                        role=self._role,
                        maximum=maximum,
                    )
            except Exception:
                claim_failed = True
            if claim_failed:
                raise AdmissionPausedError("request_budget_claim_failed")
            if permit is None:
                return self._observe_existing(key, response_dir_fd)
            return await self._complete_as_owner(permit, system, user, response_dir_fd)

    def _request_reserve(self, request_unit: str) -> RequestReserve | RequestPoolReserve:
        matches = tuple(
            reserve
            for reserve in self._product_reserve.request_reserves
            if reserve.request_unit == request_unit and reserve.role == self._role
        )
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise AdmissionPausedError("ambiguous_request_unit")
        pools = tuple(
            pool for pool in self._product_reserve.request_pools if pool.role == self._role
        )
        if len(pools) != 1:
            raise AdmissionPausedError("unsigned_request_unit")
        return pools[0]

    def _observe_existing(self, key: AttemptKey, response_dir_fd: int) -> str:
        snapshot = None
        try:
            snapshot = self._ledger.attempt_snapshot(key)
        except Exception:
            pass
        if snapshot is None:
            raise AdmissionPausedError("request_attempt_unavailable")
        if snapshot.state != "terminal" or snapshot.response_digest is None:
            raise AdmissionPausedError("request_attempt_not_terminal")
        return _read_verified_response(response_dir_fd, key, snapshot.response_digest)

    async def _complete_as_owner(
        self,
        permit: SendPermit,
        system: str,
        user: str,
        response_dir_fd: int,
    ) -> str:
        cancelled = False
        failure_code: str | None = None
        try:
            self._ledger.mark_sent(permit)
            response = await self._model_invoker.complete(
                role_plan=self._role_plan,
                maximum=permit.maximum,
                system=system,
                user=user,
            )
            if not isinstance(response, ApprovedModelResponse):
                raise TypeError("inner model response must be typed")
            usage_verified = response.usage_verified
            force_overage = response.usage_unrepresentable
            actual = _verified_actual(response, self._role_rate) if usage_verified else None
            if actual is None:
                actual = permit.maximum
                force_overage = force_overage or usage_verified
                usage_verified = False
            digest = _write_response(
                response_dir_fd,
                permit.key,
                permit.owner_token,
                response.content,
            )
            self._ledger.record_terminal(
                permit,
                actual=actual,
                response_digest=digest,
                usage_verified=usage_verified,
                force_overage=force_overage,
            )
            return response.content
        except asyncio.CancelledError:
            cancelled = True
        except Exception as exc:
            if isinstance(exc, AdmissionPausedError):
                failure_code = exc.code
            else:
                failure_code = "model_attempt_ambiguous"
        if not self._mark_uncertain(permit):
            raise AdmissionPausedError("uncertain_settlement_failed")
        if cancelled:
            raise asyncio.CancelledError
        if failure_code is None:  # Defensive: the try either returned or failed above.
            raise AdmissionPausedError("model_attempt_ambiguous")
        raise AdmissionPausedError(failure_code)

    def _mark_uncertain(self, permit: SendPermit) -> bool:
        try:
            self._ledger.mark_uncertain(permit)
        except Exception:
            return False
        return True


def _verified_actual(response: ApprovedModelResponse, rate: RoleRate) -> BudgetAmounts | None:
    cost = role_rate_cost(
        rate,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
    if cost > SQLITE_SAFE_INTEGER_MAX:
        return None
    return BudgetAmounts(
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cost_minor_units=cost,
    )


def _find_product_reserve(
    document: RunAdmissionDocument, stage: str, product_id: str
) -> ProductReserve:
    contract = document.budget_contract
    if contract is None:
        raise AdmissionPausedError("budget_contract_missing")
    matches = tuple(
        reserve
        for reserve in contract.product_reserves
        if reserve.stage == stage and reserve.product_id == product_id
    )
    if len(matches) != 1:
        raise AdmissionPausedError("product_reserve_missing")
    return matches[0]


def _open_owned_directory(root: Path) -> int:
    if not root.is_absolute() or any(part in {"", ".", ".."} for part in root.parts[1:]):
        raise AdmissionPausedError("response_root_unsafe")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(root.anchor, flags)
    try:
        for part in root.parts[1:]:
            created = False
            child = -1
            try:
                child = os.open(
                    part,
                    flags | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
                created = True
                child = os.open(
                    part,
                    flags | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
            try:
                if created:
                    os.fsync(descriptor)
                os.close(descriptor)
            except BaseException:
                os.close(child)
                raise
            descriptor = child
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise AdmissionPausedError("response_root_unsafe")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _response_name(key: AttemptKey) -> str:
    digest = hashlib.sha256(_RESPONSE_PATH_DOMAIN + canonical_json_bytes(key)).hexdigest()
    return f"{digest}.response"


def _write_response(
    response_dir_fd: int,
    key: AttemptKey,
    owner_token: str,
    response: str,
) -> str:
    payload = response.encode("utf-8")
    if len(payload) > _MAX_RESPONSE_BYTES:
        raise AdmissionPausedError("model_response_too_large")
    destination = _response_name(key)
    owner_digest = hashlib.sha256(owner_token.encode("utf-8")).hexdigest()
    temporary = f".{destination}.{owner_digest}.tmp"
    descriptor = -1
    write_failed = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=response_dir_fd,
        )
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(
            temporary,
            destination,
            src_dir_fd=response_dir_fd,
            dst_dir_fd=response_dir_fd,
        )
        os.fsync(response_dir_fd)
    except OSError:
        write_failed = True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=response_dir_fd)
        except OSError:
            pass
    if write_failed:
        raise AdmissionPausedError("response_persistence_failed")
    return hashlib.sha256(payload).hexdigest()


def _read_verified_response(
    response_dir_fd: int,
    key: AttemptKey,
    expected_digest: str,
) -> str:
    name = _response_name(key)
    descriptor = -1
    payload = None
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=response_dir_fd,
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_RESPONSE_BYTES:
            raise AdmissionPausedError("terminal_response_unsafe")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            payload = stream.read(_MAX_RESPONSE_BYTES + 1)
    except OSError:
        pass
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if payload is None:
        raise AdmissionPausedError("terminal_response_unavailable")
    if len(payload) > _MAX_RESPONSE_BYTES:
        raise AdmissionPausedError("terminal_response_unsafe")
    if not secrets.compare_digest(hashlib.sha256(payload).hexdigest(), expected_digest):
        raise AdmissionPausedError("terminal_response_digest_mismatch")
    decoded = None
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if decoded is None:
        raise AdmissionPausedError("terminal_response_invalid_utf8")
    return decoded


__all__ = [
    "ApprovedModelResponse",
    "AdmissionBlockedError",
    "AdmissionPausedError",
    "AdmissionRuntimeGuard",
    "AdmittedModelClient",
    "ProductAdmission",
    "request_unit_fingerprint",
]
