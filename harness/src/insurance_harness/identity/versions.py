"""Which filed version a clause code names, given the pinned version catalog (PV-0 appendix A §1.3).

The internal ID of a created entry is derived from the clause code, so a code that several filed
versions share can never tell them apart: it is quarantined before anything is created, whatever
the registry holds. A version key and a code that point at different entries are a conflict; two
entries are never merged.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from insurance_harness.identity.text import fold

if TYPE_CHECKING:  # the attribution module imports this one
    from insurance_harness.identity.attribution import RegisteredProduct


class VersionIndex(Protocol):
    """The pinned catalog as attribution sees it: the version keys a canonical code names."""

    def keys_for(self, clause_code: str) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class VersionMatch:
    kind: Literal["registered", "new", "conflict", "shared"]
    product_id: str | None = None  # the registered entry ("registered")
    version_key: str | None = None  # K, when the catalog names exactly one version
    by_key: bool = False  # found through its version key, not its clause codes


def normal_clause_code(text: str) -> str:
    """The one form clause codes are compared in, wherever they come from (PV-1 §2.2): folded,
    ASCII brackets as 〔〕. The registry keeps the value as it was confirmed."""
    return fold(text).replace("[", "〔").replace("]", "〕")


def canonical_clause_code(text: str, pattern: str) -> str | None:
    """The compared form, when it is a clause filing code as a whole (catalog and migration)."""
    code = normal_clause_code(text)
    return code if re.fullmatch(pattern, code) else None


def match_version(
    code: str,
    products: Sequence["RegisteredProduct"],
    index: VersionIndex,
    pattern: str,
) -> VersionMatch:
    """The ordered table of PV-0 appendix A §1.3, first row that applies."""
    keys = index.keys_for(code)
    key = keys[0] if len(keys) == 1 else None
    holders = [
        p.product_id for p in products if code in {normal_clause_code(c) for c in p.clause_codes}
    ]
    keyed = [p.product_id for p in products if key is not None and p.version_key == key]
    if keyed:  # rows 1 and 2
        if set(holders) <= {keyed[0]}:
            return VersionMatch("registered", keyed[0], key, by_key=keyed[0] not in holders)
        return VersionMatch("conflict")
    if len(keys) > 1:  # row 3: a shared code never names one version
        return VersionMatch("shared")
    if len(holders) > 1:  # row 4
        return VersionMatch("conflict")
    if holders:  # row 5
        holder = next(p for p in products if p.product_id == holders[0])
        if key is not None and holder.version_key not in (None, key):
            return VersionMatch("conflict")
        return VersionMatch("registered", holders[0], key)
    return VersionMatch("new", version_key=key)  # row 6
