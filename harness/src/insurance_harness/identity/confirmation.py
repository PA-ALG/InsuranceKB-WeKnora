"""What a person may decide about a material the attribution rules could not settle (S5b-3c-1 Spec).

Each `NEEDS_CONFIRM` reason offers a fixed set of choices (brand candidates, S11c, as the products
a title names); so does each `QUARANTINE` reason (S11a):
a material without a product anchor may be named as one registered product's, and any quarantined
material may be ignored. A choice supplies only the fact the rules
were missing — which product, which role, which pack — and the S5b-1 rules then conclude as before;
replacing, supplementing and ignoring settle a second material of the same role directly. Nothing
here reads text a person wrote, so a choice can never widen what the rules accept.
"""

import hashlib
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from insurance_harness.identity.attribution import (
    Attribution,
    AttributionInputError,
    AttributionPolicy,
    RegisteredProduct,
    Upload,
    attribute,
    load_attribution_policy,
)
from insurance_harness.identity.material_roles import load_material_roles
from insurance_harness.identity.training_versions import versioned
from insurance_harness.identity.version_basis import VersionBasis

MAX_CHOICES = 50  # the platform's limit on options per confirmation item (S5b-3a)
# Training materials by version (PV-3 Spec §3): these questions are judged again when answered.
VERSION_REASONS = frozenset({"version_candidates", "no_date_signal", "version_role_unresolved"})
_ONLY_IGNORED = frozenset(
    {"anchor_conflict", "text_unavailable", "no_registered_version", "date_signals_conflict",
     "multiple_families"}
)
OPTION_KEY = r"^[a-z0-9][a-z0-9:._-]{0,127}$"  # the platform's option key format (S5b-3a)


class ConfirmationError(ValueError):
    """NOT_CONFIRMABLE, CHOICE_UNKNOWN or CHOICE_STALE; never a document name or its text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Choice(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    key: str = Field(pattern=OPTION_KEY)
    kind: Literal["product", "pack", "role", "replace", "supplement", "ignore"]
    value: str | None = None  # the product id, schema pack id or role


def _product_key(product_id: str) -> str:
    # Product ids may hold capitals, which option keys do not allow.
    return "product:" + hashlib.sha256(product_id.encode("utf-8")).hexdigest()[:16]


def choices(
    pending: Attribution,
    registry: Sequence[RegisteredProduct],
    policy: AttributionPolicy | None = None,
) -> tuple[Choice, ...]:
    """The choices a question for a person offers, in a fixed order, ending with ignoring it."""
    policy = policy or load_attribution_policy()
    if pending.outcome not in {"NEEDS_CONFIRM", "QUARANTINE"}:
        raise ConfirmationError("NOT_CONFIRMABLE")
    ids = [product.product_id for product in registry]
    if len(set(ids)) != len(ids):  # as attribute() refuses it: never pick one definition
        raise AttributionInputError("REGISTRY_DUPLICATE_PRODUCT")
    try:
        found = _quarantined(pending, ids) if pending.outcome == "QUARANTINE" else None
        offered = [
            *(found if found is not None else _offered(pending, set(ids), policy)),
            Choice(key="ignore", kind="ignore"),
        ]
    except ValidationError:  # a policy pack or role that cannot be an option key
        raise ConfirmationError("NOT_CONFIRMABLE") from None
    keys = [choice.key for choice in offered]
    if len(set(keys)) != len(keys) or len(keys) > MAX_CHOICES:
        raise ConfirmationError("NOT_CONFIRMABLE")
    return tuple(offered)


def _quarantined(pending: Attribution, ids: list[str]) -> list[Choice]:
    """S11a Spec §2.1: without a product anchor a person may name any registered product; with
    conflicting anchors or no readable opening the rules would quarantine any product chosen, so
    only ignoring is offered."""
    if pending.reason == "no_product_anchor":
        return [Choice(key=_product_key(p), kind="product", value=p) for p in ids]
    if pending.reason in _ONLY_IGNORED:  # PV-3: no version of that time, or self-contradicting
        return []
    raise ConfirmationError("NOT_CONFIRMABLE")


def _offered(pending: Attribution, registered: set[str], policy: AttributionPolicy) -> list[Choice]:
    if pending.reason in {"multiple_products", "brand_candidates", "version_candidates"} or (
        pending.reason == "no_date_signal"
    ):
        return [
            Choice(key=_product_key(product_id), kind="product", value=product_id)
            for product_id in pending.candidates
            if product_id in registered
        ]
    if pending.reason == "pack_unresolved":
        packs = dict.fromkeys(entry.schema_pack_id for entry in policy.classifications)
        return [Choice(key=f"pack:{pack}", kind="pack", value=pack) for pack in packs]
    if pending.reason not in {"role_unresolved", "same_role_differs", "version_role_unresolved"}:
        raise ConfirmationError("NOT_CONFIRMABLE")
    if pending.product_id not in registered:
        return []
    if pending.reason == "version_role_unresolved":  # only the roles a training material may take
        return [Choice(key=f"role:{r}", kind="role", value=r) for r in policy.brand_roles]
    if pending.reason == "role_unresolved":
        roles = load_material_roles().roles
        return [Choice(key=f"role:{r.role}", kind="role", value=r.role) for r in roles]
    return [Choice(key="replace", kind="replace"), Choice(key="supplement", kind="supplement")]


def conclude(
    pending: Attribution,
    key: str,
    upload: Upload,
    registry: Sequence[RegisteredProduct],
    policy: AttributionPolicy | None = None,
) -> Attribution:
    """The attribution a person's choice concludes (Spec §2.2).

    CHOICE_STALE means the registry has changed since the question so the choice no longer applies;
    the material should then be judged afresh rather than settled by it.
    """
    policy = policy or load_attribution_policy()
    choice = next((c for c in choices(pending, registry, policy) if c.key == key), None)
    if choice is None:
        raise ConfirmationError("CHOICE_UNKNOWN")
    if choice.kind == "ignore":
        return _settled(
            pending, policy, "IGNORED", "confirmed_ignore", candidates=pending.candidates
        )
    if choice.kind in {"replace", "supplement"}:
        return _same_role(pending, choice.kind, registry, policy)
    if choice.kind in {"product", "role"} and versioned(registry):
        _still_asked(pending, choice, upload, registry, policy)
    try:
        if choice.kind == "product":
            result = attribute(upload, registry, policy, product=choice.value)
            fits = _about(result) == choice.value and (
                result.outcome in {"DUPLICATE", "SUPPLEMENT", "NEW_VERSION"}
                or (
                    result.outcome == "NEEDS_CONFIRM"
                    and result.reason in {"role_unresolved", "same_role_differs"}
                )
            )
        elif choice.kind == "role":
            result = attribute(
                upload, registry, policy, product=pending.product_id, role=choice.value
            )
            fits = (_about(result), result.role) == (pending.product_id, choice.value) and (
                result.outcome in {"SUPPLEMENT", "NEW_VERSION"}
                or (result.outcome, result.reason) == ("NEEDS_CONFIRM", "same_role_differs")
            )
        else:
            result = attribute(upload, registry, policy, pack=choice.value)
            fits = result.outcome == "CREATE" and result.schema_pack_id == choice.value
    except AttributionInputError as error:
        if error.code != "CHOICE_INVALID":
            raise
        raise ConfirmationError("CHOICE_STALE") from None
    if not fits:
        raise ConfirmationError("CHOICE_STALE")
    if pending.version_basis is not None and pending.reason in VERSION_REASONS:
        by_person = pending.reason != "version_role_unresolved"
        role_by = "person" if choice.kind == "role" else ("machine" if result.role else None)
        basis = pending.version_basis.model_copy(
            update={
                "version_decided_by": "person" if by_person else "machine",
                "role_decided_by": role_by,
            }
        )
        return result.model_copy(update={"version_basis": basis})
    return result


def _evidence(basis: VersionBasis | None) -> VersionBasis | None:
    """The evidence a question showed, without who decided."""
    if basis is None:
        return None
    return basis.model_copy(update={"version_decided_by": None, "role_decided_by": None})


def _still_asked(
    pending: Attribution,
    choice: Choice,
    upload: Upload,
    registry: Sequence[RegisteredProduct],
    policy: AttributionPolicy,
) -> None:
    """A version answer applies only to the question the material still raises, with the same
    evidence; an older question cannot carry a choice past the version rules (PV-3 Spec §3)."""
    fresh = attribute(upload, registry, policy)
    if pending.reason not in VERSION_REASONS:
        if fresh.version_basis is not None:
            raise ConfirmationError("CHOICE_STALE")
        return
    same = (fresh.reason, _evidence(fresh.version_basis)) == (
        pending.reason,
        _evidence(pending.version_basis),
    )
    if pending.reason == "version_role_unresolved":
        same = same and fresh.product_id == pending.product_id
    elif choice.value not in fresh.candidates:
        same = False
    if not same:
        raise ConfirmationError("CHOICE_STALE")


def _about(result: Attribution) -> str | None:
    """The registered product a conclusion is about: a new version names its entry of the same
    name as the one candidate, beside the new entry it adds (PV-1 Spec §3)."""
    if result.outcome == "NEW_VERSION" and len(result.candidates) == 1:
        return result.candidates[0]
    return result.product_id


def _same_role(
    pending: Attribution,
    kind: str,
    registry: Sequence[RegisteredProduct],
    policy: AttributionPolicy,
) -> Attribution:
    product = next(p for p in registry if p.product_id == pending.product_id)
    if kind == "supplement":
        return _settled(pending, policy, "SUPPLEMENT", "confirmed_supplement")
    replaced = tuple(sorted(m.knowledge_id for m in product.materials if m.role == pending.role))
    if not replaced:
        raise ConfirmationError("CHOICE_STALE")
    return _settled(pending, policy, "REPLACE", "confirmed_replace", replaces=replaced)


def _settled(
    pending: Attribution, policy: AttributionPolicy, outcome: str, reason: str, **fields: object
) -> Attribution:
    return Attribution.model_validate(
        {
            "outcome": outcome,
            "reason": reason,
            "product_id": pending.product_id,
            "role": pending.role,
            "clause_code": pending.clause_code,
            "policy_ref": policy.policy_ref,
            **fields,
        }
    )
