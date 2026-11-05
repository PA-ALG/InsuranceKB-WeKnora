"""Exact page-local ranges for the first numeric table's adjacent marked notes.

Markers and title endings are versioned policy data. This module only interprets layout;
it never normalizes source text, joins pages, or decides which fields may use a range.
"""

import re
from collections.abc import Sequence

_NUMBER = re.compile(r"^[+-]?\d+(?:[.,]\d+)*%?$")
_ITEM = re.compile(r"^\s*(?:\d+[、.．]|[（(][一二三四五六七八九十\d]+[）)])\s*\S")
_HEADING = re.compile(r"^\s*(?:第[一二三四五六七八九十百零\d]+[条章节]|\d+(?:\.\d+)+\s)")
_END = re.compile(r"[。；;！!？?]\s*$")


def numeric_row(line: str) -> bool:
    tokens = line.split()
    return len(tokens) >= 2 and all(_NUMBER.fullmatch(token) for token in tokens)


def note_blocks(
    text: str, markers: Sequence[str], title_endings: Sequence[str]
) -> list[tuple[int, int]]:
    """One contiguous note block, or none when the page/block cannot establish adjacency."""
    if not markers:
        return []
    marker = re.compile(r"^\s*(?:" + "|".join(map(re.escape, markers)) + r")\s*\d*\s*[:：]")
    lines: list[tuple[int, str]] = []
    at = 0
    for line in text.splitlines(keepends=True):
        lines.append((at, line.rstrip("\r\n")))
        at += len(line)
    first = next((i for i, (_, line) in enumerate(lines) if numeric_row(line)), None)
    if first is None:
        return []
    index = first
    while index < len(lines) and numeric_row(lines[index][1]):
        index += 1
    if index == len(lines) or marker.match(lines[index][1]) is None:
        return []
    start = lines[index][0] + len(lines[index][1]) - len(lines[index][1].lstrip())
    end = start
    previous = ""
    content = False
    for position, line in lines[index:]:
        stripped = line.strip()
        if not stripped or numeric_row(line) or _HEADING.match(line):
            break
        marked = marker.match(line)
        if not marked and any(stripped.endswith(ending) for ending in title_endings):
            break
        indented = len(line) > len(line.lstrip())
        if not marked and not _ITEM.match(line) and not indented and _END.search(previous):
            break
        if marked:
            content |= bool(line[marked.end() :].strip())
        else:
            content = True
        end = position + len(line.rstrip())
        previous = line
    return [(start, end)] if content and start < end else []


def restricted_regions(
    ranges: Sequence[tuple[int, int]],
    text: str,
    header: tuple[int, int] | None,
    markers: Sequence[str],
    title_endings: Sequence[str],
) -> list[tuple[int, int, int, str]]:
    """(original block index, start, end, kind); Office blocks establish their own adjacency."""
    out = []
    position = 0
    first_table = None
    for line in text.splitlines(keepends=True):
        if numeric_row(line):
            first_table = position
            break
        position += len(line)
    for index, (a, b) in enumerate(ranges):
        if header is not None and max(a, header[0]) < min(b, header[1]):
            out.append((index, max(a, header[0]), min(b, header[1]), "header"))
        if first_table is not None and a <= first_table < b:
            for first, last in note_blocks(text[a:b], markers, title_endings):
                out.append((index, a + first, a + last, "note"))
    return sorted(out, key=lambda row: row[1])
