"""What a person may decide about a material the attribution rules could not settle (S5b-3c-1 Spec).

Each `NEEDS_CONFIRM` reason offers a fixed set of choices. A choice supplies only the fact the rules
were missing — which product, which role, which pack — and the S5b-1 rules then conclude as before;
replacing, supplementing and ignoring settle a second material of the same role directly. Nothing
here reads text a person wrote, so a choice can never widen what the rules accept.
"""

import hashlib
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

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

MAX_CHOICES = 50  # the platform's limit on options per confirmation item (S5b-3a)


class ConfirmationError(ValueError):
    """NOT_CONFIRMABLE, CHOICE_UNKNOWN or CHOICE_STALE; never a document name or its text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Choice(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    key: str
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
    if pending.outcome != "NEEDS_CONFIRM":
        raise ConfirmationError("NOT_CONFIRMABLE")
    registered = {product.product_id for product in registry}
    offered: list[Choice]
    if pending.reason == "multiple_products":
        offered = [
            Choice(key=_product_key(product_id), kind="product", value=product_id)
            for product_id in pending.candidates
            if product_id in registered
        ]
    elif pending.reason == "pack_unresolved":
        packs = dict.fromkeys(entry.schema_pack_id for entry in policy.classifications)
        offered = [Choice(key=f"pack:{pack}", kind="pack", value=pack) for pack in packs]
    elif pending.reason in {"role_unresolved", "same_role_differs"}:
        offered = []
        if pending.product_id in registered and pending.reason == "role_unresolved":
            roles = load_material_roles().roles
            offered = [Choice(key=f"role:{r.role}", kind="role", value=r.role) for r in roles]
        elif pending.product_id in registered:
            offered = [
                Choice(key="replace", kind="replace"),
                Choice(key="supplement", kind="supplement"),
            ]
    else:
        raise ConfirmationError("NOT_CONFIRMABLE")
    offered.append(Choice(key="ignore", kind="ignore"))
    keys = [choice.key for choice in offered]
    if len(set(keys)) != len(keys) or len(keys) > MAX_CHOICES:
        raise ConfirmationError("NOT_CONFIRMABLE")
    return tuple(offered)


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
    try:
        if choice.kind == "product":
            result = attribute(upload, registry, policy, product=choice.value)
            fits = result.product_id == choice.value and (
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
            fits = (result.product_id, result.role) == (pending.product_id, choice.value) and (
                result.outcome in {"SUPPLEMENT", "NEW_VERSION"}
                or (result.outcome, result.reason) == ("NEEDS_CONFIRM", "same_role_differs")
            )
        else:
            result = attribute(upload, registry, policy, pack=choice.value)
            fits = result.outcome == "CREATE" and result.schema_pack_id == choice.value
    except AttributionInputError:
        raise ConfirmationError("CHOICE_STALE") from None
    if not fits:
        raise ConfirmationError("CHOICE_STALE")
    return result


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
