"""文本/值归一化：引文回验与值等价判定共用（spec G2.2 / G4.2）。"""

import re
import unicodedata
from datetime import date

# 枚举同义映射（G4.2）：归一化到 yes/no
_ENUM_SYNONYMS: dict[str, str] = {
    "是": "yes",
    "有": "yes",
    "true": "yes",
    "支持": "yes",
    "否": "no",
    "无": "no",
    "false": "no",
    "不支持": "no",
}

_CN_UNIT: dict[str, float] = {"百": 100, "千": 1_000, "万": 10_000, "亿": 100_000_000}

_DATE_PATTERNS = (
    re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$"),
    re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$"),
    re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日?$"),
    re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})$"),
)


def normalize_text(s: str) -> str:
    """空白全删 + 全角→半角 + 常见中西标点归一，用于子串匹配与字符串比较。"""
    s = unicodedata.normalize("NFKC", s)  # 全角 ASCII 形式（，（）：等）→ 半角
    s = re.sub(r"\s+", "", s)
    # NFKC 不覆盖的中文标点单独归一
    table = {
        ord("。"): ".",
        ord("、"): ",",
        ord("“"): '"',
        ord("”"): '"',
        ord("‘"): "'",
        ord("’"): "'",
        ord("—"): "-",
        ord("【"): "[",
        ord("】"): "]",
    }
    return s.translate(table).lower()


def quote_in_page(quote: str, page_text: str) -> bool:
    q = normalize_text(quote)
    return bool(q) and q in normalize_text(page_text)


def _parse_date(s: str) -> date | None:
    for pat in _DATE_PATTERNS:
        m = pat.match(s.strip())
        if m:
            y, mo, d = (int(g) for g in m.groups())
            try:
                return date(y, mo, d)
            except ValueError:
                return None
    return None


def _parse_number(s: str) -> float | None:
    """解析含中文单位/百分号的数字：``30万`` → 300000，``85%`` → 0.85。"""
    t = normalize_text(s).replace(",", "").replace("元", "").replace("人民币", "")
    m = re.match(r"^(-?\d+(?:\.\d+)?)([百千万亿]*)(%?)$", t)
    if not m:
        return None
    value = float(m.group(1))
    for ch in m.group(2):
        value *= _CN_UNIT[ch]
    if m.group(3):
        value /= 100
    return value


def values_equal(a: str | None, b: str | None) -> bool:
    """金标值 vs 预测值的等价判定（G4.2）：归一化字符串/日期/数字/枚举。"""
    if a is None or b is None:
        return a is None and b is None
    na, nb = normalize_text(a), normalize_text(b)
    if na == nb:
        return True
    if _ENUM_SYNONYMS.get(na) is not None and _ENUM_SYNONYMS.get(na) == _ENUM_SYNONYMS.get(nb):
        return True
    da, db = _parse_date(a), _parse_date(b)
    if da is not None and db is not None:
        return da == db
    fa, fb = _parse_number(a), _parse_number(b)
    if fa is not None and fb is not None:
        return abs(fa - fb) < 1e-9
    return False
