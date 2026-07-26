"""CanonicalEnvelopeV1 值模型：显式 sentinel 与无序集合（OpenSpec 034）。"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from typing import Final


class CanonicalSentinel(enum.Enum):
    """五个互不等价的显式 sentinel（033 §8.4）。"""

    NULL = "null"
    UNKNOWN = "unknown"
    ANY = "any"
    NEG_INFINITY = "-inf"
    POS_INFINITY = "+inf"


class CanonicalSet:
    """无序集合包装：编码时按成员 canonical 字节排序去重。

    与 ``list`` 显式区分语义顺序；成员可为任意受支持值（含 map 等
    不可 hash 值）。
    """

    __slots__ = ("_items",)

    def __init__(self, items: Iterable[object]) -> None:
        self._items: Final[tuple[object, ...]] = tuple(items)

    @property
    def items(self) -> tuple[object, ...]:
        return self._items

    def __repr__(self) -> str:
        return f"CanonicalSet({list(self._items)!r})"
