"""CanonicalEnvelopeV1 typed 错误（OpenSpec 034）。"""

from __future__ import annotations

from typing import Final

REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        "carriage_return_forbidden",
        "control_char_forbidden",
        "datetime_out_of_range",
        "decimal_not_finite",
        "decimal_out_of_range",
        "float_forbidden",
        "int_out_of_range",
        "invalid_object_type",
        "max_depth_exceeded",
        "naive_datetime",
        "non_nfc_text",
        "non_string_key",
        "reserved_key",
        "surrogate_forbidden",
        "unsupported_type",
    }
)


class CanonicalEncodingError(ValueError):
    """非法输入的确定性拒绝；``reason`` 为冻结的 reason code。"""

    def __init__(self, reason: str, message: str) -> None:
        if reason not in REASON_CODES:
            raise RuntimeError(f"unknown canonical reason code: {reason}")
        super().__init__(f"{reason}: {message}")
        self.reason = reason
