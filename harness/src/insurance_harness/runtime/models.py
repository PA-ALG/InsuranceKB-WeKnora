"""Immutable, non-authority DTOs for the OpenSpec 028 runtime contract."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import unicodedata
import weakref
from collections.abc import Generator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from threading import RLock
from typing import Annotated, Any, Literal, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StrictStr,
    StringConstraints,
    field_validator,
    model_serializer,
    model_validator,
)

from insurance_harness.template_packages import ResolvedTemplate, canonical_content_hash

NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(
        min_length=1,
        max_length=512,
        pattern=r"^\S(?:[^\r\n]*\S)?$",
    ),
]
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

_PARENT_IDENTITY_DOMAIN = b"insurancekb.runtime.parent-intake-identity.v1\0"
_CHILD_IDENTITY_DOMAIN = b"insurancekb.runtime.child-compilation-identity.v2\0"
_SECTION_SET_DOMAIN = b"insurancekb.runtime.routed-section-set.v1\0"
_SECTION_UNIVERSE_DOMAIN = b"insurancekb.runtime.materialized-section-universe.v1\0"
_TEMPLATE_BINDING_DOMAIN = b"insurancekb.runtime.template-binding.v1\0"
_CONTRACT_VALUE_HASH_DOMAIN = b"insurancekb.runtime.contract-value-hash.v1\0"
_VALIDATION_DEPTH: ContextVar[int] = ContextVar("runtime_contract_validation_depth", default=0)
_UNRESOLVED_IDENTITIES = frozenset(
    {"unknown", "unassigned", "unresolved", "pending", "none", "null", "*"}
)

RuntimeContractReason = Literal[
    "child_space_mismatch",
    "template_lock_mismatch",
    "model_plan_mismatch",
    "invalid_job_transition",
    "invalid_stage_transition",
    "invalid_stage_name",
    "duplicate_plugin_name",
    "invalid_stage_sequence",
    "duplicate_product_route",
    "duplicate_unassigned_section",
    "empty_routing_result",
    "product_space_mismatch",
    "section_partition_overlap",
    "incomplete_section_partition",
    "route_template_space_mismatch",
    "resolved_route_space_mismatch",
    "resolved_route_lock_mismatch",
    "resolved_route_plan_mismatch",
    "resolved_route_set_mismatch",
    "consensus_input_mismatch",
    "exhausted_gap_must_block",
    "governance_outcome_mismatch",
    "invalid_contract_dto",
]

JobKind = Literal["intake", "product_compilation"]
JobStatus = Literal["queued", "running", "blocked", "succeeded", "failed"]
StageStatus = Literal["pending", "running", "succeeded", "blocked", "failed"]
StageName = Literal[
    "materialize",
    "classify_route",
    "resolve_template",
    "fan_out",
    "extract",
    "verify",
    "gap",
    "consensus",
    "knowledge_sink",
]

PARENT_STAGE_SEQUENCE: tuple[StageName, ...] = (
    "materialize",
    "classify_route",
    "resolve_template",
    "fan_out",
)
CHILD_STAGE_SEQUENCE: tuple[StageName, ...] = (
    "extract",
    "verify",
    "gap",
    "consensus",
    "knowledge_sink",
)

_JOB_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    "queued": frozenset({"running", "blocked", "failed"}),
    "running": frozenset({"blocked", "succeeded", "failed"}),
    "blocked": frozenset({"running", "failed"}),
    "failed": frozenset({"running"}),
    "succeeded": frozenset(),
}
_STAGE_TRANSITIONS: dict[StageStatus, frozenset[StageStatus]] = {
    "pending": frozenset({"running", "blocked", "failed"}),
    "running": frozenset({"blocked", "succeeded", "failed"}),
    "blocked": frozenset({"running", "failed"}),
    "failed": frozenset({"running"}),
    "succeeded": frozenset(),
}


class RuntimeContractError(Exception):
    """Typed fail-closed rejection for inconsistent pure contract values."""

    def __init__(self, reason_code: RuntimeContractReason):
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class _RegisteredContractSnapshot:
    reference: weakref.ReferenceType[object]
    process_generation: str
    instance_token: str
    snapshot: object


def _make_contract_snapshot_lifecycle() -> tuple[Any, Any, Any, Any]:
    """Create closure-owned construction and exact-instance snapshot lifecycle."""

    lock = RLock()
    entries: dict[int, _RegisteredContractSnapshot] = {}
    process_id = os.getpid()
    process_generation = secrets.token_hex(32)
    sequence = 0
    construction_generation = object()
    construction_marker: ContextVar[object | None] = ContextVar(
        "runtime_contract_construction_marker",
        default=None,
    )

    def reset_for_process() -> None:
        nonlocal lock, entries, process_id, process_generation, sequence
        nonlocal construction_generation
        lock = RLock()
        entries = {}
        process_id = os.getpid()
        process_generation = secrets.token_hex(32)
        sequence = 0
        construction_generation = object()

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=reset_for_process)

    def ensure_current_process() -> None:
        if process_id != os.getpid():
            reset_for_process()

    def issue(value: object) -> None:
        nonlocal sequence
        with lock:
            ensure_current_process()
            if construction_marker.get() is not construction_generation:
                raise TypeError("contract snapshot is outside canonical construction")
            object_id = id(value)
            existing = entries.get(object_id)
            if existing is not None and existing.reference() is value:
                raise TypeError("contract instance is already registered")
            snapshot = _snapshot_model_storage(type(value), value)
            sequence += 1
            instance_token = f"{process_generation}:{sequence}"

            def discard(
                reference: weakref.ReferenceType[object],
                *,
                registered_object_id: int = object_id,
            ) -> None:
                with lock:
                    current = entries.get(registered_object_id)
                    if current is not None and current.reference is reference:
                        entries.pop(registered_object_id, None)

            reference = weakref.ref(value, discard)
            entries[object_id] = _RegisteredContractSnapshot(
                reference=reference,
                process_generation=process_generation,
                instance_token=instance_token,
                snapshot=snapshot,
            )

    def read(value: object) -> _RegisteredContractSnapshot:
        with lock:
            ensure_current_process()
            entry = entries.get(id(value))
            if (
                entry is None
                or entry.reference() is not value
                or entry.process_generation != process_generation
            ):
                raise TypeError("contract instance is not registered in this process")
            current_snapshot = _snapshot_model_storage(type(value), value)
            current = entries.get(id(value))
            if current is not entry or current.reference() is not value:
                raise TypeError("contract instance registration changed during validation")
            if current_snapshot != entry.snapshot:
                raise TypeError("contract instance differs from its canonical snapshot")
            return entry

    def initialize(self: BaseModel, **data: object) -> None:
        ensure_current_process()
        construction_token = construction_marker.set(construction_generation)
        validation_token = _VALIDATION_DEPTH.set(_VALIDATION_DEPTH.get() + 1)
        try:
            BaseModel.__init__(self, **data)
        finally:
            _VALIDATION_DEPTH.reset(validation_token)
            construction_marker.reset(construction_token)

    def validate(
        cls: type[BaseModel],
        obj: object,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        ensure_current_process()
        construction_token = construction_marker.set(construction_generation)
        validation_token = _VALIDATION_DEPTH.set(_VALIDATION_DEPTH.get() + 1)
        try:
            if type(obj) is cls:
                try:
                    obj = _snapshot_runtime_input(obj)
                except MemoryError:
                    raise
                except Exception:
                    raise RuntimeContractError("invalid_contract_dto") from None
            return cast(Any, BaseModel.model_validate).__func__(
                cls,
                obj,
                *args,
                **kwargs,
            )
        finally:
            _VALIDATION_DEPTH.reset(validation_token)
            construction_marker.reset(construction_token)

    def post_init(self: BaseModel, context: Any, /) -> None:
        del context
        if (
            _VALIDATION_DEPTH.get() <= 0
            or construction_marker.get() is not construction_generation
        ):
            raise RuntimeContractError("invalid_contract_dto")
        try:
            issue(self)
        except MemoryError:
            raise
        except Exception:
            raise RuntimeContractError("invalid_contract_dto") from None

    return initialize, classmethod(validate), post_init, read


(
    _contract_model_initialize,
    _contract_model_validate,
    _contract_model_post_init,
    _read_contract_snapshot,
) = _make_contract_snapshot_lifecycle()


def _snapshot_model_storage(model_type: type[object], value: object) -> object:
    """Freeze exact Pydantic storage into caller-independent primitive state."""

    if type(value) is not model_type or not issubclass(model_type, BaseModel):
        raise TypeError("contract DTO must use its exact model type")
    storage = object.__getattribute__(value, "__dict__")
    fields_set = object.__getattribute__(value, "__pydantic_fields_set__")
    extra = object.__getattribute__(value, "__pydantic_extra__")
    private = object.__getattribute__(value, "__pydantic_private__")
    field_names = tuple(model_type.model_fields)
    if (
        type(storage) is not dict
        or type(fields_set) is not set
        or not fields_set.issubset(field_names)
        or extra is not None
        or private is not None
        or set(storage) != set(field_names)
    ):
        raise TypeError("contract DTO storage is not canonical")
    return (
        "model",
        model_type,
        tuple(sorted(fields_set)),
        tuple(
            (field_name, _snapshot_contract_value(storage[field_name]))
            for field_name in field_names
        ),
    )


def _snapshot_contract_value(value: object) -> object:
    value_type = type(value)
    if isinstance(value, _ImmutableModel):
        entry = _read_contract_snapshot(value)
        return (
            "runtime-model",
            value_type,
            entry.instance_token,
            entry.snapshot,
        )
    if isinstance(value, BaseModel):
        return _snapshot_model_storage(value_type, value)
    if value is None:
        return ("none",)
    if value_type is str:
        return ("str", value)
    if value_type is bool:
        return ("bool", value)
    if value_type is int:
        return ("int", value)
    if value_type is tuple:
        tuple_value = cast(tuple[object, ...], value)
        return (
            "tuple",
            tuple(_snapshot_contract_value(item) for item in tuple_value),
        )
    if value_type is list:
        list_value = cast(list[object], value)
        return (
            "list",
            tuple(_snapshot_contract_value(item) for item in list_value),
        )
    if value_type is dict:
        canonical_items: list[tuple[str, object]] = []
        for key, item in cast(dict[object, object], value).items():
            if type(key) is not str:
                raise TypeError("contract mapping keys must be exact strings")
            canonical_items.append((key, item))
        return (
            "dict",
            tuple(
                (key, _snapshot_contract_value(item))
                for key, item in sorted(canonical_items)
            ),
        )
    if (
        isinstance(value, Mapping)
        and isinstance(value, tuple)
        and value_type.__module__ == "insurance_harness.template_packages.models"
        and value_type.__qualname__ == "_FrozenMapping"
    ):
        items = tuple(tuple.__iter__(value))
        if any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            for item in items
        ):
            raise TypeError("contract frozen mapping is not canonical")
        return (
            "frozen-mapping",
            value_type,
            tuple(
                (key, _snapshot_contract_value(item))
                for key, item in sorted(items)
            ),
        )
    raise TypeError("contract value is not canonical")


def _restore_contract_value(snapshot: object) -> object:
    if type(snapshot) is not tuple or not snapshot:
        raise TypeError("canonical snapshot is malformed")
    tag = snapshot[0]
    if tag == "none" and len(snapshot) == 1:
        return None
    if tag in {"str", "bool", "int"} and len(snapshot) == 2:
        expected_type = {"str": str, "bool": bool, "int": int}[tag]
        if type(snapshot[1]) is not expected_type:
            raise TypeError("canonical scalar snapshot is malformed")
        return snapshot[1]
    if tag in {"tuple", "list"} and len(snapshot) == 2:
        items = snapshot[1]
        if type(items) is not tuple:
            raise TypeError("canonical sequence snapshot is malformed")
        restored = tuple(_restore_contract_value(item) for item in items)
        return restored if tag == "tuple" else list(restored)
    if tag in {"dict", "frozen-mapping"}:
        items_index = 1 if tag == "dict" else 2
        expected_length = 2 if tag == "dict" else 3
        if len(snapshot) != expected_length or type(snapshot[items_index]) is not tuple:
            raise TypeError("canonical mapping snapshot is malformed")
        return {
            key: _restore_contract_value(item)
            for key, item in snapshot[items_index]
        }
    if tag == "model" and len(snapshot) == 4:
        model_type = snapshot[1]
        if not isinstance(model_type, type) or not issubclass(model_type, BaseModel):
            raise TypeError("canonical model snapshot is malformed")
        return model_type.model_validate(_restore_model_fields(snapshot))
    if tag == "runtime-model" and len(snapshot) == 4:
        model_type = snapshot[1]
        model_snapshot = snapshot[3]
        if not isinstance(model_type, type) or not issubclass(model_type, _ImmutableModel):
            raise TypeError("canonical runtime snapshot is malformed")
        return cast(Any, model_type).model_validate(
            _restore_model_fields(model_snapshot)
        )
    raise TypeError("canonical snapshot tag is invalid")


def _restore_model_fields(snapshot: object) -> dict[str, object]:
    if (
        type(snapshot) is not tuple
        or len(snapshot) != 4
        or snapshot[0] != "model"
        or type(snapshot[3]) is not tuple
    ):
        raise TypeError("canonical model snapshot is malformed")
    return {
        field_name: _restore_contract_value(value_snapshot)
        for field_name, value_snapshot in snapshot[3]
    }


def _snapshot_exact_model(model_type: type[BaseModel], value: object) -> dict[str, object]:
    """Return a detached reconstruction from the issuer-owned canonical snapshot."""

    try:
        if type(value) is not model_type:
            raise TypeError("contract DTO must use its exact model type")
        entry = _read_contract_snapshot(value)
        return _restore_model_fields(entry.snapshot)
    except RuntimeContractError:
        raise
    except MemoryError:
        raise
    except Exception:
        raise RuntimeContractError("invalid_contract_dto") from None


def _contract_value_semantics(snapshot: object) -> object:
    """Remove instance seals while preserving canonical contract value semantics."""

    if type(snapshot) is not tuple or not snapshot:
        raise TypeError("canonical snapshot is malformed")
    tag = snapshot[0]
    if tag == "none" and len(snapshot) == 1:
        return ("none",)
    if tag in {"str", "bool", "int"} and len(snapshot) == 2:
        return snapshot
    if tag in {"tuple", "list"} and len(snapshot) == 2:
        items = snapshot[1]
        if type(items) is not tuple:
            raise TypeError("canonical sequence snapshot is malformed")
        return (tag, tuple(_contract_value_semantics(item) for item in items))
    if tag in {"dict", "frozen-mapping"}:
        items_index = 1 if tag == "dict" else 2
        expected_length = 2 if tag == "dict" else 3
        if len(snapshot) != expected_length or type(snapshot[items_index]) is not tuple:
            raise TypeError("canonical mapping snapshot is malformed")
        return (
            tag,
            tuple(
                (key, _contract_value_semantics(item))
                for key, item in snapshot[items_index]
            ),
        )
    if tag == "runtime-model" and len(snapshot) == 4:
        return _contract_value_semantics(snapshot[3])
    if tag == "model" and len(snapshot) == 4:
        model_type = snapshot[1]
        fields = snapshot[3]
        if (
            not isinstance(model_type, type)
            or not issubclass(model_type, BaseModel)
            or type(fields) is not tuple
        ):
            raise TypeError("canonical model snapshot is malformed")
        return (
            "model",
            f"{model_type.__module__}.{model_type.__qualname__}",
            tuple(
                (field_name, _contract_value_semantics(field_snapshot))
                for field_name, field_snapshot in fields
            ),
        )
    raise TypeError("canonical snapshot tag is invalid")


def _canonical_contract_value(value: object) -> object:
    try:
        if not isinstance(value, _ImmutableModel):
            raise TypeError("value is not a runtime contract")
        entry = _read_contract_snapshot(value)
        return _contract_value_semantics(entry.snapshot)
    except RuntimeContractError:
        raise
    except MemoryError:
        raise
    except Exception:
        raise RuntimeContractError("invalid_contract_dto") from None


def _snapshot_runtime_input(value: object) -> object:
    """Reject stale sealed runtime instances before Pydantic can launder them."""

    if isinstance(value, _ImmutableModel):
        try:
            return {
                key: _snapshot_runtime_input(item)
                for key, item in _snapshot_exact_model(type(value), value).items()
            }
        except MemoryError:
            raise
        except Exception:
            raise RuntimeContractError("invalid_contract_dto") from None
    if isinstance(value, Mapping):
        return {key: _snapshot_runtime_input(item) for key, item in value.items()}
    if type(value) is tuple:
        return tuple(_snapshot_runtime_input(item) for item in value)
    if type(value) is list:
        return [_snapshot_runtime_input(item) for item in value]
    return value


class _ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    __init__ = _contract_model_initialize
    model_validate = _contract_model_validate
    model_post_init = _contract_model_post_init

    def __init_subclass__(cls) -> None:
        if cls.__base__ is not _ImmutableModel:
            raise TypeError("runtime DTO is a final contract type")
        super().__init_subclass__()

    @model_validator(mode="before")
    @classmethod
    def reject_stale_nested_runtime_instances(cls, value: object) -> object:
        return _snapshot_runtime_input(value)

    @classmethod
    def model_construct(cls, *args: Any, **kwargs: Any) -> Self:
        del args, kwargs
        raise TypeError("model_construct() is disabled for runtime contracts")

    def __getattribute__(self, name: str) -> Any:
        model_type = type(self)
        if (
            _VALIDATION_DEPTH.get() == 0
            and name in model_type.model_fields
        ):
            validated = _revalidate_exact(model_type, self)
            return object.__getattribute__(validated, name)
        return object.__getattribute__(self, name)

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
        del deep
        values = _snapshot_exact_model(type(self), self)
        if update is not None:
            values.update(update)
        return cast(Self, type(self).model_validate(values))

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        validated = _revalidate_exact(type(self), self)
        return BaseModel.model_dump(validated, *args, **kwargs)

    def model_dump_json(self, *args: Any, **kwargs: Any) -> str:
        validated = _revalidate_exact(type(self), self)
        return BaseModel.model_dump_json(validated, *args, **kwargs)

    def __iter__(self) -> Generator[tuple[str, Any], None, None]:
        validated = _revalidate_exact(type(self), self)
        yield from BaseModel.__iter__(validated)

    def __eq__(self, other: object) -> bool:
        left = _canonical_contract_value(self)
        if not isinstance(other, _ImmutableModel):
            return NotImplemented
        right = _canonical_contract_value(other)
        return type(self) is type(other) and left == right

    def __hash__(self) -> int:
        digest = _canonical_digest(
            _CONTRACT_VALUE_HASH_DOMAIN,
            _canonical_contract_value(self),
        )
        return int(digest[:15], 16)

    def __repr_args__(self) -> Generator[tuple[str | None, Any], None, None]:
        values = _snapshot_exact_model(type(self), self)
        for field_name in type(self).model_fields:
            yield field_name, values[field_name]

    def __repr__(self) -> str:
        arguments = ", ".join(
            f"{field_name}={value!r}"
            for field_name, value in self.__repr_args__()
        )
        return f"{type(self).__name__}({arguments})"

    def __str__(self) -> str:
        return " ".join(
            f"{field_name}={value!r}"
            for field_name, value in self.__repr_args__()
        )

    def __getstate__(self) -> dict[str, Any]:
        validated = _revalidate_exact(type(self), self)
        return BaseModel.__getstate__(validated)

    @model_serializer(mode="wrap")
    def serialize_exact(self, handler: Any, info: Any) -> Any:
        del info
        if _VALIDATION_DEPTH.get() > 0:
            return handler(self)
        validated = _revalidate_exact(type(self), self)
        token = _VALIDATION_DEPTH.set(_VALIDATION_DEPTH.get() + 1)
        try:
            return handler(validated)
        finally:
            _VALIDATION_DEPTH.reset(token)

    def __copy__(self) -> Self:
        return cast(
            Self,
            type(self).model_validate(_snapshot_exact_model(type(self), self)),
        )

    def __deepcopy__(self, memo: dict[int, Any] | None = None) -> Self:
        del memo
        return cast(
            Self,
            type(self).model_validate(_snapshot_exact_model(type(self), self)),
        )


del _contract_model_initialize
del _contract_model_validate
del _contract_model_post_init


def _canonical_digest(domain: bytes, value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(domain + payload).hexdigest()


def _revalidate_exact[ModelT: _ImmutableModel](
    model_type: type[ModelT],
    value: object,
) -> ModelT:
    token = _VALIDATION_DEPTH.set(_VALIDATION_DEPTH.get() + 1)
    try:
        return cast(
            ModelT,
            model_type.model_validate(_snapshot_exact_model(model_type, value)),
        )
    except MemoryError:
        raise
    except Exception:
        raise RuntimeContractError("invalid_contract_dto") from None
    finally:
        _VALIDATION_DEPTH.reset(token)


def _identity_key(value: str) -> str:
    if any(unicodedata.category(char) in {"Cc", "Cf"} for char in value):
        raise ValueError("resolved identity must not be a fallback")
    return unicodedata.normalize("NFKC", value).casefold()


def _require_resolved_identity(value: str) -> str:
    if _identity_key(value) in _UNRESOLVED_IDENTITIES:
        raise ValueError("resolved identity must not be a fallback")
    return value


class ParentIntakeIdentity(_ImmutableModel):
    """Pre-routing identity; product and template identities are intentionally absent."""

    space_id: NonBlankStr
    source_revision: NonBlankStr
    run_revision: NonBlankStr
    admission_artifact_hash: Sha256Hex
    strict_request_digest: Sha256Hex
    verified_binding_digest: Sha256Hex
    routing_policy_hash: Sha256Hex
    template_lock_hash: Sha256Hex
    structured_dispatch_lock_hash: Sha256Hex
    model_plan_hash: Sha256Hex

    @field_validator("space_id", "source_revision", "run_revision", mode="after")
    @classmethod
    def reject_control_identity(cls, value: str) -> str:
        return _require_resolved_identity(value)

    @property
    def job_id(self) -> str:
        validated = _revalidate_exact(ParentIntakeIdentity, self)
        return _canonical_digest(
            _PARENT_IDENTITY_DOMAIN,
            BaseModel.model_dump(validated, mode="json"),
        )


class ProductVersionBinding(_ImmutableModel):
    """Exact routed product identity in one Space; it conveys no product authority."""

    space_id: NonBlankStr
    product_version_id: NonBlankStr

    @field_validator("space_id", "product_version_id", mode="after")
    @classmethod
    def reject_fallback_identity(cls, value: str) -> str:
        return _require_resolved_identity(value)


class ProductSectionRoute(_ImmutableModel):
    """One deterministic product partition with its raw content addresses."""

    product: ProductVersionBinding
    section_hashes: tuple[Sha256Hex, ...]

    @field_validator("section_hashes", mode="after")
    @classmethod
    def canonicalize_section_hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("product route must contain at least one section")
        if len(set(value)) != len(value):
            raise RuntimeContractError("section_partition_overlap")
        return tuple(sorted(set(value)))

    @property
    def product_version_id(self) -> str:
        return _revalidate_exact(ProductSectionRoute, self).product.product_version_id

    @property
    def space_id(self) -> str:
        return _revalidate_exact(ProductSectionRoute, self).product.space_id

    @property
    def routed_section_set_hash(self) -> str:
        validated = _revalidate_exact(ProductSectionRoute, self)
        return _canonical_digest(_SECTION_SET_DOMAIN, validated.section_hashes)


class ResolvedRouteBinding(_ImmutableModel):
    """Content binding only; catalog membership remains a later composition concern."""

    product_route: ProductSectionRoute
    resolved_template: ResolvedTemplate
    template_lock_hash: Sha256Hex
    model_plan_hash: Sha256Hex

    @model_validator(mode="after")
    def require_resolved_template_identity(self) -> ResolvedRouteBinding:
        request = self.resolved_template.request
        source_chain = self.resolved_template.source_chain
        for value in (
            request.space_id,
            request.product_line_id,
            request.document_type_id,
            request.product_family_id,
            self.resolved_template.content.schema_version,
            *(source.package_id for source in source_chain),
            *(source.version_id for source in source_chain),
        ):
            _require_resolved_identity(value)
        if request.space_id != self.product_route.space_id:
            raise RuntimeContractError("route_template_space_mismatch")
        canonical_content_hash(self.resolved_template.content)
        return self

    @property
    def product_version_id(self) -> str:
        return _revalidate_exact(ResolvedRouteBinding, self).product_route.product_version_id

    @property
    def routed_section_set_hash(self) -> str:
        return _revalidate_exact(
            ResolvedRouteBinding, self
        ).product_route.routed_section_set_hash

    @property
    def space_id(self) -> str:
        return _revalidate_exact(ResolvedRouteBinding, self).product_route.space_id

    @property
    def schema_version(self) -> str:
        return _revalidate_exact(
            ResolvedRouteBinding, self
        ).resolved_template.content.schema_version

    @property
    def resolved_template_hash(self) -> str:
        return _revalidate_exact(
            ResolvedRouteBinding, self
        ).resolved_template.content_hash

    @property
    def template_binding_digest(self) -> str:
        validated = _revalidate_exact(ResolvedRouteBinding, self)
        return _canonical_digest(
            _TEMPLATE_BINDING_DOMAIN,
            {
                "product": BaseModel.model_dump(validated.product_route.product, mode="json"),
                "routed_section_set_hash": validated.routed_section_set_hash,
                "resolved_template": BaseModel.model_dump(
                    validated.resolved_template, mode="json", round_trip=True
                ),
                "template_lock_hash": validated.template_lock_hash,
                "model_plan_hash": validated.model_plan_hash,
            },
        )


class ChildCompilationIdentity(_ImmutableModel):
    """Post-routing child identity with exact inherited parent and route values."""

    parent: ParentIntakeIdentity
    route: ResolvedRouteBinding

    @model_validator(mode="after")
    def require_exact_parent_route_binding(self) -> ChildCompilationIdentity:
        if self.route.space_id != self.parent.space_id:
            raise RuntimeContractError("child_space_mismatch")
        if self.route.template_lock_hash != self.parent.template_lock_hash:
            raise RuntimeContractError("template_lock_mismatch")
        if self.route.model_plan_hash != self.parent.model_plan_hash:
            raise RuntimeContractError("model_plan_mismatch")
        return self

    @property
    def parent_intake_job_id(self) -> str:
        return self.parent.job_id

    @property
    def space_id(self) -> str:
        return self.parent.space_id

    @property
    def run_revision(self) -> str:
        return self.parent.run_revision

    @property
    def verified_binding_digest(self) -> str:
        return self.parent.verified_binding_digest

    @property
    def template_lock_hash(self) -> str:
        return self.parent.template_lock_hash

    @property
    def model_plan_hash(self) -> str:
        return self.parent.model_plan_hash

    @property
    def product_version_id(self) -> str:
        return self.route.product_version_id

    @property
    def resolved_template_hash(self) -> str:
        return self.route.resolved_template_hash

    @property
    def job_id(self) -> str:
        validated = _revalidate_exact(ChildCompilationIdentity, self)
        return _canonical_digest(
            _CHILD_IDENTITY_DOMAIN,
            {
                "parent_intake_job_id": validated.parent.job_id,
                "verified_binding_digest": validated.parent.verified_binding_digest,
                "template_binding_digest": validated.route.template_binding_digest,
            },
        )


type Identity = ParentIntakeIdentity | ChildCompilationIdentity


def _validated_identity(value: object) -> Identity:
    if type(value) is ParentIntakeIdentity:
        return _revalidate_exact(ParentIntakeIdentity, value)
    if type(value) is ChildCompilationIdentity:
        return _revalidate_exact(ChildCompilationIdentity, value)
    raise RuntimeContractError("invalid_contract_dto")


class JobState(_ImmutableModel):
    """Immutable state snapshot whose job id and kind are derived from identity."""

    identity: Identity
    status: JobStatus

    @field_validator("status", mode="before")
    @classmethod
    def require_exact_status_string(cls, value: object) -> object:
        if type(value) is not str:
            raise RuntimeContractError("invalid_contract_dto")
        return value

    @property
    def job_id(self) -> str:
        return _revalidate_exact(JobState, self).identity.job_id

    @property
    def job_kind(self) -> JobKind:
        identity = _revalidate_exact(JobState, self).identity
        return "intake" if type(identity) is ParentIntakeIdentity else "product_compilation"

    def transition(self, target: JobStatus) -> JobState:
        if type(target) is not str:
            raise RuntimeContractError("invalid_contract_dto")
        validated = _revalidate_exact(JobState, self)
        identity = validated.identity
        status = validated.status
        if target not in _JOB_TRANSITIONS[status]:
            raise RuntimeContractError("invalid_job_transition")
        return JobState(identity=identity, status=target)


class StageState(_ImmutableModel):
    """Immutable separately checkpointed stage state bound to one identity."""

    identity: Identity
    stage_name: StageName
    status: StageStatus

    @field_validator("stage_name", "status", mode="before")
    @classmethod
    def require_exact_state_string(cls, value: object) -> object:
        if type(value) is not str:
            raise RuntimeContractError("invalid_contract_dto")
        return value

    @model_validator(mode="after")
    def require_stage_for_job_kind(self) -> StageState:
        validated = _validated_identity(self.identity)
        job_kind: JobKind = (
            "intake" if type(validated) is ParentIntakeIdentity else "product_compilation"
        )
        expected = PARENT_STAGE_SEQUENCE if job_kind == "intake" else CHILD_STAGE_SEQUENCE
        if self.stage_name not in expected:
            raise RuntimeContractError("invalid_stage_name")
        return self

    @property
    def job_id(self) -> str:
        return _revalidate_exact(StageState, self).identity.job_id

    @property
    def job_kind(self) -> JobKind:
        identity = _revalidate_exact(StageState, self).identity
        return "intake" if type(identity) is ParentIntakeIdentity else "product_compilation"

    def transition(self, target: StageStatus) -> StageState:
        if type(target) is not str:
            raise RuntimeContractError("invalid_contract_dto")
        validated = _revalidate_exact(StageState, self)
        identity = validated.identity
        stage_name = validated.stage_name
        status = validated.status
        if target not in _STAGE_TRANSITIONS[status]:
            raise RuntimeContractError("invalid_stage_transition")
        return StageState(identity=identity, stage_name=stage_name, status=target)


class StageBinding(_ImmutableModel):
    stage_name: StageName
    plugin_name: NonBlankStr


class StagePlan(_ImmutableModel):
    """Exact ordered stage labels; this value neither registers nor authorizes plugins."""

    job_kind: JobKind
    bindings: tuple[StageBinding, ...]

    @model_validator(mode="after")
    def require_exact_unique_plan(self) -> StagePlan:
        expected = PARENT_STAGE_SEQUENCE if self.job_kind == "intake" else CHILD_STAGE_SEQUENCE
        names = tuple(binding.stage_name for binding in self.bindings)
        if names != expected:
            raise RuntimeContractError("invalid_stage_sequence")
        plugin_names = tuple(binding.plugin_name for binding in self.bindings)
        if len(set(plugin_names)) != len(plugin_names):
            raise RuntimeContractError("duplicate_plugin_name")
        return self

    @property
    def stage_names(self) -> tuple[StageName, ...]:
        return tuple(binding.stage_name for binding in self.bindings)


class IntakeContext(_ImmutableModel):
    identity: ParentIntakeIdentity
    source_ref: NonBlankStr


class MaterializedBatch(_ImmutableModel):
    context: IntakeContext
    materialized_batch_hash: Sha256Hex
    lineage_hash: Sha256Hex
    section_hashes: tuple[Sha256Hex, ...]

    @field_validator("section_hashes", mode="after")
    @classmethod
    def canonicalize_section_universe(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(set(value)) != len(value):
            raise ValueError("section universe must be non-empty and unique")
        return tuple(sorted(value))

    @property
    def section_universe_hash(self) -> str:
        validated = _revalidate_exact(MaterializedBatch, self)
        return _canonical_digest(_SECTION_UNIVERSE_DOMAIN, validated.section_hashes)


class RoutedSections(_ImmutableModel):
    """One complete, deterministic partition of materialized sections."""

    materialized: MaterializedBatch
    product_routes: tuple[ProductSectionRoute, ...]
    unassigned_section_hashes: tuple[Sha256Hex, ...]

    @field_validator("product_routes", mode="after")
    @classmethod
    def sort_product_routes(
        cls, value: tuple[ProductSectionRoute, ...]
    ) -> tuple[ProductSectionRoute, ...]:
        return tuple(sorted(value, key=lambda route: (route.space_id, route.product_version_id)))

    @field_validator("unassigned_section_hashes", mode="after")
    @classmethod
    def sort_unassigned(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(value))

    @model_validator(mode="after")
    def require_canonical_partition(self) -> RoutedSections:
        parent_space = self.materialized.context.identity.space_id
        product_ids = tuple(
            (route.space_id, route.product_version_id) for route in self.product_routes
        )
        if len(set(product_ids)) != len(product_ids):
            raise RuntimeContractError("duplicate_product_route")
        if any(route.space_id != parent_space for route in self.product_routes):
            raise RuntimeContractError("product_space_mismatch")
        if len(set(self.unassigned_section_hashes)) != len(self.unassigned_section_hashes):
            raise RuntimeContractError("duplicate_unassigned_section")
        routed_hashes = tuple(
            section_hash
            for route in self.product_routes
            for section_hash in route.section_hashes
        )
        if len(set(routed_hashes)) != len(routed_hashes) or set(routed_hashes) & set(
            self.unassigned_section_hashes
        ):
            raise RuntimeContractError("section_partition_overlap")
        if set(routed_hashes) | set(self.unassigned_section_hashes) != set(
            self.materialized.section_hashes
        ):
            raise RuntimeContractError("incomplete_section_partition")
        if not product_ids and not self.unassigned_section_hashes:
            raise RuntimeContractError("empty_routing_result")
        return self


class ResolvedRouteSet(_ImmutableModel):
    routed_sections: RoutedSections
    routes: tuple[ResolvedRouteBinding, ...]

    @model_validator(mode="after")
    def require_exact_parent_and_route_closure(self) -> ResolvedRouteSet:
        parent = self.routed_sections.materialized.context.identity
        for route in self.routes:
            if route.space_id != parent.space_id:
                raise RuntimeContractError("resolved_route_space_mismatch")
            if route.template_lock_hash != parent.template_lock_hash:
                raise RuntimeContractError("resolved_route_lock_mismatch")
            if route.model_plan_hash != parent.model_plan_hash:
                raise RuntimeContractError("resolved_route_plan_mismatch")
        expected = self.routed_sections.product_routes
        actual = tuple(route.product_route for route in self.routes)
        if len(set(route.template_binding_digest for route in self.routes)) != len(actual):
            raise RuntimeContractError("resolved_route_set_mismatch")
        if actual != expected:
            raise RuntimeContractError("resolved_route_set_mismatch")
        return self


class ProductCompilationInput(_ImmutableModel):
    child_identity: ChildCompilationIdentity

    @property
    def routed_input_hash(self) -> str:
        validated = _revalidate_exact(ProductCompilationInput, self)
        return validated.child_identity.route.routed_section_set_hash


class CandidateFactBatch(_ImmutableModel):
    compilation: ProductCompilationInput
    candidate_batch_hash: Sha256Hex


class VerifiedFactBatch(_ImmutableModel):
    candidates: CandidateFactBatch
    verified_batch_hash: Sha256Hex


class GapResult(_ImmutableModel):
    verified: VerifiedFactBatch
    gap_result_hash: Sha256Hex
    exhausted: StrictBool


class ConsensusResult(_ImmutableModel):
    verified: VerifiedFactBatch
    gap: GapResult
    consensus_hash: Sha256Hex
    outcome: Literal["agreed", "conflict", "blocked"]

    @model_validator(mode="after")
    def require_consistent_input_and_outcome(self) -> ConsensusResult:
        if self.gap.verified != self.verified:
            raise RuntimeContractError("consensus_input_mismatch")
        if self.gap.exhausted and self.outcome != "blocked":
            raise RuntimeContractError("exhausted_gap_must_block")
        return self


class GovernanceResult(_ImmutableModel):
    """Governance proposal receipt; it cannot move CurrentRelease."""

    consensus: ConsensusResult
    governance_hash: Sha256Hex
    outcome: Literal["proposed", "review", "blocked"]
    current_release_changed: Literal[False] = False

    @model_validator(mode="after")
    def require_consensus_outcome(self) -> GovernanceResult:
        expected = {"agreed": "proposed", "conflict": "review", "blocked": "blocked"}
        if self.outcome != expected[self.consensus.outcome]:
            raise RuntimeContractError("governance_outcome_mismatch")
        return self
