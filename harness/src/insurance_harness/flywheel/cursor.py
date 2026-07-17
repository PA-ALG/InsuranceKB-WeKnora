"""F1.1 增量游标：只处理游标之后的新 trace，重跑不重复处理同一 trace。

游标 = 已处理 trace 的最大 (timestamp, trace_id)。严格按此二元组排序，避免同
timestamp 多 trace 时漏处理或重处理（timestamp 相等以 trace_id 决胜，稳定）。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .models import Trace


def _key(t: Trace) -> tuple[str, str]:
    return (t.timestamp, t.trace_id)


def _encode(key: tuple[str, str]) -> str:
    return f"{key[0]}|{key[1]}"


def _decode(cursor: str) -> tuple[str, str]:
    ts, _, tid = cursor.partition("|")
    return (ts, tid)


def new_traces(traces: Iterable[Trace], cursor: str | None) -> list[Trace]:
    """返回严格晚于 cursor 的 trace（按 (timestamp,trace_id) 升序，重跑幂等）。"""
    ordered = sorted(traces, key=_key)
    if cursor is None:
        return ordered
    cur = _decode(cursor)
    return [t for t in ordered if _key(t) > cur]


def next_cursor(traces: Sequence[Trace], previous: str | None = None) -> str | None:
    """处理完这批后应持久化的新游标（最大 (timestamp,trace_id)）；不回退。"""
    if not traces:
        return previous
    enc = _encode(max(_key(t) for t in traces))
    if previous is not None and previous >= enc:
        return previous  # 游标单调不回退
    return enc
