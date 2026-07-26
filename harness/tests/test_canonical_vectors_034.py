"""034 C0.8: 语言中立向量全等与双向完备（spec C0.8）。"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from decimal import Decimal
from importlib import resources
from typing import Any

import pytest

from insurance_harness.canonical import (
    DOMAIN_SEPARATOR,
    HASH_SCHEMA_VERSION,
    CanonicalEncodingError,
    CanonicalSentinel,
    CanonicalSet,
    canonical_bytes,
    canonical_hash,
)

_UTC = dt.UTC
_CST = dt.timezone(dt.timedelta(hours=8))


def _load_vectors() -> dict[str, Any]:
    ref = resources.files("insurance_harness.canonical").joinpath(
        "vectors/canonical_vectors_v1.json"
    )
    data: dict[str, Any] = json.loads(ref.read_text(encoding="utf-8"))
    return data


_VECTORS = _load_vectors()


def _deep_list(depth: int) -> list[Any]:
    value: list[Any] = []
    for _ in range(depth - 1):
        value = [value]
    return value


VALID_BUILDERS: dict[str, Callable[[], object]] = {
    "empty_map": lambda: {},
    "empty_list": lambda: [],
    "empty_string": lambda: "",
    "bool_true": lambda: True,
    "bool_false": lambda: False,
    "int_zero": lambda: 0,
    "int_negative": lambda: -42,
    "int_max_safe": lambda: 2**53 - 1,
    "int_min_safe": lambda: -(2**53) + 1,
    "string_ascii": lambda: "hello",
    "string_unicode_nfc": lambda: "保险产品é",
    "string_with_lf": lambda: "line1\nline2",
    "string_with_tab": lambda: "a\tb",
    "string_emoji": lambda: "\U0001f600",
    "map_key_order_utf16": lambda: {"！": 2, "\U0001f600": 1},
    "map_nested": lambda: {"b": 1, "a": {"y": [1, 2], "x": "v"}},
    "list_order_preserved": lambda: [2, 1, 3],
    "set_sorted": lambda: CanonicalSet([3, 1, 2]),
    "set_dedupe": lambda: CanonicalSet([1, 1, 2]),
    "set_mixed": lambda: CanonicalSet([2, "a"]),
    "decimal_integer": lambda: Decimal("1.0"),
    "decimal_fraction": lambda: Decimal("0.500"),
    "decimal_negzero": lambda: Decimal("-0"),
    "decimal_exponent_input": lambda: Decimal("1E+2"),
    "decimal_large": lambda: Decimal("12345678901234567890.1"),
    "date_simple": lambda: dt.date(2026, 7, 26),
    "datetime_utc": lambda: dt.datetime(2026, 7, 26, 8, 0, 0, tzinfo=_UTC),
    "datetime_tz_normalized": lambda: dt.datetime(
        2026, 7, 26, 20, 0, 0, tzinfo=_CST
    ),
    "datetime_micro_trimmed": lambda: dt.datetime(
        2026, 7, 26, 12, 0, 0, 120000, tzinfo=_UTC
    ),
    "sentinel_null": lambda: CanonicalSentinel.NULL,
    "sentinel_unknown": lambda: CanonicalSentinel.UNKNOWN,
    "sentinel_any": lambda: CanonicalSentinel.ANY,
    "sentinel_neg_inf": lambda: CanonicalSentinel.NEG_INFINITY,
    "sentinel_pos_inf": lambda: CanonicalSentinel.POS_INFINITY,
    "none_is_null_sentinel": lambda: None,
    "composite_claim": lambda: {
        "predicate_id": "waiting_period_days",
        "value": 90,
        "effective_from": dt.date(2026, 1, 1),
        "applicability": {
            "jurisdiction_ids": CanonicalSet(["CN-310000", "CN-110000"]),
            "audience_segment_ids": CanonicalSentinel.ANY,
        },
    },
    "money_as_schema_map": lambda: {
        "currency": "CNY",
        "amount": Decimal("199.90"),
    },
    "depth_100": lambda: _deep_list(100),
    "domain_sep_type_a": lambda: 42,
    "domain_sep_type_b": lambda: 42,
}

INVALID_BUILDERS: dict[str, Callable[[], object]] = {
    "float_rejected": lambda: 1.5,
    "float_nan": lambda: float("nan"),
    "bytes_rejected": lambda: b"raw",
    "non_nfc_text": lambda: "é",
    "non_nfc_key": lambda: {"é": 1},
    "carriage_return_text": lambda: "a\r\nb",
    "control_char_text": lambda: "a\x00b",
    "surrogate_text": lambda: "\ud800",
    "int_too_large": lambda: 2**53,
    "int_too_small": lambda: -(2**53),
    "decimal_nan": lambda: Decimal("NaN"),
    "decimal_infinity": lambda: Decimal("Infinity"),
    "naive_datetime": lambda: dt.datetime(2026, 7, 26, 8, 0, 0),
    "non_string_key": lambda: {1: "a"},
    "reserved_key": lambda: {"$x": 1},
    "deep_nesting": lambda: _deep_list(101),
    "datetime_out_of_range": lambda: dt.datetime.min.replace(
        tzinfo=dt.timezone(dt.timedelta(hours=5))
    ),
    "decimal_out_of_range": lambda: Decimal("1E+101"),
}

HASH_INVALID_BUILDERS: dict[str, Callable[[], tuple[str, object]]] = {
    "invalid_object_type": lambda: ("bad\x00type", 1),
}


def test_vector_file_header_matches_package_constants() -> None:
    assert _VECTORS["vector_schema"] == "canonical-vectors-v1"
    assert _VECTORS["domain_separator"].encode("ascii") == DOMAIN_SEPARATOR
    assert _VECTORS["hash_schema_version"] == HASH_SCHEMA_VERSION


def test_builders_cover_all_vectors_bidirectionally() -> None:
    valid_names = {case["name"] for case in _VECTORS["valid"]}
    invalid_names = {case["name"] for case in _VECTORS["invalid"]}
    assert valid_names == set(VALID_BUILDERS)
    assert invalid_names == set(INVALID_BUILDERS) | set(HASH_INVALID_BUILDERS)


@pytest.mark.parametrize(
    "case",
    _VECTORS["valid"],
    ids=[case["name"] for case in _VECTORS["valid"]],
)
def test_valid_vector_bytes_and_hash(case: dict[str, str]) -> None:
    value = VALID_BUILDERS[case["name"]]()
    encoded = canonical_bytes(value)
    assert encoded == case["canonical_utf8"].encode("utf-8")
    assert canonical_hash(case["object_type"], value) == case["sha256"]


@pytest.mark.parametrize(
    "case",
    _VECTORS["invalid"],
    ids=[case["name"] for case in _VECTORS["invalid"]],
)
def test_invalid_vector_rejected_with_exact_reason(
    case: dict[str, str],
) -> None:
    with pytest.raises(CanonicalEncodingError) as excinfo:
        if case.get("level") == "hash":
            object_type, value = HASH_INVALID_BUILDERS[case["name"]]()
            canonical_hash(object_type, value)
        else:
            canonical_bytes(INVALID_BUILDERS[case["name"]]())
    assert excinfo.value.reason == case["reason"]


def test_domain_separation_vectors_share_bytes_but_not_hash() -> None:
    by_name = {case["name"]: case for case in _VECTORS["valid"]}
    type_a = by_name["domain_sep_type_a"]
    type_b = by_name["domain_sep_type_b"]
    assert type_a["canonical_utf8"] == type_b["canonical_utf8"]
    assert type_a["sha256"] != type_b["sha256"]
