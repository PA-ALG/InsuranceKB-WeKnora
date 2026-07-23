"""Pure, non-authority audit contracts for one OpenSpec 028 compilation."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal, Self, cast

from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from insurance_harness.runtime.models import (
    NonBlankStr,
    RuntimeContractError,
    Sha256Hex,
    _canonical_digest,
    _ImmutableModel,
    _require_resolved_identity,
    _revalidate_exact,
)

_COMPILATION_MANIFEST_DOMAIN = b"insurancekb.runtime.compilation-manifest.v1\0"

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
ChangeAction = Literal["add", "enrich", "supersede", "conflict", "retract"]
ObservedChangeSetStatus = Literal["pending", "partially_applied", "applied"]
ObservedPreReviewDecision = Literal["auto_applied", "needs_review"]
ArtifactOwnerKind = Literal["run", "product"]
ArtifactPhase = Literal["compilation"]
GovernanceOwnerKind = Literal["product"]

_CANONICAL_UTC_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"
)
_WINDOWS_RESERVED_BASENAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)
_RELEASE_ONLY_FILENAMES = frozenset(
    {"release-proof.json", "artifact-manifest.json", "compilation-manifest.json"}
)
_PORTABLE_ARTIFACT_SEGMENT = re.compile(r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$")

# S1 manifests have a fixed, shallow schema. These limits leave ample room for
# legitimate inventories while bounding adversarial Python object graphs before
# Pydantic or canonicalization sees them.
_MAX_EXACT_GRAPH_DEPTH = 64
_MAX_EXACT_CONTAINER_WIDTH = 8_192
_MAX_EXACT_GRAPH_NODES = 262_144
_MAX_EXACT_GRAPH_EDGES = 524_288
_MAX_MANIFEST_INVENTORY_FACTS = 8_192


def _require_exact_unicode_string(value: object) -> object:
    if type(value) is not str:
        raise ValueError("manifest strings must use the exact built-in str type")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("manifest strings must contain Unicode scalar values") from None
    if any(unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"} for character in value):
        raise ValueError("manifest strings must not contain control or format separators")
    return value


def _require_exact_sequence(value: object) -> object:
    if type(value) not in {tuple, list}:
        raise ValueError("manifest sequences must use exact built-in containers")
    return value


def _assign_detached_graph_value(
    parent: list[object] | dict[str, object],
    slot: int | str,
    value: object,
) -> None:
    if type(parent) is list and type(slot) is int:
        parent[slot] = value
        return
    if type(parent) is dict and type(slot) is str:
        parent[slot] = value
        return
    raise AssertionError("invalid detached graph target")


def _require_exact_python_graph(value: object) -> object:
    root: list[object] = [None]
    work: list[
        tuple[
            bool,
            object,
            int,
            list[object] | dict[str, object],
            int | str,
        ]
    ] = [(False, value, 0, root, 0)]
    active_containers: set[int] = set()
    detached_containers: dict[int, list[object] | dict[str, object]] = {}
    seen_node_identities: set[int] = set()
    node_count = 0
    edge_count = 0

    while work:
        exiting, current, depth, parent, slot = work.pop()
        current_identity = id(current)
        if exiting:
            active_containers.remove(current_identity)
            continue

        if current_identity not in seen_node_identities:
            seen_node_identities.add(current_identity)
            node_count += 1
            if node_count > _MAX_EXACT_GRAPH_NODES:
                raise ValueError("manifest input graph exceeds the node budget")

        current_type = type(current)
        if current is None or current_type in {bool, int}:
            _assign_detached_graph_value(parent, slot, current)
            continue
        if current_type is str:
            _require_exact_unicode_string(current)
            _assign_detached_graph_value(parent, slot, current)
            continue
        if isinstance(current, _ImmutableModel):
            _assign_detached_graph_value(parent, slot, current)
            continue
        if current_type not in {dict, list, tuple}:
            raise ValueError("manifest inputs require exact built-in value types")
        if depth > _MAX_EXACT_GRAPH_DEPTH:
            raise ValueError("manifest input graph exceeds the depth budget")
        if current_identity in active_containers:
            raise ValueError("manifest inputs cannot contain container cycles")
        if current_identity in detached_containers:
            _assign_detached_graph_value(
                parent,
                slot,
                detached_containers[current_identity],
            )
            continue

        container = cast(
            dict[object, object] | list[object] | tuple[object, ...],
            current,
        )
        original_length = len(container)
        if original_length > _MAX_EXACT_CONTAINER_WIDTH:
            raise ValueError("manifest input container exceeds the width budget")

        if current_type is dict:
            try:
                dict_snapshot = tuple(cast(dict[object, object], current).items())
            except RuntimeError:
                raise ValueError("manifest input changed during validation") from None
            if (
                len(cast(dict[object, object], current)) != original_length
                or len(dict_snapshot) != original_length
            ):
                raise ValueError("manifest input changed during validation")
            edge_count += len(dict_snapshot) * 2
            detached: list[object] | dict[str, object] = {}
            for key, _ in dict_snapshot:
                if type(key) is not str:
                    raise ValueError("manifest dictionary keys must be exact strings")
                _require_exact_unicode_string(key)
                key_identity = id(key)
                if key_identity not in seen_node_identities:
                    seen_node_identities.add(key_identity)
                    node_count += 1
                    if node_count > _MAX_EXACT_GRAPH_NODES:
                        raise ValueError("manifest input graph exceeds the node budget")
            child_slots: tuple[int | str, ...] = tuple(
                cast(str, key) for key, _ in dict_snapshot
            )
            children: tuple[object, ...] = tuple(item for _, item in dict_snapshot)
        else:
            sequence_snapshot = tuple(
                cast(list[object] | tuple[object, ...], current)
            )
            if (
                len(cast(list[object] | tuple[object, ...], current))
                != original_length
                or len(sequence_snapshot) != original_length
            ):
                raise ValueError("manifest input changed during validation")
            edge_count += len(sequence_snapshot)
            detached = [None] * len(sequence_snapshot)
            children = sequence_snapshot
            child_slots = tuple(range(len(sequence_snapshot)))

        if edge_count > _MAX_EXACT_GRAPH_EDGES:
            raise ValueError("manifest input graph exceeds the edge budget")

        active_containers.add(current_identity)
        detached_containers[current_identity] = detached
        _assign_detached_graph_value(parent, slot, detached)
        work.append((True, current, depth, detached, 0))
        work.extend(
            (False, child, depth + 1, detached, child_slot)
            for child, child_slot in reversed(tuple(zip(children, child_slots, strict=True)))
        )

    return root[0]


def _require_exact_model_mapping(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError("manifest DTO input must use an exact built-in dictionary")
    return cast(dict[str, object], _require_exact_python_graph(value))


def _model_validate_exact_root[ModelT: _ImmutableModel](
    model_type: type[ModelT],
    obj: Any,
    **kwargs: Any,
) -> ModelT:
    if type(obj) not in {dict, model_type}:
        raise RuntimeContractError("invalid_contract_dto")
    return cast(
        ModelT,
        _ImmutableModel.model_validate.__func__(model_type, obj, **kwargs),
    )


def _canonical_python_ingress[ModelT: _ImmutableModel](
    model_type: type[ModelT],
    value: object,
    handler: Any,
    info: ValidationInfo,
) -> ModelT:
    if info.mode != "python" or type(value) not in {dict, model_type}:
        raise ValueError("manifest DTOs require exact Python-mode input")
    checked_value = _require_exact_python_graph(value)
    return cast(ModelT, handler(checked_value))


def _model_copy_exact_update[ModelT: _ImmutableModel](
    value: ModelT,
    *,
    update: Mapping[str, Any] | None,
    deep: bool,
) -> ModelT:
    if update is not None and type(update) is not dict:
        raise RuntimeContractError("invalid_contract_dto")
    if type(deep) is not bool:
        raise RuntimeContractError("invalid_contract_dto")
    checked_update: dict[str, Any] | None = None
    if update is not None:
        try:
            checked_update = cast(dict[str, Any], _require_exact_python_graph(update))
        except ValueError:
            raise RuntimeContractError("invalid_contract_dto") from None
    try:
        return cast(
            ModelT,
            _ImmutableModel.model_copy(value, update=checked_update, deep=deep),
        )
    except ValidationError:
        raise RuntimeContractError("invalid_contract_dto") from None


def _is_safe_artifact_path(value: str) -> bool:
    if (
        "\\" in value
        or ":" in value
        or any(character in '<>"|?*' for character in value)
        or value.startswith("/")
        or "//" in value
        or any(unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"} for character in value)
    ):
        return False
    parts = value.split("/")
    if any(
        part in {"", ".", ".."}
        or _PORTABLE_ARTIFACT_SEGMENT.fullmatch(part) is None
        or len(part.encode("ascii")) > 255
        or part.endswith((".", " "))
        or unicodedata.normalize("NFKC", part).casefold().split(".", 1)[0]
        in _WINDOWS_RESERVED_BASENAMES
        for part in parts
    ):
        return False
    return parts[-1].casefold() not in _RELEASE_ONLY_FILENAMES


class CompilationRunBinding(_ImmutableModel):
    """Serializable run identity; it is evidence, never admission authority."""

    space_id: NonBlankStr
    run_id: NonBlankStr
    run_revision: NonBlankStr
    strict_request_digest: Sha256Hex
    admission_artifact_digest: Sha256Hex
    verified_binding_digest: Sha256Hex
    template_lock_hash: Sha256Hex
    model_plan_hash: Sha256Hex

    @model_validator(mode="wrap")
    @classmethod
    def require_canonical_ingress(cls, value: object, handler: Any, info: ValidationInfo) -> Self:
        return _canonical_python_ingress(cls, value, handler, info)

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> Self:
        return _model_validate_exact_root(cls, obj, **kwargs)

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        return _model_copy_exact_update(self, update=update, deep=deep)

    @model_validator(mode="before")
    @classmethod
    def require_exact_mapping(cls, value: object) -> object:
        return _require_exact_model_mapping(value)

    @field_validator(
        "space_id",
        "run_id",
        "run_revision",
        "strict_request_digest",
        "admission_artifact_digest",
        "verified_binding_digest",
        "template_lock_hash",
        "model_plan_hash",
        mode="before",
    )
    @classmethod
    def require_exact_strings(cls, value: object) -> object:
        return _require_exact_unicode_string(value)

    @field_validator("space_id", "run_id", "run_revision", mode="after")
    @classmethod
    def reject_unresolved_identity(cls, value: str) -> str:
        return _require_resolved_identity(value)


class ReleaseBaseBinding(_ImmutableModel):
    """The paired approved-release identity observed before compilation."""

    space_id: NonBlankStr
    snapshot_id: NonBlankStr
    manifest_hash: Sha256Hex

    @model_validator(mode="wrap")
    @classmethod
    def require_canonical_ingress(cls, value: object, handler: Any, info: ValidationInfo) -> Self:
        return _canonical_python_ingress(cls, value, handler, info)

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> Self:
        return _model_validate_exact_root(cls, obj, **kwargs)

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        return _model_copy_exact_update(self, update=update, deep=deep)

    @model_validator(mode="before")
    @classmethod
    def require_exact_mapping(cls, value: object) -> object:
        return _require_exact_model_mapping(value)

    @field_validator("space_id", "snapshot_id", "manifest_hash", mode="before")
    @classmethod
    def require_exact_strings(cls, value: object) -> object:
        return _require_exact_unicode_string(value)

    @field_validator("space_id", "snapshot_id", mode="after")
    @classmethod
    def reject_unresolved_identity(cls, value: str) -> str:
        return _require_resolved_identity(value)


class CompilationArtifact(_ImmutableModel):
    """Content-addressed compiler output metadata, without artifact bytes."""

    owner_kind: ArtifactOwnerKind
    artifact_phase: ArtifactPhase = "compilation"
    space_id: NonBlankStr
    product_version_id: NonBlankStr | None
    path: NonBlankStr
    sha256: Sha256Hex
    size_bytes: NonNegativeInt
    item_count: NonNegativeInt

    @model_validator(mode="wrap")
    @classmethod
    def require_canonical_ingress(cls, value: object, handler: Any, info: ValidationInfo) -> Self:
        return _canonical_python_ingress(cls, value, handler, info)

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> Self:
        return _model_validate_exact_root(cls, obj, **kwargs)

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        return _model_copy_exact_update(self, update=update, deep=deep)

    @model_validator(mode="before")
    @classmethod
    def require_exact_mapping(cls, value: object) -> object:
        return _require_exact_model_mapping(value)

    @field_validator(
        "owner_kind",
        "artifact_phase",
        "space_id",
        "product_version_id",
        "path",
        "sha256",
        mode="before",
    )
    @classmethod
    def require_exact_strings(cls, value: object) -> object:
        if value is None:
            return value
        return _require_exact_unicode_string(value)

    @field_validator("size_bytes", "item_count", mode="before")
    @classmethod
    def require_exact_ints(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("artifact counts must use exact built-in integers")
        return value

    @field_validator("path", mode="after")
    @classmethod
    def require_safe_relative_path(cls, value: str) -> str:
        if not _is_safe_artifact_path(value):
            raise ValueError("artifact path must be safe and relative")
        return value

    @field_validator("space_id", "product_version_id", mode="after")
    @classmethod
    def reject_unresolved_identity(cls, value: str | None) -> str | None:
        return None if value is None else _require_resolved_identity(value)

    @model_validator(mode="after")
    def require_explicit_owner_binding(self) -> CompilationArtifact:
        if self.owner_kind == "run" and self.product_version_id is not None:
            raise ValueError("run-owned artifacts cannot claim a product identity")
        if self.owner_kind == "product" and self.product_version_id is None:
            raise ValueError("product-owned artifacts require a product identity")
        return self


class CompilationChangeSet(_ImmutableModel):
    """One product-scoped ChangeSet fact; it grants no governance authority."""

    owner_kind: GovernanceOwnerKind
    space_id: NonBlankStr
    product_version_id: NonBlankStr
    change_set_id: NonBlankStr
    observed_status: ObservedChangeSetStatus

    @model_validator(mode="wrap")
    @classmethod
    def require_canonical_ingress(cls, value: object, handler: Any, info: ValidationInfo) -> Self:
        return _canonical_python_ingress(cls, value, handler, info)

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> Self:
        return _model_validate_exact_root(cls, obj, **kwargs)

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        return _model_copy_exact_update(self, update=update, deep=deep)

    @model_validator(mode="before")
    @classmethod
    def require_exact_mapping(cls, value: object) -> object:
        return _require_exact_model_mapping(value)

    @field_validator(
        "owner_kind",
        "space_id",
        "product_version_id",
        "change_set_id",
        "observed_status",
        mode="before",
    )
    @classmethod
    def require_exact_strings(cls, value: object) -> object:
        return _require_exact_unicode_string(value)

    @field_validator("space_id", "product_version_id", "change_set_id", mode="after")
    @classmethod
    def reject_unresolved_identity(cls, value: str) -> str:
        return _require_resolved_identity(value)


class CompilationChangeItem(_ImmutableModel):
    """One pre-review ChangeItem fact linked to an inventoried ChangeSet."""

    owner_kind: GovernanceOwnerKind
    space_id: NonBlankStr
    product_version_id: NonBlankStr
    change_set_id: NonBlankStr
    change_item_id: NonBlankStr
    claim_id: NonBlankStr | None
    action: ChangeAction
    observed_decision: ObservedPreReviewDecision
    blocking_review_ids: tuple[NonBlankStr, ...]

    @model_validator(mode="wrap")
    @classmethod
    def require_canonical_ingress(cls, value: object, handler: Any, info: ValidationInfo) -> Self:
        return _canonical_python_ingress(cls, value, handler, info)

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> Self:
        return _model_validate_exact_root(cls, obj, **kwargs)

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        return _model_copy_exact_update(self, update=update, deep=deep)

    @model_validator(mode="before")
    @classmethod
    def require_exact_mapping(cls, value: object) -> object:
        return _require_exact_model_mapping(value)

    @field_validator(
        "owner_kind",
        "space_id",
        "product_version_id",
        "change_set_id",
        "change_item_id",
        "claim_id",
        "action",
        "observed_decision",
        mode="before",
    )
    @classmethod
    def require_exact_strings(cls, value: object) -> object:
        if value is None:
            return value
        return _require_exact_unicode_string(value)

    @field_validator("blocking_review_ids", mode="before")
    @classmethod
    def require_exact_review_sequence(cls, value: object) -> object:
        return _require_exact_sequence(value)

    @field_validator("blocking_review_ids", mode="after")
    @classmethod
    def canonicalize_review_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for review_id in value:
            _require_exact_unicode_string(review_id)
            _require_resolved_identity(review_id)
        if len(set(value)) != len(value):
            raise ValueError("item review IDs must be unique")
        return tuple(sorted(value))

    @field_validator(
        "space_id",
        "product_version_id",
        "change_set_id",
        "change_item_id",
        "claim_id",
        mode="after",
    )
    @classmethod
    def reject_unresolved_identity(cls, value: str | None) -> str | None:
        return None if value is None else _require_resolved_identity(value)

    @model_validator(mode="after")
    def require_review_projection(self) -> CompilationChangeItem:
        if self.observed_decision == "needs_review" and not self.blocking_review_ids:
            raise ValueError("needs_review items require a blocking ReviewItem")
        if self.observed_decision == "auto_applied" and self.blocking_review_ids:
            raise ValueError("auto-applied items cannot claim a blocking ReviewItem")
        return self


class CompilationManifestView(_ImmutableModel):
    """Immutable compilation facts; this value cannot approve review or release."""

    schema_version: Literal["insurancekb.runtime.compilation-manifest.v1"] = (
        "insurancekb.runtime.compilation-manifest.v1"
    )
    run: CompilationRunBinding
    compiled_at: NonBlankStr
    base: ReleaseBaseBinding | None
    artifacts: tuple[CompilationArtifact, ...]
    change_sets: tuple[CompilationChangeSet, ...]
    change_items: tuple[CompilationChangeItem, ...]
    blocking_review_ids: tuple[NonBlankStr, ...]

    @model_validator(mode="wrap")
    @classmethod
    def require_canonical_ingress(cls, value: object, handler: Any, info: ValidationInfo) -> Self:
        return _canonical_python_ingress(cls, value, handler, info)

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> Self:
        return _model_validate_exact_root(cls, obj, **kwargs)

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        return _model_copy_exact_update(self, update=update, deep=deep)

    @model_validator(mode="before")
    @classmethod
    def require_exact_input_graph(cls, value: object) -> object:
        raw = _require_exact_model_mapping(value)
        if "run" in raw and type(raw["run"]) not in {dict, CompilationRunBinding}:
            raise ValueError("run input must use an exact DTO or dictionary")
        if "base" in raw and raw["base"] is not None and type(raw["base"]) not in {
            dict,
            ReleaseBaseBinding,
        }:
            raise ValueError("base input must use an exact DTO or dictionary")
        for field_name, item_type in (
            ("artifacts", CompilationArtifact),
            ("change_sets", CompilationChangeSet),
            ("change_items", CompilationChangeItem),
        ):
            if field_name not in raw:
                continue
            sequence_value = raw[field_name]
            _require_exact_sequence(sequence_value)
            sequence = cast(list[object] | tuple[object, ...], sequence_value)
            if any(type(item) not in {dict, item_type} for item in sequence):
                raise ValueError(f"{field_name} must contain exact DTOs or dictionaries")
        if "blocking_review_ids" in raw:
            review_ids_value = raw["blocking_review_ids"]
            _require_exact_sequence(review_ids_value)
            review_ids = cast(list[object] | tuple[object, ...], review_ids_value)
            if any(type(review_id) is not str for review_id in review_ids):
                raise ValueError("blocking review IDs must use exact strings")
        return raw

    @field_validator("schema_version", "compiled_at", mode="before")
    @classmethod
    def require_exact_strings(cls, value: object) -> object:
        return _require_exact_unicode_string(value)

    @field_validator("compiled_at", mode="after")
    @classmethod
    def require_canonical_utc_timestamp(cls, value: str) -> str:
        if _CANONICAL_UTC_PATTERN.fullmatch(value) is None:
            raise ValueError("compiled_at must use canonical UTC microsecond form")
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError:
            raise ValueError("compiled_at is not a valid UTC timestamp") from None
        if parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ") != value:
            raise ValueError("compiled_at must round-trip canonically")
        return value

    @field_validator(
        "artifacts",
        "change_sets",
        "change_items",
        "blocking_review_ids",
        mode="before",
    )
    @classmethod
    def require_exact_sequences(cls, value: object) -> object:
        return _require_exact_sequence(value)

    @field_validator("artifacts", mode="after")
    @classmethod
    def canonicalize_artifacts(
        cls, value: tuple[CompilationArtifact, ...]
    ) -> tuple[CompilationArtifact, ...]:
        paths = tuple(artifact.path for artifact in value)
        if len(set(paths)) != len(paths):
            raise ValueError("artifact paths must be unique")
        return tuple(
            sorted(
                value,
                key=lambda artifact: (
                    artifact.space_id,
                    artifact.product_version_id or "",
                    artifact.path,
                ),
            )
        )

    @field_validator("change_sets", mode="after")
    @classmethod
    def canonicalize_change_sets(
        cls, value: tuple[CompilationChangeSet, ...]
    ) -> tuple[CompilationChangeSet, ...]:
        set_ids = tuple(change_set.change_set_id for change_set in value)
        if len(set(set_ids)) != len(set_ids):
            raise ValueError("change set IDs must be unique")
        return tuple(
            sorted(
                value,
                key=lambda change_set: (
                    change_set.space_id,
                    change_set.product_version_id,
                    change_set.change_set_id,
                ),
            )
        )

    @field_validator("change_items", mode="after")
    @classmethod
    def canonicalize_change_items(
        cls, value: tuple[CompilationChangeItem, ...]
    ) -> tuple[CompilationChangeItem, ...]:
        item_ids = tuple(item.change_item_id for item in value)
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("change item IDs must be unique")
        return tuple(
            sorted(
                value,
                key=lambda item: (
                    item.space_id,
                    item.product_version_id or "",
                    item.change_set_id,
                    item.change_item_id,
                ),
            )
        )

    @field_validator("blocking_review_ids", mode="after")
    @classmethod
    def canonicalize_review_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for review_id in value:
            _require_exact_unicode_string(review_id)
            _require_resolved_identity(review_id)
        if len(set(value)) != len(value):
            raise ValueError("blocking review IDs must be unique")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def require_one_space(self) -> CompilationManifestView:
        inventory_fact_count = (
            len(self.artifacts)
            + len(self.change_sets)
            + len(self.change_items)
            + len(self.blocking_review_ids)
        )
        if inventory_fact_count > _MAX_MANIFEST_INVENTORY_FACTS:
            raise ValueError("manifest inventory exceeds the semantic fact budget")
        space_id = self.run.space_id
        if self.base is not None and self.base.space_id != space_id:
            raise ValueError("base release must belong to the compilation Space")
        if any(artifact.space_id != space_id for artifact in self.artifacts):
            raise ValueError("artifacts must belong to the compilation Space")
        if any(change_set.space_id != space_id for change_set in self.change_sets):
            raise ValueError("change sets must belong to the compilation Space")
        if any(item.space_id != space_id for item in self.change_items):
            raise ValueError("change items must belong to the compilation Space")
        sets_by_id = {change_set.change_set_id: change_set for change_set in self.change_sets}
        items_by_set: dict[str, list[CompilationChangeItem]] = {
            change_set_id: [] for change_set_id in sets_by_id
        }
        nested_review_ids: set[str] = set()
        for item in self.change_items:
            change_set = sets_by_id.get(item.change_set_id)
            if change_set is None:
                raise ValueError("change items must reference an inventoried ChangeSet")
            if (
                item.owner_kind != change_set.owner_kind
                or item.space_id != change_set.space_id
                or item.product_version_id != change_set.product_version_id
            ):
                raise ValueError("change item owner must match its ChangeSet")
            items_by_set[item.change_set_id].append(item)
            for review_id in item.blocking_review_ids:
                if review_id in nested_review_ids:
                    raise ValueError("one ReviewItem cannot block multiple ChangeItems")
                nested_review_ids.add(review_id)
        if tuple(sorted(nested_review_ids)) != self.blocking_review_ids:
            raise ValueError("top-level ReviewItem inventory must equal the item union")
        for change_set in self.change_sets:
            decisions = {item.observed_decision for item in items_by_set[change_set.change_set_id]}
            if not decisions:
                if change_set.observed_status == "partially_applied":
                    raise ValueError("an empty ChangeSet cannot be partially applied")
                continue
            expected_status = (
                "pending"
                if decisions == {"needs_review"}
                else "applied"
                if decisions == {"auto_applied"}
                else "partially_applied"
            )
            if change_set.observed_status != expected_status:
                raise ValueError("ChangeSet status must be the code-owned item projection")
        return self


def compilation_manifest_digest(value: CompilationManifestView) -> str:
    """Return the stable, domain-separated digest of exact validated facts."""

    validated = _revalidate_exact(CompilationManifestView, value)
    return _canonical_digest(
        _COMPILATION_MANIFEST_DOMAIN,
        BaseModel.model_dump(validated, mode="json", round_trip=True),
    )


def canonical_compilation_manifest_bytes(value: CompilationManifestView) -> bytes:
    """Serialize one validated audit value without adding any authority state."""

    try:
        validated = _revalidate_exact(CompilationManifestView, value)
        payload = BaseModel.model_dump(validated, mode="json", round_trip=True)
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except MemoryError:
        raise
    except Exception:
        raise ValueError("invalid_compilation_manifest") from None


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for pair in pairs:
        if type(pair) is not tuple or len(pair) != 2:
            raise ValueError("JSON object entries must be exact pairs")
        key, item = pair
        if type(key) is not str or key in result:
            raise ValueError("JSON object keys must be unique exact strings")
        result[key] = item
    return result


def _reject_non_json_constant(value: str) -> None:
    raise ValueError(f"non-JSON numeric constant is forbidden: {value}")


def parse_compilation_manifest(payload: bytes) -> CompilationManifestView:
    """Parse untrusted JSON with duplicate-key rejection into a fresh audit value."""

    try:
        if type(payload) is not bytes:
            raise TypeError("manifest payload must use exact bytes")
        raw = json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_non_json_constant,
        )
        if type(raw) is not dict:
            raise TypeError("manifest root must be an exact JSON object")
        return CompilationManifestView.model_validate(raw)
    except MemoryError:
        raise
    except Exception:
        raise ValueError("invalid_compilation_manifest") from None
