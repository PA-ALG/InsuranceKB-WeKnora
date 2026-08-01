"""Pure affected-only compilation of verified facts into immutable change drafts."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    StringConstraints,
    ValidationError,
    computed_field,
    field_validator,
    model_validator,
)

from insurance_harness.canonical import canonical_hash
from insurance_harness.knowledge_compiler.retractions import (
    RetractionContractError,
    RetractionProofV1,
    require_exclusive_retraction,
)
from insurance_harness.knowledge_compiler.source_authority import (
    FactScopeV1,
    SourceAuthorityContractError,
    SourceAuthorityV1,
    _resolved_identity,
    compare_source_authority,
    validate_source_authority,
)

ChangeAction = Literal["add", "enrich", "supersede", "conflict", "retract"]
FactState = Literal["known", "unknown"]
_FACT_OBJECT_TYPE = "incremental-verified-fact.v1"
_ITEM_OBJECT_TYPE = "incremental-change-item.v1"
_SET_OBJECT_TYPE = "incremental-change-set.v1"
_INPUT_OBJECT_TYPE = "incremental-change-input.v1"
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ResolvedId = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=512, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
class _FieldAuthority(Protocol):
    primary_role: Literal["terms", "brochure", "rate_table"]
    support_roles: tuple[Literal["terms", "brochure", "rate_table"], ...]


class IncrementalCompilationError(ValueError):
    """Raised when incremental inputs cannot produce an authoritative draft."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class VerifiedFactV1(_FrozenModel):
    """A deterministic fact already verified at the Child E input boundary."""

    object_type: Literal["verified_fact.v1"] = "verified_fact.v1"
    scope: FactScopeV1
    state: FactState
    value_hash: Sha256Hex | None = None
    authority: SourceAuthorityV1
    evidence_hashes: tuple[Sha256Hex, ...] = ()
    supporting_source_revision_ids: tuple[ResolvedId, ...] = ()

    @field_validator("supporting_source_revision_ids")
    @classmethod
    def _reject_wildcard_support(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _resolved_identity(value)
        return values

    @model_validator(mode="after")
    def _validate_fact(self) -> VerifiedFactV1:
        if tuple(sorted(set(self.evidence_hashes))) != self.evidence_hashes:
            raise ValueError("evidence_hashes must be unique and canonically ordered")
        if tuple(sorted(set(self.supporting_source_revision_ids))) != (
            self.supporting_source_revision_ids
        ):
            raise ValueError(
                "supporting_source_revision_ids must be unique and canonically ordered"
            )
        if (
            not self.supporting_source_revision_ids
            or self.authority.source_revision_id not in self.supporting_source_revision_ids
        ):
            raise ValueError("authority_revision_not_supported")
        if self.state == "known":
            if self.value_hash is None or not self.evidence_hashes:
                raise ValueError("known facts require value_hash and evidence")
        elif self.value_hash is not None or self.evidence_hashes:
            raise ValueError("unknown facts cannot carry value or evidence")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fact_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"fact_hash"})
        return canonical_hash(_FACT_OBJECT_TYPE, payload)


class ChangeItemDraftV1(_FrozenModel):
    object_type: Literal["incremental_change_item.v1"] = "incremental_change_item.v1"
    action: ChangeAction
    scope: FactScopeV1
    incoming_fact_hash: Sha256Hex | None = None
    prior_fact_hashes: tuple[Sha256Hex, ...] = ()
    evidence_hashes: tuple[Sha256Hex, ...] = ()
    retraction_proof_hash: Sha256Hex | None = None
    reason: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def _validate_shape(self) -> ChangeItemDraftV1:
        for values, label in (
            (self.prior_fact_hashes, "prior_fact_hashes"),
            (self.evidence_hashes, "evidence_hashes"),
        ):
            if tuple(sorted(set(values))) != values:
                raise ValueError(f"{label} must be unique and canonically ordered")
        if self.action == "add" and self.prior_fact_hashes:
            raise ValueError("add cannot reference prior facts")
        if self.action != "add" and not self.prior_fact_hashes:
            raise ValueError(f"{self.action} requires prior facts")
        if self.action == "retract":
            if self.incoming_fact_hash is not None or self.retraction_proof_hash is None:
                raise ValueError("retract requires only an explicit retraction proof")
        elif self.incoming_fact_hash is None or self.retraction_proof_hash is not None:
            raise ValueError("non-retract changes require an incoming fact")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def item_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"item_hash"})
        return canonical_hash(_ITEM_OBJECT_TYPE, payload)


class ChangeSetDraftV1(_FrozenModel):
    object_type: Literal["incremental_change_set.v1"] = "incremental_change_set.v1"
    contract_version: Literal["058.v1"] = "058.v1"
    space_id: str = Field(min_length=1, max_length=128)
    product_version_id: str = Field(min_length=1, max_length=128)
    authority_policy_hash: Sha256Hex
    input_hash: Sha256Hex
    items: tuple[ChangeItemDraftV1, ...]

    @model_validator(mode="after")
    def _validate_items(self) -> ChangeSetDraftV1:
        ordered = tuple(
            sorted(self.items, key=lambda item: (item.scope.scope_hash, item.item_hash))
        )
        if ordered != self.items:
            raise ValueError("change items must be canonically ordered")
        scope_hashes = tuple(item.scope.scope_hash for item in self.items)
        if len(scope_hashes) != len(set(scope_hashes)):
            raise ValueError("change set cannot contain duplicate affected scopes")
        if any(
            item.scope.space_id != self.space_id
            or item.scope.product_version_id != self.product_version_id
            for item in self.items
        ):
            raise ValueError("change item escaped the change-set scope")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def change_set_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"change_set_hash"})
        return canonical_hash(_SET_OBJECT_TYPE, payload)


def _item(
    action: ChangeAction,
    scope: FactScopeV1,
    incoming: VerifiedFactV1 | None,
    prior: tuple[VerifiedFactV1, ...],
    reason: str,
    proof: RetractionProofV1 | None = None,
) -> ChangeItemDraftV1:
    return ChangeItemDraftV1(
        action=action,
        scope=scope,
        incoming_fact_hash=None if incoming is None else incoming.fact_hash,
        prior_fact_hashes=tuple(sorted(fact.fact_hash for fact in prior)),
        evidence_hashes=(
            ()
            if incoming is None
            else tuple(
                sorted(
                    set(incoming.evidence_hashes).union(*(fact.evidence_hashes for fact in prior))
                )
            )
        ),
        retraction_proof_hash=None if proof is None else proof.proof_hash,
        reason=reason,
    )


def _candidate_item(
    incoming: VerifiedFactV1,
    prior: tuple[VerifiedFactV1, ...],
    field_authority: _FieldAuthority,
) -> ChangeItemDraftV1 | None:
    if incoming.state == "unknown":
        return None
    if not prior:
        return _item("add", incoming.scope, incoming, prior, "new verified fact")
    same_value = tuple(fact for fact in prior if fact.value_hash == incoming.value_hash)
    if len(same_value) == len(prior):
        known_evidence = set().union(*(fact.evidence_hashes for fact in prior))
        known_support = set().union(*(fact.supporting_source_revision_ids for fact in prior))
        if (
            set(incoming.evidence_hashes) <= known_evidence
            and set(incoming.supporting_source_revision_ids) <= known_support
        ):
            return None
        return _item("enrich", incoming.scope, incoming, prior, "additional verified support")
    different_value = tuple(fact for fact in prior if fact.value_hash != incoming.value_hash)
    if all(
        compare_source_authority(
            incoming.authority,
            fact.authority,
            field_authority=field_authority,
        )
        == "higher"
        for fact in different_value
    ):
        return _item("supersede", incoming.scope, incoming, prior, "higher source authority")
    return _item("conflict", incoming.scope, incoming, prior, "unresolved authority conflict")


def compile_incremental_changes(
    *,
    space_id: str,
    product_version_id: str,
    material_profile_catalog: object,
    material_profile_resolutions: Iterable[object],
    baseline_facts: Iterable[VerifiedFactV1],
    candidate_facts: Iterable[VerifiedFactV1],
    retraction_proofs: Iterable[RetractionProofV1] = (),
) -> ChangeSetDraftV1:
    """Compile affected facts and explicit proofs without guessing missing state."""

    try:
        if not space_id or not product_version_id:
            raise ValueError("empty_identity_forbidden")
        _resolved_identity(space_id)
        _resolved_identity(product_version_id)
    except ValueError:
        raise IncrementalCompilationError("invalid_root_scope") from None
    from insurance_harness.compiler.material_profiles import (
        MaterialProfileCatalog,
        MaterialProfileResolution,
        material_profile_catalog_hash,
    )

    try:
        catalog = MaterialProfileCatalog.model_validate(material_profile_catalog)
    except ValidationError as exc:
        raise IncrementalCompilationError("authority_policy_mismatch") from exc
    if catalog.product.product_version != product_version_id:
        raise IncrementalCompilationError("invalid_root_scope")
    catalog_hash = material_profile_catalog_hash(catalog)
    try:
        resolutions = tuple(
            MaterialProfileResolution.model_validate(value)
            for value in material_profile_resolutions
        )
    except ValidationError as exc:
        raise IncrementalCompilationError("authority_binding_mismatch") from exc
    registered_bindings = {resolution.binding_hash: resolution for resolution in resolutions}
    if not resolutions or len(registered_bindings) != len(resolutions):
        raise IncrementalCompilationError("authority_binding_mismatch")
    for resolution in resolutions:
        registered_profile = next(
            (
                profile
                for profile in catalog.profiles
                if profile.source.sha256 == resolution.profile.source.sha256
            ),
            None,
        )
        if (
            resolution.catalog_hash != catalog_hash
            or resolution.request.space_id != space_id
            or resolution.request.product_version != product_version_id
            or registered_profile != resolution.profile
        ):
            raise IncrementalCompilationError("authority_binding_mismatch")

    def revalidate_fact(value: VerifiedFactV1) -> VerifiedFactV1:
        try:
            payload = value.model_dump(
                mode="python",
                exclude={
                    "fact_hash": True,
                    "scope": {"scope_hash": True},
                    "authority": {
                        "authority_hash": True,
                        "binding": {"registration_hash": True},
                    },
                },
            )
            return VerifiedFactV1.model_validate(payload)
        except ValidationError as exc:
            raise IncrementalCompilationError("invalid_fact") from exc

    def revalidate_proof(value: RetractionProofV1) -> RetractionProofV1:
        try:
            payload = value.model_dump(
                mode="python",
                exclude={
                    "proof_hash": True,
                    "scope": {"scope_hash": True},
                    "replacement_authority": {
                        "authority_hash": True,
                        "binding": {"registration_hash": True},
                    },
                },
            )
            return RetractionProofV1.model_validate(payload)
        except ValidationError as exc:
            raise IncrementalCompilationError("invalid_retraction_proof") from exc

    baseline = tuple(sorted(map(revalidate_fact, baseline_facts), key=lambda fact: fact.fact_hash))
    candidates = tuple(
        sorted(map(revalidate_fact, candidate_facts), key=lambda fact: fact.fact_hash)
    )
    proofs = tuple(
        sorted(map(revalidate_proof, retraction_proofs), key=lambda proof: proof.proof_hash)
    )
    all_scoped: tuple[VerifiedFactV1 | RetractionProofV1, ...] = baseline + candidates + proofs
    if any(
        value.scope.space_id != space_id or value.scope.product_version_id != product_version_id
        for value in all_scoped
    ):
        raise IncrementalCompilationError("cross_scope_input")
    if any(fact.state != "known" for fact in baseline):
        raise IncrementalCompilationError("baseline facts must be known")
    if len({fact.fact_hash for fact in baseline}) != len(baseline):
        raise IncrementalCompilationError("duplicate baseline fact")

    authority_by_fact_hash: dict[str, _FieldAuthority] = {}
    for fact in baseline + candidates:
        fact_resolution = registered_bindings.get(fact.authority.binding.binding_hash)
        if (
            fact_resolution is None
            or fact_resolution.profile.source.sha256 != fact.authority.source_id
            or fact_resolution.profile.material_role != fact.authority.material_role
        ):
            raise IncrementalCompilationError("authority_binding_mismatch")
        try:
            field_authority = catalog.authority_for(fact.scope.field_id)
        except KeyError:
            raise IncrementalCompilationError("authority_policy_mismatch") from None
        try:
            validate_source_authority(
                fact.authority,
                catalog_hash=catalog_hash,
                registered_binding_hashes=frozenset(registered_bindings),
                space_id=space_id,
                product_version_id=product_version_id,
                field_authority=field_authority,
            )
        except SourceAuthorityContractError as exc:
            raise IncrementalCompilationError(exc.reason_code) from exc
        authority_by_fact_hash[fact.fact_hash] = field_authority
    for proof in proofs:
        proof_resolution = registered_bindings.get(proof.replacement_authority.binding.binding_hash)
        if (
            proof_resolution is None
            or proof_resolution.profile.source.sha256 != proof.replacement_authority.source_id
            or proof_resolution.profile.material_role != proof.replacement_authority.material_role
        ):
            raise IncrementalCompilationError("authority_binding_mismatch")
        try:
            proof_field_authority = catalog.authority_for(proof.scope.field_id)
        except KeyError:
            raise IncrementalCompilationError("authority_policy_mismatch") from None
        try:
            validate_source_authority(
                proof.replacement_authority,
                catalog_hash=catalog_hash,
                registered_binding_hashes=frozenset(registered_bindings),
                space_id=space_id,
                product_version_id=product_version_id,
                field_authority=proof_field_authority,
            )
        except SourceAuthorityContractError as exc:
            raise IncrementalCompilationError(exc.reason_code) from exc

    by_scope: dict[str, list[VerifiedFactV1]] = {}
    for fact in baseline:
        by_scope.setdefault(fact.scope.scope_hash, []).append(fact)
    items: list[ChangeItemDraftV1] = []
    affected: set[str] = set()
    for incoming in candidates:
        scope_hash = incoming.scope.scope_hash
        if scope_hash in affected:
            raise IncrementalCompilationError("multiple candidate facts for one affected scope")
        affected.add(scope_hash)
        item = _candidate_item(
            incoming,
            tuple(by_scope.get(scope_hash, ())),
            authority_by_fact_hash[incoming.fact_hash],
        )
        if item is not None:
            items.append(item)

    for proof in proofs:
        scope_hash = proof.scope.scope_hash
        if scope_hash in affected:
            raise IncrementalCompilationError("candidate and retraction share an affected scope")
        affected.add(scope_hash)
        prior = tuple(by_scope.get(scope_hash, ()))
        if len(prior) != 1:
            raise IncrementalCompilationError("retraction requires one exact baseline fact")
        try:
            require_exclusive_retraction(
                proof,
                baseline_scope=prior[0].scope,
                baseline_authority=prior[0].authority,
                supporting_source_revision_ids=prior[0].supporting_source_revision_ids,
                field_authority=authority_by_fact_hash[prior[0].fact_hash],
            )
        except RetractionContractError as exc:
            raise IncrementalCompilationError(str(exc)) from exc
        items.append(_item("retract", proof.scope, None, prior, proof.reason_code, proof))

    ordered_items = tuple(sorted(items, key=lambda item: (item.scope.scope_hash, item.item_hash)))
    input_hash = canonical_hash(
        _INPUT_OBJECT_TYPE,
        {
            "baseline_fact_hashes": [fact.fact_hash for fact in baseline],
            "candidate_fact_hashes": [fact.fact_hash for fact in candidates],
            "retraction_proof_hashes": [proof.proof_hash for proof in proofs],
            "space_id": space_id,
            "product_version_id": product_version_id,
            "authority_policy_hash": catalog_hash,
        },
    )
    return ChangeSetDraftV1(
        space_id=space_id,
        product_version_id=product_version_id,
        authority_policy_hash=catalog_hash,
        input_hash=input_hash,
        items=ordered_items,
    )


__all__ = [
    "ChangeItemDraftV1",
    "ChangeSetDraftV1",
    "IncrementalCompilationError",
    "VerifiedFactV1",
    "compile_incremental_changes",
]
