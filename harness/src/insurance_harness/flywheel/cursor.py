"""F1.1a 增量游标：只处理游标之后的新 trace，重跑不重复处理同一 trace。

游标 = 已处理 trace 的最大 (timestamp, trace_id)。时序按 **timezone-aware UTC 实际
时刻**比较（无时区视为 UTC），不按裸字符串（codex PR#18 阻断2：混合时区/格式下
字符串序错误）；同 timestamp 以 trace_id 决胜，稳定。同批内同 trace_id 去重（保留
最新时间戳一条），杜绝重复计数入口。游标编码为 UTC 归一化 `<ts>Z|<trace_id>`。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from .models import Trace


def _parse_ts(ts: str) -> datetime:
    """ISO8601 → aware UTC（无时区视为 UTC）；Trace 构造期已校验可解析。"""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _key(t: Trace) -> tuple[datetime, str]:
    return (_parse_ts(t.timestamp), t.trace_id)


def _encode(key: tuple[datetime, str]) -> str:
    ts = key[0].isoformat().replace("+00:00", "Z")
    return f"{ts}|{key[1]}"


def _decode(cursor: str) -> tuple[datetime, str]:
    ts, _, tid = cursor.partition("|")
    return (_parse_ts(ts), tid)


def _dedupe(traces: Iterable[Trace]) -> list[Trace]:
    """同批同 trace_id 去重：保留最新 (timestamp, trace_id) 一条。"""
    latest: dict[str, Trace] = {}
    for t in traces:
        kept = latest.get(t.trace_id)
        if kept is None or _key(t) > _key(kept):
            latest[t.trace_id] = t
    return list(latest.values())


def new_traces(traces: Iterable[Trace], cursor: str | None) -> list[Trace]:
    """去重后返回严格晚于 cursor 的 trace（按 UTC (timestamp,trace_id) 升序，幂等）。"""
    ordered = sorted(_dedupe(traces), key=_key)
    if cursor is None:
        return ordered
    cur = _decode(cursor)
    return [t for t in ordered if _key(t) > cur]


def next_cursor(traces: Sequence[Trace], previous: str | None = None) -> str | None:
    """处理完这批后应持久化的新游标（最大 (timestamp,trace_id)）；语义比较，不回退。"""
    if not traces:
        return previous
    batch_max = max(_key(t) for t in traces)
    if previous is not None and _decode(previous) >= batch_max:
        return previous  # 游标单调不回退
    return _encode(batch_max)
