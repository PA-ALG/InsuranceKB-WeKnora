"""F1.3 PII 脱敏：问题原文入库前遮蔽手机/证件/保单号（原文不落库，只留 trace_id）。"""

from __future__ import annotations

import re
from typing import Final

_MASK: Final[str] = "[已遮蔽]"
#: 18 位身份证（末位可 X），须在手机之前遮蔽（避免 11 位手机规则咬进证件号中段）。
_ID_CARD: Final[re.Pattern[str]] = re.compile(r"\d{17}[\dXx]")
#: 中国大陆手机号：1 + [3-9] + 9 位。
_PHONE: Final[re.Pattern[str]] = re.compile(r"1[3-9]\d{9}")
#: 保单号：≥10 位连续数字（手机/证件已先遮，剩余长数字串视作保单号；
#: 业务数字如 90 天、5.3 条位数少不受影响）。
_POLICY: Final[re.Pattern[str]] = re.compile(r"\d{10,}")


def redact_pii(text: str) -> str:
    """遮蔽文本中的手机号、身份证号、保单号；返回脱敏后文本。

    顺序：证件（18 位）→ 手机（11 位）→ 保单（残留长数字串）；短业务数字保留。
    """
    text = _ID_CARD.sub(_MASK, text)
    text = _PHONE.sub(_MASK, text)
    text = _POLICY.sub(_MASK, text)
    return text
