"""Product information inside a method: a signal that people review it (Spec §4.5; SK-0 §3.2).

An amount, a percentage, an age or a registered product name in a method's value is not judged
right or wrong here. It only means the method never goes live unattended: a training script may
well quote a product's numbers, and those stay verbatim, dated by their source, with the notice
that the terms and the published product knowledge prevail.
"""

import re
from collections.abc import Sequence

from insurance_harness.catalog.method_cards import MethodCards
from insurance_harness.identity.text import fold

PRODUCT_NAME_MIN_CHARS = 4  # a shorter name ("智盈") is part of too many ordinary words
NOTICE = {"notice": "product_info"}  # the method entity's flag for SK-3's notice


def product_signals(text: str, cards: MethodCards, product_names: Sequence[str]) -> frozenset[str]:
    """The kinds of product information `text` shows, compared folded (width, white space)."""
    folded = fold(text)
    found: set[str] = {
        p.signal for p in cards.product_info_patterns if re.search(p.pattern, folded)
    }
    names = (fold(name) for name in product_names)
    if any(len(name) >= PRODUCT_NAME_MIN_CHARS and name in folded for name in names):
        found.add("product")
    return frozenset(found)
