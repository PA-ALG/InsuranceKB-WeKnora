"""Taking a wrongly attributed material off its entry (PV-3 Spec §4; PV-0 §4.4).

The controlled way back from a wrong attribution: the material leaves its entry's materials for
`retired`, a `DETACHED` decision records why with a fixed code (never text a person wrote), and
the material is not judged again (a retired material never is). Its knowledge follows the existing
change rules on the next compile: a claim supported only by this material is withdrawn as a source
withdrawal; one still supported by another source, or under an expert lock, is kept. Only a v2
registry is detached, so a v1 file stays readable by code without this outcome; the last material
of an entry is never detached (no withdrawal path exists for an entry left without sources).

A detach is material-level (SK-1 §3.4): it also expires the material's method use. A material that
is only a method material (no entry holds it) is detached too: its method use expires, it leaves
`pending`, and the DETACHED decision (no product, role `sales_method`) keeps it out of later runs.
"""

from insurance_harness.identity.attribution import Attribution, load_attribution_policy
from insurance_harness.ingest.method_use_model import LIVE, METHOD_ROLE
from insurance_harness.ingest.method_uses import expire_material
from insurance_harness.ingest.registry import V2, DecisionEntry, ProductRegistry

REASONS = ("wrong_version", "wrong_product", "not_product_material")


class DetachError(ValueError):
    """REGISTRY_V1, MATERIAL_NOT_ATTACHED, LAST_MATERIAL, REASON_INVALID or SETTLEMENT_PENDING;
    never a path or a name."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def detach(registry: ProductRegistry, knowledge_id: str, reason: str) -> ProductRegistry:
    """The registry with the material taken off its entry; the given registry is not changed."""
    if registry.contract != V2:
        raise DetachError("REGISTRY_V1")
    if reason not in REASONS:
        raise DetachError("REASON_INVALID")
    if any(u.knowledge_id == knowledge_id and u.settlement for u in registry.method_uses):
        raise DetachError("SETTLEMENT_PENDING")  # a person's method answer is being carried out
    owner = next(
        (
            product_id
            for product_id, product in registry.products.items()
            if any(m.knowledge_id == knowledge_id for m in product.materials)
        ),
        None,
    )
    if owner is None:
        return _method_only(registry, knowledge_id, reason)
    if len(registry.products[owner].materials) == 1:
        # An entry without any source has no withdrawal path yet: the source map refuses it, so
        # the next compile could not withdraw its knowledge (review R6). Refused, not half done.
        raise DetachError("LAST_MATERIAL")
    current = registry.model_copy(deep=True)
    product = current.products[owner]
    material = next(m for m in product.materials if m.knowledge_id == knowledge_id)
    product.materials = [m for m in product.materials if m.knowledge_id != knowledge_id]
    product.retired = sorted([*product.retired, material], key=lambda m: m.knowledge_id)
    current.decisions.append(
        DecisionEntry(
            knowledge_id=material.knowledge_id,
            parse_attempt=material.parse_attempt,
            sha256=material.sha256,
            attribution=Attribution(
                outcome="DETACHED",
                reason=reason,
                product_id=owner,
                role=material.role,
                policy_ref=load_attribution_policy().policy_ref,
            ),
        )
    )
    expire_material(current, knowledge_id, "detached")
    return ProductRegistry.model_validate(current.model_dump())


def _method_only(registry: ProductRegistry, knowledge_id: str, reason: str) -> ProductRegistry:
    """A material no entry holds whose only use is a live method use (SK-1 §3.4)."""
    waiting = [p for p in registry.pending if p.knowledge_id == knowledge_id]
    live = [u for u in registry.method_uses if u.knowledge_id == knowledge_id and u.state in LIVE]
    if not live or any(p.attribution.outcome != "METHOD_MATERIAL" for p in waiting):
        raise DetachError("MATERIAL_NOT_ATTACHED")  # a product question still waits: not this
    current = registry.model_copy(deep=True)
    current.pending = [p for p in current.pending if p.knowledge_id != knowledge_id]
    expire_material(current, knowledge_id, "detached")
    use = live[0]
    current.decisions.append(
        DecisionEntry(
            knowledge_id=use.knowledge_id,
            parse_attempt=use.parse_attempt,
            sha256=use.sha256,
            attribution=Attribution(
                outcome="DETACHED",
                reason=reason,
                role=METHOD_ROLE,
                policy_ref=load_attribution_policy().policy_ref,
            ),
        )
    )
    return ProductRegistry.model_validate(current.model_dump())
