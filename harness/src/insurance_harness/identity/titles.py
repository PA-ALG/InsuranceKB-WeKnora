"""Reading a material's own title and code from its opening (S5b-1, S5b-5, S5b-7 Specs).

Moved unchanged out of the attribution module (PV-3) so that it stays a deep module under the
500-line limit; the rules are the attribution policy's data.
"""

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

from insurance_harness.identity.text import fold

if TYPE_CHECKING:  # the attribution module imports this one
    from insurance_harness.identity.attribution import AttributionPolicy, RegisteredProduct


def title_of(text: str, policy: "AttributionPolicy") -> str:
    """The product name a title starts with, or "" when it cannot be read."""
    left, right = (fold(mark) for mark in policy.title_brackets)
    if text.startswith(left):
        end = text.find(right, len(left))
        name = text[len(left) : end] if end > 0 else ""
        after = text[end + len(right) : end + len(right) + 4] if end > 0 else ""
        if any(fold(word) in after for word in policy.title_line_exclusions):
            return ""  # 《name》不适用…, 《name》并非…: an explanation, not a title (S5b-7)
    else:
        # A marker at the very start counts: then there is no title, and the body is never one.
        ends = [i for i in (text.find(fold(mark)) for mark in policy.title_end_markers) if i >= 0]
        name = text[: min(ends)] if ends else ""
    return name if len(name) <= policy.max_title_chars else ""


def head_title(window: str, own_code: str | None, policy: "AttributionPolicy") -> str:
    """The title at the start, after page numbers, labels, the insurer's name and the terms' own
    code line."""
    text = window
    issuers = [fold(name) for name in policy.issuer_names]
    while (stripped := _strip_prefix(text, policy.title_prefix_pattern, issuers)) != text:
        text = stripped  # page numbers, labels and the insurer may come together, in any order
    if own_code is not None and text.startswith(own_code):
        text = text[len(own_code) :]
        text = text.removeprefix(fold(policy.own_code_marker))
    return title_of(text, policy)


def _strip_prefix(text: str, pattern: str, issuers: Sequence[str]) -> str:
    issuer = next((name for name in issuers if text.startswith(name)), "")
    return text[len(issuer) :] if issuer else re.sub(pattern, "", text, count=1)


def guide_title(head: str, policy: "AttributionPolicy") -> str:
    """The product the reader guide introduces ("阅读指引<name>产品提供…"), or "".

    Only a fallback for terms whose start carries no title, and it fails closed (S5b-5 §2.2): one
    guide must start near the start, every guide must name the same product, and the name must
    carry no code, verification line or end word, which extraction mixes in when it garbles.
    """
    matches = list(re.finditer(policy.guide_title_pattern, head))
    if not any(match.start() < policy.anchor_chars for match in matches):
        return ""
    names = {match.group(1) for match in matches}
    if len(names) != 1:
        return ""
    name = names.pop()
    polluted = (
        re.search(policy.clause_code_pattern, name)
        or fold(policy.own_code_marker) in name
        or any(fold(marker) in name for marker in policy.title_end_markers)
    )
    return "" if polluted or not name or len(name) > policy.max_title_chars else name


def own_codes(head: str, policy: "AttributionPolicy") -> set[str]:
    """Codes printed with the verification line that follows a terms' own code (S5b-5)."""
    marked = f"({policy.clause_code_pattern}){re.escape(fold(policy.own_code_marker))}"
    return {match.group(1) for match in re.finditer(marked, head)}


def named_inside(title: str, products: Sequence["RegisteredProduct"]) -> list["RegisteredProduct"]:
    """Two or more products whose names appear in a title, none inside a longer appearance."""
    spans = []
    for product in products:
        for name in {fold(n) for n in product.names}:
            start = title.find(name)
            while start >= 0:
                spans.append((start, start + len(name), product))
                start = title.find(name, start + 1)
    whole = [
        span
        for span in spans
        if not any(
            o[0] <= span[0] and span[1] <= o[1] and o[1] - o[0] > span[1] - span[0] for o in spans
        )
    ]
    found = {span[2].product_id: span[2] for span in whole}
    return [found[key] for key in sorted(found)] if len(found) > 1 else []
