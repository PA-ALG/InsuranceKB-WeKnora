"""Exact Unicode occurrences; callers own source binding and ambiguity policy."""

from collections.abc import Iterable


def exact_quote_occurrences(
    text: str, quote: str, spans: Iterable[tuple[int, int]]
) -> tuple[int, ...]:
    """Enumerate overlapping exact matches inside offered spans, without normalization."""
    if not quote:
        raise ValueError("empty evidence quote")
    starts: set[int] = set()
    for start, end in spans:
        if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(text):
            raise ValueError("invalid evidence search span")
        cursor = start
        while True:
            position = text.find(quote, cursor, end)
            if position < 0:
                break
            starts.add(position)
            cursor = position + 1
    return tuple(sorted(starts))
