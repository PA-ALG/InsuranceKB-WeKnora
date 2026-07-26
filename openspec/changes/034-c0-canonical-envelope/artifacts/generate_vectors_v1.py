"""一次性向量生成脚本（审计用，非生产代码）。

canonical_utf8 字符串为按 25 号规范手工编写的 ground truth，不经由
reference codec 生成；本脚本只做机械工作：按 C0.7 框架从冻结字符串计算
SHA-256 并写出 canonical_vectors_v1.json。实现与向量因此互相独立验证。

运行：python generate_vectors_v1.py <output-path>
"""

from __future__ import annotations

import hashlib
import json
import sys

DOMAIN_SEPARATOR = b"insurancekb.canonical-envelope"
HASH_SCHEMA_VERSION = b"1"


def _hash(object_type: str, canonical_utf8: str) -> str:
    preimage = (
        DOMAIN_SEPARATOR
        + b"\x00"
        + HASH_SCHEMA_VERSION
        + b"\x00"
        + object_type.encode("utf-8")
        + b"\x00"
        + canonical_utf8.encode("utf-8")
    )
    return hashlib.sha256(preimage).hexdigest()


T = "test.object"

# (name, object_type, hand-authored canonical utf-8 string)
VALID: list[tuple[str, str, str]] = [
    ("empty_map", T, "{}"),
    ("empty_list", T, "[]"),
    ("empty_string", T, '""'),
    ("bool_true", T, "true"),
    ("bool_false", T, "false"),
    ("int_zero", T, "0"),
    ("int_negative", T, "-42"),
    ("int_max_safe", T, "9007199254740991"),
    ("int_min_safe", T, "-9007199254740991"),
    ("string_ascii", T, '"hello"'),
    ("string_unicode_nfc", T, '"保险产品é"'),
    ("string_with_lf", T, '"line1\\nline2"'),
    ("string_with_tab", T, '"a\\tb"'),
    ("string_emoji", T, '"😀"'),
    ("map_key_order_utf16", T, '{"😀":1,"！":2}'),
    ("map_nested", T, '{"a":{"x":"v","y":[1,2]},"b":1}'),
    ("list_order_preserved", T, "[2,1,3]"),
    ("set_sorted", T, '{"$set":[1,2,3]}'),
    ("set_dedupe", T, '{"$set":[1,2]}'),
    ("set_mixed", T, '{"$set":["a",2]}'),
    ("decimal_integer", T, '{"$decimal":"1"}'),
    ("decimal_fraction", T, '{"$decimal":"0.5"}'),
    ("decimal_negzero", T, '{"$decimal":"0"}'),
    ("decimal_exponent_input", T, '{"$decimal":"100"}'),
    ("decimal_large", T, '{"$decimal":"12345678901234567890.1"}'),
    ("date_simple", T, '{"$date":"2026-07-26"}'),
    ("datetime_utc", T, '{"$datetime":"2026-07-26T08:00:00Z"}'),
    ("datetime_tz_normalized", T, '{"$datetime":"2026-07-26T12:00:00Z"}'),
    ("datetime_micro_trimmed", T, '{"$datetime":"2026-07-26T12:00:00.12Z"}'),
    ("sentinel_null", T, '{"$s":"null"}'),
    ("sentinel_unknown", T, '{"$s":"unknown"}'),
    ("sentinel_any", T, '{"$s":"any"}'),
    ("sentinel_neg_inf", T, '{"$s":"-inf"}'),
    ("sentinel_pos_inf", T, '{"$s":"+inf"}'),
    ("none_is_null_sentinel", T, '{"$s":"null"}'),
    (
        "composite_claim",
        "claim-revision",
        '{"applicability":{"audience_segment_ids":{"$s":"any"},'
        '"jurisdiction_ids":{"$set":["CN-110000","CN-310000"]}},'
        '"effective_from":{"$date":"2026-01-01"},'
        '"predicate_id":"waiting_period_days","value":90}',
    ),
    ("domain_sep_type_a", "test.type-a", "42"),
    ("domain_sep_type_b", "test.type-b", "42"),
]

# (name, expected reason code)
INVALID: list[tuple[str, str]] = [
    ("float_rejected", "float_forbidden"),
    ("float_nan", "float_forbidden"),
    ("bytes_rejected", "unsupported_type"),
    ("non_nfc_text", "non_nfc_text"),
    ("non_nfc_key", "non_nfc_text"),
    ("carriage_return_text", "carriage_return_forbidden"),
    ("control_char_text", "control_char_forbidden"),
    ("surrogate_text", "surrogate_forbidden"),
    ("int_too_large", "int_out_of_range"),
    ("int_too_small", "int_out_of_range"),
    ("decimal_nan", "decimal_not_finite"),
    ("decimal_infinity", "decimal_not_finite"),
    ("naive_datetime", "naive_datetime"),
    ("non_string_key", "non_string_key"),
    ("reserved_key", "reserved_key"),
    ("deep_nesting", "max_depth_exceeded"),
]


def main() -> None:
    out = {
        "vector_schema": "canonical-vectors-v1",
        "domain_separator": DOMAIN_SEPARATOR.decode("ascii"),
        "hash_schema_version": HASH_SCHEMA_VERSION.decode("ascii"),
        "valid": [
            {
                "name": name,
                "object_type": object_type,
                "canonical_utf8": canonical,
                "sha256": _hash(object_type, canonical),
            }
            for name, object_type, canonical in VALID
        ],
        "invalid": [
            {"name": name, "reason": reason} for name, reason in INVALID
        ],
    }
    with open(sys.argv[1], "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


if __name__ == "__main__":
    main()
