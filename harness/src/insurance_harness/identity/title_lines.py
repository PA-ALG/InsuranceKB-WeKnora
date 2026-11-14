"""Title lines printed anywhere on a material's first pages (S5b-7 Spec §2.3).

Extraction follows the PDF content stream, not the page as it looks: rate tables draw
their title (《<product>》年交费率表) after the table, so it lands at the end of page 1,
and a title can be split over two lines (《<product>》, then 产品说明书). A title line is a
whole line, never a phrase inside a sentence: a body citing 《another product》 is not a title.
"""

import re
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from insurance_harness.identity.text import fold

if TYPE_CHECKING:
    from insurance_harness.identity.attribution import AttributionPolicy

_LINE_BREAKS = re.compile(r"[\r\n]+")
_BRACKETED = re.compile(r"^《[^《》]+》$")
# Folded sentence punctuation and quotes, and 的: a part that explains the product (《name》的续保…,
# 《name》以外的…) is never its title (S5b-7 review R1).
_NOT_IN_PART = ",.;:!?。、“”\"'的"


def title_pattern(qualifier_chars: int, documents: Sequence[str], max_name: int) -> str:
    """《name》, a short plan part (no brackets, sentence punctuation or 的), a document word.

    PB-A1: the plan part was a closed list of qualifiers (年交, 基本保险, …); rate tables also
    print parts such as 客运列车意外基本部分 or 基本部分(基础)年交, so only its length and
    characters count.
    The same kind of part may follow the document word in brackets: 费率表(年交).
    """
    words = "|".join(re.escape(word) for word in sorted(documents, key=len, reverse=True))
    part = f"[^《》{re.escape(_NOT_IN_PART)}]{{0,{qualifier_chars}}}"
    mode = rf"(?:\([^《》(){re.escape(_NOT_IN_PART)}]{{1,{qualifier_chars}}}\))?"
    return f"^《([^《》]{{1,{max_name}}})》{part}(?:{words}){mode}$"


def line_titles(
    head: str, pattern: str, exclusions: Sequence[str], fold: Callable[[str], str]
) -> dict[str, str]:
    """The title lines in `head`: each distinct name with the first whole line that carries it.

    `pattern` is matched against each whole folded line and has one group, the name. A line that is
    only a bracketed name is read together with the next non-empty line (a title split in two). A
    line carrying an exclusion (an explanation or a negation) is never a title.
    """
    title = re.compile(pattern)
    excluded = [fold(word) for word in exclusions]
    lines = [line for line in (fold(part) for part in _LINE_BREAKS.split(head)) if line]
    found: dict[str, str] = {}
    for index, line in enumerate(lines):
        whole = line
        match = title.fullmatch(whole)
        if match is None and _BRACKETED.match(line) and index + 1 < len(lines):
            whole = line + lines[index + 1]
            match = title.fullmatch(whole)
        if match is not None and not any(word in whole for word in excluded):
            found.setdefault(match.group(1), whole)
    return found


def registered_rate_titles(
    head: str, names: Sequence[str], policy: "AttributionPolicy"
) -> tuple[dict[str, str], bool]:
    """Exact unbracketed rate-title lines, or an ambiguous registered-name prefix (PB-A2).

    The caller supplies only the first two pages and only after the original anchors failed.
    Split before folding: neither adjacent lines nor page boundaries may complete a name.
    Reuse the bracketed suffix grammar, but reject a qualifier starting with parentheses:
    it may be an unregistered name extension. Never pick the longest registered prefix.
    """
    pattern = re.compile(title_pattern(
        policy.title_line_qualifier_chars,
        [fold(word) for word in policy.unbracketed_rate_documents],
        policy.max_title_chars,
    ))
    registered = {fold(name) for name in names if fold(name)}
    excluded = [fold(word) for word in policy.title_line_exclusions]
    found: dict[str, str] = {}
    for part in head.splitlines():
        whole = fold(part)
        if any(word in whole for word in excluded):
            continue
        prefixes = {name for name in registered if whole.startswith(name)}
        valid = [
            name for name in prefixes
            if not whole[len(name):].startswith("(")
            and pattern.fullmatch(f"《{name}》{whole[len(name):]}")
        ]
        if valid and len(prefixes) > 1:
            return {}, True
        for name in valid:
            found.setdefault(name, whole)
    return found, False
