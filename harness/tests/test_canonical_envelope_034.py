"""034 C0.1–C0.9 单元验收（spec 034-c0-canonical-envelope）。"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

import insurance_harness.canonical as canonical_pkg
from insurance_harness.canonical import (
    CanonicalEncodingError,
    CanonicalSentinel,
    CanonicalSet,
    canonical_bytes,
    canonical_hash,
)

_UTC = dt.UTC


def _reason(value: object) -> str:
    with pytest.raises(CanonicalEncodingError) as excinfo:
        canonical_bytes(value)
    return excinfo.value.reason


class TestDeterminismAndTypes:
    def test_encoding_is_deterministic(self) -> None:
        value = {"k": [1, "x", CanonicalSet(["b", "a"])], "d": Decimal("2.50")}
        assert canonical_bytes(value) == canonical_bytes(value)

    def test_bool_is_not_int(self) -> None:
        assert canonical_bytes(True) == b"true"
        assert canonical_bytes(1) == b"1"

    def test_tuple_encodes_like_list(self) -> None:
        assert canonical_bytes((1, 2)) == canonical_bytes([1, 2])

    def test_python_set_encodes_like_canonical_set(self) -> None:
        assert canonical_bytes({3, 1, 2}) == canonical_bytes(
            CanonicalSet([1, 2, 3])
        )
        assert canonical_bytes(frozenset({1})) == b'{"$set":[1]}'

    def test_unsupported_type_rejected(self) -> None:
        assert _reason(object()) == "unsupported_type"

    def test_nested_invalid_rejected_at_any_depth(self) -> None:
        assert _reason({"a": [{"b": [1.5]}]}) == "float_forbidden"


class TestTextRules:
    def test_lf_and_tab_allowed(self) -> None:
        assert canonical_bytes("a\n\tb") == b'"a\\n\\tb"'

    def test_other_c0_controls_rejected(self) -> None:
        assert _reason("a\x0bb") == "control_char_forbidden"
        assert _reason("a\rb") == "carriage_return_forbidden"

    def test_key_text_rules_apply(self) -> None:
        assert _reason({"a\rb": 1}) == "carriage_return_forbidden"


class TestNumbers:
    def test_safe_int_bounds_inclusive(self) -> None:
        assert canonical_bytes(2**53 - 1) == b"9007199254740991"
        assert canonical_bytes(-(2**53) + 1) == b"-9007199254740991"

    def test_decimal_scientific_input_normalized(self) -> None:
        assert canonical_bytes(Decimal("1.2E+3")) == b'{"$decimal":"1200"}'
        assert canonical_bytes(Decimal("0E-10")) == b'{"$decimal":"0"}'

    def test_decimal_negative_kept(self) -> None:
        assert canonical_bytes(Decimal("-1.10")) == b'{"$decimal":"-1.1"}'


class TestDatetime:
    def test_datetime_seconds_only(self) -> None:
        value = dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=_UTC)
        assert (
            canonical_bytes(value) == b'{"$datetime":"2026-01-02T03:04:05Z"}'
        )

    def test_datetime_full_microseconds(self) -> None:
        value = dt.datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=_UTC)
        assert (
            canonical_bytes(value)
            == b'{"$datetime":"2026-01-02T03:04:05.123456Z"}'
        )


class TestSentinels:
    def test_five_sentinels_pairwise_distinct(self) -> None:
        encodings = {
            canonical_bytes(sentinel) for sentinel in CanonicalSentinel
        }
        hashes = {
            canonical_hash("test.object", sentinel)
            for sentinel in CanonicalSentinel
        }
        assert len(encodings) == 5
        assert len(hashes) == 5

    def test_none_equals_null_sentinel(self) -> None:
        assert canonical_bytes(None) == canonical_bytes(
            CanonicalSentinel.NULL
        )


class TestMapAndSetOrdering:
    def test_utf16_key_order_not_codepoint_order(self) -> None:
        encoded = canonical_bytes({"！": 2, "\U0001f600": 1})
        assert encoded == '{"\U0001f600":1,"！":2}'.encode()

    def test_set_of_maps_sorted_by_canonical_bytes(self) -> None:
        encoded = canonical_bytes(CanonicalSet([{"b": 1}, {"a": 1}]))
        assert encoded == b'{"$set":[{"a":1},{"b":1}]}'

    def test_reserved_key_rejected_anywhere(self) -> None:
        assert _reason({"outer": {"$inner": 1}}) == "reserved_key"


class TestDepthLimit:
    def test_depth_100_accepted(self) -> None:
        value: list[object] = []
        for _ in range(99):
            value = [value]
        assert canonical_bytes(value)

    def test_depth_101_rejected_without_recursion_error(self) -> None:
        value: list[object] = []
        for _ in range(100):
            value = [value]
        assert _reason(value) == "max_depth_exceeded"


class TestHashContract:
    def test_hash_is_64_hex_lowercase(self) -> None:
        digest = canonical_hash("test.object", {"a": 1})
        assert len(digest) == 64
        assert digest == digest.lower()
        int(digest, 16)

    @pytest.mark.parametrize(
        "object_type",
        ["", "UPPER", "with space", "类型", "a" * 65, "1leading-digit"],
    )
    def test_invalid_object_type_rejected(self, object_type: str) -> None:
        with pytest.raises(CanonicalEncodingError) as excinfo:
            canonical_hash(object_type, 1)
        assert excinfo.value.reason == "invalid_object_type"

    def test_valid_object_type_grammar(self) -> None:
        assert canonical_hash("claim-revision.v1_x", 1)


class TestPurity:
    def test_package_has_no_internal_harness_imports(self) -> None:
        package_dir = Path(canonical_pkg.__file__).parent
        for source in package_dir.glob("*.py"):
            text = source.read_text(encoding="utf-8")
            assert "from insurance_harness." not in text.replace(
                "from insurance_harness.canonical", ""
            ), source.name
            assert "import insurance_harness" not in text.replace(
                "import insurance_harness.canonical", ""
            ), source.name
