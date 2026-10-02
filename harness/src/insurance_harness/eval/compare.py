"""Deterministic value comparison with auditable missing and forbidden atoms.

Normalization is ported from goldenset/normalize.py; remove those legacy
originals when goldenset/ retires in S7. No legacy module is imported here.
"""

from pydantic import BaseModel, Field

from insurance_harness.eval.golden import GoldenItem
from insurance_harness.eval.normalize import normalize_text, values_equal


class ValueComparison(BaseModel):
    correct: bool
    component_misses: list[str] = Field(default_factory=list)
    forbidden_hits: list[str] = Field(default_factory=list)


def compare_value(golden: GoldenItem, value: str | None) -> ValueComparison:
    """Require every component (or equivalent value), with forbidden terms vetoing."""
    normalized = normalize_text(value) if value is not None else ""
    misses = [
        component.name for component in golden.components
        if not any(normalize_text(accepted) in normalized for accepted in component.accepted)
    ]
    forbidden = [term for term in golden.forbidden if normalize_text(term) in normalized]
    matches = not misses if golden.components else values_equal(golden.value, value)
    return ValueComparison(
        correct=value is not None and matches and not forbidden,
        component_misses=misses,
        forbidden_hits=forbidden,
    )
