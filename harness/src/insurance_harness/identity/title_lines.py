"""Title lines printed anywhere on a material's first pages (S5b-7 Spec §2.3).

Extraction follows the PDF content stream, not the page as it looks: rate tables draw
their title (《<product>》年交费率表) after the table, so it lands at the end of page 1,
and a title can be split over two lines (《<product>》, then 产品说明书). A title line is a
whole line, never a phrase inside a sentence: a body citing 《another product》 is not a title.
"""

import re
from collections.abc import Callable

_LINE_BREAKS = re.compile(r"[\r\n]+")
_BRACKETED = re.compile(r"^《[^《》]+》$")


def line_titles(head: str, pattern: str, fold: Callable[[str], str]) -> dict[str, str]:
    """The title lines in `head`: each distinct name with the first whole line that carries it.

    `pattern` is matched against each whole folded line and has one group, the name. A line that is
    only a bracketed name is read together with the next non-empty line (a title split in two).
    """
    title = re.compile(pattern)
    lines = [line for line in (fold(part) for part in _LINE_BREAKS.split(head)) if line]
    found: dict[str, str] = {}
    for index, line in enumerate(lines):
        whole = line
        match = title.fullmatch(whole)
        if match is None and _BRACKETED.match(line) and index + 1 < len(lines):
            whole = line + lines[index + 1]
            match = title.fullmatch(whole)
        if match is not None:
            found.setdefault(match.group(1), whole)
    return found
