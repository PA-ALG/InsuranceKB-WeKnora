"""Taking a wrongly attributed material off its entry (PV-3 Spec §4; PV-0 §4.4).

The controlled way back from a wrong attribution: the material leaves its entry's materials for
`retired`, a `DETACHED` decision records why with a fixed code (never text a person wrote), and
the material is not judged again (a retired material never is). Its knowledge follows the existing
change rules on the next compile: a claim supported only by this material is withdrawn as a source
withdrawal; one still supported by another source, or under an expert lock, is kept. Only a v2
registry is detached, so a v1 file stays readable by code without this outcome; the last material
of an entry is never detached (no withdrawal path exists for an entry left without sources).
"""

from insurance_harness.identity.attribution import Attribution, load_attribution_policy
from insurance_harness.ingest.registry import V2, DecisionEntry, ProductRegistry

REASONS = ("wrong_version", "wrong_product", "not_product_material")


class DetachError(ValueError):
    """REGISTRY_V1, MATERIAL_NOT_ATTACHED, LAST_MATERIAL or REASON_INVALID; never a path or a
    name."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def detach(registry: ProductRegistry, knowledge_id: str, reason: str) -> ProductRegistry:
    """The registry with the material taken off its entry; the given registry is not changed."""
    if registry.contract != V2:
        raise DetachError("REGISTRY_V1")
    if reason not in REASONS:
        raise DetachError("REASON_INVALID")
    owner = next(
        (
            product_id
            for product_id, product in registry.products.items()
            if any(m.knowledge_id == knowledge_id for m in product.materials)
        ),
        None,
    )
    if owner is None:
        raise DetachError("MATERIAL_NOT_ATTACHED")
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
    return ProductRegistry.model_validate(current.model_dump())
