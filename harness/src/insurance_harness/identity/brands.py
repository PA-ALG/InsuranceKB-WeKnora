"""A product's brand core and the materials that name only a brand (S11c Spec §2.5).

Sales and training materials, and Office files of no recognised role, often print only a brand.
The brand core of a registered name is also its product family (PV-0 §3.3): data for grouping and
candidates, never an attribution anchor.
"""

import re
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from insurance_harness.identity.text import fold

if TYPE_CHECKING:  # the attribution module imports this one
    from insurance_harness.identity.attribution import (
        AttributionPolicy,
        RegisteredProduct,
        Upload,
    )

_QUALIFIER = re.compile(r"\([^()]*\)")  # after NFKC, as in 年金保险(分红型) or 意外(A款)医疗保险


def unqualified(name: str) -> str:
    """A name without its parenthesised qualifiers, nested ones included."""
    while (stripped := _QUALIFIER.sub("", name)) != name:
        name = stripped
    return name


def brand_core(name: str, policy: "AttributionPolicy", *, casefold: bool = True) -> str:
    """A registered name's brand core: no company or rider prefix, qualifier or type suffix."""
    core = fold(name)
    core = core.casefold() if casefold else core
    prefixes = [fold(prefix) for prefix in policy.brand_prefixes]
    while prefix := next((p for p in prefixes if core.casefold().startswith(p.casefold())), ""):
        core = core[len(prefix) :]  # repeatedly, as in 平安附加…
    core = unqualified(core)
    suffixes = [fold(entry.suffix) for entry in policy.classifications]
    ends = [s for s in suffixes if core.casefold().endswith(s.casefold())]
    found = max(ends, key=len, default="")
    return core[: len(core) - len(found)]


def years(text: str, patterns: Sequence[str]) -> set[str]:
    """The two-digit years the patterns find (each pattern has one group)."""
    return {match.group(1) for pattern in patterns for match in re.finditer(pattern, text)}


def brand_hits(
    file_name: str,
    window: str,
    products: Sequence["RegisteredProduct"],
    policy: "AttributionPolicy",
) -> dict[str, str]:
    """Each product whose brand the material's file name or opening carries, with the brand
    prefix it matched (the brand core's first brand_min_chars characters, casefolded)."""
    text = (fold(PurePosixPath(file_name).stem) + "\n" + window).casefold()
    hits: dict[str, str] = {}
    for product in products:
        for brand in sorted({brand_core(name, policy) for name in product.names}):
            prefix = brand[: policy.brand_min_chars]
            if len(brand) >= policy.brand_min_chars and prefix in text:
                hits[product.product_id] = prefix
                break
    return hits


def brand_candidates(
    upload: "Upload",
    window: str,
    products: Sequence["RegisteredProduct"],
    policy: "AttributionPolicy",
) -> list[str]:
    """Products whose brand the material's file name or opening carries (S11c Spec §2.5).

    A brand matches by its first brand_min_chars characters: registered names add type words the
    materials leave out (…养老, …长期). A year the material carries keeps the products of that
    year, when any; more than brand_max_candidates candidates are no candidates at all.
    """
    hits = brand_hits(upload.file_name, window, products, policy)
    found = [product for product in products if product.product_id in hits]
    text = (fold(PurePosixPath(upload.file_name).stem) + "\n" + window).casefold()
    wanted = years(text, (policy.upload_year_pattern,))
    dated = [
        p
        for p in found
        if wanted & years(" ".join(fold(n) for n in p.names), policy.product_year_patterns)
    ]
    chosen = dated or found
    if len(chosen) > policy.brand_max_candidates:
        return []
    return sorted(p.product_id for p in chosen)
