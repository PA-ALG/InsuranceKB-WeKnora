"""Withdrawing one method: suppressed in the registry, its members out of Active (SK-2b Spec §6).

A person withdraws a method (SK-0 §3.4): its entry is kept, marked suppressed, so no later compile
brings it back; and one candidate removes exactly that method's published Claims and entity, for
people to decide on the platform. Nothing else in Active is touched.
"""

from dataclasses import dataclass
from typing import Any

from insurance_harness.bundle.assemble import assemble
from insurance_harness.bundle.client import Release
from insurance_harness.catalog.method_cards import load_method_cards
from insurance_harness.compilers.methods.claims import COMPILER, compiler_version
from insurance_harness.compilers.methods.compile import published_members
from insurance_harness.contracts.bundle import CandidateBundle, ReviewPlan
from insurance_harness.contracts.enums import ReviewMode
from insurance_harness.ingest.registry import V2, ProductRegistry


class WithdrawError(ValueError):
    """METHOD_UNKNOWN or REGISTRY_NOT_V2; never a name."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Withdrawal:
    registry: ProductRegistry  # with the entry suppressed; the given registry is not changed
    bundle: CandidateBundle | None  # None when Active holds nothing of the method
    report: dict[str, Any]  # codes and counts only


def withdraw_method(
    registry: ProductRegistry, method_id: str, active: Release | None
) -> Withdrawal:
    if registry.contract != V2:
        raise WithdrawError("REGISTRY_NOT_V2")
    if not any(method.method_id == method_id for method in registry.methods):
        raise WithdrawError("METHOD_UNKNOWN")
    methods = [
        method.model_copy(update={"suppressed": True}) if method.method_id == method_id else method
        for method in registry.methods
    ]
    updated = ProductRegistry.model_validate_json(
        registry.model_copy(update={"methods": methods}).model_dump_json()
    )
    removals = sorted(published_members(active, method_id))
    bundle = None
    if removals:
        bundle = assemble(
            [],
            compiler_identity=f"{COMPILER}@{compiler_version(load_method_cards())}",
            base=active.head if active else None,
            review_plan=[ReviewPlan(mode=ReviewMode.HUMAN, policy_ref=None)],
            removals=removals,
        )
    report = {"method_id": method_id, "removals": len(removals), "no_changes": bundle is None}
    return Withdrawal(updated, bundle, report)
