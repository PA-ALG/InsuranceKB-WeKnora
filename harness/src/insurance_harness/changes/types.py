"""Claim-level delta produced before candidate assembly and review routing."""

from dataclasses import dataclass
from enum import StrEnum

from insurance_harness.contracts.compile import ReviewItem
from insurance_harness.contracts.knowledge import Claim


class Verdict(StrEnum):
    UNCHANGED = "unchanged"
    ADD = "add"
    FILL = "fill"
    SUPERSEDE = "supersede"
    REFRESH = "refresh"
    KEEP = "keep"
    CONFLICT = "conflict"
    RETRACT = "retract"
    # A different compiler identity rewrote an unchanged material (S12c-1b): reviewed, not kept.
    UPGRADE = "upgrade"


@dataclass(frozen=True)
class ChangeItem:
    logical_key: str
    verdict: Verdict
    base_slug: str | None
    reason: str


@dataclass(frozen=True)
class ChangeSet:
    """Only the selected product; all collections follow logical-key ordering."""

    items: tuple[ChangeItem, ...]
    members: tuple[Claim, ...]
    removals: tuple[str, ...]
    review_items: tuple[ReviewItem, ...]
